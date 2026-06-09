"""Thread-local bridge for attributing auxiliary LLM usage to the active agent."""

from __future__ import annotations

import logging
import threading
from decimal import Decimal
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_usage_recorder_local = threading.local()


def set_active_usage_recorder(recorder: Optional[Callable[..., None]]) -> None:
    """Register a callback invoked after auxiliary LLM calls complete."""
    _usage_recorder_local.recorder = recorder


def set_active_usage_agent(agent: Any) -> None:
    """Register the active AIAgent for auxiliary usage attribution."""
    if agent is None:
        clear_active_usage_recorder()
        return

    def _recorder(
        response_usage: Any,
        *,
        task: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_mode: Optional[str] = None,
    ) -> None:
        agent._record_auxiliary_usage_callback(
            response_usage,
            task=task,
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            api_mode=api_mode,
        )

    set_active_usage_recorder(_recorder)


def get_active_usage_recorder() -> Optional[Callable[..., None]]:
    return getattr(_usage_recorder_local, "recorder", None)


def clear_active_usage_recorder() -> None:
    if hasattr(_usage_recorder_local, "recorder"):
        del _usage_recorder_local.recorder


def record_auxiliary_llm_usage(
    response: Any,
    *,
    task: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    api_mode: Optional[str] = None,
) -> None:
    """Forward auxiliary usage to the active agent recorder, if any."""
    recorder = get_active_usage_recorder()
    if recorder is None:
        return
    usage = getattr(response, "usage", None)
    if not usage:
        return
    try:
        recorder(
            usage,
            task=task,
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            api_mode=api_mode,
        )
    except Exception as exc:
        logger.debug("Auxiliary usage recorder failed: %s", exc)
