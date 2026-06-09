"""Capability probing for the local document extraction stack."""

from __future__ import annotations

import importlib.util
import platform
import shutil
from pathlib import Path
from typing import Any, Dict, List

from ector_constants import get_ector_home, is_termux

_HEAVY_MIN_DISK_GB = 5.0


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _try_torch_capabilities() -> tuple[bool, bool]:
    try:
        import torch  # type: ignore
    except Exception:
        return False, False
    has_cuda = False
    has_mps = False
    try:
        has_cuda = bool(torch.cuda.is_available())
    except Exception:
        has_cuda = False
    try:
        has_mps = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    except Exception:
        has_mps = False
    return has_cuda, has_mps


def probe_document_stack() -> Dict[str, Any]:
    """Inspect local dependencies and return extraction-tier recommendations."""
    home = get_ector_home()
    disk = shutil.disk_usage(home if home.exists() else Path("/"))
    free_gb = round(disk.free / (1024 ** 3), 2)

    has_pymupdf = _has_module("fitz")
    has_pymupdf4llm = _has_module("pymupdf4llm")
    has_docling = _has_module("docling")
    has_marker = _has_module("marker")
    has_pillow = _has_module("PIL")
    has_rapidocr = _has_module("rapidocr_onnxruntime")
    has_tesseract = bool(shutil.which("tesseract"))
    has_ocrmac = _has_module("ocrmac")
    has_cuda, has_mps = _try_torch_capabilities()

    backends: List[str] = []
    if has_pymupdf:
        backends.append("pymupdf")
    if has_docling:
        backends.append("docling")
    if has_marker:
        backends.append("marker")

    recommended_tier = "none"
    if has_docling:
        recommended_tier = "standard"
    elif has_pymupdf:
        recommended_tier = "lite"

    can_install_heavy = free_gb >= _HEAVY_MIN_DISK_GB and not is_termux()
    install_hints: List[str] = []
    if not has_pymupdf:
        install_hints.append("pip install 'ector-agent[documents-lite]'")
    if not has_docling and not is_termux():
        install_hints.append("pip install 'ector-agent[documents]'")
    if not has_marker and can_install_heavy:
        install_hints.append("pip install 'ector-agent[documents-heavy]'")
    if is_termux():
        install_hints.append("Termux detected: use documents-lite only")

    available = bool(backends)
    details = []
    details.append(f"free disk: {free_gb:.2f} GB")
    details.append(f"backends: {', '.join(backends) if backends else 'none'}")
    if has_cuda:
        details.append("gpu: cuda")
    elif has_mps:
        details.append("gpu: mps")
    else:
        details.append("gpu: cpu")

    return {
        "available": available,
        "recommended_tier": recommended_tier,
        "available_backends": backends,
        "install_hints": install_hints,
        "can_install_heavy": can_install_heavy,
        "system": {
            "platform": platform.system().lower(),
            "machine": platform.machine().lower(),
            "termux": is_termux(),
            "free_disk_gb": free_gb,
        },
        "engines": {
            "rapidocr": has_rapidocr,
            "tesseract": has_tesseract,
            "ocrmac": has_ocrmac,
            "pillow": has_pillow,
            "pymupdf4llm": has_pymupdf4llm,
        },
        "runtime": {"cuda": has_cuda, "mps": has_mps},
        "details": "\n".join(details),
    }
