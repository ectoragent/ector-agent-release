"""
CLI commands for the DM pairing system.

Usage:
    ector pairing list              # Show all pending + approved users
    ector pairing approve <platform> <code>  # Approve a pairing code
    ector pairing revoke <platform> <user_id> # Revoke user access
    ector pairing clear-pending     # Clear all expired/pending codes
"""

def pairing_command(args):
    """Handle ector pairing subcommands."""
    from gateway.pairing import PairingStore

    store = PairingStore()
    action = getattr(args, "pairing_action", None)

    if action == "list":
        _cmd_list(store)
    elif action == "approve":
        _cmd_approve(store, args.platform, args.code)
    elif action == "revoke":
        _cmd_revoke(store, args.platform, args.user_id)
    elif action == "clear-pending":
        _cmd_clear_pending(store)
    else:
        print("Uso: ector pairing {list|approve|revoke|clear-pending}")
        print("Execute 'ector pairing --help' para mais detalhes.")


def _cmd_list(store):
    """List all pending and approved users."""
    from rich.console import Console

    from ector_cli.list_format import LIST_PRIMARY, ListColumn, render_list_page

    pending = store.list_pending()
    approved = store.list_approved()
    console = Console()

    if not pending and not approved:
        render_list_page(
            console,
            title="Emparelhamento",
            sections=[],
            empty_message="Ninguém tentou emparelhar ainda.",
            primary=LIST_PRIMARY,
        )
        return

    sections = []
    if pending:
        pending_rows = [
            (
                str(p.get("platform", "")),
                str(p.get("code", "")),
                str(p.get("user_id", "")),
                str(p.get("user_name") or "—"),
                f"{p.get('age_minutes', '?')}m",
            )
            for p in pending
        ]
        sections.append(
            (
                "Pendentes",
                (
                    ListColumn("Plataforma", style=f"bold {LIST_PRIMARY}", ratio=1),
                    ListColumn("Código", no_wrap=True, ratio=1),
                    ListColumn("ID usuário", overflow="fold", ratio=2),
                    ListColumn("Nome", overflow="fold", ratio=2),
                    ListColumn("Idade", style="dim", no_wrap=True, ratio=1),
                ),
                pending_rows,
            )
        )

    if approved:
        approved_rows = [
            (
                str(a.get("platform", "")),
                str(a.get("user_id", "")),
                str(a.get("user_name") or "—"),
            )
            for a in approved
        ]
        sections.append(
            (
                "Aprovados",
                (
                    ListColumn("Plataforma", style=f"bold {LIST_PRIMARY}", ratio=1),
                    ListColumn("ID usuário", overflow="fold", ratio=2),
                    ListColumn("Nome", overflow="fold", ratio=2),
                ),
                approved_rows,
            )
        )

    render_list_page(
        console,
        title="Emparelhamento",
        sections=sections,
        summary=f"[dim]{len(pending)} pendente(s) · {len(approved)} aprovado(s)[/]",
        footer="[dim]Aprovar:[/] [bold]ector pairing approve <plataforma> <código>[/]",
        primary=LIST_PRIMARY,
    )


def _cmd_approve(store, platform: str, code: str):
    """Approve a pairing code."""
    platform = platform.lower().strip()
    code = code.upper().strip()

    result = store.approve_code(platform, code)
    if result:
        uid = result["user_id"]
        name = result.get("user_name") or ""
        display = f"{name} ({uid})" if name else uid
        print(f"\n  Aprovado! O usuário {display} no {platform} agora pode usar o bot~")
        print("  Eles serão reconhecidos automaticamente na próxima mensagem.\n")
    else:
        print(f"\n  Código '{code}' não encontrado ou expirado para a plataforma '{platform}'.")
        print("  Execute 'ector pairing list' para ver códigos pendentes.\n")


def _cmd_revoke(store, platform: str, user_id: str):
    """Revoke a user's access."""
    platform = platform.lower().strip()

    if store.revoke(platform, user_id):
        print(f"\n  Acesso revogado para o usuário {user_id} no {platform}.\n")
    else:
        print(f"\n  Usuário {user_id} não encontrado na lista de aprovados para {platform}.\n")


def _cmd_clear_pending(store):
    """Clear all pending pairing codes."""
    count = store.clear_pending()
    if count:
        print(f"\n  Limpas {count} solicitação(ões) de emparelhamento pendente(s).\n")
    else:
        print("\n  Nenhuma solicitação pendente para limpar.\n")
