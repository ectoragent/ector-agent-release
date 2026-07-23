#!/bin/bash
# ============================================================================
# Ector Agent Install Script
# ============================================================================
# Quick install for developers who cloned the repo manually.
# Uses uv for desktop/server setup and Python's stdlib venv + pip on Termux.
#
# Usage:
#   ./install.sh
#
# This script:
# 1. Detects desktop/server vs Android/Termux install path
# 2. Creates a Python 3.11 virtual environment
# 3. Installs the appropriate dependency set for the platform
# 4. Creates .env from template (if not exists)
# 5. Symlinks the 'ector' CLI command into a user-facing bin dir
# 6. Runs the setup wizard (optional)
# ============================================================================

set -e

# Colors
CYAN='\033[38;2;0;209;255m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

_IO_LIB="$SCRIPT_DIR/scripts/lib/install-output.sh"
if [ -f "$_IO_LIB" ]; then
    # shellcheck source=scripts/lib/install-output.sh
    source "$_IO_LIB"
fi

PYTHON_VERSION="3.11"
IS_INTERACTIVE=false
if [ -t 0 ]; then
    IS_INTERACTIVE=true
fi

is_termux() {
    [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux/files/usr"* ]]
}

get_command_link_dir() {
    if is_termux && [ -n "${PREFIX:-}" ]; then
        echo "$PREFIX/bin"
    else
        echo "$HOME/.local/bin"
    fi
}

get_command_link_display_dir() {
    if is_termux && [ -n "${PREFIX:-}" ]; then
        echo '$PREFIX/bin'
    else
        echo '~/.local/bin'
    fi
}

echo ""
echo -e "${CYAN}Instalação do Ector Agent${NC}"
echo ""

# ============================================================================
# Install / locate uv
# ============================================================================

UV_CMD=""
if is_termux; then
    :
else
    if command -v uv &> /dev/null; then
        UV_CMD="uv"
    elif [ -x "$HOME/.local/bin/uv" ]; then
        UV_CMD="$HOME/.local/bin/uv"
    elif [ -x "$HOME/.cargo/bin/uv" ]; then
        UV_CMD="$HOME/.cargo/bin/uv"
    fi

    if [ -z "$UV_CMD" ]; then
        if curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1; then
            if [ -x "$HOME/.local/bin/uv" ]; then
                UV_CMD="$HOME/.local/bin/uv"
            elif [ -x "$HOME/.cargo/bin/uv" ]; then
                UV_CMD="$HOME/.cargo/bin/uv"
            fi
        fi
    fi

    if [ -z "$UV_CMD" ]; then
        echo -e "${RED}✗${NC} uv — instale em https://docs.astral.sh/uv/"
        exit 1
    fi
    _install_step_ok "Gerenciador Python (uv)"
fi

# ============================================================================
# Python check (uv can provision it automatically)
# ============================================================================

if is_termux; then
    if command -v python >/dev/null 2>&1; then
        PYTHON_PATH="$(command -v python)"
        if ! "$PYTHON_PATH" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            echo -e "${RED}✗${NC} Python 3.11+ (Termux: pkg install python)"
            exit 1
        fi
    else
        echo -e "${RED}✗${NC} Python (Termux: pkg install python)"
        exit 1
    fi
else
    if ! $UV_CMD python find "$PYTHON_VERSION" &> /dev/null; then
        $UV_CMD python install "$PYTHON_VERSION" >/dev/null 2>&1
    fi
    PYTHON_PATH=$($UV_CMD python find "$PYTHON_VERSION")
fi
_install_step_ok "Python $PYTHON_VERSION"

# ============================================================================
# Virtual environment
# ============================================================================

[ -d "venv" ] && rm -rf venv

if is_termux; then
    "$PYTHON_PATH" -m venv venv
else
    $UV_CMD venv venv --python "$PYTHON_VERSION" >/dev/null 2>&1
fi
_install_step_ok "Ambiente virtual Python"

export VIRTUAL_ENV="$SCRIPT_DIR/venv"
SETUP_PYTHON="$SCRIPT_DIR/venv/bin/python"

# ============================================================================
# Dependencies
# ============================================================================

if is_termux; then
    export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk 2>/dev/null || printf '%s' "${ANDROID_API_LEVEL:-}")"
    _install_step "Pacote Python e dependências" bash -c "
        \"\$1\" -m pip install --upgrade pip setuptools wheel >/dev/null &&
        \"\$1\" -m pip install -e \".[termux]\" -c constraints-termux.txt 2>/dev/null ||
        \"\$1\" -m pip install -e \".\" -c constraints-termux.txt
    " bash "$SETUP_PYTHON"
else
    _install_step "Pacote Python e dependências" bash -c \
        "$UV_CMD pip install -e \".[all]\" || $UV_CMD pip install -e \".\""
fi

# ============================================================================
# Submodules (terminal backend + RL training)
# ============================================================================

if ! is_termux && [ -d "tinker-atropos" ] && [ -f "tinker-atropos/pyproject.toml" ]; then
    _install_step_try "Treino RL (opcional)" $UV_CMD pip install -e "./tinker-atropos" || true
elif ! is_termux && [ ! -d "tinker-atropos" ]; then
    _install_verbose && _install_step_warn "Treino RL (submódulo opcional ausente)"
fi

# ============================================================================
# Optional: ripgrep (for faster file search)
# ============================================================================

if ! command -v rg &> /dev/null && [ "$IS_INTERACTIVE" = true ]; then
    read -p "Instalar ripgrep? (s/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[YySs]$ ]] || [[ -z $REPLY ]]; then
        INSTALLED=false
        if is_termux; then
            pkg install -y ripgrep >/dev/null 2>&1 && INSTALLED=true
        elif command -v sudo &> /dev/null && sudo -n true 2>/dev/null && command -v apt &> /dev/null; then
            sudo apt install -y ripgrep >/dev/null 2>&1 && INSTALLED=true
        elif command -v brew &> /dev/null; then
            brew install ripgrep >/dev/null 2>&1 && INSTALLED=true
        fi
        [ "$INSTALLED" = true ] && _install_step_ok "Busca em arquivos (ripgrep)"
    fi
elif command -v rg &> /dev/null; then
    _install_step_ok "Busca em arquivos (ripgrep)"
fi

# ============================================================================
# Environment file
# ============================================================================

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    _install_step_ok "Modelo de chaves API (.env)"
fi

# ============================================================================
# PATH setup — symlink ector into a user-facing bin dir
# ============================================================================

ECTOR_BIN="$SCRIPT_DIR/venv/bin/ector"
COMMAND_LINK_DIR="$(get_command_link_dir)"
COMMAND_LINK_DISPLAY_DIR="$(get_command_link_display_dir)"
mkdir -p "$COMMAND_LINK_DIR"
ln -sf "$ECTOR_BIN" "$COMMAND_LINK_DIR/ector"
_install_step_ok "Comando ector em $COMMAND_LINK_DISPLAY_DIR"

if is_termux; then
    export PATH="$COMMAND_LINK_DIR:$PATH"
else
    SHELL_CONFIG=""
    if [[ "$SHELL" == *"zsh"* ]]; then
        SHELL_CONFIG="$HOME/.zshrc"
    elif [[ "$SHELL" == *"bash"* ]]; then
        SHELL_CONFIG="$HOME/.bashrc"
        [ ! -f "$SHELL_CONFIG" ] && SHELL_CONFIG="$HOME/.bash_profile"
    else
        if [ -f "$HOME/.zshrc" ]; then
            SHELL_CONFIG="$HOME/.zshrc"
        elif [ -f "$HOME/.bashrc" ]; then
            SHELL_CONFIG="$HOME/.bashrc"
        elif [ -f "$HOME/.bash_profile" ]; then
            SHELL_CONFIG="$HOME/.bash_profile"
        fi
    fi

    if [ -n "$SHELL_CONFIG" ]; then
        touch "$SHELL_CONFIG" 2>/dev/null || true
        if ! echo "$PATH" | tr ':' '\n' | grep -q "^$HOME/.local/bin$"; then
            if ! grep -q '\.local/bin' "$SHELL_CONFIG" 2>/dev/null; then
                echo "" >> "$SHELL_CONFIG"
                echo "# Ector Agent — ensure ~/.local/bin is on PATH" >> "$SHELL_CONFIG"
                echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_CONFIG"
                _install_step_ok "Terminal reconhece ~/.local/bin"
            fi
        fi
    fi
fi

# ============================================================================
# Node.js (web build / WhatsApp bridge)
# ============================================================================
if ! is_termux; then
    NB_HELPER="$SCRIPT_DIR/scripts/lib/node-bootstrap.sh"
    if [ -f "$NB_HELPER" ]; then
        set +e
        export ECTOR_INSTALL_COMPACT=1
        # shellcheck source=scripts/lib/node-bootstrap.sh
        source "$NB_HELPER"
        ensure_node >/dev/null 2>&1
        NB_RC=$?
        set -e
        if [ "$NB_RC" -eq 0 ] && command -v node &>/dev/null; then
            _install_step_ok "Node.js (ferramentas web e WhatsApp)"
        else
            _install_step_warn "Node.js não encontrado (ferramentas web podem falhar)"
        fi
    fi

    _RUNTIME_CHECK="$SCRIPT_DIR/scripts/lib/install-runtime-check.sh"
    if [ -f "$_RUNTIME_CHECK" ]; then
        # shellcheck source=scripts/lib/install-runtime-check.sh
        source "$_RUNTIME_CHECK"
        verify_ector_install_core "$SCRIPT_DIR" || exit 1
        warn_missing_ui_prebuild "$SCRIPT_DIR" || true
    fi
fi

# ============================================================================
# Done
# ============================================================================

echo ""
echo -e "${CYAN}Instalação concluída${NC}"
echo ""
echo "Próximos passos:"
echo ""

if is_termux; then
    echo "  1. Execute o assistente de configuração para definir as chaves API:"
    echo "     ector setup"
    echo ""
    echo "  2. Comece a conversar:"
    echo "     ector"
    echo ""
else
    echo "  1. Recarregue seu shell:"
    echo "     source $SHELL_CONFIG"
    echo ""
    echo "  2. Execute o assistente de configuração para definir chaves API:"
    echo "     ector setup"
    echo ""
    echo "  3. Comece a conversar:"
    echo "     ector"
    echo ""
fi
echo "Outros comandos:"
echo "  ector status        # Verifica a configuração"
if is_termux; then
    echo "  ector gateway       # Executa o gateway em primeiro plano"
else
    echo "  ector gateway install # Instala o serviço do gateway (mensagens + cron)"
fi
echo "  ector cron list     # Exibe as tarefas agendadas"
echo "  ector doctor        # Diagnostica problemas"
echo ""

# Ask if they want to run setup wizard now
if [ "$IS_INTERACTIVE" = true ]; then
    read -p "Mas se preferir, posso executar o assistente de configuração para você? (s/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[YySs]$ ]] || [[ -z $REPLY ]]; then
        echo ""
        # Run directly with venv Python (no activation needed)
        "$SCRIPT_DIR/venv/bin/python" -m ector_cli.main setup
    fi
else
    echo -e "${YELLOW}▲${NC} Modo não-interativo — pulando execução automática do assistente (rode depois: ector setup)"
fi

