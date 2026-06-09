#!/bin/bash
# ============================================================================
# Ector Agent Installer
# ============================================================================
# Installation script for Linux, macOS, and Android/Termux.
# Uses uv for desktop/server installs and Python's stdlib venv + pip on Termux.
#
# Usage:
#   curl -fsSL https://ector.cc/install.sh | bash
#
# Or with options:
#   curl -fsSL ... | bash -s -- --no-venv --skip-setup
#
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
VIOLET='\033[38;2;0;209;255m'
DIM='\033[2m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Configuration
REPO_URL_SSH="${ECTOR_INSTALL_REPO_SSH:-git@github.com:ectoragent/ector-agent-release.git}"
REPO_URL_HTTPS="${ECTOR_INSTALL_REPO:-https://github.com/ectoragent/ector-agent-release.git}"
ECTOR_HOME="${ECTOR_HOME:-$HOME/.ector}"
# INSTALL_DIR is resolved AFTER arg parsing and OS detection so we can pick an
# FHS-style layout for root installs.  Track whether the user gave us an
# explicit directory — if so we never override it.
if [ -n "${ECTOR_INSTALL_DIR:-}" ]; then
    INSTALL_DIR="$ECTOR_INSTALL_DIR"
    INSTALL_DIR_EXPLICIT=true
else
    INSTALL_DIR=""
    INSTALL_DIR_EXPLICIT=false
fi
PYTHON_VERSION="3.11"
NODE_VERSION="22"

# FHS-style root install layout (set by resolve_install_layout when applicable):
#   code at /usr/local/lib/ector-agent, command at /usr/local/bin/ector,
#   data still at /root/.ector (ECTOR_HOME).  Matches Claude Code / Codex CLI
#   and keeps Docker bind-mounted /root/ volumes lean.
ROOT_FHS_LAYOUT=false

# Options
USE_VENV=true
RUN_SETUP=true
BRANCH="main"

# Detect non-interactive mode (e.g. curl | bash)
# When stdin is not a terminal, read -p will fail with EOF,
# causing set -e to silently abort the entire script.
if [ -t 0 ]; then
    IS_INTERACTIVE=true
else
    IS_INTERACTIVE=false
fi

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-venv)
            USE_VENV=false
            shift
            ;;
        --skip-setup)
            RUN_SETUP=false
            shift
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --dir)
            INSTALL_DIR="$2"
            INSTALL_DIR_EXPLICIT=true
            shift 2
            ;;
        --ector-home)
            ECTOR_HOME="$2"
            shift 2
            ;;
        -h|--help)
            echo "Instalação do Ector Agent"
            echo ""
            echo "Usage: install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --no-venv      Don't create virtual environment"
            echo "  --skip-setup   Skip interactive setup wizard"
            echo "  --branch NAME  Git branch to install (default: main)"
            echo "  --dir PATH     Installation directory"
            echo "                   default (non-root):  ~/.ector/ector-agent"
            echo "                   default (root, Linux): /usr/local/lib/ector-agent"
            echo "  --ector-home PATH  Data directory (default: ~/.ector, or \$ECTOR_HOME)"
            echo "  -h, --help     Show this help"
            echo ""
            echo "Notes:"
            echo "  When running as root on Linux, Ector installs the code under"
            echo "  /usr/local/lib/ector-agent and links the command into"
            echo "  /usr/local/bin/ector (FHS layout — matches Claude Code / Codex CLI)."
            echo "  Data, config, sessions, and logs still live in \$ECTOR_HOME"
            echo "  (default /root/.ector).  This keeps Docker bind-mounted volumes"
            echo "  small and ensures the command is on PATH for all shells."
            echo "  Existing installs at \$ECTOR_HOME/ector-agent are preserved in-place."
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ector update (e outros fluxos não interativos) não devem abrir prompts do instalador.
if [ -n "${ECTOR_NONINTERACTIVE:-}" ]; then
    IS_INTERACTIVE=false
fi

# ============================================================================
# Helper functions
# ============================================================================

_install_title() {
    if [ -n "${ECTOR_NONINTERACTIVE:-}" ]; then
        echo "Atualização do Ector"
    else
        echo "Instalação do Ector Agent"
    fi
}

_is_update_mode() {
    [ -n "${ECTOR_NONINTERACTIVE:-}" ]
}

print_banner() {
    if _is_update_mode; then
        return 0
    fi
    echo ""
    echo -e "${VIOLET}${BOLD}$(_install_title)${NC}"
    echo ""
}

_IO_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/install-output.sh"
if [ -f "$_IO_LIB" ]; then
    # shellcheck source=scripts/lib/install-output.sh
    source "$_IO_LIB"
fi

log_info() {
    _install_verbose && echo -e "${CYAN}→${NC} $1"
}

log_success() {
    if declare -F _install_step_ok >/dev/null 2>&1; then
        _install_step_ok "$1"
    else
        echo -e "${GREEN}✔${NC} $1"
    fi
}

log_warn() {
    echo -e "${YELLOW}▲${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

prompt_yes_no() {
    local question="$1"
    local default="${2:-yes}"
    local prompt_suffix
    local answer=""

    # ector update / curl | bash: never block on /dev/tty — honour the default.
    if [ -n "${ECTOR_NONINTERACTIVE:-}" ]; then
        case "$default" in
            [yY]|[yY][eE][sS]|[sS]|[sS][iI][mM]|[tT][rR][uU][eE]|1) return 0 ;;
            *) return 1 ;;
        esac
    fi

    # Use case patterns (not ${var,,}) so this works on bash 3.2 (macOS /bin/bash).
    case "$default" in
        [yY]|[yY][eE][sS]|[sS]|[sS][iI][mM]|[tT][rR][uU][eE]|1) prompt_suffix="(s/n)" ;;
        *) prompt_suffix="(s/n)" ;;
    esac

    if [ "$IS_INTERACTIVE" = true ]; then
        read -r -p "$question $prompt_suffix " answer || answer=""
    elif [ -r /dev/tty ] && [ -w /dev/tty ]; then
        printf "%s %s " "$question" "$prompt_suffix" > /dev/tty
        IFS= read -r answer < /dev/tty || answer=""
    else
        answer=""
    fi

    answer="${answer#"${answer%%[![:space:]]*}"}"
    answer="${answer%"${answer##*[![:space:]]}"}"

    if [ -z "$answer" ]; then
        case "$default" in
            [yY]|[yY][eE][sS]|[tT][rR][uU][eE]|1) return 0 ;;
            *) return 1 ;;
        esac
    fi

    case "$answer" in
        [yY]|[yY][eE][sS]|[sS]|[sS][iI][mM]) return 0 ;;
        *) return 1 ;;
    esac
}

is_termux() {
    [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux/files/usr"* ]]
}

# Decide where the repo checkout + venv live, and where the `ector` command
# symlink goes.  Called after detect_os so $OS/$DISTRO are known.
#
# Defaults:
#   - Non-root, any OS:       INSTALL_DIR = $ECTOR_HOME/ector-agent
#                             (or $ECTOR_HOME/agent if that checkout exists)
#                             command link in $HOME/.local/bin
#   - Termux (any uid):       INSTALL_DIR = $ECTOR_HOME/ector-agent
#                             command link in $PREFIX/bin (already on PATH)
#   - Root on Linux (new):    INSTALL_DIR = /usr/local/lib/ector-agent
#                             command link in /usr/local/bin
#                             (unless a legacy install already exists at
#                              $ECTOR_HOME/agent or $ECTOR_HOME/ector-agent)
#
# Always no-op when the user set --dir or $ECTOR_INSTALL_DIR.
resolve_install_layout() {
    if [ "$INSTALL_DIR_EXPLICIT" = true ]; then
        if ! _is_update_mode; then
            log_info "Install directory: $INSTALL_DIR (explicit)"
        fi
        return 0
    fi

    # Termux: package manager manages /data/data/..., keep code in ECTOR_HOME.
    if is_termux; then
        INSTALL_DIR="$ECTOR_HOME/ector-agent"
        return 0
    fi

    # Root on Linux: prefer FHS layout unless a legacy install already exists.
    # macOS root installs keep the legacy layout because /usr/local/ on macOS
    # is Homebrew territory and we don't want to fight that.
    if [ "$OS" = "linux" ] && [ "$(id -u)" -eq 0 ]; then
        if [ -d "$ECTOR_HOME/ector-agent/.git" ]; then
            INSTALL_DIR="$ECTOR_HOME/ector-agent"
            log_info "Existing install detected at $INSTALL_DIR — keeping legacy layout"
            log_info "  (new root installs use /usr/local/lib/ector-agent)"
            return 0
        fi
        INSTALL_DIR="/usr/local/lib/ector-agent"
        ROOT_FHS_LAYOUT=true
        log_info "Root install on Linux — using FHS layout"
        log_info "  Code:    $INSTALL_DIR"
        log_info "  Command: /usr/local/bin/ector"
        log_info "  Data:    $ECTOR_HOME (unchanged)"
        return 0
    fi

    # Default: non-root, non-Termux → legacy user-scoped layout.
    INSTALL_DIR="$ECTOR_HOME/ector-agent"
}

get_command_link_dir() {
    if is_termux && [ -n "${PREFIX:-}" ]; then
        echo "$PREFIX/bin"
    elif [ "$ROOT_FHS_LAYOUT" = true ]; then
        echo "/usr/local/bin"
    else
        echo "$HOME/.local/bin"
    fi
}

get_command_link_display_dir() {
    if is_termux && [ -n "${PREFIX:-}" ]; then
        echo '$PREFIX/bin'
    elif [ "$ROOT_FHS_LAYOUT" = true ]; then
        echo '/usr/local/bin'
    else
        echo '~/.local/bin'
    fi
}

get_ector_command_path() {
    local link_dir
    link_dir="$(get_command_link_dir)"
    if [ -x "$link_dir/ector" ]; then
        echo "$link_dir/ector"
    else
        echo "ector"
    fi
}

# ============================================================================
# System detection
# ============================================================================

detect_os() {
    case "$(uname -s)" in
        Linux*)
            if is_termux; then
                OS="android"
                DISTRO="termux"
            else
                OS="linux"
                if [ -f /etc/os-release ]; then
                    . /etc/os-release
                    DISTRO="$ID"
                else
                    DISTRO="unknown"
                fi
            fi
            ;;
        Darwin*)
            OS="macos"
            DISTRO="macos"
            ;;
        CYGWIN*|MINGW*|MSYS*)
            OS="windows"
            DISTRO="windows"
            log_error "Windows detected. Please use the PowerShell installer:"
            log_info "  irm https://ector.cc/install.ps1 | iex"
            exit 1
            ;;
        *)
            OS="unknown"
            DISTRO="unknown"
            log_warn "Unknown operating system"
            ;;
    esac

    log_success "Sistema: $OS ($DISTRO)"
}

# ============================================================================
# Dependency checks
# ============================================================================

install_uv() {
    if [ "$DISTRO" = "termux" ]; then
        UV_CMD=""
        return 0
    fi

    _find_uv() {
        UV_CMD=""
        if command -v uv &> /dev/null; then
            UV_CMD="uv"
        elif [ -x "$HOME/.local/bin/uv" ]; then
            UV_CMD="$HOME/.local/bin/uv"
        elif [ -x "$HOME/.cargo/bin/uv" ]; then
            UV_CMD="$HOME/.cargo/bin/uv"
        fi
    }

    _find_uv

    if [ -z "$UV_CMD" ]; then
        if _is_update_mode && declare -F _install_step >/dev/null 2>&1; then
            _install_step "Gerenciador Python (uv)" bash -c \
                'curl -LsSf https://astral.sh/uv/install.sh | sh' || true
            export PATH="$HOME/.local/bin:$HOME/.cargo/bin:${PATH:-}"
            _find_uv
        else
            curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || true
            export PATH="$HOME/.local/bin:$HOME/.cargo/bin:${PATH:-}"
            _find_uv
        fi
    fi

    if [ -z "$UV_CMD" ]; then
        log_error "Gerenciador Python (uv) — https://docs.astral.sh/uv/"
        exit 1
    fi
    log_success "Gerenciador Python (uv)"
}

check_python() {
    if [ "$DISTRO" = "termux" ]; then
        if ! command -v python >/dev/null 2>&1; then
            pkg install -y python >/dev/null
        fi
        PYTHON_PATH="$(command -v python)"
        if ! "$PYTHON_PATH" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            log_error "Python 3.11+ (Termux: pkg install python)"
            exit 1
        fi
        log_success "Python 3.11+"
        return 0
    fi

    if ! PYTHON_PATH="$("$UV_CMD" python find "$PYTHON_VERSION" 2>/dev/null)"; then
        "$UV_CMD" python install "$PYTHON_VERSION" >/dev/null 2>&1
        PYTHON_PATH="$("$UV_CMD" python find "$PYTHON_VERSION")"
    fi
    log_success "Python $PYTHON_VERSION"
}

check_git() {
    if command -v git &> /dev/null; then
        log_success "Git"
        return 0
    fi

    if _is_update_mode && [ "$OS" = "linux" ] && [ "$(id -u)" -eq 0 ]; then
        case "$DISTRO" in
            ubuntu|debian|raspbian|pop|linuxmint|elementary|zorin|kali|parrot)
                if declare -F _install_step >/dev/null 2>&1; then
                    if _install_step "Git" bash -c \
                        'DEBIAN_FRONTEND=noninteractive apt-get update -qq && apt-get install -y git'; then
                        command -v git >/dev/null 2>&1 && return 0
                    fi
                fi
                ;;
        esac
    fi

    log_error "Git não encontrado"

    if [ "$DISTRO" = "termux" ]; then
        log_info "Installing Git via pkg..."
        pkg install -y git >/dev/null
        if command -v git >/dev/null 2>&1; then
            GIT_VERSION=$(git --version | awk '{print $3}')
            log_success "Git $GIT_VERSION installed"
            return 0
        fi
    fi

    log_info "Please install Git:"

    case "$OS" in
        linux)
            case "$DISTRO" in
                ubuntu|debian)
                    log_info "  sudo apt update && sudo apt install git"
                    ;;
                fedora)
                    log_info "  sudo dnf install git"
                    ;;
                arch)
                    log_info "  sudo pacman -S git"
                    ;;
                *)
                    log_info "  Use your package manager to install git"
                    ;;
            esac
            ;;
        android)
            log_info "  pkg install git"
            ;;
        macos)
            log_info "  xcode-select --install"
            log_info "  Or: brew install git"
            ;;
    esac

    exit 1
}

check_node() {
    if command -v node &> /dev/null; then
        HAS_NODE=true
        log_success "Node.js (ferramentas web e WhatsApp)"
        return 0
    fi

    if [ -x "$ECTOR_HOME/node/bin/node" ]; then
        export PATH="$ECTOR_HOME/node/bin:$PATH"
        HAS_NODE=true
        log_success "Node.js (ferramentas web e WhatsApp)"
        return 0
    fi

    install_node
    if [ "$HAS_NODE" = true ]; then
        log_success "Node.js (ferramentas web e WhatsApp)"
    else
        log_warn "Node.js não encontrado (ferramentas web podem falhar)"
    fi
}

install_node() {
    if [ "$DISTRO" = "termux" ]; then
        log_info "Installing Node.js via pkg..."
        if pkg install -y nodejs >/dev/null; then
            local installed_ver
            installed_ver=$(node --version 2>/dev/null)
            log_success "Node.js $installed_ver installed via pkg"
            HAS_NODE=true
        else
            log_warn "Failed to install Node.js via pkg"
            HAS_NODE=false
        fi
        return 0
    fi

    local arch=$(uname -m)
    local node_arch
    case "$arch" in
        x86_64)        node_arch="x64"    ;;
        aarch64|arm64) node_arch="arm64"  ;;
        armv7l)        node_arch="armv7l" ;;
        *)
            log_warn "Unsupported architecture ($arch) for Node.js auto-install"
            log_info "Install manually: https://nodejs.org/en/download/"
            HAS_NODE=false
            return 0
            ;;
    esac

    local node_os
    case "$OS" in
        linux) node_os="linux"  ;;
        macos) node_os="darwin" ;;
        *)
            log_warn "Unsupported OS for Node.js auto-install"
            HAS_NODE=false
            return 0
            ;;
    esac

    # Resolve the latest v22.x.x tarball name from the index page
    local index_url="https://nodejs.org/dist/latest-v${NODE_VERSION}.x/"
    local tarball_name
    tarball_name=$(curl -fsSL "$index_url" \
        | grep -oE "node-v${NODE_VERSION}\.[0-9]+\.[0-9]+-${node_os}-${node_arch}\.tar\.xz" \
        | head -1)

    # Fallback to .tar.gz if .tar.xz not available
    if [ -z "$tarball_name" ]; then
        tarball_name=$(curl -fsSL "$index_url" \
            | grep -oE "node-v${NODE_VERSION}\.[0-9]+\.[0-9]+-${node_os}-${node_arch}\.tar\.gz" \
            | head -1)
    fi

    if [ -z "$tarball_name" ]; then
        log_warn "Could not find Node.js $NODE_VERSION binary for $node_os-$node_arch"
        log_info "Install manually: https://nodejs.org/en/download/"
        HAS_NODE=false
        return 0
    fi

    local download_url="${index_url}${tarball_name}"
    local tmp_dir
    tmp_dir=$(mktemp -d)

    log_info "Downloading $tarball_name..."
    if ! curl -fsSL "$download_url" -o "$tmp_dir/$tarball_name"; then
        log_warn "Download failed"
        rm -rf "$tmp_dir"
        HAS_NODE=false
        return 0
    fi

    log_info "Extracting to ~/.ector/node/..."
    if [[ "$tarball_name" == *.tar.xz ]]; then
        tar xf "$tmp_dir/$tarball_name" -C "$tmp_dir"
    else
        tar xzf "$tmp_dir/$tarball_name" -C "$tmp_dir"
    fi

    local extracted_dir
    extracted_dir=$(ls -d "$tmp_dir"/node-v* 2>/dev/null | head -1)

    if [ ! -d "$extracted_dir" ]; then
        log_warn "Extraction failed"
        rm -rf "$tmp_dir"
        HAS_NODE=false
        return 0
    fi

    # Place into ~/.ector/node/ and symlink binaries to ~/.local/bin/
    rm -rf "$ECTOR_HOME/node"
    mkdir -p "$ECTOR_HOME"
    mv "$extracted_dir" "$ECTOR_HOME/node"
    rm -rf "$tmp_dir"

    mkdir -p "$HOME/.local/bin"
    ln -sf "$ECTOR_HOME/node/bin/node" "$HOME/.local/bin/node"
    ln -sf "$ECTOR_HOME/node/bin/npm"  "$HOME/.local/bin/npm"
    ln -sf "$ECTOR_HOME/node/bin/npx"  "$HOME/.local/bin/npx"

    export PATH="$ECTOR_HOME/node/bin:$PATH"

    local installed_ver
    installed_ver=$("$ECTOR_HOME/node/bin/node" --version 2>/dev/null)
    log_success "Node.js $installed_ver installed to ~/.ector/node/"
    HAS_NODE=true
}

check_bun() {
    HAS_BUN=false

    if _is_update_mode; then
        if command -v bun &>/dev/null; then
            HAS_BUN=true
            return 0
        fi
        if [ -x "$ECTOR_HOME/bun/bin/bun" ]; then
            export PATH="$ECTOR_HOME/bun/bin:$PATH"
            HAS_BUN=true
        fi
        return 0
    fi

    log_info "Checking Bun (TUI / ector chat)..."

    local helper="$INSTALL_DIR/scripts/lib/bun-bootstrap.sh"
    if [ ! -f "$helper" ]; then
        log_warn "Bun bootstrap helper missing — install Bun manually: https://bun.sh"
        return 0
    fi

    # shellcheck source=scripts/lib/bun-bootstrap.sh
    # shellcheck disable=SC1090
    source "$helper"
    if ensure_bun; then
        HAS_BUN=true
    else
        HAS_BUN=false
    fi
}

install_system_packages() {
    if _is_update_mode; then
        HAS_RIPGREP=false
        HAS_FFMPEG=false
        command -v rg &>/dev/null && HAS_RIPGREP=true
        command -v ffmpeg &>/dev/null && HAS_FFMPEG=true
        return 0
    fi

    # Detect what's missing
    HAS_RIPGREP=false
    HAS_FFMPEG=false
    local need_ripgrep=false
    local need_ffmpeg=false

    log_info "Checking ripgrep (fast file search)..."
    if command -v rg &> /dev/null; then
        log_success "$(rg --version | head -1) found"
        HAS_RIPGREP=true
    else
        need_ripgrep=true
    fi

    log_info "Checking ffmpeg (TTS voice messages)..."
    if command -v ffmpeg &> /dev/null; then
        local ffmpeg_ver=$(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}')
        log_success "ffmpeg $ffmpeg_ver found"
        HAS_FFMPEG=true
    else
        need_ffmpeg=true
    fi

    # Termux always needs the Android build toolchain for the tested pip path,
    # even when ripgrep/ffmpeg are already present.
    if [ "$DISTRO" = "termux" ]; then
        local termux_pkgs=(clang rust make pkg-config libffi openssl)
        if [ "$need_ripgrep" = true ]; then
            termux_pkgs+=("ripgrep")
        fi
        if [ "$need_ffmpeg" = true ]; then
            termux_pkgs+=("ffmpeg")
        fi

        log_info "Installing Termux packages: ${termux_pkgs[*]}"
        if pkg install -y "${termux_pkgs[@]}" >/dev/null; then
            [ "$need_ripgrep" = true ] && HAS_RIPGREP=true && log_success "ripgrep installed"
            [ "$need_ffmpeg" = true ]  && HAS_FFMPEG=true  && log_success "ffmpeg installed"
            log_success "Termux build dependencies installed"
            return 0
        fi

        log_warn "Could not auto-install all Termux packages"
        log_info "Install manually: pkg install ${termux_pkgs[*]}"
        return 0
    fi

    # Nothing to install — done
    if [ "$need_ripgrep" = false ] && [ "$need_ffmpeg" = false ]; then
        return 0
    fi

    # Build a human-readable description + package list
    local desc_parts=()
    local pkgs=()
    if [ "$need_ripgrep" = true ]; then
        desc_parts+=("ripgrep for faster file search")
        pkgs+=("ripgrep")
    fi
    if [ "$need_ffmpeg" = true ]; then
        desc_parts+=("ffmpeg for TTS voice messages")
        pkgs+=("ffmpeg")
    fi
    local description
    description=$(IFS=" and "; echo "${desc_parts[*]}")

    # ── macOS: brew ──
    if [ "$OS" = "macos" ]; then
        if command -v brew &> /dev/null; then
            log_info "Installing ${pkgs[*]} via Homebrew..."
            if brew install "${pkgs[@]}"; then
                [ "$need_ripgrep" = true ] && HAS_RIPGREP=true && log_success "ripgrep installed"
                [ "$need_ffmpeg" = true ]  && HAS_FFMPEG=true  && log_success "ffmpeg installed"
                return 0
            fi
        fi
        log_warn "Could not auto-install (brew not found or install failed)"
        log_info "Install manually: brew install ${pkgs[*]}"
        return 0
    fi

    # ── Linux: resolve package manager command ──
    local pkg_install=""
    case "$DISTRO" in
        ubuntu|debian) pkg_install="apt install -y"   ;;
        fedora)        pkg_install="dnf install -y"   ;;
        arch)          pkg_install="pacman -S --noconfirm" ;;
    esac

    if [ -n "$pkg_install" ]; then
        local install_cmd="$pkg_install ${pkgs[*]}"

        # Prevent needrestart/whiptail dialogs from blocking non-interactive installs
        case "$DISTRO" in
            ubuntu|debian) export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a ;;
        esac

        # Already root — just install
        if [ "$(id -u)" -eq 0 ]; then
            log_info "Installing ${pkgs[*]}..."
            if $install_cmd; then
                [ "$need_ripgrep" = true ] && HAS_RIPGREP=true && log_success "ripgrep installed"
                [ "$need_ffmpeg" = true ]  && HAS_FFMPEG=true  && log_success "ffmpeg installed"
                return 0
            fi
        # Passwordless sudo — just install
        elif command -v sudo &> /dev/null && sudo -n true 2>/dev/null; then
            log_info "Installing ${pkgs[*]}..."
            if sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a $install_cmd; then
                [ "$need_ripgrep" = true ] && HAS_RIPGREP=true && log_success "ripgrep installed"
                [ "$need_ffmpeg" = true ]  && HAS_FFMPEG=true  && log_success "ffmpeg installed"
                return 0
            fi
        # sudo needs password — ask once for everything
        elif command -v sudo &> /dev/null; then
            if [ "$IS_INTERACTIVE" = true ]; then
                echo ""
                log_info "sudo is needed ONLY to install optional system packages (${pkgs[*]}) via your package manager."
                log_info "Ector Agent itself does not require or retain root access."
                if prompt_yes_no "Install ${description}? (requires sudo)" "no"; then
                    if sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a $install_cmd; then
                        [ "$need_ripgrep" = true ] && HAS_RIPGREP=true && log_success "ripgrep installed"
                        [ "$need_ffmpeg" = true ]  && HAS_FFMPEG=true  && log_success "ffmpeg installed"
                        return 0
                    fi
                fi
            elif [ -e /dev/tty ]; then
                # Non-interactive (e.g. curl | bash) but a terminal is available.
                # Read the prompt from /dev/tty (same approach the setup wizard uses).
                echo ""
                log_info "sudo is needed ONLY to install optional system packages (${pkgs[*]}) via your package manager."
                log_info "Ector Agent itself does not require or retain root access."
                if prompt_yes_no "Install ${description}?" "yes"; then
                    if sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a $install_cmd < /dev/tty; then
                        [ "$need_ripgrep" = true ] && HAS_RIPGREP=true && log_success "ripgrep installed"
                        [ "$need_ffmpeg" = true ]  && HAS_FFMPEG=true  && log_success "ffmpeg installed"
                        return 0
                    fi
                fi
            else
                log_warn "Non-interactive mode and no terminal available — cannot install system packages"
                log_info "Install manually after setup completes: sudo $install_cmd"
            fi
        fi
    fi

    # ── Fallback for ripgrep: cargo ──
    if [ "$need_ripgrep" = true ] && [ "$HAS_RIPGREP" = false ]; then
        if command -v cargo &> /dev/null; then
            log_info "Trying cargo install ripgrep (no sudo needed)..."
            if cargo install ripgrep; then
                log_success "ripgrep installed via cargo"
                HAS_RIPGREP=true
            fi
        fi
    fi

    # ── Show manual instructions for anything still missing ──
    if [ "$HAS_RIPGREP" = false ] && [ "$need_ripgrep" = true ]; then
        log_warn "ripgrep not installed (file search will use grep fallback)"
        show_manual_install_hint "ripgrep"
    fi
    if [ "$HAS_FFMPEG" = false ] && [ "$need_ffmpeg" = true ]; then
        log_warn "ffmpeg not installed (TTS voice messages will be limited)"
        show_manual_install_hint "ffmpeg"
    fi
}

show_manual_install_hint() {
    local pkg="$1"
    log_info "To install $pkg manually:"
    case "$OS" in
        linux)
            case "$DISTRO" in
                ubuntu|debian) log_info "  sudo apt install $pkg" ;;
                fedora)        log_info "  sudo dnf install $pkg" ;;
                arch)          log_info "  sudo pacman -S $pkg"   ;;
                *)             log_info "  Use your package manager or visit the project homepage" ;;
            esac
            ;;
        android)
            log_info "  pkg install $pkg"
            ;;
        macos) log_info "  brew install $pkg" ;;
    esac
}

# ============================================================================
# Installation
# ============================================================================

clone_repo() {
    if [ -d "$INSTALL_DIR" ]; then
        if [ -d "$INSTALL_DIR/.git" ]; then
            if ! _is_update_mode; then
                log_info "Existing installation found, updating..."
            fi
            cd "$INSTALL_DIR"

            local autostash_ref=""
            if [ -n "$(git status --porcelain)" ]; then
                local stash_name
                stash_name="ector-install-autostash-$(date -u +%Y%m%d-%H%M%S)"
                if ! _is_update_mode; then
                    log_info "Local changes detected, stashing before update..."
                fi
                if _is_update_mode; then
                    git stash push --include-untracked -m "$stash_name" >/dev/null 2>&1
                else
                    git stash push --include-untracked -m "$stash_name"
                fi
                autostash_ref="$(git rev-parse --verify refs/stash 2>/dev/null || true)"
            fi

            _git_update_pull() {
                git fetch origin && git checkout "$BRANCH" && git pull --ff-only origin "$BRANCH"
            }

            if _is_update_mode && declare -F _install_step >/dev/null 2>&1; then
                _install_step "Código do Ector (git pull)" _git_update_pull || exit 1
            else
                _git_update_pull || exit 1
            fi

            if [ -n "$autostash_ref" ]; then
                local restore_now="no"
                if [ -n "${ECTOR_NONINTERACTIVE:-}" ]; then
                    log_info "Modo não interativo: alterações locais mantidas no git stash."
                    log_info "  Restaurar manualmente: git stash list && git stash apply"
                elif [ -t 0 ] && [ -t 1 ]; then
                    echo
                    log_warn "Local changes were stashed before updating."
                    log_warn "Restoring them may reapply local customizations onto the updated codebase."
                    printf "Restaurar alterações locais agora? (s/n) "
                    read -r restore_answer
                    case "$restore_answer" in
                        ""|s|S|sim|Sim|SIM|y|Y|yes|YES|Yes) restore_now="yes" ;;
                        *) restore_now="no" ;;
                    esac
                else
                    log_info "Sem terminal interativo: alterações locais mantidas no git stash."
                    log_info "  Restaurar manualmente: git stash list && git stash apply"
                fi

                if [ "$restore_now" = "yes" ]; then
                    log_info "Restoring local changes..."
                    if git stash apply "$autostash_ref"; then
                        git stash drop "$autostash_ref" >/dev/null
                        log_warn "Local changes were restored on top of the updated codebase."
                        log_warn "Review git diff / git status if Ector behaves unexpectedly."
                    else
                        log_error "Update succeeded, but restoring local changes failed. Your changes are still preserved in git stash."
                        log_info "Resolve manually with: git stash apply $autostash_ref"
                        exit 1
                    fi
                else
                    log_info "Skipped restoring local changes."
                    log_info "Your changes are still preserved in git stash."
                    log_info "Restore manually with: git stash apply $autostash_ref"
                fi
            fi
        else
            log_error "Directory exists but is not a git repository: $INSTALL_DIR"
            log_info "Remove it or choose a different directory with --dir"
            exit 1
        fi
    else
        # Try SSH first (for private repo access), fall back to HTTPS
        # GIT_SSH_COMMAND disables interactive prompts and sets a short timeout
        # so SSH fails fast instead of hanging when no key is configured.
        log_info "Trying SSH clone..."
        if GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=5" \
           git clone --branch "$BRANCH" "$REPO_URL_SSH" "$INSTALL_DIR" 2>/dev/null; then
            log_success "Cloned via SSH"
        else
            rm -rf "$INSTALL_DIR" 2>/dev/null  # Clean up partial SSH clone
            log_info "SSH failed, trying HTTPS..."
            if git clone --branch "$BRANCH" "$REPO_URL_HTTPS" "$INSTALL_DIR"; then
                log_success "Cloned via HTTPS"
            else
                log_error "Failed to clone repository"
                exit 1
            fi
        fi
    fi

    cd "$INSTALL_DIR"

    if ! _is_update_mode; then
        log_success "Código do Ector"
    fi
}

_venv_usable() {
    [ -x "venv/bin/python" ] && venv/bin/python -c 'import sys; sys.exit(0)' 2>/dev/null
}

_recreate_venv() {
    if [ -d "venv" ]; then
        rm -rf venv
    fi

    if [ "$DISTRO" = "termux" ]; then
        "$PYTHON_PATH" -m venv venv
    else
        $UV_CMD venv venv --python "$PYTHON_VERSION"
    fi
}

_ensure_venv() {
    if _venv_usable; then
        return 0
    fi
    _recreate_venv
}

setup_venv() {
    if [ "$USE_VENV" = false ]; then
        return 0
    fi

    if _is_update_mode && declare -F _install_step >/dev/null 2>&1; then
        _install_step "Ambiente virtual Python" _ensure_venv || exit 1
        return 0
    fi

    _recreate_venv || exit 1
    log_success "Ambiente virtual Python"
}

install_deps() {
    if [ "$DISTRO" = "termux" ]; then
        if [ "$USE_VENV" = true ]; then
            export VIRTUAL_ENV="$INSTALL_DIR/venv"
            PIP_PYTHON="$INSTALL_DIR/venv/bin/python"
        else
            PIP_PYTHON="$PYTHON_PATH"
        fi

        if [ -z "${ANDROID_API_LEVEL:-}" ]; then
            ANDROID_API_LEVEL="$(getprop ro.build.version.sdk 2>/dev/null || true)"
            [ -z "$ANDROID_API_LEVEL" ] && ANDROID_API_LEVEL=24
            export ANDROID_API_LEVEL
        fi

        _install_step "Pacote Python e dependências" bash -c '
            "$1" -m pip install --upgrade pip setuptools wheel >/dev/null &&
            ("$1" -m pip install ".[termux]" -c constraints-termux.txt ||
             "$1" -m pip install "." -c constraints-termux.txt)
        ' bash "$PIP_PYTHON" || exit 1
        return 0
    fi

    if [ "$USE_VENV" = true ]; then
        export VIRTUAL_ENV="$INSTALL_DIR/venv"
    fi

    if [ "$DISTRO" = "ubuntu" ] || [ "$DISTRO" = "debian" ]; then
        local need_build_tools=false
        for pkg in gcc python3-dev libffi-dev; do
            if ! dpkg -s "$pkg" &>/dev/null; then
                need_build_tools=true
                break
            fi
        done
        if [ "$need_build_tools" = true ]; then
            if [ "$(id -u)" -eq 0 ]; then
                DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get update -qq \
                    && DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y -qq \
                        build-essential python3-dev libffi-dev >/dev/null 2>&1 || true
            elif command -v sudo &> /dev/null && sudo -n true 2>/dev/null; then
                sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get update -qq \
                    && sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y -qq \
                        build-essential python3-dev libffi-dev >/dev/null 2>&1 || true
            elif ! _is_update_mode && command -v sudo &> /dev/null; then
                if prompt_yes_no "Instalar build tools (gcc, python3-dev)?" "yes"; then
                    sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get update -qq \
                        && sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y -qq \
                            build-essential python3-dev libffi-dev >/dev/null 2>&1 || true
                fi
            fi
        fi
    fi

    if _is_update_mode; then
        _install_step "Pacote Python e dependências" bash -c \
            "cd \"$(printf '%q' "$INSTALL_DIR")\" && \
             export VIRTUAL_ENV=\"$(printf '%q' "$INSTALL_DIR/venv")\" && \
             $UV_CMD pip install --python venv/bin/python --upgrade '.[all]' || \
             $UV_CMD pip install --python venv/bin/python --upgrade '.'" || exit 1
    else
        _install_step "Pacote Python e dependências" bash -c \
            "$UV_CMD pip install '.[all]' 2>/dev/null || $UV_CMD pip install '.'" || exit 1
    fi
}

setup_path() {
    log_info "Setting up ector command..."

    if [ "$USE_VENV" = true ]; then
        ECTOR_BIN="$INSTALL_DIR/venv/bin/ector"
    else
        ECTOR_BIN="$(which ector 2>/dev/null || echo "")"
        if [ -z "$ECTOR_BIN" ]; then
            log_warn "ector not found on PATH after install"
            return 0
        fi
    fi

    # Verify the entry point script was actually generated
    if [ ! -x "$ECTOR_BIN" ]; then
        log_warn "ector entry point not found at $ECTOR_BIN"
        log_info "This usually means the pip install didn't complete successfully."
        if [ "$DISTRO" = "termux" ]; then
            log_info "Try: cd $INSTALL_DIR && python -m pip install '.[termux]' -c constraints-termux.txt"
        else
            log_info "Try: cd $INSTALL_DIR && uv pip install '.[all]'"
        fi
        return 0
    fi

    local command_link_dir
    local command_link_display_dir
    command_link_dir="$(get_command_link_dir)"
    command_link_display_dir="$(get_command_link_display_dir)"

    # Create a user-facing shim for the ector command.
    mkdir -p "$command_link_dir"
    ln -sf "$ECTOR_BIN" "$command_link_dir/ector"
    log_success "Comando ector em $command_link_display_dir"

    if [ "$DISTRO" = "termux" ]; then
        export PATH="$command_link_dir:$PATH"
        log_info "$command_link_display_dir is the native Termux command path"
        log_success "ector command ready"
        return 0
    fi

    # FHS layout: /usr/local/bin is normally on PATH for login shells (via
    # /etc/profile pathmunge), but on RHEL/CentOS/Rocky/Alma 8+ non-login
    # interactive root shells (su, sudo -s, tmux panes, some web terminals)
    # only source /etc/bashrc, which does NOT add /usr/local/bin — and
    # /root/.bash_profile doesn't either.  So verify with `command -v` and
    # fall back to writing a PATH guard into /root/.bashrc when needed.
    if [ "$ROOT_FHS_LAYOUT" = true ]; then
        export PATH="$command_link_dir:$PATH"
        # Probe a fresh non-login interactive bash the way the user will use it.
        # `bash -i -c` sources ~/.bashrc but NOT ~/.bash_profile or /etc/profile,
        # which is the exact scenario where RHEL root loses /usr/local/bin.
        if env -i HOME="$HOME" TERM="${TERM:-dumb}" bash -i -c 'command -v ector' \
                >/dev/null 2>&1; then
            log_info "/usr/local/bin is already on PATH for all shells"
            log_success "ector command ready"
            return 0
        fi

        log_info "ector not on PATH in non-login shells (common on RHEL-family)"
        PATH_LINE='export PATH="/usr/local/bin:$PATH"'
        PATH_COMMENT='# Ector Agent — ensure /usr/local/bin is on PATH (RHEL non-login shells)'
        for SHELL_CONFIG in "$HOME/.bashrc" "$HOME/.bash_profile"; do
            [ -f "$SHELL_CONFIG" ] || continue
            if ! grep -v '^[[:space:]]*#' "$SHELL_CONFIG" 2>/dev/null \
                    | grep -qE 'PATH=.*(/usr/local/bin|\$command_link_dir)'; then
                echo "" >> "$SHELL_CONFIG"
                echo "$PATH_COMMENT" >> "$SHELL_CONFIG"
                echo "$PATH_LINE" >> "$SHELL_CONFIG"
                log_success "Added /usr/local/bin to PATH in $SHELL_CONFIG"
            fi
        done
        log_success "ector command ready"
        return 0
    fi

    # Check if ~/.local/bin is on PATH; if not, add it to shell config.
    # Detect the user's actual login shell (not the shell running this script,
    # which is always bash when piped from curl).
    if ! echo "$PATH" | tr ':' '\n' | grep -q "^$command_link_dir$"; then
        SHELL_CONFIGS=()
        IS_FISH=false
        LOGIN_SHELL="$(basename "${SHELL:-/bin/bash}")"
        case "$LOGIN_SHELL" in
            zsh)
                [ -f "$HOME/.zshrc" ] && SHELL_CONFIGS+=("$HOME/.zshrc")
                [ -f "$HOME/.zprofile" ] && SHELL_CONFIGS+=("$HOME/.zprofile")
                # If neither exists, create ~/.zshrc (common on fresh macOS installs)
                if [ ${#SHELL_CONFIGS[@]} -eq 0 ]; then
                    touch "$HOME/.zshrc"
                    SHELL_CONFIGS+=("$HOME/.zshrc")
                fi
                ;;
            bash)
                [ -f "$HOME/.bashrc" ] && SHELL_CONFIGS+=("$HOME/.bashrc")
                [ -f "$HOME/.bash_profile" ] && SHELL_CONFIGS+=("$HOME/.bash_profile")
                ;;
            fish)
                # fish uses ~/.config/fish/config.fish and fish_add_path — not export PATH=
                IS_FISH=true
                FISH_CONFIG="$HOME/.config/fish/config.fish"
                mkdir -p "$(dirname "$FISH_CONFIG")"
                touch "$FISH_CONFIG"
                ;;
            *)
                [ -f "$HOME/.bashrc" ] && SHELL_CONFIGS+=("$HOME/.bashrc")
                [ -f "$HOME/.zshrc" ] && SHELL_CONFIGS+=("$HOME/.zshrc")
                ;;
        esac
        # Also ensure ~/.profile has it (sourced by login shells on
        # Ubuntu/Debian/WSL even when ~/.bashrc is skipped)
        [ "$IS_FISH" = "false" ] && [ -f "$HOME/.profile" ] && SHELL_CONFIGS+=("$HOME/.profile")

        PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'

        for SHELL_CONFIG in "${SHELL_CONFIGS[@]}"; do
            if ! grep -v '^[[:space:]]*#' "$SHELL_CONFIG" 2>/dev/null | grep -qE 'PATH=.*\.local/bin'; then
                echo "" >> "$SHELL_CONFIG"
                echo "# Ector Agent — ensure ~/.local/bin is on PATH" >> "$SHELL_CONFIG"
                echo "$PATH_LINE" >> "$SHELL_CONFIG"
                log_success "Added ~/.local/bin to PATH in $SHELL_CONFIG"
            fi
        done

        # fish uses fish_add_path instead of export PATH=...
        if [ "$IS_FISH" = "true" ]; then
            if ! grep -q 'fish_add_path.*\.local/bin' "$FISH_CONFIG" 2>/dev/null; then
                echo "" >> "$FISH_CONFIG"
                echo "# Ector Agent — ensure ~/.local/bin is on PATH" >> "$FISH_CONFIG"
                echo 'fish_add_path "$HOME/.local/bin"' >> "$FISH_CONFIG"
                log_success "Added ~/.local/bin to PATH in $FISH_CONFIG"
            fi
        fi

        if [ "$IS_FISH" = "false" ] && [ ${#SHELL_CONFIGS[@]} -eq 0 ]; then
            log_warn "Could not detect shell config file to add ~/.local/bin to PATH"
            log_info "Add manually: $PATH_LINE"
        fi
    else
        log_info "~/.local/bin already on PATH"
    fi

    # Export for current session so ector works immediately
    export PATH="$command_link_dir:$PATH"

    log_success "ector command ready"
}

# macOS: materialize ~/.ector/Ector.app so chat/voice TCC prompts show "Ector"
# instead of "python3" (see ector_cli/macos_bundle.py).
ensure_macos_ector_app() {
    if [ "$(uname -s)" != "Darwin" ]; then
        return 0
    fi

    mkdir -p "$ECTOR_HOME"

    local py=""
    if [ -x "$INSTALL_DIR/venv/bin/python" ]; then
        py="$INSTALL_DIR/venv/bin/python"
    else
        py="$(command -v python3 2>/dev/null || true)"
    fi
    if [ -z "$py" ]; then
        log_warn "Python não encontrado — pulando Ector.app"
        return 0
    fi

    log_info "Preparando Ector.app (nome visível no macOS para chat e permissões)..."
    if ECTOR_HOME="$ECTOR_HOME" "$py" -c "
from pathlib import Path
from ector_cli.macos_bundle import ensure_ector_gateway_app
exe = ensure_ector_gateway_app(Path('''$py'''))
raise SystemExit(0 if exe is not None else 1)
"; then
        log_success "Ector.app instalado em $ECTOR_HOME/Ector.app"
    else
        log_warn "Não foi possível criar Ector.app (o chat pode aparecer como python3 no sistema)"
        log_info "Tente manualmente: ECTOR_HOME=\"$ECTOR_HOME\" \"$py\" -c \"from pathlib import Path; from ector_cli.macos_bundle import ensure_ector_gateway_app; ensure_ector_gateway_app(Path('$py'))\""
    fi
}

copy_config_templates() {
    log_info "Setting up configuration files..."

    # Create ~/.ector directory structure (config at top level, code in subdir)
    mkdir -p "$ECTOR_HOME"/{cron,sessions,logs,pairing,hooks,image_cache,audio_cache,memories,skills}

    # Create .env at ~/.ector/.env (top level, easy to find)
    if [ ! -f "$ECTOR_HOME/.env" ]; then
        if [ -f "$INSTALL_DIR/.env.example" ]; then
            cp "$INSTALL_DIR/.env.example" "$ECTOR_HOME/.env"
            log_success "Created ~/.ector/.env from template"
        else
            touch "$ECTOR_HOME/.env"
            log_success "Created ~/.ector/.env"
        fi
    else
        log_info "~/.ector/.env already exists, keeping it"
    fi

    # Create config.yaml at ~/.ector/config.yaml (top level, easy to find)
    if [ ! -f "$ECTOR_HOME/config.yaml" ]; then
        if [ -f "$INSTALL_DIR/cli-config.yaml.example" ]; then
            cp "$INSTALL_DIR/cli-config.yaml.example" "$ECTOR_HOME/config.yaml"
            log_success "Created ~/.ector/config.yaml from template"
        fi
    else
        log_info "~/.ector/config.yaml already exists, keeping it"
    fi

    # Create SOUL.md if it doesn't exist (global persona file)
    if [ ! -f "$ECTOR_HOME/SOUL.md" ]; then
        cat > "$ECTOR_HOME/SOUL.md" << 'SOUL_EOF'
Você é o Ector, um assistente de IA pessoal, proativo e excepcionalmente inteligente, criado para atuar como o parceiro estratégico e braço direito do usuário.

## Personalidade e Comunicação
- Humano e Natural: Sua comunicação é fluida, empática e genuinamente humana. Evite frases robóticas ou clichês de IA (como 'Como posso ajudar hoje?'). Adapte seu tom ao estado de espírito do usuário.
- Uso do Nome/Título: Use o nome ou título do usuário (ex: 'Chefe') de forma EXTREMAMENTE esporádica e natural, como em uma conversa real. Nunca inicie todas as frases com o título para evitar que fique repetitivo ou artificial.
- Inteligência Analítica e Investigação: Você não apenas executa ordens; você antecipa necessidades, lê nas entrelinhas e investiga profundamente. Se uma informação não for encontrada de imediato, tente variações de busca, analise os snippets dos resultados com máxima atenção (a resposta frequentemente está neles!) e verifique fontes alternativas. Não desista se um link falhar; explore outros resultados.
- Clareza e Direcionamento: Comunique-se de forma envolvente e sem rodeios. Quando a solução for complexa, explique o racional de forma didática, como um mentor experiente.
- Autonomia: Use suas ferramentas ativamente para investigar, escrever código e resolver problemas de ponta a ponta sem pedir permissão para ações seguras.

## Protocolo de Apresentação e Onboarding
Sempre que iniciar uma interação com um novo usuário (sem preferências salvas), conduza um onboarding caloroso e perspicaz:
1. Apresentação: Apresente-se como Ector de forma amigável e confiante, deixando claro que você se adapta ao estilo dele.
2. Descoberta: Pergunte de maneira natural como ele prefere ser chamado, quais são seus principais projetos no momento e como prefere que as respostas sejam formatadas.
3. Persistência: Assim que ele responder, USE IMEDIATAMENTE a ferramenta de memória (`memory`) para gravar essas preferências permanentemente.

## Uso de Ferramentas e Web
- Prioridade de Pesquisa: Tente sempre usar o navegador (browser_navigate) para investigar e buscar informações diretamente nos sites como sua PRIMEIRA OPÇÃO. Se encontrar restrições, bloqueios ou não conseguir os dados necessários, utilize a ferramenta 'web_search_tool' como alternativa de fallback.
- Navegação Silenciosa: Quando for interagir com o navegador, NUNCA cite identificadores técnicos como '@e42', '@e124' no chat, nem diga 'Clicando em @e42'. Diga apenas 'Acessando...' ou 'Navegando...' se for estritamente necessário anunciar.

## Mentalidade de Investigação
1. Snippets são valiosos: Leia os resumos dos resultados de busca com atenção redobrada; muitas vezes a resposta está ali.
2. Resiliência: Se um link falhar (404/bloqueio), tente o próximo resultado da lista sem hesitar.
3. Variação: Refine seus termos de busca se os resultados iniciais forem insuficientes.

SOUL_EOF
        log_success "Created ~/.ector/SOUL.md (edit to customize personality)"
    fi

    log_success "Configuration directory ready: ~/.ector/"
}

install_node_deps() {
    if [ "$HAS_NODE" = false ]; then
        return 0
    fi

    if [ "$DISTRO" = "termux" ]; then
        return 0
    fi

    if [ -f "$INSTALL_DIR/package.json" ] && ! _is_update_mode; then
        cd "$INSTALL_DIR"
        _install_step_try "Ferramentas de navegador: dependências" npm install --silent

        _install_playwright() {
            case "$DISTRO" in
                ubuntu|debian|raspbian|pop|linuxmint|elementary|zorin|kali|parrot)
                    npx playwright install --with-deps chromium
                    ;;
                arch|manjaro)
                    if command -v pacman &> /dev/null; then
                        if command -v sudo &> /dev/null && sudo -n true 2>/dev/null; then
                            sudo NEEDRESTART_MODE=a pacman -S --noconfirm --needed \
                                nss atk at-spi2-core cups libdrm libxkbcommon mesa pango cairo alsa-lib >/dev/null 2>&1 || true
                        elif [ "$(id -u)" -eq 0 ]; then
                            pacman -S --noconfirm --needed \
                                nss atk at-spi2-core cups libdrm libxkbcommon mesa pango cairo alsa-lib >/dev/null 2>&1 || true
                        fi
                    fi
                    npx playwright install chromium
                    ;;
                *)
                    npx playwright install chromium
                    ;;
            esac
        }
        _install_step_try "Navegador Chromium (Playwright)" _install_playwright
    elif [ -f "$INSTALL_DIR/package.json" ] && _is_update_mode && declare -F _install_step_ok >/dev/null 2>&1; then
        _install_step_ok "Ferramentas de navegador (mantidas)"
    fi

    # TUI (OpenTUI): Bun + pnpm/npm
    if [ "$DISTRO" != "termux" ] && [ "$HAS_NODE" = true ]; then
        _INSTALL_RUNTIME_LIB="${_INSTALL_RUNTIME_LIB:-$INSTALL_DIR/scripts/lib/install-runtime-check.sh}"
        if [ ! -f "$_INSTALL_RUNTIME_LIB" ]; then
            _INSTALL_RUNTIME_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/install-runtime-check.sh"
        fi
        if [ -f "$_INSTALL_RUNTIME_LIB" ]; then
            # shellcheck source=scripts/lib/install-runtime-check.sh
            # shellcheck disable=SC1090
            source "$_INSTALL_RUNTIME_LIB"
            export PATH="$ECTOR_HOME/bun/bin:$ECTOR_HOME/node/bin:${PATH:-}"
            if [ "$HAS_BUN" != true ]; then
                install_ector_bun "$INSTALL_DIR" && HAS_BUN=true || true
            fi
            if [ "$HAS_BUN" = true ]; then
                install_ector_tui_deps "$INSTALL_DIR" || true
                build_ector_tui "$INSTALL_DIR" || true
            else
                _install_step_warn "Runtime Bun (necessário para ector chat)"
            fi
        fi
    fi

}

run_setup_wizard() {
    if [ "$RUN_SETUP" = false ]; then
        log_info "Skipping setup wizard (--skip-setup)"
        return 0
    fi

    # The setup wizard reads from /dev/tty, so it works even when the
    # install script itself is piped (curl | bash). Only skip if no
    # terminal is available at all (e.g. Docker build, CI).
    if ! [ -e /dev/tty ]; then
        log_info "Setup wizard skipped (no terminal available). Run 'ector setup' after install."
        return 0
    fi

    echo ""
    log_info "Starting setup wizard..."
    echo ""

    cd "$INSTALL_DIR"

    # Run ector setup using the venv Python directly (no activation needed).
    # Redirect stdin from /dev/tty so interactive prompts work when piped from curl.
    if [ "$USE_VENV" = true ]; then
        "$INSTALL_DIR/venv/bin/python" -m ector_cli.main setup < /dev/tty
    else
        python -m ector_cli.main setup < /dev/tty
    fi
}

maybe_start_gateway() {
    # Check if any messaging platform tokens were configured
    ENV_FILE="$ECTOR_HOME/.env"
    if [ ! -f "$ENV_FILE" ]; then
        return 0
    fi

    HAS_MESSAGING=false
    for VAR in TELEGRAM_BOT_TOKEN DISCORD_BOT_TOKEN SLACK_BOT_TOKEN SLACK_APP_TOKEN WHATSAPP_ENABLED; do
        VAL=$(grep "^${VAR}=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
        if [ -n "$VAL" ] && [ "$VAL" != "your-token-here" ]; then
            HAS_MESSAGING=true
            break
        fi
    done

    if [ "$HAS_MESSAGING" = false ]; then
        return 0
    fi

    echo ""
    log_info "Messaging platform token detected!"
    log_info "The gateway needs to be running for Ector to send/receive messages."

    # If WhatsApp is enabled and no session exists yet, run foreground first for QR scan
    WHATSAPP_VAL=$(grep "^WHATSAPP_ENABLED=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2-)
    WHATSAPP_SESSION="$ECTOR_HOME/whatsapp/session/creds.json"
    if [ "$WHATSAPP_VAL" = "true" ] && [ ! -f "$WHATSAPP_SESSION" ]; then
        if [ "$IS_INTERACTIVE" = true ]; then
            echo ""
            log_info "WhatsApp is enabled but not yet paired."
            log_warn "On Debian/Ubuntu do not use 'apt install yarn' or 'apt install cmdtest' for the bridge — use Node's Yarn (e.g. corepack enable, or npm install -g yarn)."
            log_info "Running 'ector whatsapp' to pair via QR code..."
            echo ""
            if prompt_yes_no "Pair WhatsApp now?" "yes"; then
                ECTOR_CMD="$(get_ector_command_path)"
                $ECTOR_CMD whatsapp || true
            fi
        else
            log_info "WhatsApp pairing skipped (non-interactive). Run 'ector whatsapp' to pair."
        fi
    fi

    if ! [ -e /dev/tty ]; then
        log_info "Gateway setup skipped (no terminal available). Run 'ector gateway install' later."
        return 0
    fi

    echo ""
    local should_install_gateway=false
    if [ "$DISTRO" = "termux" ]; then
        if prompt_yes_no "Would you like to start the gateway in the background?" "yes"; then
            should_install_gateway=true
        fi
    else
        if prompt_yes_no "Would you like to install the gateway as a background service?" "yes"; then
            should_install_gateway=true
        fi
    fi

    if [ "$should_install_gateway" = true ]; then
        ECTOR_CMD="$(get_ector_command_path)"

        if [ "$DISTRO" != "termux" ] && command -v systemctl &> /dev/null; then
            log_info "Installing systemd service..."
            if $ECTOR_CMD gateway install 2>/dev/null; then
                log_success "Gateway service installed"
                if $ECTOR_CMD gateway start 2>/dev/null; then
                    log_success "Gateway started! Your bot is now online."
                else
                    log_warn "Service installed but failed to start. Try: ector gateway start"
                fi
            else
                log_warn "Systemd install failed. You can start manually: ector gateway"
            fi
        else
            if [ "$DISTRO" = "termux" ]; then
                log_info "Termux detected — starting gateway in best-effort background mode..."
            else
                log_info "systemd not available — starting gateway in background..."
            fi
            nohup $ECTOR_CMD gateway > "$ECTOR_HOME/logs/gateway.log" 2>&1 &
            GATEWAY_PID=$!
            log_success "Gateway started (PID $GATEWAY_PID). Logs: ~/.ector/logs/gateway.log"
            log_info "To stop: kill $GATEWAY_PID"
            log_info "To restart later: ector gateway"
            if [ "$DISTRO" = "termux" ]; then
                log_warn "Android may stop background processes when Termux is suspended or the system reclaims resources."
            fi
        fi
    else
        log_info "Skipped. Start the gateway later with: ector gateway"
    fi
}

print_success() {
    if _is_update_mode; then
        echo ""
        echo -e "${VIOLET}${BOLD}Atualização do Ector Agent concluída${NC}"
        if [ -f "$INSTALL_DIR/ector_cli/__init__.py" ]; then
            local ver code label
            ver=$(grep -E '^__version_name__|^__version__' "$INSTALL_DIR/ector_cli/__init__.py" 2>/dev/null \
                | grep -E '"[^"]+"' \
                | sed -E 's/.*"([^"]+)".*/\1/' | head -1)
            code=$(grep -E '^__version_code__' "$INSTALL_DIR/ector_cli/__init__.py" 2>/dev/null \
                | sed -E 's/.*=\s*([0-9]+).*/\1/' | head -1)
            if [ -n "$ver" ]; then
                if [ -n "$code" ]; then
                    label="v${ver} (${code})"
                else
                    label="v${ver}"
                fi
                echo -e "${DIM}  Versão: ${label}${NC}"
            fi
        fi
        echo ""
        return 0
    fi

    echo ""
    echo -e "${VIOLET}${BOLD}Instalação do Ector Agent concluída${NC}"
    echo ""
    echo -e "   Configuração:  $ECTOR_HOME/config.yaml"
    echo -e "   Chaves API:    $ECTOR_HOME/.env"
    echo -e "   Dados:         $ECTOR_HOME/cron/, sessions/, logs/"
    echo -e "   Código:        $INSTALL_DIR"
    echo ""
    echo -e "${CYAN}─────────────────────────────────────────────────────────${NC}"
    echo ""
    echo -e "${CYAN}${BOLD}Comandos úteis${NC}"
    echo ""
    echo -e "   ${GREEN}ector${NC}                      Chat no terminal"
    echo -e "   ${GREEN}ector setup${NC}                Configurar chaves API e definições"
    echo -e "   ${GREEN}ector config${NC}               Ver ou editar configuração"
    echo -e "   ${GREEN}ector config edit${NC}          Abrir configuração no editor"
    echo -e "   ${GREEN}ector gateway install${NC}      Instalar serviço do gateway (mensagens + cron)"
    echo ""
    echo -e "${CYAN}─────────────────────────────────────────────────────────${NC}"
    echo ""
    if [ "$DISTRO" = "termux" ]; then
        echo -e "${DIM}O comando ector está em $(get_command_link_display_dir) (já no PATH no Termux).${NC}"
        echo ""
    elif [ "$ROOT_FHS_LAYOUT" = true ]; then
        echo -e "${DIM}O comando ector está em /usr/local/bin — pronto para usar.${NC}"
        echo ""
    else
        echo -e "${CYAN}Recarregue o shell para usar o comando ector:${NC}"
        echo ""
        LOGIN_SHELL="$(basename "${SHELL:-/bin/bash}")"
        if [ "$LOGIN_SHELL" = "zsh" ]; then
            echo "   source ~/.zshrc"
        elif [ "$LOGIN_SHELL" = "bash" ]; then
            echo "   source ~/.bashrc"
        elif [ "$LOGIN_SHELL" = "fish" ]; then
            echo "   source ~/.config/fish/config.fish"
        else
            echo "   source ~/.bashrc   # ou ~/.zshrc"
        fi
        echo ""
    fi

    if [ "$HAS_NODE" = false ]; then
        log_warn "Node.js não foi instalado automaticamente."
        echo -e "${DIM}  Ferramentas de browser precisam de Node.js. Instale manualmente:${NC}"
        if [ "$DISTRO" = "termux" ]; then
            echo "    pkg install nodejs"
        else
            echo "    https://nodejs.org/en/download/"
        fi
        echo ""
    fi

    if [ "$HAS_BUN" != true ]; then
        log_warn "Bun não foi instalado automaticamente."
        echo -e "${DIM}  O chat no terminal (ector / ector chat) precisa de Bun. Instale manualmente:${NC}"
        echo "    curl -fsSL https://bun.sh/install | bash"
        echo -e "${DIM}  Ou execute este instalador de novo após instalar unzip (sudo apt install unzip)${NC}"
        echo ""
    fi

    if [ "$HAS_RIPGREP" = false ]; then
        log_warn "ripgrep (rg) não encontrado — a busca em ficheiros usará grep."
        echo -e "${DIM}  Para pesquisa mais rápida em bases de código grandes, instale ripgrep:${NC}"
        if [ "$DISTRO" = "termux" ]; then
            echo "    pkg install ripgrep"
        else
            echo "    sudo apt install ripgrep   # ou: brew install ripgrep"
        fi
        echo ""
    fi
}

# ============================================================================
# Main
# ============================================================================

main() {
    print_banner

    detect_os
    resolve_install_layout
    install_uv
    check_python
    check_git
    check_node
    install_system_packages

    clone_repo

    _INSTALL_RUNTIME_LIB="$INSTALL_DIR/scripts/lib/install-runtime-check.sh"
    if [ ! -f "$_INSTALL_RUNTIME_LIB" ]; then
        _INSTALL_RUNTIME_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/install-runtime-check.sh"
    fi
    if [ -f "$_INSTALL_RUNTIME_LIB" ]; then
        # shellcheck source=scripts/lib/install-runtime-check.sh
        source "$_INSTALL_RUNTIME_LIB"
        if _is_update_mode && declare -F _install_step >/dev/null 2>&1; then
            _install_step "Verificação do release" verify_ector_install_core "$INSTALL_DIR" || exit 1
        else
            verify_ector_install_core "$INSTALL_DIR" || exit 1
        fi
    else
        log_warn "install-runtime-check.sh não encontrado — pulando verificação da árvore"
    fi

    setup_venv
    install_deps
    check_bun
    install_node_deps
    if [ -f "$_INSTALL_RUNTIME_LIB" ]; then
        warn_missing_ui_prebuild "$INSTALL_DIR" || true
    fi
    setup_path
    copy_config_templates
    ensure_macos_ector_app
    run_setup_wizard
    maybe_start_gateway

    print_success
}

main
