"""Shared CLI routing tables for identity gate and plugin/hook discovery.

Single source of truth for which top-level commands require Ector identity
auth and which nested subcommands start the agent or long-running runtime.
"""

from __future__ import annotations

# Subcommands that NEVER require identity auth.
OFFLINE_COMMANDS = frozenset({
    "login", "logout", "me",
    "version", "update", "uninstall",
    "setup", "doctor", "logs", "dump", "debug",
    "config", "hooks", "profile",
    "auth", "sessions", "skills", "tools",
    "status", "pairing", "memory",
    "backup", "reset",
})

# For grouped subcommands, identity auth and plugin discovery apply only when
# the nested sub starts an agent / serves a long-running runtime.
GROUPED_AGENT_SUBS: dict[str, tuple[str, frozenset[str]]] = {
    "cron": ("cron_command", frozenset({"run", "tick"})),
    "gateway": ("gateway_command", frozenset({"run", "start"})),
    "mcp": ("mcp_action", frozenset({"serve"})),
}

# Top-level commands that always run the agent (or agent-adjacent runtime).
AGENT_TOP_LEVEL_COMMANDS = frozenset({"chat", "acp", "rl", "localhost"})


def command_requires_identity(args) -> bool:
    """Return True when the parsed args will eventually run the agent."""
    cmd = getattr(args, "command", None)
    if getattr(args, "oneshot", None):
        return True
    if cmd is None:
        return bare_ector_should_use_chat(args)
    if cmd in OFFLINE_COMMANDS:
        return False
    if cmd in GROUPED_AGENT_SUBS:
        sub_attr, agent_subs = GROUPED_AGENT_SUBS[cmd]
        sub = getattr(args, sub_attr, None)
        return sub in agent_subs
    return True


def bare_ector_should_use_chat(args) -> bool:
    """Bare ``ector`` (no subcommand) routes to terminal chat."""
    if getattr(args, "model", None):
        return True
    if getattr(args, "provider", None):
        return True
    if getattr(args, "skills", None):
        return True
    if getattr(args, "worktree", False):
        return True
    if getattr(args, "yolo", False):
        return True
    if getattr(args, "pass_session_id", False):
        return True
    if getattr(args, "ignore_user_config", False):
        return True
    if getattr(args, "ignore_rules", False):
        return True
    return True


def should_discover_plugins_and_hooks(args) -> bool:
    """True when startup should run plugin discovery and shell-hook registration."""
    cmd = getattr(args, "command", None)
    if cmd is None or cmd in AGENT_TOP_LEVEL_COMMANDS:
        return True
    if cmd in GROUPED_AGENT_SUBS:
        sub_attr, agent_subs = GROUPED_AGENT_SUBS[cmd]
        return getattr(args, sub_attr, None) in agent_subs
    return False
