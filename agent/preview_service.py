"""WebP preview ZIP generator for layer preview display.

Extracts PNGs from a .sl1 archive, downscales them, encodes as WebP,
and packages into a ZIP for efficient frontend download.
"""

import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from PIL import Image


def _process_one_layer(png_data: bytes, scale: float, quality: int) -> bytes:
    """Resize and encode a single PNG layer to WebP. Runs in thread pool."""
    img = Image.open(BytesIO(png_data))
    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))
    img = img.resize((new_w, new_h), Image.BILINEAR)

    webp_buf = BytesIO()
    img.save(webp_buf, format="WEBP", quality=quality)
    return webp_buf.getvalue()


def generate_preview_zip(
    sl1_path: Path,
    output_path: Path,
    scale: float = 0.25,
    quality: int = 80,
) -> Path:
    """
    Generate a ZIP of downscaled WebP images from an .sl1 archive.

    Uses atomic write (temp file + rename) to prevent serving partial files
    when called concurrently from background thread and HTTP endpoint.
    Uses thread pool for parallel image processing.

    Args:
        sl1_path: Path to the .sl1 file (ZIP of PNGs).
        output_path: Path for the output preview.zip.
        scale: Scale factor for downscaling (default 0.25).
        quality: WebP quality 1-100 (default 80).

    Returns:
        Path to the generated preview.zip.
    """
    if output_path.exists():
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first, then atomically rename to prevent
    # serving a partially-written ZIP when background thread and
    # HTTP endpoint race.
    tmp_path = output_path.with_suffix(".zip.tmp")

    # Another thread/process is already generating — wait for it
    if tmp_path.exists():
        import time
        for _ in range(600):  # wait up to 60 seconds
            if output_path.exists():
                return output_path
            time.sleep(0.1)
        # Timed out — fall through and regenerate
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    # Read all PNG data from .sl1 first (sequential I/O on ZIP)
    with zipfile.ZipFile(sl1_path, "r") as src_zip:
        png_names = sorted(n for n in src_zip.namelist() if n.endswith(".png"))
        png_data_list = [src_zip.read(name) for name in png_names]

    # Process layers in parallel (PIL releases GIL during C-level ops)
    workers = min(8, os.cpu_count() or 4)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_process_one_layer, data, scale, quality)
            for data in png_data_list
        ]
        webp_results = [f.result() for f in futures]

    # Write results to ZIP (sequential)
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as dst_zip:
        for i, webp_data in enumerate(webp_results):
            dst_zip.writestr(f"{i}.webp", webp_data)

    # Atomic rename (same filesystem)
    os.replace(str(tmp_path), str(output_path))

    return output_path
