"""Florence-2 local VLM wrapper (optional, lazy-loaded)."""

from __future__ import annotations

import importlib.util
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_FLORENCE_MODEL = "microsoft/Florence-2-base"

_lock = threading.Lock()
_model = None
_processor = None
_loaded_model_id: Optional[str] = None
_load_error: Optional[str] = None


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def florence_deps_available() -> bool:
    """True when optional documents-vision deps are importable."""
    return _has_module("torch") and _has_module("transformers") and _has_module("PIL")


def florence_available() -> bool:
    """Probe whether Florence-2 can be used (deps only; does not load weights)."""
    return florence_deps_available()


def _resolve_device_dtype():
    import torch  # type: ignore

    if torch.cuda.is_available():
        return "cuda", torch.float16
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps", torch.float16
    return "cpu", torch.float32


def _load_model(model_id: str) -> None:
    global _model, _processor, _loaded_model_id, _load_error

    with _lock:
        if _model is not None and _processor is not None and _loaded_model_id == model_id:
            return
        if _load_error and _loaded_model_id == model_id:
            raise RuntimeError(_load_error)

        try:
            import torch  # type: ignore
            from PIL import Image  # noqa: F401  # type: ignore
            from transformers import AutoModelForCausalLM, AutoProcessor  # type: ignore

            device, torch_dtype = _resolve_device_dtype()
            processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
            model = AutoModelForCausalLM.from_pretrained(
                model_id,
                torch_dtype=torch_dtype,
                trust_remote_code=True,
            ).to(device)
            model.eval()
            _processor = processor
            _model = model
            _loaded_model_id = model_id
            _load_error = None
            logger.info("Florence-2 loaded model=%s device=%s", model_id, device)
        except Exception as exc:
            _model = None
            _processor = None
            _loaded_model_id = model_id
            _load_error = str(exc)
            raise RuntimeError(f"Florence-2 load failed: {exc}") from exc


def _run_task(image, task_prompt: str, *, max_new_tokens: int = 1024) -> Any:
    import torch  # type: ignore

    assert _model is not None and _processor is not None
    device = next(_model.parameters()).device
    dtype = next(_model.parameters()).dtype

    inputs = _processor(text=task_prompt, images=image, return_tensors="pt")
    # Move tensors; pixel_values need model dtype on GPU/MPS.
    moved: Dict[str, Any] = {}
    for key, value in inputs.items():
        if hasattr(value, "to"):
            if key == "pixel_values":
                moved[key] = value.to(device=device, dtype=dtype)
            else:
                moved[key] = value.to(device)
        else:
            moved[key] = value

    with torch.no_grad():
        generated_ids = _model.generate(
            input_ids=moved["input_ids"],
            pixel_values=moved["pixel_values"],
            max_new_tokens=max_new_tokens,
            do_sample=False,
            num_beams=3,
        )
    generated_text = _processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
    parsed = _processor.post_process_generation(
        generated_text,
        task=task_prompt,
        image_size=(image.width, image.height),
    )
    return parsed.get(task_prompt, parsed)


def _ocr_regions_from_result(raw: Any) -> List[Dict[str, Any]]:
    """Normalize Florence <OCR_WITH_REGION> output into box-like dicts."""
    if not isinstance(raw, dict):
        return []
    labels = raw.get("labels") or raw.get("rec_texts") or []
    quads = raw.get("quad_boxes") or raw.get("rec_boxes") or []
    regions: List[Dict[str, Any]] = []
    for idx, label in enumerate(labels):
        text = str(label).strip()
        if not text:
            continue
        quad = quads[idx] if idx < len(quads) else None
        x = y = w = h = 0
        if isinstance(quad, (list, tuple)) and len(quad) >= 8:
            xs = [float(quad[i]) for i in range(0, 8, 2)]
            ys = [float(quad[i]) for i in range(1, 8, 2)]
            x0, x1 = min(xs), max(xs)
            y0, y1 = min(ys), max(ys)
            x, y, w, h = int(x0), int(y0), int(x1 - x0), int(y1 - y0)
        elif isinstance(quad, (list, tuple)) and len(quad) >= 4:
            x0, y0, x1, y1 = (float(v) for v in quad[:4])
            x, y, w, h = int(x0), int(y0), int(x1 - x0), int(y1 - y0)
        regions.append({"text": text, "conf": None, "x": x, "y": y, "w": w, "h": h})
    return regions


def analyze_with_florence(
    path: Path | str,
    *,
    model_id: str = DEFAULT_FLORENCE_MODEL,
    include_ocr_regions: bool = True,
) -> Dict[str, Any]:
    """Run Florence-2 caption (+ optional OCR regions) on a local image."""
    if not florence_deps_available():
        return {
            "success": False,
            "error": "Florence-2 deps missing (install ector-agent[documents-vision])",
            "backend": "florence-2",
        }

    image_path = Path(path).expanduser().resolve()
    if not image_path.is_file():
        return {
            "success": False,
            "error": f"File not found: {image_path}",
            "backend": "florence-2",
        }

    try:
        from PIL import Image  # type: ignore

        _load_model(model_id)
        image = Image.open(image_path).convert("RGB")
        caption_raw = _run_task(image, "<MORE_DETAILED_CAPTION>")
        caption = caption_raw if isinstance(caption_raw, str) else str(caption_raw)

        ocr_regions: List[Dict[str, Any]] = []
        if include_ocr_regions:
            try:
                ocr_raw = _run_task(image, "<OCR_WITH_REGION>")
                ocr_regions = _ocr_regions_from_result(ocr_raw)
            except Exception as exc:
                logger.debug("Florence OCR_WITH_REGION skipped: %s", exc)

        return {
            "success": True,
            "backend": "florence-2",
            "caption": (caption or "").strip(),
            "ocr_regions": ocr_regions,
            "model_id": model_id,
        }
    except Exception as exc:
        logger.warning("Florence-2 analysis failed: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "backend": "florence-2",
        }


def reset_florence_cache_for_tests() -> None:
    """Clear lazy-loaded model state (tests only)."""
    global _model, _processor, _loaded_model_id, _load_error
    with _lock:
        _model = None
        _processor = None
        _loaded_model_id = None
        _load_error = None
