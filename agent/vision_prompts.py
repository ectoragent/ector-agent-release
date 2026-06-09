"""Shared vision prompt builders for pre-analysis and vision_analyze."""

from __future__ import annotations

import re

# User phrases that request exhaustive description (any language mix common in PT-BR).
_DETAIL_REQUEST_PATTERNS = re.compile(
    r"(?i)\b("
    r"thorough|comprehensive|detailed|in\s+depth|full\s+description|describe\s+everything|"
    r"descrev[ae]\s+tudo|em\s+detalhe|com\s+detalhe|an[aá]lis[ae]\s+completa|"
    r"profundamente|tudo\s+que\s+v[eê]|everything\s+visible|all\s+visible"
    r")\b",
)

# Short / vague perception questions — default to concise answers.
_SIMPLE_QUESTION_PATTERNS = re.compile(
    r"(?i)^\s*("
    r"what\s+do\s+you\s+see|what('s| is)\s+this|what\s+is\s+in\s+this|"
    r"o\s+que\s+voc[eê]\s+v[eê]|o\s+que\s+[eé]\s+isso|"
    r"identify|recognize|reconhece|identifica"
    r")[\s?!.]*$",
)


def _wants_detail(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    return bool(_DETAIL_REQUEST_PATTERNS.search(q))


def _is_simple_question(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return True
    if len(q) < 80 and _SIMPLE_QUESTION_PATTERNS.search(q):
        return True
    return len(q) < 40 and "?" in q


def build_preanalysis_prompt(user_text: str = "") -> str:
    """Prompt for automatic image enrichment before the main model runs."""
    user_text = (user_text or "").strip()
    if _wants_detail(user_text):
        return (
            "Describe everything visible in this image in thorough detail. "
            "Include any readable text, UI elements, objects, people, layout, "
            "and colors. Stay factual; do not mention tools, APIs, or file paths."
        )
    focus = ""
    if user_text:
        focus = (
            f"The user's message: {user_text}\n\n"
            "Answer what they need first. "
        )
    return (
        f"{focus}"
        "Give a short, factual description (2–4 sentences or a brief bullet list). "
        "Include readable text verbatim when present. "
        "Do not mention tools, APIs, providers, OCR, or file paths."
    )


def build_vision_analyze_prompt(question: str) -> str:
    """Prompt for on-demand vision_analyze tool calls."""
    question = (question or "").strip()
    if _wants_detail(question):
        return (
            "Describe everything visible in this image in thorough detail, then "
            f"answer the following question:\n\n{question}"
        )
    if _is_simple_question(question):
        q = question or "What is in this image?"
        return (
            f"Answer this question in 1–3 concise sentences. "
            f"Only add extra detail if essential.\n\nQuestion: {q}"
        )
    return (
        f"Answer the following question about this image directly and concisely. "
        f"Add brief supporting detail only when it helps.\n\n{question}"
    )


def build_browser_vision_prompt(question: str) -> str:
    """Prompt for browser screenshot analysis."""
    question = (question or "").strip() or "What is on this page?"
    base = (
        "You are analyzing a screenshot of a web browser.\n\n"
        f"User's question: {question}\n\n"
    )
    if _wants_detail(question):
        return (
            f"{base}"
            "Provide a detailed answer based on what you see. "
            "If there are verification challenges or CAPTCHAs, describe them briefly. "
            "Focus on answering the user's question."
        )
    return (
        f"{base}"
        "Answer the user's question directly in a few sentences. "
        "Mention interactive elements or CAPTCHAs only if relevant to their question."
    )


# Internal marker for re-analysis; models are instructed not to cite this block.
ECTOR_IMAGE_MARKER_PREFIX = "<!--ector:image:"


def image_persistence_marker(image_path: str) -> str:
    """HTML comment embedded in stored user messages for dashboard image replay."""
    return f"{ECTOR_IMAGE_MARKER_PREFIX}{image_path}-->"


def ensure_image_persistence_marker(block: str, image_path: str) -> str:
    """Ensure a context block carries the image marker used by session history."""
    marker = image_persistence_marker(image_path)
    if marker in (block or ""):
        return block
    if block:
        return f"{block}\n{marker}"
    return marker


def format_image_context_block(description: str, image_path: str) -> str:
    """Wrap vision pre-analysis for injection into the user message."""
    desc = (description or "").strip()
    marker = image_persistence_marker(image_path)
    return (
        f"[O usuário enviou uma imagem. Contexto interno (não repetir ao usuário):\n"
        f"{desc}]\n{marker}"
    )


def format_image_context_failed(image_path: str) -> str:
    """Context when automatic vision pre-analysis failed."""
    marker = image_persistence_marker(image_path)
    return (
        "[O usuário enviou uma imagem, mas a pré-análise automática falhou. "
        "Contexto interno — não repetir ao usuário. "
        "Se precisar, reexamine com a ferramenta de visão sem narrar falhas técnicas.]\n"
        f"{marker}"
    )
