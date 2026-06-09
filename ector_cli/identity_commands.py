"""CLI handlers for Ector identity auth (``login``/``logout``/``me``).

Thin layer over :mod:`ector_cli.identity_auth` that turns argparse
namespaces into stdout/stderr output and exit codes. Kept separate
from the auth core so the module is testable without argparse.
"""

from __future__ import annotations

import sys
from typing import Any

from ector_cli import identity_auth
from ector_cli.colors import Colors, color
from ector_cli.identity_auth import IdentityAuthError


def _print_login_cancelled() -> None:
    print(
        color("✕", Colors.DIM, Colors.BOLD)
        + color(" Login cancelado pelo usuário.", Colors.DIM),
        file=sys.stderr,
    )


def cmd_identity_login(args: Any) -> int:
    """Handle ``ector login`` (no --provider) — identity login."""
    try:
        return _cmd_identity_login_impl(args)
    except KeyboardInterrupt:
        _print_login_cancelled()
        return 130


def _cmd_identity_login_impl(args: Any) -> int:
    if identity_auth.is_logged_in() and not getattr(args, "force", False):
        try:
            me = identity_auth.whoami(force=True)
        except IdentityAuthError as exc:
            print(f"Sessão existente inválida ({exc}); refazendo login…", file=sys.stderr)
        else:
            if me:
                # ``whoami(force=True)`` has just refreshed config.user.*
                # from /me, so read the nickname from there for a friendly
                # greeting. Fall back to the email when the user has no
                # nickname set on the backend yet.
                profile = identity_auth.get_user_profile()
                nickname = profile.get("nickname") or ""
                identifier = nickname or me.get("email") or me.get("user_id") or "(sem identidade)"
                print(
                    color("✓", Colors.GREEN, Colors.BOLD)
                    + color(" Você já está autenticado como ", Colors.BOLD)
                    + color(identifier, Colors.CYAN, Colors.BOLD)
                    + color(".", Colors.BOLD)
                )
                print(
                    color("  Use ", Colors.DIM)
                    + color("ector login --force", Colors.CYAN)
                    + color(" para refazer o login.", Colors.DIM)
                )
                return 0

    open_browser = not bool(getattr(args, "no_browser", False))
    try:
        # ``identity_auth.login`` already prints the friendly success
        # banner ("Login realizado com sucesso." + optional "Olá <nick>!"),
        # so we don't echo it again here.
        callback_timeout = getattr(args, "callback_timeout", None)
        identity_auth.login(
            open_browser=open_browser,
            timeout_seconds=callback_timeout,
            force_device=bool(getattr(args, "device", False)),
            force_local=bool(getattr(args, "local", False)),
        )
    except IdentityAuthError as exc:
        if exc.code == "user_cancelled":
            _print_login_cancelled()
            return 130
        message = identity_auth.identity_auth_user_message(exc)
        print(
            color("✕", Colors.RED, Colors.BOLD)
            + color(f" {message.splitlines()[0]}", Colors.BOLD),
            file=sys.stderr,
        )
        for line in message.splitlines()[1:]:
            print(color(f"  {line}", Colors.DIM), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Erro inesperado no login: {exc}", file=sys.stderr)
        return 2

    return 0


def cmd_identity_logout(args: Any) -> int:
    """Handle ``ector logout`` (no --provider) — identity logout."""
    try:
        had = identity_auth.logout()
    except Exception as exc:  # noqa: BLE001
        print(f"Falha ao desautenticar: {exc}", file=sys.stderr)
        return 2

    if had:
        print("Sessão encerrada.")
    else:
        print("Nenhuma sessão ativa.")
    return 0


def _me_label(key: str) -> str:
    return color(f"  {key:<10}", Colors.DIM)


def _me_value(text: str, *, highlight: bool = False) -> str:
    if not text:
        return color("—", Colors.DIM)
    if highlight:
        return color(text, Colors.CYAN, Colors.BOLD)
    return text


def _print_me_summary(nickname: str, user: str, session_status: str) -> None:
    """Print nickname, user (email), and session status only."""
    print(_me_label("Nickname") + _me_value(nickname, highlight=bool(nickname)))
    print(_me_label("Usuário") + _me_value(user))
    print(_me_label("Sessão") + _me_value(session_status))


def _session_status_from_store() -> str:
    if not identity_auth.is_logged_in():
        return "não autenticada"
    if identity_auth.get_cached_access_level() == "blocked":
        return "sem acesso ao agente"
    return "ativa"


def _profile_fields_for_display() -> tuple[str, str]:
    profile = identity_auth.get_user_profile()
    return (
        str(profile.get("nickname") or "").strip(),
        str(profile.get("email") or "").strip(),
    )


def cmd_identity_me(args: Any) -> int:
    """Handle ``ector me``."""
    if not identity_auth.is_logged_in():
        _print_me_summary("", "", "não autenticada")
        print("Não autenticado. Execute: ector login", file=sys.stderr)
        return 1

    try:
        me = identity_auth.whoami(force=bool(getattr(args, "refresh", False)))
    except IdentityAuthError as exc:
        nickname, user = _profile_fields_for_display()
        if exc.access_level == "blocked":
            _print_me_summary(nickname, user, "sem acesso ao agente")
            identity_auth.print_subscription_blocked_message(str(exc), file=sys.stderr)
            return 3
        _print_me_summary(nickname, user, "inválida")
        print(f"Sessão inválida: {exc}", file=sys.stderr)
        if exc.relogin_required:
            print("Execute: ector login", file=sys.stderr)
        return 2

    if not me:
        _print_me_summary("", "", "não autenticada")
        print("Não autenticado. Execute: ector login", file=sys.stderr)
        return 1

    profile = identity_auth.get_user_profile()
    nickname = str(profile.get("nickname") or "").strip()
    user = str(me.get("email") or "").strip()
    _print_me_summary(nickname, user, _session_status_from_store())
    return 0


__all__ = [
    "cmd_identity_login",
    "cmd_identity_logout",
    "cmd_identity_me",
]
