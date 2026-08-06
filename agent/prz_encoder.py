"""Pure Python PRZ V3.0 binary encoder.

Ports the PRZ format from Mechado C++ (Slicer.cpp PrzHeader,
PrzLayerContent, LM_SVGRenderer.cpp WritePRZFormat).

All multi-byte integers are big-endian.
Config dict uses the same structure as Mechado default profile JSON
(e.g. sonic_ls_plus.json: Machine, Print, Advanced, Resin, Other sections).

Unit changes (since 2026-05-21):
  - volume / weight / price header fields are written in mm³ (previously mL).
    Downstream readers (frontend / firmware) must be updated accordingly.

Accepted config keys added in fix-prz-output-correctness (2026-05-21):
  Print.Retract Distance              — first-stage retract distance (mm); falsy = Case 4
  Print.Retract Second Distance       — second-stage retract distance (mm); falsy = Case 4
  Print.Bottom Retract Distance       — bottom first-stage retract (mm); falsy = Case 4
  Print.Bottom Retract Second Distance — bottom second-stage retract (mm); falsy = Case 4
  All four keys are read directly by _get_float() and are NOT part of PrzPrintTimingConfig.
  See _resolve_retract_pair() for the 4-case override logic (design.md D2).
"""

import re
import struct
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import PrzPrintTimingConfig, gate_blur

import numpy as np
from PIL import Image

# ---------- Constants ----------

PRZ_VERSION = b"V3.0"
PRZ_TAG = b"\x07\x00\x00\x00DLP\x00"
PRZ_FOOTER_TAG = b"\x00\x00\x00\x07\x00\x00\x00DLP\x00"
PRZ_CRLF = b"\r\n"
PRZ_LAYER_HEADER = 0x55
LAYER_CONTENT_OFFSET = 195477

# 標頭 metadata 常數（design D4）——集中管理，保留未來改 build-time 注入的彈性
SOFTWARE_NAME = "Phrozen DS"
SOFTWARE_VERSION = "0.0.1"   # 產品端版本常數；未來可改 build-time 注入
PRICE_UNIT = "$/L"

PREVIEW_SMALL_SIZE = 116
PREVIEW_LARGE_SIZE = 290

# RLE color types
RLE_BLACK = 0x00
RLE_WHITE = 0xC0
RLE_GRAY = 0x40


# ---------- Helpers ----------

# 層檔命名嚴格比對（design D2）：model#####.rle / model#####.png。
# 只認頂層、5 位零填充序號的層檔，藉此排除子目錄縮圖（thumbnail/thumbnailNNNxNNN.png）
# 與任何非層檔（config.ini / prusaslicer.ini / config.json）污染層數統計。
# 注意：前綴 "model" 綁定固定輸出檔名 output/model.sl1（其 stem 即層檔前綴，見
# fork Format/SL1.cpp export_print 的 project 命名）；若日後改輸出檔名，須同步更新此正則。
_LAYER_NAME_RE = re.compile(r"^model\d{5}\.(rle|png)$")


def sl1_layer_names(names: Iterable[str]) -> list[str]:
    """回傳 .sl1 內的層檔名，作為層數統計 / 單層取用 / PRZ 編碼的單一真值來源。

    行為（design D1 / D2）：
      - 以 `_LAYER_NAME_RE` 嚴格比對 model#####.{rle,png}，排除縮圖與設定檔。
      - 同一 .sl1 內若存在 .rle 層檔則優先採用 .rle（PRZ 快路徑），否則採用 .png。
      - 以檔名 `sorted()` 排序；5 位零填充下字典序即層索引升冪序。
    """
    layer_names = [n for n in names if _LAYER_NAME_RE.match(n)]
    rle_names = sorted(n for n in layer_names if n.endswith(".rle"))
    if rle_names:
        return rle_names
    return sorted(n for n in layer_names if n.endswith(".png"))


def _pack_str(s: str, size: int) -> bytes:
    """Pack a string into a fixed-size field with a guaranteed trailing NUL.

    Defensive packing (design D3) — protects downstream printer firmware that
    reads these fields as C-strings:
      - reserve 1 byte for the NUL terminator (effective content max = size-1),
        so a full-length string can never leave the field without a 0x00 and
        cause strlen()/strcpy() to overrun into adjacent bytes;
      - UTF-8 char-safe truncation: byte-slice to budget, then
        decode(errors="ignore") drops any partial trailing multibyte sequence
        so no half a CJK character is ever emitted;
      - zero-pad to exactly `size`.
    """
    budget = size - 1
    raw = (s or "").encode("utf-8")[:budget]
    safe = raw.decode("utf-8", errors="ignore").encode("utf-8")
    return safe.ljust(size, b"\x00")


def _traverse_dotpath(config: dict, dotpath: str) -> tuple[bool, Any]:
    """Traverse a dotted path through a nested dict.

    Returns (True, value) if the path exists; (False, None) if any segment
    is missing or a non-dict node is encountered mid-path.
    """
    parts = dotpath.split(".")
    val: Any = config
    for part in parts:
        if not isinstance(val, dict) or part not in val:
            return False, None
        val = val[part]
    return True, val


def _get_float(config: dict, dotpath: str, default: float = 0.0) -> float:
    """Get a float from a dotted config path (e.g. 'Print.Exposure Time')."""
    found, val = _traverse_dotpath(config, dotpath)
    if not found or val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _get_float_opt(config: dict, dotpath: str) -> Optional[float]:
    """Get a float from a dotted config path, returning None when absent.

    Unlike _get_float, a value of 0.0 is returned as 0.0 (not treated as
    falsy/missing). Returns None only when the key is genuinely absent or
    the stored value is None. TypeError/ValueError also yield None.
    """
    found, val = _traverse_dotpath(config, dotpath)
    if not found or val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _get_int(config: dict, dotpath: str, default: int = 0) -> int:
    """Get an int from a dotted config path."""
    parts = dotpath.split(".")
    val = config
    for part in parts:
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return default
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _get_str(config: dict, dotpath: str, default: str = "") -> str:
    """Get a string from a dotted config path."""
    parts = dotpath.split(".")
    val = config
    for part in parts:
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return default
    return str(val) if val is not None else default


def _get_list(config: dict, dotpath: str) -> list:
    """Get a list from a dotted config path."""
    parts = dotpath.split(".")
    val = config
    for part in parts:
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return []
    return val if isinstance(val, list) else []


# ---------- Preview Images ----------

def _rgb_to_rgb565_be(image: np.ndarray) -> bytes:
    """Convert RGB image (H, W, 3) uint8 to RGB565 big-endian bytes."""
    r = (image[:, :, 0].astype(np.uint16) >> 3) & 0x1F
    g = (image[:, :, 1].astype(np.uint16) >> 2) & 0x3F
    b = (image[:, :, 2].astype(np.uint16) >> 3) & 0x1F
    rgb565 = (r << 11) | (g << 5) | b
    return rgb565.astype(">u2").tobytes()


def _make_black_preview(size: int) -> bytes:
    """Create a solid black preview image as RGB565 bytes."""
    return b"\x00\x00" * (size * size)


def _resize_preview(img: Image.Image, size: int) -> np.ndarray:
    """Resize image to size*size and return as RGB numpy array."""
    img = img.convert("RGB")
    img = img.resize((size, size), Image.LANCZOS)
    return np.array(img, dtype=np.uint8)


def _preview_rgb_to_rgb565_be(rgb: np.ndarray, target_size: int) -> Optional[bytes]:
    """Convert an arbitrary-size (H, W, 3) uint8 RGB array to RGB565 BE bytes
    sized for the given PRZ preview slot, resizing via PIL Lanczos when needed.
    Returns None on invalid shape/dtype."""
    if rgb is None:
        return None
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        return None
    if rgb.shape[0] != target_size or rgb.shape[1] != target_size:
        rgb = _resize_preview(Image.fromarray(rgb, mode="RGB"), target_size)
    return _rgb_to_rgb565_be(rgb)


# ---------- RLE Encoding ----------

def _encode_run(value: int, run_len: int) -> bytes:
    """Encode a single RLE run into bytes."""
    if value == 0:
        color_type = RLE_BLACK
    elif value == 255:
        color_type = RLE_WHITE
    else:
        color_type = RLE_GRAY

    if run_len < 16:
        byte_count_bits = 0x00
        extra_count = 0
    elif run_len < 4096:
        byte_count_bits = 0x10
        extra_count = 1
    elif run_len < 1048576:
        byte_count_bits = 0x20
        extra_count = 2
    else:
        byte_count_bits = 0x30
        extra_count = 3

    first_byte = color_type | byte_count_bits | (run_len & 0x0F)

    if color_type == RLE_GRAY:
        if extra_count > 0:
            return bytes([first_byte, value]) + (run_len >> 4).to_bytes(extra_count, "big")
        return bytes([first_byte, value])
    else:
        if extra_count > 0:
            return bytes([first_byte]) + (run_len >> 4).to_bytes(extra_count, "big")
        return bytes([first_byte])


def _rle_encode_layer(gray_pixels: np.ndarray) -> bytes:
    """
    RLE-encode a grayscale layer image (row-by-row, left-to-right).

    Fully vectorized with numpy — no Python loop over runs.
    Layer starts with 0x55 header. Ends with checksum = (~sum) & 0xFF.
    """
    flat = gray_pixels.ravel()
    n = len(flat)

    if n == 0:
        out = bytearray([PRZ_LAYER_HEADER])
        out.append((~PRZ_LAYER_HEADER) & 0xFF)
        return bytes(out)

    # Vectorized run-length detection
    diff_mask = flat[1:] != flat[:-1]
    change_indices = np.flatnonzero(diff_mask)

    run_starts = np.empty(len(change_indices) + 1, dtype=np.intp)
    run_starts[0] = 0
    run_starts[1:] = change_indices + 1

    run_ends = np.empty_like(run_starts)
    run_ends[:-1] = run_starts[1:]
    run_ends[-1] = n

    run_lengths = (run_ends - run_starts).astype(np.int64)
    run_values = flat[run_starts]
    num_runs = len(run_values)

    # Vectorized color type classification
    color_types = np.full(num_runs, RLE_GRAY, dtype=np.uint8)
    color_types[run_values == 0] = RLE_BLACK
    color_types[run_values == 255] = RLE_WHITE
    is_gray = color_types == RLE_GRAY

    # Vectorized byte count bits and extra count
    byte_count_bits = np.zeros(num_runs, dtype=np.uint8)
    extra_counts = np.zeros(num_runs, dtype=np.int32)

    mask_16 = run_lengths >= 16
    mask_4096 = run_lengths >= 4096
    mask_1m = run_lengths >= 1048576

    byte_count_bits[mask_16] = 0x10
    extra_counts[mask_16] = 1
    byte_count_bits[mask_4096] = 0x20
    extra_counts[mask_4096] = 2
    byte_count_bits[mask_1m] = 0x30
    extra_counts[mask_1m] = 3

    first_bytes = color_types | byte_count_bits | (run_lengths & 0x0F).astype(np.uint8)

    # Pre-compute shifted lengths for extra bytes
    shifted = (run_lengths >> 4).astype(np.int64)

    # Calculate total output size to pre-allocate
    # Each run: 1 (first_byte) + is_gray (gray value byte) + extra_counts
    total_size = 1 + int(np.sum(1 + is_gray.astype(np.int32) + extra_counts)) + 1  # header + runs + checksum

    out = bytearray(total_size)
    out[0] = PRZ_LAYER_HEADER
    pos = 1

    # Batch encode — use numpy arrays but write sequentially
    # (sequential write is unavoidable for variable-length encoding, but inner work is minimal)
    fb_arr = first_bytes
    rv_arr = run_values
    ec_arr = extra_counts
    sh_arr = shifted
    ig_arr = is_gray

    for i in range(num_runs):
        out[pos] = fb_arr[i]
        pos += 1
        if ig_arr[i]:
            out[pos] = rv_arr[i]
            pos += 1
        ec = ec_arr[i]
        if ec > 0:
            s = int(sh_arr[i])
            if ec == 1:
                out[pos] = s & 0xFF
                pos += 1
            elif ec == 2:
                out[pos] = (s >> 8) & 0xFF
                out[pos + 1] = s & 0xFF
                pos += 2
            else:
                out[pos] = (s >> 16) & 0xFF
                out[pos + 1] = (s >> 8) & 0xFF
                out[pos + 2] = s & 0xFF
                pos += 3

    # Checksum — excludes the 0x55 header byte (matches C++ encoder)
    checksum = (~sum(out[1:pos])) & 0xFF
    out[pos] = checksum
    pos += 1

    return bytes(out[:pos])


# ---------- Timing Resolution ----------

def _resolve_timing_values(
    timing: PrzPrintTimingConfig, is_bottom: bool
) -> tuple:
    """Return (light_off_time, before_lift_time, after_lift_time, after_retract_time).

    Enforces delay_mode exclusivity:
      mode 0 (lightOff)  — light_off_delay written, all rest times forced to 0.0
      mode 1 (waitTime)  — light_off_time forced to 0.0, rest times written
    """
    if timing.exposure_delay_mode == 0:
        return (timing.light_off_delay, 0.0, 0.0, 0.0)
    # mode == 1 (waitTime)
    if is_bottom:
        return (
            0.0,
            timing.bottom_rest_before_lift,
            timing.bottom_rest_after_lift,
            timing.bottom_rest_after_retract,
        )
    return (
        0.0,
        timing.rest_before_lift,
        timing.rest_after_lift,
        timing.rest_after_retract,
    )



def _resolve_retract_pair(
    config: dict,
    dist_key: str,
    drop2_key: str,
    lift: float,
    lift2: float,
) -> tuple[float, float]:
    """Return (retract_distance, retract_second_distance).

    key 存在（含 0.0）視為已傳入；key 缺席或值為 None 視為未傳入。
    4-case override 邏輯（詳見 design.md D2 真值表）：
      Case 1 (只傳 drop2)  : (max(0, lift+lift2-drop2), drop2)
      Case 2 (只傳 dist)   : (dist, 0.0)
      Case 3 (兩者皆傳)    : (dist, drop2)  — 兩值原樣保留
      Case 4 (兩者皆未傳) : (0.0, lift+lift2)                 — 單段下降
    """
    dist  = _get_float_opt(config, dist_key)
    drop2 = _get_float_opt(config, drop2_key)
    if dist is not None and drop2 is not None:  # Case 3
        return dist, drop2
    if dist is not None:                        # Case 2
        return dist, 0.0
    if drop2 is not None:                       # Case 1
        return max(0.0, lift + lift2 - drop2), drop2
    return 0.0, lift + lift2                    # Case 4


def _to_mm_per_sec(v_mm_per_min: float) -> float:
    """Convert mm/min speed (UI/config convention) to mm/s for physics formulas (D5 unit fix)."""
    return v_mm_per_min / 60.0 if v_mm_per_min else 0.0


def _compute_print_time(
    config: dict,
    total_layers: int,
    timing: PrzPrintTimingConfig,
) -> float:
    """Compute total print time in seconds from PRZ-aware parameters.

    Phase 1: constant-speed model (÷60 unit conversion mandatory — see design.md D5).
    """
    bottom_count = _get_int(config, "Print.Bottom Layer Count", default=5)
    transition_count = _get_int(config, "Print.Transition Layer Count", default=5)
    bottom_exp = _get_float(config, "Print.Bottom Exposure Time", default=35.0)
    normal_exp = _get_float(config, "Print.Exposure Time", default=2.5)

    def motion_time(d: float, v_mm_per_min: float) -> float:
        """d in mm, v in mm/min. Converts to mm/s internally. Returns seconds."""
        v = _to_mm_per_sec(v_mm_per_min)
        return d / v if d > 0 and v > 0 else 0.0

    total = 0.0
    for layer_idx in range(total_layers):
        is_bottom = layer_idx < bottom_count
        vals = _resolve_timing_values(timing, is_bottom=is_bottom)

        # exposure with transition ramp (mirrors _write_layer_definition logic)
        if is_bottom:
            exposure = bottom_exp
        else:
            transition_idx = layer_idx - bottom_count
            if 0 <= transition_idx < transition_count:
                exposure = bottom_exp + (normal_exp - bottom_exp) / (1.0 + transition_count) * (transition_idx + 1.0)
            else:
                exposure = normal_exp

        if is_bottom:
            lift  = _get_float(config, "Print.Bottom Lifting Distance", default=8.0)
            lift2 = _get_float(config, "Print.Bottom Lifting Second Distance")
            lift_v  = _get_float(config, "Print.Bottom Lifting Speed", default=50.0)
            lift2_v = _get_float(config, "Print.Bottom Lifting Second Speed")
            retract, drop2 = _resolve_retract_pair(
                config, "Print.Bottom Retract Distance",
                "Print.Bottom Retract Second Distance", lift, lift2,
            )
            retract_v = _get_float(config, "Print.Bottom Retract Speed", default=100.0)
            drop2_v   = _get_float(config, "Print.Bottom Retract Second Speed")
        else:
            lift  = _get_float(config, "Print.Lifting Distance", default=7.0)
            lift2 = _get_float(config, "Print.Lifting Second Distance")
            lift_v  = _get_float(config, "Print.Lifting Speed", default=50.0)
            lift2_v = _get_float(config, "Print.Lifting Second Speed")
            retract, drop2 = _resolve_retract_pair(
                config, "Print.Retract Distance",
                "Print.Retract Second Distance", lift, lift2,
            )
            retract_v = _get_float(config, "Print.Normal Retract Speed", default=100.0)
            drop2_v   = _get_float(config, "Print.Normal Retract Second Speed")

        total += (
            exposure
            + vals[0]                           # light_off_time
            + vals[1]                           # before_lift_time
            + motion_time(lift,    lift_v)
            + motion_time(lift2,   lift2_v)
            + vals[2]                           # after_lift_time
            + motion_time(retract, retract_v)
            + motion_time(drop2,   drop2_v)
            + vals[3]                           # after_retract_time
        )

    return total


# ---------- Header ----------

def _write_header(
    config: dict,
    total_layers: int,
    timing: PrzPrintTimingConfig,
    estimated_print_time: float = 0,  # deprecated: ignored; time is computed via _compute_print_time()
    resin_volume_mm3: float = 0,
    preview_small: Optional[bytes] = None,
    preview_large: Optional[bytes] = None,
) -> bytes:
    """Write the PRZ V3.0 header (exactly 195477 bytes)."""
    buf = BytesIO()

    # Version (4B)
    buf.write(PRZ_VERSION)

    # Tag (8B)
    buf.write(PRZ_TAG)

    # Software (32B) — 產品識別常數（design D4）
    buf.write(_pack_str(SOFTWARE_NAME, 32))

    # Software Version (24B) — 版本號常數（design D4）
    buf.write(_pack_str(SOFTWARE_VERSION, 24))

    # File Time (24B)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    buf.write(_pack_str(now, 24))

    # Printer Name (32B)
    buf.write(_pack_str(_get_str(config, "Machine.Machine Name"), 32))

    # Printer Type (32B)
    buf.write(_pack_str(_get_str(config, "Machine.machine_type"), 32))

    # Profile Name (32B) — 樹脂名稱（design D4 契約：讀 Other.profile_name，
    # 不再誤用 Machine.Machine Name）；缺漏時 _get_str 回空字串 → 降級補 NUL
    buf.write(_pack_str(_get_str(config, "Other.profile_name"), 32))

    # AA Level (2B short BE)
    buf.write(struct.pack(">H", _get_int(config, "Advanced.Anti-aliasing Level")))

    # Grey Level (2B short BE)
    buf.write(struct.pack(">H", _get_int(config, "Advanced.Grey Level")))

    # Blur Level (2B short BE) — 受 `Advanced."Image Blur"` 開關閘控，與切片端共用
    # models.gate_blur 這個唯一真值來源。少了閘控，使用者關掉 blur 時層圖會以
    # blur = 0 光柵化，header 卻仍宣稱 `Image Blur Pixel` 的強度，PRZ 的自述與它
    # 自己夾帶的層圖互相矛盾。開關讀原始值而非走 _get_int：後者會把「鍵不存在」
    # 與「值為 false」一起壓成 0，正好抹掉閘控要區分的兩態。
    _, blur_enabled = _traverse_dotpath(config, "Advanced.Image Blur")
    buf.write(struct.pack(">H", int(gate_blur(
        blur_enabled, _get_int(config, "Advanced.Image Blur Pixel")))))

    # Preview 116x116 (26912B RGB565 BE)
    expected_small = PREVIEW_SMALL_SIZE * PREVIEW_SMALL_SIZE * 2
    if preview_small and len(preview_small) == expected_small:
        buf.write(preview_small)
    else:
        buf.write(_make_black_preview(PREVIEW_SMALL_SIZE))

    # CRLF
    buf.write(PRZ_CRLF)

    # Preview 290x290 (168200B RGB565 BE)
    expected_large = PREVIEW_LARGE_SIZE * PREVIEW_LARGE_SIZE * 2
    if preview_large and len(preview_large) == expected_large:
        buf.write(preview_large)
    else:
        buf.write(_make_black_preview(PREVIEW_LARGE_SIZE))

    # CRLF
    buf.write(PRZ_CRLF)

    # Total Layers (4B int BE)
    buf.write(struct.pack(">I", total_layers))

    # X/Y Resolution (2B short BE each)
    image_size = _get_list(config, "Machine.image_size")
    x_res = int(image_size[0]) if len(image_size) > 0 else 2560
    y_res = int(image_size[1]) if len(image_size) > 1 else 1440
    buf.write(struct.pack(">H", x_res))
    buf.write(struct.pack(">H", y_res))

    # X Mirror (1B) - inverted from config Mirror
    mirror = _get_int(config, "Machine.Mirror")
    buf.write(struct.pack("B", 0 if mirror else 1))

    # Y Mirror (1B) - always 0
    buf.write(struct.pack("B", 0))

    # Platform dimensions (3 x 4B float BE)
    bed_size = _get_list(config, "Machine.bed_size")
    platform_x = float(bed_size[2]) if len(bed_size) > 2 else 120.0
    platform_y = float(bed_size[3]) if len(bed_size) > 3 else 68.0
    platform_z = _get_float(config, "Machine.machine_z", default=175.0)
    buf.write(struct.pack(">f", platform_x))
    buf.write(struct.pack(">f", platform_y))
    buf.write(struct.pack(">f", platform_z))

    # Layer Thickness (4B float BE)
    buf.write(struct.pack(">f", _get_float(config, "Print.Layer Height", default=0.05)))

    # Exposure Time (4B float BE)
    buf.write(struct.pack(">f", _get_float(config, "Print.Exposure Time", default=2.5)))

    bottom = _resolve_timing_values(timing, is_bottom=True)
    normal = _resolve_timing_values(timing, is_bottom=False)

    # Delay Mode (1B)
    buf.write(struct.pack("B", timing.exposure_delay_mode))

    # Turn Off Time (4B float BE) — bottom[0] == normal[0] by design
    buf.write(struct.pack(">f", bottom[0]))

    # Bottom Before Lift Time (4B float BE)
    buf.write(struct.pack(">f", bottom[1]))

    # Bottom After Lift Time (4B float BE)
    buf.write(struct.pack(">f", bottom[2]))

    # Bottom After Retract Time (4B float BE)
    buf.write(struct.pack(">f", bottom[3]))

    # Before Lift Time (4B float BE)
    buf.write(struct.pack(">f", normal[1]))

    # After Lift Time (4B float BE)
    buf.write(struct.pack(">f", normal[2]))

    # After Retract Time (4B float BE)
    buf.write(struct.pack(">f", normal[3]))

    # Bottom Exposure Time (4B float BE)
    buf.write(struct.pack(">f", _get_float(config, "Print.Bottom Exposure Time", default=35.0)))

    # Bottom Layers (4B int BE)
    buf.write(struct.pack(">I", _get_int(config, "Print.Bottom Layer Count", default=5)))

    # 16 lift/retract fields (4B float BE each = 64B)
    # Order matches C++ PrzHeader: bottom_lift, bottom_lift_speed, normal_lift, normal_lift_speed,
    # bottom_retract(CALC), bottom_retract_speed, normal_retract(CALC), normal_retract_speed,
    # then all second-stage fields in same order.
    bottom_lift = _get_float(config, "Print.Bottom Lifting Distance", default=8.0)
    bottom_lift2 = _get_float(config, "Print.Bottom Lifting Second Distance")
    normal_lift = _get_float(config, "Print.Lifting Distance", default=7.0)
    normal_lift2 = _get_float(config, "Print.Lifting Second Distance")

    bottom_retract, bottom_drop2 = _resolve_retract_pair(
        config, "Print.Bottom Retract Distance", "Print.Bottom Retract Second Distance",
        bottom_lift, bottom_lift2,
    )
    normal_retract, normal_drop2 = _resolve_retract_pair(
        config, "Print.Retract Distance", "Print.Retract Second Distance",
        normal_lift, normal_lift2,
    )

    buf.write(struct.pack(">f", bottom_lift))
    buf.write(struct.pack(">f", _get_float(config, "Print.Bottom Lifting Speed", default=50.0)))
    buf.write(struct.pack(">f", normal_lift))
    buf.write(struct.pack(">f", _get_float(config, "Print.Lifting Speed", default=50.0)))
    buf.write(struct.pack(">f", bottom_retract))
    buf.write(struct.pack(">f", _get_float(config, "Print.Bottom Retract Speed", default=100.0)))
    buf.write(struct.pack(">f", normal_retract))
    buf.write(struct.pack(">f", _get_float(config, "Print.Normal Retract Speed", default=100.0)))
    buf.write(struct.pack(">f", bottom_lift2))
    buf.write(struct.pack(">f", _get_float(config, "Print.Bottom Lifting Second Speed")))
    buf.write(struct.pack(">f", normal_lift2))
    buf.write(struct.pack(">f", _get_float(config, "Print.Lifting Second Speed")))
    buf.write(struct.pack(">f", bottom_drop2))
    buf.write(struct.pack(">f", _get_float(config, "Print.Bottom Retract Second Speed")))
    buf.write(struct.pack(">f", normal_drop2))
    buf.write(struct.pack(">f", _get_float(config, "Print.Normal Retract Second Speed")))

    # Bottom Light PWM (2B short BE)
    buf.write(struct.pack(">H", _get_int(config, "Advanced.Bottom Light PWM", default=255)))

    # Normal Light PWM (2B short BE)
    buf.write(struct.pack(">H", _get_int(config, "Advanced.Light PWM", default=255)))

    # Advance Mode (1B) = 1
    buf.write(struct.pack("B", 1))

    # Print Times (4B int BE)
    print_time = _compute_print_time(config, total_layers, timing)
    buf.write(struct.pack(">I", int(print_time)))

    # Volume (4B float BE) — unit: mm³ (since 2026-05-21; formerly mL)
    volume = resin_volume_mm3 or _get_float(config, "Other.volume")
    buf.write(struct.pack(">f", volume))

    # TODO(tech-debt): per-resin-density —— 密度/單價目前取自印表機 default profile 的
    # Resin 區塊（per-printer 粒度），未來應下沉至 resin_profiles 做到 per-resin 精度。
    # Weight (4B float BE) — 由 volume × 密度 計算（design D2）；密度缺漏/為 0 → 降級寫 volume
    density = _get_float(config, "Resin.Resin Density")
    weight = (volume / 1000.0) * density if density else volume
    buf.write(struct.pack(">f", weight))

    # Price (4B float BE) — 由 volume × 單價 計算（design D2）；單價缺漏/為 0 → 降級寫 volume
    cost = _get_float(config, "Resin.Resin Cost")
    price = (volume / 1_000_000.0) * cost if cost else volume
    buf.write(struct.pack(">f", price))

    # Price Unit (8B) — 價格單位常數（design D4）
    buf.write(_pack_str(PRICE_UNIT, 8))

    # Layer Content Offset (4B int BE)
    buf.write(struct.pack(">I", LAYER_CONTENT_OFFSET))

    # Grayscale Level (1B) = 1 (8-bit)
    buf.write(struct.pack("B", 1))

    # Transition Layers (2B short BE)
    buf.write(struct.pack(">H", _get_int(config, "Print.Transition Layer Count", default=5)))

    header = buf.getvalue()
    if len(header) != LAYER_CONTENT_OFFSET:
        raise ValueError(
            f"PRZ header size mismatch: got {len(header)}, expected {LAYER_CONTENT_OFFSET}"
        )

    return header


# ---------- Per-Layer Definition ----------

def _write_layer_definition(
    config: dict, layer_idx: int, total_layers: int, timing: PrzPrintTimingConfig
) -> bytes:
    """Write per-layer definition block (matches C++ PrzLayerContent exactly)."""
    buf = BytesIO()

    bottom_layers = _get_int(config, "Print.Bottom Layer Count", default=5)
    is_bottom = layer_idx < bottom_layers
    layer_height = _get_float(config, "Print.Layer Height", default=0.05)

    # PauseFlag (2B short BE) — always 0
    buf.write(struct.pack(">H", 0))

    # PausePositionZ (4B float BE) — same as layer Z position
    # Layer 0 starts at layer_height (1-based Z), matching C++ PrzLayerContent
    z_pos = layer_height * (layer_idx + 1)
    buf.write(struct.pack(">f", z_pos))

    # LayerPositionZ (4B float BE)
    buf.write(struct.pack(">f", z_pos))

    # Exposure time (4B float BE) — with transition layer linear interpolation
    if is_bottom:
        exposure = _get_float(config, "Print.Bottom Exposure Time", default=35.0)
    else:
        transition_count = _get_int(config, "Print.Transition Layer Count", default=5)
        transition_idx = layer_idx - bottom_layers
        if 0 <= transition_idx < transition_count:
            # C++ always uses linear interpolation (no decrement check)
            bottom_exp = _get_float(config, "Print.Bottom Exposure Time", default=35.0)
            normal_exp = _get_float(config, "Print.Exposure Time", default=2.5)
            exposure = bottom_exp + (normal_exp - bottom_exp) / (1.0 + transition_count) * (transition_idx + 1.0)
        else:
            exposure = _get_float(config, "Print.Exposure Time", default=2.5)
    buf.write(struct.pack(">f", exposure))

    vals = _resolve_timing_values(timing, is_bottom=is_bottom)
    buf.write(struct.pack(">f", vals[0]))  # light_off_time
    buf.write(struct.pack(">f", vals[1]))  # before_lift_time
    buf.write(struct.pack(">f", vals[2]))  # after_lift_time
    buf.write(struct.pack(">f", vals[3]))  # after_retract_time

    # 8 lift/retract params (matches C++ PrzLayerContent order):
    # LiftDist, LiftSpeed, LiftSecondDist, LiftSecondSpeed,
    # RetractDist(CALC), RetractSpeed, RetractSecondDist, RetractSecondSpeed
    if is_bottom:
        lift = _get_float(config, "Print.Bottom Lifting Distance", default=8.0)
        lift2 = _get_float(config, "Print.Bottom Lifting Second Distance")
        retract, drop2 = _resolve_retract_pair(
            config, "Print.Bottom Retract Distance", "Print.Bottom Retract Second Distance",
            lift, lift2,
        )
        buf.write(struct.pack(">f", lift))
        buf.write(struct.pack(">f", _get_float(config, "Print.Bottom Lifting Speed", default=50.0)))
        buf.write(struct.pack(">f", lift2))
        buf.write(struct.pack(">f", _get_float(config, "Print.Bottom Lifting Second Speed")))
        buf.write(struct.pack(">f", retract))
        buf.write(struct.pack(">f", _get_float(config, "Print.Bottom Retract Speed", default=100.0)))
        buf.write(struct.pack(">f", drop2))
        buf.write(struct.pack(">f", _get_float(config, "Print.Bottom Retract Second Speed")))
    else:
        lift = _get_float(config, "Print.Lifting Distance", default=7.0)
        lift2 = _get_float(config, "Print.Lifting Second Distance")
        retract, drop2 = _resolve_retract_pair(
            config, "Print.Retract Distance", "Print.Retract Second Distance",
            lift, lift2,
        )
        buf.write(struct.pack(">f", lift))
        buf.write(struct.pack(">f", _get_float(config, "Print.Lifting Speed", default=50.0)))
        buf.write(struct.pack(">f", lift2))
        buf.write(struct.pack(">f", _get_float(config, "Print.Lifting Second Speed")))
        buf.write(struct.pack(">f", retract))
        buf.write(struct.pack(">f", _get_float(config, "Print.Normal Retract Speed", default=100.0)))
        buf.write(struct.pack(">f", drop2))
        buf.write(struct.pack(">f", _get_float(config, "Print.Normal Retract Second Speed")))

    # Light PWM (2B short BE) — C++ defaults to 0 if key not found
    if is_bottom:
        pwm = _get_int(config, "Advanced.Bottom Light PWM", default=0)
    else:
        pwm = _get_int(config, "Advanced.Light PWM", default=0)
    buf.write(struct.pack(">H", pwm))

    return buf.getvalue()


# ---------- Main Encoder ----------

def encode_prz(
    config: dict,
    sl1_path: Path,
    timing: PrzPrintTimingConfig,
    estimated_print_time: float = 0,  # deprecated: ignored; time is computed via _compute_print_time()
    resin_volume_mm3: float = 0,
    preview_small_rgb: Optional[np.ndarray] = None,
    preview_large_rgb: Optional[np.ndarray] = None,
) -> bytes:
    """
    Encode a PRZ V3.0 binary from a config dict and .sl1 layer archive.

    Args:
        config: Mechado-format config dict (same structure as default profile JSON).
        sl1_path: Path to the .sl1 ZIP file containing PNG layers.
        estimated_print_time: Deprecated. Ignored; print time is computed via _compute_print_time().
        resin_volume_mm3: Resin volume in mm³ (from slicing metadata; callers must convert mL × 1000).

    Returns:
        Complete PRZ binary data as bytes.
    """
    # Count layers via the single source of truth (sl1_layer_names). encode_prz
    # assumes PNG layers (it PNG-decodes each entry below); on a PNG-mode .sl1
    # this selects the same set as the old endswith(".png") filter.
    with zipfile.ZipFile(sl1_path, "r") as zf:
        png_names = sl1_layer_names(zf.namelist())

    total_layers = len(png_names)

    # Write header
    header = _write_header(
        config, total_layers, timing,
        resin_volume_mm3=resin_volume_mm3,
        preview_small=_preview_rgb_to_rgb565_be(preview_small_rgb, PREVIEW_SMALL_SIZE),
        preview_large=_preview_rgb_to_rgb565_be(preview_large_rgb, PREVIEW_LARGE_SIZE),
    )

    output = BytesIO()
    output.write(header)

    # Write each layer
    with zipfile.ZipFile(sl1_path, "r") as zf:
        for layer_idx, png_name in enumerate(png_names):
            # Layer definition
            output.write(_write_layer_definition(config, layer_idx, total_layers, timing))
            output.write(PRZ_CRLF)

            # Read PNG and RLE encode
            with zf.open(png_name) as f:
                img = Image.open(f)
                gray = np.array(img.convert("L"), dtype=np.uint8)

            rle_data = _rle_encode_layer(gray)

            # Layer Point Num (4B int BE) = byte count of RLE data
            output.write(struct.pack(">I", len(rle_data)))

            # RLE data
            output.write(rle_data)

            # CRLF
            output.write(PRZ_CRLF)

    # Footer
    output.write(PRZ_FOOTER_TAG)

    return output.getvalue()


def _decode_and_rle(png_bytes: bytes) -> bytes:
    """Decode PNG bytes to grayscale and RLE-encode. Used by parallel encoder."""
    img = Image.open(BytesIO(png_bytes))
    gray = np.array(img.convert("L"), dtype=np.uint8)
    return _rle_encode_layer(gray)


def encode_prz_streaming(
    config: dict,
    sl1_path: Path,
    timing: PrzPrintTimingConfig,
    estimated_print_time: float = 0,  # deprecated: ignored; time is computed via _compute_print_time()
    resin_volume_mm3: float = 0,
    preview_small_rgb: Optional[np.ndarray] = None,
    preview_large_rgb: Optional[np.ndarray] = None,
):
    """
    Generator that yields PRZ chunks for streaming response.

    Uses ThreadPoolExecutor to parallelize PNG decode + RLE encode
    while maintaining sequential output order.
    """
    with zipfile.ZipFile(sl1_path, "r") as zf:
        names = zf.namelist()

    # [layer-rle] Enumerate layer files via the single source of truth
    # (sl1_layer_names): .rle takes priority over .png. When .rle layers are
    # present we use them directly — skip the PNG decode + re-RLE round-trip;
    # otherwise fall back to the PNG decode path for standard sl1 archives.
    layer_names = sl1_layer_names(names)
    is_rle = bool(layer_names) and layer_names[0].endswith(".rle")

    total_layers = len(layer_names)

    # Yield header
    yield _write_header(
        config, total_layers, timing,
        resin_volume_mm3=resin_volume_mm3,
        preview_small=_preview_rgb_to_rgb565_be(preview_small_rgb, PREVIEW_SMALL_SIZE),
        preview_large=_preview_rgb_to_rgb565_be(preview_large_rgb, PREVIEW_LARGE_SIZE),
    )

    # Read all layers from ZIP first (ZIP is sequential I/O, fast)
    layer_data_list = []
    with zipfile.ZipFile(sl1_path, "r") as zf:
        for name in layer_names:
            layer_data_list.append(zf.read(name))

    if is_rle:
        # Already RLE — use the bytes verbatim, no decode/encode.
        rle_futures = layer_data_list
    else:
        # Parallel PNG decode + RLE encode (ProcessPool to bypass GIL)
        from concurrent.futures import ProcessPoolExecutor
        import os
        num_workers = min(os.cpu_count() or 4, 8)
        with ProcessPoolExecutor(max_workers=num_workers) as pool:
            rle_futures = list(pool.map(_decode_and_rle, layer_data_list, chunksize=32))

    # Yield each layer (sequential, must be in order)
    for layer_idx, rle_data in enumerate(rle_futures):
        layer_buf = BytesIO()

        layer_buf.write(_write_layer_definition(config, layer_idx, total_layers, timing))
        layer_buf.write(PRZ_CRLF)

        layer_buf.write(struct.pack(">I", len(rle_data)))
        layer_buf.write(rle_data)
        layer_buf.write(PRZ_CRLF)

        yield layer_buf.getvalue()

    # Yield footer
    yield PRZ_FOOTER_TAG
