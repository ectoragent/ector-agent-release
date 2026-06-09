#!/usr/bin/env bash
# ============================================================================
# scripts/lib/node-bootstrap.sh
# ----------------------------------------------------------------------------
# Sourceable helper: ensure Node.js >= MIN_VERSION is available for the TUI
# (React + Ink), browser tools, and the WhatsApp bridge. After Node is
# resolved, best-effort install/activate pnpm (corepack or npm install -g).
#
# Strategy (first hit wins — respects the user's existing tooling):
#   1. modern `node` already on PATH
#   2. ~/.ector/node/ from a prior Ector-managed install
#   3. fnm, proto, nvm (in that order) if the user already uses a version manager
#   4. Termux `pkg`, macOS Homebrew
#   5. pinned nodejs.org tarball into ~/.ector/node/ (always works, zero shell rc edits)
#
# Usage:
#   source scripts/lib/node-bootstrap.sh
#   ensure_node   # returns 0 on success, non-zero on failure
#   if [ "$ECTOR_NODE_AVAILABLE" = true ]; then ...; fi
#
# Env inputs (set before sourcing to override defaults):
#   ECTOR_NODE_MIN_VERSION   (default: 20)   — accepted on PATH
#   ECTOR_NODE_TARGET_MAJOR  (default: 22)   — installed when we install
#   ECTOR_HOME               (default: $HOME/.ector)
# ============================================================================

ECTOR_NODE_MIN_VERSION="${ECTOR_NODE_MIN_VERSION:-20}"
ECTOR_NODE_TARGET_MAJOR="${ECTOR_NODE_TARGET_MAJOR:-22}"
ECTOR_HOME="${ECTOR_HOME:-$HOME/.ector}"
ECTOR_NODE_AVAILABLE=false

# ---------------------------------------------------------------------------
# Logging — prefer the host script's log_* helpers when present
# ---------------------------------------------------------------------------

_nb_log()  {
    [ "${ECTOR_INSTALL_COMPACT:-}" = 1 ] && return 0
    declare -F log_info    >/dev/null 2>&1 && log_info    "$*" || printf '→ %s\n' "$*" >&2
}
_nb_ok()   {
    [ "${ECTOR_INSTALL_COMPACT:-}" = 1 ] && return 0
    declare -F log_success >/dev/null 2>&1 && log_success "$*" || printf '✓ %s\n' "$*" >&2
}
_nb_warn() {
    [ "${ECTOR_INSTALL_COMPACT:-}" = 1 ] && return 0
    declare -F log_warn    >/dev/null 2>&1 && log_warn    "$*" || printf '▲ %s\n' "$*" >&2
}

# ---------------------------------------------------------------------------
# Platform + version helpers
# ---------------------------------------------------------------------------

_nb_is_termux() {
    [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux/files/usr"* ]]
}

_nb_node_major() {
    local v
    v=$(node --version 2>/dev/null | sed 's/^v//' | cut -d. -f1)
    [[ "$v" =~ ^[0-9]+$ ]] && echo "$v" || echo 0
}

_nb_have_modern_node() {
    command -v node >/dev/null 2>&1 || return 1
    [ "$(_nb_node_major)" -ge "$ECTOR_NODE_MIN_VERSION" ]
}

# ---------------------------------------------------------------------------
# Version-manager paths — respect what the user already uses
# ---------------------------------------------------------------------------

_nb_try_fnm() {
    command -v fnm >/dev/null 2>&1 || return 1
    _nb_log "fnm detected — installing Node $ECTOR_NODE_TARGET_MAJOR..."
    eval "$(fnm env 2>/dev/null)" || true
    fnm install "$ECTOR_NODE_TARGET_MAJOR" >/dev/null 2>&1 || return 1
    fnm use     "$ECTOR_NODE_TARGET_MAJOR" >/dev/null 2>&1 || return 1
    _nb_have_modern_node || return 1
    _nb_ok "Node $(node --version) activated via fnm"
    return 0
}

_nb_try_proto() {
    command -v proto >/dev/null 2>&1 || return 1
    _nb_log "proto detected — installing Node $ECTOR_NODE_TARGET_MAJOR..."
    proto install node "$ECTOR_NODE_TARGET_MAJOR" >/dev/null 2>&1 || return 1
    _nb_have_modern_node || return 1
    _nb_ok "Node $(node --version) activated via proto"
    return 0
}

_nb_try_nvm() {
    local nvm_sh="${NVM_DIR:-$HOME/.nvm}/nvm.sh"
    [ -s "$nvm_sh" ] || return 1
    # shellcheck source=/dev/null
    \. "$nvm_sh" >/dev/null 2>&1 || return 1
    _nb_log "nvm detected — installing Node $ECTOR_NODE_TARGET_MAJOR..."
    nvm install "$ECTOR_NODE_TARGET_MAJOR" >/dev/null 2>&1 || return 1
    nvm use     "$ECTOR_NODE_TARGET_MAJOR" >/dev/null 2>&1 || return 1
    _nb_have_modern_node || return 1
    _nb_ok "Node $(node --version) activated via nvm"
    return 0
}

# ---------------------------------------------------------------------------
# Platform package managers
# ---------------------------------------------------------------------------

_nb_try_termux_pkg() {
    _nb_is_termux || return 1
    _nb_log "Installing Node.js via pkg..."
    pkg install -y nodejs >/dev/null 2>&1 || return 1
    _nb_have_modern_node || return 1
    _nb_ok "Node $(node --version) installed via pkg"
    return 0
}

_nb_try_brew() {
    [ "$(uname -s)" = "Darwin" ] || return 1
    command -v brew >/dev/null 2>&1 || return 1
    _nb_log "Installing Node via Homebrew..."
    brew install "node@${ECTOR_NODE_TARGET_MAJOR}" >/dev/null 2>&1 \
        || brew install node >/dev/null 2>&1 \
        || return 1
    brew link --overwrite --force "node@${ECTOR_NODE_TARGET_MAJOR}" >/dev/null 2>&1 || true
    _nb_have_modern_node || return 1
    _nb_ok "Node $(node --version) installed via Homebrew"
    return 0
}

# ---------------------------------------------------------------------------
# Bundled binary fallback — always works, no shell rc edits
# ---------------------------------------------------------------------------

_nb_install_bundled_node() {
    local arch node_arch os_name node_os
    arch=$(uname -m)
    case "$arch" in
        x86_64)        node_arch="x64"    ;;
        aarch64|arm64) node_arch="arm64"  ;;
        armv7l)        node_arch="armv7l" ;;
        *)
            _nb_warn "Unsupported arch ($arch) — install Node.js manually: https://nodejs.org/"
            return 1
            ;;
    esac

    os_name=$(uname -s)
    case "$os_name" in
        Linux*)  node_os="linux"  ;;
        Darwin*) node_os="darwin" ;;
        *)
            _nb_warn "Unsupported OS ($os_name) — install Node.js manually: https://nodejs.org/"
            return 1
            ;;
    esac

    local index_url="https://nodejs.org/dist/latest-v${ECTOR_NODE_TARGET_MAJOR}.x/"
    local tarball
    tarball=$(curl -fsSL "$index_url" \
        | grep -oE "node-v${ECTOR_NODE_TARGET_MAJOR}\.[0-9]+\.[0-9]+-${node_os}-${node_arch}\.tar\.xz" \
        | head -1)
    if [ -z "$tarball" ]; then
        tarball=$(curl -fsSL "$index_url" \
            | grep -oE "node-v${ECTOR_NODE_TARGET_MAJOR}\.[0-9]+\.[0-9]+-${node_os}-${node_arch}\.tar\.gz" \
            | head -1)
    fi
    if [ -z "$tarball" ]; then
        _nb_warn "Could not resolve Node $ECTOR_NODE_TARGET_MAJOR binary for $node_os-$node_arch"
        return 1
    fi

    local tmp
    tmp=$(mktemp -d)
    _nb_log "Downloading $tarball..."
    curl -fsSL "${index_url}${tarball}" -o "$tmp/$tarball" || {
        _nb_warn "Download failed"; rm -rf "$tmp"; return 1
    }

    _nb_log "Extracting to $ECTOR_HOME/node/..."
    if [[ "$tarball" == *.tar.xz ]]; then
        tar xf  "$tmp/$tarball" -C "$tmp" || { rm -rf "$tmp"; return 1; }
    else
        tar xzf "$tmp/$tarball" -C "$tmp" || { rm -rf "$tmp"; return 1; }
    fi

    local extracted
    extracted=$(find "$tmp" -maxdepth 1 -type d -name 'node-v*' 2>/dev/null | head -1)
    if [ ! -d "$extracted" ]; then
        _nb_warn "Extraction produced no node-v* directory"
        rm -rf "$tmp"
        return 1
    fi

    mkdir -p "$ECTOR_HOME"
    rm -rf "$ECTOR_HOME/node"
    mv "$extracted" "$ECTOR_HOME/node"
    rm -rf "$tmp"

    mkdir -p "$HOME/.local/bin"
    ln -sf "$ECTOR_HOME/node/bin/node" "$HOME/.local/bin/node"
    ln -sf "$ECTOR_HOME/node/bin/npm"  "$HOME/.local/bin/npm"
    ln -sf "$ECTOR_HOME/node/bin/npx"  "$HOME/.local/bin/npx"
    export PATH="$ECTOR_HOME/node/bin:$PATH"
    
    npm install -g pnpm >/dev/null 2>&1 || true
    ln -sf "$ECTOR_HOME/node/bin/pnpm" "$HOME/.local/bin/pnpm" || true

    _nb_have_modern_node || return 1
    _nb_ok "Node $(node --version) installed to $ECTOR_HOME/node/"
    return 0
}

# ---------------------------------------------------------------------------
# yarn + pnpm — git-hosted deps (e.g. Baileys) may run `yarn install` in prepare;
# install yarn first, then pnpm.
# ---------------------------------------------------------------------------

_nb_ensure_yarn() {
    # Debian/Ubuntu: package "cmdtest" installs a conflicting /usr/bin/yarn — not Node's Yarn.
    if command -v dpkg-query >/dev/null 2>&1; then
        if dpkg-query -W -f='${Status}' cmdtest 2>/dev/null | grep -q "install ok installed"; then
            _nb_warn "Remova o pacote Debian 'cmdtest' (yarn falso): sudo apt remove cmdtest"
        fi
    fi

    if command -v yarn >/dev/null 2>&1; then
        return 0
    fi

    if command -v corepack >/dev/null 2>&1; then
        _nb_log "Ativando Yarn via corepack (recomendado no Linux)..."
        corepack enable >/dev/null 2>&1 || true
        if command -v yarn >/dev/null 2>&1; then
            _nb_ok "yarn $(yarn --version 2>/dev/null | tr -d '\r') via corepack"
            return 0
        fi
        if corepack prepare yarn@4.6.0 --activate >/dev/null 2>&1; then
            command -v yarn >/dev/null 2>&1 && {
                _nb_ok "yarn $(yarn --version 2>/dev/null | tr -d '\r') via corepack prepare"
                return 0
            }
        fi
    fi

    if command -v npm >/dev/null 2>&1; then
        _nb_log "Instalando yarn globalmente (npm install -g yarn)..."
        if npm install -g yarn >/dev/null 2>&1; then
            command -v yarn >/dev/null 2>&1 && {
                _nb_ok "yarn $(yarn --version 2>/dev/null | tr -d '\r') instalado"
                return 0
            }
        fi
    fi

    if command -v pnpm >/dev/null 2>&1; then
        _nb_log "Instalando yarn globalmente (pnpm add -g yarn)..."
        if pnpm add -g yarn >/dev/null 2>&1; then
            command -v yarn >/dev/null 2>&1 && {
                _nb_ok "yarn $(yarn --version 2>/dev/null | tr -d '\r') via pnpm global"
                return 0
            }
        fi
    fi

    if ! command -v yarn >/dev/null 2>&1; then
        _nb_warn "yarn não encontrado — hooks prepare (ex.: Baileys no pnpm) podem falhar. Evite apt install yarn/cmdtest; use: corepack enable && corepack prepare yarn@4.6.0 --activate"
    fi
    return 0
}

_nb_ensure_pnpm() {
    command -v pnpm >/dev/null 2>&1 && return 0
    command -v npm  >/dev/null 2>&1 || return 0

    if command -v corepack >/dev/null 2>&1; then
        if corepack enable >/dev/null 2>&1 && corepack prepare pnpm@latest --activate >/dev/null 2>&1; then
            command -v pnpm >/dev/null 2>&1 && {
                _nb_ok "pnpm ativado via corepack ($(pnpm --version 2>/dev/null | tr -d '\r'))"
                return 0
            }
        fi
    fi

    _nb_log "Instalando pnpm globalmente (npm install -g pnpm)..."
    if npm install -g pnpm >/dev/null 2>&1; then
        command -v pnpm >/dev/null 2>&1 && _nb_ok "pnpm $(pnpm --version 2>/dev/null | tr -d '\r') instalado"
    else
        _nb_warn "pnpm não pôde ser instalado globalmente — use npm nos diretórios dos projetos ou instale manualmente: npm install -g pnpm"
    fi
    return 0
}

_nb_ensure_node_package_managers() {
    _nb_ensure_yarn
    _nb_ensure_pnpm
}

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

ensure_node() {
    ECTOR_NODE_AVAILABLE=false

    if _nb_have_modern_node; then
        _nb_ok "Node $(node --version) found"
        _nb_ensure_node_package_managers
        ECTOR_NODE_AVAILABLE=true
        return 0
    fi

    if [ -x "$ECTOR_HOME/node/bin/node" ]; then
        export PATH="$ECTOR_HOME/node/bin:$PATH"
        if _nb_have_modern_node; then
            _nb_ok "Node $(node --version) found (Ector-managed)"
            _nb_ensure_node_package_managers
            ECTOR_NODE_AVAILABLE=true
            return 0
        fi
    fi

    # Version managers first — respect the user's existing setup.
    _nb_try_fnm   && { ECTOR_NODE_AVAILABLE=true; _nb_ensure_node_package_managers; return 0; }
    _nb_try_proto && { ECTOR_NODE_AVAILABLE=true; _nb_ensure_node_package_managers; return 0; }
    _nb_try_nvm   && { ECTOR_NODE_AVAILABLE=true; _nb_ensure_node_package_managers; return 0; }

    # Platform package managers.
    _nb_try_termux_pkg && { ECTOR_NODE_AVAILABLE=true; _nb_ensure_node_package_managers; return 0; }
    _nb_try_brew       && { ECTOR_NODE_AVAILABLE=true; _nb_ensure_node_package_managers; return 0; }

    # Last resort: pinned nodejs.org tarball.
    _nb_install_bundled_node && { ECTOR_NODE_AVAILABLE=true; _nb_ensure_node_package_managers; return 0; }

    _nb_warn "Node.js install failed — TUI and browser tools will be unavailable."
    _nb_warn "Install manually: https://nodejs.org/en/download/  (or: \`brew install node\`, \`fnm install $ECTOR_NODE_TARGET_MAJOR\`, etc.)"
    return 1
}
