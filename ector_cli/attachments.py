"""Local file/image attachment helpers (shared by web chat and cli legacy)."""

from __future__ import annotations

import base64
import binascii
import json
import os
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from ector_constants import get_ector_home, is_termux, safe_getcwd

IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".bmp", ".tiff", ".tif", ".svg", ".ico",
})

WEB_IMAGE_MAX_BYTES = 20 * 1024 * 1024

_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "image/svg+xml": ".svg",
}


class WebChatImageError(ValueError):
    """Invalid or unsupported web chat image payload."""


class WebChatAudioError(ValueError):
    """Invalid or unsupported web chat audio payload."""


class WebChatDocumentError(ValueError):
    """Invalid or unsupported web chat document payload."""


WEB_AUDIO_MAX_BYTES = 25 * 1024 * 1024
WEB_DOCUMENT_MAX_BYTES = 50 * 1024 * 1024

_AUDIO_MIME_TO_EXT = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/aac": ".aac",
}

_AUDIO_EXTENSIONS = frozenset({
    ".webm", ".ogg", ".mp3", ".mpeg", ".mpga", ".m4a", ".wav", ".flac", ".aac",
})

DOCUMENT_EXTENSIONS = frozenset({
    ".pdf", ".md", ".txt", ".csv", ".json", ".xml", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".docx", ".xlsx", ".pptx", ".html", ".htm", ".epub",
})

_DOCUMENT_MIME_TO_EXT = {
    "application/pdf": ".pdf",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/xml": ".xml",
    "application/yaml": ".yaml",
    "application/toml": ".toml",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/html": ".html",
    "application/epub+zip": ".epub",
}


def _looks_like_image(data: bytes) -> bool:
  from gateway.platforms.base import _looks_like_image as _gateway_looks_like_image

  return _gateway_looks_like_image(data)


def _normalize_image_ext(ext: str) -> str:
    normalized = str(ext or "").strip().lower()
    if not normalized:
        return ""
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    return normalized if normalized in IMAGE_EXTENSIONS else ""


def _ext_from_filename(filename: str) -> str:
    return _normalize_image_ext(Path(str(filename or "")).suffix)


def _ext_from_mime(mime: str) -> str:
    return _normalize_image_ext(_MIME_TO_EXT.get(str(mime or "").strip().lower(), ""))


def decode_chat_image_payload(item: dict[str, Any]) -> tuple[bytes, str]:
    """Decode a dashboard chat image payload to raw bytes and file extension."""
    if not isinstance(item, dict):
        raise WebChatImageError("each image entry must be an object")

    raw_b64 = str(item.get("content_base64") or item.get("data") or "").strip()
    if not raw_b64:
        raise WebChatImageError("content_base64 is required for each image")

    if raw_b64.startswith("data:"):
        _header, _sep, raw_b64 = raw_b64.partition(",")

    try:
        data = base64.b64decode(raw_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WebChatImageError("invalid base64 image data") from exc

    if not data:
        raise WebChatImageError("empty image payload")
    if len(data) > WEB_IMAGE_MAX_BYTES:
        raise WebChatImageError(
            f"image exceeds {WEB_IMAGE_MAX_BYTES // (1024 * 1024)}MB limit"
        )

    ext = _ext_from_filename(str(item.get("filename") or ""))
    if not ext:
        ext = _ext_from_mime(str(item.get("mime") or ""))
    if not ext:
        ext = ".png"
    return data, ext


def save_image_attachment_bytes(
    data: bytes,
    *,
    ext: str,
    prefix: str = "web",
) -> Path:
    """Persist uploaded image bytes under ``{ECTOR_HOME}/images/``."""
    normalized_ext = _normalize_image_ext(ext) or ".png"
    if not _looks_like_image(data):
        raise WebChatImageError(f"refusing to save non-image payload as {normalized_ext}")
    if len(data) > WEB_IMAGE_MAX_BYTES:
        raise WebChatImageError(
            f"image exceeds {WEB_IMAGE_MAX_BYTES // (1024 * 1024)}MB limit"
        )

    img_dir = get_ector_home() / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{prefix}_{uuid.uuid4().hex[:12]}{normalized_ext}"
    path = img_dir / filename
    path.write_bytes(data)
    return path


def save_chat_image_payload(item: dict[str, Any]) -> Path:
    """Decode and persist one dashboard chat image payload."""
    data, ext = decode_chat_image_payload(item)
    return save_image_attachment_bytes(data, ext=ext, prefix="web")


def _normalize_audio_ext(ext: str) -> str:
    normalized = str(ext or "").strip().lower()
    if not normalized:
        return ""
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    return normalized if normalized in _AUDIO_EXTENSIONS else ""


def _ext_from_audio_filename(filename: str) -> str:
    return _normalize_audio_ext(Path(str(filename or "")).suffix)


def _ext_from_audio_mime(mime: str) -> str:
    base = str(mime or "").strip().lower().split(";", 1)[0]
    return _normalize_audio_ext(_AUDIO_MIME_TO_EXT.get(base, ""))


def _normalize_document_ext(ext: str) -> str:
    normalized = str(ext or "").strip().lower()
    if not normalized:
        return ""
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    return normalized if normalized in DOCUMENT_EXTENSIONS else ""


def decode_chat_document_payload(item: dict[str, Any]) -> tuple[bytes, str]:
    """Decode a dashboard chat document payload to raw bytes and extension."""
    if not isinstance(item, dict):
        raise WebChatDocumentError("each document entry must be an object")
    raw_b64 = str(item.get("content_base64") or item.get("data") or "").strip()
    if not raw_b64:
        raise WebChatDocumentError("content_base64 is required for each document")

    if raw_b64.startswith("data:"):
        _header, _sep, raw_b64 = raw_b64.partition(",")

    try:
        data = base64.b64decode(raw_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WebChatDocumentError("invalid base64 document data") from exc

    if not data:
        raise WebChatDocumentError("empty document payload")
    if len(data) > WEB_DOCUMENT_MAX_BYTES:
        raise WebChatDocumentError(
            f"document exceeds {WEB_DOCUMENT_MAX_BYTES // (1024 * 1024)}MB limit"
        )

    ext = _normalize_document_ext(Path(str(item.get("filename") or "")).suffix)
    if not ext:
        mime = str(item.get("mime") or "").strip().lower().split(";", 1)[0]
        ext = _normalize_document_ext(_DOCUMENT_MIME_TO_EXT.get(mime, ""))
    if not ext:
        ext = ".pdf"
    return data, ext


def save_chat_document_payload(item: dict[str, Any]) -> Path:
    """Decode and persist one dashboard chat document payload."""
    data, ext = decode_chat_document_payload(item)
    doc_dir = get_ector_home() / "cache" / "documents"
    doc_dir.mkdir(parents=True, exist_ok=True)
    filename = f"web_{uuid.uuid4().hex[:12]}{ext}"
    path = doc_dir / filename
    path.write_bytes(data)
    return path


def decode_chat_audio_payload(body: dict[str, Any]) -> tuple[bytes, str]:
    """Decode a dashboard chat audio payload to raw bytes and file extension."""
    if not isinstance(body, dict):
        raise WebChatAudioError("payload must be an object")

    raw_b64 = str(body.get("audio_base64") or body.get("content_base64") or "").strip()
    if not raw_b64:
        raise WebChatAudioError("audio_base64 is required")

    if raw_b64.startswith("data:"):
        _header, _sep, raw_b64 = raw_b64.partition(",")

    try:
        data = base64.b64decode(raw_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WebChatAudioError("invalid base64 audio data") from exc

    if not data:
        raise WebChatAudioError("empty audio payload")
    if len(data) > WEB_AUDIO_MAX_BYTES:
        raise WebChatAudioError(
            f"audio exceeds {WEB_AUDIO_MAX_BYTES // (1024 * 1024)}MB limit"
        )

    ext = _ext_from_audio_filename(str(body.get("filename") or ""))
    if not ext:
        ext = _ext_from_audio_mime(str(body.get("mime") or ""))
    if not ext:
        ext = ".webm"
    return data, ext


def validate_web_chat_send_payload(
    message: str,
    images: Any,
    documents: Any = None,
) -> str | None:
    """Return an error message when neither text nor media were provided."""
    has_message = bool(str(message or "").strip())
    if images is None:
        images = []
    if documents is None:
        documents = []
    if not isinstance(images, list):
        return "images must be an array"
    if not isinstance(documents, list):
        return "documents must be an array"
    if not has_message and not images and not documents:
        return "message, images or documents is required"
    if len(images) > 8:
        return "at most 8 images per message"
    if len(documents) > 4:
        return "at most 4 documents per message"
    return None


def enrich_with_attached_documents(user_text: str, document_paths: list[str]) -> str:
    """Extract text from attached documents and prepend internal context blocks."""
    from agent.rag_context import build_document_rag_block
    from agent.document_stack.extract import extract_document
    from agent.document_stack.markers import (
        format_document_context_block,
        format_document_context_failed,
    )

    if not document_paths:
        return user_text
    parts: list[str] = []
    for path in document_paths:
        p = Path(path)
        if not p.exists():
            continue
        result = extract_document(str(p), output="markdown")
        if result.get("success"):
            parts.append(
                format_document_context_block(
                    result.get("markdown", ""),
                    str(p),
                    result.get("backend", "document_extract"),
                )
            )
            rag_block = build_document_rag_block(result.get("chunks"))
            if rag_block:
                parts.append(rag_block)
        else:
            parts.append(format_document_context_failed(str(p)))
    if not parts:
        return user_text
    prefix = "\n\n".join(parts)
    return f"{prefix}\n\n{user_text}" if user_text else prefix


def prepare_web_chat_message(
    message: str,
    image_paths: list[str],
    document_paths: list[str] | None = None,
) -> str:
    """Enrich a web chat user message with image and document analysis."""
    document_paths = document_paths or []
    enriched = message
    if image_paths:
        enriched = enrich_with_attached_images(enriched, image_paths)
    if document_paths:
        enriched = enrich_with_attached_documents(enriched, document_paths)
    return enriched


def termux_example_image_path(filename: str = "cat.png") -> str:
    """Return a realistic example media path for the current Termux setup."""
    candidates = [
        os.path.expanduser("~/storage/shared"),
        "/sdcard",
        "/storage/emulated/0",
        "/storage/self/primary",
    ]
    for root in candidates:
        if os.path.isdir(root):
            return os.path.join(root, "Pictures", filename)
    return os.path.join("~/storage/shared", "Pictures", filename)


def split_path_input(raw: str) -> tuple[str, str]:
    r"""Split a leading file path token from trailing free-form text."""
    raw = str(raw or "").strip()
    if not raw:
        return "", ""

    if raw[0] in {'"', "'"}:
        quote = raw[0]
        pos = 1
        while pos < len(raw):
            ch = raw[pos]
            if ch == "\\" and pos + 1 < len(raw):
                pos += 2
                continue
            if ch == quote:
                token = raw[1:pos]
                remainder = raw[pos + 1 :].strip()
                return token, remainder
            pos += 1
        return raw[1:], ""

    pos = 0
    while pos < len(raw):
        ch = raw[pos]
        if ch == "\\" and pos + 1 < len(raw) and raw[pos + 1] == " ":
            pos += 2
        elif ch == " ":
            break
        else:
            pos += 1

    token = raw[:pos].replace("\\ ", " ")
    remainder = raw[pos:].strip()
    return token, remainder


def resolve_attachment_path(raw_path: str) -> Path | None:
    """Resolve a user-supplied local attachment path to an existing file."""
    token = str(raw_path or "").strip()
    if not token:
        return None

    if (token.startswith('"') and token.endswith('"')) or (
        token.startswith("'") and token.endswith("'")
    ):
        token = token[1:-1].strip()
    token = token.replace("\\ ", " ")
    if not token:
        return None

    expanded = token
    if token.startswith("file://"):
        try:
            parsed = urlparse(token)
            if parsed.scheme == "file":
                expanded = unquote(parsed.path or "")
                if parsed.netloc and os.name == "nt":
                    expanded = f"//{parsed.netloc}{expanded}"
        except Exception:
            expanded = token
    expanded = os.path.expandvars(os.path.expanduser(expanded))
    if os.name != "nt":
        normalized = expanded.replace("\\", "/")
        if (
            len(normalized) >= 3
            and normalized[1] == ":"
            and normalized[2] == "/"
            and normalized[0].isalpha()
        ):
            expanded = f"/mnt/{normalized[0].lower()}/{normalized[3:]}"
    path = Path(expanded)
    if not path.is_absolute():
        base_dir = Path(os.getenv("TERMINAL_CWD", safe_getcwd()))
        path = base_dir / path

    try:
        resolved = path.resolve()
    except Exception:
        resolved = path

    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def detect_file_drop(user_input: str) -> dict | None:
    """Detect if user_input starts with a real local file path."""
    if not isinstance(user_input, str):
        return None

    stripped = user_input.strip()
    if not stripped:
        return None

    starts_like_path = (
        stripped.startswith("/")
        or stripped.startswith("~")
        or stripped.startswith("./")
        or stripped.startswith("../")
        or stripped.startswith("file://")
        or (
            len(stripped) >= 3
            and stripped[1] == ":"
            and stripped[2] in ("\\", "/")
            and stripped[0].isalpha()
        )
        or stripped.startswith('"/')
        or stripped.startswith('"~')
        or stripped.startswith("'/")
        or stripped.startswith("'~")
        or (
            len(stripped) >= 4
            and stripped[0] in ("'", '"')
            and stripped[2] == ":"
            and stripped[3] in ("\\", "/")
            and stripped[1].isalpha()
        )
    )
    if not starts_like_path:
        return None

    direct_path = resolve_attachment_path(stripped)
    if direct_path is not None:
        return {
            "path": direct_path,
            "is_image": direct_path.suffix.lower() in IMAGE_EXTENSIONS,
            "remainder": "",
        }

    first_token, remainder = split_path_input(stripped)
    drop_path = resolve_attachment_path(first_token)
    if drop_path is None and " " in stripped and stripped[0] not in {"'", '"'}:
        space_positions = [idx for idx, ch in enumerate(stripped) if ch == " "]
        for pos in reversed(space_positions):
            candidate = stripped[:pos].rstrip()
            resolved = resolve_attachment_path(candidate)
            if resolved is not None:
                drop_path = resolved
                remainder = stripped[pos + 1 :].strip()
                break
    if drop_path is None:
        return None

    return {
        "path": drop_path,
        "is_image": drop_path.suffix.lower() in IMAGE_EXTENSIONS,
        "remainder": remainder,
    }


def collect_query_images(
    query: str | None, image_arg: str | None = None
) -> tuple[str, list[Path]]:
    """Collect local image attachments for single-query flows."""
    message = query or ""
    images: list[Path] = []

    if isinstance(message, str):
        dropped = detect_file_drop(message)
        if dropped and dropped.get("is_image"):
            images.append(dropped["path"])
            message = dropped["remainder"] or f"[User attached image: {dropped['path'].name}]"

    if image_arg:
        explicit_path = resolve_attachment_path(image_arg)
        if explicit_path is None:
            raise ValueError(f"Image file not found: {image_arg}")
        if explicit_path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"Not a supported image file: {explicit_path}")
        images.append(explicit_path)

    deduped: list[Path] = []
    seen: set[str] = set()
    for img in images:
        key = str(img)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(img)
    return message, deduped


def enrich_with_attached_images(user_text: str, image_paths: list[str]) -> str:
    """Pre-analyze attached images via vision with local OCR/VLM fallback."""
    import asyncio

    from agent.document_stack.extract import extract_document
    from agent.document_stack.local_image import understand_image_local
    from agent.document_stack.markers import (
        format_document_context_block,
        format_document_context_failed,
    )
    from agent.vision_prompts import (
        build_preanalysis_prompt,
        ensure_image_persistence_marker,
        format_image_context_block,
        format_image_context_failed,
        image_persistence_marker,
    )
    from tools.vision_tools import vision_analyze_tool

    try:
        from ector_cli.config import load_config

        documents_cfg = load_config().get("documents", {})
        mode = str(documents_cfg.get("preanalysis", "vision_then_ocr")).strip().lower()
        dark_mode_boost = bool(documents_cfg.get("dark_mode_boost", True))
        local_vlm = str(documents_cfg.get("local_vlm", "auto")).strip().lower()
        florence_model = str(
            documents_cfg.get("florence_model", "microsoft/Florence-2-base")
        )
    except Exception:
        mode = "vision_then_ocr"
        dark_mode_boost = True
        local_vlm = "auto"
        florence_model = "microsoft/Florence-2-base"

    prompt = build_preanalysis_prompt(user_text)

    parts: list[str] = []
    persisted_paths: list[str] = []
    for path in image_paths:
        p = Path(path)
        if not p.exists():
            continue
        persisted_paths.append(str(p))

        def _append_part(block: str) -> None:
            parts.append(ensure_image_persistence_marker(block, str(p)))

        vision_ok = False
        if mode in {"vision_then_ocr", "vision_only"}:
            try:
                r = json.loads(
                    asyncio.run(vision_analyze_tool(image_url=str(p), user_prompt=prompt))
                )
                desc = r.get("analysis", "") if r.get("success") else None
                if desc:
                    vision_ok = True
                    _append_part(format_image_context_block(desc, str(p)))
                elif mode == "vision_only":
                    _append_part(format_image_context_failed(str(p)))
            except Exception:
                if mode == "vision_only":
                    _append_part(format_image_context_failed(str(p)))

        if vision_ok:
            continue
        if mode == "vision_only":
            continue

        local = understand_image_local(
            str(p),
            local_vlm=local_vlm,
            florence_model=florence_model,
        )
        if local.get("success") and (local.get("markdown") or "").strip():
            _append_part(
                format_document_context_block(
                    local.get("markdown", ""),
                    str(p),
                    local.get("backend", "tesseract+florence"),
                )
            )
            continue

        extracted = extract_document(
            str(p),
            force_ocr=True,
            dark_mode_boost=dark_mode_boost,
            output="markdown",
        )
        if extracted.get("success"):
            _append_part(
                format_document_context_block(
                    extracted.get("markdown", ""),
                    str(p),
                    extracted.get("backend", "ocr"),
                )
            )
        else:
            _append_part(format_document_context_failed(str(p)))

    text = user_text or ""
    prefix = "\n\n".join(parts)
    if prefix:
        return f"{prefix}\n\n{text}" if text else prefix
    if persisted_paths:
        marker_prefix = "\n\n".join(
            image_persistence_marker(path) for path in persisted_paths
        )
        return f"{marker_prefix}\n\n{text}" if text else marker_prefix
    return text or "What do you see in this image?"


# Backward-compatible aliases for cli.py during migration
_IMAGE_EXTENSIONS = IMAGE_EXTENSIONS
_split_path_input = split_path_input
_resolve_attachment_path = resolve_attachment_path
_detect_file_drop = detect_file_drop
_collect_query_images = collect_query_images
_termux_example_image_path = termux_example_image_path
_is_termux_environment = is_termux
