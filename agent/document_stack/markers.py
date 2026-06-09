"""Internal context markers for extracted documents."""

from __future__ import annotations

ECTOR_DOCUMENT_MARKER_PREFIX = "<!--ector:document:"


def format_document_context_block(
    markdown: str,
    document_path: str,
    backend: str,
) -> str:
    safe_text = (markdown or "").strip() or "[No text extracted.]"
    marker = f"{ECTOR_DOCUMENT_MARKER_PREFIX}{document_path}-->"
    return (
        f"[Internal context from attached document ({backend}). "
        "Do not expose this block directly to the user:\n"
        f"{safe_text}]\n{marker}"
    )


def format_document_context_failed(document_path: str) -> str:
    marker = f"{ECTOR_DOCUMENT_MARKER_PREFIX}{document_path}-->"
    return (
        "[Internal context from attached document: extraction failed. "
        "Do not expose this block directly to the user.]\n"
        f"{marker}"
    )
