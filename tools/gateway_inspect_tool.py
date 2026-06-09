#!/usr/bin/env python3
"""Read-only gateway and messaging platform status for the agent."""

import json

from tools.registry import registry


def gateway_inspect(task_id: str = None) -> str:
    """Return current gateway and messaging platform configuration status."""
    from gateway.platform_catalog import snapshot

    return json.dumps(snapshot(agent=True), ensure_ascii=False, indent=2)


def _check_gateway_inspect() -> bool:
    return True


registry.register(
    name="gateway_inspect",
    toolset="ector-core",
    schema={
        "name": "gateway_inspect",
        "description": (
            "Return JSON status of the messaging gateway and all configured channels "
            "(Telegram, Discord, Slack, WhatsApp): which are set up, whether "
            "the gateway process is running, and suggested next steps. Use this when "
            "the user asks to configure WhatsApp, Telegram, Discord, or Slack — "
            "do NOT run `ector whatsapp` or `ector gateway setup` via terminal from "
            "the web dashboard (those require an interactive TTY). Direct them to "
            "the dashboard /channels page or use this tool to explain current state."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    handler=lambda args, **kw: gateway_inspect(task_id=kw.get("task_id")),
    check_fn=_check_gateway_inspect,
)
