"""WebP preview ZIP generator for layer preview display.

The Python fallback preview line: reads layers from a .sl1 archive, downscales
them, encodes as WebP and packages into a ZIP. Only used when the engine's own
``model_preview.zip`` is absent — a rare but supported state, since a preview
export failure MUST NOT fail an otherwise complete slice.

Two properties are shared with the engine line and MUST stay shared (spec:
slice-preview-export): the downscale ratio comes from ``preview_scale_for()``,
and the filter is a uniform box mean. The ZIP entry naming and the WebP encoding
are *not* shared — that divergence is a documented known difference, and
consumers are required to read the actual entry names and extensions.
"""

import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from PIL import Image

from .preview_scale import preview_scale_for
from .prz_decoder import rle_layer_to_png
from .prz_encoder import sl1_layer_names

# Uniform block average — the exact PIL counterpart of the engine's box mean
# (RasterBase.cpp). NOT bilinear: Pillow does scale the filter support by the
# reduction factor when shrinking, so BILINEAR is antialiased and thin supports
# survive it, but its triangle weighting under-weights features sitting at a
# block edge. slice-preview-export requires box mean of every preview line.
_RESAMPLE_FILTER = Image.BOX


def _process_one_layer(png_data: bytes, quality: int) -> bytes:
    """Resize and encode a single layer to WebP. Runs in thread pool."""
    img = Image.open(BytesIO(png_data))

    # Long side, not width: keeps the ratio consistent with the engine line for
    # portrait rasters too (see preview_scale.preview_scale_for).
    scale_str, _ = preview_scale_for(max(img.width, img.height))
    scale = float(scale_str)

    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))
    img = img.resize((new_w, new_h), _RESAMPLE_FILTER)

    webp_buf = BytesIO()
    img.save(webp_buf, format="WEBP", quality=quality)
    return webp_buf.getvalue()


def _read_layers_as_png(sl1_path: Path) -> list[bytes]:
    """Read every layer of a .sl1 as PNG bytes, whatever its on-disk encoding.

    Enumeration goes through ``sl1_layer_names()`` rather than an extension
    filter: the main slicing path runs with ``SLA_LAYER_RLE=1``, so the archive
    holds ``model#####.rle`` and no PNG at all — and a naive ``.png`` filter
    would also sweep in the thumbnail.

    RLE layers are decoded via the shared ``rle_layer_to_png()`` (the same one
    the layers.zip endpoint uses) rather than a second decode implementation.
    That re-encodes to PNG only for us to decode it again below; the extra round
    trip is accepted on this rare fallback path in exchange for a single decode
    path across the codebase.
    """
    with zipfile.ZipFile(sl1_path, "r") as src_zip:
        names = sl1_layer_names(src_zip.namelist())
        if not names:
            raise ValueError(f"no layer files found in {sl1_path}")

        out: list[bytes] = []
        for name in names:
            if name.endswith(".rle"):
                png = rle_layer_to_png(src_zip, name)
                # Whole-archive semantics, matching _rle_sl1_to_png_zip: a
                # missing resolution invalidates the entire package.
                if png is None:
                    raise ValueError(
                        f"cannot determine layer resolution for RLE->PNG in {sl1_path}"
                    )
                out.append(png)
            else:
                out.append(src_zip.read(name))
        return out


def _is_usable_cache(path: Path) -> bool:
    """A cached archive counts only if it actually holds previews.

    Jobs sliced before the RLE fix may hold an empty preview.zip. Serving it
    would let the defect outlive its fix for every such job, so an empty (or
    unreadable) archive is treated as a cache miss.
    """
    if not path.exists():
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            return bool(zf.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


def generate_preview_zip(
    sl1_path: Path,
    output_path: Path,
    quality: int = 80,
) -> Path:
    """
    Generate a ZIP of downscaled WebP images from an .sl1 archive.

    The downscale ratio is derived per layer from the source dimensions via
    ``preview_scale_for()`` — there is deliberately no caller-supplied scale,
    because that parameter's default was itself a source of divergence from the
    engine line.

    Uses atomic write (temp file + rename) to prevent serving partial files
    when called concurrently from background thread and HTTP endpoint.
    Uses thread pool for parallel image processing.

    Args:
        sl1_path: Path to the .sl1 file (ZIP of RLE or PNG layers).
        output_path: Path for the output preview.zip.
        quality: WebP quality 1-100 (default 80).

    Returns:
        Path to the generated preview.zip.

    Raises:
        ValueError: the source holds no layers, or an RLE layer cannot be
            decoded. An empty archive is never written to ``output_path``.
    """
    if _is_usable_cache(output_path):
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
            if _is_usable_cache(output_path):
                return output_path
            time.sleep(0.1)
        # Timed out — fall through and regenerate
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    # Read every layer up front (sequential I/O on ZIP). Raises before any temp
    # file exists when the source has no layers, so a failed run leaves nothing
    # behind for a later request to pick up.
    png_data_list = _read_layers_as_png(sl1_path)

    try:
        # Process layers in parallel (PIL releases GIL during C-level ops)
        workers = min(8, os.cpu_count() or 4)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_process_one_layer, data, quality)
                for data in png_data_list
            ]
            webp_results = [f.result() for f in futures]

        # Write results to ZIP (sequential)
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_STORED) as dst_zip:
            for i, webp_data in enumerate(webp_results):
                dst_zip.writestr(f"{i}.webp", webp_data)

        # Atomic rename (same filesystem)
        os.replace(str(tmp_path), str(output_path))
    except BaseException:
        # Never leave a partial or empty archive where the cache check or a
        # concurrent waiter would find it.
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return output_path
