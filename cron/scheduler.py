"""
Cron job scheduler - executes due jobs.

Provides tick() which checks for due jobs and runs them. The gateway
calls this every 60 seconds from a background thread.

Uses a file-based lock (~/.ector/cron/.tick.lock) so only one tick
runs at a time if multiple processes overlap.
"""

import asyncio
import concurrent.futures
import contextvars
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime

# fcntl is Unix-only; on Windows use msvcrt for file locking
try:
    import fcntl
except ImportError:
    fcntl = None
    try:
        import msvcrt
    except ImportError:
        msvcrt = None
from pathlib import Path
from typing import Any, List, Optional

# Add parent directory to path for imports BEFORE repo-level imports.
# Without this, standalone invocations (e.g. after `ector update` reloads
# the module) fail with ModuleNotFoundError for ector_time et al.
sys.path.insert(0, str(Path(__file__).parent.parent))

from ector_constants import get_ector_home
from ector_cli.config import load_config
from ector_time import now as _ector_now

logger = logging.getLogger(__name__)

_ENGINE_MODE_LEGACY = "legacy"
_ENGINE_MODE_APSCHEDULER = "apscheduler"
_ENGINE_MODE_SHADOW = "shadow"
_VALID_ENGINE_MODES = {
    _ENGINE_MODE_LEGACY,
    _ENGINE_MODE_APSCHEDULER,
    _ENGINE_MODE_SHADOW,
}


def _resolve_cron_enabled_toolsets(job: dict, cfg: dict) -> list[str] | None:
    """Resolve the toolset list for a cron job.

    Precedence:
    1. Per-job ``enabled_toolsets`` (set via ``cronjob`` tool on create/update).
       Keeps the agent's job-scoped toolset override intact — #6130.
    2. Per-platform ``ector tools`` config for the ``cron`` platform.
       Mirrors gateway behavior (``_get_platform_tools(cfg, platform_key)``)
       so users can gate cron toolsets globally without recreating every job.
    3. ``None`` on any lookup failure — AIAgent loads the full default set
       (legacy behavior before this change, preserved as the safety net).

    _DEFAULT_OFF_TOOLSETS ({moa, homeassistant, rl}) are removed by
    ``_get_platform_tools`` for unconfigured platforms, so fresh installs
    get cron WITHOUT ``moa`` by default (issue reported by Norbert —
    surprise $4.63 run).
    """
    per_job = job.get("enabled_toolsets")
    if per_job:
        return per_job
    try:
        from ector_cli.tools_config import _get_platform_tools  # lazy: avoid heavy import at cron module load
        return sorted(_get_platform_tools(cfg or {}, "cron"))
    except Exception as exc:
        logger.warning(
            "Cron toolset resolution failed, falling back to full default toolset: %s",
            exc,
        )
        return None

# Valid delivery platforms — used to validate user-supplied platform names
# in cron delivery targets, preventing env var enumeration via crafted names.
_KNOWN_DELIVERY_PLATFORMS = frozenset({
    "telegram",
    "discord",
    "slack",
    "whatsapp",
})

# Platforms that support a configured cron/notification home target, mapped to
# the environment variable used by gateway setup/runtime config.
_HOME_TARGET_ENV_VARS = {
    "telegram": "TELEGRAM_HOME_CHANNEL",
    "discord": "DISCORD_HOME_CHANNEL",
    "slack": "SLACK_HOME_CHANNEL",
    "whatsapp": "WHATSAPP_HOME_CHANNEL",
}

# Legacy env var names kept for back-compat.  Each entry is the current
# primary env var → the previous name.  _get_home_target_chat_id falls
# back to the legacy name if the primary is unset, so users who set the
# old name before the rename keep working until they migrate.
_LEGACY_HOME_TARGET_ENV_VARS = {
    "QQBOT_HOME_CHANNEL": "QQ_HOME_CHANNEL",
}

from cron.jobs import (
    _compute_grace_seconds,
    advance_next_run,
    compute_next_run,
    get_due_jobs,
    list_jobs,
    load_jobs,
    lock_jobs,
    mark_job_run,
    save_job_output,
    save_jobs,
)

# Sentinel: when a cron agent has nothing new to report, it can start its
# response with this marker to suppress delivery.  Output is still saved
# locally for audit.
SILENT_MARKER = "[SILENT]"

_CRON_META_TAG_RE = re.compile(r"\[\s*CRON\s*JOB\s*\]", re.IGNORECASE)
# Decorative rule lines: ASCII/Unicode dashes, box-drawing (U+2500–U+257F), markdown HR.
_RULE_LINE_RE = re.compile(
    r"^\s*(?:[─\-–—═_\u2500-\u257f]|\*{3,}|\.{3,})+\s*$",
)
_CRON_META_PHRASE_RE = re.compile(
    r"(?is)\b(fiquei com a tarefa de lembrar você de|fiquei com a tarefa de lembrar)\b\.?\s*",
)
# Phrases the model sometimes prepends before the actual reminder (same line OK).
_CRON_META_DELIVERY_SUBS = (
    (
        re.compile(
            r"\bum\s+lembrete\s+de\s+[^.!?\n]{0,160}?foi\s+programad[oa][^.!?\n]*[.!?]\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bvocê\s+receberá\s+(?:uma\s+)?lembrança[^.!?\n]{0,220}?[.!?]\s*",
            re.I,
        ),
        "",
    ),
    (
        re.compile(
            r"\bvoce\s+receber[aá]\s+(?:uma\s+)?lembran[cç]a[^.!?\n]{0,220}?[.!?]\s*",
            re.I,
        ),
        "",
    ),
)
_BELL_CHAR = "\U0001f514"
_VARIATION_SEL_16 = "\ufe0f"


def _strip_leading_bells_and_zwsp(line: str) -> str:
    """Remove leading bell emoji, VS16, and common invisible/space chars from a line."""
    s = line
    for _ in range(20):
        t = s.lstrip(" \t\u00a0\u200b\u200c\u200d")
        if t.startswith(_BELL_CHAR):
            t = t[len(_BELL_CHAR) :]
            if t.startswith(_VARIATION_SEL_16):
                t = t[len(_VARIATION_SEL_16) :]
            s = t
            continue
        s = t
        break
    return s


def _cron_recipient_first_name(job: dict) -> Optional[str]:
    """Best-effort first name from job origin for natural greetings."""
    origin = job.get("origin") or {}
    raw = str(origin.get("chat_name") or "").strip()
    if not raw:
        return None
    token = re.split(r"[\s(]+", raw, maxsplit=1)[0].strip()
    return token or None


def _sanitize_cron_delivered_text(text: str, *, job_name: Optional[str] = None) -> str:
    """Strip templated headers/decorations models sometimes emit for cron replies."""
    if not text:
        return text
    stripped = text.strip()
    if stripped.upper() == SILENT_MARKER.upper():
        return SILENT_MARKER
    if stripped.upper().startswith(SILENT_MARKER.upper()):
        return text

    cleaned = _CRON_META_TAG_RE.sub("", text)
    cleaned = _CRON_META_PHRASE_RE.sub("", cleaned)
    for rx, repl in _CRON_META_DELIVERY_SUBS:
        cleaned = rx.sub(repl, cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    lines_out: list[str] = []
    for line in cleaned.splitlines():
        raw_rstrip = line.rstrip()
        stripped_line = _strip_leading_bells_and_zwsp(raw_rstrip).strip()
        if not stripped_line:
            lines_out.append("")
            continue
        if _RULE_LINE_RE.match(raw_rstrip) or _RULE_LINE_RE.match(stripped_line):
            continue
        if stripped_line in {_BELL_CHAR, f"{_BELL_CHAR} {_BELL_CHAR}"}:
            continue
        lines_out.append(stripped_line)

    while lines_out and lines_out[0] == "":
        lines_out.pop(0)
    while lines_out and lines_out[-1] == "":
        lines_out.pop()
    compact: list[str] = []
    prev_blank = False
    for ln in lines_out:
        if ln == "":
            if not prev_blank:
                compact.append("")
            prev_blank = True
        else:
            compact.append(ln)
            prev_blank = False

    jn = (job_name or "").strip()
    if jn and len(compact) >= 2:
        idx_first = next((i for i, x in enumerate(compact) if x.strip()), None)
        idx_second = None
        if idx_first is not None:
            for j in range(idx_first + 1, len(compact)):
                if compact[j].strip():
                    idx_second = j
                    break
        if idx_second is not None and compact[idx_first].strip().casefold() == jn.casefold():
            compact.pop(idx_first)
            while compact and compact[0] == "":
                compact.pop(0)

    return "\n".join(compact).strip()


# Resolve Ector home directory (respects ECTOR_HOME override)
_ector_home = get_ector_home()

# File-based lock prevents concurrent ticks from gateway + daemon + systemd timer
_LOCK_DIR = _ector_home / "cron"
_LOCK_FILE = _LOCK_DIR / ".tick.lock"
_PARITY_LOG_FILE = _LOCK_DIR / "scheduler-parity.jsonl"


def _resolve_cron_engine_mode() -> str:
    """Resolve cron scheduling engine mode from env/config with safe fallback."""
    env_mode = (os.getenv("ECTOR_CRON_ENGINE", "") or "").strip().lower()
    if env_mode in _VALID_ENGINE_MODES:
        return env_mode

    cfg_mode = ""
    try:
        cfg = load_config() or {}
        cfg_mode = str((cfg.get("cron", {}) or {}).get("engine", "")).strip().lower()
    except Exception:
        cfg_mode = ""

    if cfg_mode in _VALID_ENGINE_MODES:
        return cfg_mode
    return _ENGINE_MODE_LEGACY


def _write_scheduler_parity_event(event: dict[str, Any]) -> None:
    """Append a scheduler parity event to JSONL for shadow/validation mode."""
    try:
        _LOCK_DIR.mkdir(parents=True, exist_ok=True)
        with open(_PARITY_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=True) + "\n")
    except Exception as exc:
        logger.debug("Failed to persist scheduler parity event: %s", exc)


def _collect_apscheduler_projection_drift() -> list[dict[str, Any]]:
    """Compare stored next_run_at against APScheduler trigger projections.

    This is read-only telemetry used in shadow mode to measure migration parity
    before switching execution semantics.
    """
    try:
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.date import DateTrigger
        from apscheduler.triggers.interval import IntervalTrigger
    except Exception:
        return []

    try:
        from cron.jobs import list_jobs
        jobs = list_jobs(include_disabled=True)
    except Exception:
        return []

    now = _ector_now()
    drifts: list[dict[str, Any]] = []

    for job in jobs:
        if not job.get("enabled", True):
            continue
        schedule = job.get("schedule", {}) or {}
        kind = schedule.get("kind")
        trigger = None

        try:
            if kind == "once":
                run_at = schedule.get("run_at")
                if run_at:
                    trigger = DateTrigger(run_date=datetime.fromisoformat(run_at))
            elif kind == "interval":
                seconds = int(schedule.get("seconds") or 0)
                if seconds > 0:
                    trigger = IntervalTrigger(seconds=seconds, timezone=now.tzinfo)
            elif kind == "cron":
                expr = schedule.get("expr")
                if expr:
                    trigger = CronTrigger.from_crontab(expr, timezone=now.tzinfo)

            if trigger is None:
                continue

            expected_next = trigger.get_next_fire_time(None, now)
            stored_next_raw = job.get("next_run_at")
            if expected_next is None or not stored_next_raw:
                continue
            stored_next = datetime.fromisoformat(stored_next_raw)
            drift_seconds = abs((stored_next - expected_next).total_seconds())
            drifts.append(
                {
                    "job_id": job.get("id"),
                    "kind": kind,
                    "stored_next_run_at": stored_next.isoformat(),
                    "aps_expected_next_run_at": expected_next.isoformat(),
                    "drift_seconds": drift_seconds,
                }
            )
        except Exception:
            continue

    return drifts


def _resolve_max_parallel_workers() -> Optional[int]:
    """Resolve max parallel workers: env var > config.yaml > unbounded."""
    max_workers: Optional[int] = None
    try:
        env_parallel = os.getenv("ECTOR_CRON_MAX_PARALLEL", "").strip()
        if env_parallel:
            max_workers = int(env_parallel) or None
    except (ValueError, TypeError):
        logger.warning("Invalid ECTOR_CRON_MAX_PARALLEL value; defaulting to unbounded")
    if max_workers is None:
        try:
            user_cfg = load_config() or {}
            cfg_parallel = (
                user_cfg.get("cron", {}) if isinstance(user_cfg, dict) else {}
            ).get("max_parallel_jobs")
            if cfg_parallel is not None:
                max_workers = int(cfg_parallel) or None
        except Exception:
            pass
    return max_workers


def _process_due_jobs(
    due_jobs: list[dict[str, Any]],
    *,
    verbose: bool,
    adapters=None,
    loop=None,
    scheduler_label: str = "legacy",
) -> int:
    """Run due jobs end-to-end preserving current delivery and status semantics."""
    if verbose:
        logger.info(
            "[%s] Running %d job(s) in parallel (max_workers=%s)",
            scheduler_label,
            len(due_jobs),
            (_resolve_max_parallel_workers() or "unbounded"),
        )

    max_workers = _resolve_max_parallel_workers()

    def _process_job(job: dict) -> bool:
        """Run one due job end-to-end: execute, save, deliver, mark."""
        try:
            success, output, final_response, error = run_job(job)

            output_file = save_job_output(job["id"], output)
            if verbose:
                logger.info("Output saved to: %s", output_file)

            deliver_content = final_response if success else f"▲ Cron job '{job.get('name', job['id'])}' failed:\n{error}"
            should_deliver = bool(deliver_content)
            if should_deliver and success and SILENT_MARKER in deliver_content.strip().upper():
                logger.info("Job '%s': agent returned %s — skipping delivery", job["id"], SILENT_MARKER)
                should_deliver = False

            delivery_error = None
            if should_deliver:
                try:
                    delivery_error = _deliver_result(job, deliver_content, adapters=adapters, loop=loop)
                except Exception as de:
                    delivery_error = str(de)
                    logger.error("Delivery failed for job %s: %s", job["id"], de)

            if success and not final_response:
                success = False
                error = "Agent completed but produced empty response (model error, timeout, or misconfiguration)"

            mark_job_run(job["id"], success, error, delivery_error=delivery_error)
            return True

        except Exception as e:
            logger.error("Error processing job %s: %s", job['id'], e)
            mark_job_run(job["id"], False, str(e))
            return False

    workdir_jobs = [j for j in due_jobs if (j.get("workdir") or "").strip()]
    parallel_jobs = [j for j in due_jobs if not (j.get("workdir") or "").strip()]
    results: list[bool] = []

    for job in workdir_jobs:
        job_ctx = contextvars.copy_context()
        results.append(job_ctx.run(_process_job, job))

    if parallel_jobs:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as tick_pool:
            futures = []
            for job in parallel_jobs:
                job_ctx = contextvars.copy_context()
                futures.append(tick_pool.submit(job_ctx.run, _process_job, job))
            results.extend(f.result() for f in futures)

    try:
        from tools.mcp_tool import _kill_orphaned_mcp_children
        _kill_orphaned_mcp_children()
    except Exception as sweep_error:
        logger.debug("Post-tick MCP orphan cleanup failed: %s", sweep_error)

    return sum(results)


def _get_due_jobs_apscheduler() -> list[dict[str, Any]]:
    """Select due jobs using APScheduler trigger projections.

    This path keeps jobs.json as source-of-truth while projecting due windows
    with APScheduler triggers. It preserves legacy grace/fast-forward behavior.
    """
    try:
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.date import DateTrigger
        from apscheduler.triggers.interval import IntervalTrigger
    except Exception:
        logger.warning("APScheduler not available; using legacy due job selector")
        return get_due_jobs()

    now = _ector_now()
    jobs = list_jobs(include_disabled=False)
    due_jobs: list[dict[str, Any]] = []
    fast_forwards: dict[str, str] = {}

    for job in jobs:
        next_run_raw = job.get("next_run_at")
        if not next_run_raw:
            continue
        try:
            next_run = datetime.fromisoformat(next_run_raw)
        except Exception:
            continue

        schedule = job.get("schedule", {}) or {}
        kind = schedule.get("kind")
        trigger = None

        try:
            if kind == "once":
                trigger = DateTrigger(run_date=next_run)
            elif kind == "interval":
                seconds = int(schedule.get("seconds") or 0)
                if seconds > 0:
                    trigger = IntervalTrigger(seconds=seconds, start_date=next_run, timezone=now.tzinfo)
            elif kind == "cron":
                expr = schedule.get("expr")
                if expr:
                    trigger = CronTrigger.from_crontab(expr, timezone=now.tzinfo)
        except Exception:
            trigger = None

        if trigger is None:
            if next_run <= now:
                due_jobs.append(job)
            continue

        fire_time = trigger.get_next_fire_time(None, now)
        is_due = next_run <= now
        if fire_time is not None:
            is_due = is_due or (fire_time <= now)
        if not is_due:
            continue

        grace = _compute_grace_seconds(schedule)
        if kind in ("cron", "interval") and (now - next_run).total_seconds() > grace:
            new_next = compute_next_run(schedule, now.isoformat())
            if new_next:
                fast_forwards[job["id"]] = new_next
            continue

        due_jobs.append(job)

    if fast_forwards:
        with lock_jobs():
            raw_jobs = load_jobs()
            changed = False
            for raw in raw_jobs:
                job_id = raw.get("id")
                if job_id in fast_forwards:
                    raw["next_run_at"] = fast_forwards[job_id]
                    changed = True
            if changed:
                save_jobs(raw_jobs)

    return due_jobs


def _get_due_jobs_legacy_preview() -> list[dict[str, Any]]:
    """Best-effort legacy due projection without mutating jobs.json."""
    now = _ector_now()
    jobs = list_jobs(include_disabled=False)
    preview_due: list[dict[str, Any]] = []
    for job in jobs:
        next_run_raw = job.get("next_run_at")
        if not next_run_raw:
            continue
        try:
            next_run = datetime.fromisoformat(next_run_raw)
        except Exception:
            continue
        if next_run <= now:
            preview_due.append(job)
    return preview_due


def _resolve_origin(job: dict) -> Optional[dict]:
    """Extract origin info from a job, preserving any extra routing metadata."""
    origin = job.get("origin")
    if not origin:
        return None
    platform = origin.get("platform")
    chat_id = origin.get("chat_id")
    if platform and chat_id:
        return origin
    return None


def _get_home_target_chat_id(platform_name: str) -> str:
    """Return the configured home target chat/room ID for a delivery platform."""
    env_var = _HOME_TARGET_ENV_VARS.get(platform_name.lower())
    if not env_var:
        return ""
    value = os.getenv(env_var, "")
    if not value:
        legacy = _LEGACY_HOME_TARGET_ENV_VARS.get(env_var)
        if legacy:
            value = os.getenv(legacy, "")
    return value


def _resolve_single_delivery_target(job: dict, deliver_value: str) -> Optional[dict]:
    """Resolve one concrete auto-delivery target for a cron job."""

    origin = _resolve_origin(job)

    if deliver_value == "local":
        return None

    if deliver_value == "origin":
        if origin:
            return {
                "platform": origin["platform"],
                "chat_id": str(origin["chat_id"]),
                "thread_id": origin.get("thread_id"),
            }
        # Origin missing (e.g. job created via API/script) — try each
        # platform's home channel as a fallback instead of silently dropping.
        for platform_name in _HOME_TARGET_ENV_VARS:
            chat_id = _get_home_target_chat_id(platform_name)
            if chat_id:
                logger.info(
                    "Job '%s' has deliver=origin but no origin; falling back to %s home channel",
                    job.get("name", job.get("id", "?")),
                    platform_name,
                )
                return {
                    "platform": platform_name,
                    "chat_id": chat_id,
                    "thread_id": None,
                }
        return None

    if ":" in deliver_value:
        platform_name, rest = deliver_value.split(":", 1)
        platform_key = platform_name.lower()

        from tools.send_message_tool import _parse_target_ref

        parsed_chat_id, parsed_thread_id, is_explicit = _parse_target_ref(platform_key, rest)
        if is_explicit:
            chat_id, thread_id = parsed_chat_id, parsed_thread_id
        else:
            chat_id, thread_id = rest, None

        # Resolve human-friendly labels like "Alice (dm)" to real IDs.
        try:
            from gateway.channel_directory import resolve_channel_name
            resolved = resolve_channel_name(platform_key, chat_id)
            if resolved:
                parsed_chat_id, parsed_thread_id, resolved_is_explicit = _parse_target_ref(platform_key, resolved)
                if resolved_is_explicit:
                    chat_id, thread_id = parsed_chat_id, parsed_thread_id
                else:
                    chat_id = resolved
        except Exception:
            pass

        return {
            "platform": platform_name,
            "chat_id": chat_id,
            "thread_id": thread_id,
        }

    platform_name = deliver_value
    if origin and origin.get("platform") == platform_name:
        return {
            "platform": platform_name,
            "chat_id": str(origin["chat_id"]),
            "thread_id": origin.get("thread_id"),
        }

    if platform_name.lower() not in _KNOWN_DELIVERY_PLATFORMS:
        return None
    chat_id = _get_home_target_chat_id(platform_name)
    if not chat_id:
        return None

    return {
        "platform": platform_name,
        "chat_id": chat_id,
        "thread_id": None,
    }


def _resolve_delivery_targets(job: dict) -> List[dict]:
    """Resolve all concrete auto-delivery targets for a cron job (supports comma-separated deliver)."""
    deliver = job.get("deliver", "local")
    if deliver == "local":
        return []
    parts = [p.strip() for p in str(deliver).split(",") if p.strip()]
    seen = set()
    targets = []
    for part in parts:
        target = _resolve_single_delivery_target(job, part)
        if target:
            key = (target["platform"].lower(), str(target["chat_id"]), target.get("thread_id"))
            if key not in seen:
                seen.add(key)
                targets.append(target)
    return targets


def _resolve_delivery_target(job: dict) -> Optional[dict]:
    """Resolve the concrete auto-delivery target for a cron job, if any."""
    targets = _resolve_delivery_targets(job)
    return targets[0] if targets else None


# Media extension sets — keep in sync with gateway/platforms/base.py:_process_message_background
_AUDIO_EXTS = frozenset({'.ogg', '.opus', '.mp3', '.wav', '.m4a'})
_VIDEO_EXTS = frozenset({'.mp4', '.mov', '.avi', '.mkv', '.webm', '.3gp'})
_IMAGE_EXTS = frozenset({'.jpg', '.jpeg', '.png', '.webp', '.gif'})


def _send_media_via_adapter(adapter, chat_id: str, media_files: list, metadata: dict | None, loop, job: dict) -> None:
    """Send extracted MEDIA files as native platform attachments via a live adapter.

    Routes each file to the appropriate adapter method (send_voice, send_image_file,
    send_video, send_document) based on file extension — mirroring the routing logic
    in ``BasePlatformAdapter._process_message_background``.
    """
    from pathlib import Path

    for media_path, _is_voice in media_files:
        try:
            ext = Path(media_path).suffix.lower()
            if ext in _AUDIO_EXTS:
                coro = adapter.send_voice(chat_id=chat_id, audio_path=media_path, metadata=metadata)
            elif ext in _VIDEO_EXTS:
                coro = adapter.send_video(chat_id=chat_id, video_path=media_path, metadata=metadata)
            elif ext in _IMAGE_EXTS:
                coro = adapter.send_image_file(chat_id=chat_id, image_path=media_path, metadata=metadata)
            else:
                coro = adapter.send_document(chat_id=chat_id, file_path=media_path, metadata=metadata)

            future = asyncio.run_coroutine_threadsafe(coro, loop)
            try:
                result = future.result(timeout=30)
            except TimeoutError:
                future.cancel()
                raise
            if result and not getattr(result, "success", True):
                logger.warning(
                    "Job '%s': media send failed for %s: %s",
                    job.get("id", "?"), media_path, getattr(result, "error", "unknown"),
                )
        except Exception as e:
            logger.warning("Job '%s': failed to send media %s: %s", job.get("id", "?"), media_path, e)


def _deliver_result(job: dict, content: str, adapters=None, loop=None) -> Optional[str]:
    """
    Deliver job output to the configured target(s) (origin chat, specific platform, etc.).

    When ``adapters`` and ``loop`` are provided (gateway is running), tries to
    use the live adapter first — this supports E2EE rooms (e.g. Matrix) where
    the standalone HTTP path cannot encrypt.  Falls back to standalone send if
    the adapter path fails or is unavailable.

    Returns None on success, or an error string on failure.
    """
    targets = _resolve_delivery_targets(job)
    if not targets:
        if job.get("deliver", "local") != "local":
            msg = f"no delivery target resolved for deliver={job.get('deliver', 'local')}"
            logger.warning("Job '%s': %s", job["id"], msg)
            return msg
        return None  # local-only jobs don't deliver — not a failure

    from tools.send_message_tool import _send_to_platform
    from gateway.config import load_gateway_config, Platform

    platform_map = {
        "telegram": Platform.TELEGRAM,
        "discord": Platform.DISCORD,
        "slack": Platform.SLACK,
        "whatsapp": Platform.WHATSAPP,
    }

    delivery_content = content
    delivery_content = _sanitize_cron_delivered_text(
        delivery_content,
        job_name=str((job.get("name") or "")).strip() or None,
    )

    # Extract MEDIA: tags so attachments are forwarded as files, not raw text
    from gateway.platforms.base import BasePlatformAdapter
    media_files, cleaned_delivery_content = BasePlatformAdapter.extract_media(delivery_content)

    try:
        config = load_gateway_config()
    except Exception as e:
        msg = f"failed to load gateway config: {e}"
        logger.error("Job '%s': %s", job["id"], msg)
        return msg

    delivery_errors = []

    for target in targets:
        platform_name = target["platform"]
        chat_id = target["chat_id"]
        thread_id = target.get("thread_id")

        # Diagnostic: log thread_id for topic-aware delivery debugging
        origin = job.get("origin") or {}
        origin_thread = origin.get("thread_id")
        if origin_thread and not thread_id:
            logger.warning(
                "Job '%s': origin has thread_id=%s but delivery target lost it "
                "(deliver=%s, target=%s)",
                job["id"], origin_thread, job.get("deliver", "local"), target,
            )
        elif thread_id:
            logger.debug(
                "Job '%s': delivering to %s:%s thread_id=%s",
                job["id"], platform_name, chat_id, thread_id,
            )

        platform = platform_map.get(platform_name.lower())
        if not platform:
            msg = f"unknown platform '{platform_name}'"
            logger.warning("Job '%s': %s", job["id"], msg)
            delivery_errors.append(msg)
            continue

        # Prefer the live adapter when the gateway is running — this supports E2EE
        # rooms (e.g. Matrix) where the standalone HTTP path cannot encrypt.
        runtime_adapter = (adapters or {}).get(platform)
        delivered = False
        if runtime_adapter is not None and loop is not None and getattr(loop, "is_running", lambda: False)():
            send_metadata = {"thread_id": thread_id} if thread_id else None
            try:
                # Send cleaned text (MEDIA tags stripped) — not the raw content
                text_to_send = cleaned_delivery_content.strip()
                adapter_ok = True
                if text_to_send:
                    future = asyncio.run_coroutine_threadsafe(
                        runtime_adapter.send(chat_id, text_to_send, metadata=send_metadata),
                        loop,
                    )
                    try:
                        send_result = future.result(timeout=60)
                    except TimeoutError:
                        future.cancel()
                        raise
                    if send_result and not getattr(send_result, "success", True):
                        err = getattr(send_result, "error", "unknown")
                        logger.warning(
                            "Job '%s': live adapter send to %s:%s failed (%s), falling back to standalone",
                            job["id"], platform_name, chat_id, err,
                        )
                        adapter_ok = False  # fall through to standalone path

                # Send extracted media files as native attachments via the live adapter
                if adapter_ok and media_files:
                    _send_media_via_adapter(runtime_adapter, chat_id, media_files, send_metadata, loop, job)

                if adapter_ok:
                    logger.info("Job '%s': delivered to %s:%s via live adapter", job["id"], platform_name, chat_id)
                    delivered = True
            except Exception as e:
                logger.warning(
                    "Job '%s': live adapter delivery to %s:%s failed (%s), falling back to standalone",
                    job["id"], platform_name, chat_id, e,
                )

        if not delivered:
            pconfig = config.platforms.get(platform)
            if not pconfig or not pconfig.enabled:
                msg = f"platform '{platform_name}' not configured/enabled"
                logger.warning("Job '%s': %s", job["id"], msg)
                delivery_errors.append(msg)
                continue

            # Standalone path: run the async send in a fresh event loop (safe from any thread)
            coro = _send_to_platform(platform, pconfig, chat_id, cleaned_delivery_content, thread_id=thread_id, media_files=media_files)
            try:
                result = asyncio.run(coro)
            except RuntimeError:
                # asyncio.run() checks for a running loop before awaiting the coroutine;
                # when it raises, the original coro was never started — close it to
                # prevent "coroutine was never awaited" RuntimeWarning, then retry in a
                # fresh thread that has no running loop.
                coro.close()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, _send_to_platform(platform, pconfig, chat_id, cleaned_delivery_content, thread_id=thread_id, media_files=media_files))
                    result = future.result(timeout=30)
            except Exception as e:
                msg = f"delivery to {platform_name}:{chat_id} failed: {e}"
                logger.error("Job '%s': %s", job["id"], msg)
                delivery_errors.append(msg)
                continue

            if result and result.get("error"):
                msg = f"delivery error: {result['error']}"
                logger.error("Job '%s': %s", job["id"], msg)
                delivery_errors.append(msg)
                continue

            logger.info("Job '%s': delivered to %s:%s", job["id"], platform_name, chat_id)

    if delivery_errors:
        return "; ".join(delivery_errors)
    return None


_DEFAULT_SCRIPT_TIMEOUT = 120  # seconds
# Backward-compatible module override used by tests and emergency monkeypatches.
_SCRIPT_TIMEOUT = _DEFAULT_SCRIPT_TIMEOUT


def _get_script_timeout() -> int:
    """Resolve cron pre-run script timeout from module/env/config with a safe default."""
    if _SCRIPT_TIMEOUT != _DEFAULT_SCRIPT_TIMEOUT:
        try:
            timeout = int(float(_SCRIPT_TIMEOUT))
            if timeout > 0:
                return timeout
        except Exception:
            logger.warning("Invalid patched _SCRIPT_TIMEOUT=%r; using env/config/default", _SCRIPT_TIMEOUT)

    env_value = os.getenv("ECTOR_CRON_SCRIPT_TIMEOUT", "").strip()
    if env_value:
        try:
            timeout = int(float(env_value))
            if timeout > 0:
                return timeout
        except Exception:
            logger.warning("Invalid ECTOR_CRON_SCRIPT_TIMEOUT=%r; using config/default", env_value)

    try:
        cfg = load_config() or {}
        cron_cfg = cfg.get("cron", {}) if isinstance(cfg, dict) else {}
        configured = cron_cfg.get("script_timeout_seconds")
        if configured is not None:
            timeout = int(float(configured))
            if timeout > 0:
                return timeout
    except Exception as exc:
        logger.debug("Failed to load cron script timeout from config: %s", exc)

    return _DEFAULT_SCRIPT_TIMEOUT


def _run_job_script(script_path: str) -> tuple[bool, str]:
    """Execute a cron job's data-collection script and capture its output.

    Scripts must reside within ECTOR_HOME/scripts/.  Both relative and
    absolute paths are resolved and validated against this directory to
    prevent arbitrary script execution via path traversal or absolute
    path injection.

    Args:
        script_path: Path to a Python script.  Relative paths are resolved
            against ECTOR_HOME/scripts/.  Absolute and ~-prefixed paths
            are also validated to ensure they stay within the scripts dir.

    Returns:
        (success, output) — on failure *output* contains the error message so the
        LLM can report the problem to the user.
    """
    from ector_constants import get_ector_home

    scripts_dir = get_ector_home() / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir_resolved = scripts_dir.resolve()

    raw = Path(script_path).expanduser()
    if raw.is_absolute():
        path = raw.resolve()
    else:
        path = (scripts_dir / raw).resolve()

    # Guard against path traversal, absolute path injection, and symlink
    # escape — scripts MUST reside within ECTOR_HOME/scripts/.
    try:
        path.relative_to(scripts_dir_resolved)
    except ValueError:
        return False, (
            f"Blocked: script path resolves outside the scripts directory "
            f"({scripts_dir_resolved}): {script_path!r}"
        )

    if not path.exists():
        return False, f"Script not found: {path}"
    if not path.is_file():
        return False, f"Script path is not a file: {path}"

    script_timeout = _get_script_timeout()

    try:
        result = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=script_timeout,
            cwd=str(path.parent),
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        # Redact secrets from both stdout and stderr before any return path.
        try:
            from agent.redact import redact_sensitive_text
            stdout = redact_sensitive_text(stdout)
            stderr = redact_sensitive_text(stderr)
        except Exception:
            pass

        if result.returncode != 0:
            parts = [f"Script exited with code {result.returncode}"]
            if stderr:
                parts.append(f"stderr:\n{stderr}")
            if stdout:
                parts.append(f"stdout:\n{stdout}")
            return False, "\n".join(parts)

        return True, stdout

    except subprocess.TimeoutExpired:
        return False, f"Script timed out after {script_timeout}s: {path}"
    except Exception as exc:
        return False, f"Script execution failed: {exc}"


def _parse_wake_gate(script_output: str) -> bool:
    """Parse the last non-empty stdout line of a cron job's pre-check script
    as a wake gate.

    The convention (ported from nanoclaw #1232): if the last stdout line is
    JSON like ``{"wakeAgent": false}``, the agent is skipped entirely — no
    LLM run, no delivery. Any other output (non-JSON, missing flag, gate
    absent, or ``wakeAgent: true``) means wake the agent normally.

    Returns True if the agent should wake, False to skip.
    """
    if not script_output:
        return True
    stripped_lines = [line for line in script_output.splitlines() if line.strip()]
    if not stripped_lines:
        return True
    last_line = stripped_lines[-1].strip()
    try:
        gate = json.loads(last_line)
    except (json.JSONDecodeError, ValueError):
        return True
    if not isinstance(gate, dict):
        return True
    return gate.get("wakeAgent", True) is not False


def _build_job_prompt(job: dict, prerun_script: Optional[tuple] = None) -> str:
    """Build the effective prompt for a cron job, optionally loading one or more skills first.

    Args:
        job: The cron job dict.
        prerun_script: Optional ``(success, stdout)`` from a script that has
            already been executed by the caller (e.g. for a wake-gate check).
            When provided, the script is not re-executed and the cached
            result is used for prompt injection. When omitted, the script
            (if any) runs inline as before.
    """
    prompt = job.get("prompt", "")
    skills = job.get("skills")

    # Run data-collection script if configured, inject output as context.
    script_path = job.get("script")
    if script_path:
        if prerun_script is not None:
            success, script_output = prerun_script
        else:
            success, script_output = _run_job_script(script_path)
        if success:
            if script_output:
                prompt = (
                    "## Script Output\n"
                    "The following data was collected by a pre-run script. "
                    "Use it as context for your analysis.\n\n"
                    f"```\n{script_output}\n```\n\n"
                    f"{prompt}"
                )
            else:
                prompt = (
                    "[Script ran successfully but produced no output.]\n\n"
                    f"{prompt}"
                )
        else:
            prompt = (
                "## Script Error\n"
                "The data-collection script failed. Report this to the user.\n\n"
                f"```\n{script_output}\n```\n\n"
                f"{prompt}"
            )

    # Inject output from referenced cron jobs as context.
    context_from = job.get("context_from")
    if context_from:
        from cron.jobs import OUTPUT_DIR
        if isinstance(context_from, str):
            context_from = [context_from]
        # Resolve "self" sentinel to the running job's own ID so a recurring
        # monitoring job can see its previous run's output and avoid
        # re-reporting the same items (delta-mode for inbox watchers,
        # feeds, dashboards, etc.).
        own_id = job.get("id")
        for source_job_id in context_from:
            is_self = isinstance(source_job_id, str) and source_job_id.strip().lower() == "self"
            if is_self:
                if not own_id:
                    continue
                source_job_id = own_id
            # Guard against path traversal — valid job IDs are 12-char hex strings
            if not source_job_id or not all(c in "0123456789abcdef" for c in source_job_id):
                logger.warning("context_from: skipping invalid job_id %r", source_job_id)
                continue
            try:
                job_output_dir = OUTPUT_DIR / source_job_id
                if not job_output_dir.exists():
                    continue  # silent skip — no output yet
                output_files = sorted(
                    job_output_dir.glob("*.md"),
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )
                if not output_files:
                    continue  # silent skip — no output yet
                latest_output = output_files[0].read_text(encoding="utf-8").strip()
                # Truncate to 8K characters to avoid prompt bloat
                _MAX_CONTEXT_CHARS = 8000
                if len(latest_output) > _MAX_CONTEXT_CHARS:
                    latest_output = latest_output[:_MAX_CONTEXT_CHARS] + "\n\n[... output truncated ...]"
                if latest_output:
                    if is_self:
                        header = (
                            "## Previous Run Output (same job)\n"
                            "This is the output you produced on the most recent run of "
                            "this same cron job. Treat it as the delta baseline: only "
                            "report items that are genuinely new or changed since then. "
                            "If nothing has materially changed, respond with exactly "
                            "\"[SILENT]\" alone to suppress delivery.\n\n"
                        )
                    else:
                        header = (
                            f"## Output from job '{source_job_id}'\n"
                            "The following is the most recent output from a preceding "
                            "cron job. Use it as context for your analysis.\n\n"
                        )
                    prompt = (
                        f"{header}"
                        f"```\n{latest_output}\n```\n\n"
                        f"{prompt}"
                    )
                else:
                    continue  # silent skip — empty output
            except (OSError, PermissionError) as e:
                logger.warning("context_from: failed to read output for job %r: %s", source_job_id, e)
                # silent skip — do not pollute the prompt with error messages

    # Always prepend cron execution guidance so the agent knows how
    # delivery works and can suppress delivery when appropriate.
    _greet = _cron_recipient_first_name(job)
    _greet_hint = (
        f"If the job has an origin chat_name, greet naturally in the user's language "
        f"(Portuguese example: \"Ei {_greet}, ...\" — use only the first name; omit if unknown). "
        if _greet
        else "If you know the user's first name from context, greet naturally; otherwise skip a formal greeting. "
    )
    cron_hint = (
        "[IMPORTANT: Scheduled cron job. "
        "DELIVERY: Final reply is sent automatically — do NOT call send_message. "
        "SILENT: If nothing to say — including when a 'Previous Run Output' block is "
        "provided and the current state has not materially changed since then "
        "(same emails, same items, same data) — output exactly \"[SILENT]\" alone "
        "(never mix with other text). Do NOT re-deliver items already reported in the "
        "previous-run output. "
        "STYLE: One short, warm line (like a friend); no title/banner/bell emoji/decorative lines, "
        "no job name as headline, no \"Lembrete:\" / \"Reminder:\" opener, no meta narration "
        "(e.g. \"Fiquei com a tarefa de lembrar\", \"[CRON JOB]\"). "
        f"{_greet_hint}"
        "In Portuguese: keep tone light and non-corporate; skip wellness clichés unless the user asked that register. "
        "]\n\n"
    )
    prompt = cron_hint + prompt
    if skills is None:
        legacy = job.get("skill")
        skills = [legacy] if legacy else []

    skill_names = [str(name).strip() for name in skills if str(name).strip()]
    if not skill_names:
        return prompt

    from tools.skills_tool import skill_view

    parts = []
    skipped: list[str] = []
    for skill_name in skill_names:
        loaded = json.loads(skill_view(skill_name))
        if not loaded.get("success"):
            error = loaded.get("error") or f"Failed to load skill '{skill_name}'"
            logger.warning("Cron job '%s': skill not found, skipping — %s", job.get("name", job.get("id")), error)
            skipped.append(skill_name)
            continue

        content = str(loaded.get("content") or "").strip()
        if parts:
            parts.append("")
        parts.extend(
            [
                f'[IMPORTANT: The user has invoked the "{skill_name}" skill, indicating they want you to follow its instructions. The full skill content is loaded below.]',
                "",
                content,
            ]
        )

    if skipped:
        notice = (
            f"[IMPORTANT: The following skill(s) were listed for this job but could not be found "
            f"and were skipped: {', '.join(skipped)}. "
            f"Start your response with a brief notice so the user is aware, e.g.: "
            f"'▲ Skill(s) not found and skipped: {', '.join(skipped)}']"
        )
        parts.insert(0, notice)

    if prompt:
        parts.extend(["", f"The user has provided the following instruction alongside the skill invocation: {prompt}"])
    return "\n".join(parts)


def run_job(job: dict) -> tuple[bool, str, str, Optional[str]]:
    """
    Execute a single cron job.
    
    Returns:
        Tuple of (success, full_output_doc, final_response, error_message)
    """
    from run_agent import AIAgent
    
    # Initialize SQLite session store so cron job messages are persisted
    # and discoverable via session_search (same pattern as gateway/run.py).
    _session_db = None
    try:
        from ector_state import SessionDB
        _session_db = SessionDB()
    except Exception as e:
        logger.debug("Job '%s': SQLite session store not available: %s", job.get("id", "?"), e)
    
    job_id = job["id"]
    job_name = job["name"]

    # Wake-gate: if this job has a pre-check script, run it BEFORE building
    # the prompt so a ``{"wakeAgent": false}`` response can short-circuit
    # the whole agent run. We pass the result into _build_job_prompt so
    # the script is only executed once.
    prerun_script = None
    script_path = job.get("script")
    if script_path:
        prerun_script = _run_job_script(script_path)
        _ran_ok, _script_output = prerun_script
        if _ran_ok and not _parse_wake_gate(_script_output):
            logger.info(
                "Job '%s' (ID: %s): wakeAgent=false, skipping agent run",
                job_name, job_id,
            )
            silent_doc = (
                f"# Cron Job: {job_name}\n\n"
                f"**Job ID:** {job_id}\n"
                f"**Run Time:** {_ector_now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                "Script gate returned `wakeAgent=false` — agent skipped.\n"
            )
            return True, silent_doc, SILENT_MARKER, None

    prompt = _build_job_prompt(job, prerun_script=prerun_script)
    origin = _resolve_origin(job)
    _cron_session_id = f"cron_{job_id}_{_ector_now().strftime('%Y%m%d_%H%M%S')}"

    logger.info("Running job '%s' (ID: %s)", job_name, job_id)
    logger.info("Prompt: %s", prompt[:100])

    # Mark this as a cron session so the approval system can apply cron_mode.
    # This env var is process-wide and persists for the lifetime of the
    # scheduler process — every job this process runs is a cron job.
    os.environ["ECTOR_CRON_SESSION"] = "1"

    # Use ContextVars for per-job session/delivery state so parallel jobs
    # don't clobber each other's targets (os.environ is process-global).
    from gateway.session_context import set_session_vars, clear_session_vars, _VAR_MAP

    _ctx_tokens = set_session_vars(
        platform=origin["platform"] if origin else "",
        chat_id=str(origin["chat_id"]) if origin else "",
        chat_name=origin.get("chat_name", "") if origin else "",
    )

    # Per-job working directory.  When set (and validated at create/update
    # time), we point TERMINAL_CWD at it so:
    #   - build_context_files_prompt() picks up AGENTS.md / CLAUDE.md /
    #     .cursorrules from the job's project dir, AND
    #   - the terminal, file, and code-exec tools run commands from there.
    #
    # tick() serializes workdir-jobs outside the parallel pool, so mutating
    # os.environ["TERMINAL_CWD"] here is safe for those jobs.  For workdir-less
    # jobs we leave TERMINAL_CWD untouched — preserves the original behaviour
    # (skip_context_files=True, tools use whatever cwd the scheduler has).
    _job_workdir = (job.get("workdir") or "").strip() or None
    if _job_workdir and not Path(_job_workdir).is_dir():
        # Directory was removed between create-time validation and now.  Log
        # and drop back to old behaviour rather than crashing the job.
        logger.warning(
            "Job '%s': configured workdir %r no longer exists — running without it",
            job_id, _job_workdir,
        )
        _job_workdir = None
    _prior_terminal_cwd = os.environ.get("TERMINAL_CWD", "_UNSET_")
    if _job_workdir:
        os.environ["TERMINAL_CWD"] = _job_workdir
        logger.info("Job '%s': using workdir %s", job_id, _job_workdir)

    try:
        # Re-read .env and config.yaml fresh every run so provider/key
        # changes take effect without a gateway restart.
        from dotenv import load_dotenv
        try:
            load_dotenv(str(_ector_home / ".env"), override=True, encoding="utf-8")
        except UnicodeDecodeError:
            load_dotenv(str(_ector_home / ".env"), override=True, encoding="latin-1")

        delivery_target = _resolve_delivery_target(job)
        if delivery_target:
            _VAR_MAP["ECTOR_CRON_AUTO_DELIVER_PLATFORM"].set(delivery_target["platform"])
            _VAR_MAP["ECTOR_CRON_AUTO_DELIVER_CHAT_ID"].set(str(delivery_target["chat_id"]))
            if delivery_target.get("thread_id") is not None:
                _VAR_MAP["ECTOR_CRON_AUTO_DELIVER_THREAD_ID"].set(str(delivery_target["thread_id"]))

        model = job.get("model") or os.getenv("ECTOR_MODEL") or ""

        # Load config.yaml for model, reasoning, prefill, toolsets, provider routing
        _cfg = {}
        try:
            import yaml
            _cfg_path = str(_ector_home / "config.yaml")
            if os.path.exists(_cfg_path):
                with open(_cfg_path) as _f:
                    _cfg = yaml.safe_load(_f) or {}
                _model_cfg = _cfg.get("model", {})
                if not job.get("model"):
                    if isinstance(_model_cfg, str):
                        model = _model_cfg
                    elif isinstance(_model_cfg, dict):
                        model = _model_cfg.get("default", model)
        except Exception as e:
            logger.warning("Job '%s': failed to load config.yaml, using defaults: %s", job_id, e)

        # Apply IPv4 preference if configured.
        try:
            from ector_constants import apply_ipv4_preference
            _net_cfg = _cfg.get("network", {})
            if isinstance(_net_cfg, dict) and _net_cfg.get("force_ipv4"):
                apply_ipv4_preference(force=True)
        except Exception:
            pass

        # Reasoning config from config.yaml
        from ector_constants import parse_reasoning_effort
        effort = str(_cfg.get("agent", {}).get("reasoning_effort", "")).strip()
        reasoning_config = parse_reasoning_effort(effort)

        # Prefill messages from env or config.yaml
        prefill_messages = None
        prefill_file = os.getenv("ECTOR_PREFILL_MESSAGES_FILE", "") or _cfg.get("prefill_messages_file", "")
        if prefill_file:
            pfpath = Path(prefill_file).expanduser()
            if not pfpath.is_absolute():
                pfpath = _ector_home / pfpath
            if pfpath.exists():
                try:
                    with open(pfpath, "r", encoding="utf-8") as _pf:
                        prefill_messages = json.load(_pf)
                    if not isinstance(prefill_messages, list):
                        prefill_messages = None
                except Exception as e:
                    logger.warning("Job '%s': failed to parse prefill messages file '%s': %s", job_id, pfpath, e)
                    prefill_messages = None

        # Max iterations
        max_iterations = _cfg.get("agent", {}).get("max_turns") or _cfg.get("max_turns") or 90

        # Provider routing
        pr = _cfg.get("provider_routing", {})

        from ector_cli.runtime_provider import (
            resolve_runtime_provider,
            format_runtime_provider_error,
        )
        from ector_cli.auth import AuthError
        try:
            runtime_kwargs = {
                "requested": job.get("provider") or os.getenv("ECTOR_INFERENCE_PROVIDER"),
            }
            if job.get("base_url"):
                runtime_kwargs["explicit_base_url"] = job.get("base_url")
            runtime = resolve_runtime_provider(**runtime_kwargs)
        except AuthError as auth_exc:
            # Primary provider auth failed — try fallback chain before giving up.
            logger.warning("Job '%s': primary auth failed (%s), trying fallback", job_id, auth_exc)
            fb = _cfg.get("fallback_providers") or _cfg.get("fallback_model")
            fb_list = (fb if isinstance(fb, list) else [fb]) if fb else []
            runtime = None
            for entry in fb_list:
                if not isinstance(entry, dict):
                    continue
                try:
                    fb_kwargs = {"requested": entry.get("provider")}
                    if entry.get("base_url"):
                        fb_kwargs["explicit_base_url"] = entry["base_url"]
                    if entry.get("api_key"):
                        fb_kwargs["explicit_api_key"] = entry["api_key"]
                    runtime = resolve_runtime_provider(**fb_kwargs)
                    logger.info("Job '%s': fallback resolved to %s", job_id, runtime.get("provider"))
                    break
                except Exception as fb_exc:
                    logger.debug("Job '%s': fallback %s failed: %s", job_id, entry.get("provider"), fb_exc)
            if runtime is None:
                raise RuntimeError(format_runtime_provider_error(auth_exc)) from auth_exc
        except Exception as exc:
            message = format_runtime_provider_error(exc)
            raise RuntimeError(message) from exc

        fallback_model = _cfg.get("fallback_providers") or _cfg.get("fallback_model") or None
        credential_pool = None
        runtime_provider = str(runtime.get("provider") or "").strip().lower()
        if runtime_provider:
            try:
                from agent.credential_pool import load_pool
                pool = load_pool(runtime_provider)
                if pool.has_credentials():
                    credential_pool = pool
                    logger.info(
                        "Job '%s': loaded credential pool for provider %s with %d entries",
                        job_id,
                        runtime_provider,
                        len(pool.entries()),
                    )
            except Exception as e:
                logger.debug("Job '%s': failed to load credential pool for %s: %s", job_id, runtime_provider, e)

        agent = AIAgent(
            model=model,
            api_key=runtime.get("api_key"),
            base_url=runtime.get("base_url"),
            provider=runtime.get("provider"),
            api_mode=runtime.get("api_mode"),
            acp_command=runtime.get("command"),
            acp_args=runtime.get("args"),
            max_iterations=max_iterations,
            reasoning_config=reasoning_config,
            prefill_messages=prefill_messages,
            fallback_model=fallback_model,
            credential_pool=credential_pool,
            providers_allowed=pr.get("only"),
            providers_ignored=pr.get("ignore"),
            providers_order=pr.get("order"),
            provider_sort=pr.get("sort"),
            enabled_toolsets=_resolve_cron_enabled_toolsets(job, _cfg),
            disabled_toolsets=["cronjob", "messaging", "wiser"],
            quiet_mode=True,
            # When a workdir is configured, inject AGENTS.md / CLAUDE.md /
            # .cursorrules from that directory; otherwise preserve the old
            # behaviour (don't inject SOUL.md/AGENTS.md from the scheduler cwd).
            skip_context_files=not bool(_job_workdir),
            skip_memory=True,  # Cron system prompts would corrupt user representations
            platform="cron",
            session_id=_cron_session_id,
            session_db=_session_db,
        )
        
        # Run the agent with an *inactivity*-based timeout: the job can run
        # for hours if it's actively calling tools / receiving stream tokens,
        # but a hung API call or stuck tool with no activity for the configured
        # duration is caught and killed.  Default 600s (10 min inactivity);
        # override via ECTOR_CRON_TIMEOUT env var.  0 = unlimited.
        #
        # Uses the agent's built-in activity tracker (updated by
        # _touch_activity() on every tool call, API call, and stream delta).
        _cron_timeout = float(os.getenv("ECTOR_CRON_TIMEOUT", 600))
        _cron_inactivity_limit = _cron_timeout if _cron_timeout > 0 else None
        _POLL_INTERVAL = 5.0
        _cron_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        # Preserve scheduler-scoped ContextVar state (for example skill-declared
        # env passthrough registrations) when the cron run hops into the worker
        # thread used for inactivity timeout monitoring.
        _cron_context = contextvars.copy_context()
        _cron_future = _cron_pool.submit(_cron_context.run, agent.run_conversation, prompt)
        _inactivity_timeout = False
        try:
            if _cron_inactivity_limit is None:
                # Unlimited — just wait for the result.
                result = _cron_future.result()
            else:
                result = None
                while True:
                    done, _ = concurrent.futures.wait(
                        {_cron_future}, timeout=_POLL_INTERVAL,
                    )
                    if done:
                        result = _cron_future.result()
                        break
                    # Agent still running — check inactivity.
                    _idle_secs = 0.0
                    if hasattr(agent, "get_activity_summary"):
                        try:
                            _act = agent.get_activity_summary()
                            _idle_secs = _act.get("seconds_since_activity", 0.0)
                        except Exception:
                            pass
                    if _idle_secs >= _cron_inactivity_limit:
                        _inactivity_timeout = True
                        break
        except Exception:
            _cron_pool.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            _cron_pool.shutdown(wait=False, cancel_futures=True)

        if _inactivity_timeout:
            # Build diagnostic summary from the agent's activity tracker.
            _activity = {}
            if hasattr(agent, "get_activity_summary"):
                try:
                    _activity = agent.get_activity_summary()
                except Exception:
                    pass
            _last_desc = _activity.get("last_activity_desc", "unknown")
            _secs_ago = _activity.get("seconds_since_activity", 0)
            _cur_tool = _activity.get("current_tool")
            _iter_n = _activity.get("api_call_count", 0)
            _iter_max = _activity.get("max_iterations", 0)

            logger.error(
                "Job '%s' idle for %.0fs (inactivity limit %.0fs) "
                "| last_activity=%s | iteration=%s/%s | tool=%s",
                job_name, _secs_ago, _cron_inactivity_limit,
                _last_desc, _iter_n, _iter_max,
                _cur_tool or "none",
            )
            if hasattr(agent, "interrupt"):
                agent.interrupt("Cron job timed out (inactivity)")
            raise TimeoutError(
                f"Cron job '{job_name}' idle for "
                f"{int(_secs_ago)}s (limit {int(_cron_inactivity_limit)}s) "
                f"— last activity: {_last_desc}"
            )

        # Guard against non-dict returns from run_conversation under error conditions
        if not isinstance(result, dict):
            raise RuntimeError(
                f"agent.run_conversation returned {type(result).__name__} instead of dict: {result!r}"
            )

        final_response = result.get("final_response", "") or ""
        # Strip leaked placeholder text that upstream may inject on empty completions.
        if final_response.strip() == "(No response generated)":
            final_response = ""
        # Use a separate variable for log display; keep final_response clean
        # for delivery logic (empty response = no delivery).
        logged_response = final_response if final_response else "(No response generated)"
        
        output = f"""# Cron Job: {job_name}

**Job ID:** {job_id}
**Run Time:** {_ector_now().strftime('%Y-%m-%d %H:%M:%S')}
**Schedule:** {job.get('schedule_display', 'N/A')}

## Prompt

{prompt}

## Response

{logged_response}
"""
        
        logger.info("Job '%s' completed successfully", job_name)
        return True, output, final_response, None
        
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.exception("Job '%s' failed: %s", job_name, error_msg)
        
        output = f"""# Cron Job: {job_name} (FAILED)

**Job ID:** {job_id}
**Run Time:** {_ector_now().strftime('%Y-%m-%d %H:%M:%S')}
**Schedule:** {job.get('schedule_display', 'N/A')}

## Prompt

{prompt}

## Error

```
{error_msg}
```
"""
        return False, output, "", error_msg

    finally:
        # Restore TERMINAL_CWD to whatever it was before this job ran.  We
        # only ever mutate it when the job has a workdir; see the setup block
        # at the top of run_job for the serialization guarantee.
        if _job_workdir:
            if _prior_terminal_cwd == "_UNSET_":
                os.environ.pop("TERMINAL_CWD", None)
            else:
                os.environ["TERMINAL_CWD"] = _prior_terminal_cwd
        # Clean up ContextVar session/delivery state for this job.
        clear_session_vars(_ctx_tokens)
        if _session_db:
            try:
                _session_db.end_session(_cron_session_id, "cron_complete")
            except (Exception, KeyboardInterrupt) as e:
                logger.debug("Job '%s': failed to end session: %s", job_id, e)
            try:
                _session_db.close()
            except (Exception, KeyboardInterrupt) as e:
                logger.debug("Job '%s': failed to close SQLite session store: %s", job_id, e)


def _tick_legacy(verbose: bool = True, adapters=None, loop=None) -> int:
    """
    Check and run all due jobs using the legacy scheduler path.
    
    Uses a file lock so only one tick runs at a time, even if the gateway's
    in-process ticker and a standalone daemon or manual tick overlap.
    
    Args:
        verbose: Whether to print status messages
        adapters: Optional dict mapping Platform → live adapter (from gateway)
        loop: Optional asyncio event loop (from gateway) for live adapter sends
    
    Returns:
        Number of jobs executed (0 if another tick is already running)
    """
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)

    # Cross-platform file locking: fcntl on Unix, msvcrt on Windows
    lock_fd = None
    try:
        lock_fd = open(_LOCK_FILE, "w")
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt:
            msvcrt.locking(lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
    except (OSError, IOError):
        logger.debug("Tick skipped — another instance holds the lock")
        if lock_fd is not None:
            lock_fd.close()
        return 0

    try:
        due_jobs = get_due_jobs()

        if verbose and not due_jobs:
            logger.info("%s - No jobs due", _ector_now().strftime('%H:%M:%S'))
            return 0

        if verbose:
            logger.info("%s - %s job(s) due", _ector_now().strftime('%H:%M:%S'), len(due_jobs))

        # Advance next_run_at for all recurring jobs FIRST, under the file lock,
        # before any execution begins.  This preserves at-most-once semantics.
        for job in due_jobs:
            advance_next_run(job["id"])
        return _process_due_jobs(
            due_jobs,
            verbose=verbose,
            adapters=adapters,
            loop=loop,
            scheduler_label="legacy",
        )
    finally:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        elif msvcrt:
            try:
                msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
            except (OSError, IOError):
                pass
        lock_fd.close()


def _tick_apscheduler(verbose: bool = True, adapters=None, loop=None) -> int:
    """Check and run due jobs using APScheduler-based due projections."""
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)

    lock_fd = None
    try:
        lock_fd = open(_LOCK_FILE, "w")
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt:
            msvcrt.locking(lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
    except (OSError, IOError):
        logger.debug("Tick skipped — another instance holds the lock")
        if lock_fd is not None:
            lock_fd.close()
        return 0

    try:
        due_jobs = _get_due_jobs_apscheduler()
        if verbose and not due_jobs:
            logger.info("%s - No jobs due", _ector_now().strftime('%H:%M:%S'))
            return 0

        if verbose:
            logger.info("%s - %s job(s) due", _ector_now().strftime('%H:%M:%S'), len(due_jobs))

        for job in due_jobs:
            advance_next_run(job["id"])

        return _process_due_jobs(
            due_jobs,
            verbose=verbose,
            adapters=adapters,
            loop=loop,
            scheduler_label="apscheduler",
        )
    finally:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        elif msvcrt:
            try:
                msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
            except (OSError, IOError):
                pass
        lock_fd.close()


def tick(verbose: bool = True, adapters=None, loop=None) -> int:
    """Cron scheduler entrypoint with migration-friendly engine selection.

    Modes:
    - legacy: execute current scheduler semantics.
    - apscheduler: execute current semantics and emit APS projection drift logs.
    - shadow: execute legacy path and log parity telemetry only (no extra side effects).
    """
    mode = _resolve_cron_engine_mode()
    if mode == _ENGINE_MODE_LEGACY:
        return _tick_legacy(verbose=verbose, adapters=adapters, loop=loop)

    if mode == _ENGINE_MODE_APSCHEDULER:
        jobs_executed = _tick_apscheduler(verbose=verbose, adapters=adapters, loop=loop)
        drifts = _collect_apscheduler_projection_drift()
        if drifts:
            event = {
                "ts": _ector_now().isoformat(),
                "mode": mode,
                "jobs_executed": jobs_executed,
                "drift_count": len(drifts),
                "max_drift_seconds": max(item["drift_seconds"] for item in drifts),
                "drifts": drifts,
            }
            _write_scheduler_parity_event(event)
        return jobs_executed

    if mode == _ENGINE_MODE_SHADOW:
        legacy_due_ids = {j.get("id") for j in _get_due_jobs_legacy_preview()}
        aps_due_ids = {j.get("id") for j in _get_due_jobs_apscheduler()}
        jobs_executed = _tick_legacy(verbose=verbose, adapters=adapters, loop=loop)
        drifts = _collect_apscheduler_projection_drift()
        event = {
            "ts": _ector_now().isoformat(),
            "mode": mode,
            "jobs_executed": jobs_executed,
            "legacy_due_count": len(legacy_due_ids),
            "aps_due_count": len(aps_due_ids),
            "legacy_only_due_ids": sorted(legacy_due_ids - aps_due_ids),
            "aps_only_due_ids": sorted(aps_due_ids - legacy_due_ids),
            "drift_count": len(drifts),
            "max_drift_seconds": max((item["drift_seconds"] for item in drifts), default=0),
            "drifts": drifts,
        }
        _write_scheduler_parity_event(event)
        return jobs_executed

    logger.warning("Unknown cron engine mode '%s'; falling back to legacy", mode)
    return _tick_legacy(verbose=verbose, adapters=adapters, loop=loop)


if __name__ == "__main__":
    from ector_cli.identity_auth import enforce_agent_runtime_access

    enforce_agent_runtime_access(interactive=False)
    tick(verbose=True)
