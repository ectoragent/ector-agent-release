"""Check whether any inference provider is configured for first-run guard."""

from __future__ import annotations


def _provider_has_env_credentials(pconfig) -> bool:
    """True when ~/.ector/.env or env has a usable key for *pconfig*."""
    from ector_cli.auth import has_usable_secret
    from ector_cli.config import get_env_value

    _IMPLICIT_ENV_VARS = {"CLAUDE_CODE_OAUTH_TOKEN"}
    for env_var in pconfig.api_key_env_vars:
        if env_var in _IMPLICIT_ENV_VARS:
            continue
        if has_usable_secret(get_env_value(env_var) or ""):
            return True
    return False


def _openrouter_keys_present() -> bool:
    from ector_cli.auth import has_usable_secret
    from ector_cli.config import get_env_value

    for env_var in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        if has_usable_secret(get_env_value(env_var) or ""):
            return True
    return False


def _provider_configured_reason() -> str | None:
    """Return a short reason tag when Ector has explicit inference setup, else None.

    Stray shell env vars (OPENAI_BASE_URL, OPENAI_API_KEY, GH_TOKEN, …) must
    not bypass the first-run guard after ``ector reset`` — only credentials tied
    to an explicit Ector choice count (auth store, model.provider, endpoints).
    """
    from ector_cli.auth import PROVIDER_REGISTRY, get_active_provider, get_auth_status
    from ector_cli.config import DEFAULT_CONFIG, load_config

    _DEFAULT_MODEL = DEFAULT_CONFIG.get("model", "")
    cfg = load_config()
    model_cfg = cfg.get("model")
    if isinstance(model_cfg, dict):
        _model_name = (model_cfg.get("default") or "").strip()
    elif isinstance(model_cfg, str):
        _model_name = model_cfg.strip()
    else:
        _model_name = ""
    _has_ector_config = bool(_model_name and _model_name != _DEFAULT_MODEL)

    active = get_active_provider()
    if active:
        status = get_auth_status(active)
        if status.get("logged_in"):
            return f"active_provider:{active}"

    if isinstance(model_cfg, dict):
        provider_id = (model_cfg.get("provider") or "").strip().lower()
        cfg_base_url = (model_cfg.get("base_url") or "").strip()
        cfg_api_key = (model_cfg.get("api_key") or "").strip()

        if provider_id == "openrouter":
            if _openrouter_keys_present() or cfg_api_key:
                return "config_provider:openrouter"
        elif provider_id in PROVIDER_REGISTRY:
            pconfig = PROVIDER_REGISTRY[provider_id]
            if pconfig.auth_type == "api_key":
                if _provider_has_env_credentials(pconfig) or cfg_api_key:
                    return f"config_provider:{provider_id}"
            elif get_auth_status(provider_id).get("logged_in"):
                return f"config_provider:{provider_id}"
        elif provider_id and (provider_id.startswith("custom") or provider_id.startswith("custom:")):
            if cfg_base_url or cfg_api_key:
                return f"config_provider:{provider_id}"

        if cfg_base_url or cfg_api_key:
            return "config_model_endpoint"

    if _has_ector_config:
        provider_id = ""
        if isinstance(model_cfg, dict):
            provider_id = (model_cfg.get("provider") or "").strip().lower()
        if not provider_id or provider_id == "openrouter":
            if _openrouter_keys_present():
                return "ector_model:openrouter"
        if provider_id in PROVIDER_REGISTRY:
            pconfig = PROVIDER_REGISTRY[provider_id]
            if pconfig.auth_type == "api_key" and _provider_has_env_credentials(pconfig):
                return f"ector_model:{provider_id}"
            if get_auth_status(provider_id).get("logged_in"):
                return f"ector_model:{provider_id}"
        try:
            from agent.anthropic_adapter import (
                is_claude_code_token_valid,
                read_claude_code_credentials,
            )

            creds = read_claude_code_credentials()
            if creds and (
                is_claude_code_token_valid(creds) or creds.get("refreshToken")
            ):
                return "claude_code_oauth"
        except Exception:
            pass

    return None


def has_any_provider_configured() -> bool:
    """Check if at least one inference provider is usable."""
    return _provider_configured_reason() is not None
