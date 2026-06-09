"""CLI presentation — spinner, tool previews, inline diffs, activity labels.

Pure display functions and classes with no AIAgent dependency.
Used by AIAgent._execute_tool_calls for CLI feedback and by the TUI/web
dashboard for tool context strings.
"""

import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from difflib import unified_diff
from pathlib import Path

from agent.tool_name_aliases import canonical_wiser_tool_name
from utils import safe_json_loads

# ANSI escape codes for inline diff rendering and tool completion lines.
_RESET = "\033[0m"

logger = logging.getLogger(__name__)
_diff_colors_cached: dict[str, str] | None = None


def _diff_ansi() -> dict[str, str]:
    """Return ANSI escapes for inline diff display."""
    global _diff_colors_cached
    if _diff_colors_cached is not None:
        return _diff_colors_cached

    # Defaults that work on dark terminals
    dim = "\033[38;2;150;150;150m"
    file_c = "\033[38;2;180;160;255m"
    hunk = "\033[38;2;120;120;140m"
    minus = "\033[38;2;255;255;255;48;2;120;20;20m"
    plus = "\033[38;2;255;255;255;48;2;20;90;20m"

    _diff_colors_cached = {
        "dim": dim, "file": file_c, "hunk": hunk,
        "minus": minus, "plus": plus,
    }
    return _diff_colors_cached


def _diff_dim():   return _diff_ansi()["dim"]
def _diff_file():  return _diff_ansi()["file"]
def _diff_hunk():  return _diff_ansi()["hunk"]
def _diff_minus(): return _diff_ansi()["minus"]
def _diff_plus():  return _diff_ansi()["plus"]
_MAX_INLINE_DIFF_FILES = 6
_MAX_INLINE_DIFF_LINES = 80


@dataclass
class LocalEditSnapshot:
    """Pre-tool filesystem snapshot used to render diffs locally after writes."""
    paths: list[Path] = field(default_factory=list)
    before: dict[str, str | None] = field(default_factory=dict)

# =========================================================================
# Configurable tool preview length (0 = no limit)
# Set once at startup by CLI or gateway from display.tool_preview_length config.
# =========================================================================
_tool_preview_max_len: int = 0  # 0 = unlimited


def set_tool_preview_max_len(n: int) -> None:
    """Set the global max length for tool call previews. 0 = no limit."""
    global _tool_preview_max_len
    _tool_preview_max_len = max(int(n), 0) if n else 0


def get_tool_preview_max_len() -> int:
    """Return the configured max preview length (0 = unlimited)."""
    return _tool_preview_max_len


def get_skin_tool_prefix() -> str:
    """Optional prefix before tool completion lines (reserved; currently unused)."""
    return ""


def get_tool_emoji(tool_name: str, default: str = "⚡") -> str:
    """Return the registry emoji for *tool_name*, or *default* when unset."""
    try:
        from tools.registry import registry
        emoji = registry.get_emoji(tool_name, default="")
        if emoji:
            return emoji
    except Exception:
        pass
    return default


# Primary argument key per tool (shared by preview + technical summary).
_PRIMARY_TOOL_ARG_KEYS: dict[str, str] = {
    "web_search": "query", "web_extract": "urls",
    "read_file": "path", "write_file": "path", "patch": "path",
    "search_files": "pattern", "browser_navigate": "url",
    "browser_click": "ref", "browser_type": "text",
    "image_generate": "prompt", "text_to_speech": "text",
    "vision_analyze": "question", "mixture_of_agents": "user_prompt",
    "skill_view": "name", "skills_list": "category",
    "cronjob": "action",
    "execute_code": "code", "delegate_task": "goal",
    "wiser": "question",
    "ask_user": "question",
    "skill_manage": "name",
}

_PREVIEW_FALLBACK_ARG_KEYS = (
    "query", "text", "command", "path", "name", "prompt", "code", "goal",
)
_TECHNICAL_FALLBACK_ARG_KEYS = _PREVIEW_FALLBACK_ARG_KEYS + ("urls",)


# =========================================================================
# Tool preview (one-line summary of a tool call's primary argument)
# =========================================================================

def _oneline(text: str) -> str:
    """Collapse whitespace (including newlines) to single spaces."""
    return " ".join(text.split())


_IRREGULAR_INF_TO_GERUND = {
    "ser": "sendo",
    "ir": "indo",
    "ver": "vendo",
    "vir": "vindo",
    "ter": "tendo",
    "poder": "podendo",
    "fazer": "fazendo",
    "dizer": "dizendo",
    "trazer": "trazendo",
    "ler": "lendo",
    "pôr": "pondo",
    "por": "pondo",
    "caber": "cabendo",
}

_TRAILING_PUNCT_RE = re.compile(r"[.,:;!?).]+$")
_LEADING_SEPARATORS_RE = re.compile(r"^[\s,:–—-]+")


def _infinitive_to_gerund(inf: str) -> str | None:
    """Convert a Portuguese infinitive to a capitalized gerund label."""
    word = _TRAILING_PUNCT_RE.sub("", inf.lower().strip())
    if not word:
        return None
    if word in _IRREGULAR_INF_TO_GERUND:
        g = _IRREGULAR_INF_TO_GERUND[word]
        return g[0].upper() + g[1:]
    if word.endswith("ar") and len(word) > 2:
        return (word[:-2] + "ando").capitalize()
    if word.endswith("er") and len(word) > 2:
        return (word[:-2] + "endo").capitalize()
    if word.endswith("ir") and len(word) > 2:
        return (word[:-2] + "indo").capitalize()
    return None


def _is_gerund_word(word: str) -> bool:
    lower = _TRAILING_PUNCT_RE.sub("", word.lower())
    return len(lower) > 4 and lower.endswith(("ando", "endo", "indo"))


def _is_regular_infinitive(word: str) -> bool:
    lower = _TRAILING_PUNCT_RE.sub("", word.lower())
    return (
        len(lower) >= 4
        and re.search(r"(?:ar|er|ir)$", lower) is not None
        and not _is_gerund_word(word)
    )


def looks_like_literal_hint(text: str) -> bool:
    """Return True for paths, URLs and shell commands that must not be humanized."""
    t = text.strip()
    if not t:
        return True
    if re.match(r"^(https?://|/|\./|\.\./|~/|[A-Za-z]:\\)", t):
        return True
    if re.match(
        r"^(?:git|npm|pnpm|yarn|bun|python|pytest|curl|wget|ssh|docker)\s",
        t,
        re.I,
    ):
        return True
    if re.match(r"^[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,12}$", t):
        return True
    return False


def _soften_infinitive_prefix(text: str, prefix: str) -> str | None:
    m = re.match(rf"^{prefix}\s+(\S+)(.*)$", text, re.I)
    if not m:
        return None
    gerund = _infinitive_to_gerund(m.group(1))
    rest = _LEADING_SEPARATORS_RE.sub("", m.group(2))
    if gerund:
        return f"{gerund} {rest}".strip() if rest else gerund
    if rest:
        return rest[0].upper() + rest[1:] if rest[0].islower() else rest
    return None


def _soften_estou_prefix(text: str) -> str | None:
    m = re.match(r"^estou\s+(\S+)(.*)$", text, re.I)
    if not m:
        return None
    word = _TRAILING_PUNCT_RE.sub("", m.group(1))
    rest = _LEADING_SEPARATORS_RE.sub("", m.group(2))
    if not _is_gerund_word(word):
        return None
    label = word[0].upper() + word[1:]
    return f"{label} {rest}".strip() if rest else label


def _soften_bare_infinitive(text: str) -> str | None:
    m = re.match(r"^(\S+)(?:\s+(.*))?$", text)
    if not m:
        return None
    word = m.group(1)
    if not _is_regular_infinitive(word):
        return None
    gerund = _infinitive_to_gerund(word)
    if not gerund:
        return None
    rest = (m.group(2) or "").strip()
    return f"{gerund} {rest}" if rest else gerund


def polish_activity_label(text: str) -> str:
    """Normalize activity labels: concise pt-BR, gerund/objective tone, no repetitive ``Vou …``.

    Aligned with ``frontend/dashboard/src/lib/polishActivityLabel.ts``.
    """
    t = _oneline(str(text or "")).strip()
    if not t or looks_like_literal_hint(t):
        return t

    for candidate in (
        _soften_infinitive_prefix(t, "vou"),
        _soften_infinitive_prefix(t, "vamos"),
        _soften_estou_prefix(t),
        _soften_bare_infinitive(t),
    ):
        if candidate:
            return candidate

    if t[0].islower():
        return t[0].upper() + t[1:]
    return t


def _normalize_shell_alias(tool_name: str) -> str:
    """Treat legacy ``shell`` tool name as ``terminal`` for display."""
    return "terminal" if tool_name == "shell" else tool_name


def _describe_skill_manage_preview(args: dict) -> str:
    """User-facing preview for skill_manage actions."""
    action = str(args.get("action", "") or "").strip()
    name = _oneline(str(args.get("name", "") or "")).strip()
    action_labels = {
        "create": "criando skill",
        "edit": "editando skill",
        "patch": "aplicando patch em skill",
        "delete": "removendo skill",
        "write_file": "escrevendo arquivo em skill",
        "remove_file": "removendo arquivo de skill",
    }
    base = action_labels.get(action, "gerenciando skill")
    if name:
        return polish_activity_label(f"{base} {name}")
    return polish_activity_label(base)


def activity_first_person(text: str) -> str:
    """Backward-compatible alias for :func:`polish_activity_label`."""
    return polish_activity_label(text)


def _describe_terminal_activity(command: str) -> str:
    """Return a concise human-readable description for terminal activity."""
    cmd = _oneline(command).strip()
    if not cmd:
        return "executando um comando no terminal"

    lower = cmd.lower()

    if "curl " in lower or "wget " in lower:
        match = re.search(r"https?://([^/\s]+)", cmd)
        if match:
            return f"consultando {match.group(1)}"
        return "consultando um endpoint"
    if "grep " in lower or " rg " in f" {lower} ":
        return "filtrando os resultados"
    if "cat " in lower or "tail " in lower or "head " in lower:
        if ".log" in lower or "logs/" in lower:
            return "lendo logs"
        return "lendo arquivos"
    if "ps " in lower or "lsof " in lower or "top " in lower:
        return "verificando processos"
    if "find " in lower and ".git" in lower:
        return "procurando repositorios git"
    if "pwd" == lower or lower.startswith("pwd "):
        return "verificando diretorio atual"
    if "date" == lower or lower.startswith("date "):
        return "verificando o horario atual"
    if lower.startswith("ls ") or lower == "ls":
        return "listando arquivos"

    return "executando uma tarefa no terminal"


def _describe_terminal_command_heuristic(args: dict) -> str:
    """Infer a short label from the command only (ignores ``description``)."""
    cmd = _oneline(str(args.get("command", "") or "")).strip()
    if not cmd:
        return "executando um comando no terminal"

    parts = [p.strip() for p in re.split(r"\s*(?:&&|;)\s*", cmd) if p.strip()]
    action_part = ""
    for part in parts:
        lower = part.lower()
        if lower.startswith("cd ") or lower.startswith("export "):
            continue
        action_part = part
        break
    if not action_part:
        action_part = parts[-1] if parts else cmd

    lower = action_part.lower()
    git_map = (
        ("git status --porcelain", "analisando status do repositorio"),
        ("git status --short", "analisando status do repositorio"),
        ("git status", "analisando status do repositorio"),
        ("git diff --stat", "analisando resumo de alteracoes"),
        ("git diff", "comparando alteracoes no repositorio"),
        ("git log", "lendo historico de commits"),
        ("git add", "preparando arquivos para commit"),
        ("git commit", "criando commit no repositorio"),
        ("git push", "enviando alteracoes para o remoto"),
        ("git pull", "sincronizando repositorio local"),
        ("git fetch", "atualizando referencias do remoto"),
        ("git branch", "checando branches do repositorio"),
        ("git checkout", "alternando branch do repositorio"),
        ("git rebase", "reorganizando historico de commits"),
    )
    for prefix, label in git_map:
        if lower.startswith(prefix):
            return label

    if lower.startswith(("scripts/run_tests.sh", "pytest ", "python -m pytest", "npm test", "pnpm test")):
        return "executando testes do projeto"

    return _describe_terminal_activity(action_part)


def _describe_terminal_activity_from_args(args: dict) -> str:
    """User-facing line: model ``description`` verbatim, else heuristic from command."""
    desc = _oneline(str(args.get("description", "") or "")).strip()
    if desc:
        return polish_activity_label(desc)
    return polish_activity_label(_describe_terminal_command_heuristic(args))


def build_tool_preview(tool_name: str, args: dict, max_len: int | None = None) -> str | None:
    """Build a short preview of a tool call's primary argument for display.

    *max_len* controls truncation.  ``None`` (default) defers to the global
    ``_tool_preview_max_len`` set via config; ``0`` means unlimited.
    """
    tool_name = _normalize_shell_alias(canonical_wiser_tool_name(tool_name))
    if max_len is None:
        max_len = _tool_preview_max_len
    if not args:
        return None

    if tool_name == "skill_manage":
        return _describe_skill_manage_preview(args)

    if tool_name == "process":
        action = args.get("action", "")
        sid = args.get("session_id", "")
        data = args.get("data", "")
        timeout_val = args.get("timeout")
        parts = [action]
        if sid:
            parts.append(sid[:16])
        if data:
            parts.append(f'"{_oneline(data[:20])}"')
        if timeout_val and action == "wait":
            parts.append(f"{timeout_val}s")
        return " ".join(parts) if parts else None

    if tool_name == "todo":
        todos_arg = args.get("todos")
        merge = args.get("merge", False)
        if todos_arg is None:
            return polish_activity_label("lendo lista de tarefas")
        elif merge:
            return polish_activity_label(f"atualizando {len(todos_arg)} tarefa(s)")
        else:
            return polish_activity_label(f"planejando {len(todos_arg)} tarefa(s)")

    if tool_name == "session_search":
        query = _oneline(args.get("query", ""))
        return f"memória: \"{query[:25]}{'...' if len(query) > 25 else ''}\""

    if tool_name == "memory":
        action = args.get("action", "")
        target = args.get("target", "")
        if action == "add":
            content = _oneline(args.get("content", ""))
            return f"+{target}: \"{content[:25]}{'...' if len(content) > 25 else ''}\""
        elif action == "replace":
            old = _oneline(args.get("old_text") or "") or "<missing old_text>"
            return f"~{target}: \"{old[:20]}\""
        elif action == "remove":
            old = _oneline(args.get("old_text") or "") or "<missing old_text>"
            return f"-{target}: \"{old[:20]}\""
        return action

    if tool_name == "send_message":
        target = args.get("target", "?")
        msg = _oneline(args.get("message", ""))
        if len(msg) > 20:
            msg = msg[:17] + "..."
        return f"para {target}: \"{msg}\""

    if tool_name.startswith("rl_"):
        rl_previews = {
            "rl_list_environments": polish_activity_label("listando envs"),
            "rl_select_environment": args.get("name", ""),
            "rl_get_current_config": polish_activity_label("lendo config"),
            "rl_edit_config": f"{args.get('field', '')}={args.get('value', '')}",
            "rl_start_training": polish_activity_label("iniciando"),
            "rl_check_status": args.get("run_id", "")[:16],
            "rl_stop_training": polish_activity_label(f"parando {args.get('run_id', '')[:16]}"),
            "rl_get_results": args.get("run_id", "")[:16],
            "rl_list_runs": polish_activity_label("listando execuções"),
            "rl_test_inference": f"{args.get('num_steps', 3)} passos",
        }
        return rl_previews.get(tool_name)

    if tool_name == "terminal":
        return _describe_terminal_activity_from_args(args)

    key = _PRIMARY_TOOL_ARG_KEYS.get(tool_name)
    if not key:
        for fallback_key in _PREVIEW_FALLBACK_ARG_KEYS:
            if fallback_key in args:
                key = fallback_key
                break

    if not key or key not in args:
        return None

    value = args[key]
    if isinstance(value, list):
        value = value[0] if value else ""

    preview = _oneline(str(value))
    if not preview:
        return None
    if max_len > 0 and len(preview) > max_len:
        preview = preview[:max_len - 3] + "..."
    return preview


def build_tool_technical_summary(tool_name: str, args: dict, max_len: int = 160) -> str | None:
    """Compact ``tool: argument`` line for TUI secondary row (expand/collapse)."""
    tool_name = _normalize_shell_alias(canonical_wiser_tool_name(tool_name))
    if not args:
        return None

    def _clip(text: str) -> str:
        if max_len > 0 and len(text) > max_len:
            return text[: max_len - 3] + "..."
        return text

    if tool_name == "terminal":
        cmd = _oneline(str(args.get("command", "") or "")).strip()
        if cmd:
            return _clip(f"{tool_name}: {cmd}")
        return None

    if tool_name == "skill_manage":
        action = _oneline(str(args.get("action", "") or ""))
        name = _oneline(str(args.get("name", "") or ""))
        if action and name:
            return _clip(f"skill_manage: {action} {name}")
        if action:
            return _clip(f"skill_manage: {action}")
        return None

    key = _PRIMARY_TOOL_ARG_KEYS.get(tool_name)
    if not key:
        for fallback_key in _TECHNICAL_FALLBACK_ARG_KEYS:
            if fallback_key in args:
                key = fallback_key
                break

    if not key or key not in args:
        return None

    value = args[key]
    if isinstance(value, list):
        value = value[0] if value else ""
    preview = _oneline(str(value))
    if not preview:
        return None
    return _clip(f"{tool_name}: {preview}")


# =========================================================================
# Inline diff previews for write actions
# =========================================================================

def _resolved_path(path: str) -> Path:
    """Resolve a possibly-relative filesystem path against the current cwd."""
    candidate = Path(os.path.expanduser(path))
    if candidate.is_absolute():
        return candidate
    return Path.cwd() / candidate


def _snapshot_text(path: Path) -> str | None:
    """Return UTF-8 file content, or None for missing/unreadable files."""
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, UnicodeDecodeError, OSError):
        return None


def _display_diff_path(path: Path) -> str:
    """Prefer cwd-relative paths in diffs when available."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except Exception:
        return str(path)


def _resolve_skill_manage_paths(args: dict) -> list[Path]:
    """Resolve skill_manage write targets to filesystem paths."""
    action = args.get("action")
    name = args.get("name")
    if not action or not name:
        return []

    from tools.skill_manager_tool import _find_skill, _resolve_skill_dir

    if action == "create":
        skill_dir = _resolve_skill_dir(name, args.get("category"))
        return [skill_dir / "SKILL.md"]

    existing = _find_skill(name)
    if not existing:
        return []

    skill_dir = Path(existing["path"])
    if action in {"edit", "patch"}:
        file_path = args.get("file_path")
        return [skill_dir / file_path] if file_path else [skill_dir / "SKILL.md"]
    if action in {"write_file", "remove_file"}:
        file_path = args.get("file_path")
        return [skill_dir / file_path] if file_path else []
    if action == "delete":
        files = [path for path in sorted(skill_dir.rglob("*")) if path.is_file()]
        return files
    return []


def _resolve_local_edit_paths(tool_name: str, function_args: dict | None) -> list[Path]:
    """Resolve local filesystem targets for write-capable tools."""
    if not isinstance(function_args, dict):
        return []

    if tool_name == "write_file":
        path = function_args.get("path")
        return [_resolved_path(path)] if path else []

    if tool_name == "patch":
        path = function_args.get("path")
        return [_resolved_path(path)] if path else []

    if tool_name == "skill_manage":
        return _resolve_skill_manage_paths(function_args)

    return []


def capture_local_edit_snapshot(tool_name: str, function_args: dict | None) -> LocalEditSnapshot | None:
    """Capture before-state for local write previews."""
    paths = _resolve_local_edit_paths(tool_name, function_args)
    if not paths:
        return None

    snapshot = LocalEditSnapshot(paths=paths)
    for path in paths:
        snapshot.before[str(path)] = _snapshot_text(path)
    return snapshot


def _result_succeeded(result: str | None) -> bool:
    """Return True only when a tool JSON result clearly indicates success."""
    if not result:
        return False
    data = safe_json_loads(result)
    if not isinstance(data, dict):
        return False
    if data.get("error"):
        return False
    if "success" in data:
        return bool(data.get("success"))
    return False


def _diff_from_snapshot(snapshot: LocalEditSnapshot | None) -> str | None:
    """Generate unified diff text from a stored before-state and current files."""
    if not snapshot:
        return None

    chunks: list[str] = []
    for path in snapshot.paths:
        before = snapshot.before.get(str(path))
        after = _snapshot_text(path)
        if before == after:
            continue

        display_path = _display_diff_path(path)
        diff = "".join(
            unified_diff(
                [] if before is None else before.splitlines(keepends=True),
                [] if after is None else after.splitlines(keepends=True),
                fromfile=f"a/{display_path}",
                tofile=f"b/{display_path}",
            )
        )
        if diff:
            chunks.append(diff)

    if not chunks:
        return None
    return "".join(chunk if chunk.endswith("\n") else chunk + "\n" for chunk in chunks)


def extract_edit_diff(
    tool_name: str,
    result: str | None,
    *,
    function_args: dict | None = None,
    snapshot: LocalEditSnapshot | None = None,
) -> str | None:
    """Extract a unified diff from a file-edit tool result."""
    if tool_name == "patch" and result:
        data = safe_json_loads(result)
        if isinstance(data, dict):
            diff = data.get("diff")
            if isinstance(diff, str) and diff.strip():
                return diff

    if tool_name not in {"write_file", "patch", "skill_manage"}:
        return None
    if not _result_succeeded(result):
        return None
    return _diff_from_snapshot(snapshot)


def _emit_inline_diff(diff_text: str, print_fn) -> bool:
    """Emit rendered diff text through the CLI's prompt_toolkit-safe printer."""
    if print_fn is None or not diff_text:
        return False
    try:
        print_fn("  revisando diff")
        for line in diff_text.rstrip("\n").splitlines():
            print_fn(line)
        return True
    except Exception:
        return False


def _render_inline_unified_diff(diff: str) -> list[str]:
    """Render unified diff lines in Ector' inline transcript style."""
    rendered: list[str] = []
    from_file = None
    to_file = None

    for raw_line in diff.splitlines():
        if raw_line.startswith("--- "):
            from_file = raw_line[4:].strip()
            continue
        if raw_line.startswith("+++ "):
            to_file = raw_line[4:].strip()
            if from_file or to_file:
                rendered.append(f"{_diff_file()}{from_file or 'a/?'} → {to_file or 'b/?'}{_RESET}")
            continue
        if raw_line.startswith("@@"):
            rendered.append(f"{_diff_hunk()}{raw_line}{_RESET}")
            continue
        if raw_line.startswith("-"):
            rendered.append(f"{_diff_minus()}{raw_line}{_RESET}")
            continue
        if raw_line.startswith("+"):
            rendered.append(f"{_diff_plus()}{raw_line}{_RESET}")
            continue
        if raw_line.startswith(" "):
            rendered.append(f"{_diff_dim()}{raw_line}{_RESET}")
            continue
        if raw_line:
            rendered.append(raw_line)

    return rendered


def _split_unified_diff_sections(diff: str) -> list[str]:
    """Split a unified diff into per-file sections."""
    sections: list[list[str]] = []
    current: list[str] = []

    for line in diff.splitlines():
        if line.startswith("--- ") and current:
            sections.append(current)
            current = [line]
            continue
        current.append(line)

    if current:
        sections.append(current)

    return ["\n".join(section) for section in sections if section]


def _summarize_rendered_diff_sections(
    diff: str,
    *,
    max_files: int = _MAX_INLINE_DIFF_FILES,
    max_lines: int = _MAX_INLINE_DIFF_LINES,
) -> list[str]:
    """Render diff sections while capping file count and total line count."""
    sections = _split_unified_diff_sections(diff)
    rendered: list[str] = []
    omitted_files = 0
    omitted_lines = 0

    for idx, section in enumerate(sections):
        if idx >= max_files:
            omitted_files += 1
            omitted_lines += len(_render_inline_unified_diff(section))
            continue

        section_lines = _render_inline_unified_diff(section)
        remaining_budget = max_lines - len(rendered)
        if remaining_budget <= 0:
            omitted_lines += len(section_lines)
            omitted_files += 1
            continue

        if len(section_lines) <= remaining_budget:
            rendered.extend(section_lines)
            continue

        rendered.extend(section_lines[:remaining_budget])
        omitted_lines += len(section_lines) - remaining_budget
        omitted_files += 1 + max(0, len(sections) - idx - 1)
        for leftover in sections[idx + 1:]:
            omitted_lines += len(_render_inline_unified_diff(leftover))
        break

    if omitted_files or omitted_lines:
        summary = f"… omitidas {omitted_lines} linha(s) de diff"
        if omitted_files:
            summary += f" em {omitted_files} arquivo(s)/seção(ões) adicional(ais)"
        rendered.append(f"{_diff_hunk()}{summary}{_RESET}")

    return rendered


def render_edit_diff_with_delta(
    tool_name: str,
    result: str | None,
    *,
    function_args: dict | None = None,
    snapshot: LocalEditSnapshot | None = None,
    print_fn=None,
) -> bool:
    """Render an edit diff inline without taking over the terminal UI."""
    diff = extract_edit_diff(
        tool_name,
        result,
        function_args=function_args,
        snapshot=snapshot,
    )
    if not diff:
        return False
    try:
        rendered_lines = _summarize_rendered_diff_sections(diff)
    except Exception as exc:
        logger.debug("Could not render inline diff: %s", exc)
        return False
    return _emit_inline_diff("\n".join(rendered_lines), print_fn)


# =========================================================================
# CLI activity spinner (Braille dots; used by run_agent quiet mode)
# =========================================================================

_DOTS_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class KawaiiSpinner:
    """Animated Braille spinner for CLI feedback during tool/API waits."""

    THINKING_VERBS = (
        "Pensando…",
        "Analisando…",
        "Avaliando…",
        "Refletindo…",
    )

    @classmethod
    def get_thinking_verbs(cls) -> list[str]:
        """Portuguese verbs rotated on the thinking spinner."""
        return list(cls.THINKING_VERBS)

    def __init__(self, message: str = "", print_fn=None):
        self.message = message
        self.spinner_frames = _DOTS_FRAMES
        self.running = False
        self.thread = None
        self.frame_idx = 0
        self.start_time = None
        self.last_line_len = 0
        # Optional callable to route all output through (e.g. a no-op for silent
        # background agents).  When set, bypasses self._out entirely so that
        # agents with _print_fn overridden remain fully silent.
        self._print_fn = print_fn
        # Capture stdout NOW, before any redirect_stdout(devnull) from
        # child agents can replace sys.stdout with a black hole.
        self._out = sys.stdout

    def _write(self, text: str, end: str = '\n', flush: bool = False):
        """Write to the stdout captured at spinner creation time.

        If a print_fn was supplied at construction, all output is routed through
        it instead — allowing callers to silence the spinner with a no-op lambda.
        """
        if self._print_fn is not None:
            try:
                self._print_fn(text)
            except Exception:
                pass
            return
        try:
            self._out.write(text + end)
            if flush:
                self._out.flush()
        except (ValueError, OSError):
            pass

    @property
    def _is_tty(self) -> bool:
        """Check if output is a real terminal, safe against closed streams."""
        try:
            return hasattr(self._out, 'isatty') and self._out.isatty()
        except (ValueError, OSError):
            return False

    def _is_patch_stdout_proxy(self) -> bool:
        """Return True when stdout is prompt_toolkit's StdoutProxy.

        patch_stdout wraps sys.stdout in a StdoutProxy that queues writes and
        injects newlines around each flush().  The \\r overwrite never lands on
        the correct line — each spinner frame ends up on its own line.

        The CLI already drives a TUI widget (_spinner_text) for spinner display,
        so KawaiiSpinner's \\r-based animation is redundant under StdoutProxy.
        """
        try:
            from prompt_toolkit.patch_stdout import StdoutProxy
            return isinstance(self._out, StdoutProxy)
        except ImportError:
            return False

    def _animate(self):
        # When stdout is not a real terminal (e.g. Docker, systemd, pipe),
        # skip the animation entirely — it creates massive log bloat.
        # Just log the start once and let stop() log the completion.
        if not self._is_tty:
            self._write(f"  [tool] {self.message}", flush=True)
            while self.running:
                time.sleep(0.5)
            return

        # When running inside prompt_toolkit's patch_stdout context the CLI
        # renders spinner state via a dedicated TUI widget (_spinner_text).
        # Driving a \r-based animation here too causes visual overdraw: the
        # StdoutProxy injects newlines around each flush, so every frame lands
        # on a new line and overwrites the status bar.
        if self._is_patch_stdout_proxy():
            while self.running:
                time.sleep(0.1)
            return

        while self.running:
            if os.getenv("ECTOR_SPINNER_PAUSE"):
                time.sleep(0.1)
                continue
            frame = self.spinner_frames[self.frame_idx % len(self.spinner_frames)]
            elapsed = time.time() - self.start_time
            line = f"  {frame} {self.message} ({elapsed:.1f}s)"
            pad = max(self.last_line_len - len(line), 0)
            self._write(f"\r{line}{' ' * pad}", end='', flush=True)
            self.last_line_len = len(line)
            self.frame_idx += 1
            time.sleep(0.12)

    def start(self):
        if self.running:
            return
        self.running = True
        self.start_time = time.time()
        self.thread = threading.Thread(target=self._animate, daemon=True)
        self.thread.start()

    def update_text(self, new_message: str):
        self.message = new_message

    def print_above(self, text: str):
        """Print a line above the spinner without disrupting animation.

        Clears the current spinner line, prints the text, and lets the
        next animation tick redraw the spinner on the line below.
        Thread-safe: uses the captured stdout reference (self._out).
        Works inside redirect_stdout(devnull) because _write bypasses
        sys.stdout and writes to the stdout captured at spinner creation.
        """
        if not self.running:
            self._write(f"  {text}", flush=True)
            return
        # Clear spinner line with spaces (not \033[K) to avoid garbled escape
        # codes when prompt_toolkit's patch_stdout is active — same approach
        # as stop(). Then print text; spinner redraws on next tick.
        blanks = ' ' * max(self.last_line_len + 5, 40)
        self._write(f"\r{blanks}\r  {text}", flush=True)

    def stop(self, final_message: str = None):
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)

        is_tty = self._is_tty
        if is_tty:
            # Clear the spinner line with spaces instead of \033[K to avoid
            # garbled escape codes when prompt_toolkit's patch_stdout is active.
            blanks = ' ' * max(self.last_line_len + 5, 40)
            self._write(f"\r{blanks}\r", end='', flush=True)
        if final_message:
            elapsed = f" ({time.time() - self.start_time:.1f}s)" if self.start_time else ""
            if is_tty:
                self._write(f"  {final_message}", flush=True)
            else:
                self._write(f"  [done] {final_message}{elapsed}", flush=True)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


# =========================================================================
# Cute tool message (completion line that replaces the spinner)
# =========================================================================

def _format_error_suffix(err: object, *, max_len: int = 70) -> str:
    """Build a scrollback-safe `` [error] …`` suffix from a tool error field."""
    if err is None:
        return " [error]"
    if isinstance(err, dict):
        err = err.get("message") or err.get("detail") or json.dumps(err, ensure_ascii=False)
    text = str(err).replace("\n", " ").strip()
    if not text:
        return " [error]"
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return f" [error] {text}"


def _detect_tool_failure(tool_name: str, result: str | None) -> tuple[bool, str]:
    """Inspect a tool result string for signs of failure.

    Returns ``(is_failure, suffix)`` where *suffix* is an informational tag
    like ``" [exit 1]"`` for terminal failures, or ``" [error]"`` for generic
    failures.  On success, returns ``(False, "")``.
    """
    if result is None:
        return False, ""

    if tool_name == "terminal":
        data = safe_json_loads(result)
        if isinstance(data, dict):
            exit_code = data.get("exit_code")
            if exit_code is not None and exit_code != 0:
                return True, f" [exit {exit_code}]"
        return False, ""

    data = safe_json_loads(result)
    if isinstance(data, dict):
        if tool_name == "memory":
            if data.get("success") is False:
                err = str(data.get("error", ""))
                if "exceed the limit" in err:
                    return True, " [cheio]"
                return True, _format_error_suffix(data.get("error"))
            return False, ""

        if tool_name == "send_message":
            if data.get("success") is True:
                return False, ""
            if data.get("success") is False:
                return True, _format_error_suffix(data.get("error"))
            err = data.get("error")
            if err:
                return True, _format_error_suffix(err)
            return False, ""

        if data.get("success") is True:
            return False, ""
        if data.get("success") is False:
            return True, _format_error_suffix(data.get("error"))
        err = data.get("error")
        if err:
            return True, _format_error_suffix(err)
        if data.get("failed") is True:
            return True, " [error]"
        return False, ""

    if result.startswith("Error"):
        return True, " [error]"

    return False, ""


def get_cute_tool_message(
    tool_name: str, args: dict, duration: float, result: str | None = None,
) -> str:
    """Generate a formatted tool completion line for CLI quiet mode.

    Format: ``● {verb:9} {detail}  {duration}``

    When *result* is provided the line is checked for failure indicators.
    Failed tool calls append an informational suffix (e.g. `` [exit 1]``).
    """
    dur = f"{duration:.1f}s"
    tool_name = _normalize_shell_alias(canonical_wiser_tool_name(tool_name))
    is_failure, failure_suffix = _detect_tool_failure(tool_name, result)
    skin_prefix = get_skin_tool_prefix()

    def _clip_limit(default_max: int) -> int | None:
        """Return max chars for snippets, or None when preview length is unlimited."""
        if _tool_preview_max_len == 0:
            return None
        return min(default_max, _tool_preview_max_len)

    def _trunc(s, n=40):
        s = str(s)
        limit = _clip_limit(n)
        if limit is None:
            return s
        return (s[:limit - 3] + "...") if len(s) > limit else s

    def _path(p, n=35):
        p = str(p)
        limit = _clip_limit(n)
        if limit is None:
            return p
        return ("..." + p[-(limit - 3):]) if len(p) > limit else p

    type_colors = {
        "web": "\033[36m",
        "browser": "\033[94m",
        "file": "\033[92m",
        "process": "\033[96m",
        "memory": "\033[95m",
        "planning": "\033[93m",
        "skills": "\033[35m",
        "media": "\033[38;5;208m",
        "code": "\033[32m",
        "automation": "\033[33m",
        "terminal": "\033[38;5;111m",
        "default": "\033[90m",
    }

    def _kind(name: str) -> str:
        if name in {"web_search", "web_extract", "web_crawl", "session_search"}:
            return "web"
        if name.startswith("browser_"):
            return "browser"
        if name in {"read_file", "write_file", "patch", "search_files"}:
            return "file"
        if name in {"process"}:
            return "process"
        if name in {"memory"}:
            return "memory"
        if name in {"todo"}:
            return "planning"
        if name in {"skills_list", "skill_view", "skill_manage"}:
            return "skills"
        if name in {"image_generate", "text_to_speech", "vision_analyze"}:
            return "media"
        if name in {"execute_code"} or name.startswith("rl_"):
            return "code"
        if name in {"cronjob", "delegate_task", "mixture_of_agents", "send_message", "wiser", "ask_user"}:
            return "automation"
        if name == "terminal":
            return "terminal"
        return "default"

    def _wrap(line: str, kind: str | None = None) -> str:
        """Apply skin prefix, color and failure suffix."""
        if skin_prefix:
            line = line.strip()
            line = f"{skin_prefix} {line}"
        color = type_colors.get(kind or _kind(tool_name), type_colors["default"])
        marker = f"{color}●{_RESET}"
        line = f"{marker} {color}{line}{_RESET}"
        if not is_failure:
            return line
        return f"{line}{failure_suffix}"

    if tool_name == "web_search":
        return _wrap(f"pesquisa  {_trunc(args.get('query', ''), 42)}  {dur}", "web")
    if tool_name == "web_extract":
        urls = args.get("urls", [])
        if urls:
            url = urls[0] if isinstance(urls, list) else str(urls)
            domain = url.replace("https://", "").replace("http://", "").split("/")[0]
            extra = f" +{len(urls)-1}" if len(urls) > 1 else ""
            return _wrap(f"extração   {_trunc(domain, 35)}{extra}  {dur}", "web")
        return _wrap(f"extração   páginas  {dur}", "web")
    if tool_name == "web_crawl":
        url = args.get("url", "")
        domain = url.replace("https://", "").replace("http://", "").split("/")[0]
        return _wrap(f"rastreio   {_trunc(domain, 35)}  {dur}", "web")
    if tool_name == "terminal":
        cmd = str(args.get("command", "") or "")
        user_line = _describe_terminal_activity_from_args(args)
        success_detail = _trunc(user_line, 90)
        if is_failure:
            detail = _trunc(user_line, 90)
            cmd_detail = _trunc(cmd, 52) if cmd else "(sem comando)"
            return _wrap(f"{detail} · cmd: {cmd_detail}  {dur}", "terminal")
        return _wrap(f"{success_detail}  {dur}", "terminal")
    if tool_name == "process":
        action = args.get("action", "?")
        sid = args.get("session_id", "")[:12]
        labels = {
            "list": "listando processos",
            "poll": f"aguardando {sid}",
            "log": f"lendo log {sid}",
            "wait": f"aguardando {sid}",
            "kill": f"encerrando {sid}",
            "write": f"escrevendo {sid}",
            "submit": f"enviando {sid}",
        }
        return _wrap(f"Processo   {labels.get(action, f'{action} {sid}')}  {dur}", "process")
    if tool_name == "read_file":
        return _wrap(f"Lendo    {_path(args.get('path', ''))}  {dur}", "file")
    if tool_name == "write_file":
        return _wrap(f"Escrevendo    {_path(args.get('path', ''))}  {dur}", "file")
    if tool_name == "patch":
        return _wrap(f"patch      {_path(args.get('path', ''))}  {dur}", "file")
    if tool_name == "search_files":
        pattern = _trunc(args.get("pattern", ""), 35)
        target = args.get("target", "content")
        verb = "busca" if target == "files" else "filtro"
        return _wrap(f"{verb:9} {pattern}  {dur}", "file")
    if tool_name == "browser_navigate":
        url = args.get("url", "")
        domain = url.replace("https://", "").replace("http://", "").split("/")[0]
        return _wrap(f"navega     {_trunc(domain, 35)}  {dur}", "browser")
    if tool_name == "browser_snapshot":
        mode = "completa" if args.get("full") else "compacta"
        return _wrap(f"captura    {mode}  {dur}", "browser")
    if tool_name == "browser_click":
        return _wrap(f"clique     {args.get('ref', '?')}  {dur}", "browser")
    if tool_name == "browser_type":
        return _wrap(f"digita     \"{_trunc(args.get('text', ''), 30)}\"  {dur}", "browser")
    if tool_name == "browser_scroll":
        d = args.get("direction", "down")
        d_pt = {"down": "baixo", "up": "cima", "right": "direita", "left": "esquerda"}.get(d, d)
        return _wrap(f"rola       {d_pt}  {dur}", "browser")
    if tool_name == "browser_back":
        return _wrap(f"voltar     {dur}", "browser")
    if tool_name == "browser_press":
        return _wrap(f"tecla      {args.get('key', '?')}  {dur}", "browser")
    if tool_name == "browser_get_images":
        return _wrap(f"imagens    extraindo  {dur}", "browser")
    if tool_name == "browser_vision":
        return _wrap(f"visão      analisando página  {dur}", "browser")
    if tool_name == "todo":
        todos_arg = args.get("todos")
        merge = args.get("merge", False)
        if todos_arg is None:
            return _wrap(f"plano      lendo tarefas  {dur}", "planning")
        elif merge:
            return _wrap(f"plano      atualiza {len(todos_arg)} tarefa(s)  {dur}", "planning")
        else:
            return _wrap(f"plano      {len(todos_arg)} tarefa(s)  {dur}", "planning")
    if tool_name == "session_search":
        return _wrap(f"Checando histórico  \"{_trunc(args.get('query', ''), 35)}\"  {dur}", "web")
    if tool_name == "memory":
        action = args.get("action", "?")
        target = args.get("target", "")
        action_pt = {"add": "adiciona", "replace": "substitui", "remove": "remove"}.get(action, action)
        if action == "add":
            return _wrap(f"Adicionando memória    +{target}: \"{_trunc(args.get('content', ''), 30)}\"  {dur}", "memory")
        elif action == "replace":
            old = args.get("old_text") or ""
            old = old if old else "<texto antigo ausente>"
            return _wrap(f"memória    ~{target}: \"{_trunc(old, 20)}\"  {dur}", "memory")
        elif action == "remove":
            old = args.get("old_text") or ""
            old = old if old else "<texto antigo ausente>"
            return _wrap(f"memória    -{target}: \"{_trunc(old, 20)}\"  {dur}", "memory")
        return _wrap(f"memória    {action_pt}  {dur}", "memory")
    if tool_name == "skills_list":
        return _wrap(f"skills     lista {args.get('category', 'todas')}  {dur}", "skills")
    if tool_name == "skill_view":
        return _wrap(f"skill      {_trunc(args.get('name', ''), 30)}  {dur}", "skills")
    if tool_name == "skill_manage":
        action = args.get("action", "?")
        name = _trunc(args.get("name", ""), 30)
        action_pt = {
            "create": "cria",
            "edit": "edita",
            "patch": "patch",
            "delete": "remove",
            "write_file": "escreve",
            "remove_file": "remove arquivo",
        }
        verb = action_pt.get(action, action)
        detail = f"{verb} {name}".strip()
        return _wrap(f"skill      {detail}  {dur}", "skills")
    if tool_name == "image_generate":
        return _wrap(f"imagem     {_trunc(args.get('prompt', ''), 35)}  {dur}", "media")
    if tool_name == "text_to_speech":
        return _wrap(f"fala       {_trunc(args.get('text', ''), 30)}  {dur}", "media")
    if tool_name == "vision_analyze":
        return _wrap(f"visão      {_trunc(args.get('question', ''), 30)}  {dur}", "media")
    if tool_name == "mixture_of_agents":
        return _wrap(f"raciocina  {_trunc(args.get('user_prompt', ''), 30)}  {dur}", "automation")
    if tool_name == "send_message":
        return _wrap(f"envia      {args.get('target', '?')}: \"{_trunc(args.get('message', ''), 25)}\"  {dur}", "automation")
    if tool_name == "cronjob":
        action = args.get("action", "?")
        if action == "create":
            skills = args.get("skills") or ([] if not args.get("skill") else [args.get("skill")])
            label = args.get("name") or (skills[0] if skills else None) or args.get("prompt", "tarefa")
            return _wrap(f"cron       cria {_trunc(label, 24)}  {dur}", "automation")
        if action == "list":
            return _wrap(f"cron       listando  {dur}", "automation")
        return _wrap(f"cron       {action} {args.get('job_id', '')}  {dur}", "automation")
    if tool_name.startswith("rl_"):
        rl = {
            "rl_list_environments": "lista envs", "rl_select_environment": f"seleciona {args.get('name', '')}",
            "rl_get_current_config": "obter config", "rl_edit_config": f"define {args.get('field', '?')}",
            "rl_start_training": "inicia treino", "rl_check_status": f"status {args.get('run_id', '?')[:12]}",
            "rl_stop_training": f"para {args.get('run_id', '?')[:12]}", "rl_get_results": f"resultados {args.get('run_id', '?')[:12]}",
            "rl_list_runs": "lista execuções", "rl_test_inference": "testa inferência",
        }
        return _wrap(f"rl         {rl.get(tool_name, tool_name.replace('rl_', ''))}  {dur}", "code")
    if tool_name == "execute_code":
        code = args.get("code", "")
        first_line = code.strip().split("\n")[0] if code.strip() else ""
        return _wrap(f"exec       {_trunc(first_line, 35)}  {dur}", "code")
    if tool_name == "delegate_task":
        tasks = args.get("tasks")
        if tasks and isinstance(tasks, list):
            return _wrap(f"delega     {len(tasks)} tarefas paralelas  {dur}", "automation")
        return _wrap(f"delega     {_trunc(args.get('goal', ''), 35)}  {dur}", "automation")
    if tool_name in ("wiser", "ask_user"):
        # Question is shown in the Wiser UI; do not repeat it in activity lines.
        label = "wiser" if tool_name == "wiser" else "ask_user"
        return _wrap(f"{label:9} concluído  {dur}", "automation")

    preview = build_tool_preview(tool_name, args) or ""
    return _wrap(f"{tool_name[:9]:9} {_trunc(preview, 35)}  {dur}", "default")
