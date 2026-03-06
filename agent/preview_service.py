"""WebP preview ZIP generator for layer preview display.

Extracts PNGs from a .sl1 archive, downscales them, encodes as WebP,
and packages into a ZIP for efficient frontend download.
"""

import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image


def generate_preview_zip(
    sl1_path: Path,
    output_path: Path,
    scale: float = 0.25,
    quality: int = 80,
) -> Path:
    """
    Generate a ZIP of downscaled WebP images from an .sl1 archive.

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

    with zipfile.ZipFile(sl1_path, "r") as src_zip:
        png_names = sorted(n for n in src_zip.namelist() if n.endswith(".png"))

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as dst_zip:
            for i, png_name in enumerate(png_names):
                with src_zip.open(png_name) as f:
                    img = Image.open(f)

                    new_w = max(1, int(img.width * scale))
                    new_h = max(1, int(img.height * scale))
                    img = img.resize((new_w, new_h), Image.LANCZOS)

                    webp_buf = BytesIO()
                    img.save(webp_buf, format="WEBP", quality=quality)

                    dst_zip.writestr(f"{i}.webp", webp_buf.getvalue())

    return output_path
