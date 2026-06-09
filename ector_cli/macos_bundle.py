"""macOS ``Ector.app`` bundle for TUI gateway / TCC-friendly process identity.

The Ink TUI spawns ``python -m tui_gateway.entry`` for chat. Without a bundle,
macOS privacy prompts show the interpreter name (``python3``). A minimal
``.app`` with a stable ``CFBundleIdentifier`` makes dialogs show **Ector**.

After upgrading from a plain-python install, users may need to re-grant
microphone access under **System Settings → Privacy** (entry **Ector**), or
run ``tccutil reset Microphone ai.ector.agent``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ector_constants import get_ector_home

BUNDLE_DIR_NAME = "Ector.app"
BUNDLE_IDENTIFIER = "ai.ector.agent"
BUNDLE_EXECUTABLE = "Ector"
_STAMP_NAME = ".source-sha256"
_PREFIX_STAMP = ".python-prefix"

_TEMPLATE_PLIST = (
    Path(__file__).resolve().parent.parent / "scripts" / "macos" / BUNDLE_DIR_NAME / "Info.plist"
)


def ector_app_path(ector_home: Path | None = None) -> Path:
    """Return ``$ECTOR_HOME/Ector.app``."""
    return (ector_home or get_ector_home()) / BUNDLE_DIR_NAME


def gateway_executable_in_bundle(app_path: Path | None = None) -> Path:
    """``Ector.app/Contents/MacOS/Ector``."""
    root = app_path or ector_app_path()
    return root / "Contents" / "MacOS" / BUNDLE_EXECUTABLE


def _resolve_interpreter(path: Path) -> Path:
    """Follow symlinks to the Mach-O interpreter."""
    try:
        return path.resolve()
    except OSError:
        return path


def _source_fingerprint(source: Path) -> str:
    resolved = _resolve_interpreter(source)
    h = hashlib.sha256()
    with open(resolved, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _linked_libpython(exe: Path) -> Path | None:
    """Resolve ``libpython*.dylib`` next to the real interpreter (uv/venv layout)."""
    resolved = _resolve_interpreter(exe)
    try:
        out = subprocess.check_output(["otool", "-L", str(resolved)], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in out.splitlines()[1:]:
        stripped = line.strip()
        if not stripped or "libpython" not in stripped:
            continue
        name = stripped.split()[0]
        if name.startswith("@rpath/"):
            candidate = resolved.parent.parent / "lib" / name.split("/", 1)[1]
        elif name.startswith("@executable_path/"):
            rel = name.split("/", 1)[1]
            candidate = resolved.parent / rel
        else:
            candidate = Path(name)
        if candidate.is_file():
            return candidate
    return None


def _bundle_lib_dir(app_path: Path) -> Path:
    return app_path / "Contents" / "lib"


def _python_prefix_for_interpreter(exe: Path) -> Path | None:
    """Return the install prefix (stdlib + lib) for a CPython interpreter."""
    resolved = _resolve_interpreter(exe)
    prefix = resolved.parent.parent
    minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    if (prefix / "lib" / f"python{minor}").is_dir():
        return prefix
    return None


def _bundle_prefix_stamp(app_path: Path) -> Path:
    return app_path / "Contents" / _PREFIX_STAMP


def _read_bundle_python_home(exe: Path) -> Path | None:
    stamp = exe.parent.parent / _PREFIX_STAMP
    if not stamp.is_file():
        return None
    try:
        text = stamp.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(text) if text else None


def python_home_for_gateway_executable(exe: Path | str) -> Path | None:
    """``PYTHONHOME`` for a gateway interpreter (required for the macOS app copy)."""
    path = Path(exe)
    if path.name == BUNDLE_EXECUTABLE and "Ector.app" in path.as_posix():
        return _read_bundle_python_home(path)
    return None


def _bundle_is_runnable(exe: Path) -> bool:
    if not exe.is_file() or not os.access(exe, os.X_OK):
        return False
    env = os.environ.copy()
    python_home = _read_bundle_python_home(exe)
    if python_home is not None:
        env["PYTHONHOME"] = str(python_home)
    try:
        proc = subprocess.run(
            [str(exe), "-c", "import sys"],
            capture_output=True,
            timeout=10,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _bundle_is_current(app_path: Path, source: Path) -> bool:
    stamp = app_path / "Contents" / _STAMP_NAME
    exe = gateway_executable_in_bundle(app_path)
    if not stamp.is_file() or not exe.is_file():
        return False
    prefix = _python_prefix_for_interpreter(source)
    prefix_stamp = _bundle_prefix_stamp(app_path)
    if prefix is not None:
        if not prefix_stamp.is_file():
            return False
        try:
            if prefix_stamp.read_text(encoding="utf-8").strip() != str(prefix):
                return False
        except OSError:
            return False
    libpython = _linked_libpython(source)
    if libpython is not None:
        bundled_lib = _bundle_lib_dir(app_path) / libpython.name
        if not bundled_lib.is_file():
            return False
        try:
            if _source_fingerprint(bundled_lib) != _source_fingerprint(libpython):
                return False
        except OSError:
            return False
    try:
        if stamp.read_text(encoding="utf-8").strip() != _source_fingerprint(source):
            return False
    except OSError:
        return False
    return _bundle_is_runnable(exe)


def _bundle_version() -> str:
    try:
        from ector_cli import __version__

        return str(__version__)
    except Exception:
        return "0.0.0"


def _write_info_plist(dest: Path) -> None:
    if not _TEMPLATE_PLIST.is_file():
        raise FileNotFoundError(f"missing bundle template: {_TEMPLATE_PLIST}")
    text = _TEMPLATE_PLIST.read_text(encoding="utf-8")
    text = text.replace("__ECTOR_VERSION__", _bundle_version())
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def ensure_ector_gateway_app(venv_python: Path | str) -> Path | None:
    """Create or refresh ``Ector.app``; return the gateway executable path.

    Non-macOS: returns ``None`` (caller should use ``sys.executable``).
    """
    if sys.platform != "darwin":
        return None

    source = Path(venv_python)
    if not source.is_file():
        return None

    app_path = ector_app_path()
    exe_path = gateway_executable_in_bundle(app_path)

    if _bundle_is_current(app_path, source):
        return exe_path

    macos_dir = exe_path.parent
    contents_dir = macos_dir.parent
    try:
        if app_path.exists():
            shutil.rmtree(app_path)
        macos_dir.mkdir(parents=True, exist_ok=True)
        resolved = _resolve_interpreter(source)
        shutil.copy2(resolved, exe_path)
        os.chmod(exe_path, 0o755)
        libpython = _linked_libpython(source)
        if libpython is not None:
            lib_dir = _bundle_lib_dir(app_path)
            lib_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(libpython, lib_dir / libpython.name)
        prefix = _python_prefix_for_interpreter(source)
        if prefix is not None:
            _bundle_prefix_stamp(app_path).write_text(str(prefix) + "\n", encoding="utf-8")
        _write_info_plist(contents_dir / "Info.plist")
        (contents_dir / _STAMP_NAME).write_text(
            _source_fingerprint(source) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return None

    if not exe_path.is_file() or not _bundle_is_runnable(exe_path):
        try:
            if app_path.exists():
                shutil.rmtree(app_path)
        except OSError:
            pass
        return None
    return exe_path


def resolve_gateway_python(
    *,
    fallback: str | None = None,
    project_root: Path | str | None = None,
) -> str:
    """Pick the Python binary for ``tui_gateway.entry`` (bundle preferred on macOS)."""
    configured = os.environ.get("ECTOR_PYTHON", "").strip()
    if configured:
        p = Path(configured)
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)

    if sys.platform == "darwin":
        bundled = gateway_executable_in_bundle()
        if bundled.is_file() and os.access(bundled, os.X_OK):
            if _bundle_is_runnable(bundled):
                return str(bundled)
            # Stale install (dylib / PYTHONHOME layout changed): drop the half bundle so
            # ``ensure_ector_gateway_app`` can rebuild instead of leaving a broken Mach-O on disk.
            try:
                app = ector_app_path()
                if app.exists():
                    shutil.rmtree(app)
            except OSError:
                pass
        if fallback:
            ensured = ensure_ector_gateway_app(fallback)
            if ensured is not None and ensured.is_file() and _bundle_is_runnable(ensured):
                return str(ensured)

    root = Path(project_root) if project_root else None
    if root is not None:
        for rel in (".venv/bin/python3", ".venv/bin/python", "venv/bin/python3", "venv/bin/python"):
            candidate = root / rel
            if candidate.is_file() and os.access(candidate, os.X_OK):
                if sys.platform == "darwin":
                    ensured = ensure_ector_gateway_app(candidate)
                    if ensured is not None and _bundle_is_runnable(ensured):
                        return str(ensured)
                return str(candidate)

    if fallback:
        return fallback
    return sys.executable
