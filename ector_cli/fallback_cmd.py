"""
ector fallback — manage the fallback provider chain.

Fallback providers are tried in order when the primary model fails with
rate-limit, overload, or connection errors. See:
https://ector.cc/docs/user-guide/features/fallback-providers

Subcommands:
  ector fallback [list]   Show the current fallback chain (default when no subcommand)
  ector fallback add      Pick provider + model via the same picker as `ector provider`,
                           then append the selection to the chain
  ector fallback remove   Pick an entry to delete from the chain
  ector fallback clear    Remove all fallback entries

Storage: ``fallback_providers`` in ``~/.ector/config.yaml`` (top-level, list of
``{provider, model, base_url?, api_mode?}`` dicts).  The legacy single-dict
``fallback_model`` format is migrated to the new list format on first add.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_chain(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the normalized fallback chain as a list of dicts.

    Accepts both the new list format (``fallback_providers``) and the legacy
    single-dict format (``fallback_model``).  The returned list is always a
    fresh copy — callers can mutate without touching the config dict.
    """
    chain = config.get("fallback_providers") or []
    if isinstance(chain, list):
        result = [dict(e) for e in chain if isinstance(e, dict) and e.get("provider") and e.get("model")]
        if result:
            return result
    legacy = config.get("fallback_model")
    if isinstance(legacy, dict) and legacy.get("provider") and legacy.get("model"):
        return [dict(legacy)]
    if isinstance(legacy, list):
        return [dict(e) for e in legacy if isinstance(e, dict) and e.get("provider") and e.get("model")]
    return []


def _write_chain(config: Dict[str, Any], chain: List[Dict[str, Any]]) -> None:
    """Persist the chain to ``fallback_providers`` and clear legacy key."""
    config["fallback_providers"] = chain
    # Drop the legacy single-dict key on write so there's only one source of truth.
    if "fallback_model" in config:
        config.pop("fallback_model", None)


def _format_entry(entry: Dict[str, Any]) -> str:
    """One-line human-readable rendering of a fallback entry."""
    provider = entry.get("provider", "?")
    model = entry.get("model", "?")
    base = entry.get("base_url")
    suffix = f"  [{base}]" if base else ""
    return f"{model}  (por {provider}){suffix}"


def _extract_fallback_from_model_cfg(model_cfg: Any) -> Optional[Dict[str, Any]]:
    """Pull the ``{provider, model, base_url?, api_mode?}`` dict from a ``config["model"]`` snapshot."""
    if not isinstance(model_cfg, dict):
        return None
    provider = (model_cfg.get("provider") or "").strip()
    # The picker writes the selected model to ``model.default``.
    model = (model_cfg.get("default") or model_cfg.get("model") or "").strip()
    if not provider or not model:
        return None
    entry: Dict[str, Any] = {"provider": provider, "model": model}
    base_url = (model_cfg.get("base_url") or "").strip()
    if base_url:
        entry["base_url"] = base_url
    api_mode = (model_cfg.get("api_mode") or "").strip()
    if api_mode:
        entry["api_mode"] = api_mode
    return entry


def _snapshot_auth_active_provider() -> Any:
    """Return the current ``active_provider`` in auth.json, or a sentinel if unavailable."""
    try:
        from ector_cli.auth import _load_auth_store
        store = _load_auth_store()
        return store.get("active_provider")
    except Exception:
        return None


def _restore_auth_active_provider(value: Any) -> None:
    """Write back a previously snapshotted ``active_provider`` value."""
    try:
        from ector_cli.auth import _auth_store_lock, _load_auth_store, _save_auth_store
        with _auth_store_lock():
            store = _load_auth_store()
            store["active_provider"] = value
            _save_auth_store(store)
    except Exception:
        # Best-effort — if auth.json can't be restored, the user's primary
        # provider may have been deactivated by the picker.  They can re-run
        # `ector provider` to fix it.  Don't fail the fallback add.
        pass


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_fallback_list(args) -> None:  # noqa: ARG001
    """Print the current fallback chain."""
    from rich.console import Console

    from ector_cli.config import load_config
    from ector_cli.list_format import LIST_PRIMARY, ListColumn, render_list_page

    config = load_config()
    chain = _read_chain(config)
    console = Console()

    if not chain:
        render_list_page(
            console,
            title="Fallback de provedores",
            sections=[],
            empty_message="Nenhum provedor de fallback configurado.",
            empty_hint="[dim]Adicione com[/] [bold]ector fallback add[/]",
            primary=LIST_PRIMARY,
        )
        return

    primary = _describe_primary(config)
    rows = [(str(i), _format_entry(entry)) for i, entry in enumerate(chain, 1)]

    render_list_page(
        console,
        title="Fallback de provedores",
        subtitle=f"primário: {primary}" if primary else "",
        sections=[
            (
                "Cadeia",
                (
                    ListColumn("#", justify="right", width=3, style="dim"),
                    ListColumn("Provedor / modelo", style=f"bold {LIST_PRIMARY}", ratio=4),
                ),
                rows,
            )
        ],
        summary=f"[dim]{len(chain)} entrada(s) — tentadas quando o primário falha[/]",
        footer="[dim]Docs:[/] https://ector.cc/docs/user-guide/features/fallback-providers",
        primary=LIST_PRIMARY,
    )


def _describe_primary(config: Dict[str, Any]) -> Optional[str]:
    """One-line description of the primary model for display purposes."""
    model_cfg = config.get("model")
    if isinstance(model_cfg, dict):
        provider = (model_cfg.get("provider") or "?").strip() or "?"
        model = (model_cfg.get("default") or model_cfg.get("model") or "?").strip() or "?"
        return f"{model}  (por {provider})"
    if isinstance(model_cfg, str) and model_cfg.strip():
        return model_cfg.strip()
    return None


def cmd_fallback_add(args) -> None:
    """Launch the same picker as `ector provider`, then append the selection to the chain."""
    from ector_cli.main import _require_tty, select_provider_and_model
    from ector_cli.config import load_config, save_config

    _require_tty("fallback add")

    # Snapshot BEFORE the picker runs so we can distinguish "user actually
    # picked something" from "user cancelled" by comparing before/after.
    before_cfg = load_config()
    model_before = copy.deepcopy(before_cfg.get("model"))
    active_provider_before = _snapshot_auth_active_provider()

    print()
    print("  Adicionando um provedor de fallback. O seletor abaixo é o mesmo de")
    print("  `ector provider` — escolha o provedor + modelo que deseja como fallback.")
    print()

    try:
        select_provider_and_model(args=args)
    except SystemExit:
        # Some provider flows exit on auth failure — restore state and re-raise.
        _restore_model_cfg(model_before)
        _restore_auth_active_provider(active_provider_before)
        raise

    # Read the post-picker state to see what the user selected.
    after_cfg = load_config()
    model_after = after_cfg.get("model")

    new_entry = _extract_fallback_from_model_cfg(model_after)
    if not new_entry:
        # Picker didn't complete (user cancelled or flow bailed).  Nothing to do.
        _restore_model_cfg(model_before)
        _restore_auth_active_provider(active_provider_before)
        print()
        print("  Nenhum fallback adicionado.")
        return

    # Picker picked the same thing that's already the primary → nothing changed,
    # and there's nothing useful to add as a fallback to itself.
    primary_entry = _extract_fallback_from_model_cfg(model_before)
    if primary_entry and primary_entry["provider"] == new_entry["provider"] \
            and primary_entry["model"] == new_entry["model"]:
        _restore_model_cfg(model_before)
        _restore_auth_active_provider(active_provider_before)
        print()
        print(f"  O modelo selecionado é o mesmo primário ({_format_entry(new_entry)}).")
        print("  Um provedor não pode ser fallback de si mesmo — nada alterado.")
        return

    # Reload the config with the primary restored, then append the new entry
    # to ``fallback_providers``.  We deliberately re-load (rather than mutating
    # ``after_cfg``) because the picker may have touched other top-level keys
    # (custom_providers, providers credentials) that we want to keep.
    _restore_model_cfg(model_before)
    _restore_auth_active_provider(active_provider_before)

    final_cfg = load_config()
    chain = _read_chain(final_cfg)

    # Reject exact-duplicate fallback entries.
    for existing in chain:
        if existing.get("provider") == new_entry["provider"] \
                and existing.get("model") == new_entry["model"]:
            print()
            print(f"  {_format_entry(new_entry)} já está na cadeia de fallback — ignorado.")
            return

    chain.append(new_entry)
    _write_chain(final_cfg, chain)
    save_config(final_cfg)

    print()
    print(f"  Fallback adicionado: {_format_entry(new_entry)}")
    n = len(chain)
    print(f"  A cadeia agora tem {n} {'entrada' if n == 1 else 'entradas'}.")
    print()
    print("  Execute `ector fallback list` para ver ou `ector fallback remove` para remover.")


def _restore_model_cfg(model_before: Any) -> None:
    """Restore ``config["model"]`` to a previously-captured snapshot."""
    from ector_cli.config import load_config, save_config

    cfg = load_config()
    if model_before is None:
        cfg.pop("model", None)
    else:
        cfg["model"] = copy.deepcopy(model_before)
    save_config(cfg)


def cmd_fallback_remove(args) -> None:  # noqa: ARG001
    """Pick an entry from the chain and remove it."""
    from ector_cli.config import load_config, save_config

    config = load_config()
    chain = _read_chain(config)

    if not chain:
        print()
        print("  Nenhum provedor de fallback configurado — nada a remover.")
        print()
        return

    choices = [_format_entry(e) for e in chain]
    choices.append("Cancelar")

    try:
        from ector_cli.setup import _curses_prompt_choice
        idx = _curses_prompt_choice("Selecione um fallback para remover:", choices, 0)
    except Exception:
        idx = _numbered_pick("Selecione um fallback para remover:", choices)

    if idx is None or idx < 0 or idx >= len(chain):
        print()
        print("  Cancelado — sem alterações.")
        return

    removed = chain.pop(idx)
    _write_chain(config, chain)
    save_config(config)

    print()
    print(f"  Fallback removido: {_format_entry(removed)}")
    if chain:
        n = len(chain)
        print(f"  A cadeia agora tem {n} {'entrada' if n == 1 else 'entradas'}.")
    else:
        print("  A cadeia de fallback está vazia.")
    print()


def cmd_fallback_clear(args) -> None:  # noqa: ARG001
    """Remove all fallback entries (with confirmation)."""
    from ector_cli.config import load_config, save_config

    config = load_config()
    chain = _read_chain(config)

    if not chain:
        print()
        print("  Nenhum provedor de fallback configurado — nada a limpar.")
        print()
        return

    print()
    n = len(chain)
    print(f"  Cadeia de fallback atual ({n} {'entrada' if n == 1 else 'entradas'}):")
    for i, entry in enumerate(chain, 1):
        print(f"    {i}. {_format_entry(entry)}")
    print()
    try:
        resp = input("  Limpar todas as entradas? (s/n): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        print("  Cancelado.")
        return
    if resp not in ("s", "sim", "y", "yes"):
        print("  Cancelado — sem alterações.")
        return

    _write_chain(config, [])
    save_config(config)
    print()
    print("  Cadeia de fallback limpa.")
    print()


def _numbered_pick(question: str, choices: List[str]) -> Optional[int]:
    """Fallback numbered-list picker when curses is unavailable."""
    print(question)
    for i, c in enumerate(choices, 1):
        print(f"  {i}. {c}")
    print()
    while True:
        try:
            val = input(f"Escolha [1-{len(choices)}]: ").strip()
            if not val:
                return None
            idx = int(val) - 1
            if 0 <= idx < len(choices):
                return idx
            print(f"Digite um número entre 1 e {len(choices)}")
        except ValueError:
            print("Digite um número válido")
        except (KeyboardInterrupt, EOFError):
            print()
            return None


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def cmd_fallback(args) -> None:
    """Top-level dispatcher for ``ector fallback [subcommand]``."""
    sub = getattr(args, "fallback_command", None)
    if sub in (None, "", "list", "ls"):
        cmd_fallback_list(args)
    elif sub == "add":
        cmd_fallback_add(args)
    elif sub in ("remove", "rm"):
        cmd_fallback_remove(args)
    elif sub == "clear":
        cmd_fallback_clear(args)
    else:
        print(f"Subcomando de fallback desconhecido: {sub}")
        print("Use um de: list, add, remove, clear")
        raise SystemExit(2)
