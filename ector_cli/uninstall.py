"""
Ector Agent Uninstaller.

Provides options for:
- Full uninstall: Remove everything including configs and data
- Keep data: Remove code but keep ~/.ector/ (configs, sessions, logs)
"""

import os
import shutil
import subprocess
from pathlib import Path

from ector_constants import get_ector_home

from ector_cli.colors import Colors, color

def log_info(msg: str):
    print(f"{color('→', Colors.CYAN)} {msg}")

def log_success(msg: str):
    print(f"{color('✔', Colors.GREEN)} {msg}")

def log_warn(msg: str):
    print(f"{color('▲', Colors.YELLOW)} {msg}")

def get_project_root() -> Path:
    """Get the project installation directory."""
    return Path(__file__).parent.parent.resolve()


def find_shell_configs() -> list:
    """Find shell configuration files that might have PATH entries."""
    home = Path.home()
    configs = []
    
    candidates = [
        home / ".bashrc",
        home / ".bash_profile",
        home / ".profile",
        home / ".zshrc",
        home / ".zprofile",
    ]
    
    for config in candidates:
        if config.exists():
            configs.append(config)
    
    return configs


def remove_path_from_shell_configs():
    """Remove Ector PATH entries from shell configuration files."""
    configs = find_shell_configs()
    removed_from = []
    
    for config_path in configs:
        try:
            content = config_path.read_text()
            original_content = content
            
            # Remove lines containing ector-agent or ector PATH entries
            new_lines = []
            skip_next = False
            
            for line in content.split('\n'):
                # Skip the "# Ector Agent" comment and following line
                if '# Ector Agent' in line or '# ector-agent' in line:
                    skip_next = True
                    continue
                if skip_next and ('ector' in line.lower() and 'PATH' in line):
                    skip_next = False
                    continue
                skip_next = False
                
                # Remove any PATH line containing ector
                if 'ector' in line.lower() and ('PATH=' in line or 'path=' in line.lower()):
                    continue
                    
                new_lines.append(line)
            
            new_content = '\n'.join(new_lines)
            
            # Clean up multiple blank lines
            while '\n\n\n' in new_content:
                new_content = new_content.replace('\n\n\n', '\n\n')
            
            if new_content != original_content:
                config_path.write_text(new_content)
                removed_from.append(config_path)
                
        except Exception as e:
            log_warn(f"Could not update {config_path}: {e}")
    
    return removed_from


def remove_wrapper_script():
    """Remove the ector wrapper script if it exists."""
    wrapper_paths = [
        Path.home() / ".local" / "bin" / "ector",
        Path("/usr/local/bin/ector"),
    ]
    
    removed = []
    for wrapper in wrapper_paths:
        if wrapper.exists():
            try:
                # Check if it's our wrapper (contains ector_cli reference)
                content = wrapper.read_text()
                if 'ector_cli' in content or 'ector-agent' in content:
                    wrapper.unlink()
                    removed.append(wrapper)
            except Exception as e:
                log_warn(f"Could not remove {wrapper}: {e}")
    
    return removed


def uninstall_gateway_service():
    """Stop and uninstall the gateway service (systemd, launchd) and kill any
    standalone gateway processes.

    Delegates to the gateway module which handles:
    - Linux: user + system systemd services (with proper DBUS env setup)
    - macOS: launchd plists
    - All platforms: standalone ``ector gateway run`` processes
    - Termux/Android: skips systemd (no systemd on Android), still kills standalone processes
    """
    import platform
    stopped_something = False

    # 1. Kill any standalone gateway processes (all platforms, including Termux)
    try:
        from ector_cli.gateway import kill_gateway_processes, find_gateway_pids
        pids = find_gateway_pids()
        if pids:
            killed = kill_gateway_processes()
            if killed:
                log_success(f"Killed {killed} running gateway process(es)")
                stopped_something = True
    except Exception as e:
        log_warn(f"Could not check for gateway processes: {e}")

    system = platform.system()

    # Termux/Android has no systemd and no launchd — nothing left to do.
    prefix = os.getenv("PREFIX", "")
    is_termux = bool(os.getenv("TERMUX_VERSION") or "com.termux/files/usr" in prefix)
    if is_termux:
        return stopped_something

    # 2. Linux: uninstall systemd services (both user and system scopes)
    if system == "Linux":
        try:
            from ector_cli.gateway import (
                get_systemd_unit_path,
                get_service_name,
                _systemctl_cmd,
            )
            svc_name = get_service_name()

            for is_system in (False, True):
                unit_path = get_systemd_unit_path(system=is_system)
                if not unit_path.exists():
                    continue

                scope = "system" if is_system else "user"
                try:
                    if is_system and os.geteuid() != 0:
                        log_warn(f"System gateway service exists at {unit_path} "
                                 f"but needs sudo to remove")
                        continue

                    cmd = _systemctl_cmd(is_system)
                    subprocess.run(cmd + ["stop", svc_name],
                                   capture_output=True, check=False)
                    subprocess.run(cmd + ["disable", svc_name],
                                   capture_output=True, check=False)
                    unit_path.unlink()
                    subprocess.run(cmd + ["daemon-reload"],
                                   capture_output=True, check=False)
                    log_success(f"Removed {scope} gateway service ({unit_path})")
                    stopped_something = True
                except Exception as e:
                    log_warn(f"Could not remove {scope} gateway service: {e}")
        except Exception as e:
            log_warn(f"Could not check systemd gateway services: {e}")

    # 3. macOS: uninstall launchd plist
    elif system == "Darwin":
        try:
            from ector_cli.gateway import get_launchd_plist_path
            plist_path = get_launchd_plist_path()
            if plist_path.exists():
                subprocess.run(["launchctl", "unload", str(plist_path)],
                               capture_output=True, check=False)
                plist_path.unlink()
                log_success(f"Removed macOS gateway service ({plist_path})")
                stopped_something = True
        except Exception as e:
            log_warn(f"Could not remove launchd gateway service: {e}")

    return stopped_something


def _is_default_ector_home(ector_home: Path) -> bool:
    """Return True when ``ector_home`` points at the default (non-profile) root."""
    try:
        from ector_constants import get_default_ector_root
        return ector_home.resolve() == get_default_ector_root().resolve()
    except Exception:
        return False


def _discover_named_profiles():
    """Return a list of ``ProfileInfo`` for every non-default profile, or ``[]``
    if profile support is unavailable or nothing is installed beyond the
    default root."""
    try:
        from ector_cli.profiles import list_profiles
    except Exception:
        return []
    try:
        return [p for p in list_profiles() if not getattr(p, "is_default", False)]
    except Exception as e:
        log_warn(f"Could not enumerate profiles: {e}")
        return []


def _uninstall_profile(profile) -> None:
    """Fully uninstall a single named profile: stop its gateway service,
    remove its alias wrapper, and wipe its ECTOR_HOME directory.

    We shell out to ``ector -p <name> gateway stop|uninstall`` because
    service names, unit paths, and plist paths are all derived from the
    current ECTOR_HOME and can't be easily switched in-process.
    """
    import sys as _sys
    name = profile.name
    profile_home = profile.path

    log_info(f"Desinstalando perfil '{name}'...")

    # 1. Stop and remove this profile's gateway service.
    #    Use `python -m ector_cli.main` so we don't depend on a `ector`
    #    wrapper that may be half-removed mid-uninstall.
    ector_invocation = [_sys.executable, "-m", "ector_cli.main", "--profile", name]
    for subcmd in ("stop", "uninstall"):
        try:
            subprocess.run(
                ector_invocation + ["gateway", subcmd],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            log_warn(f"  O encerramento do gateway expirou para '{name}'")
        except Exception as e:
            log_warn(f"  Não foi possível executar gateway {subcmd} para '{name}': {e}")

    # 2. Remove the wrapper alias script at ~/.local/bin/<name> (if any).
    alias_path = getattr(profile, "alias_path", None)
    if alias_path and alias_path.exists():
        try:
            alias_path.unlink()
            log_success(f"  Alias removido: {alias_path}")
        except Exception as e:
            log_warn(f"  Não foi possível remover o alias {alias_path}: {e}")

    # 3. Wipe the profile's ECTOR_HOME directory.
    try:
        if profile_home.exists():
            shutil.rmtree(profile_home)
            log_success(f"  Removido {profile_home}")
    except Exception as e:
        log_warn(f"  Não foi possível remover {profile_home}: {e}")


def run_uninstall(args):
    """
    Run the uninstall process.
    
    Options:
    - Full uninstall: removes code + ~/.ector/ (configs, data, logs)
    - Keep data: removes code but keeps ~/.ector/ for future reinstall
    """
    project_root = get_project_root()
    ector_home = get_ector_home()

    # Detect named profiles when uninstalling from the default root —
    # offer to clean them up too instead of leaving zombie ECTOR_HOMEs
    # and systemd units behind.
    is_default_profile = _is_default_ector_home(ector_home)
    named_profiles = _discover_named_profiles() if is_default_profile else []

       
    # Pede confirmação
    print()
    print(color("Desinstalação do Ector Agent", Colors.CYAN, Colors.BOLD))
    print()
    print(color("Escolha como deseja desinstalar", Colors.CYAN, Colors.BOLD))
    print(color("────────────────────────────────────────────────────────", Colors.DIM))
    print()
    print("  " + color("[1]", Colors.GREEN, Colors.BOLD) + " " + color("Manter meus dados", Colors.GREEN, Colors.BOLD))
    print("      Remover apenas o agente")
    print("      " + color("✓ Recomendado:", Colors.GREEN) + color(" preserva configs, sessões e logs", Colors.DIM))
    print()
    print("  " + color("[2]", Colors.RED, Colors.BOLD) + " " + color("Desinstalação completa", Colors.RED, Colors.BOLD))
    print("      Remover agente e todos os dados")
    print("      " + color("▲ Atenção:", Colors.RED) + color(" apaga permanentemente configs, sessões e logs", Colors.DIM))
    print()
    print("  " + color("[3]", Colors.CYAN, Colors.BOLD) + " " + color("Cancelar", Colors.CYAN, Colors.BOLD))
    print("      Sair sem desinstalar")
    print()
    
    try:
        choice = input(color("→ Selecione [1/2/3] (padrão: 3): ", Colors.BOLD)).strip()
    except (KeyboardInterrupt, EOFError):
        print()
        print("Cancelado.")
        return

    if not choice:
        choice = "3"
    
    if choice == "3" or choice.lower() in ("c", "cancel", "cancelar", "q", "quit", "sair", "n", "no", "não"):
        print()
        print("Desinstalação cancelada.")
        return
    
    full_uninstall = (choice == "2")

    # When doing a full uninstall from the default profile, also offer to
    # remove any named profiles — stopping their gateway services, unlinking
    # their alias wrappers, and wiping their ECTOR_HOME dirs. Otherwise
    # those leave zombie services and data behind.
    remove_profiles = False
    if full_uninstall and named_profiles:
        print()
        print(color("Outros perfis NÃO serão removidos por padrão.", Colors.YELLOW))
        print(f"Encontrado(s) {len(named_profiles)} perfil(is) nomeado(s): " +
              ", ".join(p.name for p in named_profiles))
        print()
        try:
            resp = input(color(
                f"Também deseja parar e remover estes {len(named_profiles)} perfil(is)? (s/n): ",
                Colors.BOLD
            )).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            print("Cancelado.")
            return
        remove_profiles = resp in ("s", "sim", "y", "yes")

    # Confirmação final
    print()
    if full_uninstall:
        print(color("▲  AVISO: Isso excluirá permanentemente TODOS os dados do Ector!", Colors.RED, Colors.BOLD))
        print(color("   Incluindo: configs, chaves de API, sessões, tarefas agendadas, logs", Colors.RED))
        if remove_profiles:
            print(color(
                f"   Mais {len(named_profiles)} perfil(is): " +
                ", ".join(p.name for p in named_profiles),
                Colors.RED
            ))
    else:
        print("Isso removerá o código do Ector, mas manterá sua configuração e dados.")
    
    print()
    try:
        confirm = input(f"Digite '{color('sim', Colors.YELLOW)}' para confirmar: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        print("Cancelado.")
        return
    
    if confirm not in ("sim", "yes"):
        print()
        print("Desinstalação cancelada.")
        return
    
    print()
    print(color("Desinstalando...", Colors.CYAN, Colors.BOLD))
    print()
    
    # 1. Para e desinstala serviço de gateway + mata processos independentes
    log_info("Verificando se o gateway está em execução...")
    if not uninstall_gateway_service():
        log_info("Nenhum serviço ou processo de gateway encontrado")
    
    # 2. Remove entradas de PATH das configs do shell
    log_info("Removendo entradas de PATH das configurações do shell...")
    removed_configs = remove_path_from_shell_configs()
    if removed_configs:
        for config in removed_configs:
            log_success(f"Atualizado {config}")
    else:
        log_info("Nenhuma entrada de PATH encontrada para remover")
    
    # 3. Remove script wrapper
    log_info("Removendo comando ector...")
    removed_wrappers = remove_wrapper_script()
    if removed_wrappers:
        for wrapper in removed_wrappers:
            log_success(f"Removido {wrapper}")
    else:
        log_info("Nenhum script wrapper encontrado")
    
    # 4. Remove diretório de instalação (código)
    log_info("Removendo diretório de instalação...")
    
    # Verifica se estamos rodando de dentro do diretório de instalação
    try:
        if project_root.exists():
            # Se a instalação estiver dentro de ~/.ector/, remove apenas a subpasta ector-agent
            if ector_home in project_root.parents or project_root.parent == ector_home:
                shutil.rmtree(project_root)
                log_success(f"Removido {project_root}")
            else:
                # Instalação está em outro lugar
                shutil.rmtree(project_root)
                log_success(f"Removido {project_root}")
    except Exception as e:
        log_warn(f"Não foi possível remover completamente {project_root}: {e}")
        log_info("Você pode precisar removê-lo manualmente")
    
    # 5. Opcionalmente remove diretório de dados ~/.ector/ (e perfis nomeados)
    if full_uninstall:
        # 5a. Para e remove o serviço de gateway e o wrapper de alias de cada perfil.
        if remove_profiles and named_profiles:
            for prof in named_profiles:
                _uninstall_profile(prof)

        log_info("Removendo configuração e dados...")
        try:
            if ector_home.exists():
                shutil.rmtree(ector_home)
                log_success(f"Removido {ector_home}")
        except Exception as e:
            log_warn(f"Não foi possível remover completamente {ector_home}: {e}")
            log_info("Você pode precisar removê-lo manualmente")
    else:
        log_info(f"Mantendo configuração e dados em {ector_home}")
    
    # Concluído
    print()
    print(color("Desinstalação do Ector Agent concluída", Colors.GREEN, Colors.BOLD))
    print()
    
    if not full_uninstall:
        print(color("Sua configuração e dados foram preservados:", Colors.CYAN))
        print(f"  {ector_home}/")
        print()
        print("Para reinstalar mais tarde com suas configurações existentes:")
        print(color("  curl -fsSL https://ector.cc/install.sh | bash", Colors.DIM))
        print()
    
    print(color("Recarregue seu shell para concluir o processo:", Colors.YELLOW))
    print("  source ~/.bashrc  # ou ~/.zshrc")
    print()
    print("Obrigado por usar o Ector Agent!")
    print()
