"""ector webhook — manage dynamic webhook subscriptions from the CLI.

Usage:
    ector webhook subscribe <name> [options]
    ector webhook list
    ector webhook remove <name>
    ector webhook test <name> [--payload '{"key": "value"}']

Subscriptions persist to ~/.ector/webhook_subscriptions.json and are
hot-reloaded by the webhook adapter without a gateway restart.
"""

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Dict

from ector_constants import display_ector_home

_ECTOR_ACCENT = "#00D1FF"


_SUBSCRIPTIONS_FILENAME = "webhook_subscriptions.json"


def _ector_home() -> Path:
    from ector_constants import get_ector_home
    return get_ector_home()


def _subscriptions_path() -> Path:
    return _ector_home() / _SUBSCRIPTIONS_FILENAME


def _load_subscriptions() -> Dict[str, dict]:
    path = _subscriptions_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_subscriptions(subs: Dict[str, dict]) -> None:
    path = _subscriptions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(subs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(str(tmp_path), str(path))


def _get_webhook_config() -> dict:
    """Load webhook platform config. Returns {} if not configured."""
    try:
        from ector_cli.config import load_config
        cfg = load_config()
        return cfg.get("platforms", {}).get("webhook", {})
    except Exception:
        return {}


def _is_webhook_enabled() -> bool:
    return bool(_get_webhook_config().get("enabled"))


def _get_webhook_base_url() -> str:
    wh = _get_webhook_config().get("extra", {})
    host = wh.get("host", "0.0.0.0")
    port = wh.get("port", 8644)
    display_host = "localhost" if host == "0.0.0.0" else host
    return f"http://{display_host}:{port}"


def _section_title(text: str) -> str:
    return f"[bold {_ECTOR_ACCENT}]{text}[/bold {_ECTOR_ACCENT}]"


def _setup_hint() -> str:
    _dhh = display_ector_home()
    return f"""
  A plataforma webhook não está ativa — sem ela, `ector webhook list` não funciona.

  Ative de uma destas formas:

  {_section_title("1. Assistente interativo (recomendado)")}
     ector gateway setup

  {_section_title(f"2. Manualmente em {_dhh}/config.yaml:")}

     platforms:
       webhook:
         enabled: true
         extra:
           host: "0.0.0.0"
           port: 8644
           secret: "seu-segredo-hmac-global"

  {_section_title(f"3. Variáveis de ambiente em {_dhh}/.env:")}

     WEBHOOK_ENABLED=true
     WEBHOOK_PORT=8644
     WEBHOOK_SECRET=seu-segredo-global

  {_section_title("Em seguida, inicie o gateway para receber eventos:")}

     ector gateway run
"""


def _require_webhook_enabled() -> bool:
    """Check webhook is enabled. Print setup guide and return False if not."""
    if _is_webhook_enabled():
        return True
    from rich.console import Console

    Console().print(_setup_hint())
    return False


def webhook_command(args):
    """Entry point for 'ector webhook' subcommand."""
    sub = getattr(args, "webhook_action", None)

    if not sub:
        print("Usage: ector webhook {subscribe|list|remove|test}")
        print("Run 'ector webhook --help' for details.")
        return

    if not _require_webhook_enabled():
        return

    if sub in ("subscribe", "add"):
        _cmd_subscribe(args)
    elif sub in ("list", "ls"):
        _cmd_list(args)
    elif sub in ("remove", "rm"):
        _cmd_remove(args)
    elif sub == "test":
        _cmd_test(args)


def _cmd_subscribe(args):
    name = args.name.strip().lower().replace(" ", "-")
    if not re.match(r'^[a-z0-9][a-z0-9_-]*$', name):
        print(f"Error: Invalid name '{name}'. Use lowercase alphanumeric with hyphens/underscores.")
        return

    subs = _load_subscriptions()
    is_update = name in subs

    secret = args.secret or secrets.token_urlsafe(32)
    events = [e.strip() for e in args.events.split(",")] if args.events else []

    route = {
        "description": args.description or f"Agent-created subscription: {name}",
        "events": events,
        "secret": secret,
        "prompt": args.prompt or "",
        "skills": [s.strip() for s in args.skills.split(",")] if args.skills else [],
        "deliver": args.deliver or "log",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    if getattr(args, "deliver_only", False):
        if route["deliver"] == "log":
            print(
                "Error: --deliver-only requires --deliver to be a real target "
                "(telegram, discord, slack, github_comment, etc.) — not 'log'."
            )
            return
        route["deliver_only"] = True

    if args.deliver_chat_id:
        route["deliver_extra"] = {"chat_id": args.deliver_chat_id}

    subs[name] = route
    _save_subscriptions(subs)

    base_url = _get_webhook_base_url()
    status = "Updated" if is_update else "Created"

    print(f"\n  {status} webhook subscription: {name}")
    print(f"  URL:    {base_url}/webhooks/{name}")
    print(f"  Secret: {secret}")
    if events:
        print(f"  Events: {', '.join(events)}")
    else:
        print("  Events: (all)")
    print(f"  Deliver: {route['deliver']}")
    if route.get("deliver_only"):
        print("  Mode: direct delivery (no agent, zero LLM cost)")
    if route.get("prompt"):
        prompt_preview = route["prompt"][:80] + ("..." if len(route["prompt"]) > 80 else "")
        label = "Message" if route.get("deliver_only") else "Prompt"
        print(f"  {label}: {prompt_preview}")
    print(f"\n  Configure your service to POST to the URL above.")
    print(f"  Use the secret for HMAC-SHA256 signature validation.")
    print(f"  The gateway must be running to receive events (ector gateway run).\n")


def _cmd_list(args):
    from rich.console import Console

    from ector_cli.list_format import LIST_PRIMARY, ListColumn, render_list_page

    subs = _load_subscriptions()
    console = Console()

    if not subs:
        render_list_page(
            console,
            title="Webhooks dinâmicos",
            sections=[],
            empty_message="Nenhuma inscrição dinâmica.",
            empty_hint="[dim]Crie com[/] [bold]ector webhook subscribe <nome>[/]",
            primary=LIST_PRIMARY,
        )
        return

    base_url = _get_webhook_base_url()
    rows = []
    for name, route in subs.items():
        events = ", ".join(route.get("events", [])) or "(todos)"
        deliver = route.get("deliver", "log")
        if route.get("deliver_only"):
            deliver = f"{deliver} (direto)"
        desc = route.get("description", "") or "—"
        rows.append((name, desc, f"{base_url}/webhooks/{name}", events, deliver))

    render_list_page(
        console,
        title="Webhooks dinâmicos",
        sections=[
            (
                "Inscrições",
                (
                    ListColumn("Nome", style=f"bold {LIST_PRIMARY}", min_width=14, ratio=1),
                    ListColumn("Descrição", overflow="fold", ratio=2),
                    ListColumn("URL", style="dim", overflow="fold", ratio=3),
                    ListColumn("Eventos", overflow="fold", ratio=2),
                    ListColumn("Entrega", style="dim", no_wrap=True, ratio=1),
                ),
                rows,
            )
        ],
        summary=f"[dim]{len(rows)} inscrição(ões)[/]",
        primary=LIST_PRIMARY,
    )


def _cmd_remove(args):
    name = args.name.strip().lower()
    subs = _load_subscriptions()

    if name not in subs:
        print(f"  No subscription named '{name}'.")
        print("  Note: Static routes from config.yaml cannot be removed here.")
        return

    del subs[name]
    _save_subscriptions(subs)
    print(f"  Removed webhook subscription: {name}")


def _cmd_test(args):
    """Send a test POST to a webhook route."""
    name = args.name.strip().lower()
    subs = _load_subscriptions()

    if name not in subs:
        print(f"  No subscription named '{name}'.")
        return

    route = subs[name]
    secret = route.get("secret", "")
    base_url = _get_webhook_base_url()
    url = f"{base_url}/webhooks/{name}"

    payload = args.payload or '{"test": true, "event_type": "test", "message": "Hello from ector webhook test"}'

    import hmac
    import hashlib
    sig = "sha256=" + hmac.new(
        secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    print(f"  Sending test POST to {url}")
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            data=payload.encode(),
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "test",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            print(f"  Response ({resp.status}): {body}")
    except Exception as e:
        print(f"  Error: {e}")
        print("  Is the gateway running? (ector gateway run)")
