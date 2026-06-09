"""Dangerous command approval -- detection, prompting, and per-session state.

This module is the single source of truth for the dangerous command system:
- Pattern detection (DANGEROUS_PATTERNS, detect_dangerous_command)
- Per-session approval state (thread-safe, keyed by session_key)
- Approval prompting (CLI interactive + gateway async)
- Smart approval via auxiliary LLM (auto-approve low-risk commands)
- Permanent allowlist persistence (config.yaml)
"""

import contextvars
import logging
import os
import re
import shlex
import sys
import tempfile
import threading
import time
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)

# Per-thread/per-task gateway session identity.
# Gateway runs agent turns concurrently in executor threads, so reading a
# process-global env var for session identity is racy. Keep env fallback for
# legacy single-threaded callers, but prefer the context-local value when set.
_approval_session_key: contextvars.ContextVar[str] = contextvars.ContextVar(
    "approval_session_key",
    default="",
)


def set_current_session_key(session_key: str) -> contextvars.Token[str]:
    """Bind the active approval session key to the current context."""
    return _approval_session_key.set(session_key or "")


def reset_current_session_key(token: contextvars.Token[str]) -> None:
    """Restore the prior approval session key context."""
    _approval_session_key.reset(token)


def get_current_session_key(default: str = "default") -> str:
    """Return the active session key, preferring context-local state.

    Resolution order:
    1. approval-specific contextvars (set by gateway before agent.run)
    2. session_context contextvars (set by _set_session_env)
    3. os.environ fallback (CLI, cron, tests)
    """
    session_key = _approval_session_key.get()
    if session_key:
        return session_key
    from gateway.session_context import get_session_env
    return get_session_env("ECTOR_SESSION_KEY", default)

# Sensitive write targets that should trigger approval even when referenced
# via shell expansions like $HOME or $ECTOR_HOME.
_SSH_SENSITIVE_PATH = r'(?:~|\$home|\$\{home\})/\.ssh(?:/|$)'
_ECTOR_ENV_PATH = (
    r'(?:~\/\.ector/|'
    r'(?:\$home|\$\{home\})/\.ector/|'
    r'(?:\$ector_home|\$\{ector_home\})/)'
    r'\.env\b'
)
_PROJECT_ENV_PATH = r'(?:(?:/|\.{1,2}/)?(?:[^\s/"\'`]+/)*\.env(?:\.[^/\s"\'`]+)*)'
_PROJECT_CONFIG_PATH = r'(?:(?:/|\.{1,2}/)?(?:[^\s/"\'`]+/)*config\.yaml)'
_SENSITIVE_WRITE_TARGET = (
    r'(?:/etc/|/dev/sd|'
    rf'{_SSH_SENSITIVE_PATH}|'
    rf'{_ECTOR_ENV_PATH})'
)
_PROJECT_SENSITIVE_WRITE_TARGET = rf'(?:{_PROJECT_ENV_PATH}|{_PROJECT_CONFIG_PATH})'
_COMMAND_TAIL = r'(?:\s*(?:&&|\|\||;).*)?$'

# =========================================================================
# Hardline (unconditional) blocklist
# =========================================================================
#
# Commands so catastrophic they should NEVER run via the agent, regardless
# of --yolo, /yolo, approvals.mode=off, or cron approve mode.  This is a
# floor below yolo: opting into yolo is the user trusting the agent with
# their files and services, not trusting it to wipe the disk or power the
# box off.
#
# Hardline only applies to environments that can actually damage the host
# (local, ssh, container-host cron).  Containerized backends (docker,
# singularity, modal, daytona) already bypass the dangerous-command layer
# because nothing they do can touch the host, so we leave that behavior
# alone.
#
# The list is deliberately tiny — only things with no recovery path:
# filesystem destruction rooted at /, raw block device overwrites, kernel
# shutdown/reboot, and denial-of-service commands that take the host down.
# Recoverable-but-costly operations (git reset --hard, rm -rf /tmp/x,
# chmod -R 777, curl|sh) stay in DANGEROUS_PATTERNS where yolo can pass
# them through — that's what yolo is for.
#
# Inspired by Mercury Agent's permission-hardened blocklist
# (https://github.com/cosmicstack-labs/mercury-agent).

# Regex fragment matching the *start* of a command (i.e. positions where
# a shell would begin parsing a new command).  Used by shutdown/reboot
# patterns so they don't fire on "echo reboot" or "grep 'shutdown' log".
# Matches: start of string, after command separators (; && || | newline),
# after subshell openers ( `$(` or backtick ), optionally consuming
# leading wrapper commands (sudo, env VAR=VAL, exec, nohup, setsid).
_CMDPOS = (
    r'(?:^|[;&|\n`]|\$\()'         # start position
    r'\s*'                          # optional whitespace
    r'(?:sudo\s+(?:-[^\s]+\s+)*)?'  # optional sudo with flags
    r'(?:env\s+(?:\w+=\S*\s+)*)?'   # optional env with VAR=VAL pairs
    r'(?:(?:exec|nohup|setsid|time)\s+)*'  # optional wrapper commands
    r'\s*'
)

HARDLINE_PATTERNS = [
    # rm recursive targeting the root filesystem or protected roots
    (r'\brm\s+(-[^\s]*\s+)*(/|/\*|/ \*)(\s|$)', "exclusão recursiva do sistema de arquivos raiz"),
    (r'\brm\s+(-[^\s]*\s+)*(/home|/home/\*|/root|/root/\*|/etc|/etc/\*|/usr|/usr/\*|/var|/var/\*|/bin|/bin/\*|/sbin|/sbin/\*|/boot|/boot/\*|/lib|/lib/\*)(\s|$)', "exclusão recursiva de diretório do sistema"),
    (r'\brm\s+(-[^\s]*\s+)*(~|\$HOME)(/?|/\*)?(\s|$)', "exclusão recursiva do diretório home"),
    # Filesystem format
    (r'\bmkfs(\.[a-z0-9]+)?\b', "formatar sistema de arquivos (mkfs)"),
    # Raw block device overwrites (dd + redirection)
    (r'\bdd\b[^\n]*\bof=/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*', "dd para dispositivo de bloco bruto"),
    (r'>\s*/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*\b', "redirecionamento para dispositivo de bloco bruto"),
    # Fork bomb (classic shell form)
    (r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:', "bomba de fork (fork bomb)"),
    # Kill every process on the system
    (r'\bkill\s+(-[^\s]+\s+)*-1\b', "matar todos os processos"),
    # System shutdown / reboot — anchor to command position (start of line,
    # after a command separator, or after sudo/env wrappers) so we don't
    # false-positive on "echo reboot" or "grep 'shutdown' logs".
    # _CMDPOS matches start-of-command positions.
    (_CMDPOS + r'(shutdown|reboot|halt|poweroff)\b', "desligamento/reinicialização do sistema"),
    (_CMDPOS + r'init\s+[06]\b', "init 0/6 (desligar/reiniciar)"),
    (_CMDPOS + r'systemctl\s+(poweroff|reboot|halt|kexec)\b', "systemctl poweroff/reboot"),
    (_CMDPOS + r'telinit\s+[06]\b', "telinit 0/6 (desligar/reiniciar)"),
]


def detect_hardline_command(command: str) -> tuple:
    """Check if a command matches the unconditional hardline blocklist.

    Returns:
        (is_hardline, description) or (False, None)
    """
    normalized = _normalize_command_for_detection(command).lower()
    for pattern, description in HARDLINE_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE | re.DOTALL):
            return (True, description)
    return (False, None)


def _hardline_block_result(description: str) -> dict:
    """Build the standard block result for a hardline match."""
    return {
        "approved": False,
        "hardline": True,
        "message": (
            f"BLOQUEADO (hardline): {description}. "
            "Este comando está na lista de bloqueio incondicional e não "
            "pode ser executado via agente — nem mesmo com --yolo, /yolo, "
            "approvals.mode=off ou modo de aprovação cron. Se você realmente "
            "precisar executá-lo, faça-o manualmente em um terminal fora do "
            "agente."
        ),
    }


# =========================================================================
# Dangerous command patterns
# =========================================================================

DANGEROUS_PATTERNS = [
    # Any rm at a command position (rm -v ./file, rm ./x, rm -rf …). Anchored
    # via _CMDPOS so "echo rm foo" does not false-positive.
    (_CMDPOS + r'rm\s+', "exclusão de arquivo ou diretório"),
    (r'\brm\s+(-[^\s]*\s+)*/', "excluir no caminho raiz"),
    (r'\brm\s+-[^\s]*r', "exclusão recursiva"),
    (r'\brm\s+--recursive\b', "exclusão recursiva (flag longa)"),
    (r'\bchmod\s+(-[^\s]*\s+)*(777|666|o\+[rwx]*w|a\+[rwx]*w)\b', "permissões de escrita para todos/outros"),
    (r'\bchmod\s+--recursive\b.*(777|666|o\+[rwx]*w|a\+[rwx]*w)', "escrita recursiva para todos/outros (flag longa)"),
    (r'\bchown\s+(-[^\s]*)?R\s+root', "chown recursivo para root"),
    (r'\bchown\s+--recursive\b.*root', "chown recursivo para root (flag longa)"),
    (r'\bmkfs\b', "formatar sistema de arquivos"),
    (r'\bdd\s+.*if=', "cópia de disco"),
    (r'>\s*/dev/sd', "gravação em dispositivo de bloco"),
    (r'\bDROP\s+(TABLE|DATABASE)\b', "SQL DROP"),
    (r'\bDELETE\s+FROM\b(?!.*\bWHERE\b)', "SQL DELETE sem WHERE"),
    (r'\bTRUNCATE\s+(TABLE)?\s*\w', "SQL TRUNCATE"),
    (r'>\s*/etc/', "sobrescrever config do sistema"),
    (r'\bsystemctl\s+(-[^\s]+\s+)*(stop|restart|disable|mask)\b', "parar/reiniciar serviço do sistema"),
    (r'\bkill\s+-9\s+-1\b', "matar todos os processos"),
    (r'\bpkill\s+-9\b', "forçar encerramento de processos"),
    (r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:', "bomba de fork"),
    # Any shell invocation via -c or combined flags like -lc, -ic, etc.
    (r'\b(bash|sh|zsh|ksh)\s+-[^\s]*c(\s+|$)', "comando shell via flag -c/-lc"),
    (r'\b(python[23]?|perl|ruby|node)\s+-[ec]\s+', "execução de script via flag -e/-c"),
    (r'\b(curl|wget)\b.*\|\s*(ba)?sh\b', "canalizar conteúdo remoto para shell"),
    (r'\b(bash|sh|zsh|ksh)\s+<\s*<?\s*\(\s*(curl|wget)\b', "executar script remoto via substituição de processo"),
    (rf'\btee\b.*["\']?{_SENSITIVE_WRITE_TARGET}', "sobrescrever arquivo do sistema via tee"),
    (rf'>>?\s*["\']?{_SENSITIVE_WRITE_TARGET}', "sobrescrever arquivo do sistema via redirecionamento"),
    (rf'\btee\b.*["\']?{_PROJECT_SENSITIVE_WRITE_TARGET}["\']?{_COMMAND_TAIL}', "sobrescrever env/config do projeto via tee"),
    (rf'>>?\s*["\']?{_PROJECT_SENSITIVE_WRITE_TARGET}["\']?{_COMMAND_TAIL}', "sobrescrever env/config do projeto via redirecionamento"),
    (r'\bxargs\s+.*\brm\b', "xargs com rm"),
    (r'\bfind\b.*-exec\s+(/\S*/)?rm\b', "find -exec rm"),
    (r'\bfind\b.*-delete\b', "find -delete"),
    # Gateway lifecycle protection: prevent the agent from killing its own
    # gateway process.  These commands trigger a gateway restart/stop that
    # terminates all running agents mid-work.
    (r'\bector\s+gateway\s+(stop|restart)\b', "parar/reiniciar gateway ector (mata agentes em execução)"),
    (r'\bector\s+update\b', "atualização do ector (reinicia gateway, mata agentes em execução)"),
    # Gateway protection: never start gateway outside systemd management
    (r'gateway\s+run\b.*(&\s*$|&\s*;|\bdisown\b|\bsetsid\b)', "iniciar gateway fora do systemd (use 'systemctl --user restart ector-gateway')"),
    (r'\bnohup\b.*gateway\s+run\b', "iniciar gateway fora do systemd (use 'systemctl --user restart ector-gateway')"),
    # Self-termination protection: prevent agent from killing its own process
    (r'\b(pkill|killall)\b.*\b(ector|gateway|cli\.py)\b', "matar processo ector/gateway (auto-extermínio)"),
    # Self-termination via kill + command substitution (pgrep/pidof).
    # The name-based pattern above catches `pkill ector` but not
    # `kill -9 $(pgrep -f ector)` because the substitution is opaque
    # to regex at detection time. Catch the structural pattern instead.
    (r'\bkill\b.*\$\(\s*pgrep\b', "matar processo via expansão pgrep (auto-extermínio)"),
    (r'\bkill\b.*`\s*pgrep\b', "matar processo via expansão pgrep com crase (auto-extermínio)"),
    # File copy/move/edit into sensitive system paths
    (r'\b(cp|mv|install)\b.*\s/etc/', "copiar/mover arquivo para /etc/"),
    (rf'\b(cp|mv|install)\b.*\s["\']?{_PROJECT_SENSITIVE_WRITE_TARGET}["\']?{_COMMAND_TAIL}', "sobrescrever arquivo de env/config do projeto"),
    (r'\bsed\s+-[^\s]*i.*\s/etc/', "edição in-place de configuração do sistema"),
    (r'\bsed\s+--in-place\b.*\s/etc/', "edição in-place de configuração do sistema (flag longa)"),
    # Script execution via heredoc — bypasses the -e/-c flag patterns above.
    # `python3 << 'EOF'` feeds arbitrary code via stdin without -c/-e flags.
    (r'\b(python[23]?|perl|ruby|node)\s+<<', "execução de script via heredoc"),
    # Git destructive operations that can lose uncommitted work or rewrite
    # shared history. Not captured by rm/chmod/etc patterns.
    (r'\bgit\s+reset\s+--hard\b', "git reset --hard (destrói alterações não commitadas)"),
    (r'\bgit\s+push\b.*--force\b', "git push forçado (sobrescreve histórico remoto)"),
    (r'\bgit\s+push\b.*-f\b', "git push forçado flag curta (sobrescreve histórico remoto)"),
    (r'\bgit\s+clean\s+-[^\s]*f', "git clean com força (exclui arquivos não rastreados)"),
    (r'\bgit\s+branch\s+-D\b', "exclusão forçada de branch git"),
    # Script execution after chmod +x — catches the two-step pattern where
    # a script is first made executable then immediately run. The script
    # content may contain dangerous commands that individual patterns miss.
    (r'\bchmod\s+\+x\b.*[;&|]+\s*\./', "chmod +x seguido de execução imediata"),
]


def _legacy_pattern_key(pattern: str) -> str:
    """Reproduce the old regex-derived approval key for backwards compatibility."""
    return pattern.split(r'\b')[1] if r'\b' in pattern else pattern[:20]


_PATTERN_KEY_ALIASES: dict[str, set[str]] = {}
for _pattern, _description in DANGEROUS_PATTERNS:
    _legacy_key = _legacy_pattern_key(_pattern)
    _canonical_key = _description
    _PATTERN_KEY_ALIASES.setdefault(_canonical_key, set()).update({_canonical_key, _legacy_key})
    _PATTERN_KEY_ALIASES.setdefault(_legacy_key, set()).update({_legacy_key, _canonical_key})


def _approval_key_aliases(pattern_key: str) -> set[str]:
    """Return all approval keys that should match this pattern.

    New approvals use the human-readable description string, but older
    command_allowlist entries and session approvals may still contain the
    historical regex-derived key.
    """
    return _PATTERN_KEY_ALIASES.get(pattern_key, {pattern_key})


# =========================================================================
# Detection
# =========================================================================

def _normalize_command_for_detection(command: str) -> str:
    """Normalize a command string before dangerous-pattern matching.

    Strips ANSI escape sequences (full ECMA-48 via tools.ansi_strip),
    null bytes, and normalizes Unicode fullwidth characters so that
    obfuscation techniques cannot bypass the pattern-based detection.
    """
    from tools.ansi_strip import strip_ansi

    # Strip all ANSI escape sequences (CSI, OSC, DCS, 8-bit C1, etc.)
    command = strip_ansi(command)
    # Strip null bytes
    command = command.replace('\x00', '')
    # Normalize Unicode (fullwidth Latin, halfwidth Katakana, etc.)
    command = unicodedata.normalize('NFKC', command)
    return command


def detect_dangerous_command(command: str) -> tuple:
    """Check if a command matches any dangerous patterns.

    Returns:
        (is_dangerous, pattern_key, description) or (False, None, None)
    """
    command_lower = _normalize_command_for_detection(command).lower()
    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, command_lower, re.IGNORECASE | re.DOTALL):
            pattern_key = description
            return (True, pattern_key, description)
    return (False, None, None)


# =========================================================================
# Per-session approval state (thread-safe)
# =========================================================================

_lock = threading.Lock()
_pending: dict[str, dict] = {}
_session_approved: dict[str, set] = {}
_session_yolo: set[str] = set()
_permanent_approved: set = set()
_managed_temp_artifacts: dict[str, dict[str, float]] = {}

_MANAGED_TEMP_TTL_SECONDS = 1800
_ALLOWED_TEMP_ROOTS = tuple(
    sorted(
        {
            os.path.normpath("/tmp"),
            os.path.normpath("/var/tmp"),
            os.path.normpath("/private/tmp"),
            os.path.normpath(tempfile.gettempdir()),
        }
    )
)


def _cleanup_expired_managed_temp_locked(now: float | None = None) -> None:
    ts = now if now is not None else time.time()
    empty_sessions: list[str] = []
    for session_key, entries in _managed_temp_artifacts.items():
        expired = [path for path, expiry in entries.items() if expiry <= ts]
        for path in expired:
            entries.pop(path, None)
        if not entries:
            empty_sessions.append(session_key)
    for session_key in empty_sessions:
        _managed_temp_artifacts.pop(session_key, None)


def _normalize_managed_temp_path(path: str) -> str:
    candidate = os.path.expanduser((path or "").strip())
    if not candidate:
        return ""
    if not os.path.isabs(candidate):
        return ""
    normalized = os.path.normpath(candidate)
    for root in _ALLOWED_TEMP_ROOTS:
        if normalized == root or normalized.startswith(f"{root}{os.sep}"):
            return normalized
    return ""


def register_managed_temp_artifact(
    session_key: str,
    path: str,
    *,
    ttl_seconds: int = _MANAGED_TEMP_TTL_SECONDS,
) -> bool:
    """Register a temp artifact created by trusted runtime code."""
    normalized_session = (session_key or "").strip()
    normalized_path = _normalize_managed_temp_path(path)
    if not normalized_session or not normalized_path:
        return False
    ttl = max(int(ttl_seconds or 0), 1)
    expiry = time.time() + ttl
    with _lock:
        _cleanup_expired_managed_temp_locked()
        _managed_temp_artifacts.setdefault(normalized_session, {})[normalized_path] = expiry
    return True


def consume_managed_temp_artifact(session_key: str, path: str) -> bool:
    """Consume one registered managed temp artifact token (single-use)."""
    normalized_session = (session_key or "").strip()
    normalized_path = _normalize_managed_temp_path(path)
    if not normalized_session or not normalized_path:
        return False
    with _lock:
        _cleanup_expired_managed_temp_locked()
        entries = _managed_temp_artifacts.get(normalized_session)
        if not entries:
            return False
        expiry = entries.get(normalized_path)
        if expiry is None or expiry <= time.time():
            entries.pop(normalized_path, None)
            if not entries:
                _managed_temp_artifacts.pop(normalized_session, None)
            return False
        entries.pop(normalized_path, None)
        if not entries:
            _managed_temp_artifacts.pop(normalized_session, None)
        return True


def register_managed_temp_artifacts_from_command(session_key: str, command: str) -> int:
    """Best-effort extraction of temp artifact paths created by a command."""
    normalized_session = (session_key or "").strip()
    text = (command or "").strip()
    if not normalized_session or not text:
        return 0

    candidates: set[str] = set()
    # Redirections like "cat <<EOF > /tmp/file.txt"
    for match in re.findall(r">>?\s*([\"']?)(/[^\s\"'`;&|]+)\1", text):
        candidates.add(match[1])

    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = []
    if tokens and tokens[0] == "touch":
        for arg in tokens[1:]:
            if arg.startswith("-"):
                continue
            candidates.add(arg)

    registered = 0
    for raw_path in candidates:
        if register_managed_temp_artifact(normalized_session, raw_path):
            registered += 1
    return registered


def is_safe_managed_temp_cleanup(command: str, session_key: str) -> bool:
    """Allow strictly-scoped rm cleanup for managed temp artifacts."""
    if not session_key:
        return False
    text = (command or "").strip()
    if not text:
        return False
    # Require single, plain command (no chaining, pipes, redirects, globbing, subshell).
    if re.search(r"[;&|`$><*?{}\[\]\n\r]", text):
        return False
    try:
        tokens = shlex.split(text)
    except ValueError:
        return False
    if not tokens or tokens[0] != "rm":
        return False

    flags: list[str] = []
    targets: list[str] = []
    for token in tokens[1:]:
        if token.startswith("-"):
            flags.append(token)
        else:
            targets.append(token)
    if len(targets) != 1:
        return False

    for flag in flags:
        if flag in {"--force", "--verbose", "-f", "-v", "-fv", "-vf"}:
            continue
        if "r" in flag.lower() or "d" in flag.lower():
            return False
        return False

    return consume_managed_temp_artifact(session_key, targets[0])

# =========================================================================
# Blocking gateway approval (mirrors CLI's synchronous input() flow)
# =========================================================================
# Per-session QUEUE of pending approvals.  Multiple threads (parallel
# subagents, execute_code RPC handlers) can block concurrently — each gets
# its own threading.Event.  /approve resolves the oldest, /approve all
# resolves every pending approval in the session.


class _ApprovalEntry:
    """One pending dangerous-command approval inside a gateway session."""
    __slots__ = ("event", "data", "result")

    def __init__(self, data: dict):
        self.event = threading.Event()
        self.data = data          # command, description, pattern_keys, …
        self.result: Optional[str] = None  # "once"|"session"|"always"|"deny"


_gateway_queues: dict[str, list] = {}        # session_key → [_ApprovalEntry, …]
_gateway_notify_cbs: dict[str, object] = {}  # session_key → callable(approval_data)


def register_gateway_notify(session_key: str, cb) -> None:
    """Register a per-session callback for sending approval requests to the user.

    The callback signature is ``cb(approval_data: dict) -> None`` where
    *approval_data* contains ``command``, ``description``, and
    ``pattern_keys``.  The callback bridges sync→async (runs in the agent
    thread, must schedule the actual send on the event loop).
    """
    with _lock:
        _gateway_notify_cbs[session_key] = cb


def detach_gateway_notify(session_key: str) -> None:
    """Drop the UI notify callback without resolving pending approvals.

    Used when the web SSE client disconnects (page reload) so the agent
    thread can keep waiting for /api/chat/approval while the UI reconnects.
    """
    with _lock:
        _gateway_notify_cbs.pop(session_key, None)


def unregister_gateway_notify(session_key: str) -> None:
    """Unregister the per-session gateway approval callback.

    Signals ALL blocked threads for this session so they don't hang forever
    (e.g. when the agent run finishes or is interrupted).  Also drops
    non-blocking legacy ``_pending`` entries so the web UI cannot show a
    ghost approval card after the turn ends.
    """
    with _lock:
        _gateway_notify_cbs.pop(session_key, None)
        _pending.pop(session_key, None)
        entries = _gateway_queues.pop(session_key, [])
        for entry in entries:
            entry.event.set()


def resolve_gateway_approval(session_key: str, choice: str,
                             resolve_all: bool = False) -> int:
    """Called by the gateway's /approve or /deny handler to unblock
    waiting agent thread(s).

    When *resolve_all* is True every pending approval in the session is
    resolved at once (``/approve all``).  Otherwise only the oldest one
    is resolved (FIFO).

    Returns the number of approvals resolved (0 means nothing was pending).
    """
    with _lock:
        queue = _gateway_queues.get(session_key)
        if not queue:
            _pending.pop(session_key, None)
            return 0
        if resolve_all:
            targets = list(queue)
            queue.clear()
        else:
            targets = [queue.pop(0)]
        if not queue:
            _gateway_queues.pop(session_key, None)

    for entry in targets:
        entry.result = choice
        entry.event.set()
    return len(targets)


def has_blocking_approval(session_key: str) -> bool:
    """Check if a session has one or more blocking gateway approvals waiting."""
    with _lock:
        return bool(_gateway_queues.get(session_key))


def peek_actionable_gateway_approval(session_key: str) -> Optional[dict]:
    """Return the oldest **blocking** approval payload (FIFO queue) for a session.

    Used by the web chat and gateway /approve handlers.  Does not include
    legacy ``_pending`` entries from non-blocking ``approval_required``
    fallbacks — those cannot be resolved via ``resolve_gateway_approval``.
    """
    if not session_key:
        return None
    with _lock:
        queue = _gateway_queues.get(session_key)
        if queue:
            return dict(queue[0].data)
        return None


def peek_pending_gateway_approval(session_key: str) -> Optional[dict]:
    """Return the oldest pending approval payload for a session, if any.

    Includes legacy ``_pending`` (non-blocking ``approval_required``).
    Prefer ``peek_actionable_gateway_approval`` for UI that posts to
    ``resolve_gateway_approval``.
    """
    if not session_key:
        return None
    actionable = peek_actionable_gateway_approval(session_key)
    if actionable is not None:
        return actionable
    with _lock:
        legacy = _pending.get(session_key)
        return dict(legacy) if legacy else None


def submit_pending(session_key: str, approval: dict):
    """Store a pending approval request for a session."""
    with _lock:
        _pending[session_key] = approval


def approve_session(session_key: str, pattern_key: str):
    """Approve a pattern for this session only."""
    with _lock:
        _session_approved.setdefault(session_key, set()).add(pattern_key)


def enable_session_yolo(session_key: str) -> None:
    """Enable YOLO bypass for a single session key."""
    if not session_key:
        return
    with _lock:
        _session_yolo.add(session_key)


def disable_session_yolo(session_key: str) -> None:
    """Disable YOLO bypass for a single session key."""
    if not session_key:
        return
    with _lock:
        _session_yolo.discard(session_key)


def clear_session(session_key: str) -> None:
    """Remove all approval and yolo state for a given session."""
    if not session_key:
        return
    with _lock:
        _session_approved.pop(session_key, None)
        _session_yolo.discard(session_key)
        _pending.pop(session_key, None)
        _gateway_queues.pop(session_key, None)
        _managed_temp_artifacts.pop(session_key, None)


def is_session_yolo_enabled(session_key: str) -> bool:
    """Return True when YOLO bypass is enabled for a specific session."""
    if not session_key:
        return False
    with _lock:
        return session_key in _session_yolo


def is_current_session_yolo_enabled() -> bool:
    """Return True when the active approval session has YOLO bypass enabled."""
    return is_session_yolo_enabled(get_current_session_key(default=""))


def is_approved(session_key: str, pattern_key: str) -> bool:
    """Check if a pattern is approved (session-scoped or permanent).

    Accept both the current canonical key and the legacy regex-derived key so
    existing command_allowlist entries continue to work after key migrations.
    """
    aliases = _approval_key_aliases(pattern_key)
    with _lock:
        if any(alias in _permanent_approved for alias in aliases):
            return True
        session_approvals = _session_approved.get(session_key, set())
        return any(alias in session_approvals for alias in aliases)


def approve_permanent(pattern_key: str):
    """Add a pattern to the permanent allowlist."""
    with _lock:
        _permanent_approved.add(pattern_key)


def load_permanent(patterns: set):
    """Bulk-load permanent allowlist entries from config."""
    with _lock:
        _permanent_approved.update(patterns)



# =========================================================================
# Config persistence for permanent allowlist
# =========================================================================

def load_permanent_allowlist() -> set:
    """Load permanently allowed command patterns from config.

    Also syncs them into the approval module so is_approved() works for
    patterns added via 'always' in a previous session.
    """
    try:
        from ector_cli.config import load_config
        config = load_config()
        patterns = set(config.get("command_allowlist", []) or [])
        if patterns:
            load_permanent(patterns)
        return patterns
    except Exception as e:
        logger.warning("Failed to load permanent allowlist: %s", e)
        return set()


def save_permanent_allowlist(patterns: set):
    """Save permanently allowed command patterns to config."""
    try:
        from ector_cli.config import load_config, save_config
        config = load_config()
        config["command_allowlist"] = list(patterns)
        save_config(config)
    except Exception as e:
        logger.warning("Could not save allowlist: %s", e)


# =========================================================================
# Approval prompting + orchestration
# =========================================================================

def prompt_dangerous_approval(command: str, description: str,
                              timeout_seconds: int | None = None,
                              allow_permanent: bool = True,
                              approval_callback=None) -> str:
    """Prompt the user to approve a dangerous command (CLI only).

    Args:
        allow_permanent: When False, hide the [a]lways option (used when
            tirith warnings are present, since broad permanent allowlisting
            is inappropriate for content-level security findings).
        approval_callback: Optional callback registered by the CLI for
            prompt_toolkit integration. Signature:
            (command, description, *, allow_permanent=True) -> str.

    Returns: 'once', 'session', 'always', or 'deny'
    """
    if timeout_seconds is None:
        timeout_seconds = _get_approval_timeout()

    if approval_callback is not None:
        try:
            return approval_callback(command, description,
                                     allow_permanent=allow_permanent)
        except Exception as e:
            logger.error("Approval callback failed: %s", e, exc_info=True)
            return "deny"

    os.environ["ECTOR_SPINNER_PAUSE"] = "1"
    try:
        while True:
            print()
            print(f"    Comando prestes a ser executado: {description}")
            print(f"      {command}")
            print()
            if allow_permanent:
                print("      [o] uma vez  |  [s] sessão  |  [a] sempre  |  [n] negar")
            else:
                print("      [o] uma vez  |  [s] sessão  |  [n] negar")
            print()
            sys.stdout.flush()

            result = {"choice": ""}

            def get_input():
                try:
                    prompt = "      Escolha [o/s/a/N]: " if allow_permanent else "      Escolha [o/s/N]: "
                    result["choice"] = input(prompt).strip().lower()
                except (EOFError, OSError):
                    result["choice"] = ""

            thread = threading.Thread(target=get_input, daemon=True)
            thread.start()
            thread.join(timeout=timeout_seconds)

            if thread.is_alive():
                print("\n      ⏱ Tempo esgotado — negando comando")
                return "deny"

            choice = result["choice"]
            if choice in ('o', 'uma vez'):
                print("      ✓ Permitido uma vez")
                return "once"
            elif choice in ('s', 'sessão'):
                print("      ✓ Permitido para esta sessão")
                return "session"
            elif choice in ('a', 'sempre'):
                if not allow_permanent:
                    print("      ✓ Permitido para esta sessão")
                    return "session"
                print("      ✓ Adicionado à lista de permissões permanentes")
                return "always"
            else:
                print("      ✗ Negado")
                return "deny"

    except (EOFError, KeyboardInterrupt):
        print("\n      ✗ Cancelado")
        return "deny"
    finally:
        if "ECTOR_SPINNER_PAUSE" in os.environ:
            del os.environ["ECTOR_SPINNER_PAUSE"]
        print()
        sys.stdout.flush()


def _normalize_approval_mode(mode) -> str:
    """Normalize approval mode values loaded from YAML/config.

    YAML 1.1 treats bare words like `off` as booleans, so a config entry like
    `approvals:\n  mode: off` is parsed as False unless quoted. Treat that as the
    intended string mode instead of falling back to manual approvals.
    """
    if isinstance(mode, bool):
        return "off" if mode is False else "manual"
    if isinstance(mode, str):
        normalized = mode.strip().lower()
        return normalized or "manual"
    return "manual"


def _get_approval_config() -> dict:
    """Read the approvals config block. Returns a dict with 'mode', 'timeout', etc."""
    try:
        from ector_cli.config import load_config
        config = load_config()
        return config.get("approvals", {}) or {}
    except Exception as e:
        logger.warning("Failed to load approval config: %s", e)
        return {}


def _get_approval_mode() -> str:
    """Read the approval mode from config. Returns 'manual', 'smart', or 'off'."""
    mode = _get_approval_config().get("mode", "manual")
    return _normalize_approval_mode(mode)


def _get_approval_timeout() -> int:
    """Read the approval timeout from config. Defaults to 60 seconds."""
    try:
        return int(_get_approval_config().get("timeout", 60))
    except (ValueError, TypeError):
        return 60


def _get_cron_approval_mode() -> str:
    """Read the cron approval mode from config. Returns 'deny' or 'approve'."""
    try:
        from ector_cli.config import load_config
        config = load_config()
        mode = str(config.get("approvals", {}).get("cron_mode", "deny")).lower().strip()
        if mode in ("approve", "off", "allow", "yes"):
            return "approve"
        return "deny"
    except Exception:
        return "deny"


def _smart_approve(command: str, description: str) -> str:
    """Use the auxiliary LLM to assess risk and decide approval.

    Returns 'approve' if the LLM determines the command is safe,
    'deny' if genuinely dangerous, or 'escalate' if uncertain.

    Inspired by OpenAI Codex's Smart Approvals guardian subagent
    (openai/codex#13860).
    """
    try:
        from agent.auxiliary_client import call_llm

        prompt = f"""Você é um revisor de segurança para um agente de codificação de IA. Um comando de terminal foi sinalizado por correspondência de padrões como potencialmente perigoso.

Comando: {command}
Motivo da sinalização: {description}

Avalie o risco REAL deste comando. Muitos comandos sinalizados são falsos positivos — por exemplo, `python -c "print('hello')"` é sinalizado como "execução de script via flag -c", mas é completamente inofensivo.

Regras:
- APPROVE se o comando for claramente seguro (execução de script benigna, operações de arquivo seguras, ferramentas de desenvolvimento, instalação de pacotes, operações de git, etc.)
- DENY se o comando puder genuinamente danificar o sistema (exclusão recursiva de caminhos importantes, sobrescrever arquivos do sistema, fork bombs, limpar discos, excluir bancos de dados, etc.)
- ESCALATE se você não tiver certeza

Responda com exatamente uma palavra: APPROVE, DENY ou ESCALATE"""

        response = call_llm(
            task="approval",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=16,
        )

        answer = (response.choices[0].message.content or "").strip().upper()

        if "APPROVE" in answer:
            return "approve"
        elif "DENY" in answer:
            return "deny"
        else:
            return "escalate"

    except Exception as e:
        logger.debug("Smart approvals: LLM call failed (%s), escalating", e)
        return "escalate"


def check_dangerous_command(command: str, env_type: str,
                            approval_callback=None) -> dict:
    """Check if a command is dangerous and handle approval.

    This is the main entry point called by terminal_tool before executing
    any command. It orchestrates detection, session checks, and prompting.

    Args:
        command: The shell command to check.
        env_type: Terminal backend type ('local', 'ssh', 'docker', etc.).
        approval_callback: Optional CLI callback for interactive prompts.

    Returns:
        {"approved": True/False, "message": str or None, ...}
    """
    if env_type in ("docker", "singularity", "modal", "daytona"):
        return {"approved": True, "message": None}

    # Hardline floor: commands with no recovery path (rm -rf /, mkfs, dd
    # to raw device, shutdown/reboot, fork bomb, kill -1) are blocked
    # unconditionally, BEFORE the yolo bypass.  Opting into yolo is
    # trusting the agent with your files and services, not trusting it
    # to wipe the disk or power the box off.
    is_hardline, hardline_desc = detect_hardline_command(command)
    if is_hardline:
        logger.warning("Hardline block: %s (command: %s)", hardline_desc, command[:200])
        return _hardline_block_result(hardline_desc)

    # --yolo: bypass all approval prompts. Gateway /yolo is session-scoped;
    # CLI --yolo remains process-scoped via the env var for local use.
    if os.getenv("ECTOR_YOLO_MODE") or is_current_session_yolo_enabled():
        return {"approved": True, "message": None}

    is_dangerous, pattern_key, description = detect_dangerous_command(command)
    if not is_dangerous:
        return {"approved": True, "message": None}

    session_key = get_current_session_key()
    if is_approved(session_key, pattern_key):
        return {"approved": True, "message": None}

    is_cli = os.getenv("ECTOR_INTERACTIVE")
    is_gateway = os.getenv("ECTOR_GATEWAY_SESSION")

    if not is_cli and not is_gateway:
        # Cron sessions: respect cron_mode config
        if os.getenv("ECTOR_CRON_SESSION"):
            if _get_cron_approval_mode() == "deny":
                return {
                    "approved": False,
                    "message": (
                        f"BLOQUEADO: Comando sinalizado como perigoso ({description}) "
                        "mas tarefas cron rodam sem um usuário presente para aprovar. "
                        "Encontre uma abordagem alternativa que evite este comando. "
                        "Para permitir comandos perigosos em tarefas cron, defina "
                        "approvals.cron_mode: approve em config.yaml."
                    ),
                }
        return {"approved": True, "message": None}

    if is_gateway or os.getenv("ECTOR_EXEC_ASK"):
        submit_pending(session_key, {
            "command": command,
            "pattern_key": pattern_key,
            "description": description,
        })
        return {
            "approved": False,
            "pattern_key": pattern_key,
            "status": "approval_required",
            "command": command,
            "description": description,
            "message": (
                f"▲ Este comando é potencialmente perigoso ({description}). "
                f"Pedindo aprovação ao usuário.\n\n**Comando:**\n```\n{command}\n```"
            ),
        }

    choice = prompt_dangerous_approval(command, description,
                                       approval_callback=approval_callback)

    if choice == "deny":
        return {
            "approved": False,
            "message": f"BLOQUEADO: O usuário negou este comando potencialmente perigoso (corresponde ao padrão '{description}'). NÃO repita este comando — o usuário o rejeitou explicitamente.",
            "pattern_key": pattern_key,
            "description": description,
        }

    if choice == "session":
        approve_session(session_key, pattern_key)
    elif choice == "always":
        approve_session(session_key, pattern_key)
        approve_permanent(pattern_key)
        save_permanent_allowlist(_permanent_approved)

    return {"approved": True, "message": None}


# =========================================================================
# Combined pre-exec guard (tirith + dangerous command detection)
# =========================================================================

def _format_tirith_description(tirith_result: dict) -> str:
    """Build a human-readable description from tirith findings.

    Includes severity, title, and description for each finding so users
    can make an informed approval decision. Text is localized to pt-BR for
    the interactive approval UI (TUI / gateway).
    """
    from tools.tirith_i18n_pt import (
        localize_tirith_finding,
        localize_tirith_scan_prefix,
        localize_tirith_summary,
    )

    findings = tirith_result.get("findings") or []
    if not findings:
        summary = localize_tirith_summary(
            tirith_result.get("summary") or "security issue detected"
        )
        return f"Varredura de segurança: {summary}"

    parts = []
    for raw in findings:
        f = localize_tirith_finding(raw)
        severity = f.get("severity", "")
        title = f.get("title", "")
        desc = f.get("description", "")
        if title and desc:
            parts.append(f"[{severity}] {title}: {desc}" if severity else f"{title}: {desc}")
        elif title:
            parts.append(f"[{severity}] {title}" if severity else title)
    if not parts:
        summary = localize_tirith_summary(
            tirith_result.get("summary") or "security issue detected"
        )
        return f"Varredura de segurança: {summary}"

    return localize_tirith_scan_prefix("Security scan — " + "; ".join(parts))


def check_all_command_guards(command: str, env_type: str,
                             approval_callback=None) -> dict:
    """Run all pre-exec security checks and return a single approval decision.

    Gathers findings from tirith and dangerous-command detection, then
    presents them as a single combined approval request. This prevents
    a gateway force=True replay from bypassing one check when only the
    other was shown to the user.
    """
    # Skip containers for both checks
    if env_type in ("docker", "singularity", "modal", "daytona"):
        return {"approved": True, "message": None}

    # Hardline floor: unconditional block for catastrophic commands
    # (rm -rf /, mkfs, dd to raw device, shutdown/reboot, fork bomb,
    # kill -1). Applies BEFORE yolo / mode=off / cron approve-mode so
    # no session-level setting can bypass it.
    is_hardline, hardline_desc = detect_hardline_command(command)
    if is_hardline:
        logger.warning("Hardline block: %s (command: %s)", hardline_desc, command[:200])
        return _hardline_block_result(hardline_desc)

    # --yolo or approvals.mode=off: bypass all approval prompts.
    # Gateway /yolo is session-scoped; CLI --yolo remains process-scoped.
    approval_mode = _get_approval_mode()
    if os.getenv("ECTOR_YOLO_MODE") or is_current_session_yolo_enabled() or approval_mode == "off":
        return {"approved": True, "message": None}

    session_key = get_current_session_key()
    if is_safe_managed_temp_cleanup(command, session_key):
        return {
            "approved": True,
            "message": None,
            "managed_temp_cleanup": True,
            "description": "cleanup de artefato temporário gerenciado",
        }

    is_cli = os.getenv("ECTOR_INTERACTIVE")
    is_gateway = os.getenv("ECTOR_GATEWAY_SESSION")
    is_ask = os.getenv("ECTOR_EXEC_ASK")

    # Preserve the existing non-interactive behavior: outside CLI/gateway/ask
    # flows, we do not block on approvals and we skip external guard work.
    if not is_cli and not is_gateway and not is_ask:
        # Cron sessions: respect cron_mode config
        if os.getenv("ECTOR_CRON_SESSION"):
            if _get_cron_approval_mode() == "deny":
                # Run detection to get a description for the block message
                is_dangerous, _pk, description = detect_dangerous_command(command)
                if is_dangerous:
                    return {
                        "approved": False,
                        "message": (
                            f"BLOCKED: Command flagged as dangerous ({description}) "
                            "but cron jobs run without a user present to approve it. "
                            "Find an alternative approach that avoids this command. "
                            "To allow dangerous commands in cron jobs, set "
                            "approvals.cron_mode: approve in config.yaml."
                        ),
                    }
        return {"approved": True, "message": None}

    # --- Phase 1: Gather findings from both checks ---

    # Tirith check — wrapper guarantees no raise for expected failures.
    # Only catch ImportError (module not installed).
    tirith_result = {"action": "allow", "findings": [], "summary": ""}
    try:
        from tools.tirith_security import check_command_security
        tirith_result = check_command_security(command)
    except ImportError:
        pass  # tirith module not installed — allow

    # Dangerous command check (detection only, no approval)
    is_dangerous, pattern_key, description = detect_dangerous_command(command)

    # --- Phase 2: Decide ---

    # Collect warnings that need approval
    warnings = []  # list of (pattern_key, description, is_tirith)

    # Tirith block/warn → approvable warning with rich findings.
    # Previously, tirith "block" was a hard block with no approval prompt.
    # Now both block and warn go through the approval flow so users can
    # inspect the explanation and approve if they understand the risk.
    if tirith_result["action"] in ("block", "warn"):
        findings = tirith_result.get("findings") or []
        rule_id = findings[0].get("rule_id", "unknown") if findings else "unknown"
        tirith_key = f"tirith:{rule_id}"
        tirith_desc = _format_tirith_description(tirith_result)
        if not is_approved(session_key, tirith_key):
            warnings.append((tirith_key, tirith_desc, True))

    if is_dangerous:
        if not is_approved(session_key, pattern_key):
            warnings.append((pattern_key, description, False))

    # Nothing to warn about
    if not warnings:
        return {"approved": True, "message": None}

    # --- Phase 2.5: Smart approval (auxiliary LLM risk assessment) ---
    # When approvals.mode=smart, ask the aux LLM before prompting the user.
    # Inspired by OpenAI Codex's Smart Approvals guardian subagent
    # (openai/codex#13860).
    if approval_mode == "smart":
        combined_desc_for_llm = "; ".join(desc for _, desc, _ in warnings)
        verdict = _smart_approve(command, combined_desc_for_llm)
        if verdict == "approve":
            # Auto-approve and grant session-level approval for these patterns
            for key, _, _ in warnings:
                approve_session(session_key, key)
            logger.debug("Smart approval: auto-approved '%s' (%s)",
                         command[:60], combined_desc_for_llm)
            return {"approved": True, "message": None,
                    "smart_approved": True,
                    "description": combined_desc_for_llm}
        elif verdict == "deny":
            combined_desc_for_llm = "; ".join(desc for _, desc, _ in warnings)
            return {
                "approved": False,
                "message": f"BLOCKED by smart approval: {combined_desc_for_llm}. "
                           "The command was assessed as genuinely dangerous. Do NOT retry.",
                "smart_denied": True,
            }
        # verdict == "escalate" → fall through to manual prompt

    # --- Phase 3: Approval ---

    # Combine descriptions for a single approval prompt
    combined_desc = "; ".join(desc for _, desc, _ in warnings)
    primary_key = warnings[0][0]
    all_keys = [key for key, _, _ in warnings]
    has_tirith = any(is_t for _, _, is_t in warnings)

    # Gateway/async approval — block the agent thread until the user
    # responds with /approve or /deny, mirroring the CLI's synchronous
    # input() flow.  The agent never sees "approval_required"; it either
    # gets the command output (approved) or a definitive "BLOCKED" message.
    if is_gateway or is_ask:
        notify_cb = None
        with _lock:
            notify_cb = _gateway_notify_cbs.get(session_key)

        if notify_cb is not None:
            # --- Blocking gateway approval (queue-based) ---
            # Each call gets its own _ApprovalEntry so parallel subagents
            # and execute_code threads can block concurrently.
            approval_data = {
                "command": command,
                "pattern_key": primary_key,
                "pattern_keys": all_keys,
                "description": combined_desc,
            }
            entry = _ApprovalEntry(approval_data)
            with _lock:
                _gateway_queues.setdefault(session_key, []).append(entry)

            # Notify the user (bridges sync agent thread → async gateway)
            try:
                notify_cb(approval_data)
            except Exception as exc:
                logger.warning("Gateway approval notify failed: %s", exc)
                with _lock:
                    queue = _gateway_queues.get(session_key, [])
                    if entry in queue:
                        queue.remove(entry)
                    if not queue:
                        _gateway_queues.pop(session_key, None)
                return {
                    "approved": False,
                    "message": "BLOCKED: Failed to send approval request to user. Do NOT retry.",
                    "pattern_key": primary_key,
                    "description": combined_desc,
                }

            # Block until the user responds or timeout (default 5 min).
            # Poll in short slices so we can fire activity heartbeats every
            # ~10s to the agent's inactivity tracker.  Without this, the
            # blocking event.wait() never touches activity, and the
            # gateway's inactivity watchdog (agent.gateway_timeout, default
            # 1800s) kills the agent while the user is still responding to
            # the approval prompt.  Mirrors the _wait_for_process() cadence
            # in tools/environments/base.py.
            timeout = _get_approval_config().get("gateway_timeout", 300)
            try:
                timeout = int(timeout)
            except (ValueError, TypeError):
                timeout = 300

            try:
                from tools.environments.base import touch_activity_if_due
            except Exception:  # pragma: no cover
                touch_activity_if_due = None

            _now = time.monotonic()
            _deadline = _now + max(timeout, 0)
            _activity_state = {"last_touch": _now, "start": _now}
            resolved = False
            while True:
                _remaining = _deadline - time.monotonic()
                if _remaining <= 0:
                    break
                # 1s poll slice — the event is set immediately when the
                # user responds, so slice length only controls heartbeat
                # cadence, not user-visible responsiveness.
                if entry.event.wait(timeout=min(1.0, _remaining)):
                    resolved = True
                    break
                if touch_activity_if_due is not None:
                    touch_activity_if_due(
                        _activity_state, "waiting for user approval"
                    )

            # Clean up this entry from the queue
            with _lock:
                queue = _gateway_queues.get(session_key, [])
                if entry in queue:
                    queue.remove(entry)
                if not queue:
                    _gateway_queues.pop(session_key, None)

            choice = entry.result
            if not resolved or choice is None or choice == "deny":
                reason = "timed out" if not resolved else "denied by user"
                return {
                    "approved": False,
                    "message": f"BLOCKED: Command {reason}. Do NOT retry this command.",
                    "pattern_key": primary_key,
                    "description": combined_desc,
                }

            # User approved — persist based on scope (same logic as CLI)
            for key, _, is_tirith in warnings:
                if choice == "session" or (choice == "always" and is_tirith):
                    approve_session(session_key, key)
                elif choice == "always":
                    approve_session(session_key, key)
                    approve_permanent(key)
                    save_permanent_allowlist(_permanent_approved)
                # choice == "once": no persistence — command allowed this
                # single time only, matching the CLI's behavior.

            return {"approved": True, "message": None,
                    "user_approved": True, "description": combined_desc}

        # Fallback: no gateway callback registered (e.g. cron, batch).
        # Return approval_required for backward compat.
        submit_pending(session_key, {
            "command": command,
            "pattern_key": primary_key,
            "pattern_keys": all_keys,
            "description": combined_desc,
        })
        return {
            "approved": False,
            "pattern_key": primary_key,
            "status": "approval_required",
            "command": command,
            "description": combined_desc,
            "message": (
                f"▲ {combined_desc}. Asking the user for approval.\n\n**Command:**\n```\n{command}\n```"
            ),
        }

    # CLI interactive: single combined prompt
    # Hide [a]lways when any tirith warning is present
    choice = prompt_dangerous_approval(command, combined_desc,
                                       allow_permanent=not has_tirith,
                                       approval_callback=approval_callback)

    if choice == "deny":
        return {
            "approved": False,
            "message": "BLOCKED: User denied. Do NOT retry.",
            "pattern_key": primary_key,
            "description": combined_desc,
        }

    # Persist approval for each warning individually
    for key, _, is_tirith in warnings:
        if choice == "session" or (choice == "always" and is_tirith):
            # tirith: session only (no permanent broad allowlisting)
            approve_session(session_key, key)
        elif choice == "always":
            # dangerous patterns: permanent allowed
            approve_session(session_key, key)
            approve_permanent(key)
            save_permanent_allowlist(_permanent_approved)

    return {"approved": True, "message": None,
            "user_approved": True, "description": combined_desc}


# Load permanent allowlist from config on module import
load_permanent_allowlist()
