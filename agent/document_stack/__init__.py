"""Document extraction stack (local-first OCR + parsing)."""

from agent.document_stack.extract import extract_document
from agent.document_stack.probe import probe_document_stack

__all__ = ["extract_document", "probe_document_stack"]
