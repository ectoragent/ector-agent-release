"""Canonical paths and relocation for agent-generated image files."""

from __future__ import annotations

import logging
import re
import shutil
import uuid
from pathlib import Path

from ector_constants import get_agent_images_dir, get_ector_home

logger = logging.getLogger(__name__)

_IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".svg", ".ico"}
)
_ARTIFACT_SUFFIXES = frozenset(
    {".svg", ".html", ".htm", ".csv", ".json", ".md", ".txt", ".pdf"}
)
_ATTACHABLE_SUFFIXES = _IMAGE_SUFFIXES | _ARTIFACT_SUFFIXES
_OUTPUT_PATH_RE = re.compile(
    r"(?:file://)?(?:~\/|\.{1,2}\/|\/)[^\s\"'<>|]+\.(?:png|jpe?g|gif|webp|bmp|tiff?|svg|ico|html?|csv|json|md|txt|pdf)",
    re.IGNORECASE,
)


def _is_image_file(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_SUFFIXES


def _already_under_ector_images(resolved: Path) -> bool:
    home = get_ector_home().resolve()
    for sub in (Path("images"), Path("cache") / "images"):
        try:
            resolved.relative_to((home / sub).resolve())
            return True
        except ValueError:
            continue
    return False


def _already_under_ector_home(resolved: Path) -> bool:
    try:
        resolved.relative_to(get_ector_home().resolve())
        return True
    except ValueError:
        return False


def _agent_files_dir() -> Path:
    path = get_ector_home() / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def relocate_agent_image_if_needed(source: str) -> str:
    """Copy an image into ``{ECTOR_HOME}/images`` when saved elsewhere.

    Returns the path the agent should reference (unchanged if already under
    ECTOR image dirs, or a new path under ``images/`` after copy).
    """
    raw = str(source or "").strip()
    if not raw:
        return raw
    try:
        src = Path(raw).expanduser().resolve(strict=True)
    except (OSError, ValueError):
        return raw
    if not src.is_file() or not _is_image_file(src):
        return raw
    if _already_under_ector_images(src):
        return str(src)

    dest_dir = get_agent_images_dir()
    dest_name = f"agent_{src.stem}_{uuid.uuid4().hex[:8]}{src.suffix.lower()}"
    dest = dest_dir / dest_name
    try:
        shutil.copy2(src, dest)
        logger.info("Relocated agent image %s -> %s", src, dest)
        return str(dest)
    except OSError as exc:
        logger.warning("Could not relocate agent image %s: %s", src, exc)
        return raw


def relocate_agent_artifact_if_needed(source: str) -> str:
    """Copy a generated artifact into ``{ECTOR_HOME}/files`` when saved elsewhere."""
    raw = str(source or "").strip()
    if not raw:
        return raw
    try:
        src = Path(raw).expanduser().resolve(strict=True)
    except (OSError, ValueError):
        return raw
    if not src.is_file() or src.suffix.lower() not in _ARTIFACT_SUFFIXES:
        return raw
    if _already_under_ector_home(src):
        return str(src)

    dest_dir = _agent_files_dir()
    dest_name = f"agent_{src.stem}_{uuid.uuid4().hex[:8]}{src.suffix.lower()}"
    dest = dest_dir / dest_name
    try:
        shutil.copy2(src, dest)
        logger.info("Relocated agent artifact %s -> %s", src, dest)
        return str(dest)
    except OSError as exc:
        logger.warning("Could not relocate agent artifact %s: %s", src, exc)
        return raw


def markdown_for_agent_image_path(image_path: str) -> str | None:
    """Build a markdown image line for the web dashboard when path is servable."""
    from ector_cli.chat_media_paths import chat_image_api_url

    url = chat_image_api_url(image_path)
    if not url:
        return None
    name = Path(str(image_path)).stem.replace("_", " ").strip() or "imagem"
    return f"\n\n![{name}]({url})\n"


def markdown_from_write_tool_result(result: str) -> str | None:
    """If a write/edit tool saved an image, return markdown to embed it in chat."""
    import json

    try:
        data = json.loads(str(result or ""))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("error"):
        return None
    path = str(data.get("path") or "").strip()
    if not path:
        return None
    return markdown_for_agent_image_path(path)


def _extract_output_paths(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _OUTPUT_PATH_RE.finditer(str(text or "")):
        raw = match.group(0).strip().rstrip(".,;:!?")
        if raw.startswith("file://"):
            raw = raw[7:]
        if not raw or raw in seen:
            continue
        seen.add(raw)
        found.append(raw)
    return found


def markdown_from_tool_result(tool_name: str, result: str) -> str | None:
    """Return markdown snippet to surface generated media in web chat."""
    name = str(tool_name or "").strip()
    if not name or not result:
        return None

    if name in {"write_file", "edit_file", "patch"}:
        return markdown_from_write_tool_result(result)

    if name != "execute_code":
        return None

    import json

    try:
        data = json.loads(str(result or ""))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    output = str(data.get("output") or "").strip()
    if not output:
        return None

    snippets: list[str] = []
    for raw_path in _extract_output_paths(output):
        suffix = Path(raw_path).suffix.lower()
        if suffix in _IMAGE_SUFFIXES:
            moved = relocate_agent_image_if_needed(raw_path)
            md = markdown_for_agent_image_path(moved)
            if md:
                snippets.append(md.strip())
            continue
        if suffix in _ARTIFACT_SUFFIXES:
            moved = relocate_agent_artifact_if_needed(raw_path)
            snippets.append(f"Artefato gerado: `{moved}`")

    if not snippets:
        return None
    return "\n\n" + "\n\n".join(snippets) + "\n"


def extract_chat_media_from_tool_result(tool_name: str, result: str) -> list[dict]:
    """Extract media candidates from a tool result for chat attachments."""
    name = str(tool_name or "").strip()
    if not name or not result:
        return []

    import json

    if name in {"write_file", "edit_file", "patch"}:
        try:
            data = json.loads(str(result or ""))
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(data, dict) or data.get("error"):
            return []
        path = str(data.get("path") or "").strip()
        if not path:
            return []
        suffix = Path(path).suffix.lower()
        if suffix not in _ATTACHABLE_SUFFIXES:
            return []
        kind = "image" if suffix in _IMAGE_SUFFIXES else "artifact"
        if kind == "image":
            path = relocate_agent_image_if_needed(path)
        elif kind == "artifact":
            path = relocate_agent_artifact_if_needed(path)
        return [{"path": path, "kind": kind}]

    if name != "execute_code":
        return []

    try:
        data = json.loads(str(result or ""))
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    output = str(data.get("output") or "").strip()
    if not output:
        return []

    media: list[dict] = []
    for raw_path in _extract_output_paths(output):
        suffix = Path(raw_path).suffix.lower()
        if suffix in _IMAGE_SUFFIXES:
            media.append(
                {"path": relocate_agent_image_if_needed(raw_path), "kind": "image"}
            )
        elif suffix in _ARTIFACT_SUFFIXES:
            media.append(
                {"path": relocate_agent_artifact_if_needed(raw_path), "kind": "artifact"}
            )
    return media


def normalize_write_result_media_path(result_dict: dict) -> dict:
    """If *result_dict* points at supported media outside ECTOR_HOME, relocate/update."""
    if result_dict.get("error"):
        return result_dict
    path = result_dict.get("path")
    if not isinstance(path, str) or not path.strip():
        return result_dict
    suffix = Path(path).suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        new_path = relocate_agent_image_if_needed(path)
    elif suffix in _ARTIFACT_SUFFIXES:
        new_path = relocate_agent_artifact_if_needed(path)
    else:
        return result_dict
    if new_path != path:
        out = dict(result_dict)
        out["path"] = new_path
        out["relocated_from"] = path
        return out
    return result_dict


def normalize_write_result_image_path(result_dict: dict) -> dict:
    """Backward-compatible wrapper for older imports."""
    return normalize_write_result_media_path(result_dict)
