"""Network/connectivity error detection for graceful agent recovery."""

from __future__ import annotations

import errno
import json
import re

_CONNECTION_ERROR_TYPES = frozenset({
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "PoolTimeout",
    "RemoteProtocolError",
    "ConnectionError",
    "ConnectionResetError",
    "gaierror",
})

_OFFLINE_MARKERS = (
    "network is unreachable",
    "no route to host",
    "name or service not known",
    "nodename nor servname provided",
    "getaddrinfo failed",
    "temporary failure in name resolution",
    "failed to establish a new connection",
    "network unreachable",
    "enetunreach",
    "ehostunreach",
    "could not resolve host",
    "name resolution",
)


def is_transient_connection_error(exc: Exception) -> bool:
    """True for transport-level failures that may recover with a retry."""
    name = type(exc).__name__
    if name in _CONNECTION_ERROR_TYPES:
        return True
    err_lower = str(exc).lower()
    return any(
        kw in err_lower
        for kw in (
            "connection refused",
            "connection reset",
            "connection lost",
            "connection closed",
            "connection terminated",
            "timed out",
            "timeout",
            "network error",
            "network connection",
            "peer closed",
            "broken pipe",
        )
    )


def is_likely_internet_unavailable(exc: Exception) -> bool:
    """True when the failure pattern suggests no working internet route."""
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
        errno.ENETDOWN,
    ):
        return True
    err_lower = str(exc).lower()
    return any(marker in err_lower for marker in _OFFLINE_MARKERS)


def offline_error_summary() -> str:
    return (
        "Sem conexão com a internet ou com o provedor do modelo. "
        "Verifique a rede e tente novamente."
    )


_MESSAGE_IN_QUOTES_RE = re.compile(
    r"""['"]message['"]\s*:\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


def _extract_embedded_error_message(error: str | Exception) -> str | None:
    """Pull a provider message out of SDK/JSON error strings."""
    if isinstance(error, Exception):
        body = getattr(error, "body", None)
        if isinstance(body, dict):
            err_obj = body.get("error")
            if isinstance(err_obj, dict):
                msg = str(err_obj.get("message") or "").strip()
                if msg:
                    return msg
            msg = str(body.get("message") or "").strip()
            if msg:
                return msg
    text = str(error).strip()
    if not text:
        return None
    match = _MESSAGE_IN_QUOTES_RE.search(text)
    if match:
        return match.group(1).strip()
    brace = text.find("{")
    if brace >= 0:
        try:
            payload = json.loads(text[brace:])
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            err_obj = payload.get("error")
            if isinstance(err_obj, dict):
                msg = str(err_obj.get("message") or "").strip()
                if msg:
                    return msg
    return None


def _provider_specific_user_message(error: str | Exception) -> str | None:
    """Known provider errors with actionable pt-BR guidance."""
    extracted = _extract_embedded_error_message(error) or str(error)
    lowered = extracted.lower()
    if "third-party apps" in lowered and "extra usage" in lowered:
        return (
            "O OAuth Anthropic conectado no Ector é tratado como app de terceiros "
            "pela Anthropic — o uso não debita o limite do seu plano, e sim os "
            "créditos de **uso extra**. Adicione créditos em "
            "claude.ai/settings/usage, use uma API key (sk-ant-api…) ou troque "
            "de provedor no seletor de modelos."
        )
    return None


def user_facing_api_error_summary(exc: Exception) -> str:
    """Short pt-BR summary for status lines and final bubbles."""
    if is_likely_internet_unavailable(exc):
        return offline_error_summary()
    if is_transient_connection_error(exc):
        return (
            "Não foi possível alcançar o provedor do modelo — "
            "verifique sua conexão."
        )
    return ""


def format_api_failure_final_response(
    exc: Exception,
    *,
    max_retries: int,
    stream_drop: bool = False,
) -> str:
    """User-facing assistant message when API retries are exhausted."""
    from agent.user_status import connection_exhausted_status

    if is_likely_internet_unavailable(exc):
        return offline_error_summary()
    if stream_drop:
        base = connection_exhausted_status(max_retries)
        return (
            f"{base}\n\n"
            "A conexão com o provedor caiu durante a resposta — isso pode "
            "acontecer quando o modelo gera uma ferramenta muito grande. "
            "Tente pedir para gravar o arquivo em partes menores ou usar "
            "execute_code."
        )
    if is_transient_connection_error(exc):
        return connection_exhausted_status(max_retries)
    specific = _provider_specific_user_message(exc)
    if specific:
        return specific
    summary = _extract_embedded_error_message(exc) or str(exc).strip()
    if not summary:
        return (
            f"A chamada de API falhou após {max_retries} tentativas. "
            "Tente de novo em instantes."
        )
    if len(summary) > 220 or "<html" in summary.lower():
        return (
            f"A chamada de API falhou após {max_retries} tentativas. "
            "O provedor retornou um erro inesperado — tente de novo em instantes."
        )
    return (
        f"A chamada de API falhou após {max_retries} tentativas: {summary[:220]}"
    )


def user_facing_failure_text(
    *,
    error: str | Exception | None = None,
    max_retries: int = 3,
    stream_drop: bool = False,
) -> str | None:
    """Build a friendly assistant bubble when a turn ends with failed=True."""
    if error is None:
        return offline_error_summary()
    if isinstance(error, Exception):
        return format_api_failure_final_response(
            error,
            max_retries=max_retries,
            stream_drop=stream_drop,
        )
    text = str(error).strip()
    if not text:
        return offline_error_summary()
    specific = _provider_specific_user_message(text)
    if specific:
        return specific
    embedded = _extract_embedded_error_message(text)
    if embedded:
        text = embedded
    lowered = text.lower()
    if any(marker in lowered for marker in _OFFLINE_MARKERS):
        return offline_error_summary()
    if any(
        kw in lowered
        for kw in (
            "connection refused",
            "connection reset",
            "connection lost",
            "connection closed",
            "network connection",
            "network error",
            "timed out",
            "timeout",
            "peer closed",
        )
    ):
        from agent.user_status import connection_exhausted_status

        return connection_exhausted_status(max_retries)
    if len(text) > 220 or "<html" in lowered:
        return (
            "Não foi possível concluir a resposta — o provedor retornou um erro "
            "inesperado. Tente de novo em instantes."
        )
    return text
