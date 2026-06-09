"""
First-touch UI hints + user-name guardrails.

The legacy interview-style onboarding (where the agent asked nome / cargo /
personalidade / iniciativa on the first turn) was removed when the user
profile moved to the ector.cc backend (``GET /agent/auth/me`` populates
``config.user.*``; see :mod:`ector_cli.identity_auth`). What remains here:

1. **First-touch hint flags** — small one-liners that fire once per install
   the first time the user hits a behavior fork (message-while-busy, slow
   tool). Tracked via ``onboarding.seen.<flag>`` in
   ``config.yaml``; the section name is preserved for backward compatibility.
2. **User-name guardrail** — ``user_memory_blocks_assistant_alias_name``
   refuses ``memory(target='user')`` writes that would persist the assistant's
   identity ("Ector", "IA", "GPT", …) as the *user's* name.

Keep this module tiny and dependency-free so both the CLI and gateway can
import it without pulling in heavy modules.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

_INVALID_USER_NAMES = {
    "ector",
    "vetor",
    "assistant",
    "assistente",
    "agente",
    "ai",
    "ia",
    "chatgpt",
    "gpt",
}
_INVALID_USER_NAMES_NORMALIZED = {
    re.sub(r"[^a-z0-9]+", "", name.strip().lower()) for name in _INVALID_USER_NAMES
}


def _normalize_candidate_name(value: str) -> str:
    """Normalize candidate names for robust invalid-name checks."""
    lowered = (value or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "", lowered)


_USER_NAME_ASSIGNMENT_RE = re.compile(
    r"(?im)(?:"
    r"\bseu nome é\s+|\bnome\s*=\s*|\bme chame de\s+"
    r"|\byour name is\s+|\bname\s*=\s*|\bcall me\s+"
    r")([^\n§]+)"
)


def _user_explicitly_chose_ector_callname(text: str) -> bool:
    """True only when the user clearly opts into Ector/Vetor as their call name."""
    t = text or ""
    return bool(
        re.search(r"(?im)\bme chame de\s+(ector|vetor)\b", t)
        or re.search(r"(?im)\bcall me\s+(ector|vetor)\b", t)
    )


def user_memory_blocks_assistant_alias_name(content: str) -> Optional[str]:
    """If ``content`` would record a forbidden name as the user's name, return error text.

    Used by ``memory`` tool (target ``user``) to stop the model from persisting
    the assistant identity as the user's name. Returns ``None`` when allowed.
    """
    text = (content or "").strip()
    if not text:
        return None
    m = _USER_NAME_ASSIGNMENT_RE.search(text)
    if not m:
        return None
    candidate = m.group(1).strip().strip(".,;:!?\"'`()[]{}")
    normalized = _normalize_candidate_name(candidate)
    if not normalized or normalized not in _INVALID_USER_NAMES_NORMALIZED:
        return None
    if normalized in {"ector", "vetor"} and _user_explicitly_chose_ector_callname(text):
        return None
    return (
        "Recusado: não grave o nome do assistente (Ector, IA, GPT, assistente, etc.) "
        "como nome do usuário. O nome do usuário vem do perfil em ector.cc "
        "(config.user.nickname) e não deve ser sobrescrito a partir de fala "
        "do próprio agente."
    )


# -------------------------------------------------------------------------
# Flag names (stable — used as config.yaml keys under onboarding.seen)
# -------------------------------------------------------------------------

BUSY_INPUT_FLAG = "busy_input_prompt"
TOOL_PROGRESS_FLAG = "tool_progress_prompt"


# -------------------------------------------------------------------------
# Hint content
# -------------------------------------------------------------------------

def busy_input_hint_gateway(mode: str) -> str:
    """Hint shown the first time a user messages while the agent is busy.

    ``mode`` is the effective busy_input_mode that was just applied, so the
    message matches reality ("I just interrupted…" vs "I just queued…").
    """
    if mode == "queue":
        return (
            "💡 Dica de primeira vez — enfileirei sua mensagem em vez de interromper. "
            "Envie `/busy interrupt` para fazer novas mensagens pararem a tarefa atual "
            "imediatamente, ou `/busy status` para verificar. Este aviso não aparecerá novamente."
        )
    if mode == "steer":
        return (
            "💡 Dica de primeira vez — direcionei sua mensagem para a execução atual; "
            "ela chegará após a próxima chamada de ferramenta em vez de interromper. "
            "Envie `/busy interrupt` ou `/busy queue` para mudar isso, ou "
            "`/busy status` para verificar. Este aviso não aparecerá novamente."
        )
    return (
        "💡 Dica de primeira vez — acabei de interromper minha tarefa atual para responder a você. "
        "Envie `/busy queue` para enfileirar o acompanhamento para depois da tarefa atual, "
        "`/busy steer` para injetá-lo no meio da execução sem interromper, ou "
        "`/busy status` para verificar. Este aviso não aparecerá novamente."
    )


def busy_input_hint_cli(mode: str) -> str:
    """CLI version of the busy-input hint (plain text, no markdown)."""
    if mode == "queue":
        return (
            "(dica) Sua mensagem foi enfileirada para o próximo turno. "
            "Use /busy interrupt para fazer o Enter parar a execução atual, "
            "ou /busy steer para injetar no meio. Esta dica aparece apenas uma vez."
        )
    if mode == "steer":
        return (
            "(dica) Sua mensagem foi direcionada para a execução atual; ela chega "
            "após a próxima chamada de ferramenta. Use /busy interrupt ou /busy queue para "
            "mudar isso. Esta dica aparece apenas uma vez."
        )
    return (
        "(dica) Sua mensagem interrompeu a execução atual. "
        "Use /busy queue para enfileirar mensagens para o próximo turno, "
        "ou /busy steer para injetar no meio da execução. Esta dica aparece apenas uma vez."
    )


def tool_progress_hint_gateway() -> str:
    return (
        "💡 Dica de primeira vez — aquela ferramenta demorou um pouco e estou transmitindo cada passo. "
        "Se as mensagens de progresso parecerem barulhentas, envie `/verbose` para alternar os modos "
        "(all → new → off). Este aviso não aparecerá novamente."
    )


def tool_progress_hint_cli() -> str:
    return (
        "(dica) Aquela ferramenta rodou por um tempo. Use /verbose para alternar os modos de "
        "exibição do progresso (all -> new -> off -> verbose). Esta dica aparece apenas uma vez."
    )


# -------------------------------------------------------------------------
# State read / write
# -------------------------------------------------------------------------

def _get_seen_dict(config: Mapping[str, Any]) -> Mapping[str, Any]:
    onboarding = config.get("onboarding") if isinstance(config, Mapping) else None
    if not isinstance(onboarding, Mapping):
        return {}
    seen = onboarding.get("seen")
    return seen if isinstance(seen, Mapping) else {}


def is_seen(config: Mapping[str, Any], flag: str) -> bool:
    """Return True if the user has already been shown this first-touch hint."""
    return bool(_get_seen_dict(config).get(flag))


def mark_seen(config_path: Path, flag: str) -> bool:
    """Persist ``onboarding.seen.<flag> = True`` to ``config_path``.

    Uses the atomic YAML writer so a concurrent process can't observe a
    partially-written file.  Returns True on success, False on any error
    (including the config file being absent — onboarding is best-effort).
    """
    try:
        import yaml
        from utils import atomic_yaml_write
    except Exception as e:  # pragma: no cover — dependency issue
        logger.debug("onboarding: failed to import yaml/utils: %s", e)
        return False

    try:
        cfg: dict = {}
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        if not isinstance(cfg.get("onboarding"), dict):
            cfg["onboarding"] = {}
        seen = cfg["onboarding"].get("seen")
        if not isinstance(seen, dict):
            seen = {}
            cfg["onboarding"]["seen"] = seen
        if seen.get(flag) is True:
            return True  # already marked — nothing to do
        seen[flag] = True
        atomic_yaml_write(config_path, cfg)
        return True
    except Exception as e:
        logger.debug("onboarding: failed to mark flag %s: %s", flag, e)
        return False


__all__ = [
    "BUSY_INPUT_FLAG",
    "TOOL_PROGRESS_FLAG",
    "busy_input_hint_gateway",
    "busy_input_hint_cli",
    "tool_progress_hint_gateway",
    "tool_progress_hint_cli",
    "is_seen",
    "mark_seen",
    "user_memory_blocks_assistant_alias_name",
]
