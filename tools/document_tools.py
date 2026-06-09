#!/usr/bin/env python3
"""Document extraction tools (local-first OCR stack)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import httpx

from agent.document_stack.extract import extract_document
from agent.document_stack.probe import probe_document_stack
from ector_constants import get_ector_home
from tools.registry import registry, tool_error, tool_result
from tools.url_safety import is_safe_url
from tools.website_policy import check_website_access


def check_document_requirements() -> bool:
    report = probe_document_stack()
    return bool(report.get("available"))


async def _download_document(url: str, destination: Path, timeout: float = 30.0) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    blocked = check_website_access(url)
    if blocked:
        raise PermissionError(blocked["message"])
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        destination.write_bytes(resp.content)
    return destination


async def document_extract_tool(
    *,
    path: str = "",
    url: str = "",
    output: str = "markdown",
    pages: str = "",
    force_ocr: bool = False,
    include_tables: bool = True,
) -> str:
    try:
        source_path = ""
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                return tool_error("Only http/https URLs are supported")
            if not is_safe_url(url):
                return tool_error("Unsafe URL blocked")
            out_dir = get_ector_home() / "cache" / "documents" / "downloads"
            ext = Path(parsed.path).suffix or ".pdf"
            downloaded = await _download_document(url, out_dir / f"download{ext}")
            source_path = str(downloaded)
        else:
            source_path = str(Path(path).expanduser())
        result = extract_document(
            source_path,
            output=output,
            pages=pages or None,
            force_ocr=bool(force_ocr),
            include_tables=bool(include_tables),
        )
        if not result.get("success"):
            return tool_error(result.get("error", "Document extraction failed"), **result)
        return tool_result(result)
    except Exception as exc:
        return tool_error(f"Document extraction failed: {exc}")


DOCUMENT_EXTRACT_SCHEMA = {
    "name": "document_extract",
    "description": (
        "Extract text/markdown from local documents and images using local-first backends "
        "(pymupdf/docling/marker). Use for PDFs, screenshots, and OCR fallback."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Local file path to extract."},
            "url": {"type": "string", "description": "Optional http/https URL to download and extract."},
            "output": {
                "type": "string",
                "enum": ["markdown", "text", "json"],
                "description": "Output format preference.",
            },
            "pages": {"type": "string", "description": "Optional page range like '0-4'."},
            "force_ocr": {"type": "boolean", "description": "Force OCR-capable backend when available."},
            "include_tables": {"type": "boolean", "description": "Keep table structures in extracted markdown."},
        },
        "required": [],
    },
}


def _handle_document_extract(args: Dict[str, Any], **kw: Any):
    return document_extract_tool(
        path=str(args.get("path", "") or ""),
        url=str(args.get("url", "") or ""),
        output=str(args.get("output", "markdown") or "markdown"),
        pages=str(args.get("pages", "") or ""),
        force_ocr=bool(args.get("force_ocr", False)),
        include_tables=bool(args.get("include_tables", True)),
    )


registry.register(
    name="document_extract",
    toolset="documents",
    schema=DOCUMENT_EXTRACT_SCHEMA,
    handler=_handle_document_extract,
    check_fn=check_document_requirements,
    is_async=True,
    emoji="📄",
)
