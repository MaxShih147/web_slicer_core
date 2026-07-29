"""Tests for the prz-header-metadata change.

Covers spec `prz-header-metadata`:
  - software / softwareVersion / priceUnit 常數寫入
  - printerName / printerType / profileName 動態來源與降級
  - weight / price 由 volume × 密度/單價 計算與降級
  - _pack_str 防禦性字元安全截斷 + 強制 NUL

本檔目前僅完成 tasks 階段 0（測試骨架 + 回歸錨點登記）。
階段 0.2 的赤兔回歸錨點以 xfail 登記：weight/price 計算尚未實作
（現行 encoder 仍將 volume 直接寫入 weight/price），待 task 4 實作後轉綠。
"""

import io
import os
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from agent.prz_encoder import (
    _write_header,
    _pack_str,
    encode_prz,
    LAYER_CONTENT_OFFSET,
    SOFTWARE_NAME,
    SOFTWARE_VERSION,
    PRICE_UNIT,
)
from agent.prz_decoder import _parse_header, parse_prz
from agent.models import PrzPrintTimingConfig


# ---------------------------------------------------------------------------
# Shared fixtures / helpers (no mocks)
# ---------------------------------------------------------------------------

# 赤兔樣本回歸錨點（design.md D2）：
#   volume=1002 mm³, density=1.1 g/mL, cost=33 $/L → weight≈1.1022 g, price≈0.033066
ANCHOR_VOLUME_MM3 = 1002.0
ANCHOR_DENSITY = 1.1
ANCHOR_COST = 33.0
ANCHOR_WEIGHT = 1.1022
ANCHOR_PRICE = 0.033066


def _zero_timing() -> PrzPrintTimingConfig:
    return PrzPrintTimingConfig(
        exposure_delay_mode=1,
        light_off_delay=0.0,
        rest_before_lift=0.0,
        rest_after_lift=0.0,
        rest_after_retract=0.0,
    )


def _base_config() -> dict:
    """最小可用 Mechado 風格 config（含 Machine / Advanced / Resin / Other 區塊）。"""
    return {
        "Machine": {
            "Machine Name": "Phrozen Sonic Mini 8K S",
            "machine_type": "Phrozen Sonic Mini 8K S",
            "image_size": [8, 8],
            "bed_size": [0, 0, 120.0, 68.0],
            "machine_z": 175.0,
            "Mirror": 0,
        },
        "Advanced": {
            "Anti-aliasing Level": 0,
            "Grey Level": 0,
            "Image Blur Pixel": 0,
            "Light PWM": 255,
            "Bottom Light PWM": 255,
        },
        "Print": {},
        "Resin": {
            "Resin Density": ANCHOR_DENSITY,
            "Resin Cost": ANCHOR_COST,
            "Resin Currency": 0,
            "Resin Units": 0,
        },
        "Other": {
            "profile_name": "Aqua Resin - Gray-8K -50um",
            "volume": 0,
        },
    }


def _make_sl1(num_layers: int = 1, width: int = 8, height: int = 8) -> Path:
    """建構最小 .sl1（zip of PNG layers）供 encode_prz 端到端測試使用。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for i in range(num_layers):
            img = Image.fromarray(np.zeros((height, width), dtype=np.uint8), mode="L")
            png_buf = io.BytesIO()
            img.save(png_buf, format="PNG")
            zf.writestr(f"model{i:05d}.png", png_buf.getvalue())
    fd, path = tempfile.mkstemp(suffix=".sl1")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return Path(path)


def _build_and_parse(config: dict, resin_volume_mm3: float = 0.0):
    """以 _write_header 產出標頭並用 _parse_header 還原，回傳 PrzHeader。"""
    header = _write_header(
        config,
        total_layers=1,
        timing=_zero_timing(),
        resin_volume_mm3=resin_volume_mm3,
    )
    assert len(header) == LAYER_CONTENT_OFFSET
    return _parse_header(header)


# ---------------------------------------------------------------------------
# 1.1  _pack_str 防禦性硬化（design D3）：四個場景
# ---------------------------------------------------------------------------

class TestPackStr:
    def test_pack_str_oversize_ascii(self):
        # 超長 ASCII：34B 寫入 32B → 截斷至 size-1，尾端保證 NUL
        s = "FotoDent Denture Transparent 385nm"  # 34 bytes
        out = _pack_str(s, 32)
        assert len(out) == 32
        assert out[-1] == 0x00                       # 保證 NUL 結尾
        assert out.rstrip(b"\x00") == s.encode("utf-8")[:31]
        assert len(out.rstrip(b"\x00")) <= 31        # 有效內容 ≤ size-1

    def test_pack_str_cjk_no_broken_char(self):
        # CJK 多位元組不被裸 byte 切斷：每字 3B，size=8 → budget=7 → 容 2 字(6B)
        s = "樹脂材料測試"  # 6 個中文字 = 18 bytes > 7
        out = _pack_str(s, 8)
        assert len(out) == 8
        assert out[-1] == 0x00
        decoded = out.rstrip(b"\x00").decode("utf-8")  # 不應拋例外
        assert "�" not in decoded                  # 無替代字元/斷字
        assert decoded == "樹脂"                         # 恰好 2 個完整字元

    def test_pack_str_exact_fill_keeps_nul(self):
        # 恰好填滿 32B 的字串 → 縮減至 31B 並保留 1 個 NUL
        s = "A" * 32
        out = _pack_str(s, 32)
        assert len(out) == 32
        assert out[-1] == 0x00
        assert out.rstrip(b"\x00") == b"A" * 31

    def test_pack_str_empty_and_none(self):
        # 空字串與 None → 全 0x00、長度等於 size、不拋例外
        assert _pack_str("", 8) == b"\x00" * 8
        assert _pack_str(None, 24) == b"\x00" * 24


# ---------------------------------------------------------------------------
# 1.2  _pack_str 不變式：跨 size(8/24/32) × 邊界字串，恆滿足長度與 NUL 結尾
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("size", [8, 24, 32])
@pytest.mark.parametrize(
    "make_s",
    [
        pytest.param(lambda n: None, id="none"),
        pytest.param(lambda n: "", id="empty"),
        pytest.param(lambda n: "AB", id="short-ascii"),
        pytest.param(lambda n: "樹脂材料測試專用樹脂配方", id="oversize-cjk"),  # 12 字 = 36B
        pytest.param(lambda n: "A" * n, id="exact-fill"),
    ],
)
def test_pack_str_invariant(make_s, size):
    out = _pack_str(make_s(size), size)
    # 不變式 (1)：輸出位元組長度恆等於 size
    assert len(out) == size
    # 不變式 (2)：最後一 byte 恆為 NUL
    assert out[-1:] == b"\x00"


# ---------------------------------------------------------------------------
# 2.  常數欄位 software / softwareVersion / priceUnit（design D4）
# ---------------------------------------------------------------------------

class TestHeaderConstants:
    def test_header_constants_software_fields(self):
        # software [12:44] 與 softwareVersion [44:68] 應寫入具名常數
        h = _build_and_parse(_base_config(), resin_volume_mm3=ANCHOR_VOLUME_MM3)
        assert h.software == SOFTWARE_NAME == "Phrozen DS"
        assert h.software_version == SOFTWARE_VERSION == "0.0.1"
        assert h.software_version != ""

    def test_header_constants_price_unit(self):
        # priceUnit [195462:195470]（decoder 未解析，直接驗原始 bytes）
        header = _write_header(
            _base_config(), total_layers=1, timing=_zero_timing(),
            resin_volume_mm3=ANCHOR_VOLUME_MM3,
        )
        decoded = header[195462:195470].rstrip(b"\x00").decode("utf-8")
        assert decoded == PRICE_UNIT == "$/L"


# ---------------------------------------------------------------------------
# 3.  印表機與樹脂顯示名 printerName / printerType / profileName（design D4）
# ---------------------------------------------------------------------------

class TestDisplayNames:
    def test_profile_name_source(self):
        # 3.1：profileName 讀 Other.profile_name，且不再等於印表機名
        config = _base_config()
        config["Machine"]["Machine Name"] = "Phrozen Sonic Mini 8K S"
        config["Other"]["profile_name"] = "Aqua Resin - Gray-8K -50um"
        h = _build_and_parse(config, resin_volume_mm3=ANCHOR_VOLUME_MM3)
        assert h.profile_name == "Aqua Resin - Gray-8K -50um"
        assert h.profile_name != h.printer_name

    def test_profile_name_missing(self):
        # 3.2：Other.profile_name 缺漏 → profileName 空字串、不拋例外、長度不變
        config = _base_config()
        config["Other"].pop("profile_name", None)
        header = _write_header(
            config, total_layers=1, timing=_zero_timing(),
            resin_volume_mm3=ANCHOR_VOLUME_MM3,
        )
        assert len(header) == LAYER_CONTENT_OFFSET
        h = _parse_header(header)
        assert h.profile_name == ""

    def test_printer_display_names(self):
        # 3.3：印表機名/型別由 config 帶入並原樣還原
        config = _base_config()
        config["Machine"]["Machine Name"] = "Phrozen Sonic Mini 8K S"
        config["Machine"]["machine_type"] = "MSLA-8K"
        h = _build_and_parse(config, resin_volume_mm3=ANCHOR_VOLUME_MM3)
        assert h.printer_name == "Phrozen Sonic Mini 8K S"
        assert h.printer_type == "MSLA-8K"


# ---------------------------------------------------------------------------
# 5.1  端到端：encode_prz() → parse_prz()，斷言 8 欄位全部正確
# ---------------------------------------------------------------------------

class TestEndToEndHeader:
    def test_end_to_end_header(self):
        config = _base_config()
        config["Machine"]["Machine Name"] = "Phrozen Sonic Mini 8K S"
        config["Machine"]["machine_type"] = "MSLA-8K"
        config["Other"]["profile_name"] = "Aqua Resin - Gray-8K -50um"

        sl1 = _make_sl1(num_layers=1)
        try:
            data = encode_prz(
                config=config,
                sl1_path=sl1,
                timing=_zero_timing(),
                resin_volume_mm3=ANCHOR_VOLUME_MM3,
            )
        finally:
            sl1.unlink(missing_ok=True)

        prz = parse_prz(data)
        h = prz.header

        # 8 個目標欄位（priceUnit 未由 decoder 解析，直驗原始 bytes）
        assert h.software == "Phrozen DS"
        assert h.software_version == "0.0.1"
        assert h.printer_name == "Phrozen Sonic Mini 8K S"
        assert h.printer_type == "MSLA-8K"
        assert h.profile_name == "Aqua Resin - Gray-8K -50um"
        assert h.weight == pytest.approx(ANCHOR_WEIGHT, abs=1e-3)
        assert h.price == pytest.approx(ANCHOR_PRICE, abs=1e-3)
        assert data[195462:195470].rstrip(b"\x00").decode("utf-8") == "$/L"

        # header 長度錨點
        assert data[:4] == b"V3.0"


# ---------------------------------------------------------------------------
# 4.  weight / price 動態計算與降級（design D2）
# ---------------------------------------------------------------------------

class TestWeightPrice:
    def test_weight_price_compute(self):
        # 4.2：赤兔錨點 volume=1002, density=1.1, cost=33 → weight≈1.1022, price≈0.033066
        h = _build_and_parse(_base_config(), resin_volume_mm3=ANCHOR_VOLUME_MM3)
        assert h.weight == pytest.approx(ANCHOR_WEIGHT, abs=1e-3)
        assert h.price == pytest.approx(ANCHOR_PRICE, abs=1e-3)

    def test_weight_price_degrade_density_missing(self):
        # 4.3：density 缺漏 → weight 降級寫 volume（price 仍正常計算）
        config = _base_config()
        config["Resin"].pop("Resin Density", None)
        h = _build_and_parse(config, resin_volume_mm3=ANCHOR_VOLUME_MM3)
        assert h.weight == pytest.approx(ANCHOR_VOLUME_MM3, abs=1e-3)
        assert h.price == pytest.approx(ANCHOR_PRICE, abs=1e-3)

    def test_weight_price_degrade_cost_missing(self):
        # 4.3：cost 缺漏 → price 降級寫 volume（weight 仍正常計算）
        config = _base_config()
        config["Resin"].pop("Resin Cost", None)
        h = _build_and_parse(config, resin_volume_mm3=ANCHOR_VOLUME_MM3)
        assert h.price == pytest.approx(ANCHOR_VOLUME_MM3, abs=1e-3)
        assert h.weight == pytest.approx(ANCHOR_WEIGHT, abs=1e-3)


# ---------------------------------------------------------------------------
# 0.1  測試骨架健全性：標頭可建置、可解析、長度正確
# ---------------------------------------------------------------------------

class TestScaffold:
    def test_header_builds_and_parses(self):
        h = _build_and_parse(_base_config(), resin_volume_mm3=ANCHOR_VOLUME_MM3)
        assert h.version == "V3.0"

    def test_header_exact_length(self):
        header = _write_header(
            _base_config(), total_layers=1, timing=_zero_timing(),
            resin_volume_mm3=ANCHOR_VOLUME_MM3,
        )
        assert len(header) == LAYER_CONTENT_OFFSET  # 195477


# ---------------------------------------------------------------------------
# 0.2  赤兔回歸錨點（task 4 已實作 weight/price 計算，xfail 解除轉綠）
# ---------------------------------------------------------------------------

class TestRegressionAnchor:
    def test_regression_anchor_weight(self):
        h = _build_and_parse(_base_config(), resin_volume_mm3=ANCHOR_VOLUME_MM3)
        assert h.weight == pytest.approx(ANCHOR_WEIGHT, abs=1e-3)

    def test_regression_anchor_price(self):
        h = _build_and_parse(_base_config(), resin_volume_mm3=ANCHOR_VOLUME_MM3)
        assert h.price == pytest.approx(ANCHOR_PRICE, abs=1e-3)
