#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Sourceable: valida árvore mínima de runtime (dashboard web pré-compilado).
#
#   source scripts/lib/install-runtime-check.sh
#   verify_ector_install_tree "$INSTALL_DIR" || exit 1
# ----------------------------------------------------------------------------

_IO_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install-output.sh"
if [ -f "$_IO_LIB" ]; then
    # shellcheck source=scripts/lib/install-output.sh
    source "$_IO_LIB"
fi

_ECTOR_INSTALL_REQUIRED=(
    "tools/environments/__init__.py"
    "run_agent.py"
)

_ir_log() {
    if declare -F log_info >/dev/null 2>&1; then
        log_info "$@"
    else
        printf '→ %s\n' "$*" >&2
    fi
}

_ir_ok() {
    if declare -F _install_step_ok >/dev/null 2>&1; then
        _install_step_ok "$@"
    elif declare -F log_success >/dev/null 2>&1; then
        log_success "$@"
    else
        printf '✔ %s\n' "$*" >&2
    fi
}

_ir_warn() {
    if declare -F log_warn >/dev/null 2>&1; then
        log_warn "$@"
    else
        printf '▲ %s\n' "$*" >&2
    fi
}

_ir_err() {
    if declare -F log_error >/dev/null 2>&1; then
        log_error "$@"
    else
        printf '✗ %s\n' "$*" >&2
    fi
}

_web_can_build_from_source() {
    local dashboard_dir="$1"
    [ -d "$dashboard_dir/src" ]
}

verify_ector_install_core() {
    local root="${1:?install root}"
    local missing=()
    local rel

    for rel in "${_ECTOR_INSTALL_REQUIRED[@]}"; do
        if [ ! -f "$root/$rel" ]; then
            missing+=("$rel")
        fi
    done

    if [ "${#missing[@]}" -eq 0 ]; then
        return 0
    fi

    _ir_err "Instalação incompleta — faltam ficheiros de runtime:"
    for rel in "${missing[@]}"; do
        printf '  - %s\n' "$rel" >&2
    done
    _ir_err "O pacote clonado (ector-agent-release) está incompleto."
    _ir_err "Publique um release corrigido (sync_public_release) ou instale a partir do repo completo: ./install.sh"
    return 1
}

verify_ector_ui_prebuild() {
    local root="${1:?install root}"
    local dashboard_dir="$root/frontend/dashboard"

    if [ -d "$dashboard_dir" ] && ! _web_can_build_from_source "$dashboard_dir"; then
        if [ ! -f "$root/ector_cli/web_dist/index.html" ]; then
            return 1
        fi
    fi
    return 0
}

warn_missing_ui_prebuild() {
    local root="${1:?install root}"

    if verify_ector_ui_prebuild "$root"; then
        return 0
    fi

    if declare -F _install_step_warn >/dev/null 2>&1; then
        _install_step_warn "Interface web incompleta — atualize o release público"
    else
        _ir_warn "Interface web incompleta — atualize o release público"
    fi
    return 0
}

verify_ector_install_tree() {
    local root="${1:?install root}"
    verify_ector_install_core "$root" || return 1
    if verify_ector_ui_prebuild "$root"; then
        return 0
    fi
    _ir_err "Instalação incompleta — faltam ficheiros de runtime:"
    printf '  - %s\n' "ector_cli/web_dist/index.html" >&2
    _ir_err "O pacote clonado (ector-agent-release) está incompleto."
    _ir_err "Publique um release corrigido (sync_public_release) ou instale a partir do repo completo: ./install.sh"
    return 1
}

# Legacy no-ops (install scripts may still call these after TUI removal).
install_ector_tui_deps() { return 0; }
build_ector_tui() { return 0; }
install_ector_bun() { return 0; }
finalize_ector_tui_after_update() { return 0; }
