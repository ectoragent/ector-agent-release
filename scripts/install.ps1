# ============================================================================
# Ector Agent Installer for Windows
# ============================================================================
# Installation script for Windows (PowerShell).
# Uses uv for fast Python provisioning and package management.
#
# Usage:
#   curl -fsSL https://ector.cc/install.ps1 | powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://ector.cc/install.ps1 | iex"
#
# Or download and run with options:
#   .\install.ps1 -NoVenv -SkipSetup
#   .\install.ps1 -Help
#
# ============================================================================

param(
    [switch]$NoVenv,
    [switch]$SkipSetup,
    [switch]$Help,
    [string]$Branch = "main",
    [string]$EctorHome = "",
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Write-Host @"
Instalação do Ector Agent (Windows)

Usage: .\install.ps1 [OPTIONS]

Options:
  -NoVenv       Não criar ambiente virtual
  -SkipSetup    Pular assistente de configuração interativo
  -Branch NAME  Branch git a instalar (padrão: main)
  -EctorHome    Diretório de dados (padrão: %LOCALAPPDATA%\ector ou `$env:ECTOR_HOME)
  -InstallDir   Diretório do código (padrão: <EctorHome>\ector-agent ou `$env:ECTOR_INSTALL_DIR)
  -Help         Mostrar esta ajuda

Variáveis de ambiente:
  ECTOR_HOME              Diretório de dados
  ECTOR_INSTALL_DIR       Diretório do checkout git
  ECTOR_NONINTERACTIVE    1 = modo atualização/não interativo (sem prompts)
  ECTOR_INSTALL_COMPACT   1 = saída compacta (uma linha por passo)
  ECTOR_INSTALL_REPO      URL HTTPS do repositório release
  ECTOR_INSTALL_REPO_SSH  URL SSH do repositório release
"@
    return
}

# Resolve paths after param() so env vars override defaults.
if (-not $EctorHome) {
    $EctorHome = if ($env:ECTOR_HOME) { $env:ECTOR_HOME } else { Join-Path $env:LOCALAPPDATA "ector" }
}
if (-not $InstallDir) {
    $InstallDir = if ($env:ECTOR_INSTALL_DIR) { $env:ECTOR_INSTALL_DIR } else { Join-Path $EctorHome "ector-agent" }
}

$IsInteractive = [Environment]::UserInteractive -and ($Host.Name -ne "ServerRemoteHost")
if ($env:ECTOR_NONINTERACTIVE) {
    $IsInteractive = $false
}
$IsUpdateMode = [bool]$env:ECTOR_NONINTERACTIVE
$IsCompact = ($env:ECTOR_INSTALL_COMPACT -eq "1") -or ($env:ECTOR_INSTALL_COMPACT -eq "true")

$script:EctorBin = $null
$script:EctorCmd = $null

# ============================================================================
# Configuration
# ============================================================================

if ($env:ECTOR_INSTALL_REPO_SSH) {
    $RepoUrlSsh = $env:ECTOR_INSTALL_REPO_SSH
} else {
    $RepoUrlSsh = "git@github.com:ectoragent/ector-agent-release.git"
}
if ($env:ECTOR_INSTALL_REPO) {
    $RepoUrlHttps = $env:ECTOR_INSTALL_REPO
} else {
    $RepoUrlHttps = "https://github.com/ectoragent/ector-agent-release.git"
}
$PythonVersion = "3.11"
$NodeVersion = "22"

# ============================================================================
# Helper functions
# ============================================================================

function Write-Banner {
    if ($IsUpdateMode) { return }
    Write-Host ""
    Write-Host "Instalação do Ector Agent" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Info {
    param([string]$Message)
    if ($IsCompact) { return }
    Write-Host "→ $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    if ($IsCompact) {
        Write-Host "✔ $Message" -ForegroundColor Green
    } else {
        Write-Host "✅ $Message" -ForegroundColor Green
    }
}

function Write-Warn {
    param([string]$Message)
    Write-Host "▲ $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
}

function Prompt-YesNo {
    param(
        [string]$Question,
        [bool]$DefaultYes = $true
    )
    if (-not $IsInteractive) { return $DefaultYes }
    $suffix = "(s/n)"
    $response = Read-Host "$Question $suffix"
    if ([string]::IsNullOrWhiteSpace($response)) { return $DefaultYes }
    return ($response -match '^[SsYy]')
}

function Get-EctorCommandPath {
    if ($script:EctorCmd -and (Test-Path $script:EctorCmd)) {
        return $script:EctorCmd
    }
    if (-not $NoVenv) {
        $venvEctor = Join-Path $InstallDir "venv\Scripts\ector.exe"
        if (Test-Path $venvEctor) {
            $script:EctorCmd = $venvEctor
            return $venvEctor
        }
    }
    $cmd = Get-Command ector -ErrorAction SilentlyContinue
    if ($cmd) {
        $script:EctorCmd = $cmd.Source
        return $cmd.Source
    }
    return "ector"
}

function Test-InstallCore {
    $required = @(
        "tools\environments\__init__.py",
        "frontend\tui\packages\ector-tui\package.json",
        "run_agent.py"
    )
    $missing = @()
    foreach ($rel in $required) {
        if (-not (Test-Path (Join-Path $InstallDir $rel))) {
            $missing += $rel
        }
    }
    if ($missing.Count -eq 0) { return $true }

    Write-Err "Instalação incompleta — faltam ficheiros de runtime:"
    foreach ($rel in $missing) {
        Write-Host "  - $rel" -ForegroundColor Red
    }
    Write-Err "O pacote clonado (ector-agent-release) está incompleto."
    Write-Info "Publique um release corrigido (sync_public_release) ou instale a partir do repo completo."
    return $false
}

# ============================================================================
# Dependency checks
# ============================================================================

function Install-Uv {
    Write-Info "Checking for uv package manager..."
    
    # Check if uv is already available
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $version = uv --version
        $script:UvCmd = "uv"
        Write-Success "uv found ($version)"
        return $true
    }
    
    # Check common install locations
    $uvPaths = @(
        "$env:USERPROFILE\.local\bin\uv.exe",
        "$env:USERPROFILE\.cargo\bin\uv.exe"
    )
    foreach ($uvPath in $uvPaths) {
        if (Test-Path $uvPath) {
            $script:UvCmd = $uvPath
            $version = & $uvPath --version
            Write-Success "uv found at $uvPath ($version)"
            return $true
        }
    }
    
    # Install uv
    Write-Info "Installing uv (fast Python package manager)..."
    try {
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" 2>&1 | Out-Null
        
        # Find the installed binary
        $uvExe = "$env:USERPROFILE\.local\bin\uv.exe"
        if (-not (Test-Path $uvExe)) {
            $uvExe = "$env:USERPROFILE\.cargo\bin\uv.exe"
        }
        if (-not (Test-Path $uvExe)) {
            # Refresh PATH and try again
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
            if (Get-Command uv -ErrorAction SilentlyContinue) {
                $uvExe = (Get-Command uv).Source
            }
        }
        
        if (Test-Path $uvExe) {
            $script:UvCmd = $uvExe
            $version = & $uvExe --version
            Write-Success "uv installed ($version)"
            return $true
        }
        
        Write-Err "uv installed but not found on PATH"
        Write-Info "Try restarting your terminal and re-running"
        return $false
    } catch {
        Write-Err "Failed to install uv"
        Write-Info "Install manually: https://docs.astral.sh/uv/getting-started/installation/"
        return $false
    }
}

function Test-Python {
    Write-Info "Checking Python $PythonVersion..."
    
    # Let uv find or install Python
    try {
        $pythonPath = & $UvCmd python find $PythonVersion 2>$null
        if ($pythonPath) {
            $ver = & $pythonPath --version 2>$null
            Write-Success "Python found: $ver"
            return $true
        }
    } catch { }
    
    # Python not found — use uv to install it (no admin needed!)
    Write-Info "Python $PythonVersion not found, installing via uv..."
    try {
        $uvOutput = & $UvCmd python install $PythonVersion 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pythonPath = & $UvCmd python find $PythonVersion 2>$null
            if ($pythonPath) {
                $ver = & $pythonPath --version 2>$null
                Write-Success "Python installed: $ver"
                return $true
            }
        } else {
            Write-Warn "uv python install output:"
            Write-Host $uvOutput -ForegroundColor DarkGray
        }
    } catch {
        Write-Warn "uv python install error: $_"
    }

    # Fallback: check if ANY Python 3.10+ is already available on the system
    Write-Info "Trying to find any existing Python 3.10+..."
    foreach ($fallbackVer in @("3.12", "3.13", "3.10")) {
        try {
            $pythonPath = & $UvCmd python find $fallbackVer 2>$null
            if ($pythonPath) {
                $ver = & $pythonPath --version 2>$null
                Write-Success "Found fallback: $ver"
                $script:PythonVersion = $fallbackVer
                return $true
            }
        } catch { }
    }

    # Fallback: try system python
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $sysVer = python --version 2>$null
        if ($sysVer -match "3\.(1[0-9]|[1-9][0-9])") {
            Write-Success "Using system Python: $sysVer"
            return $true
        }
    }
    
    Write-Err "Failed to install Python $PythonVersion"
    Write-Info "Install Python 3.11 manually, then re-run this script:"
    Write-Info "  https://www.python.org/downloads/"
    Write-Info "  Or: winget install Python.Python.3.11"
    return $false
}

function Test-Git {
    Write-Info "Checking Git..."
    
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $version = git --version
        Write-Success "Git found ($version)"
        return $true
    }
    
    Write-Err "Git not found"
    Write-Info "Please install Git from:"
    Write-Info "  https://git-scm.com/download/win"
    return $false
}

function Test-Node {
    Write-Info "Checking Node.js (for browser tools)..."

    if (Get-Command node -ErrorAction SilentlyContinue) {
        $version = node --version
        Write-Success "Node.js $version found"
        $script:HasNode = $true
        return $true
    }

    # Check our own managed install from a previous run
    $managedNode = "$EctorHome\node\node.exe"
    if (Test-Path $managedNode) {
        $version = & $managedNode --version
        $env:Path = "$EctorHome\node;$env:Path"
        Write-Success "Node.js $version found (Ector-managed)"
        $script:HasNode = $true
        return $true
    }

    Write-Info "Node.js not found — installing Node.js $NodeVersion LTS..."

    # Try winget first (cleanest on modern Windows)
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Info "Installing via winget..."
        try {
            winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
            # Refresh PATH
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
            if (Get-Command node -ErrorAction SilentlyContinue) {
                $version = node --version
                Write-Success "Node.js $version installed via winget"
                $script:HasNode = $true
                return $true
            }
        } catch { }
    }

    # Fallback: download binary zip to ~/.ector/node/
    Write-Info "Downloading Node.js $NodeVersion binary..."
    try {
        $arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
        $indexUrl = "https://nodejs.org/dist/latest-v${NodeVersion}.x/"
        $indexPage = Invoke-WebRequest -Uri $indexUrl -UseBasicParsing
        $zipName = ($indexPage.Content | Select-String -Pattern "node-v${NodeVersion}\.\d+\.\d+-win-${arch}\.zip" -AllMatches).Matches[0].Value

        if ($zipName) {
            $downloadUrl = "${indexUrl}${zipName}"
            $tmpZip = "$env:TEMP\$zipName"
            $tmpDir = "$env:TEMP\ector-node-extract"

            Invoke-WebRequest -Uri $downloadUrl -OutFile $tmpZip -UseBasicParsing
            if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }
            Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force

            $extractedDir = Get-ChildItem $tmpDir -Directory | Select-Object -First 1
            if ($extractedDir) {
                if (Test-Path "$EctorHome\node") { Remove-Item -Recurse -Force "$EctorHome\node" }
                Move-Item $extractedDir.FullName "$EctorHome\node"
                $env:Path = "$EctorHome\node;$env:Path"

                $version = & "$EctorHome\node\node.exe" --version
                Write-Success "Node.js $version installed to ~/.ector/node/"
                $script:HasNode = $true

                Remove-Item -Force $tmpZip -ErrorAction SilentlyContinue
                Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
                return $true
            }
        }
    } catch {
        Write-Warn "Download failed: $_"
    }

    Write-Warn "Could not auto-install Node.js"
    Write-Info "Install manually: https://nodejs.org/en/download/"
    $script:HasNode = $false
    return $true
}

function Install-SystemPackages {
    $script:HasRipgrep = $false
    $script:HasFfmpeg = $false
    $needRipgrep = $false
    $needFfmpeg = $false

    Write-Info "Checking ripgrep (fast file search)..."
    if (Get-Command rg -ErrorAction SilentlyContinue) {
        $version = rg --version | Select-Object -First 1
        Write-Success "$version found"
        $script:HasRipgrep = $true
    } else {
        $needRipgrep = $true
    }

    Write-Info "Checking ffmpeg (TTS voice messages)..."
    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
        Write-Success "ffmpeg found"
        $script:HasFfmpeg = $true
    } else {
        $needFfmpeg = $true
    }

    if (-not $needRipgrep -and -not $needFfmpeg) { return }

    # Build description and package lists for each package manager
    $descParts = @()
    $wingetPkgs = @()
    $chocoPkgs = @()
    $scoopPkgs = @()

    if ($needRipgrep) {
        $descParts += "ripgrep for faster file search"
        $wingetPkgs += "BurntSushi.ripgrep.MSVC"
        $chocoPkgs += "ripgrep"
        $scoopPkgs += "ripgrep"
    }
    if ($needFfmpeg) {
        $descParts += "ffmpeg for TTS voice messages"
        $wingetPkgs += "Gyan.FFmpeg"
        $chocoPkgs += "ffmpeg"
        $scoopPkgs += "ffmpeg"
    }

    $description = $descParts -join " and "
    $hasWinget = Get-Command winget -ErrorAction SilentlyContinue
    $hasChoco = Get-Command choco -ErrorAction SilentlyContinue
    $hasScoop = Get-Command scoop -ErrorAction SilentlyContinue

    # Try winget first (most common on modern Windows)
    if ($hasWinget) {
        Write-Info "Installing $description via winget..."
        foreach ($pkg in $wingetPkgs) {
            try {
                winget install $pkg --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
            } catch { }
        }
        # Refresh PATH and recheck
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
        if ($needRipgrep -and (Get-Command rg -ErrorAction SilentlyContinue)) {
            Write-Success "ripgrep installed"
            $script:HasRipgrep = $true
            $needRipgrep = $false
        }
        if ($needFfmpeg -and (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
            Write-Success "ffmpeg installed"
            $script:HasFfmpeg = $true
            $needFfmpeg = $false
        }
        if (-not $needRipgrep -and -not $needFfmpeg) { return }
    }

    # Fallback: choco
    if ($hasChoco -and ($needRipgrep -or $needFfmpeg)) {
        Write-Info "Trying Chocolatey..."
        foreach ($pkg in $chocoPkgs) {
            try { choco install $pkg -y 2>&1 | Out-Null } catch { }
        }
        if ($needRipgrep -and (Get-Command rg -ErrorAction SilentlyContinue)) {
            Write-Success "ripgrep installed via chocolatey"
            $script:HasRipgrep = $true
            $needRipgrep = $false
        }
        if ($needFfmpeg -and (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
            Write-Success "ffmpeg installed via chocolatey"
            $script:HasFfmpeg = $true
            $needFfmpeg = $false
        }
    }

    # Fallback: scoop
    if ($hasScoop -and ($needRipgrep -or $needFfmpeg)) {
        Write-Info "Trying Scoop..."
        foreach ($pkg in $scoopPkgs) {
            try { scoop install $pkg 2>&1 | Out-Null } catch { }
        }
        if ($needRipgrep -and (Get-Command rg -ErrorAction SilentlyContinue)) {
            Write-Success "ripgrep installed via scoop"
            $script:HasRipgrep = $true
            $needRipgrep = $false
        }
        if ($needFfmpeg -and (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
            Write-Success "ffmpeg installed via scoop"
            $script:HasFfmpeg = $true
            $needFfmpeg = $false
        }
    }

    # Show manual instructions for anything still missing
    if ($needRipgrep) {
        Write-Warn "ripgrep not installed (file search will use findstr fallback)"
        Write-Info "  winget install BurntSushi.ripgrep.MSVC"
    }
    if ($needFfmpeg) {
        Write-Warn "ffmpeg not installed (TTS voice messages will be limited)"
        Write-Info "  winget install Gyan.FFmpeg"
    }
}

# ============================================================================
# Installation
# ============================================================================

function Install-Repository {
    if (-not $IsUpdateMode) {
        Write-Info "Installing to $InstallDir..."
    }
    
    if (Test-Path $InstallDir) {
        if (Test-Path "$InstallDir\.git") {
            if (-not $IsUpdateMode) {
                Write-Info "Existing installation found, updating..."
            }
            Push-Location $InstallDir

            $autostashRef = $null
            $status = git status --porcelain 2>$null
            if ($status) {
                if (-not $IsUpdateMode) {
                    Write-Info "Local changes detected, stashing before update..."
                }
                $stashName = "ector-install-autostash-$((Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss'))"
                git stash push --include-untracked -m $stashName 2>$null | Out-Null
                $autostashRef = git rev-parse --verify refs/stash 2>$null
            }

            git -c windows.appendAtomically=false fetch origin
            git -c windows.appendAtomically=false checkout $Branch
            git -c windows.appendAtomically=false pull --ff-only origin $Branch
            if ($LASTEXITCODE -ne 0) {
                Pop-Location
                throw "git pull --ff-only failed (local branch may have diverged)"
            }

            if ($autostashRef) {
                if ($IsUpdateMode) {
                    Write-Info "Modo não interativo: alterações locais mantidas no git stash."
                    Write-Info "  Restaurar manualmente: git stash list && git stash apply"
                } elseif ($IsInteractive) {
                    Write-Host ""
                    Write-Warn "Local changes were stashed before updating."
                    Write-Warn "Restoring them may reapply local customizations onto the updated codebase."
                    if (Prompt-YesNo "Restaurar alterações locais agora?" $true) {
                        Write-Info "Restoring local changes..."
                        git stash apply $autostashRef 2>$null | Out-Null
                        if ($LASTEXITCODE -eq 0) {
                            git stash drop $autostashRef 2>$null | Out-Null
                            Write-Warn "Local changes were restored on top of the updated codebase."
                        } else {
                            Write-Err "Update succeeded, but restoring local changes failed."
                            Write-Info "Resolve manually with: git stash apply $autostashRef"
                            Pop-Location
                            throw "Failed to restore stashed local changes"
                        }
                    } else {
                        Write-Info "Skipped restoring local changes."
                        Write-Info "Your changes are still preserved in git stash."
                    }
                } else {
                    Write-Info "Sem terminal interativo: alterações locais mantidas no git stash."
                    Write-Info "  Restaurar manualmente: git stash list && git stash apply"
                }
            }

            Pop-Location
        } else {
            Write-Err "Directory exists but is not a git repository: $InstallDir"
            Write-Info "Remove it or choose a different directory with -InstallDir"
            throw "Directory exists but is not a git repository: $InstallDir"
        }
    } else {
        $cloneSuccess = $false

        # Fix Windows git "copy-fd: write returned: Invalid argument" error.
        # Git for Windows can fail on atomic file operations (hook templates,
        # config lock files) due to antivirus, OneDrive, or NTFS filter drivers.
        # The -c flag injects config before any file I/O occurs.
        Write-Info "Configuring git for Windows compatibility..."
        $env:GIT_CONFIG_COUNT = "1"
        $env:GIT_CONFIG_KEY_0 = "windows.appendAtomically"
        $env:GIT_CONFIG_VALUE_0 = "false"
        git config --global windows.appendAtomically false 2>$null

        # Try SSH first, then HTTPS, with -c flag for atomic write fix
        Write-Info "Trying SSH clone..."
        $env:GIT_SSH_COMMAND = "ssh -o BatchMode=yes -o ConnectTimeout=5"
        try {
            git -c windows.appendAtomically=false clone --branch $Branch --recurse-submodules $RepoUrlSsh $InstallDir
            if ($LASTEXITCODE -eq 0) { $cloneSuccess = $true }
        } catch { }
        $env:GIT_SSH_COMMAND = $null
        
        if (-not $cloneSuccess) {
            if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue }
            Write-Info "SSH failed, trying HTTPS..."
            try {
                git -c windows.appendAtomically=false clone --branch $Branch --recurse-submodules $RepoUrlHttps $InstallDir
                if ($LASTEXITCODE -eq 0) { $cloneSuccess = $true }
            } catch { }
        }

        # Fallback: download ZIP archive (bypasses git file I/O issues entirely)
        if (-not $cloneSuccess) {
            if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue }
            Write-Warn "Git clone failed — downloading ZIP archive instead..."
            try {
                $zipUrl = "https://ector.cc/archive/refs/heads/$Branch.zip"
                $zipPath = "$env:TEMP\ector-agent-$Branch.zip"
                $extractPath = "$env:TEMP\ector-agent-extract"
                
                Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
                if (Test-Path $extractPath) { Remove-Item -Recurse -Force $extractPath }
                Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
                
                # GitHub ZIPs extract to repo-branch/ subdirectory
                $extractedDir = Get-ChildItem $extractPath -Directory | Select-Object -First 1
                if ($extractedDir) {
                    New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir) -ErrorAction SilentlyContinue | Out-Null
                    Move-Item $extractedDir.FullName $InstallDir -Force
                    Write-Success "Downloaded and extracted"
                    
                    # Initialize git repo so updates work later
                    Push-Location $InstallDir
                    git -c windows.appendAtomically=false init 2>$null
                    git -c windows.appendAtomically=false config windows.appendAtomically false 2>$null
                    git remote add origin $RepoUrlHttps 2>$null
                    Pop-Location
                    Write-Success "Git repo initialized for future updates"
                    
                    $cloneSuccess = $true
                }
                
                # Cleanup temp files
                Remove-Item -Force $zipPath -ErrorAction SilentlyContinue
                Remove-Item -Recurse -Force $extractPath -ErrorAction SilentlyContinue
            } catch {
                Write-Err "ZIP download also failed: $_"
            }
        }

        if (-not $cloneSuccess) {
            throw "Failed to download repository (tried git clone SSH, HTTPS, and ZIP)"
        }
    }
    
    # Set per-repo config (harmless if it fails)
    Push-Location $InstallDir
    git -c windows.appendAtomically=false config windows.appendAtomically false 2>$null

    # Ensure submodules are initialized and updated
    Write-Info "Initializing submodules..."
    git -c windows.appendAtomically=false submodule update --init --recursive 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Submodule init failed (terminal/RL tools may need manual setup)"
    } else {
        Write-Success "Submodules ready"
    }
    Pop-Location
    
    if (-not $IsUpdateMode) {
        Write-Success "Código do Ector"
    } else {
        Write-Success "Código do Ector (git pull)"
    }
}

function Install-Venv {
    if ($NoVenv) {
        Write-Info "Skipping virtual environment (-NoVenv)"
        return
    }
    
    Write-Info "Creating virtual environment with Python $PythonVersion..."
    
    Push-Location $InstallDir
    
    if (Test-Path "venv") {
        Write-Info "Virtual environment already exists, recreating..."
        Remove-Item -Recurse -Force "venv"
    }
    
    # uv creates the venv and pins the Python version in one step
    & $UvCmd venv venv --python $PythonVersion
    
    Pop-Location
    
    Write-Success "Virtual environment ready (Python $PythonVersion)"
}

function Install-Dependencies {
    Write-Info "Installing dependencies..."
    
    Push-Location $InstallDir
    
    if (-not $NoVenv) {
        # Tell uv to install into our venv (no activation needed)
        $env:VIRTUAL_ENV = "$InstallDir\venv"
    }
    
    # Install main package with all extras (non-editable).
    try {
        & $UvCmd pip install ".[all]" 2>&1 | Out-Null
    } catch {
        & $UvCmd pip install "." | Out-Null
    }
    
    Write-Success "Main package installed"
    
    # Install optional submodules
    Write-Info "Installing tinker-atropos (RL training backend)..."
    if (Test-Path "tinker-atropos\pyproject.toml") {
        try {
            & $UvCmd pip install -e ".\tinker-atropos" 2>&1 | Out-Null
            Write-Success "tinker-atropos installed"
        } catch {
            Write-Warn "tinker-atropos install failed (RL tools may not work)"
        }
    } else {
        Write-Warn "tinker-atropos not found (run: git submodule update --init)"
    }
    
    Pop-Location
    
    Write-Success "All dependencies installed"
}

function Set-PathVariable {
    Write-Info "Setting up ector command..."
    
    if ($NoVenv) {
        $script:EctorBin = $InstallDir
    } else {
        $script:EctorBin = Join-Path $InstallDir "venv\Scripts"
    }
    
    # Add the venv Scripts dir to user PATH so ector is globally available
    # On Windows, the ector.exe in venv\Scripts\ has the venv Python baked in
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    
    if ($currentPath -notlike "*$($script:EctorBin)*") {
        [Environment]::SetEnvironmentVariable(
            "Path",
            "$($script:EctorBin);$currentPath",
            "User"
        )
        Write-Success "Comando ector em $($script:EctorBin)"
    } else {
        Write-Info "PATH already configured"
    }
    
    # Set ECTOR_HOME so the Python code finds config/data in the right place.
    # Only needed on Windows where we install to %LOCALAPPDATA%\ector instead
    # of the Unix default ~/.ector
    $currentEctorHome = [Environment]::GetEnvironmentVariable("ECTOR_HOME", "User")
    if (-not $currentEctorHome -or $currentEctorHome -ne $EctorHome) {
        [Environment]::SetEnvironmentVariable("ECTOR_HOME", $EctorHome, "User")
        Write-Success "Set ECTOR_HOME=$EctorHome"
    }
    $env:ECTOR_HOME = $EctorHome
    
    # Update current session
    $env:Path = "$($script:EctorBin);$env:Path"
    $script:EctorCmd = Get-EctorCommandPath
    
    Write-Success "ector command ready"
}

function Copy-ConfigTemplates {
    Write-Info "Setting up configuration files..."
    
    # Create ~/.ector directory structure
    New-Item -ItemType Directory -Force -Path "$EctorHome\cron" | Out-Null
    New-Item -ItemType Directory -Force -Path "$EctorHome\sessions" | Out-Null
    New-Item -ItemType Directory -Force -Path "$EctorHome\logs" | Out-Null
    New-Item -ItemType Directory -Force -Path "$EctorHome\pairing" | Out-Null
    New-Item -ItemType Directory -Force -Path "$EctorHome\hooks" | Out-Null
    New-Item -ItemType Directory -Force -Path "$EctorHome\image_cache" | Out-Null
    New-Item -ItemType Directory -Force -Path "$EctorHome\audio_cache" | Out-Null
    New-Item -ItemType Directory -Force -Path "$EctorHome\memories" | Out-Null
    New-Item -ItemType Directory -Force -Path "$EctorHome\skills" | Out-Null

    
    # Create .env
    $envPath = "$EctorHome\.env"
    if (-not (Test-Path $envPath)) {
        $examplePath = "$InstallDir\.env.example"
        if (Test-Path $examplePath) {
            Copy-Item $examplePath $envPath
            Write-Success "Created ~/.ector/.env from template"
        } else {
            New-Item -ItemType File -Force -Path $envPath | Out-Null
            Write-Success "Created ~/.ector/.env"
        }
    } else {
        Write-Info "~/.ector/.env already exists, keeping it"
    }
    
    # Create config.yaml
    $configPath = "$EctorHome\config.yaml"
    if (-not (Test-Path $configPath)) {
        $examplePath = "$InstallDir\cli-config.yaml.example"
        if (Test-Path $examplePath) {
            Copy-Item $examplePath $configPath
            Write-Success "Created ~/.ector/config.yaml from template"
        }
    } else {
        Write-Info "~/.ector/config.yaml already exists, keeping it"
    }
    
    # Create SOUL.md if it doesn't exist (global persona file)
    $soulPath = "$EctorHome\SOUL.md"
    if (-not (Test-Path $soulPath)) {
        @"
# Ector Agent Persona

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
"@ | Set-Content -Path $soulPath -Encoding UTF8
        Write-Success "Created ~/.ector/SOUL.md (edit to customize personality)"
    }
    
    Write-Success "Configuration directory ready: ~/.ector/"
}

function Install-Bun {
    $script:HasBun = $false
    Write-Info "Checking Bun (TUI / ector chat)..."

    if (Get-Command bun -ErrorAction SilentlyContinue) {
        $version = bun --version
        Write-Success "Bun $version found"
        $script:HasBun = $true
        return $true
    }

    $managedBun = "$EctorHome\bun\bin\bun.exe"
    if (Test-Path $managedBun) {
        $env:Path = "$EctorHome\bun\bin;$env:Path"
        $version = & $managedBun --version
        Write-Success "Bun $version found (Ector-managed)"
        $script:HasBun = $true
        return $true
    }

    Write-Info "Installing Bun to $EctorHome\bun ..."
    try {
        $env:BUN_INSTALL = "$EctorHome\bun"
        if (-not (Test-Path $env:BUN_INSTALL)) {
            New-Item -ItemType Directory -Force -Path $env:BUN_INSTALL | Out-Null
        }
        $env:Path = "$env:BUN_INSTALL\bin;$env:Path"
        irm https://bun.sh/install.ps1 | iex
        if (Test-Path $managedBun) {
            $version = & $managedBun --version
            Write-Success "Bun $version installed to $EctorHome\bun\"
            $script:HasBun = $true
            return $true
        }
    } catch {
        Write-Warn "Bun install failed: $_"
    }

    Write-Warn "Could not auto-install Bun — terminal chat needs https://bun.sh"
    $script:HasBun = $false
    return $true
}

function Install-TuiDeps {
    if (-not $HasNode) {
        return
    }
    if (-not $HasBun) {
        Write-Warn "Skipping TUI setup (Bun not installed)"
        return
    }

    $tuiDir = "$InstallDir\frontend\tui"
    if (-not (Test-Path "$tuiDir\package.json")) {
        return
    }

    $env:Path = "$EctorHome\bun\bin;$EctorHome\node;$env:Path"

    if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
        if (Get-Command corepack -ErrorAction SilentlyContinue) {
            corepack enable 2>$null | Out-Null
            corepack prepare pnpm@latest --activate 2>$null | Out-Null
        }
        if (-not (Get-Command pnpm -ErrorAction SilentlyContinue) -and (Get-Command npm -ErrorAction SilentlyContinue)) {
            npm install -g pnpm 2>$null | Out-Null
        }
    }

    Write-Info "Installing TUI dependencies..."
    Push-Location $tuiDir
    try {
        $env:CI = "true"
        if ((Get-Command pnpm -ErrorAction SilentlyContinue) -and (Test-Path "pnpm-lock.yaml")) {
            pnpm install --frozen-lockfile --config.only-built-dependencies[]=esbuild 2>$null
            if ($LASTEXITCODE -ne 0) { pnpm install --config.only-built-dependencies[]=esbuild }
            pnpm rebuild esbuild --config.only-built-dependencies[]=esbuild 2>$null | Out-Null
        } elseif (Get-Command npm -ErrorAction SilentlyContinue) {
            npm install --no-fund --no-audit --progress=false
        }
        Write-Success "TUI dependencies installed"

        $prebuilt = (Test-Path "dist\entry.js") -and (Test-Path "packages\ector-tui\dist\tui-bundle.js") `
            -and -not ((Test-Path "packages\ector-tui\scripts\bundle.mjs") -and (Test-Path "src"))
        if ($prebuilt) {
            Write-Success "TUI pre-built (release) — skipping build"
            return
        }

        Write-Info "Building TUI (OpenTUI)..."
        if (Get-Command pnpm -ErrorAction SilentlyContinue) {
            pnpm run build --config.only-built-dependencies[]=esbuild
        } else {
            npm run build
        }
        if (Test-Path "dist\entry.js") {
            Write-Success "TUI built successfully"
        } else {
            Write-Warn "TUI build did not produce dist\entry.js"
        }
    } catch {
        Write-Warn "TUI setup failed: $_"
    } finally {
        Pop-Location
    }
}

function Install-NodeDeps {
    if (-not $HasNode) {
        Write-Info "Skipping Node.js dependencies (Node not installed)"
        return
    }
    
    Push-Location $InstallDir
    
    if (Test-Path "package.json") {
        Write-Info "Installing Node.js dependencies (browser tools)..."
        try {
            npm install --silent 2>&1 | Out-Null
            Write-Success "Node.js dependencies installed"
        } catch {
            Write-Warn "npm install failed (browser tools may not work)"
        }
    }
    
    Pop-Location
    Install-TuiDeps
}

function Invoke-SetupWizard {
    if ($SkipSetup) {
        Write-Info "Skipping setup wizard (-SkipSetup)"
        return
    }
    if ($IsUpdateMode) {
        Write-Info "Assistente de configuração ignorado (modo atualização)"
        return
    }
    if (-not $IsInteractive) {
        Write-Info "Assistente de configuração ignorado (sem terminal). Execute depois: ector setup"
        return
    }
    
    Write-Host ""
    Write-Info "Starting setup wizard..."
    Write-Host ""
    
    Push-Location $InstallDir
    
    # Run ector setup using the venv Python directly (no activation needed)
    if (-not $NoVenv) {
        & ".\venv\Scripts\python.exe" -m ector_cli.main setup
    } else {
        python -m ector_cli.main setup
    }
    
    Pop-Location
}

function Start-GatewayIfConfigured {
    if (-not $IsInteractive) { return }

    $envPath = Join-Path $EctorHome ".env"
    if (-not (Test-Path $envPath)) { return }

    $hasMessaging = $false
    $content = Get-Content $envPath -ErrorAction SilentlyContinue
    foreach ($var in @("TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "WHATSAPP_ENABLED")) {
        $match = $content | Where-Object { $_ -match "^${var}=.+" -and $_ -notmatch "your-token-here" }
        if ($match) { $hasMessaging = $true; break }
    }

    if (-not $hasMessaging) { return }

    $ectorCmd = Get-EctorCommandPath

    # If WhatsApp is enabled but not yet paired, run foreground for QR scan
    $whatsappEnabled = $content | Where-Object { $_ -match "^WHATSAPP_ENABLED=true" }
    $whatsappSession = Join-Path $EctorHome "whatsapp\session\creds.json"
    if ($whatsappEnabled -and -not (Test-Path $whatsappSession)) {
        Write-Host ""
        Write-Info "WhatsApp is enabled but not yet paired."
        Write-Info "Running 'ector whatsapp' to pair via QR code..."
        Write-Host ""
        if (Prompt-YesNo "Parear WhatsApp agora?" $true) {
            try {
                & $ectorCmd whatsapp
            } catch {
                # Expected after pairing completes
            }
        }
    }

    Write-Host ""
    Write-Info "Messaging platform token detected!"
    Write-Info "The gateway needs to be running for Ector to send/receive messages."
    Write-Host ""

    if (Prompt-YesNo "Deseja iniciar o gateway em segundo plano?" $true) {
        Write-Info "Starting gateway in background..."
        try {
            $logFile = Join-Path $EctorHome "logs\gateway.log"
            $errFile = Join-Path $EctorHome "logs\gateway-error.log"
            Start-Process -FilePath $ectorCmd -ArgumentList "gateway" `
                -RedirectStandardOutput $logFile `
                -RedirectStandardError $errFile `
                -WindowStyle Hidden
            Write-Success "Gateway started! Your bot is now online."
            Write-Info "Logs: $logFile"
            Write-Info "To stop: close the gateway process from Task Manager"
        } catch {
            Write-Warn "Failed to start gateway. Run manually: ector gateway"
        }
    } else {
        Write-Info "Skipped. Start the gateway later with: ector gateway"
    }
}

function Write-Completion {
    Write-Host ""
    if ($IsUpdateMode) {
        Write-Host "Atualização do Ector Agent concluída" -ForegroundColor Green
        $initPy = Join-Path $InstallDir "ector_cli\__init__.py"
        if (Test-Path $initPy) {
            $ver = (Select-String -Path $initPy -Pattern '^__version_name__\s*=\s*"([^"]+)"|^__version__\s*=\s*"([^"]+)"' | ForEach-Object {
                if ($_.Matches[0].Groups[1].Success) { $_.Matches[0].Groups[1].Value } else { $_.Matches[0].Groups[2].Value }
            } | Select-Object -First 1)
            $code = (Select-String -Path $initPy -Pattern '^__version_code__\s*=\s*(\d+)' | ForEach-Object { $_.Matches[0].Groups[1].Value } | Select-Object -First 1)
            if ($ver) {
                $label = if ($code) { "v$ver ($code)" } else { "v$ver" }
                Write-Host "  Versão: $label" -ForegroundColor DarkGray
            }
        }
        Write-Host ""
        return
    }

    Write-Host "Instalação do Ector Agent concluída" -ForegroundColor Green
    Write-Host ""
    Write-Host "   Configuração:  $EctorHome\config.yaml"
    Write-Host "   Chaves API:    $EctorHome\.env"
    Write-Host "   Dados:         $EctorHome\cron\, sessions\, logs\"
    Write-Host "   Código:        $InstallDir"
    Write-Host ""
    Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Comandos úteis" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "   ector                      Chat no terminal" -ForegroundColor Green
    Write-Host "   ector setup                Configurar chaves API e definições" -ForegroundColor Green
    Write-Host "   ector config               Ver ou editar configuração" -ForegroundColor Green
    Write-Host "   ector config edit          Abrir configuração no editor" -ForegroundColor Green
    Write-Host "   ector gateway install      Instalar serviço do gateway (mensagens + cron)" -ForegroundColor Green
    Write-Host ""
    Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Reinicie o terminal para aplicar alterações no PATH" -ForegroundColor Yellow
    Write-Host ""
    
    if (-not $HasNode) {
        Write-Warn "Node.js não foi instalado automaticamente."
        Write-Host "  Ferramentas de browser precisam de Node.js:" -ForegroundColor DarkGray
        Write-Host "  https://nodejs.org/en/download/" -ForegroundColor DarkGray
        Write-Host ""
    }

    if (-not $HasBun) {
        Write-Warn "Bun não foi instalado automaticamente."
        Write-Host "  Chat no terminal (ector / ector chat) requer Bun:" -ForegroundColor DarkGray
        Write-Host "  irm https://bun.sh/install.ps1 | iex" -ForegroundColor DarkGray
        Write-Host ""
    }
    
    if (-not $HasRipgrep) {
        Write-Warn "ripgrep (rg) não instalado. Para busca mais rápida em ficheiros:"
        Write-Host "  winget install BurntSushi.ripgrep.MSVC" -ForegroundColor DarkGray
        Write-Host ""
    }
}

# ============================================================================
# Main
# ============================================================================

function Main {
    Write-Banner
    
    if (-not (Install-Uv)) { throw "uv installation failed — cannot continue" }
    if (-not (Test-Python)) { throw "Python $PythonVersion not available — cannot continue" }
    if (-not (Test-Git)) { throw "Git not found — install from https://git-scm.com/download/win" }
    Test-Node              # Auto-installs if missing
    Install-SystemPackages  # ripgrep + ffmpeg in one step
    
    Install-Repository
    if (-not (Test-InstallCore)) { throw "Incomplete install tree" }
    Install-Venv
    Install-Dependencies
    Install-Bun
    Install-NodeDeps
    Set-PathVariable
    Copy-ConfigTemplates
    if (-not $IsUpdateMode) {
        Invoke-SetupWizard
        Start-GatewayIfConfigured
    }
    
    Write-Completion
}

# Wrap in try/catch so errors don't kill the terminal when run via:
#   irm https://...install.ps1 | iex
# (exit/throw inside iex kills the entire PowerShell session)
try {
    Main
} catch {
    Write-Host ""
    Write-Err "Installation failed: $_"
    Write-Host ""
    Write-Info "If the error is unclear, try downloading and running the script directly:"
    Write-Host "  Invoke-WebRequest -Uri 'https://ector.cc/install.ps1' -OutFile install.ps1" -ForegroundColor Yellow
    Write-Host "  .\install.ps1" -ForegroundColor Yellow
    Write-Host ""
}
