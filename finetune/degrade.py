"""Optional image degradation for line crops (blur / noise / JPEG)."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

JPEG_QUALITY = 40
GAUSS_NOISE_STD = 12.0
BLUR_RADIUS = 1.2


# Write degraded copies of every png that already has a .gt.txt sibling.
def degrade(data_dir: Path) -> int:
    written = 0
    for gt_path in sorted(data_dir.rglob("*.gt.txt")):
        png_name = gt_path.name[: -len(".gt.txt")] + ".png"
        png_path = gt_path.with_name(png_name)
        if not png_path.is_file():
            continue
        image = Image.open(png_path).convert("RGB")
        stem = png_path.stem
        parent = png_path.parent
        label = gt_path.read_text(encoding="utf-8")

        variants = {
            f"{stem}_blur.png": _blur(image),
            f"{stem}_noise.png": _noise(image),
            f"{stem}_jpeg.png": _jpeg(image),
        }
        for name, variant in variants.items():
            out = parent / name
            variant.save(out)
            (parent / name.replace(".png", ".gt.txt")).write_text(
                label, encoding="utf-8"
            )
            written += 1

    logger.info("wrote %d degraded line(s) under %s", written, data_dir)
    return written


# Apply a light Gaussian blur.
def _blur(image: Image.Image) -> Image.Image:
    return image.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS))


# Add Gaussian noise to pixel values.
def _noise(image: Image.Image) -> Image.Image:
    arr = np.asarray(image, dtype=np.float32)
    noise = np.random.normal(0.0, GAUSS_NOISE_STD, arr.shape)
    noisy = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(noisy)


# Re-encode through low-quality JPEG.
def _jpeg(image: Image.Image) -> Image.Image:
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=JPEG_QUALITY)
    buf.seek(0)
    return Image.open(buf).convert("RGB").copy()
