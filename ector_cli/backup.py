"""
Backup and import commands for ector CLI.

`ector backup` creates a zip archive of the entire ~/.ector/ directory
(excluding the ector-agent repo and transient files).

`ector import` restores from a backup zip, overlaying onto the current
ECTOR_HOME root.
"""

import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ector_constants import get_default_ector_root, get_ector_home, display_ector_home

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exclusion rules
# ---------------------------------------------------------------------------

# Directory names to skip entirely (matched against each path component)
_EXCLUDED_DIRS = {
    "ector-agent",     # the codebase repo — re-clone instead
    "__pycache__",      # bytecode caches — regenerated on import
    ".git",             # nested git dirs (profiles shouldn't have these, but safety)
    "node_modules",     # js deps if website/ somehow leaks in
    "backups",          # prior auto-backups — don't nest backups exponentially
    # Regeneratable / bulky runtime data (see profiles._DEFAULT_EXPORT_EXCLUDE_ROOT)
    "logs",
    "cache",
    "image_cache",
    "audio_cache",
    "document_cache",
    "browser_screenshots",
    "checkpoints",
    "sandboxes",
    "state-snapshots",
    "profiles",         # sibling profiles when backing up ~/.ector root
    ".worktrees",
    "venv",
    "bin",
    "optional-skills",
    "web_dist",
}

# File-name suffixes to skip
_EXCLUDED_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".db-shm",
    ".db-wal",
)

# File names to skip (runtime state that's meaningless on another machine)
_EXCLUDED_NAMES = {
    "gateway.pid",
    "cron.pid",
}


def _should_exclude(rel_path: Path) -> bool:
    """Return True if *rel_path* (relative to ector root) should be skipped."""
    parts = rel_path.parts

    # Any path component matches an excluded dir name
    for part in parts:
        if part in _EXCLUDED_DIRS:
            return True

    name = rel_path.name

    if name in _EXCLUDED_NAMES:
        return True

    if name.endswith(_EXCLUDED_SUFFIXES):
        return True

    return False


# ---------------------------------------------------------------------------
# SQLite safe copy
# ---------------------------------------------------------------------------

def _safe_copy_db(src: Path, dst: Path) -> bool:
    """Copy a SQLite database safely using the backup() API.

    Handles WAL mode — produces a consistent snapshot even while
    the DB is being written to.  Falls back to raw copy on failure.
    """
    try:
        conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        backup_conn = sqlite3.connect(str(dst))
        conn.backup(backup_conn)
        backup_conn.close()
        conn.close()
        return True
    except Exception as exc:
        logger.warning("SQLite safe copy failed for %s: %s", src, exc)
        try:
            shutil.copy2(src, dst)
            return True
        except Exception as exc2:
            logger.error("Raw copy also failed for %s: %s", src, exc2)
            return False


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def _format_size(nbytes: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def run_backup(args) -> None:
    """Create a zip backup of the Ector home directory."""
    ector_root = get_default_ector_root()

    if not ector_root.is_dir():
        print(f"Erro: Diretório home do Ector não encontrado em {ector_root}")
        sys.exit(1)

    # Determine output path
    if args.output:
        out_path = Path(args.output).expanduser().resolve()
        # If user gave a directory, put the zip inside it
        if out_path.is_dir():
            stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            out_path = out_path / f"ector-backup-{stamp}.zip"
    else:
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        out_path = Path.home() / f"ector-backup-{stamp}.zip"

    # Ensure the suffix is .zip
    if out_path.suffix.lower() != ".zip":
        out_path = out_path.with_suffix(out_path.suffix + ".zip")

    # Ensure parent directory exists
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect files
    print(f"Escaneando {display_ector_home()} ...")
    files_to_add: list[tuple[Path, Path]] = []  # (absolute, relative)
    skipped_dirs = set()

    for dirpath, dirnames, filenames in os.walk(ector_root, followlinks=False):
        dp = Path(dirpath)
        rel_dir = dp.relative_to(ector_root)

        # Prune excluded directories in-place so os.walk doesn't descend
        orig_dirnames = dirnames[:]
        dirnames[:] = [
            d for d in dirnames
            if d not in _EXCLUDED_DIRS
        ]
        for removed in set(orig_dirnames) - set(dirnames):
            skipped_dirs.add(str(rel_dir / removed))

        for fname in filenames:
            fpath = dp / fname
            rel = fpath.relative_to(ector_root)

            if _should_exclude(rel):
                continue

            # Skip the output zip itself if it happens to be inside ector root
            try:
                if fpath.resolve() == out_path.resolve():
                    continue
            except (OSError, ValueError):
                pass

            files_to_add.append((fpath, rel))

    if not files_to_add:
        print("Nenhum arquivo para fazer backup.")
        return

    # Create the zip
    file_count = len(files_to_add)
    print(f"Fazendo backup de {file_count} arquivos ...")

    total_bytes = 0
    errors = []
    t0 = time.monotonic()

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for i, (abs_path, rel_path) in enumerate(files_to_add, 1):
            try:
                # Safe copy for SQLite databases (handles WAL mode)
                if abs_path.suffix == ".db":
                    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                        tmp_db = Path(tmp.name)
                    if _safe_copy_db(abs_path, tmp_db):
                        zf.write(tmp_db, arcname=str(rel_path))
                        total_bytes += tmp_db.stat().st_size
                        tmp_db.unlink(missing_ok=True)
                    else:
                        tmp_db.unlink(missing_ok=True)
                        errors.append(f"  {rel_path}: Falha na cópia segura do SQLite")
                        continue
                else:
                    zf.write(abs_path, arcname=str(rel_path))
                    total_bytes += abs_path.stat().st_size
            except (PermissionError, OSError, ValueError) as exc:
                errors.append(f"  {rel_path}: {exc}")
                continue

            # Progress every 500 files
            if i % 500 == 0:
                print(f"  {i}/{file_count} arquivos ...")

    elapsed = time.monotonic() - t0
    zip_size = out_path.stat().st_size

    # Summary
    print()
    print(f"Backup concluído: {out_path}")
    print(f"  Arquivos:    {file_count}")
    print(f"  Original:    {_format_size(total_bytes)}")
    print(f"  Compactado:  {_format_size(zip_size)}")
    print(f"  Tempo:       {elapsed:.1f}s")

    if skipped_dirs:
        print(f"\n  Diretórios excluídos:")
        for d in sorted(skipped_dirs):
            print(f"    {d}/")

    if errors:
        print(f"\n  Avisos ({len(errors)} arquivos pulados):")
        for e in errors[:10]:
            print(e)
        if len(errors) > 10:
            print(f"  ... e mais {len(errors) - 10}")

    print(f"\nRestaure com: ector import {out_path.name}")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _validate_backup_zip(zf: zipfile.ZipFile) -> tuple[bool, str]:
    """Check that a zip looks like a Ector backup.

    Returns (ok, reason).
    """
    names = zf.namelist()
    if not names:
        return False, "o arquivo zip está vazio"

    # Look for telltale files that a ector home would have
    markers = {"config.yaml", ".env", "state.db"}
    found = set()
    for n in names:
        # Could be at the root or one level deep (if someone zipped the directory)
        basename = Path(n).name
        if basename in markers:
            found.add(basename)

    if not found:
        return False, (
            "o zip não parece ser um backup do Ector "
            "(nenhum config.yaml, .env ou banco de dados de estado encontrado)"
        )

    return True, ""


def _detect_prefix(zf: zipfile.ZipFile) -> str:
    """Detect if the zip has a common directory prefix wrapping all entries.

    Some tools zip as `.ector/config.yaml` instead of `config.yaml`.
    Returns the prefix to strip (empty string if none).
    """
    names = [n for n in zf.namelist() if not n.endswith("/")]
    if not names:
        return ""

    # Find common prefix
    parts_list = [Path(n).parts for n in names]

    # Check if all entries share a common first directory
    first_parts = {p[0] for p in parts_list if len(p) > 1}
    if len(first_parts) == 1:
        prefix = first_parts.pop()
        # Only strip if it looks like a ector dir name
        if prefix in (".ector", "ector"):
            return prefix + "/"

    return ""


def run_import(args) -> None:
    """Restore a Ector backup from a zip file."""
    zip_path = Path(args.zipfile).expanduser().resolve()

    if not zip_path.is_file():
        print(f"Erro: Arquivo não encontrado: {zip_path}")
        sys.exit(1)

    if not zipfile.is_zipfile(zip_path):
        print(f"Erro: Não é um arquivo zip válido: {zip_path}")
        sys.exit(1)

    ector_root = get_default_ector_root()

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Validate
        ok, reason = _validate_backup_zip(zf)
        if not ok:
            print(f"Erro: {reason}")
            sys.exit(1)

        prefix = _detect_prefix(zf)
        members = [n for n in zf.namelist() if not n.endswith("/")]
        file_count = len(members)

        print(f"O backup contém {file_count} arquivos")
        print(f"Alvo: {display_ector_home()}")

        if prefix:
            print(f"Prefixo de arquivo detectado: {prefix!r} (será removido)")

        # Check for existing installation
        has_config = (ector_root / "config.yaml").exists()
        has_env = (ector_root / ".env").exists()

        if (has_config or has_env) and not args.force:
            print()
            print("Aviso: O diretório alvo já possui configuração do Ector.")
            print("A importação irá sobrescrever os arquivos existentes com o conteúdo do backup.")
            print()
            try:
                answer = input("Continuar? (s/n) ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAbortado.")
                sys.exit(1)
            if answer not in ("s", "sim", "y", "yes"):
                print("Abortado.")
                return

        # Extract
        print(f"\nImportando {file_count} arquivos ...")
        ector_root.mkdir(parents=True, exist_ok=True)

        errors = []
        restored = 0
        t0 = time.monotonic()

        for member in members:
            # Strip prefix if detected
            if prefix and member.startswith(prefix):
                rel = member[len(prefix):]
            else:
                rel = member

            if not rel:
                continue

            target = ector_root / rel

            # Security: reject absolute paths and traversals
            try:
                target.resolve().relative_to(ector_root.resolve())
            except ValueError:
                errors.append(f"  {rel}: travessia de caminho bloqueada")
                continue

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                restored += 1
            except (PermissionError, OSError) as exc:
                errors.append(f"  {rel}: {exc}")

            if restored % 500 == 0:
                print(f"  {restored}/{file_count} arquivos ...")

        elapsed = time.monotonic() - t0

        # Summary
        print()
        print(f"Importação concluída: {restored} arquivos restaurados em {elapsed:.1f}s")
        print(f"  Alvo: {display_ector_home()}")

        if errors:
            print(f"\n  Avisos ({len(errors)} arquivos pulados):")
            for e in errors[:10]:
                print(e)
            if len(errors) > 10:
                print(f"  ... e mais {len(errors) - 10}")

        # Post-import: restore profile wrapper scripts
        profiles_dir = ector_root / "profiles"
        restored_profiles = []
        if profiles_dir.is_dir():
            try:
                from ector_cli.profiles import (
                    create_wrapper_script, check_alias_collision,
                    _is_wrapper_dir_in_path, _get_wrapper_dir,
                )
                for entry in sorted(profiles_dir.iterdir()):
                    if not entry.is_dir():
                        continue
                    profile_name = entry.name
                    # Only create wrappers for directories with config
                    if not (entry / "config.yaml").exists() and not (entry / ".env").exists():
                        continue
                    collision = check_alias_collision(profile_name)
                    if collision:
                        print(f"  Pulou o alias '{profile_name}': {collision}")
                        restored_profiles.append((profile_name, False))
                    else:
                        wrapper = create_wrapper_script(profile_name)
                        restored_profiles.append((profile_name, wrapper is not None))

                if restored_profiles:
                    created = [n for n, ok in restored_profiles if ok]
                    skipped = [n for n, ok in restored_profiles if not ok]
                    if created:
                        print(f"\n  Aliases de perfil restaurados: {', '.join(created)}")
                    if skipped:
                        print(f"  Aliases de perfil pulados:    {', '.join(skipped)}")
                    if not _is_wrapper_dir_in_path():
                        print(f"\n  Nota: {_get_wrapper_dir()} não está no seu PATH.")
                        print('  Adicione à configuração do seu shell (~/.bashrc ou ~/.zshrc):')
                        print('    export PATH="$HOME/.local/bin:$PATH"')
            except ImportError:
                # ector_cli.profiles might not be available (fresh install)
                if any(profiles_dir.iterdir()):
                    print(f"\n  Perfis detectados, mas os aliases não puderam ser criados.")
                    print(f"  Execute: ector profile list  (após instalar o ector)")

        # Guidance
        print()
        if not (ector_root / "ector-agent").is_dir():
            print("Nota: O código do ector-agent não foi incluído no backup.")
            print("  Se esta for uma instalação nova, atualize o código (git pull) e reinstale as dependências")

        if restored_profiles:
            gw_profiles = [n for n, _ in restored_profiles]
            print("\nPara reabilitar os serviços de gateway para os perfis:")
            for pname in gw_profiles:
                print(f"  ector -p {pname} gateway install")

        print("Concluído. Sua configuração do Ector foi restaurada.")


# ---------------------------------------------------------------------------
# Quick state snapshots (used by /snapshot slash command and ector backup --quick)
# ---------------------------------------------------------------------------

# Critical state files to include in quick snapshots (relative to ECTOR_HOME).
# Everything else is either regeneratable (logs, cache) or managed separately
# (skills, repo, sessions/).
#
# Entries may be individual files OR directories.  Directories are captured
# recursively; missing entries are silently skipped.  Pairing data lives in
# platform-specific JSON blobs outside state.db, so it's listed here explicitly
# — quick snapshots capture this set so approved-user lists
# are recoverable if anything goes wrong (issue #15733).
_QUICK_STATE_FILES = (
    "state.db",
    "config.yaml",
    ".env",
    "auth.json",
    "identity.json",
    "cron/jobs.json",
    "gateway_state.json",
    "channel_directory.json",
    "processes.json",
    # Pairing stores (generic + per-platform JSONs outside state.db)
    "pairing",                          # legacy location (gateway/pairing.py)
    "platforms/pairing",                # new location (gateway/pairing.py)
    "feishu_comment_pairing.json",      # Feishu comment subscription pairings
)

# Critical state for pre-update rollback — config, credentials, DBs, pairing.
# Deliberately excludes sessions/, logs/, caches/, skills/, and the repo tree
# (``ector update`` only mutates the install checkout + pip deps).
_PRE_UPDATE_STATE_FILES = _QUICK_STATE_FILES + (
    "SOUL.md",
    "memories/MEMORY.md",
    "memories/USER.md",
)

_QUICK_SNAPSHOTS_DIR = "state-snapshots"
_QUICK_DEFAULT_KEEP = 20


def _quick_snapshot_root(ector_home: Optional[Path] = None) -> Path:
    home = ector_home or get_ector_home()
    return home / _QUICK_SNAPSHOTS_DIR


def create_quick_snapshot(
    label: Optional[str] = None,
    ector_home: Optional[Path] = None,
) -> Optional[str]:
    """Create a quick state snapshot of critical files.

    Copies STATE_FILES to a timestamped directory under state-snapshots/.
    Auto-prunes old snapshots beyond the keep limit.

    Returns:
        Snapshot ID (timestamp-based), or None if no files found.
    """
    home = ector_home or get_ector_home()
    root = _quick_snapshot_root(home)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snap_id = f"{ts}-{label}" if label else ts
    snap_dir = root / snap_id
    snap_dir.mkdir(parents=True, exist_ok=True)

    manifest: Dict[str, int] = {}  # rel_path -> file size

    for rel in _QUICK_STATE_FILES:
        src = home / rel
        if not src.exists():
            continue

        if src.is_dir():
            # Walk the directory and record each file individually in the
            # manifest so restore can treat them uniformly.  Empty dirs are
            # skipped (nothing to snapshot).
            for sub in src.rglob("*"):
                if not sub.is_file():
                    continue
                sub_rel = sub.relative_to(home).as_posix()
                dst = snap_dir / sub_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(sub, dst)
                    manifest[sub_rel] = dst.stat().st_size
                except (OSError, PermissionError) as exc:
                    logger.warning("Could not snapshot %s: %s", sub_rel, exc)
            continue

        if not src.is_file():
            continue

        dst = snap_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        try:
            if src.suffix == ".db":
                if not _safe_copy_db(src, dst):
                    continue
            else:
                shutil.copy2(src, dst)
            manifest[rel] = dst.stat().st_size
        except (OSError, PermissionError) as exc:
            logger.warning("Could not snapshot %s: %s", rel, exc)

    if not manifest:
        shutil.rmtree(snap_dir, ignore_errors=True)
        return None

    # Write manifest
    meta = {
        "id": snap_id,
        "timestamp": ts,
        "label": label,
        "file_count": len(manifest),
        "total_size": sum(manifest.values()),
        "files": manifest,
    }
    with open(snap_dir / "manifest.json", "w") as f:
        json.dump(meta, f, indent=2)

    # Auto-prune
    _prune_quick_snapshots(root, keep=_QUICK_DEFAULT_KEEP)

    logger.info("State snapshot created: %s (%d files)", snap_id, len(manifest))
    return snap_id


def list_quick_snapshots(
    limit: int = 20,
    ector_home: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """List existing quick state snapshots, most recent first."""
    root = _quick_snapshot_root(ector_home)
    if not root.exists():
        return []

    results = []
    for d in sorted(root.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        manifest_path = d / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path) as f:
                    results.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                results.append({"id": d.name, "file_count": 0, "total_size": 0})
        if len(results) >= limit:
            break

    return results


def restore_quick_snapshot(
    snapshot_id: str,
    ector_home: Optional[Path] = None,
) -> bool:
    """Restore state from a quick snapshot.

    Overwrites current state files with the snapshot's copies.
    Returns True if at least one file was restored.
    """
    home = ector_home or get_ector_home()
    root = _quick_snapshot_root(home)
    snap_dir = root / snapshot_id

    if not snap_dir.is_dir():
        return False

    manifest_path = snap_dir / "manifest.json"
    if not manifest_path.exists():
        return False

    with open(manifest_path) as f:
        meta = json.load(f)

    restored = 0
    for rel in meta.get("files", {}):
        src = snap_dir / rel
        if not src.exists():
            continue

        dst = home / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        try:
            if dst.suffix == ".db":
                # Atomic-ish replace for databases
                tmp = dst.parent / f".{dst.name}.snap_restore"
                shutil.copy2(src, tmp)
                dst.unlink(missing_ok=True)
                shutil.move(str(tmp), str(dst))
            else:
                shutil.copy2(src, dst)
            restored += 1
        except (OSError, PermissionError) as exc:
            logger.error("Failed to restore %s: %s", rel, exc)

    logger.info("Restored %d files from snapshot %s", restored, snapshot_id)
    return restored > 0


def _prune_quick_snapshots(root: Path, keep: int = _QUICK_DEFAULT_KEEP) -> int:
    """Remove oldest quick snapshots beyond the keep limit. Returns count deleted."""
    if not root.exists():
        return 0

    dirs = sorted(
        (d for d in root.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,
    )

    deleted = 0
    for d in dirs[keep:]:
        try:
            shutil.rmtree(d)
            deleted += 1
        except OSError as exc:
            logger.warning("Failed to prune snapshot %s: %s", d.name, exc)

    return deleted


def prune_quick_snapshots(
    keep: int = _QUICK_DEFAULT_KEEP,
    ector_home: Optional[Path] = None,
) -> int:
    """Manually prune quick snapshots. Returns count deleted."""
    return _prune_quick_snapshots(_quick_snapshot_root(ector_home), keep=keep)


def run_quick_backup(args) -> None:
    """CLI entry point for ector backup --quick."""
    label = getattr(args, "label", None)
    snap_id = create_quick_snapshot(label=label)
    if snap_id:
        print(f"Snapshot de estado criado: {snap_id}")
        snaps = list_quick_snapshots()
        print(f"  {len(snaps)} snapshot(s) armazenados em {display_ector_home()}/state-snapshots/")
        print(f"  Restaure com: /snapshot restore {snap_id}")
    else:
        print("Nenhum arquivo de estado encontrado para fazer snapshot.")


# ---------------------------------------------------------------------------
# Pre-update auto-backup
# ---------------------------------------------------------------------------

_PRE_UPDATE_BACKUPS_DIR = "backups"
_PRE_UPDATE_PREFIX = "pre-update-"
_PRE_UPDATE_DEFAULT_KEEP = 5


def _pre_update_backup_dir(ector_home: Optional[Path] = None) -> Path:
    home = ector_home or get_ector_home()
    return home / _PRE_UPDATE_BACKUPS_DIR


def _collect_state_file_paths(
    ector_root: Path,
    rel_entries: tuple[str, ...],
) -> list[tuple[Path, Path]]:
    """Resolve *rel_entries* (files or dirs) under *ector_root* for archiving."""
    files_to_add: list[tuple[Path, Path]] = []

    for rel in rel_entries:
        src = ector_root / rel
        if not src.exists():
            continue

        if src.is_dir():
            for sub in src.rglob("*"):
                if not sub.is_file():
                    continue
                try:
                    sub_rel = sub.relative_to(ector_root)
                except ValueError:
                    continue
                if _should_exclude(sub_rel):
                    continue
                files_to_add.append((sub, sub_rel))
            continue

        if not src.is_file():
            continue

        try:
            rel_path = src.relative_to(ector_root)
        except ValueError:
            continue
        if _should_exclude(rel_path):
            continue
        files_to_add.append((src, rel_path))

    return files_to_add


def _write_files_to_zip(
    out_path: Path,
    files_to_add: list[tuple[Path, Path]],
) -> bool:
    """Write *files_to_add* to *out_path*. Returns True on success."""
    if not files_to_add:
        return False

    try:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for abs_path, rel_path in files_to_add:
                try:
                    if abs_path.suffix == ".db":
                        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                            tmp_db = Path(tmp.name)
                        try:
                            if _safe_copy_db(abs_path, tmp_db):
                                zf.write(tmp_db, arcname=str(rel_path))
                        finally:
                            tmp_db.unlink(missing_ok=True)
                    else:
                        zf.write(abs_path, arcname=str(rel_path))
                except (PermissionError, OSError, ValueError) as exc:
                    logger.debug("Skipping %s in zip backup: %s", rel_path, exc)
                    continue
    except OSError as exc:
        logger.warning("Zip write failed for %s: %s", out_path, exc)
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False

    return True


def _prune_pre_update_backups(backup_dir: Path, keep: int) -> int:
    """Remove oldest pre-update backups beyond the keep limit.

    Returns the number of files deleted.  Only touches files matching
    ``pre-update-*.zip`` so hand-made zips dropped in the same directory
    are never touched.
    """
    if keep < 0:
        keep = 0
    if not backup_dir.exists():
        return 0

    backups = sorted(
        (p for p in backup_dir.iterdir()
         if p.is_file() and p.name.startswith(_PRE_UPDATE_PREFIX) and p.suffix.lower() == ".zip"),
        key=lambda p: p.name,
        reverse=True,
    )

    deleted = 0
    for p in backups[keep:]:
        try:
            p.unlink()
            deleted += 1
        except OSError as exc:
            logger.warning("Failed to prune backup %s: %s", p.name, exc)

    return deleted


def create_pre_update_backup(
    ector_home: Optional[Path] = None,
    keep: int = _PRE_UPDATE_DEFAULT_KEEP,
) -> Optional[Path]:
    """Create a lean zip backup of critical ECTOR_HOME state under ``backups/``.

    Only archives config, credentials, databases, pairing stores, and a few
    identity files — not sessions, logs, caches, or the install tree.
    Writes to ``<ECTOR_HOME>/backups/pre-update-<timestamp>.zip`` and
    auto-prunes old pre-update backups.

    Returns the path to the created zip, or ``None`` if no files were
    found or the backup could not be created.  Never raises — the caller
    should continue even if the backup fails.
    """
    ector_root = ector_home or get_ector_home()
    if not ector_root.is_dir():
        return None

    backup_dir = _pre_update_backup_dir(ector_root)
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create pre-update backup dir %s: %s", backup_dir, exc)
        return None

    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out_path = backup_dir / f"{_PRE_UPDATE_PREFIX}{stamp}.zip"

    files_to_add = _collect_state_file_paths(ector_root, _PRE_UPDATE_STATE_FILES)
    if not files_to_add:
        return None

    if not _write_files_to_zip(out_path, files_to_add):
        return None

    _prune_pre_update_backups(backup_dir, keep=keep)
    return out_path
