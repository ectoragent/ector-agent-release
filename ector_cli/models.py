"""
Canonical model catalogs and lightweight validation helpers.

Add, remove, or reorder entries here — both `ector setup` and
`ector` provider-selection will pick up the change automatically.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
import time
from difflib import get_close_matches
from pathlib import Path
from typing import Any, NamedTuple, Optional

from ector_cli import __version__ as _ECTOR_VERSION

# Identify ourselves so endpoints fronted by Cloudflare's Browser Integrity
# Check (error 1010) don't reject the default ``Python-urllib/*`` signature.
_ECTOR_USER_AGENT = f"ector-cli/{_ECTOR_VERSION}"

COPILOT_BASE_URL = "https://api.githubcopilot.com"
COPILOT_MODELS_URL = f"{COPILOT_BASE_URL}/models"
COPILOT_EDITOR_VERSION = "vscode/1.104.1"
COPILOT_REASONING_EFFORTS_GPT5 = ["minimal", "low", "medium", "high"]
COPILOT_REASONING_EFFORTS_O_SERIES = ["low", "medium", "high"]


# Curated ector.cc / OpenRouter agentic subset — single source of truth.
# Synced from OpenRouter + provider docs (2026-06). Descriptions are menu-only.
_ECTOR_CURATED_DESCRIPTIONS: dict[str, str] = {
    "moonshotai/kimi-k2.6": "recomendado",
    "minimax/minimax-m2.5:free": "grátis",
    "moonshotai/kimi-k2.6:free": "grátis",
    "nvidia/nemotron-3-super-120b-a12b:free": "grátis",
    "nvidia/nemotron-3-ultra-550b-a55b:free": "grátis",
    "openrouter/elephant-alpha": "grátis",
}

ECTOR_CURATED_MODEL_IDS: list[str] = [
    "moonshotai/kimi-k2.6",
    "anthropic/claude-opus-4.8",
    "anthropic/claude-opus-4.7",
    "anthropic/claude-opus-4.6",
    "anthropic/claude-sonnet-4.6",
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-haiku-4.5",
    "openai/gpt-5.5",
    "openai/gpt-5.5-pro",
    "openai/gpt-5.4",
    "openai/gpt-5.4-mini",
    "openai/gpt-5.4-nano",
    "openai/gpt-5.3-codex",
    "google/gemini-3.5-flash",
    "google/gemini-3.1-pro-preview",
    "google/gemini-3-flash-preview",
    "google/gemini-3-pro-preview",
    "google/gemini-3.1-flash-lite-preview",
    "xiaomi/mimo-v2.5-pro",
    "xiaomi/mimo-v2.5",
    "qwen/qwen3.7-plus",
    "qwen/qwen3.6-plus",
    "qwen/qwen3.5-35b-a3b",
    "stepfun/step-3.7-flash",
    "stepfun/step-3.5-flash",
    "minimax/minimax-m3",
    "minimax/minimax-m2.7",
    "minimax/minimax-m2.7-highspeed",
    "minimax/minimax-m2.5",
    "minimax/minimax-m2.5-highspeed",
    "minimax/minimax-m2.5:free",
    "z-ai/glm-5.1",
    "z-ai/glm-5v-turbo",
    "z-ai/glm-5-turbo",
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
    "x-ai/grok-4.20",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3-super-120b-a12b",
    "arcee-ai/trinity-large-thinking",
    "openrouter/elephant-alpha",
]

# Fallback OpenRouter snapshot used when the live catalog is unavailable.
OPENROUTER_MODELS: list[tuple[str, str]] = [
    (mid, _ECTOR_CURATED_DESCRIPTIONS.get(mid, ""))
    for mid in ECTOR_CURATED_MODEL_IDS
]

_openrouter_catalog_cache: list[tuple[str, str]] | None = None


# Fallback Vercel AI Gateway snapshot used when the live catalog is unavailable.
# OSS / open-weight models prioritized first, then closed-source by family.
# Slugs match Vercel's actual /v1/models catalog (e.g. alibaba/ for Qwen,
# zai/ and xai/ without hyphens).
VERCEL_AI_GATEWAY_MODELS: list[tuple[str, str]] = [
    ("moonshotai/kimi-k2.6",                 "recomendado"),
    ("alibaba/qwen3.7-plus",                 ""),
    ("alibaba/qwen3.6-plus",                 ""),
    ("zai/glm-5.1",                          ""),
    ("minimax/minimax-m3",                   ""),
    ("minimax/minimax-m2.7",                 ""),
    ("anthropic/claude-opus-4.8",            ""),
    ("anthropic/claude-sonnet-4.6",          ""),
    ("anthropic/claude-opus-4.7",            ""),
    ("anthropic/claude-opus-4.6",            ""),
    ("anthropic/claude-haiku-4.5",           ""),
    ("openai/gpt-5.5",                       ""),
    ("openai/gpt-5.4",                       ""),
    ("openai/gpt-5.4-mini",                  ""),
    ("openai/gpt-5.3-codex",                 ""),
    ("google/gemini-3.5-flash",              ""),
    ("google/gemini-3.1-pro-preview",        ""),
    ("google/gemini-3-flash-preview",        ""),
    ("google/gemini-3.1-flash-lite-preview", ""),
    ("xai/grok-4.20",                        ""),
]

_ai_gateway_catalog_cache: list[tuple[str, str]] | None = None


def _codex_curated_models() -> list[str]:
    """Derive the openai-codex curated list from codex_models.py.

    Single source of truth: DEFAULT_CODEX_MODELS + forward-compat synthesis.
    This keeps the gateway /provider picker in sync with the CLI `ector provider`
    flow without maintaining a separate static list.
    """
    from ector_cli.codex_models import DEFAULT_CODEX_MODELS, _add_forward_compat_models
    return _add_forward_compat_models(list(DEFAULT_CODEX_MODELS))


_PROVIDER_MODELS: dict[str, list[str]] = {
    "ector": list(ECTOR_CURATED_MODEL_IDS),
    # Native OpenAI Chat Completions (api.openai.com). Used by /provider counts and
    # provider_model_ids fallback when /v1/models is unavailable.
    "openai": [
        "gpt-5.5",
        "gpt-5.5-pro",
        "gpt-5.4",
        "gpt-5.4-pro",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5-mini",
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-4.1",
        "gpt-4o",
        "gpt-4o-mini",
    ],
    "openai-codex": _codex_curated_models(),
    "copilot-acp": [
        "copilot-acp",
    ],
    "copilot": [
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5-mini",
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-4.1",
        "gpt-4o",
        "gpt-4o-mini",
        "claude-opus-4.7",
        "claude-sonnet-4.6",
        "claude-sonnet-4",
        "claude-sonnet-4.5",
        "claude-haiku-4.5",
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3-pro-preview",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
        "grok-4.3",
    ],
    "gemini": [
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite-preview",
        "gemini-3-flash-preview",
        "gemini-3-pro-preview",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
    ],
    "google-gemini-cli": [
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite-preview",
        "gemini-3-flash-preview",
        "gemini-3-pro-preview",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
    ],
    "zai": [
        "glm-5.1",
        "glm-5",
        "glm-5v-turbo",
        "glm-5-turbo",
        "glm-4.7",
        "glm-4.5",
        "glm-4.5-flash",
    ],
    "xai": [
        "grok-4.3",
        "grok-4.20-0309-reasoning",
        "grok-4.20-0309-non-reasoning",
        "grok-4.20-multi-agent-0309",
        "grok-build-0.1",
    ],
    "nvidia": [
        # NVIDIA flagship reasoning models
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/nemotron-3-super-120b-a12b",
        "nvidia/nemotron-3-nano-30b-a3b",
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        # Third-party agentic models hosted on build.nvidia.com
        # (map to OpenRouter defaults — users get familiar picks on NIM)
        "qwen/qwen3.7-plus",
        "qwen/qwen3.5-397b-a17b",
        "deepseek-ai/deepseek-v3.2",
        "moonshotai/kimi-k2.6",
        "minimaxai/minimax-m2.7",
        "minimaxai/minimax-m3",
        "z-ai/glm5",
        "openai/gpt-oss-120b",
    ],
    "kimi-coding": [
        "kimi-k2.6",
        "kimi-for-coding",
        "kimi-k2.5",
    ],
    "kimi-coding-cn": [
        "kimi-k2.6",
        "kimi-k2.5",
    ],
    "stepfun": [
        "step-3.7-flash",
        "step-3.5-flash",
        "step-3.5-flash-2603",
    ],
    "moonshot": [
        "kimi-k2.6",
        "kimi-k2.5",
    ],
    "minimax": [
        "MiniMax-M3",
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
        "MiniMax-M2.5",
        "MiniMax-M2.5-highspeed",
        "MiniMax-M2.1",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
    ],
    "minimax-cn": [
        "MiniMax-M3",
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
        "MiniMax-M2.5",
        "MiniMax-M2.5-highspeed",
        "MiniMax-M2.1",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
    ],
    "anthropic": [
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-opus-4-5-20251101",
        "claude-sonnet-4-5-20250929",
        "claude-opus-4-20250514",
        "claude-sonnet-4-20250514",
        "claude-haiku-4-5-20251001",
    ],
    "deepseek": [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "xiaomi": [
        "mimo-v2.5-pro",
        "mimo-v2.5",
        "mimo-v2-pro",
        "mimo-v2-omni",
        "mimo-v2-flash",
    ],
    "arcee": [
        "trinity-large-thinking",
        "trinity-large-preview",
        "trinity-mini",
    ],
    "kilocode": [
        "anthropic/claude-opus-4.8",
        "anthropic/claude-sonnet-4.6",
        "openai/gpt-5.5",
        "google/gemini-3.5-flash",
    ],
    # Alibaba DashScope Coding platform (coding-intl) — default endpoint.
    # Supports Qwen models + third-party providers (GLM, Kimi, MiniMax).
    # Users with classic DashScope keys should override DASHSCOPE_BASE_URL
    # to https://dashscope-intl.aliyuncs.com/compatible-mode/v1 (OpenAI-compat)
    # or https://dashscope-intl.aliyuncs.com/apps/anthropic (Anthropic-compat).
    "alibaba": [
        "kimi-k2.6",
        "kimi-k2.5",
        "qwen3.7-plus",
        "qwen3.6-plus",
        "qwen3-coder-plus",
        "qwen3-coder-next",
        # Third-party models available on coding-intl
        "glm-5",
        "glm-4.7",
        "MiniMax-M3",
        "MiniMax-M2.7",
        "MiniMax-M2.5",
    ],
    # Curated HF model list — only agentic models that map to OpenRouter defaults.
    "huggingface": [
        "moonshotai/Kimi-K2.6",
        "moonshotai/Kimi-K2.5",
        "Qwen/Qwen3.5-397B-A17B",
        "Qwen/Qwen3.5-35B-A3B",
        "deepseek-ai/DeepSeek-V3.2",
        "MiniMaxAI/MiniMax-M3",
        "MiniMaxAI/MiniMax-M2.7",
        "MiniMaxAI/MiniMax-M2.5",
        "zai-org/GLM-5",
        "XiaomiMiMo/MiMo-V2-Flash",
    ],
    # AWS Bedrock — static fallback list used when dynamic discovery is
    # unavailable (no boto3, no credentials, or API error).  The agent
    # prefers live discovery via ListFoundationModels + ListInferenceProfiles.
    # Use inference profile IDs (us.*) since most models require them.
    "bedrock": [
        "us.anthropic.claude-opus-4-8-v1",
        "us.anthropic.claude-opus-4-7-v1",
        "us.anthropic.claude-sonnet-4-6",
        "us.anthropic.claude-opus-4-6-v1",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "us.amazon.nova-pro-v1:0",
        "us.amazon.nova-lite-v1:0",
        "us.amazon.nova-micro-v1:0",
        "deepseek.v3.2",
        "us.meta.llama4-maverick-17b-instruct-v1:0",
        "us.meta.llama4-scout-17b-instruct-v1:0",
    ],
    # Azure Foundry: user-provided endpoint and model.
    # Empty list because models depend on the endpoint configuration.
    "azure-foundry": [],
    # Ollama Cloud static fallback when live /v1/models is unreachable.
    "ollama-cloud": [
        "gpt-oss:120b",
        "kimi-k2.6",
        "kimi-k2.5",
        "qwen3-coder-next",
        "deepseek-v3.2",
        "glm-4.7",
        "minimax-m2.7",
        "minimax-m2.5",
    ],
}

# OpenRouter picker uses the same curated agentic subset as the default Ector route.
_PROVIDER_MODELS["openrouter"] = list(_PROVIDER_MODELS["ector"])

# Vercel AI Gateway: derive the bare-model-id catalog from the curated
# ``VERCEL_AI_GATEWAY_MODELS`` snapshot so both the picker (tuples with descriptions)
# and the static fallback catalog (bare ids) stay in sync from a single
# source of truth.
_PROVIDER_MODELS["ai-gateway"] = [mid for mid, _ in VERCEL_AI_GATEWAY_MODELS]

# ---------------------------------------------------------------------------
# Canonical provider list — single source of truth for provider identity.
# Every code path that lists, displays, or iterates providers derives from
# this list:  ector provider, /provider, list_authenticated_providers.
#
# Fields:
#   slug        — internal provider ID (used in config.yaml, --provider flag)
#   label       — short display name
#   tui_desc    — longer description for the `ector provider` interactive picker
# ---------------------------------------------------------------------------

class ProviderEntry(NamedTuple):
    slug: str
    label: str
    tui_desc: str   # detailed description for `ector provider` TUI


CANONICAL_PROVIDERS: list[ProviderEntry] = [
    ProviderEntry("openrouter",     "OpenRouter",               "OpenRouter (mais de 100 modelos, pague pelo uso)"),
    ProviderEntry("ai-gateway",     "Vercel AI Gateway",        "Vercel AI Gateway (mais de 200 modelos, $5 de crédito grátis, sem markup)"),
    ProviderEntry("anthropic",      "Anthropic",                "Anthropic (modelos Claude — chave API ou Claude Code)"),
    ProviderEntry("openai",         "OpenAI",                   "OpenAI API Direta (GPT-4o, o1, etc — requer OPENAI_API_KEY)"),
    ProviderEntry("openai-codex",   "OpenAI Codex",             "OpenAI Codex"),
    ProviderEntry("copilot",        "GitHub Copilot",           "GitHub Copilot (usa GITHUB_TOKEN ou token de autenticação gh)"),
    ProviderEntry("copilot-acp",    "GitHub Copilot ACP",       "GitHub Copilot ACP (inicia `copilot --acp --stdio`)"),
    ProviderEntry("huggingface",    "Hugging Face",             "Provedores de Inferência Hugging Face (mais de 20 modelos abertos)"),
    ProviderEntry("gemini",         "Google Gemini",              "Google Gemini via API key (Google AI Studio / GEMINI_API_KEY)"),
    ProviderEntry("google-gemini-cli", "Google Gemini (OAuth)",   "Google Gemini via OAuth + Code Assist (nível grátis suportado; sem necessidade de chave API)"),
    ProviderEntry("deepseek",       "DeepSeek",                 "DeepSeek (V4-Flash/V4-Pro — 1M contexto, tool calls, caching — API direta)"),
    ProviderEntry("ollama-cloud",   "Ollama Cloud",             "Ollama Cloud (modelos abertos hospedados na nuvem — ollama.com)"),
    ProviderEntry("minimax",        "MiniMax",                  "MiniMax (API direta global)"),
    ProviderEntry("bedrock",        "AWS Bedrock",              "AWS Bedrock (Claude, Nova, Llama, DeepSeek — IAM ou chave API)"),
    ProviderEntry("azure-foundry",  "Azure Foundry",            "Azure Foundry (endpoint estilo OpenAI ou Anthropic — sua implantação Azure AI)"),
]

# Derived dicts — used throughout the codebase
_PROVIDER_LABELS = {p.slug: p.label for p in CANONICAL_PROVIDERS}
_PROVIDER_LABELS["custom"] = "Custom endpoint"  # special case: not a named provider

# Providers hidden from the interactive picker (Brazil-focused UX), but still
# supported via config/flags (and kept in `_PROVIDER_ALIASES` / `_PROVIDER_MODELS`).
_HIDDEN_PICKER_PROVIDERS: frozenset[str] = frozenset({
    "xiaomi",
    "nvidia",
    "qwen-oauth",
    "xai",
    "zai",
    "kimi-coding",
    "kimi-coding-cn",
    "stepfun",
    "minimax-cn",
    "alibaba",
    "arcee",
    "kilocode",
})

# Keep labels for hidden-but-supported providers so parsing/normalization and
# non-interactive flows don't degrade to raw slugs.
_PROVIDER_LABELS.update({
    "xiaomi": "Xiaomi MiMo",
    "nvidia": "NVIDIA NIM",
    "qwen-oauth": "Qwen OAuth (Portal)",
    "xai": "xAI",
    "zai": "Z.AI / GLM",
    "kimi-coding": "Kimi / Kimi Coding Plan",
    "kimi-coding-cn": "Kimi / Moonshot (China)",
    "stepfun": "StepFun Step Plan",
    "minimax": "MiniMax",
    "minimax-cn": "MiniMax (China)",
    "alibaba": "Alibaba Cloud (DashScope)",
    "arcee": "Arcee AI",
    "kilocode": "Kilo Code",
})


_PROVIDER_ALIASES = {
    "glm": "zai",
    "z-ai": "zai",
    "z.ai": "zai",
    "zhipu": "zai",
    "github": "copilot",
    "github-copilot": "copilot",
    "github-models": "copilot",
    "github-model": "copilot",
    "github-copilot-acp": "copilot-acp",
    "copilot-acp-agent": "copilot-acp",
    "google": "gemini",
    "google-gemini": "gemini",
    "google-ai-studio": "gemini",
    "kimi": "kimi-coding",
    "moonshot": "kimi-coding",
    "kimi-cn": "kimi-coding-cn",
    "moonshot-cn": "kimi-coding-cn",
    "step": "stepfun",
    "stepfun-coding-plan": "stepfun",
    "arcee-ai": "arcee",
    "arceeai": "arcee",
    "minimax-china": "minimax-cn",
    "minimax_cn": "minimax-cn",
    "claude": "anthropic",
    "claude-code": "anthropic",
    "deep-seek": "deepseek",
    "aigateway": "ai-gateway",
    "vercel": "ai-gateway",
    "vercel-ai-gateway": "ai-gateway",
    "kilo": "kilocode",
    "kilo-code": "kilocode",
    "kilo-gateway": "kilocode",
    "dashscope": "alibaba",
    "aliyun": "alibaba",
    "qwen": "alibaba",
    "alibaba-cloud": "alibaba",
    "qwen-portal": "qwen-oauth",
    "gemini-cli": "google-gemini-cli",
    "gemini-oauth": "google-gemini-cli",
    "hf": "huggingface",
    "hugging-face": "huggingface",
    "huggingface-hub": "huggingface",
    "mimo": "xiaomi",
    "xiaomi-mimo": "xiaomi",
    "aws": "bedrock",
    "aws-bedrock": "bedrock",
    "amazon-bedrock": "bedrock",
    "amazon": "bedrock",
    "grok": "xai",
    "x-ai": "xai",
    "x.ai": "xai",
    "nim": "nvidia",
    "nvidia-nim": "nvidia",
    "build-nvidia": "nvidia",
    "nemotron": "nvidia",
    "ollama": "custom",  # bare "ollama" = local; use "ollama-cloud" for cloud
    "ollama_cloud": "ollama-cloud",
}


def get_default_model_for_provider(provider: str) -> str:
    """Return the default model for a provider, or empty string if unknown.

    Uses the first entry in _PROVIDER_MODELS as the default.  This is the
    model a user would be offered first in the ``ector provider`` picker.

    Used as a fallback when the user has configured a provider but never
    selected a model (e.g. ``ector auth add openai-codex`` without
    ``ector provider``).
    """
    models = _PROVIDER_MODELS.get(provider, [])
    return models[0] if models else ""


def _openrouter_model_is_free(pricing: Any) -> bool:
    """Return True when both prompt and completion pricing are zero."""
    if not isinstance(pricing, dict):
        return False
    try:
        return float(pricing.get("prompt", "0")) == 0 and float(pricing.get("completion", "0")) == 0
    except (TypeError, ValueError):
        return False


def _openrouter_model_supports_tools(item: Any) -> bool:
    """Return True when the model's ``supported_parameters`` advertise tool calling.

    ector-agent is tool-calling-first — every provider path assumes the model
    can invoke tools. Models that don't advertise ``tools`` in their
    ``supported_parameters`` (e.g. image-only or completion-only models) cannot
    be driven by the agent loop and would fail at the first tool call.

    **Permissive when the field is missing.** Some OpenRouter-compatible gateways
    (ector.cc, private mirrors, older catalog snapshots) don't populate
    ``supported_parameters`` at all. Treat that as "unknown capability → allow"
    so the picker doesn't silently empty for those users. Only hide models
    whose ``supported_parameters`` is an explicit list that omits ``tools``.

    Ported from Kilo-Org/kilocode#9068.
    """
    if not isinstance(item, dict):
        return True
    params = item.get("supported_parameters")
    if not isinstance(params, list):
        # Field absent / malformed / None — be permissive.
        return True
    return "tools" in params


def fetch_openrouter_models(
    timeout: float = 8.0,
    *,
    force_refresh: bool = False,
) -> list[tuple[str, str]]:
    """Return the curated OpenRouter picker list, refreshed from the live catalog when possible."""
    global _openrouter_catalog_cache

    if _openrouter_catalog_cache is not None and not force_refresh:
        return list(_openrouter_catalog_cache)

    fallback = list(OPENROUTER_MODELS)
    preferred_ids = [mid for mid, _ in fallback]

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except Exception:
        return list(_openrouter_catalog_cache or fallback)

    live_items = payload.get("data", [])
    if not isinstance(live_items, list):
        return list(_openrouter_catalog_cache or fallback)

    live_by_id: dict[str, dict[str, Any]] = {}
    for item in live_items:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        live_by_id[mid] = item

    curated: list[tuple[str, str]] = []
    for preferred_id in preferred_ids:
        live_item = live_by_id.get(preferred_id)
        if live_item is None:
            continue
        # Hide models that don't advertise tool-calling support — ector-agent
        # requires it and surfacing them leads to immediate runtime failures
        # when the user selects them. Ported from Kilo-Org/kilocode#9068.
        if not _openrouter_model_supports_tools(live_item):
            continue
        desc = "free" if _openrouter_model_is_free(live_item.get("pricing")) else ""
        curated.append((preferred_id, desc))

    if not curated:
        return list(_openrouter_catalog_cache or fallback)

    first_id, _ = curated[0]
    curated[0] = (first_id, "recommended")
    _openrouter_catalog_cache = curated
    return list(curated)


def model_ids(*, force_refresh: bool = False) -> list[str]:
    """Return just the OpenRouter model-id strings."""
    return [mid for mid, _ in fetch_openrouter_models(force_refresh=force_refresh)]


def get_curated_ector_model_ids() -> list[str]:
    """Return the curated ector.cc model-id list from the in-repo snapshot."""
    return list(_PROVIDER_MODELS.get("ector", []))


def _ai_gateway_model_is_free(pricing: Any) -> bool:
    """Return True if an AI Gateway model has $0 input AND output pricing."""
    if not isinstance(pricing, dict):
        return False
    try:
        return float(pricing.get("input", "0")) == 0 and float(pricing.get("output", "0")) == 0
    except (TypeError, ValueError):
        return False


def fetch_ai_gateway_models(
    timeout: float = 8.0,
    *,
    force_refresh: bool = False,
) -> list[tuple[str, str]]:
    """Return the curated AI Gateway picker list, refreshed from the live catalog when possible."""
    global _ai_gateway_catalog_cache

    if _ai_gateway_catalog_cache is not None and not force_refresh:
        return list(_ai_gateway_catalog_cache)

    from ector_constants import AI_GATEWAY_BASE_URL

    fallback = list(VERCEL_AI_GATEWAY_MODELS)
    preferred_ids = [mid for mid, _ in fallback]

    try:
        req = urllib.request.Request(
            f"{AI_GATEWAY_BASE_URL.rstrip('/')}/models",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except Exception:
        return list(_ai_gateway_catalog_cache or fallback)

    live_items = payload.get("data", [])
    if not isinstance(live_items, list):
        return list(_ai_gateway_catalog_cache or fallback)

    live_by_id: dict[str, dict[str, Any]] = {}
    for item in live_items:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        live_by_id[mid] = item

    curated: list[tuple[str, str]] = []
    for preferred_id in preferred_ids:
        live_item = live_by_id.get(preferred_id)
        if live_item is None:
            continue
        desc = "free" if _ai_gateway_model_is_free(live_item.get("pricing")) else ""
        curated.append((preferred_id, desc))

    if not curated:
        return list(_ai_gateway_catalog_cache or fallback)

    # If the live catalog offers a free Moonshot model, auto-promote it to
    # position #1 as "recommended" — dynamic discovery without a PR.
    free_moonshot = next(
        (
            mid
            for mid, item in live_by_id.items()
            if mid.startswith("moonshotai/")
            and _ai_gateway_model_is_free(item.get("pricing"))
        ),
        None,
    )
    if free_moonshot:
        curated = [(mid, desc) for mid, desc in curated if mid != free_moonshot]
        curated.insert(0, (free_moonshot, "recommended"))
    else:
        first_id, _ = curated[0]
        curated[0] = (first_id, "recommended")

    _ai_gateway_catalog_cache = curated
    return list(curated)


def ai_gateway_model_ids(*, force_refresh: bool = False) -> list[str]:
    """Return just the AI Gateway model-id strings."""
    return [mid for mid, _ in fetch_ai_gateway_models(force_refresh=force_refresh)]




# ---------------------------------------------------------------------------
# Pricing helpers — fetch live pricing from OpenRouter-compatible /v1/models
# ---------------------------------------------------------------------------

# Cache: maps model_id → {"prompt": str, "completion": str} per endpoint
_pricing_cache: dict[str, dict[str, dict[str, str]]] = {}


def _format_price_per_mtok(per_token_str: str) -> str:
    """Convert a per-token price string to a human-friendly $/Mtok string.

    Always uses 2 decimal places so that prices align vertically when
    right-justified in a column (the decimal point stays in the same position).

    Examples:
        "0.000003"   → "$3.00"      (per million tokens)
        "0.00003"    → "$30.00"
        "0.00000015" → "$0.15"
        "0.0000001"  → "$0.10"
        "0.00018"    → "$180.00"
        "0"          → "free"
    """
    try:
        val = float(per_token_str)
    except (TypeError, ValueError):
        return "?"
    if val == 0:
        return "free"
    per_m = val * 1_000_000
    return f"${per_m:.2f}"


def format_model_pricing_table(
    models: list[tuple[str, str]],
    pricing_map: dict[str, dict[str, str]],
    current_model: str = "",
    indent: str = "      ",
) -> list[str]:
    """Build a column-aligned model+pricing table for terminal display.

    Returns a list of pre-formatted lines ready to print.
    *models* is ``[(model_id, description), ...]``.
    """
    if not models:
        return []

    # Build rows: (model_id, input_price, output_price, cache_price, is_current)
    rows: list[tuple[str, str, str, str, bool]] = []
    has_cache = False
    for mid, _desc in models:
        is_cur = mid == current_model
        p = pricing_map.get(mid)
        if p:
            inp = _format_price_per_mtok(p.get("prompt", ""))
            out = _format_price_per_mtok(p.get("completion", ""))
            cache_read = p.get("input_cache_read", "")
            cache = _format_price_per_mtok(cache_read) if cache_read else ""
            if cache:
                has_cache = True
        else:
            inp, out, cache = "", "", ""
        rows.append((mid, inp, out, cache, is_cur))

    name_col = max(len(r[0]) for r in rows) + 2
    # Compute price column widths from the actual data so decimals align
    price_col = max(
        max((len(r[1]) for r in rows if r[1]), default=4),
        max((len(r[2]) for r in rows if r[2]), default=4),
        3,  # minimum: "In" / "Out" header
    )
    cache_col = max(
        max((len(r[3]) for r in rows if r[3]), default=4),
        5,  # minimum: "Cache" header
    ) if has_cache else 0
    lines: list[str] = []

    # Header
    if has_cache:
        lines.append(f"{indent}{'Modelo':<{name_col}} {'Entrada':>{price_col}}  {'Saída':>{price_col}}  {'Cache':>{cache_col}}  /Mtok")
        lines.append(f"{indent}{'-' * name_col} {'-' * price_col}  {'-' * price_col}  {'-' * cache_col}")
    else:
        lines.append(f"{indent}{'Modelo':<{name_col}} {'Entrada':>{price_col}}  {'Saída':>{price_col}}  /Mtok")
        lines.append(f"{indent}{'-' * name_col} {'-' * price_col}  {'-' * price_col}")

    for mid, inp, out, cache, is_cur in rows:
        marker = "  ← atual" if is_cur else ""
        if has_cache:
            lines.append(f"{indent}{mid:<{name_col}} {inp:>{price_col}}  {out:>{price_col}}  {cache:>{cache_col}}{marker}")
        else:
            lines.append(f"{indent}{mid:<{name_col}} {inp:>{price_col}}  {out:>{price_col}}{marker}")

    return lines


def fetch_models_with_pricing(
    api_key: str | None = None,
    base_url: str = "https://openrouter.ai/api",
    timeout: float = 8.0,
    *,
    force_refresh: bool = False,
) -> dict[str, dict[str, str]]:
    """Fetch ``/v1/models`` and return ``{model_id: {prompt, completion}}`` pricing.

    Results are cached per *base_url* so repeated calls are free.
    Works with any OpenRouter-compatible endpoint (OpenRouter, ector.cc).
    """
    cache_key = (base_url or "").rstrip("/")
    if not force_refresh and cache_key in _pricing_cache:
        return _pricing_cache[cache_key]

    url = cache_key.rstrip("/") + "/v1/models"
    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": _ECTOR_USER_AGENT,
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except Exception:
        _pricing_cache[cache_key] = {}
        return {}

    result: dict[str, dict[str, str]] = {}
    for item in payload.get("data", []):
        mid = item.get("id")
        pricing = item.get("pricing")
        if mid and isinstance(pricing, dict):
            entry: dict[str, str] = {
                "prompt": str(pricing.get("prompt", "")),
                "completion": str(pricing.get("completion", "")),
            }
            if pricing.get("input_cache_read"):
                entry["input_cache_read"] = str(pricing["input_cache_read"])
            if pricing.get("input_cache_write"):
                entry["input_cache_write"] = str(pricing["input_cache_write"])
            result[mid] = entry

    _pricing_cache[cache_key] = result
    return result


def fetch_ai_gateway_pricing(
    timeout: float = 8.0,
    *,
    force_refresh: bool = False,
) -> dict[str, dict[str, str]]:
    """Fetch Vercel AI Gateway /v1/models and return ector-shaped pricing.

    Vercel uses ``input`` / ``output`` field names; ector's picker expects
    ``prompt`` / ``completion``. This translates. Cache read/write field names
    already match.
    """
    from ector_constants import AI_GATEWAY_BASE_URL

    cache_key = AI_GATEWAY_BASE_URL.rstrip("/")
    if not force_refresh and cache_key in _pricing_cache:
        return _pricing_cache[cache_key]

    try:
        req = urllib.request.Request(
            f"{cache_key}/models",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except Exception:
        _pricing_cache[cache_key] = {}
        return {}

    result: dict[str, dict[str, str]] = {}
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        mid = item.get("id")
        pricing = item.get("pricing")
        if not (mid and isinstance(pricing, dict)):
            continue
        entry: dict[str, str] = {
            "prompt": str(pricing.get("input", "")),
            "completion": str(pricing.get("output", "")),
        }
        if pricing.get("input_cache_read"):
            entry["input_cache_read"] = str(pricing["input_cache_read"])
        if pricing.get("input_cache_write"):
            entry["input_cache_write"] = str(pricing["input_cache_write"])
        result[mid] = entry

    _pricing_cache[cache_key] = result
    return result


def _resolve_openrouter_api_key() -> str:
    """Best-effort OpenRouter API key for pricing fetch."""
    return os.getenv("OPENROUTER_API_KEY", "").strip()


def _resolve_ector_catalog_credentials() -> tuple[str, str]:
    """Return ``(bearer_token, base_url)`` for ector.cc model catalog pricing."""
    try:
        from ector_cli.identity_auth import get_access_token

        token = get_access_token(auto_refresh=True)
        if token:
            return (token, "https://ector.cc")
    except Exception:
        pass
    return ("", "")


def get_pricing_for_provider(provider: str, *, force_refresh: bool = False) -> dict[str, dict[str, str]]:
    """Return live pricing for providers that support it (openrouter, ector, ai-gateway)."""
    normalized = normalize_provider(provider)
    if normalized == "openrouter":
        return fetch_models_with_pricing(
            api_key=_resolve_openrouter_api_key(),
            base_url="https://openrouter.ai/api",
            force_refresh=force_refresh,
        )
    if normalized == "ai-gateway":
        return fetch_ai_gateway_pricing(force_refresh=force_refresh)
    if normalized == "ector":
        api_key, base_url = _resolve_ector_catalog_credentials()
        if base_url:
            # Ector base_url typically looks like https://ector.cc/...
            # We need the part before /v1 for our fetch function
            stripped = base_url.rstrip("/")
            if stripped.endswith("/v1"):
                stripped = stripped[:-3]
            return fetch_models_with_pricing(
                api_key=api_key,
                base_url=stripped,
                force_refresh=force_refresh,
            )
    return {}


# All provider IDs and aliases that are valid for the provider:model syntax.
_KNOWN_PROVIDER_NAMES: set[str] = (
    set(_PROVIDER_LABELS.keys())
    | set(_PROVIDER_ALIASES.keys())
    | {"openrouter", "custom"}
)


def list_available_providers() -> list[dict[str, str]]:
    """Return info about all providers the user could use with ``provider:model``.

    Each dict has ``id``, ``label``, and ``aliases``.
    Checks which providers have valid credentials configured.

    Derives the provider list from :data:`CANONICAL_PROVIDERS` (single
    source of truth shared with ``ector provider``, ``/provider``, etc.).
    """
    # Derive display order from canonical list + custom
    provider_order = [p.slug for p in CANONICAL_PROVIDERS] + ["custom"]

    # Build reverse alias map
    aliases_for: dict[str, list[str]] = {}
    for alias, canonical in _PROVIDER_ALIASES.items():
        aliases_for.setdefault(canonical, []).append(alias)

    result = []
    for pid in provider_order:
        label = _PROVIDER_LABELS.get(pid, pid)
        alias_list = aliases_for.get(pid, [])
        # Check if this provider has credentials available
        has_creds = False
        try:
            from ector_cli.auth import get_auth_status, has_usable_secret
            if pid == "custom":
                custom_base_url = _get_custom_base_url() or ""
                has_creds = bool(custom_base_url.strip())
            elif pid == "openrouter":
                has_creds = has_usable_secret(os.getenv("OPENROUTER_API_KEY", ""))
            else:
                status = get_auth_status(pid)
                has_creds = bool(status.get("logged_in") or status.get("configured"))
        except Exception:
            pass
        result.append({
            "id": pid,
            "label": label,
            "aliases": alias_list,
            "authenticated": has_creds,
        })
    return result


def parse_model_input(raw: str, current_provider: str) -> tuple[str, str]:
    """Parse ``/provider`` input into ``(provider, model)``.

    Supports ``provider:model`` syntax to switch providers at runtime::

        openrouter:anthropic/claude-sonnet-4.5  →  ("openrouter", "anthropic/claude-sonnet-4.5")
        ector:ector-3                           →  ("ector", "ector-3")
        anthropic/claude-sonnet-4.5             →  (current_provider, "anthropic/claude-sonnet-4.5")
        gpt-5.4                                 →  (current_provider, "gpt-5.4")

    The colon is only treated as a provider delimiter if the left side is a
    recognized provider name or alias.  This avoids misinterpreting model names
    that happen to contain colons (e.g. ``anthropic/claude-3.5-sonnet:beta``).

    Returns ``(provider, model)`` where *provider* is either the explicit
    provider from the input or *current_provider* if none was specified.
    """
    stripped = raw.strip()
    colon = stripped.find(":")
    if colon > 0:
        provider_part = stripped[:colon].strip().lower()
        model_part = stripped[colon + 1:].strip()
        if provider_part and model_part and provider_part in _KNOWN_PROVIDER_NAMES:
            # Support custom:name:model triple syntax for named custom
            # providers.  ``custom:local:qwen`` → ("custom:local", "qwen").
            # Single colon ``custom:qwen`` → ("custom", "qwen") as before.
            if provider_part == "custom" and ":" in model_part:
                second_colon = model_part.find(":")
                custom_name = model_part[:second_colon].strip()
                actual_model = model_part[second_colon + 1:].strip()
                if custom_name and actual_model:
                    return (f"custom:{custom_name}", actual_model)
            return (normalize_provider(provider_part), model_part)
    return (current_provider, stripped)


def _get_custom_base_url() -> str:
    """Get the custom endpoint base_url from config.yaml."""
    try:
        from ector_cli.config import load_config
        config = load_config()
        model_cfg = config.get("model", {})
        if isinstance(model_cfg, dict):
            return str(model_cfg.get("base_url", "")).strip()
    except Exception:
        pass
    return ""


def curated_models_for_provider(
    provider: Optional[str],
    *,
    force_refresh: bool = False,
) -> list[tuple[str, str]]:
    """Return ``(model_id, description)`` tuples for a provider's model list.

    Tries to fetch the live model list from the provider's API first,
    falling back to the static ``_PROVIDER_MODELS`` catalog if the API
    is unreachable.
    """
    normalized = normalize_provider(provider)
    if normalized == "openrouter":
        return fetch_openrouter_models(force_refresh=force_refresh)

    # Try live API first (Codex, Ector, etc. all support /models)
    live = provider_model_ids(normalized)
    if live:
        return [(m, "") for m in live]

    # Fallback to static catalog
    models = _PROVIDER_MODELS.get(normalized, [])
    return [(m, "") for m in models]


def _provider_keys(provider: str) -> set[str]:
    key = (provider or "").strip().lower()
    normalized = normalize_provider(provider)
    return {k for k in (key, normalized) if k}


def _model_in_provider_catalog(name_lower: str, providers: set[str]) -> bool:
    return any(
        name_lower == model.lower()
        for provider in providers
        for model in _PROVIDER_MODELS.get(provider, [])
    )


_AGGREGATOR_PROVIDERS = frozenset(
    {"ector", "openrouter", "ai-gateway", "copilot", "kilocode"}
)


def _resolve_static_model_alias(
    name_lower: str,
    current_keys: set[str],
) -> Optional[tuple[str, str]]:
    """Resolve short aliases (e.g. sonnet/opus) using static catalogs only."""
    try:
        from ector_cli.model_switch import MODEL_ALIASES
    except Exception:
        return None

    identity = MODEL_ALIASES.get(name_lower)
    if identity is None:
        return None

    vendor = identity.vendor
    family = identity.family

    def _match(provider: str) -> Optional[str]:
        models = _PROVIDER_MODELS.get(provider, [])
        if not models:
            return None
        prefix = (
            f"{vendor}/{family}"
            if provider in _AGGREGATOR_PROVIDERS
            else family
        ).lower()
        for model in models:
            if model.lower().startswith(prefix):
                return model
        return None

    for provider in current_keys:
        if matched := _match(provider):
            return provider, matched

    for provider in _PROVIDER_MODELS:
        if provider in current_keys or provider in _AGGREGATOR_PROVIDERS:
            continue
        if matched := _match(provider):
            return provider, matched

    for provider in _AGGREGATOR_PROVIDERS:
        if provider in current_keys and (matched := _match(provider)):
            return provider, matched

    return None


def detect_static_provider_for_model(
    model_name: str,
    current_provider: str,
) -> Optional[tuple[str, str]]:
    """Auto-detect a provider from static catalogs only.

    Returns ``(provider_id, model_name)``. The model name may be remapped
    when a static alias or bare provider name resolves to a catalog default.
    Returns ``None`` when no confident match is found.
    """
    name = (model_name or "").strip()
    if not name:
        return None

    name_lower = name.lower()
    current_keys = _provider_keys(current_provider)

    alias_match = _resolve_static_model_alias(name_lower, current_keys)
    if alias_match:
        return alias_match

    # --- Step 0: bare provider name typed as model ---
    # If someone types `/provider ector` or `/provider anthropic`, treat it as a
    # provider switch and pick the first model from that provider's catalog.
    # Skip "custom" and "openrouter" — custom has no model catalog, and
    # openrouter requires an explicit model name to be useful.
    resolved_provider = _PROVIDER_ALIASES.get(name_lower, name_lower)
    if resolved_provider not in {"custom", "openrouter"}:
        default_models = _PROVIDER_MODELS.get(resolved_provider, [])
        if (
            resolved_provider in _PROVIDER_LABELS
            and default_models
            and resolved_provider not in current_keys
        ):
            return (resolved_provider, default_models[0])

    # Aggregators list other providers' models — never auto-switch TO them
    # If the model belongs to the current provider's catalog, don't suggest switching
    if _model_in_provider_catalog(name_lower, current_keys):
        return None

    # --- Step 1: check static provider catalogs for a direct match ---
    for pid, models in _PROVIDER_MODELS.items():
        if pid in current_keys or pid in _AGGREGATOR_PROVIDERS:
            continue
        if any(name_lower == m.lower() for m in models):
            return (pid, name)

    return None


def detect_provider_for_model(
    model_name: str,
    current_provider: str,
) -> Optional[tuple[str, str]]:
    """Auto-detect the best provider for a model name.

    Returns ``(provider_id, model_name)`` — the model name may be remapped
    (e.g. bare ``deepseek-chat`` → ``deepseek/deepseek-chat`` for OpenRouter).
    Returns ``None`` when no confident match is found.

    Priority:
    0. Bare provider name → switch to that provider's default model
    1. Direct provider static catalog match
    2. OpenRouter catalog match
    """
    name = (model_name or "").strip()
    if not name:
        return None

    static_match = detect_static_provider_for_model(name, current_provider)
    if static_match:
        return static_match
    if _model_in_provider_catalog(name.lower(), _provider_keys(current_provider)):
        return None

    # --- Step 2: check OpenRouter catalog ---
    # First try exact match (handles provider/model format)
    or_slug = _find_openrouter_slug(name)
    if or_slug:
        if current_provider != "openrouter":
            return ("openrouter", or_slug)
        # Already on openrouter, just return the resolved slug
        if or_slug != name:
            return ("openrouter", or_slug)
        return None  # already on openrouter with matching name

    return None


def _find_openrouter_slug(model_name: str) -> Optional[str]:
    """Find the full OpenRouter model slug for a bare or partial model name.

    Handles:
    - Exact match: ``anthropic/claude-opus-4.6`` → as-is
    - Bare name: ``deepseek-chat`` → ``deepseek/deepseek-chat``
    - Bare name: ``claude-opus-4.6`` → ``anthropic/claude-opus-4.6``
    """
    name_lower = model_name.strip().lower()
    if not name_lower:
        return None

    # Exact match (already has provider/ prefix)
    for mid in model_ids():
        if name_lower == mid.lower():
            return mid

    # Try matching just the model part (after the /)
    for mid in model_ids():
        if "/" in mid:
            _, model_part = mid.split("/", 1)
            if name_lower == model_part.lower():
                return mid

    return None


def normalize_provider(provider: Optional[str]) -> str:
    """Normalize provider aliases to Ector' canonical provider ids.

    Note: ``"auto"`` passes through unchanged — use
    ``ector_cli.auth.resolve_provider()`` to resolve it to a concrete
    provider based on credentials and environment.
    """
    normalized = (provider or "openrouter").strip().lower()
    return _PROVIDER_ALIASES.get(normalized, normalized)


def provider_label(provider: Optional[str]) -> str:
    """Return a human-friendly label for a provider id or alias."""
    original = (provider or "openrouter").strip()
    normalized = original.lower()
    if normalized == "auto":
        return "Auto"
    normalized = normalize_provider(normalized)
    return _PROVIDER_LABELS.get(normalized, original or "OpenRouter")


def infer_provider_id_from_base_url(url: str) -> Optional[str]:
    """Map an OpenAI-compatible base URL to a built-in provider id when possible."""
    from urllib.parse import urlparse

    raw = (url or "").strip()
    if not raw:
        return None
    try:
        host = urlparse(raw).netloc.lower()
    except Exception:
        host = ""
    if not host:
        return None

    try:
        from ector_cli.auth import PROVIDER_REGISTRY
    except Exception:
        PROVIDER_REGISTRY = {}

    for pid, pconfig in PROVIDER_REGISTRY.items():
        reg_url = (getattr(pconfig, "inference_base_url", None) or "").strip()
        if not reg_url:
            continue
        try:
            reg_host = urlparse(reg_url).netloc.lower()
        except Exception:
            reg_host = ""
        if reg_host and (host == reg_host or host.endswith("." + reg_host)):
            return pid

    host_hints = (
        ("deepseek", "deepseek"),
        ("generativelanguage.googleapis", "gemini"),
        ("api.openai.com", "openai"),
        ("openrouter.ai", "openrouter"),
        ("integrate.api.nvidia.com", "nvidia"),
        ("api.x.ai", "xai"),
        ("api.minimax", "minimax"),
        ("dashscope", "alibaba"),
        ("moonshot", "kimi-coding"),
    )
    for needle, pid in host_hints:
        if needle in host:
            return pid
    return None


def resolve_display_provider_id(config: Optional[dict] = None) -> Optional[str]:
    """Best-effort provider id for status lines and wizard menus.

    Honors explicit ``model.provider`` in config.yaml. When the provider is
    ``custom``, infers a built-in id from ``model.base_url``, matching
    ``custom_providers`` entries, or ``OPENAI_BASE_URL`` so DeepSeek (and
    similar) endpoints are not mislabeled as a generic custom endpoint.
    """
    from ector_cli.config import get_compatible_custom_providers, get_env_value, load_config

    if config is None:
        config = load_config()
    model_cfg = config.get("model")
    if not isinstance(model_cfg, dict):
        model_cfg = {}

    cfg_provider = (model_cfg.get("provider") or "").strip().lower()
    cfg_base = (model_cfg.get("base_url") or "").strip().rstrip("/")

    if cfg_provider and cfg_provider not in ("", "auto"):
        if cfg_provider == "custom":
            for entry in get_compatible_custom_providers(config):
                if not isinstance(entry, dict):
                    continue
                entry_url = (entry.get("base_url") or "").strip().rstrip("/")
                if cfg_base and entry_url and cfg_base == entry_url:
                    provider_key = (entry.get("provider_key") or "").strip().lower()
                    if provider_key:
                        return normalize_provider(provider_key)
            inferred = infer_provider_id_from_base_url(cfg_base)
            if not inferred:
                inferred = infer_provider_id_from_base_url(get_env_value("OPENAI_BASE_URL"))
            if inferred:
                return normalize_provider(inferred)
            return "custom"
        return normalize_provider(cfg_provider)

    env_provider = (os.getenv("ECTOR_INFERENCE_PROVIDER") or "").strip().lower()
    requested = env_provider or "auto"
    try:
        from ector_cli.auth import resolve_provider

        detected = resolve_provider(requested)
    except Exception:
        detected = None

    if detected == "openrouter" and get_env_value("OPENAI_BASE_URL"):
        inferred = infer_provider_id_from_base_url(get_env_value("OPENAI_BASE_URL"))
        if inferred:
            return normalize_provider(inferred)
        return "custom"
    return detected


# Models that support OpenAI Priority Processing (service_tier="priority").
# See https://openai.com/api-priority-processing/ for the canonical list.
# Only the bare model slug is stored (no vendor prefix).
_PRIORITY_PROCESSING_MODELS: frozenset[str] = frozenset({
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o",
    "gpt-4o-mini",
    "o3",
    "o4-mini",
})

# Models that support Anthropic Fast Mode (speed="fast").
# See https://platform.claude.com/docs/en/build-with-claude/fast-mode
# Currently only Claude Opus 4.6.  Both hyphen and dot variants are stored
# to handle native Anthropic (claude-opus-4-6) and OpenRouter (claude-opus-4.6).
_ANTHROPIC_FAST_MODE_MODELS: frozenset[str] = frozenset({
    "claude-opus-4-6",
    "claude-opus-4.6",
})


def _strip_vendor_prefix(model_id: str) -> str:
    """Strip vendor/ prefix from a model ID (e.g. 'anthropic/claude-opus-4-6' -> 'claude-opus-4-6')."""
    raw = str(model_id or "").strip().lower()
    if "/" in raw:
        raw = raw.split("/", 1)[1]
    return raw


def model_supports_fast_mode(model_id: Optional[str]) -> bool:
    """Return whether Ector should expose the /fast toggle for this model."""
    raw = _strip_vendor_prefix(str(model_id or ""))
    if raw in _PRIORITY_PROCESSING_MODELS:
        return True
    # Anthropic fast mode — strip date suffixes (e.g. claude-opus-4-6-20260401)
    # and OpenRouter variant tags (:fast, :beta) for matching.
    base = raw.split(":")[0]
    return base in _ANTHROPIC_FAST_MODE_MODELS


def _is_anthropic_fast_model(model_id: Optional[str]) -> bool:
    """Return True if the model supports Anthropic's fast mode (speed='fast')."""
    raw = _strip_vendor_prefix(str(model_id or ""))
    base = raw.split(":")[0]
    return base in _ANTHROPIC_FAST_MODE_MODELS


def resolve_fast_mode_overrides(model_id: Optional[str]) -> dict[str, Any] | None:
    """Return request_overrides for fast/priority mode, or None if unsupported.

    Returns provider-appropriate overrides:
    - OpenAI models: ``{"service_tier": "priority"}`` (Priority Processing)
    - Anthropic models: ``{"speed": "fast"}`` (Anthropic Fast Mode beta)

    The overrides are injected into the API request kwargs by
    ``_build_api_kwargs`` in run_agent.py — each API path handles its own
    keys (service_tier for OpenAI/Codex, speed for Anthropic Messages).
    """
    if not model_supports_fast_mode(model_id):
        return None
    if _is_anthropic_fast_model(model_id):
        return {"speed": "fast"}
    return {"service_tier": "priority"}


def _resolve_copilot_catalog_api_key() -> str:
    """Best-effort GitHub token for fetching the Copilot model catalog."""
    try:
        from ector_cli.auth import resolve_api_key_provider_credentials

        creds = resolve_api_key_provider_credentials("copilot")
        return str(creds.get("api_key") or "").strip()
    except Exception:
        return ""


# Providers where models.dev is treated as authoritative: curated static
# lists are kept only as an offline fallback and to capture custom additions
# the registry doesn't publish yet. Adding a provider here causes its
# curated list to be merged with fresh models.dev entries (fresh first, any
# curated-only names appended) for both the CLI and the gateway /provider picker.
#
# DELIBERATELY EXCLUDED:
#   - "openrouter": curated list is already a hand-picked agentic subset of
#     OpenRouter's 400+ catalog. Blindly merging would dump everything.
#   - "ector": curated list and Portal /models endpoint are the source of
#     truth for the subscription tier.
# Also excluded: providers that already have dedicated live-endpoint
# branches below (copilot, anthropic, ai-gateway, ollama-cloud, custom,
# stepfun, openai-codex) — those paths handle freshness themselves.
_MODELS_DEV_PREFERRED: frozenset[str] = frozenset({
    "deepseek",
    "kilocode",
    "fireworks",
    "mistral",
    "togetherai",
    "cohere",
    "perplexity",
    "groq",
    "nvidia",
    "huggingface",
    "zai",
    "gemini",
    "google",
})


def _merge_with_models_dev(provider: str, curated: list[str]) -> list[str]:
    """Merge curated list with fresh models.dev entries for a preferred provider.

    Returns models.dev entries first (in models.dev order), then any
    curated-only entries appended. Preserves case for curated fallbacks
    (e.g. ``MiniMax-M2.7``) while trusting models.dev for newer variants.

    If models.dev is unreachable or returns nothing, the curated list is
    returned unchanged — this is the offline/CI fallback path.
    """
    try:
        from agent.models_dev import list_agentic_models
        mdev = list_agentic_models(provider)
    except Exception:
        mdev = []

    if not mdev:
        return list(curated)

    # Case-insensitive dedup while preserving order and curated casing.
    seen_lower: set[str] = set()
    merged: list[str] = []
    for mid in mdev:
        key = str(mid).lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        merged.append(mid)
    for mid in curated:
        key = str(mid).lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        merged.append(mid)
    return merged


def provider_model_ids(provider: Optional[str], *, force_refresh: bool = False) -> list[str]:
    """Return the best known model catalog for a provider.

    Tries live API endpoints for providers that support them (Codex, Ector),
    falling back to static lists. For providers in ``_MODELS_DEV_PREFERRED``
    (xiaomi, deepseek, smaller inference providers, etc.),
    models.dev entries are merged on top of curated so new models released
    on the platform appear in ``/provider`` without a Ector release.
    """
    normalized = normalize_provider(provider)
    if normalized == "openrouter":
        return model_ids(force_refresh=force_refresh)
    if normalized == "openai-codex":
        from ector_cli.codex_models import get_codex_model_ids

        # Pass the live OAuth access token so the picker matches whatever
        # ChatGPT lists for this account right now (new models appear without
        # a Ector release). Falls back to the hardcoded catalog if no token
        # or the endpoint is unreachable.
        access_token = None
        try:
            from ector_cli.auth import resolve_codex_runtime_credentials

            creds = resolve_codex_runtime_credentials(refresh_if_expiring=True)
            access_token = creds.get("api_key")
        except Exception:
            access_token = None
        return get_codex_model_ids(access_token=access_token)
    if normalized in {"copilot", "copilot-acp"}:
        try:
            live = _fetch_github_models(_resolve_copilot_catalog_api_key())
            if live:
                return live
        except Exception:
            pass
        if normalized == "copilot-acp":
            return list(_PROVIDER_MODELS.get("copilot", []))
    # Legacy Portal OAuth provider removed.
    if normalized == "stepfun":
        try:
            from ector_cli.auth import resolve_api_key_provider_credentials

            creds = resolve_api_key_provider_credentials("stepfun")
            api_key = str(creds.get("api_key") or "").strip()
            base_url = str(creds.get("base_url") or "").strip()
            if api_key and base_url:
                live = fetch_api_models(api_key, base_url)
                if live:
                    return live
        except Exception:
            pass
    if normalized == "anthropic":
        live = _fetch_anthropic_models()
        if live:
            return live
    if normalized == "ai-gateway":
        live = _fetch_ai_gateway_models()
        if live:
            return live
    if normalized == "ollama-cloud":
        live = fetch_ollama_cloud_models(force_refresh=force_refresh)
        if live:
            return live
    if normalized == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if api_key:
            base_raw = os.getenv("OPENAI_BASE_URL", "").strip().rstrip("/")
            base = base_raw or "https://api.openai.com/v1"
            try:
                live = fetch_api_models(api_key, base)
                if live:
                    return live
            except Exception:
                pass
    if normalized == "custom":
        base_url = _get_custom_base_url()
        if base_url:
            # Try common API key env vars for custom endpoints
            api_key = (
                os.getenv("CUSTOM_API_KEY", "")
                or os.getenv("OPENAI_API_KEY", "")
                or os.getenv("OPENROUTER_API_KEY", "")
            )
            live = fetch_api_models(api_key, base_url)
            if live:
                return live
    curated_static = list(_PROVIDER_MODELS.get(normalized, []))
    if normalized in _MODELS_DEV_PREFERRED:
        return _merge_with_models_dev(normalized, curated_static)
    return curated_static


def _fetch_anthropic_models(timeout: float = 5.0) -> Optional[list[str]]:
    """Fetch available models from the Anthropic /v1/models endpoint.

    Uses resolve_anthropic_token() to find credentials (env vars or
    Claude Code auto-discovery).  Returns sorted model IDs or None.
    """
    try:
        from agent.anthropic_adapter import resolve_anthropic_token, _is_oauth_token
    except ImportError:
        return None

    token = resolve_anthropic_token()
    if not token:
        return None

    headers: dict[str, str] = {"anthropic-version": "2023-06-01"}
    if _is_oauth_token(token):
        headers["Authorization"] = f"Bearer {token}"
        from agent.anthropic_adapter import _COMMON_BETAS, _OAUTH_ONLY_BETAS
        headers["anthropic-beta"] = ",".join(_COMMON_BETAS + _OAUTH_ONLY_BETAS)
    else:
        headers["x-api-key"] = token

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            models = [m["id"] for m in data.get("data", []) if m.get("id")]
            # Sort: latest/largest first (opus > sonnet > haiku, higher version first)
            return sorted(models, key=lambda m: (
                "opus" not in m,      # opus first
                "sonnet" not in m,    # then sonnet
                "haiku" not in m,     # then haiku
                m,                    # alphabetical within tier
            ))
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("Failed to fetch Anthropic models: %s", e)
        return None


def _payload_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data", [])
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def copilot_default_headers() -> dict[str, str]:
    """Standard headers for Copilot API requests.

    Includes Openai-Intent and x-initiator headers that Copilot clients
    send on every request.
    """
    try:
        from ector_cli.copilot_auth import copilot_request_headers
        return copilot_request_headers(is_agent_turn=True)
    except ImportError:
        return {
            "Editor-Version": COPILOT_EDITOR_VERSION,
            "User-Agent": "EctorAgent/1.0",
            "Openai-Intent": "conversation-edits",
            "x-initiator": "agent",
        }


def _copilot_catalog_item_is_text_model(item: dict[str, Any]) -> bool:
    model_id = str(item.get("id") or "").strip()
    if not model_id:
        return False

    if item.get("model_picker_enabled") is False:
        return False

    capabilities = item.get("capabilities")
    if isinstance(capabilities, dict):
        model_type = str(capabilities.get("type") or "").strip().lower()
        if model_type and model_type != "chat":
            return False

    supported_endpoints = item.get("supported_endpoints")
    if isinstance(supported_endpoints, list):
        normalized_endpoints = {
            str(endpoint).strip()
            for endpoint in supported_endpoints
            if str(endpoint).strip()
        }
        if normalized_endpoints and not normalized_endpoints.intersection(
            {"/chat/completions", "/responses", "/v1/messages"}
        ):
            return False

    return True


def fetch_github_model_catalog(
    api_key: Optional[str] = None, timeout: float = 5.0
) -> Optional[list[dict[str, Any]]]:
    """Fetch the live GitHub Copilot model catalog for this account."""
    attempts: list[dict[str, str]] = []
    if api_key:
        attempts.append({
            **copilot_default_headers(),
            "Authorization": f"Bearer {api_key}",
        })
    attempts.append(copilot_default_headers())

    for headers in attempts:
        req = urllib.request.Request(COPILOT_MODELS_URL, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                items = _payload_items(data)
                models: list[dict[str, Any]] = []
                seen_ids: set[str] = set()
                for item in items:
                    if not _copilot_catalog_item_is_text_model(item):
                        continue
                    model_id = str(item.get("id") or "").strip()
                    if not model_id or model_id in seen_ids:
                        continue
                    seen_ids.add(model_id)
                    models.append(item)
                if models:
                    return models
        except Exception:
            continue
    return None


# ─── Copilot catalog context-window helpers ─────────────────────────────────

# Module-level cache: {model_id: max_prompt_tokens}
_copilot_context_cache: dict[str, int] = {}
_copilot_context_cache_time: float = 0.0
_COPILOT_CONTEXT_CACHE_TTL = 3600  # 1 hour


def get_copilot_model_context(model_id: str, api_key: Optional[str] = None) -> Optional[int]:
    """Look up max_prompt_tokens for a Copilot model from the live /models API.

    Results are cached in-process for 1 hour to avoid repeated API calls.
    Returns the token limit or None if not found.
    """
    global _copilot_context_cache, _copilot_context_cache_time

    # Serve from cache if fresh
    if _copilot_context_cache and (time.time() - _copilot_context_cache_time < _COPILOT_CONTEXT_CACHE_TTL):
        if model_id in _copilot_context_cache:
            return _copilot_context_cache[model_id]
        # Cache is fresh but model not in it — don't re-fetch
        return None

    # Fetch and populate cache
    catalog = fetch_github_model_catalog(api_key=api_key)
    if not catalog:
        return None

    cache: dict[str, int] = {}
    for item in catalog:
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        caps = item.get("capabilities") or {}
        limits = caps.get("limits") or {}
        max_prompt = limits.get("max_prompt_tokens")
        if isinstance(max_prompt, int) and max_prompt > 0:
            cache[mid] = max_prompt

    _copilot_context_cache = cache
    _copilot_context_cache_time = time.time()

    return cache.get(model_id)


def _is_github_models_base_url(base_url: Optional[str]) -> bool:
    normalized = (base_url or "").strip().rstrip("/").lower()
    return (
        normalized.startswith(COPILOT_BASE_URL)
        or normalized.startswith("https://models.github.ai/inference")
    )


def _fetch_github_models(api_key: Optional[str] = None, timeout: float = 5.0) -> Optional[list[str]]:
    catalog = fetch_github_model_catalog(api_key=api_key, timeout=timeout)
    if not catalog:
        return None
    return [item.get("id", "") for item in catalog if item.get("id")]


_COPILOT_MODEL_ALIASES = {
    "openai/gpt-5": "gpt-5-mini",
    "openai/gpt-5-chat": "gpt-5-mini",
    "openai/gpt-5-mini": "gpt-5-mini",
    "openai/gpt-5-nano": "gpt-5-mini",
    "openai/gpt-4.1": "gpt-4.1",
    "openai/gpt-4.1-mini": "gpt-4.1",
    "openai/gpt-4.1-nano": "gpt-4.1",
    "openai/gpt-4o": "gpt-4o",
    "openai/gpt-4o-mini": "gpt-4o-mini",
    "openai/o1": "gpt-5.2",
    "openai/o1-mini": "gpt-5-mini",
    "openai/o1-preview": "gpt-5.2",
    "openai/o3": "gpt-5.3-codex",
    "openai/o3-mini": "gpt-5-mini",
    "openai/o4-mini": "gpt-5-mini",
    "anthropic/claude-opus-4.6": "claude-opus-4.6",
    "anthropic/claude-sonnet-4.6": "claude-sonnet-4.6",
    "anthropic/claude-sonnet-4": "claude-sonnet-4",
    "anthropic/claude-sonnet-4.5": "claude-sonnet-4.5",
    "anthropic/claude-haiku-4.5": "claude-haiku-4.5",
    # Dash-notation fallbacks: Ector' default Claude IDs elsewhere use
    # hyphens (anthropic native format), but Copilot's API only accepts
    # dot-notation.  Accept both so users who configure copilot + a
    # default hyphenated Claude model don't hit HTTP 400
    # "model_not_supported".  See issue #6879.
    "claude-opus-4-6": "claude-opus-4.6",
    "claude-sonnet-4-6": "claude-sonnet-4.6",
    "claude-sonnet-4-0": "claude-sonnet-4",
    "claude-sonnet-4-5": "claude-sonnet-4.5",
    "claude-haiku-4-5": "claude-haiku-4.5",
    "anthropic/claude-opus-4-6": "claude-opus-4.6",
    "anthropic/claude-sonnet-4-6": "claude-sonnet-4.6",
    "anthropic/claude-sonnet-4-0": "claude-sonnet-4",
    "anthropic/claude-sonnet-4-5": "claude-sonnet-4.5",
    "anthropic/claude-haiku-4-5": "claude-haiku-4.5",
}


def _copilot_catalog_ids(
    catalog: Optional[list[dict[str, Any]]] = None,
    api_key: Optional[str] = None,
) -> set[str]:
    if catalog is None and api_key:
        catalog = fetch_github_model_catalog(api_key=api_key)
    if not catalog:
        return set()
    return {
        str(item.get("id") or "").strip()
        for item in catalog
        if str(item.get("id") or "").strip()
    }


def normalize_copilot_model_id(
    model_id: Optional[str],
    *,
    catalog: Optional[list[dict[str, Any]]] = None,
    api_key: Optional[str] = None,
) -> str:
    raw = str(model_id or "").strip()
    if not raw:
        return ""

    catalog_ids = _copilot_catalog_ids(catalog=catalog, api_key=api_key)
    alias = _COPILOT_MODEL_ALIASES.get(raw)
    if alias:
        return alias

    candidates = [raw]
    if "/" in raw:
        candidates.append(raw.split("/", 1)[1].strip())

    if raw.endswith("-mini"):
        candidates.append(raw[:-5])
    if raw.endswith("-nano"):
        candidates.append(raw[:-5])
    if raw.endswith("-chat"):
        candidates.append(raw[:-5])

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if candidate in _COPILOT_MODEL_ALIASES:
            return _COPILOT_MODEL_ALIASES[candidate]
        if candidate in catalog_ids:
            return candidate

    if "/" in raw:
        return raw.split("/", 1)[1].strip()
    return raw


def _github_reasoning_efforts_for_model_id(model_id: str) -> list[str]:
    raw = (model_id or "").strip().lower()
    if raw.startswith(("openai/o1", "openai/o3", "openai/o4", "o1", "o3", "o4")):
        return list(COPILOT_REASONING_EFFORTS_O_SERIES)
    normalized = normalize_copilot_model_id(model_id).lower()
    if normalized.startswith("gpt-5"):
        return list(COPILOT_REASONING_EFFORTS_GPT5)
    return []


def _should_use_copilot_responses_api(model_id: str) -> bool:
    """Decide whether a Copilot model should use the Responses API.

    GPT-5+ models use Responses API, except ``gpt-5-mini`` which uses
    Chat Completions. All non-GPT models (Claude, Gemini, etc.) use
    Chat Completions.
    """
    import re

    match = re.match(r"^gpt-(\d+)", model_id)
    if not match:
        return False
    major = int(match.group(1))
    return major >= 5 and not model_id.startswith("gpt-5-mini")


def copilot_model_api_mode(
    model_id: Optional[str],
    *,
    catalog: Optional[list[dict[str, Any]]] = None,
    api_key: Optional[str] = None,
) -> str:
    """Determine the API mode for a Copilot model.

    Uses the model ID pattern as the
    primary signal.  Falls back to the catalog's ``supported_endpoints``
    only for models not covered by the pattern check.
    """
    # Fetch the catalog once so normalize + endpoint check share it
    # (avoids two redundant network calls for non-GPT-5 models).
    if catalog is None and api_key:
        catalog = fetch_github_model_catalog(api_key=api_key)

    normalized = normalize_copilot_model_id(model_id, catalog=catalog, api_key=api_key)
    if not normalized:
        return "chat_completions"

    # Primary: model ID pattern
    if _should_use_copilot_responses_api(normalized):
        return "codex_responses"

    # Secondary: check catalog for non-GPT-5 models (Claude via /v1/messages, etc.)
    if catalog:
        catalog_entry = next((item for item in catalog if item.get("id") == normalized), None)
        if isinstance(catalog_entry, dict):
            supported_endpoints = {
                str(endpoint).strip()
                for endpoint in (catalog_entry.get("supported_endpoints") or [])
                if str(endpoint).strip()
            }
            # For non-GPT-5 models, check if they only support messages API
            if "/v1/messages" in supported_endpoints and "/chat/completions" not in supported_endpoints:
                return "anthropic_messages"

    return "chat_completions"


# Azure Foundry model families that require the Responses API.  Azure
# rejects /chat/completions against these deployments with
# ``400 "The requested operation is unsupported."`` — the same payload Bob
# Dobolina hit in April 2026 on ``gpt-5.3-codex`` while ``gpt-4o-pure`` on
# the same endpoint worked fine.  Keep the patterns broad enough to cover
# vendor-renamed deployments (e.g. ``gpt-5.3-codex``, ``gpt-5-codex``,
# ``gpt-5.4``, ``o1-preview``) but tight enough to leave GPT-4 / 3.5 / Llama /
# Mistral / Grok deployments on chat completions.
_AZURE_FOUNDRY_RESPONSES_PREFIXES = (
    "codex",       # codex-*, codex-mini
    "gpt-5",       # gpt-5, gpt-5.x, gpt-5-codex, gpt-5.x-codex
    "o1",          # o1, o1-preview, o1-mini
    "o3",          # o3, o3-mini
    "o4",          # o4, o4-mini
)


def azure_foundry_model_api_mode(model_name: Optional[str]) -> Optional[str]:
    """Infer Azure Foundry api_mode from a deployment/model name.

    Returns ``"codex_responses"`` when the model name matches a family that
    only accepts the Responses API on Azure Foundry (GPT-5.x, codex, o1/o3/o4
    reasoning models).  Returns ``None`` otherwise — the caller should fall
    back to the configured/default api_mode (typically ``chat_completions``)
    so GPT-4o, GPT-4 Turbo, Llama, Mistral, etc. keep working.

    Intentionally does NOT return ``anthropic_messages``; Anthropic-style
    Azure endpoints are disambiguated by URL (``/anthropic`` suffix) in
    ``runtime_provider._detect_api_mode_for_url`` and by the user setting
    ``model.api_mode: anthropic_messages`` explicitly.
    """
    raw = str(model_name or "").strip().lower()
    if not raw:
        return None
    # Strip any vendor/ prefix a user may have copied from OpenRouter / Copilot.
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    # gpt-5-mini speaks chat completions on Copilot but Azure Foundry deploys
    # the full gpt-5 family uniformly on Responses API — don't carve an
    # exception here.
    for prefix in _AZURE_FOUNDRY_RESPONSES_PREFIXES:
        if raw.startswith(prefix):
            return "codex_responses"
    return None


def github_model_reasoning_efforts(
    model_id: Optional[str],
    *,
    catalog: Optional[list[dict[str, Any]]] = None,
    api_key: Optional[str] = None,
) -> list[str]:
    """Return supported reasoning-effort levels for a Copilot-visible model."""
    normalized = normalize_copilot_model_id(model_id, catalog=catalog, api_key=api_key)
    if not normalized:
        return []

    catalog_entry = None
    if catalog is not None:
        catalog_entry = next((item for item in catalog if item.get("id") == normalized), None)
    elif api_key:
        fetched_catalog = fetch_github_model_catalog(api_key=api_key)
        if fetched_catalog:
            catalog_entry = next((item for item in fetched_catalog if item.get("id") == normalized), None)

    if catalog_entry is not None:
        capabilities = catalog_entry.get("capabilities")
        if isinstance(capabilities, dict):
            supports = capabilities.get("supports")
            if isinstance(supports, dict):
                efforts = supports.get("reasoning_effort")
                if isinstance(efforts, list):
                    normalized_efforts = [
                        str(effort).strip().lower()
                        for effort in efforts
                        if str(effort).strip()
                    ]
                    return list(dict.fromkeys(normalized_efforts))
            return []
        legacy_capabilities = {
            str(capability).strip().lower()
            for capability in catalog_entry.get("capabilities", [])
            if str(capability).strip()
        }
        if "reasoning" not in legacy_capabilities:
            return []

    return _github_reasoning_efforts_for_model_id(str(model_id or normalized))


def probe_api_models(
    api_key: Optional[str],
    base_url: Optional[str],
    timeout: float = 5.0,
    api_mode: Optional[str] = None,
) -> dict[str, Any]:
    """Probe a ``/models`` endpoint with light URL heuristics.

    For ``anthropic_messages`` mode, uses ``x-api-key`` and
    ``anthropic-version`` headers (Anthropic's native auth) instead of
    ``Authorization: Bearer``.  The response shape (``data[].id``) is
    identical, so the same parser works for both.
    """
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        return {
            "models": None,
            "probed_url": None,
            "resolved_base_url": "",
            "suggested_base_url": None,
            "used_fallback": False,
        }

    if _is_github_models_base_url(normalized):
        models = _fetch_github_models(api_key=api_key, timeout=timeout)
        return {
            "models": models,
            "probed_url": COPILOT_MODELS_URL,
            "resolved_base_url": COPILOT_BASE_URL,
            "suggested_base_url": None,
            "used_fallback": False,
        }

    if normalized.endswith("/v1"):
        alternate_base = normalized[:-3].rstrip("/")
    else:
        alternate_base = normalized + "/v1"

    candidates: list[tuple[str, bool]] = [(normalized, False)]
    if alternate_base and alternate_base != normalized:
        candidates.append((alternate_base, True))

    tried: list[str] = []
    headers: dict[str, str] = {"User-Agent": _ECTOR_USER_AGENT}
    if api_key and api_mode == "anthropic_messages":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if normalized.startswith(COPILOT_BASE_URL):
        headers.update(copilot_default_headers())

    for candidate_base, is_fallback in candidates:
        url = candidate_base.rstrip("/") + "/models"
        tried.append(url)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                return {
                    "models": [m.get("id", "") for m in data.get("data", [])],
                    "probed_url": url,
                    "resolved_base_url": candidate_base.rstrip("/"),
                    "suggested_base_url": alternate_base if alternate_base != candidate_base else normalized,
                    "used_fallback": is_fallback,
                }
        except Exception:
            continue

    return {
        "models": None,
        "probed_url": tried[0] if tried else normalized.rstrip("/") + "/models",
        "resolved_base_url": normalized,
        "suggested_base_url": alternate_base if alternate_base != normalized else None,
        "used_fallback": False,
    }


def _fetch_ai_gateway_models(timeout: float = 5.0) -> Optional[list[str]]:
    """Fetch available language models with tool-use from AI Gateway."""
    api_key = os.getenv("AI_GATEWAY_API_KEY", "").strip()
    if not api_key:
        return None
    base_url = os.getenv("AI_GATEWAY_BASE_URL", "").strip()
    if not base_url:
        from ector_constants import AI_GATEWAY_BASE_URL
        base_url = AI_GATEWAY_BASE_URL

    url = base_url.rstrip("/") + "/models"
    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": _ECTOR_USER_AGENT,
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            return [
                m["id"]
                for m in data.get("data", [])
                if m.get("id")
                and m.get("type") == "language"
                and "tool-use" in (m.get("tags") or [])
            ]
    except Exception:
        return None


def fetch_api_models(
    api_key: Optional[str],
    base_url: Optional[str],
    timeout: float = 5.0,
    api_mode: Optional[str] = None,
) -> Optional[list[str]]:
    """Fetch the list of available model IDs from the provider's ``/models`` endpoint.

    Returns a list of model ID strings, or ``None`` if the endpoint could not
    be reached (network error, timeout, auth failure, etc.).
    """
    return probe_api_models(api_key, base_url, timeout=timeout, api_mode=api_mode).get("models")


# ---------------------------------------------------------------------------
# Ollama Cloud — merged model discovery with disk cache
# ---------------------------------------------------------------------------



_OLLAMA_CLOUD_CACHE_TTL = 3600  # 1 hour


def _ollama_cloud_cache_path() -> Path:
    """Return the path for the Ollama Cloud model cache."""
    from ector_constants import get_ector_home
    return get_ector_home() / "ollama_cloud_models_cache.json"


def _load_ollama_cloud_cache(*, ignore_ttl: bool = False) -> Optional[dict]:
    """Load cached Ollama Cloud models from disk.

    Args:
        ignore_ttl: If True, return data even if the TTL has expired (stale fallback).
    """
    try:
        cache_path = _ollama_cloud_cache_path()
        if not cache_path.exists():
            return None
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        models = data.get("models")
        if not (isinstance(models, list) and models):
            return None
        if not ignore_ttl:
            cached_at = data.get("cached_at", 0)
            if (time.time() - cached_at) > _OLLAMA_CLOUD_CACHE_TTL:
                return None  # stale
        return data
    except Exception:
        pass
    return None


def _save_ollama_cloud_cache(models: list[str]) -> None:
    """Persist the merged Ollama Cloud model list to disk."""
    try:
        from utils import atomic_json_write
        cache_path = _ollama_cloud_cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(cache_path, {"models": models, "cached_at": time.time()}, indent=None)
    except Exception:
        pass


def fetch_ollama_cloud_models(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    *,
    force_refresh: bool = False,
) -> list[str]:
    """Fetch Ollama Cloud models by merging live API + models.dev, with disk cache.

    Resolution order:
      1. Disk cache (if fresh, < 1 hour, and not force_refresh)
      2. Live ``/v1/models`` endpoint (primary — freshest source)
      3. models.dev registry (secondary — fills gaps for unlisted models)
      4. Merge: live models first, then models.dev additions (deduped)

    Returns a list of model IDs (never None — empty list on total failure).
    """
    # 1. Check disk cache
    if not force_refresh:
        cached = _load_ollama_cloud_cache()
        if cached is not None:
            return cached["models"]

    # 2. Live API probe
    if not api_key:
        api_key = os.getenv("OLLAMA_API_KEY", "")
    if not base_url:
        base_url = os.getenv("OLLAMA_BASE_URL", "") or "https://ollama.com/v1"

    live_models: list[str] = []
    if api_key:
        result = fetch_api_models(api_key, base_url, timeout=8.0)
        if result:
            live_models = result

    # 3. models.dev registry
    mdev_models: list[str] = []
    try:
        from agent.models_dev import list_agentic_models
        mdev_models = list_agentic_models("ollama-cloud")
    except Exception:
        pass

    # 4. Merge: live first, then models.dev additions (deduped, order-preserving)
    if live_models or mdev_models:
        seen: set[str] = set()
        merged: list[str] = []
        for m in live_models:
            if m and m not in seen:
                seen.add(m)
                merged.append(m)
        for m in mdev_models:
            if m and m not in seen:
                seen.add(m)
                merged.append(m)
        if merged:
            _save_ollama_cloud_cache(merged)
            return merged

    # Total failure — return stale cache if available (ignore TTL)
    stale = _load_ollama_cloud_cache(ignore_ttl=True)
    if stale is not None:
        return stale["models"]

    return []


def validate_requested_model(
    model_name: str,
    provider: Optional[str],
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    api_mode: Optional[str] = None,
) -> dict[str, Any]:
    """
    Validate a ``/provider`` value for the active provider.

    Performs format checks first, then probes the live API to confirm
    the model actually exists.

    Returns a dict with:
      - accepted: whether the CLI should switch to the requested model now
      - persist: whether it is safe to save to config
      - recognized: whether it matched a known provider catalog
      - message: optional warning / guidance for the user
    """
    requested = (model_name or "").strip()
    normalized = normalize_provider(provider)
    if normalized == "openrouter" and base_url and "openrouter.ai" not in base_url:
        normalized = "custom"
    requested_for_lookup = requested
    if normalized == "copilot":
        requested_for_lookup = normalize_copilot_model_id(
            requested,
            api_key=api_key,
        ) or requested

    if not requested:
        return {
            "accepted": False,
            "persist": False,
            "recognized": False,
            "message": "O nome do modelo não pode estar vazio.",
        }

    if any(ch.isspace() for ch in requested):
        return {
            "accepted": False,
            "persist": False,
            "recognized": False,
            "message": "Nomes de modelos não podem conter espaços.",
        }

    if normalized == "custom":
        # Try probing with correct auth for the api_mode.
        if api_mode == "anthropic_messages":
            probe = probe_api_models(api_key, base_url, api_mode=api_mode)
        else:
            probe = probe_api_models(api_key, base_url)
        api_models = probe.get("models")
        if api_models is not None:
            if requested_for_lookup in set(api_models):
                return {
                    "accepted": True,
                    "persist": True,
                    "recognized": True,
                    "message": None,
                }

            # Auto-correct if the top match is very similar (e.g. typo)
            auto = get_close_matches(requested_for_lookup, api_models, n=1, cutoff=0.9)
            if auto:
                return {
                    "accepted": True,
                    "persist": True,
                    "recognized": True,
                    "corrected_model": auto[0],
                    "message": f"Auto-corrigido `{requested}` → `{auto[0]}`",
                }

            suggestions = get_close_matches(requested, api_models, n=3, cutoff=0.5)
            suggestion_text = ""
            if suggestions:
                suggestion_text = "\n  Modelos semelhantes: " + ", ".join(f"`{s}`" for s in suggestions)

            message = (
                f"Nota: `{requested}` não foi encontrado na listagem de modelos deste endpoint customizado "
                f"({probe.get('probed_url')}). Pode ainda funcionar se o servidor suportar modelos ocultos ou apelidados."
                f"{suggestion_text}"
            )
            if probe.get("used_fallback"):
                message += (
                    f"\n  A verificação do endpoint teve sucesso após tentar `{probe.get('resolved_base_url')}`. "
                    f"Considere salvar isso como sua URL base."
                )

            return {
                "accepted": True,
                "persist": True,
                "recognized": False,
                "message": message,
            }

        message = (
            f"Nota: não foi possível alcançar a listagem de modelos deste endpoint customizado em `{probe.get('probed_url')}`. "
            f"O Ector ainda salvará `{requested}`, mas o endpoint deve expor `/models` para verificação."
        )
        if api_mode == "anthropic_messages":
            message += (
                "\n  Muitos proxies compatíveis com Anthropic não implementam a API de Modelos "
                "(GET /v1/models). O nome do modelo foi aceito sem verificação."
            )
        if probe.get("suggested_base_url"):
            message += f"\n  Se este servidor espera `/v1`, tente a URL base: `{probe.get('suggested_base_url')}`"

        return {
            "accepted": api_mode == "anthropic_messages",
            "persist": True,
            "recognized": False,
            "message": message,
        }

    # OpenAI Codex has its own catalog path; /v1/models probing is not the right validation path.
    if normalized == "openai-codex":
        try:
            codex_models = provider_model_ids("openai-codex")
        except Exception:
            codex_models = []
        if codex_models:
            if requested_for_lookup in set(codex_models):
                return {
                    "accepted": True,
                    "persist": True,
                    "recognized": True,
                    "message": None,
                }
            # Auto-correct if the top match is very similar (e.g. typo)
            auto = get_close_matches(requested_for_lookup, codex_models, n=1, cutoff=0.9)
            if auto:
                return {
                    "accepted": True,
                    "persist": True,
                    "recognized": True,
                    "corrected_model": auto[0],
                    "message": f"Auto-corrigido `{requested}` → `{auto[0]}`",
                }
            suggestions = get_close_matches(requested_for_lookup, codex_models, n=3, cutoff=0.5)
            suggestion_text = ""
            if suggestions:
                suggestion_text = "\n  Modelos semelhantes: " + ", ".join(f"`{s}`" for s in suggestions)
            return {
                "accepted": False,
                "persist": False,
                "recognized": False,
                "message": (
                    f"O modelo `{requested}` não foi encontrado na listagem de modelos do OpenAI Codex."
                    f"{suggestion_text}"
                ),
            }

    # MiniMax providers don't expose a /models endpoint — validate against
    # the static catalog instead, similar to openai-codex.
    if normalized in ("minimax", "minimax-cn"):
        try:
            catalog_models = provider_model_ids(normalized)
        except Exception:
            catalog_models = []
        if catalog_models:
            # Case-insensitive lookup (catalog uses mixed case like MiniMax-M2.7)
            catalog_lower = {m.lower(): m for m in catalog_models}
            if requested_for_lookup.lower() in catalog_lower:
                return {
                    "accepted": True,
                    "persist": True,
                    "recognized": True,
                    "message": None,
                }
            # Auto-correct close matches (case-insensitive)
            catalog_lower_list = list(catalog_lower.keys())
            auto = get_close_matches(requested_for_lookup.lower(), catalog_lower_list, n=1, cutoff=0.9)
            if auto:
                corrected = catalog_lower[auto[0]]
                return {
                    "accepted": True,
                    "persist": True,
                    "recognized": True,
                    "corrected_model": corrected,
                    "message": f"Auto-corrigido `{requested}` → `{corrected}`",
                }
            suggestions = get_close_matches(requested_for_lookup.lower(), catalog_lower_list, n=3, cutoff=0.5)
            suggestion_text = ""
            if suggestions:
                suggestion_text = "\n  Modelos semelhantes: " + ", ".join(f"`{catalog_lower[s]}`" for s in suggestions)
            return {
                "accepted": True,
                "persist": True,
                "recognized": False,
                "message": (
                    f"Nota: `{requested}` não foi encontrado no catálogo do MiniMax."
                    f"{suggestion_text}"
                    "\n  O MiniMax não expõe um endpoint /models, então o Ector não pode verificar o nome do modelo."
                    "\n  O modelo ainda pode funcionar se existir no servidor."
                ),
            }

    # Native Anthropic provider: /v1/models requires x-api-key (or Bearer for
    # OAuth) plus anthropic-version headers.  The generic OpenAI-style probe
    # below uses plain Bearer auth and 401s against Anthropic, so dispatch to
    # the native fetcher which handles both API keys and Claude-Code OAuth
    # tokens.  (The api_mode=="anthropic_messages" branch below handles the
    # Messages-API transport case separately.)
    if normalized == "anthropic":
        anthropic_models = _fetch_anthropic_models()
        if anthropic_models is not None:
            if requested_for_lookup in set(anthropic_models):
                return {
                    "accepted": True,
                    "persist": True,
                    "recognized": True,
                    "message": None,
                }
            auto = get_close_matches(requested_for_lookup, anthropic_models, n=1, cutoff=0.9)
            if auto:
                return {
                    "accepted": True,
                    "persist": True,
                    "recognized": True,
                    "corrected_model": auto[0],
                    "message": f"Auto-corrigido `{requested}` → `{auto[0]}`",
                }
            suggestions = get_close_matches(requested, anthropic_models, n=3, cutoff=0.5)
            suggestion_text = ""
            if suggestions:
                suggestion_text = "\n  Modelos semelhantes: " + ", ".join(f"`{s}`" for s in suggestions)
            # Accept anyway — Anthropic sometimes gates newer/preview models
            # (e.g. snapshot IDs, early-access releases) behind accounts
            # even though they aren't listed on /v1/models.
            return {
                "accepted": True,
                "persist": True,
                "recognized": False,
                "message": (
                    f"Nota: `{requested}` não foi encontrado na listagem /v1/models da Anthropic. "
                    f"Pode ainda funcionar se você tiver IDs de acesso antecipado ou snapshot."
                    f"{suggestion_text}"
                ),
            }
        # _fetch_anthropic_models returned None — no token resolvable or
        # network failure.  Fall through to the generic warning below.

    # Anthropic Messages API: many proxies don't implement /v1/models.
    # Try probing with correct auth; if it fails, accept with a warning.
    if api_mode == "anthropic_messages":
        api_models = fetch_api_models(api_key, base_url, api_mode=api_mode)
        if api_models is not None:
            if requested_for_lookup in set(api_models):
                return {
                    "accepted": True,
                    "persist": True,
                    "recognized": True,
                    "message": None,
                }
            auto = get_close_matches(requested_for_lookup, api_models, n=1, cutoff=0.9)
            if auto:
                return {
                    "accepted": True,
                    "persist": True,
                    "recognized": True,
                    "corrected_model": auto[0],
                    "message": f"Auto-corrigido `{requested}` → `{auto[0]}`",
                }
        # Probe failed or model not found — accept anyway (proxy likely
        # doesn't implement the Anthropic Models API).
        return {
            "accepted": True,
            "persist": True,
            "recognized": False,
            "message": (
                f"Nota: não foi possível verificar `{requested}` contra a listagem de modelos deste "
                f"endpoint. Muitos proxies compatíveis com Anthropic não "
                f"implementam GET /v1/models. O nome do modelo foi aceito "
                f"sem verificação."
            ),
        }

    # Probe the live API to check if the model actually exists
    api_models = fetch_api_models(api_key, base_url)

    if api_models is not None:
        # Gemini's OpenAI-compat /v1beta/openai/models endpoint returns IDs
        # prefixed with "models/" (e.g. "models/gemini-2.5-flash") — native
        # Gemini-API convention.  Our curated list and user input both use
        # the bare ID, so a direct set-membership check drops every known
        # Gemini model.  Strip the prefix before comparison.  See #12532.
        if normalized == "gemini":
            api_models = [
                m[len("models/"):] if isinstance(m, str) and m.startswith("models/") else m
                for m in api_models
            ]
        if requested_for_lookup in set(api_models):
            # API confirmed the model exists
            return {
                "accepted": True,
                "persist": True,
                "recognized": True,
                "message": None,
            }
        else:
            # API responded but model is not listed.  Accept anyway —
            # the user may have access to models not shown in the public
            # listing (e.g. Z.AI Pro/Max plans can use glm-5 on coding
            # endpoints even though it's not in /models).  Warn but allow.

            # Auto-correct if the top match is very similar (e.g. typo)
            auto = get_close_matches(requested_for_lookup, api_models, n=1, cutoff=0.9)
            if auto:
                return {
                    "accepted": True,
                    "persist": True,
                    "recognized": True,
                    "corrected_model": auto[0],
                    "message": f"Auto-corrigido `{requested}` → `{auto[0]}`",
                }

            suggestions = get_close_matches(requested, api_models, n=3, cutoff=0.5)
            suggestion_text = ""
            if suggestions:
                suggestion_text = "\n  Modelos semelhantes: " + ", ".join(f"`{s}`" for s in suggestions)

        return {
            "accepted": False,
            "persist": False,
            "recognized": False,
            "message": (
                f"O modelo `{requested}` não foi encontrado na listagem deste provedor."
                f"{suggestion_text}"
            ),
        }

    # api_models is None — couldn't reach API.  Accept and persist,
    # but warn so typos don't silently break things.

    # Bedrock: use our own discovery instead of HTTP /models endpoint.
    # Bedrock's bedrock-runtime URL doesn't support /models — it uses the
    # AWS SDK control plane (ListFoundationModels + ListInferenceProfiles).
    if normalized == "bedrock":
        try:
            from agent.bedrock_adapter import discover_bedrock_models, resolve_bedrock_region
            region = resolve_bedrock_region()
            discovered = discover_bedrock_models(region)
            discovered_ids = {m["id"] for m in discovered}
            if requested in discovered_ids:
                return {
                    "accepted": True,
                    "persist": True,
                    "recognized": True,
                    "message": None,
                }
            # Not in discovered list — still accept (user may have custom
            # inference profiles or cross-account access), but warn.
            suggestions = get_close_matches(requested, list(discovered_ids), n=3, cutoff=0.4)
            suggestion_text = ""
            if suggestions:
                suggestion_text = "\n  Modelos semelhantes: " + ", ".join(f"`{s}`" for s in suggestions)
            return {
                "accepted": True,
                "persist": True,
                "recognized": False,
                "message": (
                    f"Nota: `{requested}` não foi encontrado na descoberta de modelos do Bedrock para {region}. "
                    f"Pode ainda funcionar com perfis de inferência personalizados ou acesso entre contas."
                    f"{suggestion_text}"
                ),
            }
        except Exception:
            pass  # Fall through to generic warning

    # Static-catalog fallback: when the /models probe was unreachable,
    # validate against the curated list from provider_model_ids() — same
    # pattern as the openai-codex and minimax branches above. Without this block,
    # validate_requested_model would
    # reject every model on such providers, switch_model() would return
    # success=False, and the gateway would never write to
    # _session_model_overrides.
    provider_label = _PROVIDER_LABELS.get(normalized, normalized)
    try:
        catalog_models = provider_model_ids(normalized)
    except Exception:
        catalog_models = []

    if catalog_models:
        catalog_lower = {m.lower(): m for m in catalog_models}
        if requested_for_lookup.lower() in catalog_lower:
            return {
                "accepted": True,
                "persist": True,
                "recognized": True,
                "message": None,
            }
        catalog_lower_list = list(catalog_lower.keys())
        auto = get_close_matches(
            requested_for_lookup.lower(), catalog_lower_list, n=1, cutoff=0.9
        )
        if auto:
            corrected = catalog_lower[auto[0]]
            return {
                "accepted": True,
                "persist": True,
                "recognized": True,
                "corrected_model": corrected,
                "message": f"Auto-corrigido `{requested}` → `{corrected}`",
            }
        suggestions = get_close_matches(
            requested_for_lookup.lower(), catalog_lower_list, n=3, cutoff=0.5
        )
        suggestion_text = ""
        if suggestions:
            suggestion_text = "\n  Modelos semelhantes: " + ", ".join(
                f"`{catalog_lower[s]}`" for s in suggestions
            )
        return {
            "accepted": True,
            "persist": True,
            "recognized": False,
            "message": (
                f"Nota: `{requested}` não foi encontrado no catálogo curado de {provider_label} "
                f"e o endpoint /models estava inacessível.{suggestion_text}"
                f"\n  O modelo ainda pode funcionar se existir no provedor."
            ),
        }

    # No catalog available — accept with a warning, matching the comment's
    # stated intent ("Accept and persist, but warn").
    return {
        "accepted": True,
        "persist": True,
        "recognized": False,
        "message": (
            f"Nota: não foi possível alcançar a API de {provider_label} para validar `{requested}`. "
            f"Se o serviço não estiver fora do ar, este modelo pode não ser válido."
        ),
    }
