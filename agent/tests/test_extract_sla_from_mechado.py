"""
Tests for _extract_sla_from_mechado — optimize-slice-config-flow 階段 1 & 2。

涵蓋 specs/slice-config-intake/spec.md 場景：
  - 新流程萃取：完整 Machine/Advanced → 正確數值（bed_size[2]/[3]、AA Level 不二次轉換）
  - AA Level 不得二次轉換
  - mechado 缺欄位退預設且不報錯
  - center 位移換算為絕對座標
  - 未提供 center 時不產生 center_x/center_y
  - Round-trip 等價：新（mechado 萃取）== 舊（snake _convert_v2_config_to_sla），逐欄位
"""

import pytest

from agent.api_v2 import _convert_v2_config_to_sla, _extract_sla_from_mechado
from agent.models import SLAConfig


# 切片相關欄位（Round-trip 比對的逐欄位清單）
_SLICING_FIELDS = (
    "layer_height",
    "printer_model",
    "display_pixels_x",
    "display_pixels_y",
    "display_width",
    "display_height",
    "anti_aliasing",
    "anti_aliasing_level",
    "gray_level",
    "blur",
)


def _make_mechado(machine_type, image_size, bed_size, layer_height,
                  aa_enabled, aa_level_backend, grey, blur_backend):
    """建構一份完整三段式 mechado config（模擬前端 uiToDefault 產出）。

    注意：AA Level / blur 已是後端刻度（前端寫入 mechado 時已套 UI→backend 轉換）。
    """
    return {
        "Machine": {
            "machine_type": machine_type,
            "image_size": list(image_size),
            "bed_size": list(bed_size),
        },
        "Print": {
            "Layer Height": layer_height,
        },
        "Advanced": {
            "Anti-aliasing": aa_enabled,
            "Anti-aliasing Level": aa_level_backend,
            "Grey Level": grey,
            "Image Blur Pixel": blur_backend,
        },
    }


def _make_snake(machine_type, image_size, bed_size, layer_height,
                aa_enabled, aa_level_backend, grey, blur_backend):
    """建構等價的舊版 snake-case 切片 config（模擬前端 uiToBackendSlicingConfig 產出）。

    與 _make_mechado 取自同一組來源值；AA Level / blur 同為後端刻度（前端兩條
    映射路徑使用相同 transform）。
    """
    return {
        "layer_height": layer_height,
        "printer_model": machine_type,
        "display_pixels_x": image_size[0],
        "display_pixels_y": image_size[1],
        "display_width": bed_size[2],
        "display_height": bed_size[3],
        "anti_aliasing": aa_enabled,
        "anti_aliasing_level": aa_level_backend,
        "gray_level": grey,
        "blur": blur_backend,
    }


# 代表性機型參數（來源：DS-online 內建 profile）
_PROFILES = [
    # machine_type, image_size, bed_size, layer_height, aa_enabled, aa_lvl, grey, blur
    ("sonic_4k_2022", [3840, 2160], [0.0, 0.0, 134.0, 75.0], 0.05, True, 2, 0, 1),
    ("sonic_cs_plus", [7536, 3240], [0.0, 0.0, 165.79, 71.28], 0.10, False, 1, 3, 0),
    ("sonic_ls_plus", [3840, 2400], [0.0, 0.0, 200.0, 125.0], 0.02, True, 0, 5, 2),
]


class TestExtractValues:
    """階段 1：spec「新流程萃取」場景。"""

    def test_full_machine_advanced_extraction(self):
        """1.2: 完整 Machine/Advanced → 正確數值，bed_size 取 [2]/[3]。"""
        mechado = _make_mechado(
            "sonic_4k_2022", [3840, 2160], [0.0, 0.0, 134.0, 75.0],
            0.05, True, 2, 0, 1,
        )
        out = _extract_sla_from_mechado(mechado)

        assert out["display_width"] == 134.0   # bed_size[2]，非 [0]
        assert out["display_height"] == 75.0   # bed_size[3]，非 [1]
        assert out["display_pixels_x"] == 3840
        assert out["display_pixels_y"] == 2160
        assert out["layer_height"] == 0.05
        assert out["printer_model"] == "sonic_4k_2022"
        assert out["anti_aliasing_level"] == 2  # 直接複製，未變成 8
        assert out["gray_level"] == 0
        assert out["blur"] == 1                 # 直接複製

    def test_aa_level_not_transformed(self):
        """1.2: AA Level 直接複製，不得二次轉換（1 不可變成 4 或 0）。"""
        mechado = _make_mechado(
            "x", [100, 100], [0.0, 0.0, 50.0, 50.0], 0.05, True, 1, 0, 0,
        )
        out = _extract_sla_from_mechado(mechado)
        assert out["anti_aliasing_level"] == 1

    def test_missing_advanced_falls_back_to_defaults(self):
        """1.2: 缺 Advanced 區段時萃取成功不報錯，相關欄位退回 SLAConfig 預設。"""
        mechado = {
            "Machine": {"image_size": [3840, 2160], "bed_size": [0.0, 0.0, 134.0, 75.0]},
            "Print": {"Layer Height": 0.05},
            # 無 Advanced
        }
        out = _extract_sla_from_mechado(mechado)  # 不應拋錯
        assert "anti_aliasing_level" not in out
        assert "gray_level" not in out
        assert "blur" not in out

        sla = SLAConfig(**out)
        assert sla.anti_aliasing_level == SLAConfig.model_fields["anti_aliasing_level"].default
        assert sla.gray_level == SLAConfig.model_fields["gray_level"].default
        assert sla.blur == SLAConfig.model_fields["blur"].default


class TestCenterConversion:
    """階段 1：spec「center 位移換算」場景。"""

    def test_center_converted_to_absolute(self):
        """1.4: center=[10,-5] + bed[0,0,134,75] → center_x=77.0, center_y=32.5。"""
        mechado = _make_mechado(
            "x", [3840, 2160], [0.0, 0.0, 134.0, 75.0], 0.05, True, 2, 0, 1,
        )
        out = _extract_sla_from_mechado(mechado, center=[10.0, -5.0])
        assert out["center_x"] == 77.0    # 10 + 134/2
        assert out["center_y"] == 32.5    # -5 + 75/2

    def test_no_center_means_no_center_keys(self):
        """1.4: 未提供 center 時，萃取結果不含 center_x/center_y。"""
        mechado = _make_mechado(
            "x", [3840, 2160], [0.0, 0.0, 134.0, 75.0], 0.05, True, 2, 0, 1,
        )
        out = _extract_sla_from_mechado(mechado)
        assert "center_x" not in out
        assert "center_y" not in out


class TestRoundTripEquivalence:
    """階段 2：Round-trip 等價測試 — 新（mechado）== 舊（snake），逐欄位。"""

    @pytest.mark.parametrize("profile", _PROFILES, ids=lambda p: p[0])
    def test_new_equals_old_per_field(self, profile):
        """2.1/2.2: 同一組來源值，mechado 萃取 == snake 舊萃取，逐欄位完全一致。"""
        mechado = _make_mechado(*profile)
        snake = _make_snake(*profile)

        new_sla = SLAConfig(**_extract_sla_from_mechado(mechado))
        old_sla = _convert_v2_config_to_sla(snake)

        for field in _SLICING_FIELDS:
            assert getattr(new_sla, field) == getattr(old_sla, field), (
                f"欄位 '{field}' 不一致：new={getattr(new_sla, field)} "
                f"old={getattr(old_sla, field)}（profile={profile[0]}）"
            )


# 哨兵：代表「開關鍵完全不存在」，與 False / None 明確區分（三態語意的第三態）。
_ABSENT = object()


def _mechado_with_blur_switch(blur_enabled, blur_pixel):
    """在標準 mechado 之上加掛 `Advanced."Image Blur"` 開關。

    `blur_enabled` 傳入 `_ABSENT` 時完全不寫入該鍵（模擬舊 config）。
    """
    mechado = _make_mechado(
        "sonic_4k_2022", [3840, 2160], [0.0, 0.0, 134.0, 75.0],
        0.05, True, 2, 0, blur_pixel,
    )
    if blur_enabled is not _ABSENT:
        mechado["Advanced"]["Image Blur"] = blur_enabled
    return mechado


class TestBlurSwitchGating:
    """spec「後端從完整 mechado config 萃取 SLAConfig 切片參數」的 blur 三態閘控。

    背景：前端在使用者未勾選 blur 時仍送出 `Image Blur Pixel = 1`，本閘控導入前後端
    完全沒讀開關，導致切片一律以 blur 啟用執行。
    """

    def test_switch_false_zeroes_blur(self):
        """開關 false + 強度 1 → blur 為 0。"""
        out = _extract_sla_from_mechado(_mechado_with_blur_switch(False, 1))
        assert out["blur"] == 0

    def test_switch_false_ignores_any_intensity(self):
        """開關優先於強度：false + 強度 3 仍為 0，不得取 3。"""
        out = _extract_sla_from_mechado(_mechado_with_blur_switch(False, 3))
        assert out["blur"] == 0

    def test_switch_true_copies_intensity(self):
        """開關 true → 強度直接複製，不得套用任何刻度轉換。"""
        out = _extract_sla_from_mechado(_mechado_with_blur_switch(True, 2))
        assert out["blur"] == 2

    def test_missing_switch_preserves_legacy_behaviour(self):
        """開關鍵不存在 → 直接複製（向後相容，舊 config 行為不得改變）。"""
        out = _extract_sla_from_mechado(_mechado_with_blur_switch(_ABSENT, 1))
        assert out["blur"] == 1

    def test_switch_does_not_touch_anti_aliasing_fields(self):
        """開關與 AA 正交：關閉 blur MUST NOT 影響 AA 相關欄位。"""
        out = _extract_sla_from_mechado(_mechado_with_blur_switch(False, 1))
        assert out["anti_aliasing"] is True
        assert out["anti_aliasing_level"] == 2
        assert out["gray_level"] == 0

    def test_switch_false_writes_blur_zero_to_ini(self, tmp_path):
        """開關 false 時 generate_config_ini() 寫出的 INI 含 `blur = 0`。"""
        from agent.sla_operations import generate_config_ini

        sla = SLAConfig(**_extract_sla_from_mechado(_mechado_with_blur_switch(False, 1)))
        ini_path = tmp_path / "config.ini"
        generate_config_ini(sla, ini_path)
        assert "blur = 0" in ini_path.read_text().splitlines()


class TestBlurSwitchGatingLegacyFlatConfig:
    """spec「舊版扁平 config 轉換亦須尊重 Image Blur 開關」。

    兩個轉換器對同一語意產生不一致的 blur，會讓 execute 階段的
    「base(mechado) ← override(snake)」合併依請求順序產生不可預期的結果。
    """

    def test_flat_switch_false_zeroes_blur(self):
        sla = _convert_v2_config_to_sla({"Image Blur": False, "Image Blur Pixel": 1})
        assert sla.blur == 0

    def test_flat_missing_switch_preserves_legacy_behaviour(self):
        sla = _convert_v2_config_to_sla({"Image Blur Pixel": 1})
        assert sla.blur == 1

    def test_flat_switch_true_copies_intensity(self):
        sla = _convert_v2_config_to_sla({"Image Blur": True, "Image Blur Pixel": 2})
        assert sla.blur == 2

    def test_flat_switch_gates_snake_blur_too(self):
        """開關也必須閘控 snake `blur` 鍵，而非只閘控 DS-Online 的強度鍵。"""
        sla = _convert_v2_config_to_sla({"Image Blur": False, "blur": 3})
        assert sla.blur == 0

    @pytest.mark.parametrize(
        "enabled,pixel",
        [(False, 1), (False, 3), (True, 2), (_ABSENT, 1)],
        ids=["off-1", "off-3", "on-2", "absent-1"],
    )
    def test_both_converters_agree(self, enabled, pixel):
        """同一語意餵給兩個轉換器，blur 必須相等（結構上共用 _gate_blur）。"""
        mechado_out = _extract_sla_from_mechado(_mechado_with_blur_switch(enabled, pixel))

        flat = {"Image Blur Pixel": pixel}
        if enabled is not _ABSENT:
            flat["Image Blur"] = enabled
        flat_sla = _convert_v2_config_to_sla(flat)

        assert SLAConfig(**mechado_out).blur == flat_sla.blur