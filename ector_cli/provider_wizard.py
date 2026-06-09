"""Interactive provider and model selection wizard for CLI and setup."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from ector_constants import AI_GATEWAY_BASE_URL, OPENROUTER_BASE_URL

def select_provider_and_model(args=None):
    """Core provider selection + model picking logic.

    Shared by ``cmd_provider`` (``ector provider``) and the setup wizard
    (``setup_model_provider`` in setup.py).  Handles the full flow:
    provider picker, credential prompting, model selection, and config
    persistence.
    """
    from ector_cli.auth import (
        resolve_provider,
        AuthError,
    )
    from ector_cli.config import (
        get_compatible_custom_providers,
        load_config,
        get_env_value,
    )
    config = load_config()
    current_model = config.get("model")
    if isinstance(current_model, dict):
        current_model = current_model.get("default", "")
    current_model = current_model or "(not set)"

    from ector_cli.models import (
        CANONICAL_PROVIDERS,
        _PROVIDER_LABELS,
        provider_label,
        resolve_display_provider_id,
    )

    compatible_custom_providers = get_compatible_custom_providers(config)
    # Only reflect explicit config — not env auto-detect — so the status
    # line does not show a different provider than the one being configured.
    active = resolve_display_provider_id(config)

    provider_labels = dict(_PROVIDER_LABELS)  # derive from canonical list
    active_label = provider_label(active) if active else "(não configurado)"

    print()
    print(f"  Modelo atual:     {current_model}")
    print(f"  Provedor ativo:   {active_label}")
    print()

    # Step 1: Provider selection — flat list from CANONICAL_PROVIDERS
    all_providers = [(p.slug, p.tui_desc) for p in CANONICAL_PROVIDERS]

    def _named_custom_provider_map(cfg) -> dict[str, dict[str, str]]:
        from ector_cli.config import read_raw_config

        # Build a lookup of raw (un-expanded) api_key templates keyed by a
        # stable identity. We intentionally bypass
        # ``get_compatible_custom_providers(read_raw_config())`` here because
        # its ``_normalize_custom_provider_entry`` step calls ``urlparse()``
        # on ``base_url`` and drops any entry whose ``base_url`` is itself an
        # env-ref template (e.g. ``${NEURALWATT_API_BASE}``). Dropping those
        # entries is exactly how env-ref preservation fails for the user
        # config that motivated this fix.
        raw_api_key_refs: dict[tuple, str] = {}
        raw_cfg = read_raw_config()

        def _record_raw(
            name: str,
            provider_key: str,
            model: str,
            api_key: str,
        ) -> None:
            template = str(api_key or "").strip()
            if "${" not in template:
                return
            name = str(name or "").strip()
            provider_key = str(provider_key or "").strip()
            model = str(model or "").strip()
            # Index by every plausible identity the loaded (expanded) config
            # might present: (name), (name, model), (provider_key), and
            # (provider_key, model). Case-insensitive on name/provider_key so
            # the loaded entry matches regardless of display casing.
            if name:
                raw_api_key_refs.setdefault((name.lower(),), template)
                raw_api_key_refs.setdefault((name.lower(), model), template)
            if provider_key:
                raw_api_key_refs.setdefault((provider_key.lower(),), template)
                raw_api_key_refs.setdefault(
                    (provider_key.lower(), model), template
                )

        raw_list = raw_cfg.get("custom_providers")
        if isinstance(raw_list, list):
            for raw_entry in raw_list:
                if not isinstance(raw_entry, dict):
                    continue
                _record_raw(
                    raw_entry.get("name", ""),
                    "",
                    raw_entry.get("model", "")
                    or raw_entry.get("default_model", ""),
                    raw_entry.get("api_key", ""),
                )
        raw_providers = raw_cfg.get("providers")
        if isinstance(raw_providers, dict):
            for raw_key, raw_entry in raw_providers.items():
                if not isinstance(raw_entry, dict):
                    continue
                _record_raw(
                    raw_entry.get("name", "") or raw_key,
                    raw_key,
                    raw_entry.get("model", "")
                    or raw_entry.get("default_model", ""),
                    raw_entry.get("api_key", ""),
                )

        def _lookup_ref(name: str, provider_key: str, model: str) -> str:
            name_lc = str(name or "").strip().lower()
            pkey_lc = str(provider_key or "").strip().lower()
            model = str(model or "").strip()
            for identity in (
                (pkey_lc, model),
                (pkey_lc,),
                (name_lc, model),
                (name_lc,),
            ):
                if identity[0] and identity in raw_api_key_refs:
                    return raw_api_key_refs[identity]
            return ""

        custom_provider_map = {}
        for entry in get_compatible_custom_providers(cfg):
            if not isinstance(entry, dict):
                continue
            name = (entry.get("name") or "").strip()
            base_url = (entry.get("base_url") or "").strip()
            if not name or not base_url:
                continue
            key = "custom:" + name.lower().replace(" ", "-")
            provider_key = (entry.get("provider_key") or "").strip()
            if provider_key:
                try:
                    resolve_provider(provider_key)
                except AuthError:
                    key = provider_key
            custom_provider_map[key] = {
                "name": name,
                "base_url": base_url,
                "api_key": entry.get("api_key", ""),
                "key_env": entry.get("key_env", ""),
                "model": entry.get("model", ""),
                "api_mode": entry.get("api_mode", ""),
                "provider_key": provider_key,
                "api_key_ref": _lookup_ref(
                    name, provider_key, entry.get("model", "")
                ),
            }
        return custom_provider_map

    # Add user-defined custom providers from config.yaml
    _custom_provider_map = _named_custom_provider_map(
        config
    )  # key → {name, base_url, api_key}
    for key, provider_info in _custom_provider_map.items():
        name = provider_info["name"]
        base_url = provider_info["base_url"]
        short_url = base_url.replace("https://", "").replace("http://", "").rstrip("/")
        saved_model = provider_info.get("model", "")
        model_hint = f" — {saved_model}" if saved_model else ""
        all_providers.append((key, f"{name} ({short_url}){model_hint}"))

    # Build the menu
    ordered: list[tuple[str, str]] = []
    default_idx = 0
    for key, label in all_providers:
        if active and key == active:
            ordered.append((key, f"{label}  ← atualmente ativo"))
            default_idx = len(ordered) - 1
        else:
            ordered.append((key, label))

    # Note: "custom" isn't part of CANONICAL_PROVIDERS; append it explicitly.
    ordered.append(("custom", "Endpoint personalizado (digitar URL manualmente)"))
    if active == "custom":
        default_idx = len(ordered) - 1
    _has_saved_custom_list = isinstance(config.get("custom_providers"), list) and bool(
        config.get("custom_providers")
    )
    if _has_saved_custom_list:
        ordered.append(("remove-custom", "Remover um provedor personalizado salvo"))
    ordered.append(("aux-config", "Configurar modelos auxiliares..."))
    ordered.append(("cancel", "Deixar inalterado"))

    while True:
        provider_idx = _prompt_provider_choice(
            [label for _, label in ordered],
            default=default_idx,
        )
        if provider_idx is None or ordered[provider_idx][0] == "cancel":
            print("Nenhuma alteração.")
            return

        selected_provider = ordered[provider_idx][0]

        if selected_provider == "aux-config":
            _aux_config_menu()
            return

        # Step 2: Provider-specific setup + model selection
        if selected_provider == "openrouter":
            result = _model_flow_openrouter(config, current_model)
            if result == _BACK_TO_PROVIDER_MENU:
                continue
        elif selected_provider == "ai-gateway":
            result = _model_flow_ai_gateway(config, current_model)
            if result == _BACK_TO_PROVIDER_MENU:
                continue
        elif selected_provider == "openai-codex":
            _model_flow_openai_codex(config, current_model)
        elif selected_provider == "qwen-oauth":
            _model_flow_qwen_oauth(config, current_model)
        elif selected_provider == "google-gemini-cli":
            _model_flow_google_gemini_cli(config, current_model)
        elif selected_provider == "copilot-acp":
            _model_flow_copilot_acp(config, current_model)
        elif selected_provider == "copilot":
            _model_flow_copilot(config, current_model)
        elif selected_provider == "custom":
            _model_flow_custom(config)
        elif (
            selected_provider.startswith("custom:")
            or selected_provider in _custom_provider_map
        ):
            provider_info = _named_custom_provider_map(load_config()).get(selected_provider)
            if provider_info is None:
                print(
                    "Aviso: o provedor personalizado salvo selecionado não está mais disponível. "
                    "Ele pode ter sido removido do config.yaml. Nenhuma alteração."
                )
                return
            _model_flow_named_custom(config, provider_info)
        elif selected_provider == "remove-custom":
            _remove_custom_provider(config)
        elif selected_provider == "anthropic":
            _model_flow_anthropic(config, current_model)
        elif selected_provider == "kimi-coding":
            _model_flow_kimi(config, current_model)
        elif selected_provider == "stepfun":
            _model_flow_stepfun(config, current_model)
        elif selected_provider == "bedrock":
            _model_flow_bedrock(config, current_model)
        elif selected_provider == "azure-foundry":
            _model_flow_azure_foundry(config, current_model)
        elif selected_provider in (
            "openai",
            "gemini",
            "deepseek",
            "xai",
            "zai",
            "kimi-coding-cn",
            "minimax",
            "minimax-cn",
            "kilocode",
            "alibaba",
            "huggingface",
            "xiaomi",
            "arcee",
            "nvidia",
            "ollama-cloud",
        ):
            _model_flow_api_key_provider(config, selected_provider, current_model)

        break

    # ── Post-switch cleanup: clear stale OPENAI_BASE_URL ──────────────
    # When the user switches to a named provider (anything except "custom"),
    # a leftover OPENAI_BASE_URL in ~/.ector/.env can poison auxiliary
    # clients that use provider:auto. Clear it proactively.  (#5161)
    if selected_provider not in (
        "custom",
        "cancel",
        "remove-custom",
    ) and not selected_provider.startswith("custom:"):
        _clear_stale_openai_base_url()


def _clear_stale_openai_base_url():
    """Remove OPENAI_BASE_URL from ~/.ector/.env if the active provider is not 'custom'.

    After a provider switch, a leftover OPENAI_BASE_URL causes auxiliary
    clients (compression, vision, delegation) with provider:auto to route
    requests to the old custom endpoint instead of the newly selected
    provider.  See issue #5161.
    """
    from ector_cli.config import get_env_value, save_env_value, load_config

    cfg = load_config()
    model_cfg = cfg.get("model", {})
    if isinstance(model_cfg, dict):
        provider = (model_cfg.get("provider") or "").strip().lower()
    else:
        provider = ""

    if provider == "custom" or not provider:
        return  # custom provider legitimately uses OPENAI_BASE_URL

    stale_url = get_env_value("OPENAI_BASE_URL")
    if stale_url:
        save_env_value("OPENAI_BASE_URL", "")
        print(
            f"Limpou OPENAI_BASE_URL obsoleto do .env (era: {stale_url[:40]}...)"
            if len(stale_url) > 40
            else f"Limpou OPENAI_BASE_URL obsoleto do .env (era: {stale_url})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Auxiliary model configuration
#
# Ector uses lightweight "auxiliary" models for side tasks (vision analysis,
# context compression, web extraction, session search, etc.). Each task has
# its own provider+model pair in config.yaml under `auxiliary.<task>`.
#
# The UI lives behind "Configure auxiliary models..." at the bottom of the
# `ector provider` picker. It does NOT re-run credential setup — it
# only routes already-authenticated providers to specific aux tasks. Users
# configure new providers through the normal `ector provider` flow first.
# ─────────────────────────────────────────────────────────────────────────────

# (task_key, display_name, short_description)
_AUX_TASKS: list[tuple[str, str, str]] = [
    ("vision",           "Vision",           "image/screenshot analysis"),
    ("compression",      "Compression",      "context summarization"),
    ("web_extract",      "Web extract",      "web page summarization"),
    ("session_search",   "Session search",   "past-conversation recall"),
    ("approval",         "Approval",         "smart command approval"),
    ("mcp",              "MCP",              "MCP tool reasoning"),
    ("title_generation", "Title generation", "session titles"),
    ("skills_hub",       "Skills hub",       "skills search/install"),
]


def _format_aux_current(task_cfg: dict) -> str:
    """Render the current aux config for display in the task menu."""
    if not isinstance(task_cfg, dict):
        return "auto"
    base_url = str(task_cfg.get("base_url") or "").strip()
    provider = str(task_cfg.get("provider") or "auto").strip() or "auto"
    model = str(task_cfg.get("model") or "").strip()
    if base_url:
        short = base_url.replace("https://", "").replace("http://", "").rstrip("/")
        return f"custom ({short})" + (f" · {model}" if model else "")
    if provider == "auto":
        return "auto" + (f" · {model}" if model else "")
    if model:
        return f"{provider} · {model}"
    return provider


def _save_aux_choice(
    task: str,
    *,
    provider: str,
    model: str = "",
    base_url: str = "",
    api_key: str = "",
) -> None:
    """Persist an auxiliary task's provider/model to config.yaml.

    Only writes the four routing fields — timeout, download_timeout, and any
    other task-specific settings are preserved untouched. The main model
    config (``model.default``/``model.provider``) is never modified.
    """
    from ector_cli.config import load_config, save_config

    cfg = load_config()
    aux = cfg.setdefault("auxiliary", {})
    if not isinstance(aux, dict):
        aux = {}
        cfg["auxiliary"] = aux
    entry = aux.setdefault(task, {})
    if not isinstance(entry, dict):
        entry = {}
        aux[task] = entry
    entry["provider"] = provider
    entry["model"] = model or ""
    entry["base_url"] = base_url or ""
    entry["api_key"] = api_key or ""
    save_config(cfg)


def _reset_aux_to_auto() -> int:
    """Reset every known aux task back to auto/empty. Returns number reset."""
    from ector_cli.config import load_config, save_config

    cfg = load_config()
    aux = cfg.setdefault("auxiliary", {})
    if not isinstance(aux, dict):
        aux = {}
        cfg["auxiliary"] = aux
    count = 0
    for task, _name, _desc in _AUX_TASKS:
        entry = aux.setdefault(task, {})
        if not isinstance(entry, dict):
            entry = {}
            aux[task] = entry
        changed = False
        if entry.get("provider") not in (None, "", "auto"):
            entry["provider"] = "auto"
            changed = True
        for field in ("model", "base_url", "api_key"):
            if entry.get(field):
                entry[field] = ""
                changed = True
        # Preserve timeout/download_timeout — those are user-tuned, not routing
        if changed:
            count += 1
    save_config(cfg)
    return count


def _aux_config_menu() -> None:
    """Top-level auxiliary-model picker — choose a task to configure.

    Loops until the user picks "Back" so multiple tasks can be configured
    without returning to the main provider menu.
    """
    from ector_cli.config import load_config

    while True:
        cfg = load_config()
        aux = cfg.get("auxiliary", {}) if isinstance(cfg.get("auxiliary"), dict) else {}

        print()
        print("  Modelos auxiliares — roteamento de tarefas secundárias")
        print()
        print("  Tarefas secundárias (visão, compressão, extração web, etc.) usam por padrão")
        print("  seu modelo de chat principal. \"auto\" significa \"usar meu modelo principal\" —")
        print("  o Ector só recorre a um backend leve (OpenRouter,")
        print("  ector.cc) se o modelo principal estiver indisponível. Sobrescreva uma")
        print("  tarefa abaixo se quiser fixá-la em um provedor/modelo específico.")
        print()

        # Build the task menu with current settings inline
        name_col = max(len(name) for _, name, _ in _AUX_TASKS) + 2
        desc_col = max(len(desc) for _, _, desc in _AUX_TASKS) + 4
        entries: list[tuple[str, str]] = []
        for task_key, name, desc in _AUX_TASKS:
            task_cfg = aux.get(task_key, {}) if isinstance(aux.get(task_key), dict) else {}
            current = _format_aux_current(task_cfg)
            label = f"{name.ljust(name_col)}{('(' + desc + ')').ljust(desc_col)}{current}"
            entries.append((task_key, label))
        entries.append(("__reset__", "Redefinir todos para auto"))
        entries.append(("__back__",  "Voltar"))

        idx = _prompt_provider_choice(
            [label for _, label in entries], default=0,
        )
        if idx is None:
            return
        key = entries[idx][0]
        if key == "__back__":
            return
        if key == "__reset__":
            n = _reset_aux_to_auto()
            if n:
                print(f"Redefiniu {n} tarefa(s) auxiliares para auto.")
            else:
                print("Todas as tarefas auxiliares já estavam definidas como auto.")
            print()
            continue
        # Otherwise configure the specific task
        _aux_select_for_task(key)


def _aux_select_for_task(task: str) -> None:
    """Pick a provider + model for a single auxiliary task and persist it.

    Uses ``list_authenticated_providers()`` to only show providers the user
    has already configured. This avoids re-running OAuth/credential flows
    inside the aux picker — users set up new providers through the normal
    ``ector provider`` flow, then route aux tasks to them here.
    """
    from ector_cli.config import load_config
    from ector_cli.model_switch import list_authenticated_providers

    cfg = load_config()
    aux = cfg.get("auxiliary", {}) if isinstance(cfg.get("auxiliary"), dict) else {}
    task_cfg = aux.get(task, {}) if isinstance(aux.get(task), dict) else {}
    current_provider = str(task_cfg.get("provider") or "auto").strip() or "auto"
    current_model = str(task_cfg.get("model") or "").strip()
    current_base_url = str(task_cfg.get("base_url") or "").strip()

    display_name = next((name for key, name, _ in _AUX_TASKS if key == task), task)

    # Gather authenticated providers (has credentials + curated model list)
    try:
        providers = list_authenticated_providers(current_provider=current_provider)
    except Exception as exc:
        print(f"Could not detect authenticated providers: {exc}")
        providers = []

    entries: list[tuple[str, str, list[str]]] = []  # (slug, label, models)
    # "auto" always first
    auto_marker = "  ← atual" if current_provider == "auto" and not current_base_url else ""
    entries.append(("__auto__", f"auto (recomendado){auto_marker}", []))

    for p in providers:
        slug = p.get("slug", "")
        name = p.get("name") or slug
        total = p.get("total_models", 0)
        models = p.get("models") or []
        model_hint = f" — {total} models" if total else ""
        marker = "  ← atual" if slug == current_provider and not current_base_url else ""
        entries.append((slug, f"{name}{model_hint}{marker}", list(models)))

    # Custom endpoint (raw base_url)
    custom_marker = "  ← atual" if current_base_url else ""
    entries.append(("__custom__", f"Endpoint personalizado (URL direta){custom_marker}", []))
    entries.append(("__back__", "Voltar", []))

    print()
    print(f"  Configurar {display_name} — atual: {_format_aux_current(task_cfg)}")
    print()

    idx = _prompt_provider_choice([label for _, label, _ in entries], default=0)
    if idx is None:
        return
    slug, _label, models = entries[idx]

    if slug == "__back__":
        return

    if slug == "__auto__":
        _save_aux_choice(task, provider="auto", model="", base_url="", api_key="")
        print(f"{display_name}: redefinido para auto.")
        return

    if slug == "__custom__":
        _aux_flow_custom_endpoint(task, task_cfg)
        return

    # Regular provider — pick a model from its curated list
    _aux_flow_provider_model(task, slug, models, current_model)


def _aux_flow_provider_model(
    task: str,
    provider_slug: str,
    curated_models: list,
    current_model: str = "",
) -> None:
    """Prompt for a model under an already-authenticated provider, save to aux."""
    from ector_cli.auth import _prompt_model_selection
    from ector_cli.models import get_pricing_for_provider

    display_name = next((name for key, name, _ in _AUX_TASKS if key == task), task)

    # Fetch live pricing for this provider (non-blocking)
    pricing: dict = {}
    try:
        pricing = get_pricing_for_provider(provider_slug) or {}
    except Exception:
        pricing = {}

    model_list = list(curated_models)

    # Let the user pick a model. _prompt_model_selection supports "Enter custom
    # model name" and cancel.  When there's no curated list (rare), fall back
    # to a raw input prompt.
    if not model_list:
        print(f"Nenhuma lista de modelos curados para {provider_slug}.")
        print("Digite o slug do modelo manualmente (vazio = usar padrão do provedor):")
        try:
            val = input("Model: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return
        selected = val or ""
    else:
        selected = _prompt_model_selection(
            model_list, current_model=current_model, pricing=pricing,
        )
        if selected is None:
            print("Nenhuma alteração.")
            return

    _save_aux_choice(task, provider=provider_slug, model=selected or "",
                     base_url="", api_key="")
    if selected:
        print(f"{display_name}: {provider_slug} · {selected}")
    else:
        print(f"{display_name}: {provider_slug} (modelo padrão do provedor)")


def _aux_flow_custom_endpoint(task: str, task_cfg: dict) -> None:
    """Prompt for a direct OpenAI-compatible base_url + optional api_key/model."""
    import getpass

    display_name = next((name for key, name, _ in _AUX_TASKS if key == task), task)
    current_base_url = str(task_cfg.get("base_url") or "").strip()
    current_model = str(task_cfg.get("model") or "").strip()

    print()
    print(f"  Endpoint personalizado para {display_name}")
    print("  Forneça uma URL base compatível com OpenAI (ex: http://localhost:11434/v1)")
    print()
    try:
        url_prompt = f"Base URL [{current_base_url}]: " if current_base_url else "Base URL: "
        url = input(url_prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return
    url = url or current_base_url
    if not url:
        print("Nenhuma URL fornecida. Nenhuma alteração.")
        return
    try:
        model_prompt = f"Slug do modelo (opcional) [{current_model}]: " if current_model else "Slug do modelo (opcional): "
        model = input(model_prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return
    model = model or current_model
    try:
        api_key = getpass.getpass("Chave API (opcional, vazio = usar OPENAI_API_KEY): ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return

    _save_aux_choice(
        task, provider="custom", model=model, base_url=url, api_key=api_key,
    )
    short_url = url.replace("https://", "").replace("http://", "").rstrip("/")
    print(f"{display_name}: custom ({short_url})" + (f" · {model}" if model else ""))


def _prompt_provider_choice(choices, *, default=0):
    """Show provider selection menu with curses arrow-key navigation.

    Falls back to a numbered list when curses is unavailable (e.g. piped
    stdin, non-TTY environments).  Returns the selected index, or None
    if the user cancels.
    """
    try:
        from ector_cli.setup import _curses_prompt_choice

        idx = _curses_prompt_choice("Selecionar provedor:", choices, default)
        if idx >= 0:
            print()
            return idx
    except Exception:
        pass

    # Fallback: numbered list
    from ector_cli.colors import Colors, color

    print(color("Selecionar provedor:", Colors.CYAN, Colors.BOLD))
    for i, c in enumerate(choices, 1):
        marker = "→" if i - 1 == default else " "
        print(f"  {marker} {i}. {c}")
    print()
    while True:
        try:
            val = input(f"Escolha [1-{len(choices)}] ({default + 1}): ").strip()
            if not val:
                return default
            idx = int(val) - 1
            if 0 <= idx < len(choices):
                return idx
            print(f"Por favor, digite 1-{len(choices)}")
        except ValueError:
            print("Por favor, digite um número")
        except (KeyboardInterrupt, EOFError):
            print()
            return None


def _model_picker_identity_extras() -> dict:
    """Plan hints from identity cache for model picker (upgrade / locked models)."""
    try:
        from ector_cli.identity_auth import identity_model_picker_kwargs

        return identity_model_picker_kwargs()
    except Exception:
        return {}


def _model_flow_openrouter(config, current_model=""):
    """OpenRouter provider: ensure API key, then pick model."""
    from ector_cli.auth import (
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
    )
    from ector_cli.config import get_env_value, save_env_value

    api_key = get_env_value("OPENROUTER_API_KEY")
    if not api_key:
        print("Nenhuma chave API do OpenRouter configurada.")
        print("Obtenha uma em: https://openrouter.ai/keys")
        print()
        try:
            import getpass

            key = getpass.getpass("Chave API do OpenRouter (ou Enter para cancelar): ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return _BACK_TO_PROVIDER_MENU
        if not key:
            print("Cancelado.")
            return _BACK_TO_PROVIDER_MENU
        save_env_value("OPENROUTER_API_KEY", key)
        print("Chave API salva.")
        print()

    from ector_cli.models import model_ids, get_pricing_for_provider

    openrouter_models = model_ids(force_refresh=True)

    # Fetch live pricing (non-blocking — returns empty dict on failure)
    pricing = get_pricing_for_provider("openrouter", force_refresh=True)

    picker_kw = _model_picker_identity_extras()
    selected = _prompt_model_selection(
        openrouter_models,
        current_model=current_model,
        pricing=pricing,
        unavailable_models=picker_kw.get("unavailable_models"),
        portal_url=picker_kw.get("portal_url", ""),
    )
    if selected:
        _save_model_choice(selected)

        # Update config provider and deactivate any OAuth provider
        from ector_cli.config import load_config, save_config

        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = "openrouter"
        model["base_url"] = OPENROUTER_BASE_URL
        model["api_mode"] = "chat_completions"
        save_config(cfg)
        deactivate_provider()
        print(f"Modelo padrão definido para: {selected} (via OpenRouter)")
    else:
        print("Nenhuma alteração.")
        return _BACK_TO_PROVIDER_MENU


def _model_flow_ai_gateway(config, current_model=""):
    """Vercel AI Gateway provider: ensure API key, then pick model with pricing."""
    from ector_cli.auth import (
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
    )
    from ector_cli.config import get_env_value, save_env_value

    api_key = get_env_value("AI_GATEWAY_API_KEY")
    if not api_key:
        print("Nenhuma chave API do Vercel AI Gateway configurada.")
        print("Crie uma chave API aqui: https://vercel.com/d?to=%2F%5Bteam%5D%2F%7E%2Fai-gateway&title=AI+Gateway")
        print("Adicione um método de pagamento para ganhar $5 em créditos gratuitos.")
        print()
        try:
            import getpass

            key = getpass.getpass("Chave API do AI Gateway (ou Enter para cancelar): ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return
        if not key:
            print("Cancelado.")
            return
        save_env_value("AI_GATEWAY_API_KEY", key)
        print("Chave API salva.")
        print()

    from ector_cli.models import ai_gateway_model_ids, get_pricing_for_provider

    models_list = ai_gateway_model_ids(force_refresh=True)
    pricing = get_pricing_for_provider("ai-gateway", force_refresh=True)

    selected = _prompt_model_selection(
        models_list, current_model=current_model, pricing=pricing
    )
    if selected:
        _save_model_choice(selected)

        from ector_cli.config import load_config, save_config

        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = "ai-gateway"
        model["base_url"] = AI_GATEWAY_BASE_URL
        model["api_mode"] = "chat_completions"
        save_config(cfg)
        deactivate_provider()
        print(f"Modelo padrão definido para: {selected} (via Vercel AI Gateway)")
    else:
        print("Nenhuma alteração.")



def _model_flow_openai_codex(config, current_model=""):
    """OpenAI Codex provider: ensure logged in, then pick model."""
    from ector_cli.auth import (
        get_codex_auth_status,
        _prompt_model_selection,
        _save_model_choice,
        _update_config_for_provider,
        _login_openai_codex,
        PROVIDER_REGISTRY,
        DEFAULT_CODEX_BASE_URL,
    )
    from ector_cli.codex_models import get_codex_model_ids

    status = get_codex_auth_status()
    if status.get("logged_in"):
        print("  Credenciais do OpenAI Codex: ✔")
        print()
        print("    1. Usar credenciais existentes")
        print("    2. Reautenticar (novo login OAuth)")
        print("    3. Cancelar")
        print()
        try:
            choice = input("  Escolha [1/2/3]: ").strip()
        except (KeyboardInterrupt, EOFError):
            choice = "1"

        if choice == "2":
            print("Iniciando um novo login no OpenAI Codex...")
            print()
            try:
                mock_args = argparse.Namespace()
                _login_openai_codex(
                    mock_args,
                    PROVIDER_REGISTRY["openai-codex"],
                    force_new_login=True,
                )
            except SystemExit:
                print("Login cancelado ou falhou.")
                return
            except Exception as exc:
                print(f"Login falhou: {exc}")
                return
            status = get_codex_auth_status()
            if not status.get("logged_in"):
                print("Login falhou.")
                return
        elif choice == "3":
            return
    else:
        print("Não logado no OpenAI Codex. Iniciando login...")
        print()
        try:
            mock_args = argparse.Namespace()
            _login_openai_codex(mock_args, PROVIDER_REGISTRY["openai-codex"])
        except SystemExit:
            print("Login cancelado ou falhou.")
            return
        except Exception as exc:
            print(f"Login falhou: {exc}")
            return

    _codex_token = None
    # Prefer credential pool (where `ector auth` stores device_code tokens),
    # fall back to legacy provider state.
    try:
        _codex_status = get_codex_auth_status()
        if _codex_status.get("logged_in"):
            _codex_token = _codex_status.get("api_key")
    except Exception:
        pass
    if not _codex_token:
        try:
            from ector_cli.auth import resolve_codex_runtime_credentials

            _codex_creds = resolve_codex_runtime_credentials()
            _codex_token = _codex_creds.get("api_key")
        except Exception:
            pass

    codex_models = get_codex_model_ids(access_token=_codex_token)

    selected = _prompt_model_selection(codex_models, current_model=current_model)
    if selected:
        _save_model_choice(selected)
        _update_config_for_provider("openai-codex", DEFAULT_CODEX_BASE_URL)
        print(f"Modelo padrão definido para: {selected} (via OpenAI Codex)")
    else:
        print("Nenhuma alteração.")


_DEFAULT_QWEN_PORTAL_MODELS = [
    "qwen3-coder-plus",
    "qwen3-coder",
]


def _model_flow_qwen_oauth(_config, current_model=""):
    """Qwen OAuth provider: reuse local Qwen CLI login, then pick model."""
    from ector_cli.auth import (
        get_qwen_auth_status,
        resolve_qwen_runtime_credentials,
        _prompt_model_selection,
        _save_model_choice,
        _update_config_for_provider,
        DEFAULT_QWEN_BASE_URL,
    )
    from ector_cli.models import fetch_api_models

    status = get_qwen_auth_status()
    if not status.get("logged_in"):
        print("Não logado no Qwen CLI OAuth.")
        print("Execute: qwen auth qwen-oauth")
        auth_file = status.get("auth_file")
        if auth_file:
            print(f"Arquivo de credenciais esperado: {auth_file}")
        if status.get("error"):
            print(f"Erro: {status.get('error')}")
        return

    # Try live model discovery, fall back to curated list.
    models = None
    try:
        creds = resolve_qwen_runtime_credentials(refresh_if_expiring=True)
        models = fetch_api_models(creds["api_key"], creds["base_url"])
    except Exception:
        pass
    if not models:
        models = list(_DEFAULT_QWEN_PORTAL_MODELS)

    default = current_model or (models[0] if models else "qwen3-coder-plus")
    selected = _prompt_model_selection(models, current_model=default)
    if selected:
        _save_model_choice(selected)
        _update_config_for_provider("qwen-oauth", DEFAULT_QWEN_BASE_URL)
        print(f"Modelo padrão definido para: {selected} (via Qwen OAuth)")
    else:
        print("Nenhuma alteração.")


def _model_flow_google_gemini_cli(_config, current_model=""):
    """Google Gemini OAuth (PKCE) via Cloud Code Assist — supports free AND paid tiers.

    Flow:
      1. Show upfront warning about Google's ToS stance (per public reverse-engineered OAuth flows).
      2. If creds missing, run PKCE browser OAuth via agent.google_oauth.
      3. Resolve project context (env -> config -> auto-discover -> free tier).
      4. Prompt user to pick a model.
      5. Save to ~/.ector/config.yaml.
    """
    from ector_cli.auth import (
        DEFAULT_GEMINI_CLOUDCODE_BASE_URL,
        get_gemini_oauth_auth_status,
        resolve_gemini_oauth_runtime_credentials,
        _prompt_model_selection,
        _save_model_choice,
        _update_config_for_provider,
    )
    from ector_cli.models import _PROVIDER_MODELS

    print()
    print("▲  O Google considera o uso do cliente Gemini CLI OAuth com software")
    print("   de terceiros uma violação de política. Alguns usuários relataram")
    print("   restrições de conta. Você pode usar sua própria chave API através")
    print("   do provedor 'gemini' para a experiência de menor risco.")
    print()
    try:
        proceed = input("Continuar com o login OAuth? (s/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("Cancelado.")
        return
    if proceed not in {"s", "sim", "y", "yes"}:
        print("Cancelado.")
        return

    status = get_gemini_oauth_auth_status()
    if not status.get("logged_in"):
        try:
            from agent.google_oauth import resolve_project_id_from_env, start_oauth_flow

            env_project = resolve_project_id_from_env()
            start_oauth_flow(force_relogin=True, project_id=env_project)
        except Exception as exc:
            print(f"Login OAuth falhou: {exc}")
            return

    # Verify creds resolve + trigger project discovery
    try:
        creds = resolve_gemini_oauth_runtime_credentials(force_refresh=False)
        project_id = creds.get("project_id", "")
        if project_id:
            print(f"  Usando projeto GCP: {project_id}")
        else:
            print(
                "  Nenhum projeto GCP configurado — o nível gratuito será provisionado automaticamente no primeiro pedido."
            )
    except Exception as exc:
        print(f"Falha ao resolver credenciais do Gemini: {exc}")
        return

    models = list(_PROVIDER_MODELS.get("google-gemini-cli") or [])
    default = current_model or (models[0] if models else "gemini-3-flash-preview")
    selected = _prompt_model_selection(models, current_model=default)
    if selected:
        _save_model_choice(selected)
        _update_config_for_provider(
            "google-gemini-cli", DEFAULT_GEMINI_CLOUDCODE_BASE_URL
        )
        print(
            f"Modelo padrão definido para: {selected} (via Google Gemini OAuth / Code Assist)"
        )
    else:
        print("Nenhuma alteração.")


def _model_flow_custom(config):
    """Custom endpoint: collect URL, API key, and model name.

    Automatically saves the endpoint to ``custom_providers`` in config.yaml
    so it appears in the provider menu on subsequent runs.
    """
    from ector_cli.auth import _save_model_choice, deactivate_provider
    from ector_cli.config import get_env_value, load_config, save_config

    current_url = get_env_value("OPENAI_BASE_URL") or ""
    current_key = get_env_value("OPENAI_API_KEY") or ""

    print("Configuração de endpoint compatível com OpenAI personalizado:")
    if current_url:
        print(f"  URL atual: {current_url}")
    if current_key:
        print(f"  Chave atual: {current_key[:8]}...")
    print()

    try:
        base_url = input(
            f"API base URL [{current_url or 'e.g. https://api.example.com/v1'}]: "
        ).strip()
        import getpass

        api_key = getpass.getpass(
            f"API key [{current_key[:8] + '...' if current_key else 'optional'}]: "
        ).strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return

    if not base_url and not current_url:
        print("Nenhuma URL fornecida. Cancelado.")
        return

    # Validate URL format
    effective_url = base_url or current_url
    if not effective_url.startswith(("http://", "https://")):
        print(f"Invalid URL: {effective_url} (must start with http:// or https://)")
        return

    effective_key = api_key or current_key

    # Hint: most local model servers (Ollama, vLLM, llama.cpp) require /v1
    # in the base URL for OpenAI-compatible chat completions.  Prompt the
    # user if the URL looks like a local server without /v1.
    _url_lower = effective_url.rstrip("/").lower()
    _looks_local = any(
        h in _url_lower
        for h in ("localhost", "127.0.0.1", "0.0.0.0", ":11434", ":8080", ":5000")
    )
    if _looks_local and not _url_lower.endswith("/v1"):
        print()
        print(f"  Dica: Você quis dizer adicionar /v1 no final?")
        print(f"  A maioria dos servidores de modelos locais (Ollama, vLLM, llama.cpp) exige isso.")
        print(f"  ex: {effective_url.rstrip('/')}/v1")
        try:
            _add_v1 = input("  Adicionar /v1? (s/n): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            _add_v1 = "n"
        if _add_v1 in ("", "s", "sim", "y", "yes"):
            effective_url = effective_url.rstrip("/") + "/v1"
            if base_url:
                base_url = effective_url
            print(f"  URL atualizada: {effective_url}")
        print()

    from ector_cli.models import probe_api_models

    probe = probe_api_models(effective_key, effective_url)
    if probe.get("used_fallback") and probe.get("resolved_base_url"):
        print(
            f"Aviso: a verificação do endpoint funcionou em {probe['resolved_base_url']}/models, "
            f"não na URL exata que você digitou. Salvando a URL base funcional em vez disso."
        )
        effective_url = probe["resolved_base_url"]
        if base_url:
            base_url = effective_url
    elif probe.get("models") is not None:
        print(
            f"Endpoint verificado via {probe.get('probed_url')} "
            f"({len(probe.get('models') or [])} modelo(s) visível(is))"
        )
    else:
        print(
            f"Aviso: não foi possível verificar este endpoint via {probe.get('probed_url')}. "
            f"O Ector ainda assim irá salvá-lo."
        )
        if probe.get("suggested_base_url"):
            suggested = probe["suggested_base_url"]
            if suggested.endswith("/v1"):
                print(
                    f"  Se este servidor espera /v1 no caminho, tente a URL base: {suggested}"
                )
            else:
                print(f"  Se /v1 não deve estar na URL base, tente: {suggested}")

    # Select model — use probe results when available, fall back to manual input
    model_name = ""
    detected_models = probe.get("models") or []
    try:
        if len(detected_models) == 1:
            print(f"  Modelo detectado: {detected_models[0]}")
            confirm = input("  Usar este modelo? (s/n): ").strip().lower()
            if confirm in ("", "s", "sim", "y", "yes"):
                model_name = detected_models[0]
            else:
                model_name = input("Nome do modelo (ex: gpt-4, llama-3-70b): ").strip()
        elif len(detected_models) > 1:
            print("Modelos disponíveis:")
            for i, m in enumerate(detected_models, 1):
                print(f"    {i}. {m}")
            pick = input(
                f"  Selecionar modelo [1-{len(detected_models)}] ou digitar nome: "
            ).strip()
            if pick.isdigit() and 1 <= int(pick) <= len(detected_models):
                model_name = detected_models[int(pick) - 1]
            elif pick:
                model_name = pick
        else:
            model_name = input("Nome do modelo (ex: gpt-4, llama-3-70b): ").strip()

        context_length_str = input(
            "Tamanho do contexto em tokens [deixe em branco para detecção automática]: "
        ).strip()

        # Prompt for a display name — shown in the provider menu on future runs
        default_name = _auto_provider_name(effective_url)
        display_name = input(f"Nome de exibição [{default_name}]: ").strip() or default_name
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return

    context_length = None
    if context_length_str:
        try:
            context_length = int(
                context_length_str.replace(",", "")
                .replace("k", "000")
                .replace("K", "000")
            )
            if context_length <= 0:
                context_length = None
        except ValueError:
            print(f"Tamanho do contexto inválido: {context_length_str} — será detectado automaticamente.")
            context_length = None

    if model_name:
        _save_model_choice(model_name)

        # Update config and deactivate any OAuth provider
        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = "custom"
        model["base_url"] = effective_url
        if effective_key:
            model["api_key"] = effective_key
        model.pop("api_mode", None)  # let runtime auto-detect from URL
        save_config(cfg)
        deactivate_provider()

        # Sync the caller's config dict so the setup wizard's final
        # save_config(config) preserves our model settings.  Without
        # this, the wizard overwrites model.provider/base_url with
        # the stale values from its own config dict (#4172).
        config["model"] = dict(model)

        print(f"Modelo padrão definido para: {model_name} (via {effective_url})")
    else:
        if base_url or api_key:
            deactivate_provider()
        # Even without a model name, persist the custom endpoint on the
        # caller's config dict so the setup wizard doesn't lose it.
        _caller_model = config.get("model")
        if not isinstance(_caller_model, dict):
            _caller_model = {"default": _caller_model} if _caller_model else {}
        _caller_model["provider"] = "custom"
        _caller_model["base_url"] = effective_url
        if effective_key:
            _caller_model["api_key"] = effective_key
        _caller_model.pop("api_mode", None)
        config["model"] = _caller_model
        print("Endpoint salvo. Use `/provider` no chat ou `ector provider` para definir um modelo.")

    # Auto-save to custom_providers so it appears in the menu next time
    _save_custom_provider(
        effective_url,
        effective_key,
        model_name or "",
        context_length=context_length,
        name=display_name,
    )


def _auto_provider_name(base_url: str) -> str:
    """Generate a display name from a custom endpoint URL.

    Returns a human-friendly label like "Local (localhost:11434)" or
    "RunPod (xyz.runpod.io)".  Used as the default when prompting the
    user for a display name during custom endpoint setup.
    """
    import re

    clean = base_url.replace("https://", "").replace("http://", "").rstrip("/")
    clean = re.sub(r"/v1/?$", "", clean)
    name = clean.split("/")[0]
    if "localhost" in name or "127.0.0.1" in name:
        name = f"Local ({name})"
    elif "runpod" in name.lower():
        name = f"RunPod ({name})"
    else:
        name = name.capitalize()
    return name


def _custom_provider_api_key_config_value(provider_info, resolved_api_key=""):
    """Return the value that should be persisted for a custom provider key."""
    api_key_ref = str(provider_info.get("api_key_ref", "") or "").strip()
    if api_key_ref:
        return api_key_ref

    key_env = str(provider_info.get("key_env", "") or "").strip()
    if key_env and not str(provider_info.get("api_key", "") or "").strip():
        return f"${{{key_env}}}"

    return str(resolved_api_key or "").strip()


def _save_custom_provider(
    base_url, api_key="", model="", context_length=None, name=None
):
    """Save a custom endpoint to custom_providers in config.yaml.

    Deduplicates by base_url — if the URL already exists, updates the
    model name and context_length but doesn't add a duplicate entry.
    Uses *name* when provided, otherwise auto-generates from the URL.
    """
    from ector_cli.config import load_config, save_config

    cfg = load_config()
    providers = cfg.get("custom_providers") or []
    if not isinstance(providers, list):
        providers = []

    # Check if this URL is already saved — update model/context_length if so
    for entry in providers:
        if isinstance(entry, dict) and entry.get("base_url", "").rstrip(
            "/"
        ) == base_url.rstrip("/"):
            changed = False
            if model and entry.get("model") != model:
                entry["model"] = model
                changed = True
            if model and context_length:
                models_cfg = entry.get("models", {})
                if not isinstance(models_cfg, dict):
                    models_cfg = {}
                models_cfg[model] = {"context_length": context_length}
                entry["models"] = models_cfg
                changed = True
            if changed:
                cfg["custom_providers"] = providers
                save_config(cfg)
            return  # already saved, updated if needed

    # Use provided name or auto-generate from URL
    if not name:
        name = _auto_provider_name(base_url)

    entry = {"name": name, "base_url": base_url}
    if api_key:
        entry["api_key"] = api_key
    if model:
        entry["model"] = model
    if model and context_length:
        entry["models"] = {model: {"context_length": context_length}}

    providers.append(entry)
    cfg["custom_providers"] = providers
    save_config(cfg)
    print(f'  💾 Salvo nos provedores personalizados como "{name}" (edite no config.yaml)')


def _model_flow_azure_foundry(config, current_model=""):
    """Azure Foundry provider: configure endpoint, API mode, API key, and model.

    Azure Foundry supports both OpenAI-style (``/v1/chat/completions``) and
    Anthropic-style (``/v1/messages``) endpoints.  The wizard auto-detects
    the transport and available models when possible:

    * URLs ending in ``/anthropic`` → Anthropic Messages API.
    * Successful ``GET <base>/models`` probe → OpenAI-style + populates
      a picker with the returned deployment / model IDs.
    * Anthropic Messages probe fallback when ``/models`` fails.
    * Manual entry when every probe fails (private endpoints, etc.).

    Context lengths for the chosen model are resolved via the standard
    :func:`agent.model_metadata.get_model_context_length` chain
    (models.dev, provider metadata, hardcoded family fallbacks).
    """
    from ector_cli.auth import _save_model_choice, deactivate_provider  # noqa: F401
    from ector_cli.config import get_env_value, save_env_value, load_config, save_config
    from ector_cli import azure_detect
    import getpass

    # ── Load current Azure Foundry configuration ─────────────────────
    model_cfg = config.get("model", {})
    if isinstance(model_cfg, dict) and model_cfg.get("provider") == "azure-foundry":
        current_base_url = str(model_cfg.get("base_url", "") or "")
        current_api_mode = str(model_cfg.get("api_mode", "") or "")
    else:
        current_base_url = ""
        current_api_mode = ""

    current_api_key = get_env_value("AZURE_FOUNDRY_API_KEY") or ""

    print()
    print("Configuração do Azure Foundry")
    print("=" * 50)
    print()
    print("O Azure Foundry pode hospedar modelos com endpoints de API no estilo OpenAI")
    print("ou no estilo Anthropic. O Ector testará seu endpoint para detectar")
    print("automaticamente o transporte e os modelos implantados")
    print("quando possível.")
    print()

    if current_base_url:
        print(f"  Endpoint atual: {current_base_url}")
    if current_api_mode:
        _lbl = "Estilo OpenAI" if current_api_mode == "chat_completions" else "Estilo Anthropic"
        print(f"  Modo de API atual: {_lbl}")
    if current_api_key:
        print(f"  Chave API atual:  {current_api_key[:8]}...")
    print()

    # ── Step 1: endpoint URL ─────────────────────────────────────────
    try:
        base_url = input(
            f"URL do endpoint da API [{current_base_url or 'ex: https://seu-recurso.openai.azure.com/openai/v1'}]: "
        ).strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.")
        return

    effective_url = (base_url or current_base_url).rstrip("/")
    if not effective_url:
        print("Nenhuma URL de endpoint fornecida. Cancelado.")
        return
    if not effective_url.startswith(("http://", "https://")):
        print(f"Invalid URL: {effective_url} (must start with http:// or https://)")
        return

    # ── Step 2: API key ──────────────────────────────────────────────
    print()
    try:
        api_key = getpass.getpass(
            f"Chave API [{current_api_key[:8] + '...' if current_api_key else 'obrigatória'}]: "
        ).strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.")
        return

    effective_key = api_key or current_api_key
    if not effective_key:
        print("Nenhuma chave API fornecida. Cancelado.")
        return

    # ── Step 3: auto-detect transport + models ───────────────────────
    print()
    print("◐ Testando endpoint para detectar automaticamente o transporte e modelos...")
    detection = azure_detect.detect(effective_url, effective_key)

    discovered_models: list[str] = list(detection.models)
    api_mode: str = detection.api_mode or ""

    if api_mode:
        mode_label = "Estilo OpenAI" if api_mode == "chat_completions" else "Estilo Anthropic"
        print(f"✔ Transporte de API detectado: {mode_label}")
        if detection.reason:
            print(f"    ({detection.reason})")
        if discovered_models:
            print(f"✔ Encontrou {len(discovered_models)} modelo(s) implantado(s) neste endpoint")
    else:
        print(f"▲  Detecção automática incompleta: {detection.reason}")
        print()
        print("Selecione o formato de API que seu endpoint Azure Foundry usa:")
        print("  1. Estilo OpenAI  (POST /v1/chat/completions)")
        print("     Para: modelos GPT, Llama, Mistral e a maioria dos modelos abertos")
        print("  2. Estilo Anthropic  (POST /v1/messages)")
        print("     Para: modelos Claude implantados via formato de API Anthropic")
        try:
            default_choice = "2" if current_api_mode == "anthropic_messages" else "1"
            mode_choice = input(f"Formato de API [1/2] ({default_choice}): ").strip() or default_choice
        except (KeyboardInterrupt, EOFError):
            print("\nCancelado.")
            return
        api_mode = "anthropic_messages" if mode_choice == "2" else "chat_completions"

    # ── Step 4: model name ───────────────────────────────────────────
    print()
    effective_model = ""
    if discovered_models:
        print("Modelos disponíveis neste endpoint:")
        for i, mid in enumerate(discovered_models[:30], start=1):
            print(f"  {i:>2}. {mid}")
        if len(discovered_models) > 30:
            print(f"  ... e mais {len(discovered_models) - 30} (digite o nome manualmente se não for mostrado)")
        print()
        try:
            pick = input(
                f"Escolha pelo número, ou digite um nome de implantação [{current_model or discovered_models[0]}]: "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelado.")
            return
        if not pick:
            effective_model = current_model or discovered_models[0]
        elif pick.isdigit() and 1 <= int(pick) <= min(len(discovered_models), 30):
            effective_model = discovered_models[int(pick) - 1]
        else:
            effective_model = pick
    else:
        try:
            model_name = input(
                f"Nome do modelo / implantação [{current_model or 'ex: gpt-5.4, claude-sonnet-4-6'}]: "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelado.")
            return
        effective_model = model_name or current_model

    if not effective_model:
        print("Nenhum nome de modelo fornecido. Cancelado.")
        return

    # ── Step 5: context-length lookup ────────────────────────────────
    ctx_len = azure_detect.lookup_context_length(
        effective_model, effective_url, effective_key,
    )

    # ── Step 6: persist ──────────────────────────────────────────────
    save_env_value("AZURE_FOUNDRY_API_KEY", effective_key)

    cfg = load_config()
    model = cfg.get("model")
    if not isinstance(model, dict):
        model = {"default": model} if model else {}
        cfg["model"] = model

    model["provider"] = "azure-foundry"
    model["base_url"] = effective_url
    model["api_mode"] = api_mode
    model["default"] = effective_model
    if ctx_len:
        model["context_length"] = ctx_len

    save_config(cfg)
    deactivate_provider()
    config["model"] = dict(model)

    # Clear any conflicting env vars so auxiliary clients don't poison
    # themselves with a stale OpenAI base URL / key.
    if get_env_value("OPENAI_BASE_URL"):
        save_env_value("OPENAI_BASE_URL", "")
    if get_env_value("OPENAI_API_KEY"):
        save_env_value("OPENAI_API_KEY", "")

    mode_label = "Estilo OpenAI" if api_mode == "chat_completions" else "Estilo Anthropic"
    print()
    print("✔ Azure Foundry configurado:")
    print(f"    Endpoint:           {effective_url}")
    print(f"    Modo de API:        {mode_label}")
    print(f"    Modelo:             {effective_model}")
    if ctx_len:
        print(f"    Tamanho do contexto: {ctx_len:,} tokens")
    else:
        print("    Tamanho do contexto: não detectado automaticamente (será resolvido em tempo de execução)")
    print()


def _remove_custom_provider(config):
    """Let the user remove a saved custom provider from config.yaml."""
    from ector_cli.config import load_config, save_config

    cfg = load_config()
    providers = cfg.get("custom_providers") or []
    if not isinstance(providers, list) or not providers:
        print("Nenhum provedor personalizado configurado.")
        return

    print("Remover um provedor personalizado:\n")

    choices = []
    for entry in providers:
        if isinstance(entry, dict):
            name = entry.get("name", "unnamed")
            url = entry.get("base_url", "")
            short_url = url.replace("https://", "").replace("http://", "").rstrip("/")
            choices.append(f"{name} ({short_url})")
        else:
            choices.append(str(entry))
    choices.append("Cancelar")

    from ector_cli.curses_ui import curses_radiolist, flush_stdin

    cancel_idx = len(choices) - 1
    idx = curses_radiolist(
        "Selecione o provedor para remover:",
        choices,
        selected=0,
        cancel_returns=cancel_idx,
    )
    flush_stdin()
    print()

    if idx is None or idx >= len(providers):
        print("Nenhuma alteração.")
        return

    removed = providers.pop(idx)
    cfg["custom_providers"] = providers
    save_config(cfg)
    removed_name = (
        removed.get("name", "unnamed") if isinstance(removed, dict) else str(removed)
    )
    print(f'✔ Removeu "{removed_name}" dos provedores personalizados.')


def _model_flow_named_custom(config, provider_info):
    """Handle a named custom provider from config.yaml custom_providers list.

    Always probes the endpoint's /models API to let the user pick a model.
    If a model was previously saved, it is pre-selected in the menu.
    Falls back to the saved model if probing fails.
    """
    from ector_cli.auth import _save_model_choice, deactivate_provider
    from ector_cli.config import load_config, save_config
    from ector_cli.models import fetch_api_models

    name = provider_info["name"]
    base_url = provider_info["base_url"]
    api_mode = provider_info.get("api_mode", "")
    api_key = provider_info.get("api_key", "")
    key_env = provider_info.get("key_env", "")
    saved_model = provider_info.get("model", "")
    provider_key = (provider_info.get("provider_key") or "").strip()

    # Resolve key from env var if api_key not set directly
    if not api_key and key_env:
        api_key = os.environ.get(key_env, "")
    config_api_key = _custom_provider_api_key_config_value(provider_info, api_key)

    print(f"  Provider: {name}")
    print(f"  URL:      {base_url}")
    if saved_model:
        print(f"  Current:  {saved_model}")
    print()

    print("Buscando modelos disponíveis...")
    models = fetch_api_models(
        api_key, base_url, timeout=8.0,
        api_mode=api_mode or None,
    )

    if models:
        default_idx = 0
        if saved_model and saved_model in models:
            default_idx = models.index(saved_model)

        print(f"Encontrou {len(models)} modelo(s):\n")
        from ector_cli.curses_ui import curses_radiolist, flush_stdin

        menu_items = [
            f"{m} (atual)" if m == saved_model else m for m in models
        ] + ["Cancelar"]
        idx = curses_radiolist(
            f"Selecionar modelo de {name}:",
            menu_items,
            selected=default_idx,
            cancel_returns=len(models),
        )
        flush_stdin()
        print()
        if idx is None or idx >= len(models):
            print("Cancelado.")
            return
        model_name = models[idx]
    elif saved_model:
        print("Não foi possível buscar modelos do endpoint.")
        try:
            model_name = input(f"Nome do modelo [{saved_model}]: ").strip() or saved_model
        except (KeyboardInterrupt, EOFError):
            print("\nCancelado.")
            return
    else:
        print("Não foi possível buscar modelos do endpoint. Digite o nome do modelo manualmente.")
        try:
            model_name = input("Nome do modelo: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelado.")
            return
        if not model_name:
            print("Nenhum modelo especificado. Cancelado.")
            return

    # Activate and save the model to the custom_providers entry
    _save_model_choice(model_name)

    cfg = load_config()
    model = cfg.get("model")
    if not isinstance(model, dict):
        model = {"default": model} if model else {}
        cfg["model"] = model
    if provider_key:
        model["provider"] = provider_key
        model.pop("base_url", None)
        model.pop("api_key", None)
    else:
        model["provider"] = "custom"
        model["base_url"] = base_url
        if config_api_key:
            model["api_key"] = config_api_key
    # Apply api_mode from custom_providers entry, or clear stale value
    custom_api_mode = provider_info.get("api_mode", "")
    if custom_api_mode:
        model["api_mode"] = custom_api_mode
    else:
        model.pop("api_mode", None)  # let runtime auto-detect from URL
    save_config(cfg)
    deactivate_provider()

    # Persist the selected model back to whichever schema owns this endpoint.
    if provider_key:
        cfg = load_config()
        providers_cfg = cfg.get("providers")
        if isinstance(providers_cfg, dict):
            provider_entry = providers_cfg.get(provider_key)
            if isinstance(provider_entry, dict):
                provider_entry["default_model"] = model_name
                # Only persist an inline api_key when the user originally had
                # one (either a literal secret or a ``${VAR}`` template). When
                # the entry relies on ``key_env``, do not synthesize a
                # ``${key_env}`` api_key — the runtime already resolves the
                # key from ``key_env`` directly, and writing the resolved
                # secret (or even a synthesized template) would silently
                # downgrade credential hygiene on entries that intentionally
                # keep plaintext out of ``config.yaml``. See issue #15803.
                original_api_key_ref = str(
                    provider_info.get("api_key_ref", "") or ""
                ).strip()
                original_api_key = str(
                    provider_info.get("api_key", "") or ""
                ).strip()
                had_inline_api_key = bool(original_api_key_ref or original_api_key)
                if (
                    had_inline_api_key
                    and config_api_key
                    and not str(provider_entry.get("api_key", "") or "").strip()
                ):
                    provider_entry["api_key"] = config_api_key
                if key_env and not str(provider_entry.get("key_env", "") or "").strip():
                    provider_entry["key_env"] = key_env
                cfg["providers"] = providers_cfg
                save_config(cfg)
    else:
        # Save model name to the custom_providers entry for next time
        _save_custom_provider(base_url, config_api_key, model_name)

    print(f"\n✔ Modelo definido para: {model_name}")
    print(f"   Provider: {name} ({base_url})")


# Curated model lists for direct API-key providers — single source in models.py
from ector_cli.models import _PROVIDER_MODELS


def _current_reasoning_effort(config) -> str:
    agent_cfg = config.get("agent")
    if isinstance(agent_cfg, dict):
        return str(agent_cfg.get("reasoning_effort") or "").strip().lower()
    return ""


def _set_reasoning_effort(config, effort: str) -> None:
    agent_cfg = config.get("agent")
    if not isinstance(agent_cfg, dict):
        agent_cfg = {}
        config["agent"] = agent_cfg
    agent_cfg["reasoning_effort"] = effort


def _prompt_reasoning_effort_selection(efforts, current_effort=""):
    """Prompt for a reasoning effort. Returns effort, 'none', or None to keep current."""
    deduped = list(
        dict.fromkeys(
            str(effort).strip().lower() for effort in efforts if str(effort).strip()
        )
    )
    canonical_order = ("minimal", "low", "medium", "high", "xhigh")
    ordered = [effort for effort in canonical_order if effort in deduped]
    ordered.extend(effort for effort in deduped if effort not in canonical_order)
    if not ordered:
        return None

    def _label(effort):
        if effort == current_effort:
            return f"{effort}  ← atualmente em uso"
        return effort

    disable_label = "Desativar raciocínio"
    skip_label = "Pular (manter atual)"

    if current_effort == "none":
        default_idx = len(ordered)
    elif current_effort in ordered:
        default_idx = ordered.index(current_effort)
    elif "medium" in ordered:
        default_idx = ordered.index("medium")
    else:
        default_idx = 0

    from ector_cli.curses_ui import curses_radiolist, flush_stdin

    menu_choices = [_label(effort) for effort in ordered] + [disable_label, skip_label]
    idx = curses_radiolist(
        "Selecionar esforço de raciocínio:",
        menu_choices,
        selected=default_idx,
        cancel_returns=len(ordered) + 1,
    )
    flush_stdin()
    print()
    if idx < len(ordered):
        return ordered[idx]
    if idx == len(ordered):
        return "none"
    return None


def _model_flow_copilot(config, current_model=""):
    """GitHub Copilot flow using env vars, gh CLI, or OAuth device code."""
    from ector_cli.auth import (
        PROVIDER_REGISTRY,
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
        resolve_api_key_provider_credentials,
    )
    from ector_cli.config import save_env_value, load_config, save_config
    from ector_cli.models import (
        fetch_api_models,
        fetch_github_model_catalog,
        github_model_reasoning_efforts,
        copilot_model_api_mode,
        normalize_copilot_model_id,
    )

    provider_id = "copilot"
    pconfig = PROVIDER_REGISTRY[provider_id]

    creds = resolve_api_key_provider_credentials(provider_id)
    api_key = creds.get("api_key", "")
    source = creds.get("source", "")

    if not api_key:
        print("Nenhum token do GitHub configurado para o GitHub Copilot.")
        print()
        print("  Tipos de token suportados:")
        print(
            "    → Token OAuth (gho_*)          via `copilot login` ou fluxo de código de dispositivo"
        )
        print("    → Fine-grained PAT (github_pat_*)  com permissão de Copilot Requests")
        print("    → Token do GitHub App (ghu_*)     via variável de ambiente")
        print("    ✖ PAT Clássico (ghp_*)          NÃO é suportado pela API do Copilot")
        print()
        print("  Opções:")
        print("    1. Login com GitHub (fluxo de código de dispositivo OAuth)")
        print("    2. Inserir um token manualmente")
        print("    3. Cancelar")
        print()
        try:
            choice = input("  Escolha [1-3]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return

        if choice == "1":
            try:
                from ector_cli.copilot_auth import copilot_device_code_login

                token = copilot_device_code_login()
                if token:
                    save_env_value("COPILOT_GITHUB_TOKEN", token)
                    print("  Token do Copilot salvo.")
                    print()
                else:
                    print("  Login cancelado ou falhou.")
                    return
            except Exception as exc:
                print(f"  Login falhou: {exc}")
                return
        elif choice == "2":
            try:
                import getpass

                new_key = getpass.getpass("  Token (COPILOT_GITHUB_TOKEN): ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            if not new_key:
                print("  Cancelado.")
                return
            # Validate token type
            try:
                from ector_cli.copilot_auth import validate_copilot_token

                valid, msg = validate_copilot_token(new_key)
                if not valid:
                    print(f"  ✖ {msg}")
                    return
            except ImportError:
                pass
            save_env_value("COPILOT_GITHUB_TOKEN", new_key)
            print("  Token salvo.")
            print()
        else:
            print("  Cancelado.")
            return

        creds = resolve_api_key_provider_credentials(provider_id)
        api_key = creds.get("api_key", "")
        source = creds.get("source", "")
    else:
        if source in ("GITHUB_TOKEN", "GH_TOKEN"):
            print(f"  Token do GitHub: {api_key[:8]}... ✔ ({source})")
        elif source == "gh auth token":
            print("  Token do GitHub: ✔ (de `gh auth token`)")
        else:
            print("  Token do GitHub: ✔")
        print()

    effective_base = pconfig.inference_base_url

    catalog = fetch_github_model_catalog(api_key)
    live_models = (
        [item.get("id", "") for item in catalog if item.get("id")]
        if catalog
        else fetch_api_models(api_key, effective_base)
    )
    normalized_current_model = (
        normalize_copilot_model_id(
            current_model,
            catalog=catalog,
            api_key=api_key,
        )
        or current_model
    )
    if live_models:
        model_list = [model_id for model_id in live_models if model_id]
        print(f"  Encontrou {len(model_list)} modelo(s) do GitHub Copilot")
    else:
        model_list = _PROVIDER_MODELS.get(provider_id, [])
        if model_list:
            print(
                "  ▲  Não foi possível detectar modelos do GitHub Copilot automaticamente — mostrando padrões."
            )
            print('    Use "Inserir nome de modelo personalizado" se não vir seu modelo.')

    if model_list:
        selected = _prompt_model_selection(
            model_list, current_model=normalized_current_model
        )
    else:
        try:
            selected = input("Nome do modelo: ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    if selected:
        selected = (
            normalize_copilot_model_id(
                selected,
                catalog=catalog,
                api_key=api_key,
            )
            or selected
        )
        initial_cfg = load_config()
        current_effort = _current_reasoning_effort(initial_cfg)
        reasoning_efforts = github_model_reasoning_efforts(
            selected,
            catalog=catalog,
            api_key=api_key,
        )
        selected_effort = None
        if reasoning_efforts:
            print(f"  {selected} suporta controles de raciocínio.")
            selected_effort = _prompt_reasoning_effort_selection(
                reasoning_efforts, current_effort=current_effort
            )

        _save_model_choice(selected)

        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = provider_id
        model["base_url"] = effective_base
        model["api_mode"] = copilot_model_api_mode(
            selected,
            catalog=catalog,
            api_key=api_key,
        )
        if selected_effort is not None:
            _set_reasoning_effort(cfg, selected_effort)
        save_config(cfg)
        deactivate_provider()

        print(f"Modelo padrão definido para: {selected} (via {pconfig.name})")
        if reasoning_efforts:
            if selected_effort == "none":
                print("Raciocínio desativado para este modelo.")
            elif selected_effort:
                print(f"Esforço de raciocínio definido para: {selected_effort}")
    else:
        print("Nenhuma alteração.")


def _model_flow_copilot_acp(config, current_model=""):
    """GitHub Copilot ACP flow using the local Copilot CLI."""
    from ector_cli.auth import (
        PROVIDER_REGISTRY,
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
        get_external_process_provider_status,
        resolve_api_key_provider_credentials,
        resolve_external_process_provider_credentials,
    )
    from ector_cli.models import (
        fetch_github_model_catalog,
        normalize_copilot_model_id,
    )
    from ector_cli.config import load_config, save_config

    del config

    provider_id = "copilot-acp"
    pconfig = PROVIDER_REGISTRY[provider_id]

    status = get_external_process_provider_status(provider_id)
    resolved_command = (
        status.get("resolved_command") or status.get("command") or "copilot"
    )
    effective_base = status.get("base_url") or pconfig.inference_base_url

    print("  O GitHub Copilot ACP delega turnos do Ector para `copilot --acp`.")
    print("  O Ector inicia atualmente seu próprio subprocesso ACP para cada pedido.")
    print("  O Ector usa seu modelo selecionado como dica para a sessão Copilot ACP.")
    print(f"  Comando: {resolved_command}")
    print(f"  Marcador de backend: {effective_base}")
    print()

    try:
        creds = resolve_external_process_provider_credentials(provider_id)
    except Exception as exc:
        print(f"  ▲  {exc}")
        print(
            "  Set ECTOR_COPILOT_ACP_COMMAND or COPILOT_CLI_PATH if Copilot CLI is installed elsewhere."
        )
        return

    effective_base = creds.get("base_url") or effective_base

    catalog_api_key = ""
    try:
        catalog_creds = resolve_api_key_provider_credentials("copilot")
        catalog_api_key = catalog_creds.get("api_key", "")
    except Exception:
        pass

    catalog = fetch_github_model_catalog(catalog_api_key)
    normalized_current_model = (
        normalize_copilot_model_id(
            current_model,
            catalog=catalog,
            api_key=catalog_api_key,
        )
        or current_model
    )

    if catalog:
        model_list = [item.get("id", "") for item in catalog if item.get("id")]
        print(f"  Encontrou {len(model_list)} modelo(s) do GitHub Copilot")
    else:
        model_list = _PROVIDER_MODELS.get("copilot", [])
        if model_list:
            print(
                "  ▲ Não foi possível detectar modelos do GitHub Copilot automaticamente — mostrando padrões."
            )
            print('    Use "Inserir nome de modelo personalizado" se não vir seu modelo.')

    if model_list:
        selected = _prompt_model_selection(
            model_list,
            current_model=normalized_current_model,
        )
    else:
        try:
            selected = input("Nome do modelo: ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    if not selected:
        print("Nenhuma alteração.")
        return

    selected = (
        normalize_copilot_model_id(
            selected,
            catalog=catalog,
            api_key=catalog_api_key,
        )
        or selected
    )
    _save_model_choice(selected)

    cfg = load_config()
    model = cfg.get("model")
    if not isinstance(model, dict):
        model = {"default": model} if model else {}
        cfg["model"] = model
    model["provider"] = provider_id
    model["base_url"] = effective_base
    model["api_mode"] = "chat_completions"
    save_config(cfg)
    deactivate_provider()

    print(f"Modelo padrão definido para: {selected} (via {pconfig.name})")


def _model_flow_kimi(config, current_model=""):
    """Kimi / Moonshot model selection with automatic endpoint routing.

    - sk-kimi-* keys   → api.kimi.com/coding/v1  (Kimi Coding Plan)
    - Other keys        → api.moonshot.ai/v1      (legacy Moonshot)

    No manual base URL prompt — endpoint is determined by key prefix.
    """
    from ector_cli.auth import (
        PROVIDER_REGISTRY,
        KIMI_CODE_BASE_URL,
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
    )
    from ector_cli.config import (
        get_env_value,
        save_env_value,
        load_config,
        save_config,
    )

    provider_id = "kimi-coding"
    pconfig = PROVIDER_REGISTRY[provider_id]
    key_env = pconfig.api_key_env_vars[0] if pconfig.api_key_env_vars else ""
    base_url_env = pconfig.base_url_env_var or ""

    # Step 1: Check / prompt for API key
    existing_key = ""
    for ev in pconfig.api_key_env_vars:
        existing_key = get_env_value(ev) or os.getenv(ev, "")
        if existing_key:
            break

    if not existing_key:
        print(f"Nenhuma chave API do {pconfig.name} configurada.")
        if key_env:
            try:
                import getpass

                new_key = getpass.getpass(f"{key_env} (ou Enter para cancelar): ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            if not new_key:
                print("Cancelado.")
                return
            save_env_value(key_env, new_key)
            existing_key = new_key
            print("API key saved.")
            print()
    else:
        print(f"  Chave API do {pconfig.name}: {existing_key[:8]}... ✔")
        print()

    # Step 2: Auto-detect endpoint from key prefix
    is_coding_plan = existing_key.startswith("sk-kimi-")
    if is_coding_plan:
        effective_base = KIMI_CODE_BASE_URL
        print(f"  Detectou chave Kimi Coding Plan → {effective_base}")
    else:
        effective_base = pconfig.inference_base_url
        print(f"  Usando endpoint Moonshot → {effective_base}")
    # Clear any manual base URL override so auto-detection works at runtime
    if base_url_env and get_env_value(base_url_env):
        save_env_value(base_url_env, "")
    print()

    # Step 3: Model selection — show appropriate models for the endpoint
    if is_coding_plan:
        # Coding Plan models (kimi-k2.6 first)
        model_list = [
            "kimi-k2.6",
            "kimi-k2.5",
            "kimi-for-coding",
            "kimi-k2-thinking",
            "kimi-k2-thinking-turbo",
        ]
    else:
        # Legacy Moonshot models (excludes Coding Plan-only models)
        model_list = _PROVIDER_MODELS.get("moonshot", [])

    if model_list:
        selected = _prompt_model_selection(model_list, current_model=current_model)
    else:
        try:
            selected = input("Digite o nome do modelo: ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    if selected:
        _save_model_choice(selected)

        # Update config with provider and base URL
        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = provider_id
        model["base_url"] = effective_base
        model.pop("api_mode", None)  # let runtime auto-detect from URL
        save_config(cfg)
        deactivate_provider()

        endpoint_label = "Kimi Coding" if is_coding_plan else "Moonshot"
        print(f"Modelo padrão definido para: {selected} (via {endpoint_label})")
    else:
        print("Nenhuma alteração.")


def _infer_stepfun_region(base_url: str) -> str:
    """Infer the current StepFun region from the configured endpoint."""
    normalized = (base_url or "").strip().lower()
    if "api.stepfun.com" in normalized:
        return "china"
    return "international"


def _stepfun_base_url_for_region(region: str) -> str:
    from ector_cli.auth import (
        STEPFUN_STEP_PLAN_CN_BASE_URL,
        STEPFUN_STEP_PLAN_INTL_BASE_URL,
    )

    return (
        STEPFUN_STEP_PLAN_CN_BASE_URL
        if region == "china"
        else STEPFUN_STEP_PLAN_INTL_BASE_URL
    )


def _model_flow_stepfun(config, current_model=""):
    """StepFun Step Plan flow with region-specific endpoints."""
    from ector_cli.auth import (
        PROVIDER_REGISTRY,
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
    )
    from ector_cli.config import get_env_value, save_env_value, load_config, save_config
    from ector_cli.models import fetch_api_models

    provider_id = "stepfun"
    pconfig = PROVIDER_REGISTRY[provider_id]
    key_env = pconfig.api_key_env_vars[0] if pconfig.api_key_env_vars else ""
    base_url_env = pconfig.base_url_env_var or ""

    existing_key = ""
    for ev in pconfig.api_key_env_vars:
        existing_key = get_env_value(ev) or os.getenv(ev, "")
        if existing_key:
            break

    if not existing_key:
        print(f"Nenhuma chave API do {pconfig.name} configurada.")
        if key_env:
            try:
                import getpass
                new_key = getpass.getpass(f"{key_env} (ou Enter para cancelar): ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            if not new_key:
                print("Cancelado.")
                return
            save_env_value(key_env, new_key)
            existing_key = new_key
            print("API key saved.")
            print()
    else:
        print(f"  Chave API do {pconfig.name}: {existing_key[:8]}... ✔")
        print()

    current_base = ""
    if base_url_env:
        current_base = get_env_value(base_url_env) or os.getenv(base_url_env, "")
    if not current_base:
        model_cfg = config.get("model")
        if isinstance(model_cfg, dict):
            current_base = str(model_cfg.get("base_url") or "").strip()
    current_region = _infer_stepfun_region(current_base or pconfig.inference_base_url)

    region_choices = [
        ("international", f"International ({_stepfun_base_url_for_region('international')})"),
        ("china", f"China ({_stepfun_base_url_for_region('china')})"),
    ]
    ordered_regions = []
    for region_key, label in region_choices:
        if region_key == current_region:
            ordered_regions.insert(0, (region_key, f"{label}  ← atualmente ativo"))
        else:
            ordered_regions.append((region_key, label))
    ordered_regions.append(("cancel", "Cancelar"))

    region_idx = _prompt_provider_choice([label for _, label in ordered_regions])
    if region_idx is None or ordered_regions[region_idx][0] == "cancel":
        print("Nenhuma alteração.")
        return

    selected_region = ordered_regions[region_idx][0]
    effective_base = _stepfun_base_url_for_region(selected_region)
    if base_url_env:
        save_env_value(base_url_env, effective_base)

    live_models = fetch_api_models(existing_key, effective_base)
    if live_models:
        model_list = live_models
        print(f"  Encontrou {len(model_list)} modelo(s) da API do {pconfig.name}")
    else:
        model_list = _PROVIDER_MODELS.get(provider_id, [])
        if model_list:
            print(
                f"  Não foi possível detectar modelos da API do {pconfig.name} automaticamente — "
                "mostrando catálogo de fallback do Step Plan."
            )

    if model_list:
        selected = _prompt_model_selection(model_list, current_model=current_model)
    else:
        try:
            selected = input("Nome do modelo: ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    if selected:
        _save_model_choice(selected)

        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = provider_id
        model["base_url"] = effective_base
        model.pop("api_mode", None)
        save_config(cfg)
        deactivate_provider()

        config["model"] = dict(model)
        print(f"Modelo padrão definido para: {selected} (via {pconfig.name})")
    else:
        print("Nenhuma alteração.")


def _model_flow_bedrock_api_key(config, region, current_model=""):
    """Bedrock API Key mode — uses the OpenAI-compatible bedrock-mantle endpoint.

    For developers who don't have an AWS account but received a Bedrock API Key
    from their AWS admin. Works like any OpenAI-compatible endpoint.
    """
    from ector_cli.auth import (
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
    )
    from ector_cli.config import (
        load_config,
        save_config,
        get_env_value,
        save_env_value,
    )
    from ector_cli.models import _PROVIDER_MODELS

    mantle_base_url = f"https://bedrock-mantle.{region}.api.aws/v1"

    # Prompt for API key
    existing_key = get_env_value("AWS_BEARER_TOKEN_BEDROCK") or ""
    if existing_key:
        print(f"  Chave API do Bedrock: {existing_key[:12]}... ✔")
    else:
        print(f"  Endpoint: {mantle_base_url}")
        print()
        try:
            import getpass

            api_key = getpass.getpass("  Chave API do Bedrock: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return
        if not api_key:
            print("  Cancelado.")
            return
        save_env_value("AWS_BEARER_TOKEN_BEDROCK", api_key)
        existing_key = api_key
        print("  ✔ Chave API salva.")
    print()

    # Model selection — use static list (mantle doesn't need boto3 for discovery)
    model_list = _PROVIDER_MODELS.get("bedrock", [])
    print(f"  Mostrando {len(model_list)} modelos curados")

    if model_list:
        selected = _prompt_model_selection(model_list, current_model=current_model)
    else:
        try:
            selected = input("  ID do modelo: ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    if selected:
        _save_model_choice(selected)

        # Save as custom provider pointing to bedrock-mantle
        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = "custom"
        model["base_url"] = mantle_base_url
        model.pop("api_mode", None)  # chat_completions is the default

        # Also save region in bedrock config for reference
        bedrock_cfg = cfg.get("bedrock", {})
        if not isinstance(bedrock_cfg, dict):
            bedrock_cfg = {}
        bedrock_cfg["region"] = region
        cfg["bedrock"] = bedrock_cfg

        # Save the API key env var name so ector knows where to find it
        save_env_value("OPENAI_API_KEY", existing_key)
        save_env_value("OPENAI_BASE_URL", mantle_base_url)

        save_config(cfg)
        deactivate_provider()

        print(f"  Modelo padrão definido para: {selected} (via Chave API do Bedrock, {region})")
        print(f"  Endpoint: {mantle_base_url}")
    else:
        print("  Nenhuma alteração.")


def _model_flow_bedrock(config, current_model=""):
    """AWS Bedrock provider: verify credentials, pick region, discover models.

    Uses the native Converse API via boto3 — not the OpenAI-compatible endpoint.
    Auth is handled by the AWS SDK default credential chain (env vars, profile,
    instance role), so no API key prompt is needed.
    """
    from ector_cli.auth import (
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
    )
    from ector_cli.config import load_config, save_config
    from ector_cli.models import _PROVIDER_MODELS

    # 1. Check for AWS credentials
    try:
        from agent.bedrock_adapter import (
            has_aws_credentials,
            resolve_aws_auth_env_var,
            resolve_bedrock_region,
            discover_bedrock_models,
        )
    except ImportError:
        print("  ✖ boto3 não está instalado. Instale-o com:")
        print("    pip install boto3")
        print()
        return

    if not has_aws_credentials():
        print("  ▲  Nenhuma credencial AWS detectada via variáveis de ambiente.")
        print("  O Bedrock usará a cadeia de credenciais padrão do boto3 (IMDS, SSO, etc.)")
        print()

    auth_var = resolve_aws_auth_env_var()
    if auth_var:
        print(f"  Credenciais AWS: {auth_var} ✔")
    else:
        print("  Credenciais AWS: cadeia padrão do boto3 (instance role / SSO)")
    print()

    # 2. Region selection
    current_region = resolve_bedrock_region()
    try:
        region_input = input(f"  Região AWS [{current_region}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return
    region = region_input or current_region

    # 2b. Authentication mode
    print("  Escolha o método de autenticação:")
    print()
    print("    1. Cadeia de credenciais IAM (recomendado)")
    print("       Funciona com EC2 instance roles, SSO, vars de ambiente, aws configure")
    print("    2. Chave API do Bedrock")
    print("       Insira sua Chave API do Bedrock diretamente — também suporta")
    print("       cenários de equipe onde um admin distribui chaves")
    print()
    try:
        auth_choice = input("  Escolha [1]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return

    if auth_choice == "2":
        _model_flow_bedrock_api_key(config, region, current_model)
        return

    # 3. Model discovery — try live API first, fall back to static list
    print(f"  Descobrindo modelos em {region}...")
    live_models = discover_bedrock_models(region)

    if live_models:
        _EXCLUDE_PREFIXES = (
            "stability.",
            "cohere.embed",
            "twelvelabs.",
            "us.stability.",
            "us.cohere.embed",
            "us.twelvelabs.",
            "global.cohere.embed",
            "global.twelvelabs.",
        )
        _EXCLUDE_SUBSTRINGS = ("safeguard", "voxtral", "palmyra-vision")
        filtered = []
        for m in live_models:
            mid = m["id"]
            if any(mid.startswith(p) for p in _EXCLUDE_PREFIXES):
                continue
            if any(s in mid.lower() for s in _EXCLUDE_SUBSTRINGS):
                continue
            filtered.append(m)

        # Deduplicate: prefer inference profiles (us.*, global.*) over bare
        # foundation model IDs.
        profile_base_ids = set()
        for m in filtered:
            mid = m["id"]
            if mid.startswith(("us.", "global.")):
                base = mid.split(".", 1)[1] if "." in mid[3:] else mid
                profile_base_ids.add(base)

        deduped = []
        for m in filtered:
            mid = m["id"]
            if not mid.startswith(("us.", "global.")) and mid in profile_base_ids:
                continue
            deduped.append(m)

        _RECOMMENDED = [
            "us.anthropic.claude-sonnet-4-6",
            "us.anthropic.claude-opus-4-6",
            "us.anthropic.claude-haiku-4-5",
            "us.amazon.nova-pro",
            "us.amazon.nova-lite",
            "us.amazon.nova-micro",
            "deepseek.v3",
            "us.meta.llama4-maverick",
            "us.meta.llama4-scout",
        ]

        def _sort_key(m):
            mid = m["id"]
            for i, rec in enumerate(_RECOMMENDED):
                if mid.startswith(rec):
                    return (0, i, mid)
            if mid.startswith("global."):
                return (1, 0, mid)
            return (2, 0, mid)

        deduped.sort(key=_sort_key)
        model_list = [m["id"] for m in deduped]
        print(
            f"  Encontrou {len(model_list)} modelo(s) de texto (filtrados de {len(live_models)} no total)"
        )
    else:
        model_list = _PROVIDER_MODELS.get("bedrock", [])
        if model_list:
            print(
                f"  Usando {len(model_list)} modelos curados (descoberta ao vivo indisponível)"
            )
        else:
            print(
                "  Nenhum modelo encontrado. Verifique as permissões IAM para bedrock:ListFoundationModels."
            )
            return

    # 4. Model selection
    if model_list:
        selected = _prompt_model_selection(model_list, current_model=current_model)
    else:
        try:
            selected = input("  ID do modelo: ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    if selected:
        _save_model_choice(selected)

        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = "bedrock"
        model["base_url"] = f"https://bedrock-runtime.{region}.amazonaws.com"
        model.pop("api_mode", None)  # bedrock_converse is auto-detected

        bedrock_cfg = cfg.get("bedrock", {})
        if not isinstance(bedrock_cfg, dict):
            bedrock_cfg = {}
        bedrock_cfg["region"] = region
        cfg["bedrock"] = bedrock_cfg

        save_config(cfg)
        deactivate_provider()

        print(f"  Modelo padrão definido para: {selected} (via AWS Bedrock, {region})")
    else:
        print("  Nenhuma alteração.")


def _model_flow_api_key_provider(config, provider_id, current_model=""):
    """Generic flow for API-key providers (z.ai, MiniMax, etc.)."""
    from ector_cli.auth import (
        PROVIDER_REGISTRY,
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
    )
    from ector_cli.config import (
        get_env_value,
        save_env_value,
        load_config,
        save_config,
    )
    from ector_cli.models import fetch_api_models

    pconfig = PROVIDER_REGISTRY[provider_id]
    key_env = pconfig.api_key_env_vars[0] if pconfig.api_key_env_vars else ""
    base_url_env = pconfig.base_url_env_var or ""

    # Check / prompt for API key
    existing_key = ""
    for ev in pconfig.api_key_env_vars:
        existing_key = get_env_value(ev) or os.getenv(ev, "")
        if existing_key:
            break

    if not existing_key:
        print(f"Nenhuma chave API do {pconfig.name} configurada.")
        if key_env:
            try:
                import getpass

                new_key = getpass.getpass(f"{key_env} (ou Enter para cancelar): ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            if not new_key:
                print("Cancelado.")
                return
            save_env_value(key_env, new_key)
            existing_key = new_key
            print("✔ API key salva.")
            print()
    else:
        print(f"  {pconfig.name} API key: {existing_key[:8]}... ✔")
        try:
            change = input("  Deseja alterar a API Key? (s/n): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            change = ""
        
        if change in ("y", "yes", "s", "sim"):
            try:
                import getpass
                new_key = getpass.getpass(f"  Nova {key_env} (ou Enter para manter): ").strip()
                if new_key:
                    save_env_value(key_env, new_key)
                    existing_key = new_key
                    print("  API key atualizada.")
            except (KeyboardInterrupt, EOFError):
                pass
        print()

    # Gemini free-tier gate: free-tier daily quotas (<= 250 RPD for Flash)
    # are exhausted in a handful of agent turns, so refuse to wire up the
    # provider with a free-tier key. Probe is best-effort; network or auth
    # errors fall through without blocking.
    if provider_id == "gemini" and existing_key:
        try:
            from agent.gemini_native_adapter import probe_gemini_tier
        except Exception:
            probe_gemini_tier = None
        if probe_gemini_tier is not None:
            print("  Verificando nível da API do Gemini...")
            probe_base = (
                (get_env_value(base_url_env) if base_url_env else "")
                or os.getenv(base_url_env or "", "")
                or pconfig.inference_base_url
            )
            tier = probe_gemini_tier(existing_key, probe_base)
            if tier == "free":
                print()
                print(
                    "✖ Esta chave API do Google está no nível gratuito "
                    "(<= 250 pedidos/dia para o gemini-2.5-flash)."
                )
                print(
                    "   O Ector normalmente faz de 3 a 10 chamadas de API por turno do usuário "
                    "(iterações de ferramentas + tarefas auxiliares),"
                )
                print(
                    "   então o nível gratuito se esgota após algumas "
                    "mensagens e não consegue sustentar"
                )
                print("   uma sessão de agente.")
                print()
                print(
                    "   Para usar o Gemini com o Ector, ative o faturamento no seu "
                    "projeto Google Cloud e regenere"
                )
                print(
                    "   a chave em um projeto com faturamento ativado: "
                    "https://aistudio.google.com/apikey"
                )
                print()
                print(
                    "   Alternativas com uso gratuito viável: DeepSeek, "
                    "OpenRouter (modelos gratuitos), Groq, Ector."
                )
                print()
                print("Não salvando o Gemini como provedor padrão.")
                return
            if tier == "paid":
                print("  Verificação de nível: pago ✔")
            else:
                # "unknown" -- network issue, auth problem, unexpected response.
                # Don't block; the runtime 429 handler will surface free-tier
                # guidance if the key turns out to be free tier.
                print("  Verificação de nível: não foi possível verificar (prosseguindo de qualquer forma).")
            print()

    # Optional base URL override
    current_base = ""
    if base_url_env:
        current_base = get_env_value(base_url_env) or os.getenv(base_url_env, "")
    effective_base = current_base or pconfig.inference_base_url

    override = ""
    if provider_id != "openai":
        try:
            override = input(f"URL Base ({effective_base}): ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            override = ""
    if override and base_url_env:
        if not override.startswith(("http://", "https://")):
            print(
                "  URL inválida — deve começar com http:// ou https://. Mantendo o valor atual."
            )
        else:
            save_env_value(base_url_env, override)
            effective_base = override

    print()

    # Model selection — resolution order:
    #   1. models.dev registry (cached, filtered for agentic/tool-capable models)
    #   2. Curated static fallback list (offline insurance)
    #   3. Live /models endpoint probe (small providers without models.dev data)
    #
    # Ollama Cloud: dedicated merged discovery (live API + models.dev + disk cache)
    if provider_id == "ollama-cloud":
        from ector_cli.models import fetch_ollama_cloud_models

        api_key_for_probe = existing_key or (get_env_value(key_env) if key_env else "")
        # During setup, force a live refresh so the picker reflects newly
        # released models (e.g. deepseek v4 flash, kimi k2.6) the moment
        # the user enters their key — not an hour later when the disk
        # cache TTL expires.
        model_list = fetch_ollama_cloud_models(
            api_key=api_key_for_probe,
            base_url=effective_base,
            force_refresh=True,
        )
        if model_list:
            print(f"  Encontrou {len(model_list)} modelo(s) da Ollama Cloud")
    else:
        curated = _PROVIDER_MODELS.get(provider_id, [])
        # Bias the picker with shared recommendations (CLI + Web).
        try:
            from ector_cli.provider_model_catalog import merge_recommended_first
            curated = merge_recommended_first(provider_id, models=curated)
        except Exception:
            pass

        # Try models.dev first — returns tool-capable models, filtered for noise
        mdev_models: list = []
        try:
            from agent.models_dev import list_agentic_models

            mdev_models = list_agentic_models(provider_id)
        except Exception:
            pass

        if mdev_models:
            # Merge models.dev with curated list so newly added models
            # (not yet in models.dev) still appear in the picker.
            if curated:
                seen = {m.lower() for m in mdev_models}
                merged = list(mdev_models)
                for m in curated:
                    if m.lower() not in seen:
                        merged.append(m)
                        seen.add(m.lower())
                # Ensure shared recommendations are first overall.
                try:
                    from ector_cli.provider_model_catalog import merge_recommended_first
                    model_list = merge_recommended_first(provider_id, models=merged)
                except Exception:
                    model_list = merged
            else:
                model_list = mdev_models
        elif curated and len(curated) >= 8:
            # Curated list is substantial — use it directly, skip live probe
            model_list = curated
            print(
                f'  Mostrando {len(model_list)} modelos curados — use "Inserir nome de modelo personalizado" para outros.'
            )
        else:
            api_key_for_probe = existing_key or (
                get_env_value(key_env) if key_env else ""
            )
            live_models = fetch_api_models(api_key_for_probe, effective_base)
            if live_models and len(live_models) >= len(curated):
                model_list = live_models
                print(f"  Encontrou {len(model_list)} modelo(s) da API do {pconfig.name}")
            else:
                model_list = curated
                if model_list:
                    print(
                        f'  Mostrando {len(model_list)} modelos curados — use "Inserir nome de modelo personalizado" para outros.'
                    )
            # else: no defaults either, will fall through to raw input

    picker_kw = _model_picker_identity_extras()
    if model_list:
        selected = _prompt_model_selection(
            model_list,
            current_model=current_model,
            unavailable_models=picker_kw.get("unavailable_models"),
            portal_url=picker_kw.get("portal_url", ""),
            available_count=len(model_list),
        )
    else:
        try:
            selected = input("Nome do modelo: ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    if selected:
        _save_model_choice(selected)

        # Update config with provider, base URL, and provider-specific API mode
        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = provider_id
        model["base_url"] = effective_base
        model.pop("api_mode", None)
        save_config(cfg)
        deactivate_provider()

        print(f"Modelo padrão definido para: {selected} (via {pconfig.name})")
    else:
        print("Nenhuma alteração.")


def _run_anthropic_oauth_flow(save_env_value):
    """Run the Claude OAuth setup-token flow. Returns True if credentials were saved."""
    from agent.anthropic_adapter import (
        run_oauth_setup_token,
        read_claude_code_credentials,
        is_claude_code_token_valid,
    )
    from ector_cli.config import (
        save_anthropic_oauth_token,
        use_anthropic_claude_code_credentials,
    )

    def _activate_claude_code_credentials_if_available() -> bool:
        try:
            creds = read_claude_code_credentials()
        except Exception:
            creds = None
        if creds and (
            is_claude_code_token_valid(creds) or bool(creds.get("refreshToken"))
        ):
            use_anthropic_claude_code_credentials(save_fn=save_env_value)
            print("  ✔ Credenciais do Claude Code vinculadas.")
            from ector_constants import display_ector_home as _dhh_fn

            print(
                f"    O Ector usará o armazenamento de credenciais do Claude diretamente em vez de copiar um setup-token para {_dhh_fn()}/.env."
            )
            return True
        return False

    try:
        print()
        print("  Executando 'claude setup-token' — siga as instruções abaixo.")
        print("  Uma janela do navegador será aberta para você autorizar o acesso.")
        print()
        token = run_oauth_setup_token()
        if token:
            if _activate_claude_code_credentials_if_available():
                return True
            save_anthropic_oauth_token(token, save_fn=save_env_value)
            print("  ✔ Credenciais OAuth salvas.")
            return True

        # Subprocess completed but no token auto-detected — ask user to paste
        print()
        print("  Se o setup-token foi exibido acima, cole-o aqui:")
        print()
        try:
            import getpass

            manual_token = getpass.getpass(
                "  Cole o setup-token (ou Enter para cancelar): "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return False
        if manual_token:
            save_anthropic_oauth_token(manual_token, save_fn=save_env_value)
            print("  ✔ Setup-token salvo.")
            return True

        print("  ▲  Não foi possível detectar credenciais salvas.")
        return False

    except FileNotFoundError:
        # Claude CLI not installed — guide user through manual setup
        print()
        print("  A CLI 'claude' é necessária para o login OAuth.")
        print()
        print("  Para instalar e autenticar:")
        print()
        print("    1. Instale o Claude Code:  npm install -g @anthropic-ai/claude-code")
        print("    2. Execute:                  claude setup-token")
        print("    3. Siga as instruções no navegador para autorizar")
        print("    4. Execute novamente:        ector provider")
        print()
        print("  Ou cole um setup-token existente agora (sk-ant-oat-...):")
        print()
        try:
            import getpass

            token = getpass.getpass("  Setup-token (ou Enter para cancelar): ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return False
        if token:
            save_anthropic_oauth_token(token, save_fn=save_env_value)
            print("  ✔ Setup-token salvo.")
            return True
        print("  Cancelado — instale o Claude Code e tente novamente.")
        return False


def _model_flow_anthropic(config, current_model=""):
    """Flow for Anthropic provider — OAuth subscription, API key, or Claude Code creds."""
    from ector_cli.auth import (
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
    )
    from ector_cli.config import (
        save_env_value,
        load_config,
        save_config,
        save_anthropic_api_key,
    )
    from ector_cli.models import _PROVIDER_MODELS

    # Check ALL credential sources
    from ector_cli.auth import get_anthropic_key

    existing_key = get_anthropic_key()
    cc_available = False
    try:
        from agent.anthropic_adapter import (
            read_claude_code_credentials,
            is_claude_code_token_valid,
            _is_oauth_token,
            _resolve_claude_code_token_from_credentials,
        )

        cc_creds = read_claude_code_credentials()
        if cc_creds and is_claude_code_token_valid(cc_creds):
            cc_available = True
    except Exception:
        pass

    # Stale-OAuth guard: if the only existing cred is an expired OAuth token
    # (no valid cc_creds to fall back on), treat it as missing so the re-auth
    # path is offered instead of silently accepting a broken token.
    existing_is_stale_oauth = False
    if existing_key and _is_oauth_token(existing_key) and not cc_available:
        existing_is_stale_oauth = True

    has_creds = (bool(existing_key) and not existing_is_stale_oauth) or cc_available
    needs_auth = not has_creds

    if has_creds:
        # Show what we found
        if existing_key:
            print(f"  Credenciais Anthropic: {existing_key[:12]}... ✔")
        elif cc_available:
            print("  Credenciais do Claude Code: ✔ (detectadas automaticamente)")
        print()
        print("    1. Usar credenciais existentes")
        print("    2. Reautenticar (novo login OAuth)")
        print("    3. Cancelar")
        print()
        try:
            choice = input("  Escolha [1/2/3]: ").strip()
        except (KeyboardInterrupt, EOFError):
            choice = "1"

        if choice == "2":
            needs_auth = True
        elif choice == "3":
            return
        # choice == "1" or default: use existing, proceed to model selection

    if needs_auth:
        # Show auth method choice
        print()
        print("  Escolha o método de autenticação:")
        print()
        print("    1. Assinatura Claude Pro/Max (login OAuth)")
        print("    2. Chave API da Anthropic (pay-per-token)")
        print("    3. Cancelar")
        print()
        try:
            choice = input("  Escolha [1/2/3]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return

        if choice == "1":
            if not _run_anthropic_oauth_flow(save_env_value):
                return

        elif choice == "2":
            print()
            print("  Get an API key at: https://platform.claude.com/settings/keys")
            print()
            try:
                import getpass

                api_key = getpass.getpass("  Chave API (sk-ant-...): ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            if not api_key:
                print("  Cancelado.")
                return
            save_anthropic_api_key(api_key, save_fn=save_env_value)
            print("  ✔ Chave API salva.")

        else:
            print("  Nenhuma alteração.")
            return
    print()

    # Model selection
    model_list = _PROVIDER_MODELS.get("anthropic", [])
    if model_list:
        selected = _prompt_model_selection(model_list, current_model=current_model)
    else:
        try:
            selected = input("Nome do modelo (ex: claude-sonnet-4-20250514): ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    if selected:
        _save_model_choice(selected)

        # Update config with provider — clear base_url since
        # resolve_runtime_provider() always hardcodes Anthropic's URL.
        # Leaving a stale base_url in config can contaminate other
        # providers if the user switches without running 'ector provider'.
        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = "anthropic"
        model.pop("base_url", None)
        save_config(cfg)
        deactivate_provider()

        print(f"Modelo padrão definido para: {selected} (via Anthropic)")
    else:
        print("Nenhuma alteração.")


