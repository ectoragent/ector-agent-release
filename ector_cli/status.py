"""
Status command for ector CLI.

Shows the status of all Ector Agent components.
"""

import os
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

from ector_cli.colors import Colors, color
from ector_cli.config import get_env_path, get_env_value, get_ector_home, load_config
from ector_cli.models import provider_label
from ector_constants import OPENROUTER_MODELS_URL
def check_mark(ok: bool) -> str:
    if ok:
        return color("✔", Colors.GREEN)
    return color("✖", Colors.RED)

def redact_key(key: str) -> str:
    """Redact an API key for display."""
    if not key:
        return "(não definido)"
    if len(key) < 12:
        return "***"
    return key[:4] + "..." + key[-4:]


def _format_iso_timestamp(value) -> str:
    """Format ISO timestamps for status output, converting to local timezone."""
    if not value or not isinstance(value, str):
        return "(desconhecido)"
    from datetime import datetime, timezone
    text = value.strip()
    if not text:
        return "(desconhecido)"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return value
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _configured_model_label(config: dict) -> str:
    """Return the configured default model from config.yaml."""
    model_cfg = config.get("model")
    if isinstance(model_cfg, dict):
        model = (model_cfg.get("default") or model_cfg.get("name") or "").strip()
    elif isinstance(model_cfg, str):
        model = model_cfg.strip()
    else:
        model = ""
    return model or "(não definido)"


def _effective_provider_label() -> str:
    """Return the provider label matching current CLI runtime resolution."""
    from ector_cli.models import resolve_display_provider_id

    try:
        config = load_config()
    except Exception:
        config = {}
    effective = resolve_display_provider_id(config)
    if effective:
        return provider_label(effective)
    return provider_label("auto")


from ector_constants import is_termux as _is_termux


def show_status(args):
    """Show status of all Ector Agent components."""
    show_all = getattr(args, 'all', False)
    deep = getattr(args, 'deep', False)
    
    print()
    print(color("┌─────────────────────────────────────────────────────────┐", Colors.CYAN))
    print(color("│                     Status do Ector                     │", Colors.CYAN))
    print(color("└─────────────────────────────────────────────────────────┘", Colors.CYAN))
    
    # =========================================================================
    # Environment
    # =========================================================================
    print()
    print(color("◆ Ambiente", Colors.CYAN, Colors.BOLD))
    print(f"  Projeto:      {PROJECT_ROOT}")
    print(f"  Python:       {sys.version.split()[0]}")
    
    env_path = get_env_path()
    print(f"  Arquivo .env: {check_mark(env_path.exists())} {'existe' if env_path.exists() else 'não encontrado'}")

    try:
        config = load_config()
    except Exception:
        config = {}

    print(f"  Modelo:       {_configured_model_label(config)}")
    print(f"  Provedor:     {_effective_provider_label()}")
    
    # =========================================================================
    # API Keys
    # =========================================================================
    print()
    print(color("◆ Chaves API", Colors.CYAN, Colors.BOLD))
    
    keys = {
        "OpenRouter": "OPENROUTER_API_KEY",
        "OpenAI": "OPENAI_API_KEY",
        "Z.AI/GLM": ("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY", "ZHIPU_API_KEY"),
        "Kimi": "KIMI_API_KEY",
        "StepFun Step Plan": "STEPFUN_API_KEY",
        "MiniMax": "MINIMAX_API_KEY",
        "MiniMax-CN": "MINIMAX_CN_API_KEY",
        "Firecrawl": "FIRECRAWL_API_KEY",
        "Tavily": "TAVILY_API_KEY",
        "Browser Use": "BROWSER_USE_API_KEY",  # Optional — local browser works without this
        "Browserbase": "BROWSERBASE_API_KEY",  # Optional — direct credentials only
        "FAL": "FAL_KEY",
        "Tinker": "TINKER_API_KEY",
        "WandB": "WANDB_API_KEY",
        "ElevenLabs": "ELEVENLABS_API_KEY",
        "GitHub": "GITHUB_TOKEN",
    }
    
    for name, env_var in keys.items():
        env_var_names = (env_var,) if isinstance(env_var, str) else env_var
        value = ""
        for var_name in env_var_names:
            value = get_env_value(var_name) or ""
            if value:
                break
        has_key = bool(value)
        display = redact_key(value) if not show_all else value
        print(f"  {name:<12}  {check_mark(has_key)} {display}")

    from ector_cli.auth import get_anthropic_key
    anthropic_value = get_anthropic_key()
    anthropic_display = redact_key(anthropic_value) if not show_all else anthropic_value
    print(f"  {'Anthropic':<12}  {check_mark(bool(anthropic_value))} {anthropic_display}")

    # =========================================================================
    # Auth Providers (OAuth)
    # =========================================================================
    print()
    print(color("◆ Provedores de Autenticação", Colors.CYAN, Colors.BOLD))

    try:
        from ector_cli import identity_auth
        from ector_cli.auth import get_codex_auth_status, get_qwen_auth_status

        identity_logged_in = identity_auth.is_logged_in()
        identity_base = identity_auth.get_auth_base_url()
        identity_email = ""
        if identity_logged_in:
            try:
                me = identity_auth.whoami()
                identity_email = (me or {}).get("email", "")
            except Exception:
                pass
        codex_status = get_codex_auth_status()
        qwen_status = get_qwen_auth_status()
    except Exception:
        identity_logged_in = False
        identity_base = "https://ector.cc"
        identity_email = ""
        codex_status = {}
        qwen_status = {}

    identity_label = "logado" if identity_logged_in else "não logado (execute: ector login)"
    print(
        f"  {'Identidade':<12}  {check_mark(identity_logged_in)} "
        f"{identity_label}"
    )
    print(f"    API:           {identity_base}")
    if identity_email:
        print(f"    Email:         {identity_email}")

    codex_logged_in = bool(codex_status.get("logged_in"))
    print(
        f"  {'OpenAI Codex':<12}  {check_mark(codex_logged_in)} "
        f"{'logado' if codex_logged_in else 'não logado (execute: ector provider)'}"
    )
    codex_auth_file = codex_status.get("auth_store")
    if codex_auth_file:
        print(f"    Arq. auth:  {codex_auth_file}")
    codex_last_refresh = _format_iso_timestamp(codex_status.get("last_refresh"))
    if codex_status.get("last_refresh"):
        print(f"    Atualizado: {codex_last_refresh}")
    if codex_status.get("error") and not codex_logged_in:
        print(f"    Erro:       {codex_status.get('error')}")

    qwen_logged_in = bool(qwen_status.get("logged_in"))
    print(
        f"  {'Qwen OAuth':<12}  {check_mark(qwen_logged_in)} "
        f"{'logado' if qwen_logged_in else 'não logado (execute: qwen auth qwen-oauth)'}"
    )
    qwen_auth_file = qwen_status.get("auth_file")
    if qwen_auth_file:
        print(f"    Arq. auth:  {qwen_auth_file}")
    qwen_exp = qwen_status.get("expires_at_ms")
    if qwen_exp:
        from datetime import datetime, timezone
        print(f"    Expira acesso: {datetime.fromtimestamp(int(qwen_exp) / 1000, tz=timezone.utc).isoformat()}")
    if qwen_status.get("error") and not qwen_logged_in:
        print(f"    Erro:          {qwen_status.get('error')}")

    # =========================================================================
    # API-Key Providers
    # =========================================================================
    print()
    print(color("◆ Provedores via Chave API", Colors.CYAN, Colors.BOLD))

    apikey_providers = {
        "Z.AI / GLM":       ("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY", "ZHIPU_API_KEY"),
        "Kimi / Moonshot":  ("KIMI_API_KEY",),
        "StepFun Step Plan": ("STEPFUN_API_KEY",),
        "MiniMax":          ("MINIMAX_API_KEY",),
        "MiniMax (China)":  ("MINIMAX_CN_API_KEY",),
    }
    for pname, env_vars in apikey_providers.items():
        key_val = ""
        for ev in env_vars:
            key_val = get_env_value(ev) or ""
            if key_val:
                break
        configured = bool(key_val)
        label = "configurado" if configured else "não configurado (execute: ector provider)"
        print(f"  {pname:<16} {check_mark(configured)} {label}")

    # =========================================================================
    # Terminal Configuration
    # =========================================================================
    print()
    print(color("◆ Backend do Terminal", Colors.CYAN, Colors.BOLD))
    
    terminal_env = os.getenv("TERMINAL_ENV", "")
    if not terminal_env:
        # Fall back to config file value when env var isn't set
        # (ector status doesn't go through cli.py's config loading)
        try:
            _cfg = load_config()
            terminal_env = _cfg.get("terminal", {}).get("backend", "local")
        except Exception:
            terminal_env = "local"
    print(f"  Backend:      {terminal_env}")
    
    if terminal_env == "ssh":
        ssh_host = os.getenv("TERMINAL_SSH_HOST", "")
        ssh_user = os.getenv("TERMINAL_SSH_USER", "")
        print(f"  SSH Host:     {ssh_host or '(not set)'}")
        print(f"  SSH User:     {ssh_user or '(not set)'}")
    elif terminal_env == "docker":
        docker_image = os.getenv("TERMINAL_DOCKER_IMAGE", "python:3.11-slim")
        print(f"  Imagem Docker: {docker_image}")
    elif terminal_env == "daytona":
        daytona_image = os.getenv("TERMINAL_DAYTONA_IMAGE", "nikolaik/python-nodejs:python3.11-nodejs20")
        print(f"  Imagem Daytona: {daytona_image}")
    
    sudo_password = os.getenv("SUDO_PASSWORD", "")
    print(f"  Sudo:         {check_mark(bool(sudo_password))} {'habilitado' if sudo_password else 'desabilitado'}")
    
    # =========================================================================
    # Messaging Platforms
    # =========================================================================
    print()
    print(color("◆ Plataformas de Mensagem", Colors.CYAN, Colors.BOLD))
    
    platforms = {
        "WhatsApp": ("WHATSAPP_ENABLED", "WHATSAPP_HOME_CHANNEL"),
        "Telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_HOME_CHANNEL"),
        "Discord": ("DISCORD_BOT_TOKEN", "DISCORD_HOME_CHANNEL"),
        "Slack": ("SLACK_BOT_TOKEN", "SLACK_HOME_CHANNEL"),
    }

    for name, (token_var, home_var) in platforms.items():
        token = os.getenv(token_var, "")
        if token_var == "WHATSAPP_ENABLED":
            has_token = token.lower() == "true"
        else:
            has_token = bool(token)

        home_channel = os.getenv(home_var, "") if home_var else ""
        
        status = "configurado" if has_token else "não configurado"
        if home_channel:
            status += f" (home: {home_channel})"
        
        print(f"  {name:<12}  {check_mark(has_token)} {status}")
    
    # =========================================================================
    # Gateway Status
    # =========================================================================
    print()
    print(color("◆ Serviço de Gateway", Colors.CYAN, Colors.BOLD))

    try:
        from ector_cli.gateway import get_gateway_runtime_snapshot, _format_gateway_pids

        snapshot = get_gateway_runtime_snapshot()
        is_running = snapshot.running
        print(f"  Status:       {check_mark(is_running)} {'em execução' if is_running else 'parado'}")
        print(f"  Gerenciador:  {snapshot.manager}")
        if snapshot.gateway_pids:
            print(f"  PID(s):       {_format_gateway_pids(snapshot.gateway_pids)}")
        if snapshot.has_process_service_mismatch:
            print("  Serviço:      instalado mas não gerenciando o gateway atual em execução")
        elif _is_termux() and not snapshot.gateway_pids:
            print("  Inicie com:   ector gateway")
            print("  Nota:         o Android pode parar tarefas em segundo plano quando o Termux é suspenso")
        elif snapshot.service_installed and not snapshot.service_running:
            print("  Serviço:      instalado mas parado")
    except Exception:
        if _is_termux():
            print(f"  Status:       {color('desconhecido', Colors.DIM)}")
            print("  Gerenciador:  Termux / processo manual")
        elif sys.platform.startswith('linux'):
            print(f"  Status:       {color('desconhecido', Colors.DIM)}")
            print("  Gerenciador:  systemd/manual")
        elif sys.platform == 'darwin':
            print(f"  Status:       {color('desconhecido', Colors.DIM)}")
            print("  Gerenciador:  launchd")
        else:
            print(f"  Status:       {color('N/A', Colors.DIM)}")
            print("  Gerenciador:  (não suportado nesta plataforma)")
    
    # =========================================================================
    # Cron Jobs
    # =========================================================================
    print()
    print(color("◆ Tarefas Agendadas", Colors.CYAN, Colors.BOLD))
    
    jobs_file = get_ector_home() / "cron" / "jobs.json"
    if jobs_file.exists():
        import json
        try:
            with open(jobs_file, encoding="utf-8") as f:
                data = json.load(f)
                jobs = data.get("jobs", [])
                enabled_jobs = [j for j in jobs if j.get("enabled", True)]
                print(f"  Tarefas:      {len(enabled_jobs)} ativas, {len(jobs)} total")
        except Exception:
            print("  Tarefas:      (erro ao ler arquivo de tarefas)")
    else:
        print("  Tarefas:      0")
    
    # =========================================================================
    # Sessions
    # =========================================================================
    print()
    print(color("◆ Sessions", Colors.CYAN, Colors.BOLD))
    
    sessions_file = get_ector_home() / "sessions" / "sessions.json"
    if sessions_file.exists():
        import json
        try:
            with open(sessions_file, encoding="utf-8") as f:
                data = json.load(f)
                print(f"  Ativas:       {len(data)} sessão(ões)")
        except Exception:
            print("  Ativas:       (erro ao ler arquivo de sessões)")
    else:
        print("  Ativas:       0")
    
    # =========================================================================
    # Deep checks
    # =========================================================================
    if deep:
        print()
        print(color("◆ Testes Profundos", Colors.CYAN, Colors.BOLD))
        
        # Check OpenRouter connectivity
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        if openrouter_key:
            try:
                import httpx
                response = httpx.get(
                    OPENROUTER_MODELS_URL,
                    headers={"Authorization": f"Bearer {openrouter_key}"},
                    timeout=10
                )
                ok = response.status_code == 200
                print(f"  OpenRouter:   {check_mark(ok)} {'alcançável' if ok else f'erro ({response.status_code})'}")
            except Exception as e:
                print(f"  OpenRouter:   {check_mark(False)} erro: {e}")
        
        # Check gateway port
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', 18789))
            sock.close()
            # Port in use = gateway likely running
            port_in_use = result == 0
            # This is informational, not necessarily bad
            print(f"  Porta 18789:  {'em uso' if port_in_use else 'disponível'}")
        except OSError:
            pass
    
    print()
    print(color("─" * 60, Colors.DIM))
    print(color("  Execute 'ector doctor' para diagnósticos detalhados", Colors.DIM))
    print(color("  Execute 'ector setup' para configurar", Colors.DIM))
    print()
