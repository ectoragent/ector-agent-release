#!/usr/bin/env bash
# ============================================================================
# scripts/lib/bun-bootstrap.sh
# ----------------------------------------------------------------------------
# Sourceable helper: ensure Bun is available for the OpenTUI terminal chat.
#
# Strategy (first hit wins):
#   1. `bun` already on PATH
#   2. ~/.ector/bun/bin/bun from a prior Ector-managed install
#   3. Termux `pkg install bun`
#   4. macOS Homebrew
#   5. Official installer into ~/.ector/bun/ (BUN_INSTALL)
#
# Usage:
#   source scripts/lib/bun-bootstrap.sh
#   ensure_bun
# ============================================================================

ECTOR_HOME="${ECTOR_HOME:-$HOME/.ector}"
BUN_INSTALL="${BUN_INSTALL:-$ECTOR_HOME/bun}"
ECTOR_BUN_AVAILABLE=false

_bb_log()  {
    [ "${ECTOR_INSTALL_COMPACT:-}" = 1 ] && return 0
    declare -F log_info    >/dev/null 2>&1 && log_info    "$*" || printf '→ %s\n' "$*" >&2
}
_bb_ok()   {
    [ "${ECTOR_INSTALL_COMPACT:-}" = 1 ] && return 0
    declare -F log_success >/dev/null 2>&1 && log_success "$*" || printf '✓ %s\n' "$*" >&2
}
_bb_warn() {
    [ "${ECTOR_INSTALL_COMPACT:-}" = 1 ] && return 0
    declare -F log_warn    >/dev/null 2>&1 && log_warn    "$*" || printf '▲ %s\n' "$*" >&2
}

_bb_is_termux() {
    [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux/files/usr"* ]]
}

_bb_ensure_unzip() {
    command -v unzip >/dev/null 2>&1 && return 0

    _bb_log "Installing unzip (required for Bun)..."

    if command -v apt-get >/dev/null 2>&1; then
        if [ "$(id -u)" -eq 0 ]; then
            DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 || true
            DEBIAN_FRONTEND=noninteractive apt-get install -y unzip >/dev/null 2>&1 \
                && command -v unzip >/dev/null 2>&1 && return 0
        elif command -v sudo >/dev/null 2>&1; then
            DEBIAN_FRONTEND=noninteractive sudo -n apt-get update -qq >/dev/null 2>&1 || true
            DEBIAN_FRONTEND=noninteractive sudo -n apt-get install -y unzip >/dev/null 2>&1 \
                && command -v unzip >/dev/null 2>&1 && return 0
        fi
    fi

    if command -v dnf >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
        dnf install -y unzip >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1 && return 0
    fi

    if command -v apk >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
        apk add --no-cache unzip >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1 && return 0
    fi

    if command -v pacman >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
        pacman -S --noconfirm unzip >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1 && return 0
    fi

    return 1
}

_bb_prepend_managed_path() {
    if [ -x "$BUN_INSTALL/bin/bun" ]; then
        export BUN_INSTALL
        case ":${PATH}:" in
            *":$BUN_INSTALL/bin:"*) ;;
            *) export PATH="$BUN_INSTALL/bin:$PATH" ;;
        esac
    fi
}

_bb_try_termux_pkg() {
    _bb_is_termux || return 1
    command -v pkg >/dev/null 2>&1 || return 1
    _bb_log "Installing Bun via pkg..."
    pkg install -y bun unzip >/dev/null 2>&1 || return 1
    command -v bun >/dev/null 2>&1 || return 1
    _bb_ok "Bun $(bun --version 2>/dev/null | tr -d '\r') installed via pkg"
    return 0
}

_bb_try_brew() {
    [ "$(uname -s)" = "Darwin" ] || return 1
    command -v brew >/dev/null 2>&1 || return 1
    _bb_log "Installing Bun via Homebrew..."
    brew install oven-sh/bun/bun >/dev/null 2>&1 \
        || brew install bun >/dev/null 2>&1 \
        || return 1
    command -v bun >/dev/null 2>&1 || return 1
    _bb_ok "Bun $(bun --version 2>/dev/null | tr -d '\r') installed via Homebrew"
    return 0
}

_bb_install_managed() {
    _bb_ensure_unzip || true
    command -v unzip >/dev/null 2>&1 || {
        _bb_warn "unzip is required to install Bun (e.g. apt install unzip)"
        return 1
    }
    command -v curl >/dev/null 2>&1 || {
        _bb_warn "curl is required to install Bun"
        return 1
    }

    mkdir -p "$ECTOR_HOME"
    export BUN_INSTALL="$ECTOR_HOME/bun"
    _bb_prepend_managed_path

    _bb_log "Installing Bun to $BUN_INSTALL ..."
    if curl -fsSL https://bun.sh/install | bash; then
        _bb_prepend_managed_path
        if [ -x "$BUN_INSTALL/bin/bun" ]; then
            mkdir -p "$HOME/.local/bin"
            ln -sf "$BUN_INSTALL/bin/bun" "$HOME/.local/bin/bun"
            _bb_ok "Bun $($BUN_INSTALL/bin/bun --version 2>/dev/null | tr -d '\r') installed to $BUN_INSTALL/"
            return 0
        fi
    fi
    return 1
}

ensure_bun() {
    ECTOR_BUN_AVAILABLE=false

    if command -v bun >/dev/null 2>&1; then
        _bb_ok "Bun $(bun --version 2>/dev/null | tr -d '\r') found"
        ECTOR_BUN_AVAILABLE=true
        return 0
    fi

    _bb_prepend_managed_path
    if command -v bun >/dev/null 2>&1; then
        _bb_ok "Bun $(bun --version 2>/dev/null | tr -d '\r') found (Ector-managed)"
        ECTOR_BUN_AVAILABLE=true
        return 0
    fi

    _bb_try_termux_pkg && { ECTOR_BUN_AVAILABLE=true; return 0; }
    _bb_try_brew       && { ECTOR_BUN_AVAILABLE=true; return 0; }

    _bb_ensure_unzip || true
    _bb_install_managed && { ECTOR_BUN_AVAILABLE=true; return 0; }

    _bb_warn "Bun install failed — terminal chat (ector chat) requires Bun: https://bun.sh"
    return 1
}
