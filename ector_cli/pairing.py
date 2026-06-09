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
    pending = store.list_pending()
    approved = store.list_approved()

    if not pending and not approved:
        print("Nenhum dado de emparelhamento encontrado. Ninguém tentou emparelhar ainda~")
        return

    if pending:
        print(f"\n  Solicitações de Emparelhamento Pendentes ({len(pending)}):")
        print(f"  {'Plataforma':<12} {'Código':<10} {'ID Usuário':<20} {'Nome':<20} {'Idade'}")
        print(f"  {'----------':<12} {'------':<10} {'----------':<20} {'----':<20} {'-----'}")
        for p in pending:
            print(
                f"  {p['platform']:<12} {p['code']:<10} {p['user_id']:<20} "
                f"{(p.get('user_name') or ''):<20} {p['age_minutes']}m atrás"
            )
    else:
        print("\n  Nenhuma solicitação de emparelhamento pendente.")

    if approved:
        print(f"\n  Usuários Aprovados ({len(approved)}):")
        print(f"  {'Plataforma':<12} {'ID Usuário':<20} {'Nome':<20}")
        print(f"  {'----------':<12} {'----------':<20} {'----':<20}")
        for a in approved:
            print(f"  {a['platform']:<12} {a['user_id']:<20} {(a.get('user_name') or ''):<20}")
    else:
        print("\n  Nenhum usuário aprovado.")

    print()


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
