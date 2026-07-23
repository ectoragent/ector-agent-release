#!/usr/bin/env python3
"""
Sincroniza a biblioteca de skills do usuário (nuvem) para ~/.ector/skills/.

Usa GET /agent/me/skills/manifest (ETag) e baixa apenas bundles alterados.
Skills gerenciadas ficam registradas em ~/.ector/cloud_skills.json.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import httpx

from ector_constants import get_ector_home

logger = logging.getLogger(__name__)

SKILLS_DIR = get_ector_home() / "skills"
CLOUD_STATE_FILE = get_ector_home() / "cloud_skills.json"
CLOUD_ETAG_FILE = get_ector_home() / "cloud_skills.etag"
CLOUD_RATE_STATE_FILE = get_ector_home() / "cloud_skills.rate.json"
CLOUD_SYNC_LOCK_FILE = get_ector_home() / "cloud_skills.lock"
BUNDLED_MANIFEST_FILE = SKILLS_DIR / ".bundled_manifest"
DEFAULT_ONBOARDING_SKILL_SLUG = "ector-hub-onboarding"

_DEFAULT_CLOUD_SYNC_INTERVAL_SECONDS = 300.0
_DEFAULT_MIN_COOLDOWN_SECONDS = 120.0
_DEFAULT_BUNDLE_DELAY_SECONDS = 0.35
_DEFAULT_MAX_BUNDLES_PER_RUN = 20
_MIN_CLOUD_SYNC_INTERVAL_SECONDS = 60.0
_MIN_COOLDOWN_SECONDS = 30.0
_MAX_BACKOFF_SECONDS = 3600.0
_RATE_LIMIT_HTTP_CODES = frozenset({429, 503})

_sync_lock = threading.Lock()
_sync_thread: Optional[threading.Thread] = None
_last_schedule_monotonic = 0.0
_agent_startup_primed = False


@dataclass(frozen=True)
class CloudSyncSettings:
    enabled: bool
    interval_seconds: float
    min_cooldown_seconds: float
    bundle_delay_seconds: float
    max_bundles_per_run: int


def _cloud_sync_settings() -> CloudSyncSettings:
    """Limites de sync automático (proteção da API)."""
    defaults = CloudSyncSettings(
        enabled=True,
        interval_seconds=_DEFAULT_CLOUD_SYNC_INTERVAL_SECONDS,
        min_cooldown_seconds=_DEFAULT_MIN_COOLDOWN_SECONDS,
        bundle_delay_seconds=_DEFAULT_BUNDLE_DELAY_SECONDS,
        max_bundles_per_run=_DEFAULT_MAX_BUNDLES_PER_RUN,
    )
    try:
        from ector_cli.config import load_config

        cfg = load_config() or {}
        skills = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else {}
        if skills.get("cloud_sync") is False:
            return CloudSyncSettings(
                enabled=False,
                interval_seconds=defaults.interval_seconds,
                min_cooldown_seconds=defaults.min_cooldown_seconds,
                bundle_delay_seconds=defaults.bundle_delay_seconds,
                max_bundles_per_run=defaults.max_bundles_per_run,
            )

        def _float(key: str, default: float, *, minimum: float) -> float:
            raw = skills.get(key, default)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = default
            return max(minimum, value)

        def _int(key: str, default: int, *, minimum: int) -> int:
            raw = skills.get(key, default)
            try:
                value = int(raw)
            except (TypeError, ValueError):
                value = default
            return max(minimum, value)

        return CloudSyncSettings(
            enabled=True,
            interval_seconds=_float(
                "cloud_sync_interval_seconds",
                defaults.interval_seconds,
                minimum=_MIN_CLOUD_SYNC_INTERVAL_SECONDS,
            ),
            min_cooldown_seconds=_float(
                "cloud_sync_min_cooldown_seconds",
                defaults.min_cooldown_seconds,
                minimum=_MIN_COOLDOWN_SECONDS,
            ),
            bundle_delay_seconds=_float(
                "cloud_sync_bundle_delay_seconds",
                defaults.bundle_delay_seconds,
                minimum=0.0,
            ),
            max_bundles_per_run=_int(
                "cloud_sync_max_bundles_per_run",
                defaults.max_bundles_per_run,
                minimum=1,
            ),
        )
    except Exception:
        return defaults


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        retry_at = parsedate_to_datetime(raw)
        return max(0.0, retry_at.timestamp() - time.time())
    except Exception:
        return None


def _read_rate_state() -> Dict[str, Any]:
    return _read_json(CLOUD_RATE_STATE_FILE)


def _write_rate_state(data: Dict[str, Any]) -> None:
    _write_json_atomic(CLOUD_RATE_STATE_FILE, data)


def _rate_limit_backoff_remaining() -> float:
    state = _read_rate_state()
    until = float(state.get("backoff_until") or 0)
    return max(0.0, until - time.time())


def _record_rate_limit(response: Optional[httpx.Response] = None) -> None:
    state = _read_rate_state()
    strikes = int(state.get("consecutive_rate_limits") or 0) + 1
    retry_after = _retry_after_seconds(response) if response is not None else None
    delay = retry_after if retry_after is not None else min(60.0 * strikes, 600.0)
    delay = max(_MIN_COOLDOWN_SECONDS, min(delay, _MAX_BACKOFF_SECONDS))
    now = time.time()
    state["backoff_until"] = now + delay
    state["consecutive_rate_limits"] = strikes
    state["last_attempt_at"] = now
    _write_rate_state(state)
    logger.debug(
        "cloud_skills_sync: rate limited, backing off %.0fs (strikes=%d)",
        delay,
        strikes,
    )


def _record_sync_attempt() -> None:
    state = _read_rate_state()
    state["last_attempt_at"] = time.time()
    _write_rate_state(state)


def _record_sync_success() -> None:
    now = time.time()
    _write_rate_state(
        {
            "last_attempt_at": now,
            "last_success_at": now,
            "backoff_until": 0,
            "consecutive_rate_limits": 0,
        }
    )


def _can_attempt_sync(*, force: bool, respect_rate_limit: bool) -> tuple[bool, str]:
    settings = _cloud_sync_settings()
    if not settings.enabled:
        return False, "disabled"
    if not respect_rate_limit:
        return True, ""

    remaining = _rate_limit_backoff_remaining()
    if remaining > 0:
        return False, "backoff"

    state = _read_rate_state()
    now = time.time()
    last_attempt = float(state.get("last_attempt_at") or 0)
    if force:
        if now - last_attempt < settings.min_cooldown_seconds:
            return False, "cooldown"
    elif now - last_attempt < settings.interval_seconds:
        return False, "interval"
    return True, ""


@contextlib.contextmanager
def _cross_process_sync_lock() -> Iterator[bool]:
    """Evita sync concorrente entre CLI, TUI e gateway no mesmo ECTOR_HOME."""
    acquired = False
    handle = None
    try:
        CLOUD_SYNC_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        handle = open(CLOUD_SYNC_LOCK_FILE, "a+", encoding="utf-8")
    except OSError as exc:
        logger.debug("cloud_skills_sync: lock file unavailable (%s), continuing", exc)
        yield True
        return
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except (ImportError, AttributeError, BlockingIOError, OSError):
            acquired = False
        yield acquired
    finally:
        if handle is not None:
            if acquired:
                with contextlib.suppress(Exception):
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def _sync_thread_running() -> bool:
    global _sync_thread
    return _sync_thread is not None and _sync_thread.is_alive()


def _authorization_header() -> Optional[str]:
    """Bearer token com refresh automático (evita 401 em sync em background)."""
    from ector_cli.identity_auth import get_access_token

    token = get_access_token(auto_refresh=True)
    if not token:
        return None
    return f"Bearer {token}"


def _record_cloud_hub_lock(
    slug: str,
    install_dir: Path,
    *,
    checksum: str,
    files: Dict[str, Any],
) -> None:
    """Regista skill gerida na nuvem no lock do hub para `ector skills list`."""
    from tools.skills_hub import HubLockFile, content_hash

    rel = str(install_dir.relative_to(SKILLS_DIR))
    lock = HubLockFile()
    lock.record_install(
        name=slug,
        source="ector-cloud",
        identifier=slug,
        trust_level="official",
        scan_verdict="cloud_sync",
        skill_hash=checksum or content_hash(install_dir),
        install_path=rel,
        files=[k for k in files if isinstance(k, str)],
        metadata={"hub_slug": slug, "cloud_managed": True},
    )


def _auth_base_url() -> str:
    from ector_cli.identity_auth import get_auth_base_url

    return get_auth_base_url().rstrip("/")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _install_files(target_dir: Path, files: Dict[str, Any]) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    wrote_any = False
    for rel_path, content in files.items():
        if not isinstance(rel_path, str) or not rel_path or ".." in rel_path.replace("\\", "/"):
            continue
        if not wrote_any:
            target_dir.mkdir(parents=True, exist_ok=True)
            wrote_any = True
        dest = target_dir / rel_path.replace("\\", "/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            dest.write_bytes(content)
        else:
            dest.write_text(str(content), encoding="utf-8")


def _invalidate_skills_prompt_cache() -> None:
    try:
        from agent.prompt_builder import clear_skills_system_prompt_cache

        clear_skills_system_prompt_cache(clear_snapshot=True)
    except Exception:
        logger.debug("cloud_skills_sync: prompt cache clear failed", exc_info=True)


def _drop_slug_from_cloud_state(slug: str) -> None:
    previous = _read_json(CLOUD_STATE_FILE)
    prev_skills = previous.get("skills") if isinstance(previous.get("skills"), dict) else {}
    if slug not in prev_skills:
        return
    updated = dict(prev_skills)
    updated.pop(slug, None)
    _write_json_atomic(
        CLOUD_STATE_FILE,
        {"skills": updated, "etag": previous.get("etag", "")},
    )


def uninstall_cloud_managed_skill(slug: str) -> bool:
    """Remove pastas locais + lock do hub para uma skill gerida na nuvem."""
    slug = str(slug or "").strip()
    if not slug:
        return False

    from tools.skills_hub import HubLockFile

    paths_to_try: list[Path] = []
    previous = _read_json(CLOUD_STATE_FILE)
    prev_skills = previous.get("skills") if isinstance(previous.get("skills"), dict) else {}
    meta = prev_skills.get(slug) if isinstance(prev_skills, dict) else None
    if isinstance(meta, dict):
        rel = str(meta.get("install_path") or "").strip()
        if rel:
            paths_to_try.append(SKILLS_DIR / rel)
        category = str(meta.get("category") or "").strip()
        if category:
            paths_to_try.append(SKILLS_DIR / category / slug)

    lock = HubLockFile()
    entry = lock.get_installed(slug)
    if entry:
        rel = str(entry.get("install_path") or "").strip()
        if rel:
            paths_to_try.append(SKILLS_DIR / rel)

    paths_to_try.append(SKILLS_DIR / "software-development" / slug)
    paths_to_try.append(SKILLS_DIR / slug)

    removed_any = False
    seen: set[str] = set()
    for target in paths_to_try:
        key = str(target)
        if key in seen:
            continue
        seen.add(key)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            removed_any = True

    if entry:
        try:
            lock.record_uninstall(slug)
        except Exception:
            logger.debug("cloud_skills_sync: hub lock cleanup failed for %s", slug, exc_info=True)

    _drop_slug_from_cloud_state(slug)

    if removed_any:
        _invalidate_skills_prompt_cache()
        try:
            from tools.memory_tool import scrub_skill_name_from_memory

            scrub_skill_name_from_memory(slug)
        except Exception:
            logger.debug(
                "cloud_skills_sync: memory scrub failed for %s", slug, exc_info=True
            )
    return removed_any


def remove_skill_from_cloud_library(slug: str, *, quiet: bool = True) -> Dict[str, Any]:
    """Remove da biblioteca na API e desinstala localmente neste dispositivo."""
    slug = str(slug or "").strip()
    if not slug:
        return {"ok": False, "error": "empty_slug"}

    summary: Dict[str, Any] = {
        "ok": True,
        "slug": slug,
        "api_removed": False,
        "local_removed": False,
    }

    bearer = _authorization_header()
    if bearer is None:
        summary["skipped"] = "not_logged_in"
    else:
        base = _auth_base_url()
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                resp = client.delete(
                    f"{base}/agent/me/skills/{slug}",
                    headers={"Authorization": bearer},
                )
            summary["api_removed"] = resp.status_code in (204, 404)
            if resp.status_code == 401:
                summary["ok"] = False
                summary["skipped"] = "unauthorized"
                if not quiet:
                    from rich.console import Console

                    Console().print(
                        "[yellow]Sessão expirada.[/] Execute [bold]ector login[/] e tente novamente."
                    )
        except httpx.HTTPError as exc:
            logger.debug("remove_skill_from_cloud_library api failed: %s", exc, exc_info=True)
            summary["api_error"] = str(exc)

    summary["local_removed"] = uninstall_cloud_managed_skill(slug)

    with contextlib.suppress(OSError):
        CLOUD_ETAG_FILE.unlink()

    if not quiet:
        from rich.console import Console

        c = Console()
        if summary.get("local_removed") or summary.get("api_removed"):
            c.print(f"[green]Removida:[/] {slug} (biblioteca e pasta local, se existiam).")
        else:
            c.print(f"[dim]Nada a remover localmente para {slug}.[/]")

    return summary


def purge_hub_and_cloud_installed_skills(*, quiet: bool = True) -> Dict[str, Any]:
    """Remove all Hub/cloud-tracked skills from disk (and cloud library when logged in).

    Preserves agent-created / manual local skills that have no hub lock and no
    ``cloud_skills.json`` entry.
    """
    from tools.skills_hub import HubLockFile

    slugs: set[str] = set()
    previous = _read_json(CLOUD_STATE_FILE)
    prev_skills = previous.get("skills") if isinstance(previous.get("skills"), dict) else {}
    for slug in prev_skills.keys():
        s = str(slug).strip()
        if s:
            slugs.add(s)

    try:
        for entry in HubLockFile().list_installed():
            name = str(entry.get("name") or "").strip()
            if name:
                slugs.add(name)
    except Exception:
        logger.debug("purge: hub lock list failed", exc_info=True)

    results: list[Dict[str, Any]] = []
    for slug in sorted(slugs):
        results.append(remove_skill_from_cloud_library(slug, quiet=quiet))

    remaining = _read_json(CLOUD_STATE_FILE)
    rem_skills = remaining.get("skills") if isinstance(remaining.get("skills"), dict) else {}
    if not rem_skills:
        with contextlib.suppress(OSError):
            CLOUD_STATE_FILE.unlink()
        with contextlib.suppress(OSError):
            CLOUD_ETAG_FILE.unlink()

    _invalidate_skills_prompt_cache()
    removed = sum(1 for r in results if r.get("local_removed") or r.get("api_removed"))
    return {
        "ok": True,
        "slugs": sorted(slugs),
        "removed_count": removed,
        "results": results,
    }


def _local_checksum_for_dir(install_dir: Path) -> Optional[str]:
    skill_md = install_dir / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        import hashlib

        return hashlib.sha256(skill_md.read_bytes()).hexdigest()
    except OSError:
        return None


def _iso_timestamp_ms(value: Any) -> Optional[int]:
    from datetime import datetime, timezone

    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except ValueError:
        return None


def _hub_install_dir(entry: Dict[str, Any]) -> Optional[Path]:
    rel = str(entry.get("install_path") or "").strip()
    if not rel:
        return None
    install_dir = SKILLS_DIR / rel
    return install_dir if install_dir.is_dir() else None


def _cloud_skill_needs_local_sync(slug: str, remote_checksum: str, hub_entry: Dict[str, Any]) -> bool:
    if not remote_checksum:
        return False
    install_dir = _hub_install_dir(hub_entry)
    if install_dir is None:
        return True
    local_checksum = _local_checksum_for_dir(install_dir)
    if not local_checksum:
        return True
    return local_checksum != remote_checksum


def _iter_stale_cloud_library_slugs(
    client: httpx.Client,
    base: str,
    headers: Dict[str, str],
) -> list[str]:
    """Slugs em que o catálogo foi atualizado após o vínculo na biblioteca do utilizador."""
    try:
        library_resp = client.get(f"{base}/agent/me/skills", headers=headers)
    except httpx.HTTPError:
        return []
    if library_resp.status_code != 200:
        return []

    rows = library_resp.json()
    if not isinstance(rows, list):
        return []

    stale: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or "").strip()
        if not slug:
            continue
        skill_ms = _iso_timestamp_ms(row.get("skillUpdatedAt"))
        library_ms = _iso_timestamp_ms(row.get("libraryUpdatedAt"))
        if skill_ms is not None and library_ms is not None and skill_ms > library_ms:
            stale.append(slug)
    return stale


def _refresh_stale_cloud_library_links(
    client: httpx.Client,
    base: str,
    headers: Dict[str, str],
    *,
    slugs: Optional[list[str]] = None,
) -> int:
    """Renova vínculos na API (equivalente a «Atualizar» no dashboard)."""
    targets = slugs if slugs is not None else _iter_stale_cloud_library_slugs(client, base, headers)
    refreshed = 0
    for slug in targets:
        try:
            resp = client.post(
                f"{base}/agent/me/skills/{slug}",
                headers=headers,
            )
        except httpx.HTTPError:
            logger.debug("refresh cloud library link failed for %s", slug, exc_info=True)
            continue
        if resp.status_code in (200, 201):
            refreshed += 1
    return refreshed


def collect_cloud_skill_update_names(
    hub_installed: Dict[str, Dict[str, Any]],
) -> set[str]:
    """Skills da biblioteca na nuvem com atualização no servidor ou no disco local."""
    from tools.skills_hub import is_cloud_managed_hub_entry

    cloud_entries = {
        name: entry
        for name, entry in hub_installed.items()
        if is_cloud_managed_hub_entry(entry)
    }
    if not cloud_entries:
        return set()

    bearer = _authorization_header()
    if bearer is None:
        return set()

    pending: set[str] = set()
    base = _auth_base_url()
    headers = {"Authorization": bearer}

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            stale_slugs = _iter_stale_cloud_library_slugs(client, base, headers)
            pending.update(slug for slug in stale_slugs if slug in cloud_entries)

            manifest_headers = dict(headers)
            stored_etag = ""
            if CLOUD_ETAG_FILE.exists():
                stored_etag = CLOUD_ETAG_FILE.read_text(encoding="utf-8").strip()
            if stored_etag:
                manifest_headers["If-None-Match"] = stored_etag

            manifest_resp = client.get(
                f"{base}/agent/me/skills/manifest",
                headers=manifest_headers,
            )
            if manifest_resp.status_code == 200:
                manifest = manifest_resp.json()
                entries = manifest.get("skills") if isinstance(manifest, dict) else None
                if isinstance(entries, list):
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        slug = str(entry.get("slug") or "").strip()
                        if slug not in cloud_entries:
                            continue
                        remote_checksum = str(entry.get("checksumSha256") or "")
                        if _cloud_skill_needs_local_sync(slug, remote_checksum, cloud_entries[slug]):
                            pending.add(slug)
            elif manifest_resp.status_code == 304:
                state = _read_json(CLOUD_STATE_FILE)
                skills_state = state.get("skills") if isinstance(state.get("skills"), dict) else {}
                for slug, hub_entry in cloud_entries.items():
                    if slug in pending:
                        continue
                    meta = skills_state.get(slug) if isinstance(skills_state.get(slug), dict) else {}
                    remote_checksum = str(meta.get("checksumSha256") or "")
                    if _cloud_skill_needs_local_sync(slug, remote_checksum, hub_entry):
                        pending.add(slug)
    except httpx.HTTPError as exc:
        logger.debug("collect_cloud_skill_update_names failed: %s", exc)

    return pending


def _print_cloud_sync_summary(summary: Dict[str, Any], *, quiet: bool) -> None:
    if quiet:
        return
    from rich.console import Console

    c = Console()
    skipped = summary.get("skipped")
    if skipped == "not_logged_in":
        c.print(
            "[yellow]Sessão não encontrada.[/] "
            "Execute [bold]ector login[/] e depois [bold]ector skills sync[/]."
        )
        return
    if skipped in ("sync_in_progress", "rate_limited", "unauthorized"):
        return
    if summary.get("not_modified"):
        refreshed = int(summary.get("library_refreshed") or 0)
        if refreshed:
            c.print(
                f"[green]Biblioteca atualizada:[/] {refreshed} vínculo(s) renovado(s). "
                "[dim]Manifest sem alteração de conteúdo.[/]"
            )
        else:
            c.print("[dim]Biblioteca de skills na nuvem já está atualizada.[/]")
        return
    if not summary.get("ok", True):
        return
    parts: list[str] = []
    refreshed = int(summary.get("library_refreshed") or 0)
    if refreshed:
        parts.append(f"{refreshed} vínculo(s) renovado(s)")
    parts.append(
        f"{summary.get('downloaded', 0)} baixada(s), "
        f"{summary.get('unchanged', 0)} sem alteração, "
        f"{summary.get('removed', 0)} removida(s)"
    )
    msg = f"[green]Sync concluído:[/] {', '.join(parts)}."
    c.print(msg)


def sync_cloud_skills_library(
    *,
    quiet: bool = True,
    prune_legacy: bool = True,
    respect_rate_limit: bool = True,
    refresh_stale_links: bool = True,
) -> Dict[str, Any]:
    """Pull user library from API and update local skill folders."""
    bearer = _authorization_header()
    if bearer is None:
        summary: Dict[str, Any] = {"ok": True, "skipped": "not_logged_in"}
        if prune_legacy:
            legacy = cleanup_legacy_local_skills(quiet=quiet)
            summary["legacy_cleaned"] = legacy.get("removed", 0)
        _print_cloud_sync_summary(summary, quiet=quiet)
        return summary

    settings = _cloud_sync_settings()

    base = _auth_base_url()
    headers = {"Authorization": bearer}
    stored_etag = ""
    if CLOUD_ETAG_FILE.exists():
        stored_etag = CLOUD_ETAG_FILE.read_text(encoding="utf-8").strip()
    if stored_etag:
        headers["If-None-Match"] = stored_etag

    summary: Dict[str, Any] = {
        "ok": True,
        "downloaded": 0,
        "removed": 0,
        "unchanged": 0,
        "not_modified": False,
        "deferred_bundles": 0,
        "library_refreshed": 0,
    }

    with _cross_process_sync_lock() as lock_acquired:
        if not lock_acquired:
            return {"ok": True, "skipped": "sync_in_progress"}

        if respect_rate_limit:
            allowed, reason = _can_attempt_sync(force=False, respect_rate_limit=True)
            if not allowed:
                return {"ok": True, "skipped": reason}

        _record_sync_attempt()

        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                if refresh_stale_links:
                    summary["library_refreshed"] = _refresh_stale_cloud_library_links(
                        client,
                        base,
                        headers,
                    )
                    if int(summary["library_refreshed"]) > 0:
                        with contextlib.suppress(OSError):
                            CLOUD_ETAG_FILE.unlink()
                        stored_etag = ""
                        headers.pop("If-None-Match", None)

                manifest_resp = client.get(f"{base}/agent/me/skills/manifest", headers=headers)
                if manifest_resp.status_code in _RATE_LIMIT_HTTP_CODES:
                    _record_rate_limit(manifest_resp)
                    return {"ok": False, "skipped": "rate_limited"}
                if manifest_resp.status_code == 304:
                    summary["not_modified"] = True
                    _record_sync_success()
                    if prune_legacy:
                        legacy = cleanup_legacy_local_skills(
                            library_slugs=_cloud_library_slugs(),
                            quiet=quiet,
                        )
                        summary["legacy_cleaned"] = legacy.get("removed", 0)
                    _print_cloud_sync_summary(summary, quiet=quiet)
                    return summary
                if manifest_resp.status_code == 401:
                    if not quiet:
                        from rich.console import Console

                        Console().print(
                            "[yellow]Sessão expirada ou inválida.[/] "
                            "Execute [bold]ector login[/] e depois [bold]ector skills sync[/]."
                        )
                    return {"ok": False, "skipped": "unauthorized", "relogin": True}
                manifest_resp.raise_for_status()
                manifest = manifest_resp.json()
                etag = manifest_resp.headers.get("etag", "").strip()
                if etag:
                    CLOUD_ETAG_FILE.write_text(etag, encoding="utf-8")

                entries = manifest.get("skills") if isinstance(manifest, dict) else None
                if not isinstance(entries, list):
                    entries = []

                previous = _read_json(CLOUD_STATE_FILE)
                prev_skills = previous.get("skills") if isinstance(previous.get("skills"), dict) else {}
                new_state: Dict[str, Any] = {}
                pending_downloads: list[Dict[str, Any]] = []
                manifest_slugs: set[str] = set()
                manifest_meta: Dict[str, Dict[str, Any]] = {}

                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    slug = str(entry.get("slug") or "").strip()
                    category = str(entry.get("category") or "general").strip() or "general"
                    checksum = entry.get("checksumSha256")
                    if not slug:
                        continue

                    manifest_slugs.add(slug)
                    install_dir = SKILLS_DIR / category / slug
                    remote_checksum = str(checksum) if checksum else ""
                    manifest_meta[slug] = {
                        "category": category,
                        "install_path": str(install_dir.relative_to(SKILLS_DIR)),
                        "checksumSha256": remote_checksum,
                    }
                    local_checksum = _local_checksum_for_dir(install_dir)

                    if remote_checksum and local_checksum == remote_checksum:
                        summary["unchanged"] += 1
                        new_state[slug] = {
                            "category": category,
                            "install_path": str(install_dir.relative_to(SKILLS_DIR)),
                            "checksumSha256": remote_checksum,
                        }
                        continue

                    pending_downloads.append(
                        {
                            "slug": slug,
                            "category": category,
                            "checksum": remote_checksum,
                            "install_dir": install_dir,
                        }
                    )

                bundles_downloaded = 0
                max_bundles = settings.max_bundles_per_run
                bundle_delay = settings.bundle_delay_seconds

                for index, item in enumerate(pending_downloads):
                    if bundles_downloaded >= max_bundles:
                        summary["deferred_bundles"] = len(pending_downloads) - index
                        break
                    if bundles_downloaded > 0 and bundle_delay > 0:
                        time.sleep(bundle_delay)

                    slug = item["slug"]
                    install_dir = item["install_dir"]
                    remote_checksum = item["checksum"]

                    bundle_resp = client.get(
                        f"{base}/agent/me/skills/{slug}/bundle",
                        headers={"Authorization": bearer},
                    )
                    if bundle_resp.status_code in _RATE_LIMIT_HTTP_CODES:
                        _record_rate_limit(bundle_resp)
                        summary["deferred_bundles"] = len(pending_downloads) - index
                        break
                    if bundle_resp.status_code != 200:
                        logger.debug(
                            "cloud_skills_sync: bundle %s status %s",
                            slug,
                            bundle_resp.status_code,
                        )
                        continue
                    bundle = bundle_resp.json()
                    files = bundle.get("files") if isinstance(bundle, dict) else None
                    if not isinstance(files, dict) or "SKILL.md" not in files:
                        continue

                    _install_files(install_dir, files)
                    final_checksum = remote_checksum or _local_checksum_for_dir(install_dir) or ""
                    _record_cloud_hub_lock(
                        slug,
                        install_dir,
                        checksum=final_checksum,
                        files=files,
                    )
                    summary["downloaded"] += 1
                    bundles_downloaded += 1
                    new_state[slug] = {
                        "category": item["category"],
                        "install_path": str(install_dir.relative_to(SKILLS_DIR)),
                        "checksumSha256": final_checksum,
                    }

                # Slugs still in the API manifest but not updated this run (deferred
                # downloads or bundle failures) must stay in new_state — do not treat
                # them as removed from the user's library.
                for slug in manifest_slugs:
                    if slug in new_state:
                        continue
                    prev_entry = prev_skills.get(slug) if isinstance(prev_skills, dict) else None
                    if isinstance(prev_entry, dict) and prev_entry:
                        new_state[slug] = dict(prev_entry)
                        continue
                    meta = manifest_meta.get(slug)
                    if isinstance(meta, dict):
                        new_state[slug] = dict(meta)

                # Uninstall only when the slug left the cloud library (not in manifest).
                for old_slug in prev_skills:
                    if old_slug in new_state:
                        continue
                    if old_slug in manifest_slugs:
                        continue
                    if uninstall_cloud_managed_skill(str(old_slug)):
                        summary["removed"] += 1

                state_payload = {
                    "skills": new_state,
                    "etag": etag or stored_etag,
                    "last_synced_at": int(time.time()),
                }
                _write_json_atomic(CLOUD_STATE_FILE, state_payload)

                if prune_legacy:
                    legacy = cleanup_legacy_local_skills(
                        library_slugs=set(new_state.keys()),
                        quiet=quiet,
                    )
                    summary["legacy_cleaned"] = legacy.get("removed", 0)

                _record_sync_success()

                if int(summary.get("downloaded") or 0) > 0 or int(summary.get("removed") or 0) > 0:
                    try:
                        from agent.skill_commands import notify_skill_commands_changed

                        notify_skill_commands_changed()
                    except Exception:
                        logger.debug(
                            "cloud_skills_sync: slash command refresh failed",
                            exc_info=True,
                        )
        except httpx.HTTPError as exc:
            logger.debug("cloud_skills_sync failed: %s", exc, exc_info=True)
            return {"ok": False, "error": str(exc)}

    _print_cloud_sync_summary(summary, quiet=quiet)
    return summary


def ensure_onboarding_skill_in_library(
    *,
    slug: str = DEFAULT_ONBOARDING_SKILL_SLUG,
    quiet: bool = True,
) -> Dict[str, Any]:
    """Best-effort: garante a skill onboarding na biblioteca do utilizador."""
    bearer = _authorization_header()
    if bearer is None:
        return {"ok": True, "skipped": "not_logged_in"}

    base = _auth_base_url()
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True) as client:
            resp = client.post(
                f"{base}/agent/me/skills/{slug}",
                headers={"Authorization": bearer},
            )
    except httpx.HTTPError as exc:
        logger.debug("cloud onboarding enrollment failed: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc)}

    if resp.status_code in (200, 201):
        if not quiet:
            from rich.console import Console

            Console().print("[dim]Skill de onboarding vinculada à sua biblioteca.[/]")
        return {"ok": True, "added": slug}
    if resp.status_code == 401:
        return {"ok": False, "skipped": "unauthorized"}
    if resp.status_code == 404:
        # Catálogo pode não ter a skill em ambientes locais.
        return {"ok": True, "skipped": "not_found"}
    if resp.status_code == 409:
        return {"ok": True, "skipped": "already_exists"}
    return {"ok": False, "status": resp.status_code}


def _read_skill_name(skill_md: Path) -> str:
    try:
        content = skill_md.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return skill_md.parent.name
    in_frontmatter = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter and stripped.startswith("name:"):
            value = stripped.split(":", 1)[1].strip().strip("\"'")
            if value:
                return value
    return skill_md.parent.name


def _iter_local_skill_dirs() -> list[tuple[str, Path]]:
    if not SKILLS_DIR.exists():
        return []
    found: list[tuple[str, Path]] = []
    for skill_md in SKILLS_DIR.rglob("SKILL.md"):
        path_str = str(skill_md)
        if "/.hub/" in path_str or "/.git/" in path_str:
            continue
        skill_dir = skill_md.parent
        name = _read_skill_name(skill_md)
        found.append((name, skill_dir))
    return found


def _read_bundled_manifest_names() -> set[str]:
    if not BUNDLED_MANIFEST_FILE.exists():
        return set()
    names: set[str] = set()
    try:
        for line in BUNDLED_MANIFEST_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            name = line.split(":", 1)[0].strip() if ":" in line else line
            if name:
                names.add(name)
    except OSError:
        return set()
    return names


def _official_catalog_slugs() -> set[str]:
    try:
        from tools.skills_hub import _load_ector_index

        index = _load_ector_index() or {}
        skills = index.get("skills") if isinstance(index, dict) else []
        slugs: set[str] = set()
        if isinstance(skills, list):
            for entry in skills:
                if not isinstance(entry, dict):
                    continue
                slug = str(entry.get("slug") or entry.get("name") or "").strip()
                if slug:
                    slugs.add(slug)
        return slugs
    except Exception:
        logger.debug("cleanup: failed to load ector skills index", exc_info=True)
        return set()


def _cloud_library_slugs() -> set[str]:
    previous = _read_json(CLOUD_STATE_FILE)
    prev_skills = previous.get("skills") if isinstance(previous.get("skills"), dict) else {}
    return {str(k).strip() for k in prev_skills if str(k).strip()}


def _hub_lock_entry_for_skill(name: str) -> Optional[Dict[str, Any]]:
    try:
        from tools.skills_hub import HubLockFile

        entry = HubLockFile().get_installed(name)
        return entry if isinstance(entry, dict) else None
    except Exception:
        logger.debug("cleanup: hub lock lookup failed for %s", name, exc_info=True)
        return None


def _is_cloud_managed_hub_entry(entry: Dict[str, Any]) -> bool:
    from tools.skills_hub import is_cloud_managed_hub_entry

    return is_cloud_managed_hub_entry(entry)


def _should_remove_legacy_skill(
    name: str,
    *,
    library: set[str],
    manifest_names: set[str],
    catalog_slugs: set[str],
    hub_entry: Optional[Dict[str, Any]],
    remove_all_not_in_library: bool,
    prune_catalog_not_in_library: bool,
) -> bool:
    """Decide if a local folder is safe to delete during cloud library sync.

    Skills criadas pelo agente (sem entrada no hub lock) nunca são removidas aqui.
    """
    if name in library:
        return False
    if name in manifest_names:
        return True
    if remove_all_not_in_library:
        return True
    if hub_entry is None:
        return False
    if _is_cloud_managed_hub_entry(hub_entry):
        return True
    if prune_catalog_not_in_library and catalog_slugs and name in catalog_slugs:
        return True
    return False


def _remove_skill_dir(skill_dir: Path) -> bool:
    if not skill_dir.exists():
        return False
    try:
        if skill_dir.resolve() == SKILLS_DIR.resolve():
            return False
        if SKILLS_DIR.resolve() not in skill_dir.resolve().parents:
            return False
    except OSError:
        return False
    shutil.rmtree(skill_dir, ignore_errors=True)
    return True


def cleanup_legacy_local_skills(
    *,
    library_slugs: Optional[set[str]] = None,
    use_manifest: bool = True,
    prune_catalog_not_in_library: bool = True,
    remove_all_not_in_library: bool = False,
    quiet: bool = True,
) -> Dict[str, Any]:
    """Remove skills obsoletas do instalador bundled ou geridas na nuvem/hub.

    - ``.bundled_manifest``: skills do instalador antigo.
    - Hub lock ``ector-cloud`` / ``cloud_managed``: órfãs fora da biblioteca.
    - Catálogo público Hub: só se também estiver registada no hub lock.
    - Skills **locais** (sem hub lock, ex.: criadas via ``skill_manage``) são preservadas.
    - ``remove_all_not_in_library=True`` é opt-in explícito (não usado no sync automático).
    """
    library = {str(s).strip() for s in (library_slugs if library_slugs is not None else _cloud_library_slugs()) if str(s).strip()}
    manifest_names = _read_bundled_manifest_names() if use_manifest else set()
    catalog_slugs = _official_catalog_slugs() if prune_catalog_not_in_library else set()

    targets: dict[str, Path] = {}
    for name, skill_dir in _iter_local_skill_dirs():
        hub_entry = _hub_lock_entry_for_skill(name)
        if _should_remove_legacy_skill(
            name,
            library=library,
            manifest_names=manifest_names,
            catalog_slugs=catalog_slugs,
            hub_entry=hub_entry,
            remove_all_not_in_library=remove_all_not_in_library,
            prune_catalog_not_in_library=prune_catalog_not_in_library,
        ):
            targets[name] = skill_dir

    removed_names: list[str] = []
    for name, skill_dir in sorted(targets.items(), key=lambda item: str(item[1])):
        if _remove_skill_dir(skill_dir):
            removed_names.append(name)

    if use_manifest and BUNDLED_MANIFEST_FILE.exists() and (manifest_names or removed_names):
        with contextlib.suppress(OSError):
            BUNDLED_MANIFEST_FILE.unlink()

    if removed_names:
        _invalidate_skills_prompt_cache()
        try:
            from tools.memory_tool import scrub_skill_name_from_memory

            for name in removed_names:
                scrub_skill_name_from_memory(name)
        except Exception:
            logger.debug(
                "cloud_skills_sync: memory scrub failed after legacy cleanup",
                exc_info=True,
            )

    summary = {
        "ok": True,
        "removed": len(removed_names),
        "removed_names": removed_names,
        "library_slugs": sorted(library),
    }
    return summary


def clear_cloud_skills_local_state(*, remove_files: bool = True) -> Dict[str, Any]:
    """Limpa estado local de skills cloud; opcionalmente remove arquivos instalados."""
    previous = _read_json(CLOUD_STATE_FILE)
    prev_skills = previous.get("skills") if isinstance(previous.get("skills"), dict) else {}
    removed = 0

    if remove_files:
        for slug in list(prev_skills.keys()):
            if uninstall_cloud_managed_skill(str(slug)):
                removed += 1

    with contextlib.suppress(OSError):
        CLOUD_STATE_FILE.unlink()
    with contextlib.suppress(OSError):
        CLOUD_ETAG_FILE.unlink()

    return {"ok": True, "removed": removed}


def maybe_schedule_cloud_skills_sync(*, quiet: bool = True, force: bool = False) -> None:
    """Agenda sync em background respeitando cooldown, intervalo e backoff da API.

    ``force=True`` usa apenas o cooldown curto (não o intervalo longo), para arranques
    sem disparar sync a cada comando.
    """
    settings = _cloud_sync_settings()
    if not settings.enabled:
        return
    if _authorization_header() is None:
        return

    allowed, _reason = _can_attempt_sync(force=force, respect_rate_limit=True)
    if not allowed:
        return

    global _last_schedule_monotonic
    now = time.monotonic()
    min_gap = settings.min_cooldown_seconds if force else settings.interval_seconds
    if (now - _last_schedule_monotonic) < min_gap:
        return

    with _sync_lock:
        if _sync_thread_running():
            return
        _last_schedule_monotonic = now

        def _run() -> None:
            global _sync_thread
            try:
                result = sync_cloud_skills_library(quiet=quiet, respect_rate_limit=True)
                if int(result.get("deferred_bundles") or 0) > 0:
                    maybe_schedule_cloud_skills_sync(quiet=True, force=False)
            except Exception:
                logger.debug("cloud_skills_sync background failed", exc_info=True)
            finally:
                with _sync_lock:
                    _sync_thread = None

        thread = threading.Thread(target=_run, name="cloud-skills-sync", daemon=True)
        _sync_thread = thread
        thread.start()


def prime_cloud_skills_for_skills_cli(*, max_wait_seconds: float = 6.0) -> None:
    """Atualiza a biblioteca na nuvem antes de ``ector skills list`` (e similares).

    - Com sessão e dentro do cooldown/backoff: sync bloqueante curto (lista fiel).
    - Caso contrário: agenda em background ou ignora (sem bombardear a API).
    """
    settings = _cloud_sync_settings()
    if not settings.enabled or _authorization_header() is None:
        return

    allowed, reason = _can_attempt_sync(force=True, respect_rate_limit=True)
    if not allowed:
        if reason not in ("backoff", "disabled"):
            maybe_schedule_cloud_skills_sync(quiet=True, force=False)
        return

    deadline = time.monotonic() + max(0.0, float(max_wait_seconds))

    with _sync_lock:
        if _sync_thread_running():
            while _sync_thread_running() and time.monotonic() < deadline:
                time.sleep(0.05)
            if _sync_thread_running():
                return
        try:
            sync_cloud_skills_library(quiet=True, respect_rate_limit=True)
        except Exception:
            logger.debug("cloud_skills_sync skills CLI prime failed", exc_info=True)


def ensure_cloud_skills_for_agent_startup(*, max_wait_seconds: float = 2.5) -> None:
    """Uma vez por processo: sync inicial ou agenda verificação com limites."""
    global _agent_startup_primed
    if _agent_startup_primed:
        return
    _agent_startup_primed = True

    settings = _cloud_sync_settings()
    if not settings.enabled:
        return
    try:
        if _authorization_header() is None:
            return
    except KeyboardInterrupt:
        raise

    has_local_state = CLOUD_STATE_FILE.exists() or CLOUD_ETAG_FILE.exists()
    if has_local_state:
        maybe_schedule_cloud_skills_sync(quiet=True, force=False)
        return

    allowed, _reason = _can_attempt_sync(force=True, respect_rate_limit=True)
    if not allowed:
        maybe_schedule_cloud_skills_sync(quiet=True, force=False)
        return

    deadline = time.monotonic() + max(0.5, float(max_wait_seconds))

    def _blocking_sync() -> None:
        try:
            sync_cloud_skills_library(quiet=True, respect_rate_limit=True)
        except KeyboardInterrupt:
            raise
        except Exception:
            logger.debug("cloud_skills_sync blocking startup failed", exc_info=True)

    with _sync_lock:
        if _sync_thread_running():
            while _sync_thread_running() and time.monotonic() < deadline:
                time.sleep(0.05)
            return
        try:
            _blocking_sync()
        except KeyboardInterrupt:
            raise


def start_periodic_cloud_skills_sync(
    stop_event: threading.Event,
    *,
    interval_seconds: Optional[float] = None,
) -> threading.Thread:
    """Ticker em background para gateway / processos longos."""

    settings = _cloud_sync_settings()
    interval = float(
        interval_seconds if interval_seconds is not None else settings.interval_seconds
    )
    interval = max(_MIN_CLOUD_SYNC_INTERVAL_SECONDS, interval)

    def _loop() -> None:
        while not stop_event.wait(interval):
            if settings.enabled:
                maybe_schedule_cloud_skills_sync(quiet=True, force=False)

    thread = threading.Thread(
        target=_loop,
        name="cloud-skills-sync-ticker",
        daemon=True,
    )
    thread.start()
    return thread


def schedule_cloud_skills_sync(*, quiet: bool = True) -> None:
    """Compat: agenda sync em background (respeita cooldown/backoff)."""
    maybe_schedule_cloud_skills_sync(quiet=quiet, force=False)
