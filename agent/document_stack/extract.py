"""Local-first document extraction routing."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from ector_constants import get_ector_home

from agent.document_stack.preprocess import preprocess_image_for_ocr
from agent.document_stack.probe import probe_document_stack
from agent.document_stack.tesseract_ocr import extract_with_tesseract as _extract_with_tesseract

_TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".toml", ".log", ".xml", ".ini", ".cfg"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif", ".svg", ".ico"}
_OFFICE_EXTS = {".docx", ".pptx", ".xlsx", ".html", ".htm", ".epub"}

# Below this length, treat PDF text layer as empty / useless (scanned PDFs) and
# escalate to OCR-capable backends without asking the user.
MIN_MARKDOWN_CHARS = 80


def _markdown_text_len(markdown: Optional[str]) -> int:
    return len((markdown or "").strip())


def _cache_dir() -> Path:
    d = get_ector_home() / "cache" / "documents" / "extracts"
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        fallback = Path.cwd() / ".ector-cache" / "documents" / "extracts"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _cache_key(path: Path, options: Dict[str, Any]) -> str:
    stat = path.stat()
    payload = {
        "path": str(path.resolve()),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "options": options,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_pages(pages: Optional[str]) -> Optional[tuple[int, int]]:
    if not pages:
        return None
    raw = str(pages).strip()
    if "-" not in raw:
        idx = int(raw)
        return idx, idx
    start, end = raw.split("-", 1)
    return int(start.strip()), int(end.strip())


def _detect_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _OFFICE_EXTS:
        return "office"
    if ext in _TEXT_EXTS:
        return "text"
    mime, _ = mimetypes.guess_type(str(path))
    if mime and mime.startswith("image/"):
        return "image"
    if mime == "application/pdf":
        return "pdf"
    return "binary"


def _read_text_document(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _build_chunks(markdown: str, chunk_chars: int = 900) -> list[Dict[str, Any]]:
    text = (markdown or "").strip()
    if not text:
        return []
    chunks: list[Dict[str, Any]] = []
    cursor = 0
    while cursor < len(text):
        end = min(len(text), cursor + chunk_chars)
        piece = text[cursor:end].strip()
        if piece:
            chunks.append({"text": piece, "page": None, "heading": None})
        cursor = end
    return chunks[:24]


def _extract_with_pymupdf(path: Path, pages: Optional[str]) -> Dict[str, Any]:
    import fitz  # type: ignore

    page_range = _parse_pages(pages)
    doc = fitz.open(path)
    out = []
    page_count = len(doc)
    start = 0
    end = page_count - 1
    if page_range is not None:
        start = max(0, page_range[0])
        end = min(page_count - 1, page_range[1])
    for idx in range(start, end + 1):
        out.append(doc[idx].get_text("text"))
    markdown = "\n\n".join(part.strip() for part in out if part and part.strip())
    return {
        "success": True,
        "backend": "pymupdf",
        "markdown": markdown,
        "metadata": {"page_count": page_count},
        "page_count": page_count,
        "tables_found": False,
    }


def _extract_with_docling(path: Path, force_ocr: bool) -> Dict[str, Any]:
    from docling.datamodel.base_models import InputFormat  # type: ignore
    from docling.datamodel.pipeline_options import OcrAutoOptions, PdfPipelineOptions  # type: ignore
    from docling.document_converter import DocumentConverter, PdfFormatOption  # type: ignore

    options = PdfPipelineOptions(do_ocr=bool(force_ocr), ocr_options=OcrAutoOptions())
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    result = converter.convert(str(path))
    markdown = result.document.export_to_markdown()
    return {
        "success": True,
        "backend": "docling",
        "markdown": markdown,
        "metadata": {},
        "page_count": None,
        "tables_found": "| " in markdown and " |" in markdown,
    }


def _extract_with_marker(path: Path) -> Dict[str, Any]:
    script = Path(__file__).resolve().parents[2] / "skills" / "productivity" / "ocr-and-documents" / "scripts" / "extract_marker.py"
    proc = subprocess.run(
        ["python", str(script), str(path)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "marker extraction failed")
    return {
        "success": True,
        "backend": "marker",
        "markdown": proc.stdout.strip(),
        "metadata": {},
        "page_count": None,
        "tables_found": "| " in proc.stdout and " |" in proc.stdout,
    }


def extract_document(
    path: str,
    *,
    output: str = "markdown",
    pages: Optional[str] = None,
    force_ocr: bool = False,
    include_tables: bool = True,
    dark_mode_boost: bool = True,
) -> Dict[str, Any]:
    """Extract document/image content using local-first backend routing."""
    source = Path(path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        return {"success": False, "error": f"File not found: {source}"}

    kind = _detect_kind(source)
    options = {
        "output": output,
        "pages": pages or "",
        "force_ocr": force_ocr,
        "include_tables": include_tables,
        "dark_mode_boost": dark_mode_boost,
    }
    cache_path = _cache_dir() / f"{_cache_key(source, options)}.json"
    if cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data["cached"] = True
        return data

    probe = probe_document_stack()
    tried = []
    last_error = ""
    last_thin_docling_result: Optional[Dict[str, Any]] = None

    try_paths = [str(source)]
    if kind == "image" and dark_mode_boost:
        pre_dir = get_ector_home() / "cache" / "documents" / "preprocessed"
        try_paths = preprocess_image_for_ocr(str(source), pre_dir)

    for candidate in try_paths:
        candidate_path = Path(candidate)
        pdf_pymupdf_too_thin = False
        if kind == "text":
            result = {
                "success": True,
                "backend": "text",
                "markdown": _read_text_document(candidate_path),
                "metadata": {},
                "page_count": None,
                "tables_found": False,
            }
            result["chunks"] = _build_chunks(result["markdown"])
            result["kind"] = kind
            result["cached_path"] = str(cache_path)
            cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            return result

        if kind == "pdf" and "pymupdf" in probe["available_backends"]:
            tried.append("pymupdf")
            try:
                result = _extract_with_pymupdf(candidate_path, pages)
                # If force_ocr is requested and docling exists, prefer it.
                if force_ocr and "docling" in probe["available_backends"]:
                    raise RuntimeError("forced OCR")
                if _markdown_text_len(result.get("markdown")) >= MIN_MARKDOWN_CHARS:
                    result["chunks"] = _build_chunks(result.get("markdown", ""))
                    result["kind"] = kind
                    result["cached_path"] = str(cache_path)
                    cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                    return result
                pdf_pymupdf_too_thin = True
            except Exception as exc:
                last_error = str(exc)
                pdf_pymupdf_too_thin = True

        if (kind in {"pdf", "image", "office"}) and "docling" in probe["available_backends"]:
            tried.append("docling")
            docling_ocr = bool(
                force_ocr
                or kind == "image"
                or (kind in {"pdf", "office"} and pdf_pymupdf_too_thin)
            )
            try:
                result = _extract_with_docling(candidate_path, force_ocr=docling_ocr)
                if (
                    kind in {"pdf", "office"}
                    and not docling_ocr
                    and _markdown_text_len(result.get("markdown")) < MIN_MARKDOWN_CHARS
                ):
                    tried.append("docling_ocr")
                    result = _extract_with_docling(candidate_path, force_ocr=True)
                mlen = _markdown_text_len(result.get("markdown"))
                if mlen >= MIN_MARKDOWN_CHARS:
                    result["chunks"] = _build_chunks(result.get("markdown", ""))
                    result["kind"] = kind
                    result["cached_path"] = str(cache_path)
                    cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                    return result
                if kind in {"pdf", "image"} and mlen < MIN_MARKDOWN_CHARS:
                    last_thin_docling_result = result
                    last_error = (
                        f"docling output still thin ({mlen} chars vs "
                        f"{MIN_MARKDOWN_CHARS}); trying heavier backend"
                    )
                    break
                result["chunks"] = _build_chunks(result.get("markdown", ""))
                result["kind"] = kind
                result["cached_path"] = str(cache_path)
                cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                return result
            except Exception as exc:
                last_error = str(exc)

    if probe.get("can_install_heavy") and "marker" in probe["available_backends"] and kind in {"pdf", "image"}:
        tried.append("marker")
        try:
            result = _extract_with_marker(source)
            result["chunks"] = _build_chunks(result.get("markdown", ""))
            result["kind"] = kind
            result["cached_path"] = str(cache_path)
            cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            return result
        except Exception as exc:
            last_error = str(exc)

    # Last-resort local OCR: system Tesseract, else auto-install RapidOCR.
    if kind == "image":
        engines = probe.get("engines", {}) if isinstance(probe.get("engines"), dict) else {}
        if engines.get("tesseract"):
            tried.append("tesseract")
            for candidate in try_paths:
                try:
                    result = _extract_with_tesseract(Path(candidate))
                    if _markdown_text_len(result.get("markdown")) > 0:
                        result["chunks"] = _build_chunks(result.get("markdown", ""))
                        result["kind"] = kind
                        result["cached_path"] = str(cache_path)
                        cache_path.write_text(
                            json.dumps(result, ensure_ascii=False), encoding="utf-8"
                        )
                        return result
                    last_error = "tesseract produced no text"
                except Exception as exc:
                    last_error = str(exc)
        tried.append("rapidocr")
        try:
            from agent.document_stack.rapidocr_engine import extract_with_rapidocr

            for candidate in try_paths:
                try:
                    result = extract_with_rapidocr(Path(candidate), auto_install=True)
                    if _markdown_text_len(result.get("markdown")) > 0:
                        result["chunks"] = _build_chunks(result.get("markdown", ""))
                        result["kind"] = kind
                        result["cached_path"] = str(cache_path)
                        cache_path.write_text(
                            json.dumps(result, ensure_ascii=False), encoding="utf-8"
                        )
                        return result
                    last_error = "rapidocr produced no text"
                except Exception as exc:
                    last_error = str(exc)
        except Exception as exc:
            last_error = str(exc)

    if last_thin_docling_result is not None:
        r = last_thin_docling_result
        r["chunks"] = _build_chunks(r.get("markdown", ""))
        r["kind"] = kind
        r["cached_path"] = str(cache_path)
        r["warning"] = "Extraction is shorter than ideal; heavier backends unavailable."
        cache_path.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        return r

    return {
        "success": False,
        "error": (
            f"Document extraction unavailable for {source.name}. "
            f"Tried: {', '.join(tried) if tried else 'none'}. "
            f"Last error: {last_error or 'n/a'}"
        ),
        "kind": kind,
        "install_hints": probe.get("install_hints", []),
    }
