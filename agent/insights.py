"""Backward-compatible re-exports — use ``agent.stats`` instead."""

from agent.stats import (  # noqa: F401
    StatsEngine as InsightsEngine,
    _bar_chart,
    _format_duration,
)
