"""
Comando 'reset' para o Ector CLI.

Permite "formatar" o agente, limpando sessões, memórias, logs e o cache
local do perfil do usuário (config.user.*, populado por
``ector_cli.identity_auth`` a partir de ``GET /agent/auth/me``).
"""

import os
import shutil
import logging
from pathlib import Path

from ector_constants import display_ector_home, get_ector_home

from ector_cli.config import save_config_value
from ector_cli.colors import Colors, color
from ector_cli.cli_output import print_success, print_info, print_warning

logger = logging.getLogger(__name__)

_STATE_DB_FILES = (
    "state.db",
    "state.db-wal",
    "state.db-shm",
    "ector_state.db",
    "ector_state.db-wal",
    "ector_state.db-shm",
)


def _remove_sqlite_files(ector_home: Path, names: tuple[str, ...]) -> int:
    """Remove SQLite database paths if present. Returns count removed."""
    removed = 0
    for name in names:
        path = ector_home / name
        if not path.exists():
            continue
        try:
            path.unlink()
            removed += 1
        except Exception as e:
            print_warning(f"Erro ao remover {name}: {e}")
    return removed


def run_reset(args) -> bool:
    """Executa o reset do estado do agente.

    Returns:
        True se o reset foi concluído; False se o utilizador cancelou.
    """
    ector_home = get_ector_home()
    ector_home_display = display_ector_home()

    if not getattr(args, "yes", False):
        print()
        print(f"Atenção! Isso apagará permanentemente os seguintes dados:")
        print()
        
        print("  - Todas as sessões e histórico de chat (state.db + FTS / RAG)")
        print("  - Memória local (vetores, fatos, preferências)")
        print("  - Logs e histórico de erros")
        print("  - Checkpoints e snapshots")
        print("  - Cache de contexto")
        print("  - Cache local do perfil do usuário (config.user.*)")
       
        if getattr(args, "hard", False):
            print(
                color(
                    f"  - [CRÍTICO] Suas configurações (config, .env, skills, plugins, auth, etc.)",
                    Colors.RED, Colors.BOLD,
                )
            )
            print()
        try:
            confirm = input("  Tem certeza que deseja continuar? (s/N): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelado.")
            return False

        if confirm != 's':
            print("Cancelado.")
            return False

    if getattr(args, "hard", False):
        if ector_home.exists():
            try:
                shutil.rmtree(ector_home)
                print_success(
                    f"Pasta {ector_home_display} removida por completo (reset --hard)."
                )
            except Exception as e:
                print_warning(f"Erro ao remover {ector_home}: {e}")
        else:
            print_info(f"{ector_home_display} não existe; nada a remover.")
        print()
        print(color("✔ Agente formatado com sucesso!", Colors.CYAN, Colors.BOLD))
        return True

    # 1. Session store + FTS (RAG sobre histórico usa o mesmo índice em state.db)
    n_state = _remove_sqlite_files(ector_home, _STATE_DB_FILES)
    if n_state:
        print_success(
            f"state.db e arquivos relacionados removidos ({n_state}) — sessões e índice FTS/RAG limpos."
        )

    # 1b. Legado (algumas instalações antigas)
    legacy = ector_home / "sessions.db"
    if legacy.exists():
        try:
            os.remove(legacy)
            print_success("Base de dados legada sessions.db removida.")
        except Exception as e:
            print_warning(f"Erro ao remover sessions.db: {e}")

    # 2. Logs
    logs_dir = ector_home / "logs"
    if logs_dir.exists():
        try:
            shutil.rmtree(logs_dir)
            os.makedirs(logs_dir)
            print_success("Logs limpos.")
        except Exception as e:
            print_warning(f"Erro ao limpar logs: {e}")

    # 3. Context Cache
    cache_dir = ector_home / "context_cache"
    if cache_dir.exists():
        try:
            shutil.rmtree(cache_dir)
            print_success("Cache de contexto limpo.")
        except Exception as e:
            print_warning(f"Erro ao limpar cache: {e}")

    # 4. Persona cache (config.user.*).  The next `ector login` /
    # `ector me` re-fetches it from /agent/auth/me.
    try:
        from ector_cli.identity_auth import USER_PROFILE_CONFIG_KEYS

        for _key in USER_PROFILE_CONFIG_KEYS:
            save_config_value(f"user.{_key}", "")
        print_success("Cache de perfil do usuário (config.user.*) limpo.")
    except Exception as e:
        print_warning(f"Erro ao limpar cache de perfil: {e}")

    # 5. Memory (Local storage for facts and preferences)
    # Check both 'memory' (legacy) and 'memories' (canonical)
    for mdir_name in ["memory", "memories"]:
        memory_dir = ector_home / mdir_name
        if memory_dir.exists():
            try:
                shutil.rmtree(memory_dir)
                print_success(f"Diretório de memória '{mdir_name}' removido.")
            except Exception as e:
                print_warning(f"Erro ao remover memória '{mdir_name}': {e}")

    # 6. Checkpoints
    checkpoints_dir = ector_home / "checkpoints"
    if checkpoints_dir.exists():
        try:
            shutil.rmtree(checkpoints_dir)
            print_success("Checkpoints removidos.")
        except Exception as e:
            print_warning(f"Erro ao remover checkpoints: {e}")
            
    # 7. Snapshots
    snapshots_dir = ector_home / "snapshots"
    if snapshots_dir.exists():
        try:
            shutil.rmtree(snapshots_dir)
            print_success("Snapshots removidos.")
        except Exception as e:
            print_warning(f"Erro ao remover snapshots: {e}")

    # 8. Clear model from config so next `ector` run triggers first-run setup
    try:
        from ector_cli.config import load_config, save_config
        cfg = load_config()
        if isinstance(cfg.get("model"), dict):
            cfg["model"] = {"default": ""}
        else:
            cfg["model"] = ""
        save_config(cfg)
        print_success("Modelo removido da configuração.")
    except Exception as e:
        print_warning(f"Erro ao limpar modelo do config: {e}")

    # 9. Clear provider API keys from .env so first-run guard triggers
    try:
        from ector_cli.auth import PROVIDER_REGISTRY
        _provider_env_vars = {
            "OPENROUTER_API_KEY", "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "OPENAI_BASE_URL",
        }
        for _p in PROVIDER_REGISTRY.values():
            if _p.auth_type == "api_key":
                _provider_env_vars.update(_p.api_key_env_vars)
        from ector_cli.config import save_env_value
        for _var in sorted(_provider_env_vars):
            save_env_value(_var, "")
        print_success("Chaves de API do provedor removidas do .env.")
    except Exception as e:
        print_warning(f"Erro ao limpar chaves do .env: {e}")

    print()
    print(color("✔ Agente formatado com sucesso!", Colors.CYAN, Colors.BOLD))
    print(color("Use 'ector' para começar do zero.", Colors.DIM))
    return True
