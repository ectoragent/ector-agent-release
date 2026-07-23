"""Local image understanding: Tesseract (+ coords) ∥ Florence-2 → merge."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

from agent.document_stack.florence import (
    DEFAULT_FLORENCE_MODEL,
    analyze_with_florence,
    florence_available,
)
from agent.document_stack.merge import merge_backend_label, merge_image_understanding
from agent.document_stack.tesseract_ocr import extract_with_tesseract, tesseract_available

logger = logging.getLogger(__name__)


def _load_documents_cfg() -> Dict[str, Any]:
    try:
        from ector_cli.config import load_config

        cfg = load_config().get("documents", {})
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _should_run_florence(local_vlm: str) -> bool:
    mode = (local_vlm or "auto").strip().lower()
    if mode in {"off", "false", "0", "none"}:
        return False
    if mode == "florence":
        return True
    # auto
    return florence_available()


def understand_image_local(
    path: str | Path,
    *,
    local_vlm: Optional[str] = None,
    florence_model: Optional[str] = None,
    include_florence_ocr: bool = True,
) -> Dict[str, Any]:
    """Run Tesseract and optional Florence-2 in parallel, then merge.

    Returns a result shaped like extract_document for drop-in use in
    attachment enrichment paths.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        return {"success": False, "error": f"File not found: {source}", "kind": "image"}

    cfg = _load_documents_cfg()
    vlm_mode = (
        local_vlm
        if local_vlm is not None
        else str(cfg.get("local_vlm", "auto"))
    )
    model_id = (
        florence_model
        if florence_model is not None
        else str(cfg.get("florence_model", DEFAULT_FLORENCE_MODEL))
    )

    run_tess = tesseract_available()
    run_flo = _should_run_florence(vlm_mode)
    if run_flo and not florence_available():
        if (vlm_mode or "").strip().lower() == "florence":
            logger.debug("local_vlm=florence but deps unavailable")
        run_flo = False

    if not run_tess and not run_flo:
        return {
            "success": False,
            "error": "No local image backends (tesseract / florence)",
            "kind": "image",
        }

    ocr_result: Optional[Dict[str, Any]] = None
    florence_result: Optional[Dict[str, Any]] = None

    def _ocr() -> Dict[str, Any]:
        return extract_with_tesseract(source)

    def _flo() -> Dict[str, Any]:
        return analyze_with_florence(
            source,
            model_id=model_id,
            include_ocr_regions=include_florence_ocr,
        )

    try:
        if run_tess and run_flo:
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_ocr = pool.submit(_ocr)
                fut_flo = pool.submit(_flo)
                try:
                    ocr_result = fut_ocr.result()
                except Exception as exc:
                    ocr_result = {"success": False, "error": str(exc)}
                try:
                    florence_result = fut_flo.result()
                except Exception as exc:
                    florence_result = {"success": False, "error": str(exc)}
        elif run_tess:
            try:
                ocr_result = _ocr()
            except Exception as exc:
                ocr_result = {"success": False, "error": str(exc)}
        else:
            try:
                florence_result = _flo()
            except Exception as exc:
                florence_result = {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": str(exc), "kind": "image"}

    merged = merge_image_understanding(ocr_result, florence_result)
    if not merged:
        errors = []
        if ocr_result and not ocr_result.get("success"):
            errors.append(str(ocr_result.get("error") or "tesseract failed"))
        if florence_result and not florence_result.get("success"):
            errors.append(str(florence_result.get("error") or "florence failed"))
        return {
            "success": False,
            "error": "; ".join(errors) or "local image understanding produced no content",
            "kind": "image",
            "ocr": ocr_result,
            "florence": florence_result,
        }

    backend = merge_backend_label(ocr_result, florence_result)
    boxes = []
    if ocr_result and isinstance(ocr_result.get("boxes"), list):
        boxes = ocr_result["boxes"]

    return {
        "success": True,
        "backend": backend,
        "markdown": merged,
        "boxes": boxes,
        "metadata": {
            "local_vlm": vlm_mode,
            "florence_model": model_id if run_flo else None,
            "ocr_backend": (ocr_result or {}).get("backend"),
            "florence_ok": bool(florence_result and florence_result.get("success")),
        },
        "page_count": None,
        "tables_found": False,
        "kind": "image",
        "ocr": ocr_result,
        "florence": florence_result,
    }
