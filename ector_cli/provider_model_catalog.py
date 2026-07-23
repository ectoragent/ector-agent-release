from __future__ import annotations

from typing import Any, Dict, List, Sequence


# -----------------------------------------------------------------------------
# Shared provider/model catalog for CLI + Web setup
# -----------------------------------------------------------------------------

SETUP_PROVIDER_ORDER: tuple[str, ...] = (
    "openai",
    "anthropic",
    "openrouter",
    "gemini",
    "google-gemini-cli",
    "deepseek",
    "zai",
    "kimi-coding",
    "kimi-coding-cn",
    "alibaba",
    "xai",
    "nvidia",
    "huggingface",
    "minimax",
    "minimax-cn",
    "ollama-cloud",
    "ai-gateway",
    "kilocode",
    "arcee",
    "xiaomi",
    "stepfun",
    "azure-foundry",
    "copilot",
)


def _recommended_models_for_setup_provider(provider_id: str) -> List[str]:
    """Model hints for web/CLI pickers — mirrors ``_PROVIDER_MODELS`` in models.py."""
    from ector_cli.models import OPENROUTER_MODELS, _PROVIDER_MODELS

    pid = (provider_id or "").strip().lower()
    if pid == "openrouter":
        curated = _PROVIDER_MODELS.get("openrouter") or _PROVIDER_MODELS.get("ector")
        if curated:
            return list(curated)
        return [model_id for model_id, _ in OPENROUTER_MODELS]

    models = _PROVIDER_MODELS.get(pid)
    return list(models) if models else []


def _build_recommended_models_by_provider() -> Dict[str, List[str]]:
    """Build picker hints for every provider in the setup wizard order."""
    out: Dict[str, List[str]] = {}
    for pid in SETUP_PROVIDER_ORDER:
        hints = _recommended_models_for_setup_provider(pid)
        if hints:
            out[pid] = hints
    return out


# Recommended models for setup pickers (synced from ector_cli.models._PROVIDER_MODELS).
RECOMMENDED_MODELS_BY_PROVIDER: Dict[str, List[str]] = _build_recommended_models_by_provider()

WEB_PICKER_MAX_MODELS_PER_PROVIDER = 4
# OAuth/native providers with a small curated lineup — show the full list.
_PICKER_UNCAPPED_PROVIDERS = frozenset({"anthropic"})


def get_recommended_models(provider_id: str) -> List[str]:
    pid = (provider_id or "").strip().lower()
    return list(RECOMMENDED_MODELS_BY_PROVIDER.get(pid, []))


def merge_recommended_first(
    provider_id: str,
    *,
    models: Sequence[str],
) -> List[str]:
    """Return a new list with recommended models first (stable order, unique).

    Keeps the original order of the input list for non-recommended items.
    """
    recommended = get_recommended_models(provider_id)
    if not recommended:
        return list(models)

    seen = set()
    out: List[str] = []

    def _add(m: str) -> None:
        k = m.lower()
        if k in seen:
            return
        seen.add(k)
        out.append(m)

    for m in recommended:
        _add(m)
    for m in models:
        _add(m)
    return out


def picker_models_for_provider(
    provider_id: str,
    *,
    config_models: Sequence[str] | None = None,
    fallback_models: Sequence[str] | None = None,
    active_model: str = "",
    max_models: int = WEB_PICKER_MAX_MODELS_PER_PROVIDER,
) -> List[str]:
    """Curated picker list: recommended first, then config/fallback, capped."""
    pid = (provider_id or "").strip()
    extra = [str(m).strip() for m in (config_models or []) if str(m).strip()]
    curated = get_recommended_models(pid)

    if len(extra) >= 2:
        models = list(extra)
    elif curated:
        models = merge_recommended_first(pid, models=extra)
    elif fallback_models:
        models = merge_recommended_first(pid, models=list(fallback_models))
    else:
        models = list(extra)

    active = (active_model or "").strip()
    if active and active not in models:
        models = [active, *models]

    cap = 0 if pid.lower() in _PICKER_UNCAPPED_PROVIDERS else max_models
    if cap > 0:
        return models[:cap]
    return models


def build_setup_catalog_rows(*, provider_registry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build setup catalog rows used by the web wizard.

    Expects provider_registry values to behave like ProviderConfig (auth_type,
    api_key_env_vars, base_url_env_var, name, id).
    """
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for pid in SETUP_PROVIDER_ORDER:
        if pid == "openrouter":
            rows.append(
                {
                    "id": "openrouter",
                    "name": "OpenRouter",
                    "auth_type": "api_key",
                    "api_key_env_vars": ["OPENROUTER_API_KEY"],
                    "base_url_env_var": "OPENROUTER_BASE_URL",
                    "model_hints": get_recommended_models("openrouter"),
                }
            )
            seen.add("openrouter")
            continue

        p = provider_registry.get(pid)
        if not p or getattr(p, "auth_type", "") != "api_key" or not getattr(p, "api_key_env_vars", None):
            continue

        rows.append(
            {
                "id": p.id,
                "name": p.name,
                "auth_type": p.auth_type,
                "api_key_env_vars": list(p.api_key_env_vars),
                "base_url_env_var": p.base_url_env_var or "",
                "model_hints": get_recommended_models(p.id),
            }
        )
        seen.add(p.id)

    for pid in SETUP_PROVIDER_ORDER:
        if pid in seen:
            continue
        p = provider_registry.get(pid)
        if not p or getattr(p, "auth_type", "") != "oauth_external":
            continue
        rows.append(
            {
                "id": p.id,
                "name": p.name,
                "auth_type": p.auth_type,
                "api_key_env_vars": [],
                "base_url_env_var": p.base_url_env_var or "",
                "model_hints": get_recommended_models(p.id),
            }
        )
        seen.add(p.id)

    for pid, p in provider_registry.items():
        if pid in seen:
            continue
        if getattr(p, "auth_type", "") != "api_key" or not getattr(p, "api_key_env_vars", None):
            continue
        rows.append(
            {
                "id": p.id,
                "name": p.name,
                "auth_type": p.auth_type,
                "api_key_env_vars": list(p.api_key_env_vars),
                "base_url_env_var": p.base_url_env_var or "",
                "model_hints": get_recommended_models(p.id),
            }
        )

    return rows
