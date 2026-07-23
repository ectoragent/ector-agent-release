"""User-visible status lines (pt-BR) for TUI, dashboard SSE, and gateway."""


def reasoning_status(elapsed_seconds: int | None = None) -> str:
    """While waiting for the model to respond."""
    if not elapsed_seconds or elapsed_seconds <= 0:
        return "Trabalhando…"
    return f"Trabalhando… ({int(elapsed_seconds)}s)"


def stale_response_status(seconds: int, *, streaming: bool) -> str:
    """Provider call exceeded the stale threshold."""
    if streaming:
        return f"▲ Demorou mais que o esperado ({int(seconds)}s)… reconectando"
    return f"▲ Demorou mais que o esperado ({int(seconds)}s)… tentando de novo"


def internet_unavailable_status() -> str:
    return "▲ Sem conexão com a internet — verifique a rede e tente de novo."


def web_request_timeout_status(seconds: int, *, crawl: bool = False) -> str:
    """Web tool HTTP/SDK call exceeded the configured timeout."""
    op = "rastreio do site" if crawl else "consulta na web"
    return (
        f"▲ A {op} excedeu o tempo limite ({int(seconds)}s) — "
        "verifique sua conexão e as chaves da API, ou tente de novo."
    )


def provider_unreachable_status() -> str:
    return (
        "▲ Não foi possível alcançar o provedor do modelo — "
        "verifique sua conexão."
    )


def unstable_connection_status(attempt: int, max_attempts: int) -> str:
    return f"▲ Conexão instável — reconectando ({attempt}/{max_attempts})…"


def connection_exhausted_status(max_attempts: int) -> str:
    return (
        f"❌ Não consegui manter a conexão após {max_attempts} tentativas. "
        "Tente de novo em instantes."
    )


def tool_stream_reconnect_status(attempt: int, max_attempts: int) -> str:
    return (
        f"▲ Conexão caiu durante uma ferramenta — reconectando "
        f"({attempt}/{max_attempts})…"
    )


def reconnected_resuming_status() -> str:
    return "Reconectado — retomando…"


def fallback_model_status(model: str) -> str:
    return f"Alternando para modelo reserva ({model})…"


def rate_limit_fallback_status() -> str:
    return "▲ Muitas requisições — tentando outro modelo…"


def history_compressing_status(attempt: int, max_attempts: int) -> str:
    return f"▲ Histórico muito longo — comprimindo ({attempt}/{max_attempts})…"


def history_compressed_retry_status() -> str:
    return "🗜️ Histórico enxugado — tentando de novo…"


def conversation_compressing_status(attempt: int, max_attempts: int) -> str:
    return f"🗜️ Conversa muito longa — comprimindo ({attempt}/{max_attempts})…"


def incomplete_response_fallback_status() -> str:
    return "▲ Resposta incompleta — tentando outro modelo…"


def invalid_response_retry_status(max_retries: int) -> str:
    return (
        f"▲ Resposta inválida após {max_retries} tentativas — tentando outro modelo…"
    )


def api_error_fallback_status() -> str:
    return "▲ Erro na API — tentando outro modelo…"


def retries_exhausted_fallback_status(max_retries: int) -> str:
    return f"▲ {max_retries} tentativas sem sucesso — tentando outro modelo…"


def rate_limit_pause_status(wait_seconds: float, attempt: int, max_retries: int) -> str:
    return (
        f"Pausa rápida (limite de uso) — retomando em {wait_seconds:.1f}s "
        f"({attempt}/{max_retries})…"
    )


def retry_pause_status(wait_seconds: float, attempt: int, max_retries: int) -> str:
    return f"Nova tentativa em {wait_seconds:.1f}s ({attempt}/{max_retries})…"


def interrupt_during_reasoning_message(elapsed_seconds: float) -> str:
    return (
        f"Operação interrompida durante o raciocínio "
        f"({elapsed_seconds:.1f}s decorridos)."
    )
