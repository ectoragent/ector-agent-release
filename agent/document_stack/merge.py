"""Merge Tesseract OCR geometry with Florence-2 scene understanding."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _format_box_line(box: Dict[str, Any]) -> str:
    text = str(box.get("text") or "").replace('"', '\\"')
    x = int(box.get("x") or 0)
    y = int(box.get("y") or 0)
    w = int(box.get("w") or 0)
    h = int(box.get("h") or 0)
    x2, y2 = x + w, y + h
    conf = box.get("conf")
    conf_suffix = f" conf={conf:.0f}" if isinstance(conf, (int, float)) else ""
    return f'- "{text}" @ ({x},{y})-({x2},{y2}){conf_suffix}'


def merge_image_understanding(
    ocr: Optional[Dict[str, Any]],
    florence: Optional[Dict[str, Any]],
) -> str:
    """Build a single markdown context block from OCR + Florence results.

    Policy:
    - Florence owns scene/UI understanding (caption).
    - Tesseract owns literal OCR text + positions when available.
    - Florence OCR regions are included only when Tesseract text is thin.
    """
    sections: List[str] = []

    caption = ""
    if florence and florence.get("success"):
        caption = str(florence.get("caption") or "").strip()
    if caption:
        sections.append(f"## Scene\n{caption}")

    ocr_text = ""
    boxes: List[Dict[str, Any]] = []
    if ocr and ocr.get("success"):
        ocr_text = str(ocr.get("markdown") or "").strip()
        raw_boxes = ocr.get("boxes")
        if isinstance(raw_boxes, list):
            boxes = [b for b in raw_boxes if isinstance(b, dict) and b.get("text")]

    if boxes:
        lines = ["## OCR (with positions)"]
        # Cap density so the agent prompt stays usable.
        for box in boxes[:200]:
            lines.append(_format_box_line(box))
        if len(boxes) > 200:
            lines.append(f"- … and {len(boxes) - 200} more words")
        sections.append("\n".join(lines))
    elif ocr_text:
        sections.append(f"## OCR\n{ocr_text}")

    tesseract_thin = not boxes and len(ocr_text) < 40
    florence_regions: List[Dict[str, Any]] = []
    if florence and florence.get("success") and tesseract_thin:
        raw_regions = florence.get("ocr_regions")
        if isinstance(raw_regions, list):
            florence_regions = [
                r for r in raw_regions if isinstance(r, dict) and r.get("text")
            ]
    if florence_regions:
        lines = ["## OCR regions (Florence)"]
        for region in florence_regions[:80]:
            lines.append(_format_box_line(region))
        sections.append("\n".join(lines))

    return "\n\n".join(sections).strip()


def merge_backend_label(
    ocr: Optional[Dict[str, Any]],
    florence: Optional[Dict[str, Any]],
) -> str:
    """Stable backend string for markers / logging."""
    has_ocr = bool(ocr and ocr.get("success") and (ocr.get("markdown") or ocr.get("boxes")))
    has_flo = bool(florence and florence.get("success") and florence.get("caption"))
    ocr_name = "tesseract"
    if has_ocr and isinstance(ocr, dict):
        raw = str(ocr.get("backend") or "").strip().lower()
        if raw.startswith("rapid"):
            ocr_name = "rapidocr"
        elif raw:
            ocr_name = raw
    if has_ocr and has_flo:
        return f"{ocr_name}+florence"
    if has_flo:
        return "florence-2"
    if has_ocr:
        return ocr_name
    return "local"
