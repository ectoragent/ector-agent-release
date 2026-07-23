#!/usr/bin/env python3
"""
Toolsets Module

This module provides a flexible system for defining and managing tool aliases/toolsets.
Toolsets allow you to group tools together for specific scenarios and can be composed
from individual tools or other toolsets.

Features:
- Define custom toolsets with specific tools
- Compose toolsets from other toolsets
- Built-in common toolsets for typical use cases
- Easy extension for new toolsets
- Support for dynamic toolset resolution

Usage:
    from toolsets import get_toolset, resolve_toolset, get_all_toolsets
    
    # Get tools for a specific toolset
    tools = get_toolset("research")
    
    # Resolve a toolset to get all tool names (including from composed toolsets)
    all_tools = resolve_toolset("full_stack")
"""

from typing import List, Dict, Any, Set, Optional

from agent.tool_name_aliases import canonical_wiser_toolset_name


# Shared tool list for CLI and all messaging platform toolsets.
# Edit this once to update all platforms simultaneously.
_ECTOR_CORE_TOOLS = [
    # Web
    "web_search", "web_extract",
    # Terminal + process management
    "terminal", "process",
    # File manipulation
    "read_file", "write_file", "patch", "search_files",
    # Vision + image generation + document extraction
    "vision_analyze", "image_generate", "document_extract",
    # Skills
    "skills_list", "skill_view", "skill_manage",
    # Browser automation
    "browser_navigate", "browser_snapshot", "browser_click",
    "browser_type", "browser_scroll", "browser_back",
    "browser_press", "browser_get_images",
    "browser_vision", "browser_console", "browser_cdp", "browser_dialog",
    # Text-to-speech
    "text_to_speech",
    # Planning & memory
    "todo", "memory",
    # Session history search
    "session_search",
    # Chapter markers for the dashboard's floating table of contents
    "mark_chapter",
    # Wiser — pergunta ao usuário (decisão / lacuna de contexto)
    "wiser",
    # Code execution + delegation
    "execute_code", "delegate_task",
    # Cronjob management
    "cronjob",
    # Cross-platform messaging (gated on gateway running via check_fn)
    "send_message",
    # Gateway / messaging channel status (read-only)
    "gateway_inspect",
    # Home Assistant smart home control (gated on HASS_TOKEN via check_fn)
    "ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service",
]


# Core toolset definitions
# These can include individual tools or reference other toolsets
TOOLSETS = {
    # Basic toolsets - individual tool categories
    "web": {
        "description": "Pesquisar na internet e extrair conteúdo de páginas ou PDFs em texto utilizável.",
        "tools": ["web_search", "web_extract"],
        "includes": []  # No other toolsets included
    },
    
    "search": {
        "description": "Somente busca na web (sem extração ou scraping)",
        "tools": ["web_search"],
        "includes": []
    },
    
    "vision": {
        "description": "Analisar imagens enviadas ou capturadas — screenshots, diagramas, interfaces e documentos visuais.",
        "tools": ["vision_analyze"],
        "includes": []
    },

    "documents": {
        "description": "Extração local de documentos/OCR (PDF, imagens, tabelas)",
        "tools": ["document_extract"],
        "includes": [],
    },
    
    "image_gen": {
        "description": "Criar imagens a partir de prompts de texto com o provedor de imagem configurado.",
        "tools": ["image_generate"],
        "includes": []
    },
    
    "terminal": {
        "description": "Executar comandos no sistema e gerir processos em background (logs, cancelar, aguardar conclusão).",
        "tools": ["terminal", "process"],
        "includes": []
    },
    
    "moa": {
        "description": "Combinar várias perspectivas de modelos para problemas difíceis que beneficiam de raciocínio ampliado.",
        "tools": ["mixture_of_agents"],
        "includes": []
    },
    
    "skills": {
        "description": "Instalar, listar e editar skills — conhecimento e fluxos reutilizáveis para o agente.",
        "tools": ["skills_list", "skill_view", "skill_manage"],
        "includes": []
    },
    
    "browser": {
        "description": "Controlar um navegador real: abrir sites, interagir com elementos e capturar o estado de páginas dinâmicas.",
        "tools": [
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_scroll", "browser_back",
            "browser_press", "browser_get_images",
            "browser_vision", "browser_console", "browser_cdp",
            "browser_dialog", "web_search"
        ],
        "includes": []
    },

    # Registry toolset name for CDP passthrough tools (see tools/browser_cdp_tool.py).
    "browser-cdp": {
        "description": "CDP passthrough e diálogos nativos do navegador (requer endpoint CDP)",
        "tools": ["browser_cdp", "browser_dialog"],
        "includes": [],
    },
    
    "cronjob": {
        "description": "Criar e gerir tarefas automáticas que o agente executa num horário definido.",
        "tools": ["cronjob"],
        "includes": []
    },
    
    "messaging": {
        "description": "Enviar mensagens através do gateway (Telegram, Discord, Slack, SMS e outros canais).",
        "tools": ["send_message"],
        "includes": []
    },
    
    "rl": {
        "description": "Treinar e avaliar modelos com ambientes de reforço Tinker-Atropos.",
        "tools": [
            "rl_list_environments", "rl_select_environment",
            "rl_get_current_config", "rl_edit_config",
            "rl_start_training", "rl_check_status",
            "rl_stop_training", "rl_get_results",
            "rl_list_runs", "rl_test_inference"
        ],
        "includes": []
    },
    
    "file": {
        "description": "Ler, criar, editar e pesquisar ficheiros no projeto, com patches precisos e busca por conteúdo.",
        "tools": ["read_file", "write_file", "patch", "search_files"],
        "includes": []
    },
    
    "tts": {
        "description": "Converter respostas do agente em áudio (Edge TTS gratuito ou provedores premium).",
        "tools": ["text_to_speech"],
        "includes": []
    },
    
    "todo": {
        "description": "Manter listas de tarefas multi-passo visíveis durante execuções longas ou complexas.",
        "tools": ["todo"],
        "includes": []
    },
    
    "memory": {
        "description": "Guardar preferências, factos e contexto importante entre sessões e conversas.",
        "tools": ["memory"],
        "includes": []
    },
    
    "session_search": {
        "description": "Pesquisar no histórico local de chats por palavras-chave, tema ou trecho de conversa.",
        "tools": ["session_search"],
        "includes": []
    },

    "mark_chapter": {
        "description": "Marcar capítulos no índice flutuante do dashboard quando a conversa muda de fase.",
        "tools": ["mark_chapter"],
        "includes": []
    },

    "wiser": {
        "description": "Pedir confirmação ou escolha ao utilizador antes de ações sensíveis ou ambíguas.",
        "tools": ["wiser"],
        "includes": []
    },

    # Legacy configs: toolset ``ask_user`` (nome antigo da tool).
    "ask_user": {
        "description": "Alias antigo do Wiser (mesmas ferramentas)",
        "tools": [],
        "includes": ["wiser"],
    },
    
    "code_execution": {
        "description": "Correr Python que invoca outras ferramentas num único passo, reduzindo idas e voltas ao modelo.",
        "tools": ["execute_code"],
        "includes": []
    },
    
    "delegation": {
        "description": "Lançar subagentes com contexto isolado para subtarefas paralelas ou mais complexas.",
        "tools": ["delegate_task"],
        "includes": []
    },

    "homeassistant": {
        "description": "Monitorizar e controlar dispositivos de casa inteligente via Home Assistant.",
        "tools": ["ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service"],
        "includes": []
    },

    "discord": {
        "description": "Ler canais, pesquisar membros e participar em conversas no Discord.",
        "tools": ["discord"],
        "includes": [],
    },

    "discord_admin": {
        "description": "Administrar servidor Discord: canais, cargos, mensagens fixadas e moderação.",
        "tools": ["discord_admin"],
        "includes": [],
    },




    # Scenario-specific toolsets
    
    "debugging": {
        "description": "Kit de depuração e solução de problemas",
        "tools": ["terminal", "process"],
        "includes": ["web", "file"]  # For searching error messages and solutions, and file operations
    },
    
    "safe": {
        "description": "Kit seguro sem acesso ao terminal",
        "tools": [],
        "includes": ["web", "vision", "image_gen"]
    },
    
    # ==========================================================================
    # Full Ector toolsets (CLI + messaging platforms)
    #
    # All platforms share the same core tools (including send_message,
    # which is gated on gateway running via its check_fn).
    # ==========================================================================

    "ector-acp": {
        "description": "Integração com editores (VS Code, Zed, JetBrains): foco em código, sem mensagens, áudio ou Wiser",
        "tools": [
            "web_search", "web_extract",
            "terminal", "process",
            "read_file", "write_file", "patch", "search_files",
            "vision_analyze",
            "skills_list", "skill_view", "skill_manage",
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_scroll", "browser_back",
            "browser_press", "browser_get_images",
            "browser_vision", "browser_console", "browser_cdp", "browser_dialog",
            "todo", "memory",
            "session_search",
            "execute_code", "delegate_task",
        ],
        "includes": []
    },

    "ector-api-server": {
        "description": "Servidor de API compatível com OpenAI: ferramentas completas via HTTP (sem wiser nem send_message)",
        "tools": [
            # Web
            "web_search", "web_extract",
            # Terminal + process management
            "terminal", "process",
            # File manipulation
            "read_file", "write_file", "patch", "search_files",
            # Vision + image generation
            "vision_analyze", "image_generate",
            # Skills
            "skills_list", "skill_view", "skill_manage",
            # Browser automation
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_scroll", "browser_back",
            "browser_press", "browser_get_images",
            "browser_vision", "browser_console", "browser_cdp", "browser_dialog",
            # Planning & memory
            "todo", "memory",
            # Session history search
            "session_search",
            # Code execution + delegation
            "execute_code", "delegate_task",
            # Cronjob management
            "cronjob",
            # Home Assistant smart home control (gated on HASS_TOKEN via check_fn)
            "ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service",

        ],
        "includes": []
    },
    
    "ector-cli": {
        "description": "CLI interativa completa: ferramentas padrão + agendamentos cron",
        "tools": _ECTOR_CORE_TOOLS,
        "includes": []
    },

    "ector-cron": {
        # Mirrors ector-cli so cron's "default" toolset is the same set of
        # core tools users see interactively — then `ector tools` filters
        # them down per the platform config. _DEFAULT_OFF_TOOLSETS (moa,
        # homeassistant, rl) are excluded by _get_platform_tools() unless
        # the user explicitly enables them.
        "description": "Padrão para cron: mesmo núcleo que ector-cli; filtrado por `ector tools` conforme a plataforma",
        "tools": _ECTOR_CORE_TOOLS,
        "includes": []
    },

    "ector-telegram": {
        "description": "Bot Telegram: acesso completo (terminal com checagens de segurança)",
        "tools": _ECTOR_CORE_TOOLS,
        "includes": []
    },
    
    "ector-discord": {
        "description": "Bot Discord: acesso completo (aprovação para comandos perigosos no terminal)",
        "tools": _ECTOR_CORE_TOOLS + [
            "discord",
            "discord_admin",
        ],
        "includes": []
    },
    
    "ector-whatsapp": {
        "description": "Bot WhatsApp: mensagens pessoais (similar ao Telegram)",
        "tools": _ECTOR_CORE_TOOLS,
        "includes": []
    },
    
    "ector-slack": {
        "description": "Bot Slack: workspace completo (terminal com checagens de segurança)",
        "tools": _ECTOR_CORE_TOOLS,
        "includes": []
    },
    















    "ector-gateway": {
        "description": "União das ferramentas de todas as plataformas de mensagens do gateway",
        "tools": [],
        "includes": ["ector-telegram", "ector-discord", "ector-whatsapp", "ector-slack"]
    }
}

# (no legacy aliases)



def get_toolset(name: str) -> Optional[Dict[str, Any]]:
    """
    Get a toolset definition by name.
    
    Args:
        name (str): Name of the toolset
        
    Returns:
        Dict: Toolset definition with description, tools, and includes
        None: If toolset not found
    """
    name = canonical_wiser_toolset_name(name)
    toolset = TOOLSETS.get(name)
    if toolset:
        return toolset

    try:
        from tools.registry import registry
    except Exception:
        return None

    registry_toolset = name
    description = f"Conjunto do plugin: {name}"
    alias_target = registry.get_toolset_alias_target(name)

    if name not in _get_plugin_toolset_names():
        registry_toolset = alias_target
        if not registry_toolset:
            return None
        description = f"Ferramentas do servidor MCP «{name}»"
    else:
        reverse_aliases = {
            canonical: alias
            for alias, canonical in _get_registry_toolset_aliases().items()
            if alias not in TOOLSETS
        }
        alias = reverse_aliases.get(name)
        if alias:
            description = f"Ferramentas do servidor MCP «{alias}»"

    return {
        "description": description,
        "tools": registry.get_tool_names_for_toolset(registry_toolset),
        "includes": [],
    }


def resolve_toolset(name: str, visited: Set[str] = None) -> List[str]:
    """
    Recursively resolve a toolset to get all tool names.
    
    This function handles toolset composition by recursively resolving
    included toolsets and combining all tools.
    
    Args:
        name (str): Name of the toolset to resolve
        visited (Set[str]): Set of already visited toolsets (for cycle detection)
        
    Returns:
        List[str]: List of all tool names in the toolset
    """
    if visited is None:
        visited = set()

    name = canonical_wiser_toolset_name(name)

    # Special aliases that represent all tools across every toolset
    # This ensures future toolsets are automatically included without changes.
    if name in {"all", "*"}:
        all_tools: Set[str] = set()
        for toolset_name in get_toolset_names():
            # Use a fresh visited set per branch to avoid cross-branch contamination
            resolved = resolve_toolset(toolset_name, visited.copy())
            all_tools.update(resolved)
        return sorted(all_tools)

    # Check for cycles / already-resolved (diamond deps).
    # Silently return [] — either this is a diamond (not a bug, tools already
    # collected via another path) or a genuine cycle (safe to skip).
    if name in visited:
        return []

    visited.add(name)

    # Get toolset definition
    toolset = get_toolset(name)
    if not toolset:
        return []

    # Collect direct tools
    tools = set(toolset.get("tools", []))

    # Recursively resolve included toolsets, sharing the visited set across
    # sibling includes so diamond dependencies are only resolved once and
    # cycle warnings don't fire multiple times for the same cycle.
    for included_name in toolset.get("includes", []):
        included_tools = resolve_toolset(included_name, visited)
        tools.update(included_tools)
    
    return sorted(tools)


def resolve_multiple_toolsets(toolset_names: List[str]) -> List[str]:
    """
    Resolve multiple toolsets and combine their tools.
    
    Args:
        toolset_names (List[str]): List of toolset names to resolve
        
    Returns:
        List[str]: Combined list of all tool names (deduplicated)
    """
    all_tools = set()
    
    for name in toolset_names:
        tools = resolve_toolset(name)
        all_tools.update(tools)
    
    return sorted(all_tools)


def _get_plugin_toolset_names() -> Set[str]:
    """Return toolset names registered by plugins (from the tool registry).

    These are toolsets that exist in the registry but not in the static
    ``TOOLSETS`` dict — i.e. they were added by plugins at load time.
    """
    try:
        from tools.registry import registry
        return {
            toolset_name
            for toolset_name in registry.get_registered_toolset_names()
            if toolset_name not in TOOLSETS
        }
    except Exception:
        return set()


def _get_registry_toolset_aliases() -> Dict[str, str]:
    """Return explicit toolset aliases registered in the live registry."""
    try:
        from tools.registry import registry
        return registry.get_registered_toolset_aliases()
    except Exception:
        return {}


def get_all_toolsets() -> Dict[str, Dict[str, Any]]:
    """
    Get all available toolsets with their definitions.

    Includes both statically-defined toolsets and plugin-registered ones.
    
    Returns:
        Dict: All toolset definitions
    """
    result = dict(TOOLSETS)
    aliases = _get_registry_toolset_aliases()
    for ts_name in _get_plugin_toolset_names():
        display_name = ts_name
        for alias, canonical in aliases.items():
            if canonical == ts_name and alias not in TOOLSETS:
                display_name = alias
                break
        if display_name in result:
            continue
        toolset = get_toolset(display_name)
        if toolset:
            result[display_name] = toolset
    return result


def get_toolset_names() -> List[str]:
    """
    Get names of all available toolsets (excluding aliases).

    Includes plugin-registered toolset names.
    
    Returns:
        List[str]: List of toolset names
    """
    names = set(TOOLSETS.keys())
    aliases = _get_registry_toolset_aliases()
    for ts_name in _get_plugin_toolset_names():
        for alias, canonical in aliases.items():
            if canonical == ts_name and alias not in TOOLSETS:
                names.add(alias)
                break
        else:
            names.add(ts_name)
    return sorted(names)




def validate_toolset(name: str) -> bool:
    """
    Check if a toolset name is valid.
    
    Args:
        name (str): Toolset name to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    # Accept special alias names for convenience
    if name in {"all", "*"}:
        return True
    if name in TOOLSETS:
        return True
    if name in _get_plugin_toolset_names():
        return True
    return name in _get_registry_toolset_aliases()


def create_custom_toolset(
    name: str,
    description: str,
    tools: List[str] = None,
    includes: List[str] = None
) -> None:
    """
    Create a custom toolset at runtime.
    
    Args:
        name (str): Name for the new toolset
        description (str): Description of the toolset
        tools (List[str]): Direct tools to include
        includes (List[str]): Other toolsets to include
    """
    TOOLSETS[name] = {
        "description": description,
        "tools": tools or [],
        "includes": includes or []
    }




def get_toolset_info(name: str) -> Dict[str, Any]:
    """
    Get detailed information about a toolset including resolved tools.
    
    Args:
        name (str): Toolset name
        
    Returns:
        Dict: Detailed toolset information
    """
    toolset = get_toolset(name)
    if not toolset:
        return None
    
    resolved_tools = resolve_toolset(name)
    
    return {
        "name": name,
        "description": toolset["description"],
        "direct_tools": toolset["tools"],
        "includes": toolset["includes"],
        "resolved_tools": resolved_tools,
        "tool_count": len(resolved_tools),
        "is_composite": bool(toolset["includes"])
    }




if __name__ == "__main__":
    print("Demonstração do sistema de toolsets")
    print("=" * 60)
    
    print("\nConjuntos disponíveis:")
    print("-" * 40)
    for name, toolset in get_all_toolsets().items():
        info = get_toolset_info(name)
        composite = "[composto]" if info["is_composite"] else "[folha]"
        print(f"  {composite} {name:20} - {toolset['description']}")
        print(f"     Ferramentas: {len(info['resolved_tools'])} no total")
    
    print("\nExemplos de resolução de toolsets:")
    print("-" * 40)
    for name in ["web", "terminal", "safe", "debugging"]:
        tools = resolve_toolset(name)
        print(f"\n  {name}:")
        print(f"    Resolvido para {len(tools)} ferramentas: {', '.join(sorted(tools))}")
    
    print("\nResolução de vários toolsets:")
    print("-" * 40)
    combined = resolve_multiple_toolsets(["web", "vision", "terminal"])
    print("  Unindo ['web', 'vision', 'terminal']:")
    print(f"    Resultado: {', '.join(sorted(combined))}")
    
    print("\nCriação de toolset personalizado:")
    print("-" * 40)
    create_custom_toolset(
        name="my_custom",
        description="Toolset personalizado para tarefas específicas",
        tools=["web_search"],
        includes=["terminal", "vision"]
    )
    custom_info = get_toolset_info("my_custom")
    print("  Criado toolset 'my_custom':")
    print(f"    Descrição: {custom_info['description']}")
    print(f"    Ferramentas resolvidas: {', '.join(custom_info['resolved_tools'])}")
