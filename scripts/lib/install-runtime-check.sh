#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Sourceable: valida árvore mínima de runtime e instala deps do TUI (pnpm/npm).
#
#   source scripts/lib/install-runtime-check.sh
#   verify_ector_install_tree "$INSTALL_DIR" || exit 1
#   install_ector_tui_deps "$INSTALL_DIR"
# ----------------------------------------------------------------------------

_IO_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install-output.sh"
if [ -f "$_IO_LIB" ]; then
    # shellcheck source=scripts/lib/install-output.sh
    source "$_IO_LIB"
fi

# Ficheiros que têm de existir após clone do release (export incompleto quebra o agente).
_ECTOR_INSTALL_REQUIRED=(
    "tools/environments/__init__.py"
    "frontend/tui/packages/ector-tui/package.json"
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

_tui_can_build_from_source() {
    local tui_dir="$1"
    [ -f "$tui_dir/packages/ector-tui/scripts/bundle.mjs" ] && [ -d "$tui_dir/src" ]
}

_tui_prebuilt_release_ready() {
    local tui_dir="$1"
    [ -f "$tui_dir/dist/entry.js" ] || return 1
    [ -f "$tui_dir/packages/ector-tui/dist/tui-bundle.js" ] || return 1
    if _tui_can_build_from_source "$tui_dir"; then
        return 1
    fi
    return 0
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
    local missing=()
    local tui_dir="$root/frontend/tui"
    local dashboard_dir="$root/frontend/dashboard"

    if [ -d "$tui_dir" ] && ! _tui_can_build_from_source "$tui_dir"; then
        if [ ! -f "$tui_dir/dist/entry.js" ]; then
            missing+=("frontend/tui/dist/entry.js")
        fi
        if [ ! -f "$tui_dir/packages/ector-tui/dist/tui-bundle.js" ]; then
            missing+=("frontend/tui/packages/ector-tui/dist/tui-bundle.js")
        fi
    fi

    if [ -d "$dashboard_dir" ] && ! _web_can_build_from_source "$dashboard_dir"; then
        if [ ! -f "$root/ector_cli/web_dist/index.html" ]; then
            missing+=("ector_cli/web_dist/index.html")
        fi
    fi

    if [ "${#missing[@]}" -eq 0 ]; then
        return 0
    fi

    return 1
}

warn_missing_ui_prebuild() {
    local root="${1:?install root}"

    if verify_ector_ui_prebuild "$root"; then
        return 0
    fi

    if declare -F _install_step_warn >/dev/null 2>&1; then
        _install_step_warn "Interface web/chat incompleta — atualize o release público"
    else
        _ir_warn "Interface web/chat incompleta — atualize o release público"
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
    local tui_dir="$root/frontend/tui"
    local dashboard_dir="$root/frontend/dashboard"
    if [ -d "$tui_dir" ] && ! _tui_can_build_from_source "$tui_dir"; then
        [ -f "$tui_dir/dist/entry.js" ] || printf '  - %s\n' "frontend/tui/dist/entry.js" >&2
        [ -f "$tui_dir/packages/ector-tui/dist/tui-bundle.js" ] || printf '  - %s\n' "frontend/tui/packages/ector-tui/dist/tui-bundle.js" >&2
    fi
    if [ -d "$dashboard_dir" ] && ! _web_can_build_from_source "$dashboard_dir"; then
        [ -f "$root/ector_cli/web_dist/index.html" ] || printf '  - %s\n' "ector_cli/web_dist/index.html" >&2
    fi
    _ir_err "O pacote clonado (ector-agent-release) está incompleto."
    _ir_err "Publique um release corrigido (sync_public_release) ou instale a partir do repo completo: ./install.sh"
    return 1
}

_ir_write_pnpm_esbuild_allowlist() {
    local tui_dir="$1"
    local npmrc="$tui_dir/.npmrc"
    touch "$npmrc"
    if ! grep -qE 'only-built-dependencies|onlyBuiltDependencies' "$npmrc" 2>/dev/null; then
        {
            echo '# Ector: allow esbuild postinstall (pnpm 10 blocks lifecycle scripts by default)'
            echo 'only-built-dependencies[]=esbuild'
        } >>"$npmrc"
    fi

    local ws="$tui_dir/pnpm-workspace.yaml"
    if [ ! -f "$ws" ] || ! grep -qE '^packages:' "$ws" 2>/dev/null || ! grep -qE 'allowBuilds|esbuild' "$ws" 2>/dev/null; then
        cat >"$ws" <<'EOF'
packages:
  - .

# Ector: allow esbuild lifecycle scripts (pnpm 11+ strictDepBuilds)
allowBuilds:
  esbuild: true
EOF
    fi

    if command -v pnpm >/dev/null 2>&1; then
        (
            cd "$tui_dir"
            export CI="${CI:-true}"
            export PNPM_CONFIG_CONFIRM_MODULES_PURGE="${PNPM_CONFIG_CONFIRM_MODULES_PURGE:-false}"
            pnpm approve-builds esbuild >/dev/null 2>&1 || true
        )
    fi
}

_ir_tui_node_modules_ready() {
    local tui_dir="$1"
    if [ ! -d "$tui_dir/node_modules" ]; then
        return 1
    fi
    if [ -f "$tui_dir/node_modules/@ector/ink/package.json" ]; then
        return 0
    fi
    if compgen -G "$tui_dir/node_modules/.pnpm/@ector+ink@*/node_modules/@ector/ink/package.json" >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

_ir_pnpm_install_tui() {
    local tui_dir="$1"
    _ir_write_pnpm_esbuild_allowlist "$tui_dir"
    cd "$tui_dir"
    export CI="${CI:-true}"
    export PNPM_CONFIG_CONFIRM_MODULES_PURGE="${PNPM_CONFIG_CONFIRM_MODULES_PURGE:-false}"

    local rc=0
    if pnpm install --frozen-lockfile --config.only-built-dependencies[]=esbuild; then
        rc=0
    else
        rc=$?
        if _ir_tui_node_modules_ready "$tui_dir"; then
            rc=0
        else
            pnpm install --config.only-built-dependencies[]=esbuild || rc=$?
        fi
    fi

    if _ir_tui_node_modules_ready "$tui_dir"; then
        pnpm rebuild esbuild --config.only-built-dependencies[]=esbuild >/dev/null 2>&1 || true
        return 0
    fi
    return "${rc:-1}"
}

_ir_ensure_pnpm() {
    command -v pnpm >/dev/null 2>&1 && return 0

    if command -v corepack >/dev/null 2>&1; then
        corepack enable >/dev/null 2>&1 || true
        if corepack prepare pnpm@latest --activate >/dev/null 2>&1 && command -v pnpm >/dev/null 2>&1; then
            return 0
        fi
    fi

    if command -v npm >/dev/null 2>&1; then
        npm install -g pnpm >/dev/null 2>&1 && command -v pnpm >/dev/null 2>&1 && return 0
    fi

    return 1
}

install_ector_tui_deps() {
    local root="${1:?install root}"
    local tui_dir="$root/frontend/tui"

    if [ ! -f "$tui_dir/package.json" ]; then
        return 0
    fi

    if [ ! -f "$tui_dir/packages/ector-tui/package.json" ]; then
        _ir_err "Pacote @ector/ink ausente em frontend/tui/packages/ector-tui/"
        return 1
    fi

    if _tui_prebuilt_release_ready "$tui_dir"; then
        _ir_ok "Chat no terminal (já incluído no release)"
        return 0
    fi

    _ir_ensure_pnpm || true

    if command -v pnpm >/dev/null 2>&1 && [ -f "$tui_dir/pnpm-lock.yaml" ]; then
        if declare -F _install_step >/dev/null 2>&1; then
            _install_step "Chat no terminal: dependências" _ir_pnpm_install_tui "$tui_dir" || return 1
        else
            _ir_pnpm_install_tui "$tui_dir" || return 1
            _ir_ok "Chat no terminal: dependências"
        fi
    elif command -v npm >/dev/null 2>&1; then
        if declare -F _install_step >/dev/null 2>&1; then
            _install_step "Chat no terminal: dependências" bash -c \
                "cd \"$(printf '%q' "$tui_dir")\" && npm install --no-fund --no-audit --progress=false" \
                || return 1
        else
            (cd "$tui_dir" && npm install --no-fund --no-audit --progress=false) || return 1
            _ir_ok "Chat no terminal: dependências"
        fi
    else
        _install_step_warn "Chat no terminal: npm/pnpm indisponível"
        return 1
    fi
    return 0
}

build_ector_tui() {
    local root="${1:?install root}"
    local tui_dir="$root/frontend/tui"

    if [ ! -f "$tui_dir/package.json" ]; then
        return 0
    fi

    if [ ! -d "$tui_dir/node_modules" ]; then
        _install_step_warn "Chat no terminal: dependências ausentes"
        return 1
    fi

    if _tui_prebuilt_release_ready "$tui_dir"; then
        return 0
    fi

    _ir_tui_build_cmd() {
        cd "$tui_dir"
        export CI="${CI:-true}"
        if command -v pnpm >/dev/null 2>&1; then
            pnpm run build
        elif command -v npm >/dev/null 2>&1; then
            npm run build
        else
            return 1
        fi
    }

    if declare -F _install_step >/dev/null 2>&1; then
        _install_step "Chat no terminal" _ir_tui_build_cmd || return 1
    else
        _ir_tui_build_cmd || return 1
        _ir_ok "Chat no terminal"
    fi

    if [ ! -f "$tui_dir/dist/entry.js" ]; then
        _install_step_warn "Chat no terminal: build incompleto"
        return 1
    fi
    return 0
}

sync_ector_tui_ink_to_pnpm_store() {
    local tui_dir="${1:?tui dir}"
    local src_bundle="$tui_dir/packages/ector-tui/dist/tui-bundle.js"
    if [ ! -f "$src_bundle" ]; then
        return 0
    fi
    local pnpm_root="$tui_dir/node_modules/.pnpm"
    if [ ! -d "$pnpm_root" ]; then
        return 0
    fi
    local d target_dir target_bundle
    for d in "$pnpm_root"/@ector+ink@*/node_modules/@ector/ink; do
        [ -d "$d" ] || continue
        target_dir="$d/dist"
        mkdir -p "$target_dir" 2>/dev/null || continue
        target_bundle="$target_dir/tui-bundle.js"
        rm -f "$target_bundle" 2>/dev/null || true
        if ! ln "$src_bundle" "$target_bundle" 2>/dev/null; then
            cp -f "$src_bundle" "$target_bundle" 2>/dev/null || true
        fi
    done
}

restore_ector_tui_prebuild_from_git() {
    local root="${1:?install root}"
    local tui_dir="$root/frontend/tui"

    [ -d "$tui_dir" ] || return 0
    if _tui_can_build_from_source "$tui_dir"; then
        return 0
    fi
    if _tui_prebuilt_release_ready "$tui_dir"; then
        return 0
    fi
    if [ ! -d "$root/.git" ]; then
        return 0
    fi

    (
        cd "$root" || exit 0
        git checkout HEAD -- \
            frontend/tui/dist/entry.js \
            frontend/tui/packages/ector-tui/dist/tui-bundle.js \
            2>/dev/null
    ) || true
}

finalize_ector_tui_after_update() {
    local root="${1:?install root}"
    local tui_dir="$root/frontend/tui"

    [ -f "$tui_dir/package.json" ] || return 0
    restore_ector_tui_prebuild_from_git "$root"

    if _tui_can_build_from_source "$tui_dir"; then
        sync_ector_tui_ink_to_pnpm_store "$tui_dir"
        return 0
    fi
    if ! _tui_prebuilt_release_ready "$tui_dir"; then
        return 1
    fi
    if ! _ir_tui_node_modules_ready "$tui_dir"; then
        _ir_ensure_pnpm || return 1
        _ir_pnpm_install_tui "$tui_dir" || return 1
    fi
    sync_ector_tui_ink_to_pnpm_store "$tui_dir"
    return 0
}

install_ector_bun() {
    local root="${1:?install root}"
    local helper="$root/scripts/lib/bun-bootstrap.sh"

    if [ ! -f "$helper" ]; then
        _install_step_warn "Runtime Bun (instalador ausente)"
        return 1
    fi

    export ECTOR_INSTALL_COMPACT=1
    # shellcheck source=scripts/lib/bun-bootstrap.sh
    source "$helper"
    if ensure_bun; then
        _ir_ok "Runtime Bun (chat no terminal)"
        return 0
    fi
    _install_step_warn "Runtime Bun (necessário para ector chat)"
    return 1
}
