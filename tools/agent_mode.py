"""Session-scoped agent mode (agent vs plan) for web chat."""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

_lock = threading.RLock()
_session_agent_mode: Dict[str, str] = {}

VALID_AGENT_MODES = frozenset({"agent", "plan"})

AGENT_MODE_LABELS = {
    "agent": "Agente",
    "plan": "Plano",
}

PLAN_MODE_EPHEMERAL_PROMPT = (
    "## Modo Plano (somente planejamento)\n"
    "Você está em **modo Plano**. O usuário quer ver um plano antes de qualquer execução.\n\n"
    "**Esta seção prevalece** sobre qualquer outra instrução de \"planejar e executar na "
    "mesma mensagem\" ou \"não pule ferramentas depois de planejar\".\n\n"
    "**Faça:**\n"
    "- Explore o contexto com ferramentas **somente de leitura** "
    "(ex.: `read_file`, `grep`, `search_files`, `glob`, pesquisa web, "
    "`browser_snapshot`, `browser_navigate`).\n"
    "- Na resposta final, coloque conversa e explicações **antes** da seção do plano.\n"
    "- O artefato gravado começa em **`## Plano`** — use exatamente esse heading.\n"
    "- Dentro de `## Plano`: objetivo, passos numerados, arquivos tocados, riscos e "
    "critérios de sucesso.\n"
    "- **Obrigatório:** termine **sempre** com `## Plano` e pelo menos **2 passos "
    "numerados**. Sem essa seção, o card **Plano pronto** não aparece.\n"
    "- Só essa seção `## Plano` é salva em `plans/<session_id>.md` e exibida no card "
    "**Plano pronto**.\n"
    "- `todo` é **opcional** e complementar — prefira passos numerados em `## Plano`.\n"
    "- Se usar `todo`, marque **todas** as etapas como `pending` (passos planejados). "
    "**Nunca** use `in_progress` nem `completed` neste modo.\n\n"
    "**Não faça:**\n"
    "- **Não chame** ferramentas de execução ou mutação — elas **não estão disponíveis** "
    "neste modo: `terminal`, `process`, `execute_code`, `write_file`, `patch`, "
    "`delegate_task`, `skill_manage`, `browser_click`, `browser_type`, "
    "`browser_scroll`, `browser_press`, `browser_dialog`, `browser_cdp`.\n"
    "- Para inspecionar disco ou listar arquivos use `read_file` / `grep` / `search_files` — "
    "**nunca** `terminal` nem `execute_code` (mesmo para \"só listar\").\n"
    "- Não execute comandos, não edite arquivos, não delegue subagentes "
    "e não use ações interativas no browser.\n"
    "- **Não implemente** mudanças neste turno.\n"
    "- Não diga que já aplicou mudanças; pare após entregar o plano.\n"
    "- Se precisar de dados que só viriam de uma tool bloqueada, descreva no plano "
    "o que o modo **Agente** deve executar depois — **não tente** a tool bloqueada.\n"
)

WEB_PLAN_MODE_UI_GUIDANCE = (
    "## Interface Ector (dashboard web — `ector`)\n"
    "O usuário controla o modo pela UI. Você **conhece** estes elementos — cite-os com precisão:\n\n"
    "1. **Seletor de modo** — rodapé do composer (abaixo do campo de mensagem), "
    "**à esquerda do nome do modelo**. Dropdown com **Plano** (ícone checklist) "
    "e **Agente** (ícone robô). É o controle principal para trocar o modo **antes** do próximo envio.\n"
    "2. **Card Executar plano** — após você entregar a seção `## Plano` neste turno, "
    "aparece um card **\"Plano pronto\"** com o botão **\"Executar plano\"** logo **acima** "
    "do composer. O texto da seção `## Plano` é salvo em **`plans/<session_id>.md`** "
    "(ex.: `~/.ector/plans/`) e exibido nesse card.\n"
    "3. **Continuar planejando** — no mesmo card, o usuário pode dispensar e seguir em Plano.\n\n"
    "**Quando uma tool de execução for bloqueada neste turno:**\n"
    "- Explique que o bloqueio é **esperado** em Modo Plano (não é bug) — **antes** de `## Plano`.\n"
    "- Continue o plano com leitura OU diga que o usuário pode clicar **Executar plano** "
    "(se o card já estiver visível) ou escolher **Agente** no dropdown e **enviar de novo**.\n"
    "- **Nunca** diga \"deve haver um botão/toggle por aí\" ou \"não sei onde fica na interface\".\n"
    "- Se o usuário disser que o dropdown já mostra **Agente**, o estado da sessão pode estar "
    "atrasado: peça para selecionar **Agente** outra vez no dropdown e reenviar, ou usar "
    "**Executar plano** após revisar o plano.\n"
)

CHAT_PLAN_MODE_UI_GUIDANCE = (
    "## Comandos nesta plataforma de chat (WhatsApp/Slack/Discord/Telegram/etc.)\n"
    "Não há dropdown nem card aqui — o usuário controla o modo por comandos de barra. "
    "Cite-os com precisão:\n\n"
    "1. **`/plan`** — ativa o modo Plano para esta sessão.\n"
    "2. **`/agent`** — volta ao modo Agente (execução normal) para esta sessão.\n\n"
    "**Quando uma tool de execução for bloqueada neste turno:**\n"
    "- Explique que o bloqueio é **esperado** em Modo Plano (não é bug) — **antes** de `## Plano`.\n"
    "- Diga que o usuário pode enviar `/agent` e depois reenviar o pedido (ou dizer para seguir "
    "em frente) para que você implemente o plano — **nunca** tente a tool bloqueada.\n"
)

PLAN_EXECUTE_USER_MESSAGE = (
    "O usuário aprovou o plano. Implemente o plano da sua última resposta "
    "passo a passo, executando as mudanças necessárias."
)

# Hard block: mutating / executing tools while in plan mode.
_PLAN_MODE_BLOCKED_TOOLS = frozenset(
    {
        "terminal",
        "process",
        "execute_code",
        "delegate_task",
        "write_file",
        "patch",
        "skill_manage",
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_press",
        "browser_dialog",
        "browser_cdp",
    }
)

_PLAN_MODE_BLOCK_MESSAGE = (
    "Modo Plano ativo: `{tool_name}` executa ou altera o sistema e está bloqueada "
    "neste turno. Use ferramentas de leitura, entregue o plano em markdown e "
    "indique que o usuário pode mudar para modo Agente para executar."
)

_WEB_PLAN_MODE_BLOCK_MESSAGE = (
    "Modo Plano: `{tool_name}` não está disponível — use apenas leitura "
    "(`read_file`, `grep`, `search_files`, etc.) e finalize a seção `## Plano`."
)


def plan_mode_blocked_tool_names() -> frozenset[str]:
    return _PLAN_MODE_BLOCKED_TOOLS


def _mcp_tool_names() -> frozenset[str]:
    """Tool names from connected MCP servers — unknown side effects, so Plan
    mode blocks all of them by default (deny-by-default for anything not on
    Ector's own reviewed builtin toolset)."""
    try:
        from tools.mcp_tool import get_registered_mcp_tool_names

        return get_registered_mcp_tool_names()
    except Exception:
        return frozenset()


def filter_tools_for_plan_mode(
    tool_definitions: list,
    session_key: str,
) -> list:
    """Remove execution/mutation tools from the model schema in plan mode.

    Also strips every MCP-provided tool: MCP server tools are arbitrary and
    external (a connected server could expose "send_email" or "delete_repo"
    under any name), so a fixed name-based blocklist can never account for
    them — they're excluded wholesale instead of allowlisted individually.
    """
    if not is_plan_mode(session_key):
        return tool_definitions
    blocked = _PLAN_MODE_BLOCKED_TOOLS | _mcp_tool_names()
    return [
        tool
        for tool in tool_definitions
        if (tool.get("function") or {}).get("name") not in blocked
    ]


def normalize_agent_mode(mode: Optional[str]) -> str:
    raw = (mode or "").strip().lower()
    if raw in VALID_AGENT_MODES:
        return raw
    return "agent"


def agent_mode_label(mode: Optional[str]) -> str:
    return AGENT_MODE_LABELS.get(normalize_agent_mode(mode), AGENT_MODE_LABELS["agent"])


def get_session_agent_mode(session_key: str) -> str:
    if not session_key:
        return "agent"
    with _lock:
        return normalize_agent_mode(_session_agent_mode.get(session_key))


def set_session_agent_mode(session_key: str, mode: str) -> str:
    normalized = normalize_agent_mode(mode)
    if not session_key:
        return normalized
    with _lock:
        if normalized == "agent":
            _session_agent_mode.pop(session_key, None)
        else:
            _session_agent_mode[session_key] = normalized
    return normalized


def clear_session_agent_mode(session_key: str) -> None:
    if not session_key:
        return
    with _lock:
        _session_agent_mode.pop(session_key, None)


def is_plan_mode(session_key: str) -> bool:
    return get_session_agent_mode(session_key) == "plan"


def format_plan_mode_block_message(
    tool_name: str,
    platform: Optional[str] = None,
) -> str:
    name = (tool_name or "tool").strip() or "tool"
    plat = (platform or "").strip().lower()
    template = _WEB_PLAN_MODE_BLOCK_MESSAGE if plat == "web" else _PLAN_MODE_BLOCK_MESSAGE
    return template.format(tool_name=name)


def get_plan_mode_block_message(
    session_key: str,
    tool_name: str,
    tool_args: Optional[Dict[str, Any]] = None,
    platform: Optional[str] = None,
) -> Optional[str]:
    key = (session_key or "").strip()
    if not key:
        try:
            from tools.approval import get_current_session_key

            key = get_current_session_key(default="")
        except Exception:
            key = ""
    if not key or not is_plan_mode(key):
        return None
    if tool_name == "memory":
        action = str((tool_args or {}).get("action") or "").strip().lower()
        if action in {"add", "replace", "remove"}:
            return format_plan_mode_block_message(tool_name, platform)
    if tool_name in _PLAN_MODE_BLOCKED_TOOLS or tool_name in _mcp_tool_names():
        return format_plan_mode_block_message(tool_name, platform)
    return None


def ephemeral_prompt_for_mode(
    mode: str,
    platform: Optional[str] = None,
) -> Optional[str]:
    if normalize_agent_mode(mode) != "plan":
        return None
    parts = [PLAN_MODE_EPHEMERAL_PROMPT]
    plat = (platform or "").strip().lower()
    if plat == "web":
        parts.append(WEB_PLAN_MODE_UI_GUIDANCE)
    elif plat:
        parts.append(CHAT_PLAN_MODE_UI_GUIDANCE)
    return "\n\n".join(parts)
