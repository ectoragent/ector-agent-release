"""Image preprocessing for OCR (especially dark mode UI screenshots)."""

from __future__ import annotations

from pathlib import Path
from typing import List


def preprocess_image_for_ocr(image_path: str, output_dir: Path) -> List[str]:
    """Generate OCR-friendly variants of an input image.

    Returns a list of local paths ordered by preference.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    variants = [image_path]
    try:
        from PIL import Image, ImageEnhance, ImageOps  # type: ignore
    except Exception:
        return variants

    src = Path(image_path)
    if not src.exists():
        return variants

    try:
        with Image.open(src) as img:
            gray = ImageOps.grayscale(img)
            contrast = ImageEnhance.Contrast(gray).enhance(2.0)
            sharp = ImageEnhance.Sharpness(contrast).enhance(1.5)
            boosted_path = output_dir / f"{src.stem}_ocr_boosted.png"
            sharp.save(boosted_path, format="PNG")
            variants.append(str(boosted_path))

            inverted = ImageOps.invert(sharp)
            inverted_path = output_dir / f"{src.stem}_ocr_inverted.png"
            inverted.save(inverted_path, format="PNG")
            variants.append(str(inverted_path))
    except Exception:
        return variants

    return variants
