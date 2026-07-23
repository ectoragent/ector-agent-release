"""Tesseract OCR with word-level bounding boxes (TSV)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple


def tesseract_available() -> bool:
    return bool(shutil.which("tesseract"))


def parse_tesseract_tsv(tsv: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Parse Tesseract TSV stdout into plain text and word boxes.

    TSV columns: level, page_num, block_num, par_num, line_num, word_num,
    left, top, width, height, conf, text. Word rows use level == 5.
    """
    boxes: List[Dict[str, Any]] = []
    words: List[str] = []
    lines = (tsv or "").splitlines()
    if not lines:
        return "", []

    start = 1 if lines[0].lower().startswith("level") else 0
    for line in lines[start:]:
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        try:
            level = int(parts[0])
        except ValueError:
            continue
        if level != 5:
            continue
        text = parts[11]
        if not text or not text.strip():
            continue
        try:
            conf = float(parts[10])
        except ValueError:
            conf = -1.0
        if conf < 0:
            continue
        try:
            left = int(parts[6])
            top = int(parts[7])
            width = int(parts[8])
            height = int(parts[9])
        except ValueError:
            continue
        words.append(text)
        boxes.append(
            {
                "text": text,
                "conf": conf,
                "x": left,
                "y": top,
                "w": width,
                "h": height,
            }
        )
    return " ".join(words).strip(), boxes


def extract_with_tesseract(path: Path) -> Dict[str, Any]:
    """Run Tesseract OCR; prefer TSV (text + boxes), fall back to plain stdout.

    English only for now (avoids failing on missing language packs).
    """
    if not tesseract_available():
        raise RuntimeError("tesseract binary not found on PATH")

    tsv_proc = subprocess.run(
        ["tesseract", str(path), "stdout", "tsv"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if tsv_proc.returncode == 0 and (tsv_proc.stdout or "").strip():
        text, boxes = parse_tesseract_tsv(tsv_proc.stdout)
        if text or boxes:
            return {
                "success": True,
                "backend": "tesseract",
                "markdown": text,
                "boxes": boxes,
                "metadata": {"boxes": boxes, "ocr_format": "tsv"},
                "page_count": None,
                "tables_found": False,
            }

    proc = subprocess.run(
        ["tesseract", str(path), "stdout"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        err = (tsv_proc.stderr or proc.stderr or "").strip() or "tesseract extraction failed"
        raise RuntimeError(err)
    text = (proc.stdout or "").strip()
    return {
        "success": True,
        "backend": "tesseract",
        "markdown": text,
        "boxes": [],
        "metadata": {"boxes": [], "ocr_format": "text"},
        "page_count": None,
        "tables_found": False,
    }
