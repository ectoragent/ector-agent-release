"""Resolve dashboard-servable media paths under ECTOR_HOME and session cwd."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from ector_constants import get_ector_home

ImageBucket = Literal["images", "cache"]

_CHAT_IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".svg", ".ico"}
)

ARTIFACT_SUFFIXES = frozenset({".html", ".htm", ".svg"})

PREVIEW_FILE_SUFFIXES = _CHAT_IMAGE_SUFFIXES | ARTIFACT_SUFFIXES

_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

_ARTIFACT_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
}


def chat_images_dir() -> Path:
    path = get_ector_home() / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def chat_cache_images_dir() -> Path:
    path = get_ector_home() / "cache" / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _safe_basename(filename: str) -> str:
    raw = str(filename or "").strip()
    safe = Path(raw).name
    if not safe or safe in {".", ".."} or "/" in safe or "\\" in safe:
        raise ValueError("invalid filename")
    return safe


def classify_image_path(image_path: str) -> tuple[ImageBucket, str] | None:
    """Map an absolute path to (bucket, basename) when under allowed image dirs."""
    if not image_path:
        return None
    try:
        resolved = Path(str(image_path).strip()).expanduser().resolve(strict=True)
    except (OSError, ValueError):
        return None
    if not resolved.is_file():
        return None
    if resolved.suffix.lower() not in _CHAT_IMAGE_SUFFIXES:
        return None

    images_dir = chat_images_dir()
    cache_dir = chat_cache_images_dir()
    try:
        resolved.relative_to(images_dir)
        return "images", resolved.name
    except ValueError:
        pass
    try:
        resolved.relative_to(cache_dir)
        return "cache", resolved.name
    except ValueError:
        pass
    return None


def resolve_chat_image_file(filename: str, bucket: ImageBucket = "images") -> Path:
    """Resolve a basename within the images or cache/images directory."""
    raw = str(filename or "").strip()
    if not raw or ".." in raw or "/" in raw or "\\" in raw:
        raise ValueError("invalid filename")
    safe = _safe_basename(raw)
    base = chat_cache_images_dir() if bucket == "cache" else chat_images_dir()
    try:
        resolved = (base / safe).resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(safe) from exc
    if not resolved.is_file():
        raise FileNotFoundError(safe)
    resolved.relative_to(base)
    if resolved.suffix.lower() not in _CHAT_IMAGE_SUFFIXES:
        raise ValueError("unsupported image format")
    return resolved


def chat_image_api_url(image_path: str) -> str:
    """Relative dashboard URL for a persisted image path or basename."""
    classified = classify_image_path(image_path)
    if classified:
        bucket, name = classified
        return chat_image_api_url_for_name(name, bucket=bucket)
    try:
        name = _safe_basename(image_path)
    except ValueError:
        return ""
    if name.lower().endswith(tuple(_CHAT_IMAGE_SUFFIXES)):
        return chat_image_api_url_for_name(name, bucket="images")
    return ""


def chat_image_api_url_for_name(
    filename: str,
    *,
    bucket: ImageBucket = "images",
) -> str:
    name = _safe_basename(filename)
    if bucket == "cache":
        return f"/api/chat/images/cache/{quote(name, safe='')}"
    return f"/api/chat/images/{quote(name, safe='')}"


def image_media_type(path: Path) -> str:
    return _IMAGE_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def artifact_media_type(path: Path) -> str:
    return _ARTIFACT_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _is_image_suffix(suffix: str) -> bool:
    return suffix.lower() in _CHAT_IMAGE_SUFFIXES


def is_local_image_reference(url: str) -> bool:
    """True when *url* looks like a local filesystem image path."""
    raw = str(url or "").strip()
    if not raw or raw.startswith(("http://", "https://", "data:", "blob:", "/api/")):
        return False
    if raw.startswith("file://"):
        raw = raw[7:]
    path = Path(os.path.expanduser(raw))
    return _is_image_suffix(path.suffix)


def chat_file_preview_url(file_path: str, session_id: str) -> str:
    """Relative dashboard URL to stream a session-scoped file by path."""
    sid = str(session_id or "").strip()
    path = str(file_path or "").strip()
    if not sid or not path:
        return ""
    return (
        "/api/chat/files/preview?"
        f"path={quote(path, safe='')}&session_id={quote(sid, safe='')}"
    )


def _allowed_roots(session_cwd: str) -> list[Path]:
    roots: list[Path] = [get_ector_home().resolve()]
    try:
        roots.append(Path.home().resolve())
    except OSError:
        pass
    cwd = str(session_cwd or "").strip()
    if cwd:
        try:
            roots.append(Path(cwd).expanduser().resolve())
        except OSError:
            pass
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def resolve_readable_file(
    raw_path: str,
    *,
    session_cwd: str,
    allowed_suffixes: frozenset[str],
) -> Path:
    """Resolve a user/agent path that must live under session cwd or ECTOR_HOME."""
    text = str(raw_path or "").strip()
    if not text:
        raise ValueError("empty path")
    if text.startswith("file://"):
        text = text[7:]
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = Path(session_cwd).expanduser() / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise FileNotFoundError(text) from exc
    if not resolved.is_file():
        raise FileNotFoundError(text)
    if resolved.suffix.lower() not in allowed_suffixes:
        raise ValueError("unsupported file type")

    for root in _allowed_roots(session_cwd):
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise PermissionError("path outside allowed directories")


def rewrite_markdown_image_paths(
    markdown: str,
    *,
    session_id: str | None = None,
) -> str:
    """Rewrite local image paths in markdown link targets to dashboard API URLs."""

    if not markdown:
        return markdown

    sid = str(session_id or "").strip()

    def rewrite_url(url: str) -> str:
        raw = url.strip()
        if not raw:
            return url
        if raw.startswith("/api/chat/"):
            return raw
        if raw.startswith(("http://", "https://", "data:", "blob:")):
            return url
        if raw.startswith("file://"):
            raw = raw[7:]
        expanded = os.path.expanduser(raw)
        classified = classify_image_path(expanded)
        if classified:
            bucket, name = classified
            return chat_image_api_url_for_name(name, bucket=bucket)
        if sid and is_local_image_reference(expanded):
            preview = chat_file_preview_url(expanded, sid)
            if preview:
                return preview
        return url

    def paren_repl(match: re.Match[str]) -> str:
        return f"]({rewrite_url(match.group(1))})"

    return re.sub(r"\]\(([^)]+)\)", paren_repl, markdown)
