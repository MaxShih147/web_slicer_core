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