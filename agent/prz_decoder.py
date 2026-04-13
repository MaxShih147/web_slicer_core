"""Pure Python PRZ V3.0 binary decoder.

Mirrors the encoding logic in prz_encoder.py — all offsets and field order
are derived from prz_encoder.py's _write_header() and _write_layer_definition().

All multi-byte integers are big-endian.
"""

import struct
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# ---------- Constants (mirrored from prz_encoder.py) ----------

PRZ_VERSION = b"V3.0"
PRZ_TAG = b"\x07\x00\x00\x00DLP\x00"
PRZ_CRLF = b"\r\n"
PRZ_LAYER_HEADER = 0x55
LAYER_CONTENT_OFFSET = 195_477

PREVIEW_SMALL_SIZE = 116
PREVIEW_LARGE_SIZE = 290

RLE_BLACK = 0x00
RLE_WHITE = 0xC0
RLE_GRAY = 0x40
RLE_COLOR_MASK = 0xC0
RLE_BYTE_COUNT_MASK = 0x30
RLE_LEN_LOW_MASK = 0x0F


# ---------- Dataclasses ----------

@dataclass
class PrzHeader:
    """All fields parsed from the PRZ V3.0 header (195,477 bytes)."""

    # Identification
    version: str                    # "V3.0"
    software: str                   # always empty in current encoder
    software_version: str           # always empty in current encoder
    file_time: str                  # "YYYY-MM-DD HH:MM:SS"

    # Machine info
    printer_name: str               # Machine.Machine Name
    printer_type: str               # Machine.machine_type
    profile_name: str               # same as printer_name

    # Image quality
    aa_level: int                   # Advanced.Anti-aliasing Level (uint16 BE)
    grey_level: int                 # Advanced.Grey Level (uint16 BE)
    blur_level: int                 # Advanced.Image Blur Pixel (uint16 BE)

    # Resolution & geometry
    total_layers: int               # uint32 BE
    x_res: int                      # Machine.image_size[0]  (uint16 BE)
    y_res: int                      # Machine.image_size[1]  (uint16 BE)
    x_mirror: int                   # 0 = mirrored, 1 = normal (inverted from config)
    y_mirror: int                   # always 0
    platform_x: float               # Machine.bed_size[2]
    platform_y: float               # Machine.bed_size[3]
    platform_z: float               # Machine.machine_z

    # Print parameters
    layer_height: float             # Print.Layer Height (mm)
    exposure_time: float            # Print.Exposure Time (s)
    delay_mode: int                 # always 1
    light_off_time: float           # Print.Light-off Delay (s)
    bottom_before_lift_time: float  # always 0.0
    bottom_after_lift_time: float   # always 0.0
    bottom_after_retract_time: float  # Print.Rest Time After Retract
    before_lift_time: float         # always 0.0
    after_lift_time: float          # always 0.0
    after_retract_time: float       # Print.Rest Time After Retract

    # Bottom layer parameters
    bottom_exposure_time: float     # Print.Bottom Exposure Time (s)
    bottom_layers: int              # Print.Bottom Layer Count (uint32 BE)

    # Lift / retract parameters (header-level defaults)
    bottom_lift_distance: float     # Print.Bottom Lifting Distance (mm)
    bottom_lift_speed: float        # Print.Bottom Lifting Speed (mm/min)
    normal_lift_distance: float     # Print.Lifting Distance (mm)
    normal_lift_speed: float        # Print.Lifting Speed (mm/min)
    bottom_retract_distance: float  # CALCULATED
    bottom_retract_speed: float     # Print.Bottom Retract Speed (mm/min)
    normal_retract_distance: float  # CALCULATED
    normal_retract_speed: float     # Print.Normal Retract Speed (mm/min)
    bottom_lift2_distance: float    # Print.Bottom Lifting Second Distance
    bottom_lift2_speed: float       # Print.Bottom Lifting Second Speed
    normal_lift2_distance: float    # Print.Lifting Second Distance
    normal_lift2_speed: float       # Print.Lifting Second Speed
    bottom_drop2_distance: float    # Print.Bottom Retract Second Distance
    bottom_drop2_speed: float       # Print.Bottom Retract Second Speed
    normal_drop2_distance: float    # Print.Retract Second Distance
    normal_drop2_speed: float       # Print.Normal Retract Second Speed

    # PWM
    bottom_light_pwm: int           # Advanced.Bottom Light PWM (uint16 BE)
    normal_light_pwm: int           # Advanced.Light PWM (uint16 BE)

    # Misc
    advance_mode: int               # always 0
    print_time: int                 # seconds (uint32 BE)
    volume: float                   # resin ml
    weight: float                   # same as volume in encoder
    price: float                    # same as volume in encoder
    layer_content_offset: int       # always 195477 (uint32 BE)
    grayscale_level: int            # always 1
    transition_layers: int          # Print.Transition Layer Count (uint16 BE)


@dataclass
class PrzLayerDef:
    """Fields from one layer's 64-byte definition block."""

    pause_flag: int         # always 0 (uint16 BE)
    pause_z: float          # same as layer_z (float BE)
    layer_z: float          # layer_height × (index + 1) (float BE)
    exposure_time: float    # interpolated for transition layers (float BE)
    light_off_time: float   # Print.Light-off Delay (float BE)
    before_lift_time: float   # always 0.0
    after_lift_time: float    # always 0.0
    after_retract_time: float  # Print.Rest Time After Retract
    lift_distance: float      # bottom or normal lift distance
    lift_speed: float
    lift2_distance: float
    lift2_speed: float
    retract_distance: float   # CALCULATED
    retract_speed: float
    drop2_distance: float
    drop2_speed: float
    light_pwm: int            # per-layer PWM (uint16 BE); may be patched


@dataclass
class PrzFile:
    """Parsed PRZ V3.0 file.

    Layer images are decoded on demand via decode_layer_image(index) to avoid
    loading all layer data into memory at once.
    """

    header: PrzHeader
    preview_small: np.ndarray   # shape (116, 116, 3) uint8 RGB
    preview_large: np.ndarray   # shape (290, 290, 3) uint8 RGB
    layers: list                # list[PrzLayerDef]

    # Internal: memoryview of the original data buffer (zero-copy slicing).
    # Each entry in _layer_rle_slices: (offset_into_data, rle_byte_count)
    _data: memoryview = field(repr=False, default_factory=lambda: memoryview(b""))
    _layer_rle_slices: list = field(repr=False, default_factory=list)  # list[(int, int)]

    def decode_layer_image(self, index: int) -> np.ndarray:
        """Decode layer *index* (0-based) to a (height, width) uint8 grayscale array.

        Raises:
            IndexError: if index is out of [0, total_layers) range.
            ValueError: if RLE checksum does not match.
        """
        if not (0 <= index < len(self._layer_rle_slices)):
            raise IndexError(
                f"Layer index {index} out of range "
                f"[0, {len(self._layer_rle_slices)})"
            )
        offset, size = self._layer_rle_slices[index]
        rle_bytes = self._data[offset: offset + size]
        return _rle_decode_layer(
            rle_bytes,
            width=self.header.x_res,
            height=self.header.y_res,
        )


# ---------- Preview image helpers ----------

def _rgb565_be_to_rgb(data: bytes, w: int, h: int) -> np.ndarray:
    """Decode RGB565 big-endian bytes to an (h, w, 3) uint8 RGB array."""
    pixels = np.frombuffer(data, dtype=">u2").reshape(h, w)
    r = ((pixels >> 11) & 0x1F).astype(np.uint8)
    g = ((pixels >> 5) & 0x3F).astype(np.uint8)
    b = (pixels & 0x1F).astype(np.uint8)
    # Scale 5-bit → 8-bit (×8 + top 3 bits) and 6-bit → 8-bit (×4 + top 2 bits)
    r = (r << 3) | (r >> 2)
    g = (g << 2) | (g >> 4)
    b = (b << 3) | (b >> 2)
    return np.stack([r, g, b], axis=-1)


# ---------- Header parser ----------

def _unpack_str(data: bytes, offset: int, size: int) -> str:
    """Read a null-terminated fixed-size string field."""
    raw = data[offset: offset + size]
    return raw.rstrip(b"\x00").decode("utf-8", errors="replace")


def _parse_header(data: bytes) -> PrzHeader:
    """Parse the 195,477-byte PRZ header into a PrzHeader dataclass.

    Offsets are derived 1-to-1 from prz_encoder.py's _write_header().
    """
    d = data  # alias for readability

    # --- Identification ---
    version        = _unpack_str(d, 0, 4)           # [0:4]   4B
    # tag            = d[4:12]                        # [4:12]  8B — not stored
    software       = _unpack_str(d, 12, 32)          # [12:44] 32B
    sw_version     = _unpack_str(d, 44, 24)          # [44:68] 24B
    file_time      = _unpack_str(d, 68, 24)          # [68:92] 24B
    printer_name   = _unpack_str(d, 92, 32)          # [92:124] 32B
    printer_type   = _unpack_str(d, 124, 32)         # [124:156] 32B
    profile_name   = _unpack_str(d, 156, 32)         # [156:188] 32B

    # --- Image quality ---
    aa_level,  = struct.unpack_from(">H", d, 188)   # [188:190]
    grey_level,= struct.unpack_from(">H", d, 190)   # [190:192]
    blur_level,= struct.unpack_from(">H", d, 192)   # [192:194]

    # Preview images — decoded separately in parse_prz()
    # [194:27106]  26912B  = 116×116×2
    # [27106:27108] CRLF
    # [27108:195308] 168200B = 290×290×2
    # [195308:195310] CRLF

    # --- Layers & resolution ---
    total_layers, = struct.unpack_from(">I", d, 195310)  # [195310:195314]
    x_res,        = struct.unpack_from(">H", d, 195314)  # [195314:195316]
    y_res,        = struct.unpack_from(">H", d, 195316)  # [195316:195318]
    x_mirror,     = struct.unpack_from("B",  d, 195318)  # [195318:195319]
    y_mirror,     = struct.unpack_from("B",  d, 195319)  # [195319:195320]

    # --- Platform geometry ---
    platform_x,   = struct.unpack_from(">f", d, 195320)  # [195320:195324]
    platform_y,   = struct.unpack_from(">f", d, 195324)  # [195324:195328]
    platform_z,   = struct.unpack_from(">f", d, 195328)  # [195328:195332]

    # --- Print parameters ---
    layer_height,  = struct.unpack_from(">f", d, 195332)  # [195332:195336]
    exposure_time, = struct.unpack_from(">f", d, 195336)  # [195336:195340]
    delay_mode,    = struct.unpack_from("B",  d, 195340)  # [195340:195341]
    light_off_time,= struct.unpack_from(">f", d, 195341)  # [195341:195345]

    bottom_before_lift_time,  = struct.unpack_from(">f", d, 195345)  # [195345:195349]
    bottom_after_lift_time,   = struct.unpack_from(">f", d, 195349)  # [195349:195353]
    bottom_after_retract_time,= struct.unpack_from(">f", d, 195353)  # [195353:195357]
    before_lift_time,         = struct.unpack_from(">f", d, 195357)  # [195357:195361]
    after_lift_time,          = struct.unpack_from(">f", d, 195361)  # [195361:195365]
    after_retract_time,       = struct.unpack_from(">f", d, 195365)  # [195365:195369]

    bottom_exposure_time,= struct.unpack_from(">f", d, 195369)  # [195369:195373]
    bottom_layers,       = struct.unpack_from(">I", d, 195373)  # [195373:195377]

    # --- 16 lift/retract float fields (4B each = 64B total) ---
    o = 195377
    (bottom_lift_dist, bottom_lift_spd,
     normal_lift_dist, normal_lift_spd,
     bottom_retract_dist, bottom_retract_spd,
     normal_retract_dist, normal_retract_spd,
     bottom_lift2_dist, bottom_lift2_spd,
     normal_lift2_dist, normal_lift2_spd,
     bottom_drop2_dist, bottom_drop2_spd,
     normal_drop2_dist, normal_drop2_spd) = struct.unpack_from(">16f", d, o)
    # o advances to 195377 + 64 = 195441

    # --- PWM ---
    bottom_pwm, = struct.unpack_from(">H", d, 195441)  # [195441:195443]
    normal_pwm, = struct.unpack_from(">H", d, 195443)  # [195443:195445]

    # --- Misc tail ---
    advance_mode,         = struct.unpack_from("B",  d, 195445)  # [195445:195446]
    print_time,           = struct.unpack_from(">I", d, 195446)  # [195446:195450]
    volume,               = struct.unpack_from(">f", d, 195450)  # [195450:195454]
    weight,               = struct.unpack_from(">f", d, 195454)  # [195454:195458]
    price,                = struct.unpack_from(">f", d, 195458)  # [195458:195462]
    # price_unit            = d[195462:195470]                     # 8B zeroed
    layer_content_offset, = struct.unpack_from(">I", d, 195470)  # [195470:195474]
    grayscale_level,      = struct.unpack_from("B",  d, 195474)  # [195474:195475]
    transition_layers,    = struct.unpack_from(">H", d, 195475)  # [195475:195477]

    return PrzHeader(
        version=version,
        software=software,
        software_version=sw_version,
        file_time=file_time,
        printer_name=printer_name,
        printer_type=printer_type,
        profile_name=profile_name,
        aa_level=aa_level,
        grey_level=grey_level,
        blur_level=blur_level,
        total_layers=total_layers,
        x_res=x_res,
        y_res=y_res,
        x_mirror=x_mirror,
        y_mirror=y_mirror,
        platform_x=platform_x,
        platform_y=platform_y,
        platform_z=platform_z,
        layer_height=layer_height,
        exposure_time=exposure_time,
        delay_mode=delay_mode,
        light_off_time=light_off_time,
        bottom_before_lift_time=bottom_before_lift_time,
        bottom_after_lift_time=bottom_after_lift_time,
        bottom_after_retract_time=bottom_after_retract_time,
        before_lift_time=before_lift_time,
        after_lift_time=after_lift_time,
        after_retract_time=after_retract_time,
        bottom_exposure_time=bottom_exposure_time,
        bottom_layers=bottom_layers,
        bottom_lift_distance=bottom_lift_dist,
        bottom_lift_speed=bottom_lift_spd,
        normal_lift_distance=normal_lift_dist,
        normal_lift_speed=normal_lift_spd,
        bottom_retract_distance=bottom_retract_dist,
        bottom_retract_speed=bottom_retract_spd,
        normal_retract_distance=normal_retract_dist,
        normal_retract_speed=normal_retract_spd,
        bottom_lift2_distance=bottom_lift2_dist,
        bottom_lift2_speed=bottom_lift2_spd,
        normal_lift2_distance=normal_lift2_dist,
        normal_lift2_speed=normal_lift2_spd,
        bottom_drop2_distance=bottom_drop2_dist,
        bottom_drop2_speed=bottom_drop2_spd,
        normal_drop2_distance=normal_drop2_dist,
        normal_drop2_speed=normal_drop2_spd,
        bottom_light_pwm=bottom_pwm,
        normal_light_pwm=normal_pwm,
        advance_mode=advance_mode,
        print_time=print_time,
        volume=volume,
        weight=weight,
        price=price,
        layer_content_offset=layer_content_offset,
        grayscale_level=grayscale_level,
        transition_layers=transition_layers,
    )


# ---------- Layer scanner ----------

# Per-layer definition format string — 16 fields before PWM:
# >H  pause_flag         (2B)
# >f  pause_z            (4B)
# >f  layer_z            (4B)
# >f  exposure_time      (4B)
# >f  light_off_time     (4B)
# >f  before_lift_time   (4B)
# >f  after_lift_time    (4B)
# >f  after_retract_time (4B)
# >f  lift_distance      (4B)
# >f  lift_speed         (4B)
# >f  lift2_distance     (4B)
# >f  lift2_speed        (4B)
# >f  retract_distance   (4B)
# >f  retract_speed      (4B)
# >f  drop2_distance     (4B)
# >f  drop2_speed        (4B)
# >H  light_pwm          (2B)
# Total: 2 + 15*4 + 2 = 64B
_LAYER_DEF_FMT = ">Hfffffffffffffffh"  # note: last field is signed-short, same bytes as >H for PWM
_LAYER_DEF_SIZE = 64
_RLE_SIZE_FMT = ">I"
_RLE_SIZE_BYTES = 4


def _scan_layers(data: bytes, total_layers: int) -> tuple[list, list]:
    """Scan the layer section starting at LAYER_CONTENT_OFFSET.

    Returns:
        (layer_defs, rle_slices)
        layer_defs:  list of PrzLayerDef (one per layer)
        rle_slices:  list of (offset, size) tuples pointing into `data`
    """
    pos = LAYER_CONTENT_OFFSET
    layer_defs = []
    rle_slices = []

    for _ in range(total_layers):
        # 1. Parse 64-byte layer definition
        (pause_flag, pause_z, layer_z, exposure_time, light_off_time,
         before_lift_time, after_lift_time, after_retract_time,
         lift_distance, lift_speed, lift2_distance, lift2_speed,
         retract_distance, retract_speed, drop2_distance, drop2_speed,
         pwm_raw) = struct.unpack_from(">Hfffffffffffffffh", data, pos)

        layer_defs.append(PrzLayerDef(
            pause_flag=pause_flag,
            pause_z=pause_z,
            layer_z=layer_z,
            exposure_time=exposure_time,
            light_off_time=light_off_time,
            before_lift_time=before_lift_time,
            after_lift_time=after_lift_time,
            after_retract_time=after_retract_time,
            lift_distance=lift_distance,
            lift_speed=lift_speed,
            lift2_distance=lift2_distance,
            lift2_speed=lift2_speed,
            retract_distance=retract_distance,
            retract_speed=retract_speed,
            drop2_distance=drop2_distance,
            drop2_speed=drop2_speed,
            light_pwm=pwm_raw & 0xFFFF,  # treat as unsigned
        ))
        pos += _LAYER_DEF_SIZE

        # 2. Skip CRLF after definition
        pos += 2  # PRZ_CRLF

        # 3. Read RLE data size
        rle_size, = struct.unpack_from(_RLE_SIZE_FMT, data, pos)
        pos += _RLE_SIZE_BYTES

        # 4. Record RLE slice (offset into data, byte count)
        rle_slices.append((pos, rle_size))
        pos += rle_size

        # 5. Skip trailing CRLF
        pos += 2  # PRZ_CRLF

    return layer_defs, rle_slices


# ---------- RLE decoder ----------

def _rle_decode_layer(rle_bytes: bytes | memoryview, width: int, height: int) -> np.ndarray:
    """Decode a PRZ RLE-encoded layer back to a (height, width) uint8 array.

    rle_bytes must start with PRZ_LAYER_HEADER (0x55) and end with a checksum.

    Raises:
        ValueError: if checksum mismatch or data is malformed.
    """
    if not rle_bytes or rle_bytes[0] != PRZ_LAYER_HEADER:
        raise ValueError("RLE data does not start with PRZ_LAYER_HEADER (0x55)")

    # Verify checksum — sum of bytes [1:-1], checksum is last byte.
    # Special case: encoder writes a 2-byte sequence [0x55, (~0x55)&0xFF] for
    # empty layers (n=0), which differs from the general formula (~sum([]))&0xFF.
    # We accept both to stay compatible with encoder output.
    payload = rle_bytes[1:-1]
    checksum_byte = rle_bytes[-1]
    if len(payload) == 0:
        # Empty payload: encoder uses (~PRZ_LAYER_HEADER) & 0xFF as checksum
        expected_checksum = (~PRZ_LAYER_HEADER) & 0xFF
    else:
        expected_checksum = (~sum(payload)) & 0xFF
    if expected_checksum != checksum_byte:
        raise ValueError(
            f"RLE checksum mismatch: expected 0x{expected_checksum:02X}, "
            f"got 0x{checksum_byte:02X}"
        )

    total_pixels = width * height
    output = np.empty(total_pixels, dtype=np.uint8)
    filled = 0

    mv = memoryview(rle_bytes)
    i = 1  # skip PRZ_LAYER_HEADER
    end = len(rle_bytes) - 1  # exclude checksum byte

    while i < end and filled < total_pixels:
        first = mv[i]
        i += 1

        color_type = first & RLE_COLOR_MASK
        byte_count_bits = (first & RLE_BYTE_COUNT_MASK) >> 4  # 0, 1, 2, or 3
        run_len = first & RLE_LEN_LOW_MASK

        # Gray value byte comes BEFORE extra bytes — mirrors encoder byte order:
        #   encoder writes [first_byte][gray_value][extra_bytes...]
        if color_type == RLE_GRAY:
            gray_value = mv[i]
            i += 1

        # Extra bytes extend the run length
        if byte_count_bits > 0:
            extra = int.from_bytes(mv[i: i + byte_count_bits], "big")
            run_len |= (extra << 4)
            i += byte_count_bits

        if color_type == RLE_GRAY:
            output[filled: filled + run_len] = gray_value
        elif color_type == RLE_WHITE:
            output[filled: filled + run_len] = 255
        else:  # RLE_BLACK
            output[filled: filled + run_len] = 0

        filled += run_len

    return output.reshape(height, width)


# ---------- Public API ----------

def parse_prz(data: bytes) -> PrzFile:
    """Parse a PRZ V3.0 binary file and return a PrzFile.

    Layer images are NOT decoded eagerly — call PrzFile.decode_layer_image(i)
    to decode individual layers.

    Args:
        data: complete .prz file contents as bytes.

    Returns:
        PrzFile instance with header, previews, and layer definitions.

    Raises:
        ValueError: if data is not a valid PRZ V3.0 file or is too short.
    """
    # Validate magic bytes
    if len(data) < LAYER_CONTENT_OFFSET:
        raise ValueError(
            f"File too short: {len(data)} bytes "
            f"(minimum header size is {LAYER_CONTENT_OFFSET})"
        )
    if data[:4] != PRZ_VERSION:
        raise ValueError(
            f"Invalid PRZ file: expected version magic {PRZ_VERSION!r}, "
            f"got {data[:4]!r}"
        )
    if data[4:12] != PRZ_TAG:
        raise ValueError(
            f"Invalid PRZ file: tag mismatch at bytes 4–11"
        )

    # Parse header
    header = _parse_header(data)

    # Decode preview images
    # Small: [194:27106] = 116*116*2 = 26912B
    preview_small = _rgb565_be_to_rgb(data[194:27106], PREVIEW_SMALL_SIZE, PREVIEW_SMALL_SIZE)
    # Large: [27108:195308] = 290*290*2 = 168200B
    preview_large = _rgb565_be_to_rgb(data[27108:195308], PREVIEW_LARGE_SIZE, PREVIEW_LARGE_SIZE)

    # Scan layers (definitions + RLE slice offsets)
    layer_defs, rle_slices = _scan_layers(data, header.total_layers)

    return PrzFile(
        header=header,
        preview_small=preview_small,
        preview_large=preview_large,
        layers=layer_defs,
        _data=memoryview(data) if not isinstance(data, memoryview) else data,
        _layer_rle_slices=rle_slices,
    )
