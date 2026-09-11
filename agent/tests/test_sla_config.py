"""
Tests for SLAConfig model — Task 1 (fix-prz-output-correctness).

Covers:
  - initial_layer_height fallback to layer_height when not set (1.3)
  - initial_layer_height explicit override preserved (1.4)
  - generate_config_ini writes initial_layer_height to INI (1.5)
"""

import tempfile
from pathlib import Path

import pytest

from agent.models import SLAConfig
from agent.sla_operations import generate_config_ini


class TestInitialLayerHeightFallback:
    def test_fallback_when_not_set(self):
        """1.3: initial_layer_height 未設定時應 fallback 至 layer_height。"""
        config = SLAConfig(layer_height=0.05)
        assert config.initial_layer_height == 0.05

    def test_explicit_override_preserved(self):
        """1.4: 顯式傳入 initial_layer_height 時應保留使用者設定值。"""
        config = SLAConfig(layer_height=0.05, initial_layer_height=0.30)
        assert config.initial_layer_height == 0.30

    def test_ini_contains_initial_layer_height(self):
        """1.5: generate_config_ini 產生的 INI 應含 initial_layer_height 一行。"""
        config = SLAConfig(layer_height=0.05)
        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = Path(tmpdir) / "config.ini"
            generate_config_ini(config, ini_path)
            content = ini_path.read_text()
        assert "initial_layer_height = 0.05" in content


# ---------------------------------------------------------------------------
# add-support-tree-global-params change: 13 個支撐樹全域參數（僅後端範圍）
# ---------------------------------------------------------------------------

STANDARD_SUPPORT_FIELDS = {
    "support_head_width": 1.0,
    "support_base_diameter": 4.0,
    "support_base_height": 1.0,
    "support_bracing_angle": 45.0,
    "support_max_bridge_length": 15.0,
    "support_max_pillar_link_distance": 10.0,
    "support_max_bridges_on_pillar": 3,
    "support_small_pillar_diameter_percent": 50.0,
    "support_buildplate_only": False,
}


class TestStandardSupportTreeGlobalParams:
    """1.1: 9 個標準支撐樹全域參數。"""

    def test_custom_values_written_to_ini(self):
        custom = {
            "support_head_width": 2.5,
            "support_base_diameter": 6.0,
            "support_base_height": 2.0,
            "support_bracing_angle": 30.0,
            "support_max_bridge_length": 20.0,
            "support_max_pillar_link_distance": 8.0,
            "support_max_bridges_on_pillar": 5,
            "support_small_pillar_diameter_percent": 70.0,
            "support_buildplate_only": True,
        }
        config = SLAConfig(**custom)
        for field, value in custom.items():
            assert getattr(config, field) == value

        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = Path(tmpdir) / "config.ini"
            generate_config_ini(config, ini_path)
            content = ini_path.read_text()
        assert "support_head_width = 2.5" in content
        assert "support_base_diameter = 6.0" in content
        assert "support_base_height = 2.0" in content
        assert "support_bracing_angle = 30.0" in content
        assert "support_max_bridge_length = 20.0" in content
        assert "support_max_pillar_link_distance = 8.0" in content
        assert "support_max_bridges_on_pillar = 5" in content
        assert "support_small_pillar_diameter_percent = 70.0" in content
        assert "support_buildplate_only = 1" in content

    def test_defaults_match_engine(self):
        """未提供時，套用與 PrintConfig.cpp 一致的引擎預設值。"""
        config = SLAConfig()
        for field, default in STANDARD_SUPPORT_FIELDS.items():
            assert getattr(config, field) == default

    def test_max_pillar_link_distance_zero_is_accepted(self):
        """1.3 邊界案例：0 是合法值（完全不串接），不得被下限保護攔截。"""
        config = SLAConfig(support_max_pillar_link_distance=0)
        assert config.support_max_pillar_link_distance == 0

        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = Path(tmpdir) / "config.ini"
            generate_config_ini(config, ini_path)
            content = ini_path.read_text()
        assert "support_max_pillar_link_distance = 0" in content


class TestSupportBaseSafetyDistance:
    """2.1: 底座安全距離——後端如實傳遞，不做任何攔截或改寫。"""

    def test_zero_written_as_is(self):
        config = SLAConfig(support_base_safety_distance=0)
        assert config.support_base_safety_distance == 0

        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = Path(tmpdir) / "config.ini"
            generate_config_ini(config, ini_path)
            content = ini_path.read_text()
        assert "support_base_safety_distance = 0" in content

    def test_default_matches_engine(self):
        config = SLAConfig()
        assert config.support_base_safety_distance == 1.0


class TestSupportPillarConnectionMode:
    """3.1: 柱間連接模式——合法值集合驗證。"""

    @pytest.mark.parametrize("mode", ["zigzag", "cross", "dynamic"])
    def test_legal_values_accepted(self, mode):
        config = SLAConfig(support_pillar_connection_mode=mode)
        assert config.support_pillar_connection_mode == mode

    def test_default_is_dynamic(self):
        config = SLAConfig()
        assert config.support_pillar_connection_mode == "dynamic"

    def test_illegal_value_rejected(self):
        with pytest.raises(ValueError):
            SLAConfig(support_pillar_connection_mode="auto")


class TestSupportTreeType:
    """4.1: 支撐樹型別——入口開放且拒絕未實作值。"""

    @pytest.mark.parametrize("tree_type", ["default", "branching"])
    def test_legal_values_accepted(self, tree_type):
        config = SLAConfig(support_tree_type=tree_type)
        assert config.support_tree_type == tree_type

    def test_default_is_default(self):
        config = SLAConfig()
        assert config.support_tree_type == "default"

    def test_organic_rejected(self):
        with pytest.raises(ValueError):
            SLAConfig(support_tree_type="organic")

    def test_other_illegal_value_rejected(self):
        with pytest.raises(ValueError):
            SLAConfig(support_tree_type="not-a-real-type")

    def test_branching_without_branchingsupport_fields_does_not_raise(self):
        """branching 不需要提供任何 branchingsupport_* 欄位也不報錯
        （引擎在缺欄位時採用自身預設值，本次不搬移這批欄位）。"""
        config = SLAConfig(support_tree_type="branching")
        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = Path(tmpdir) / "config.ini"
            generate_config_ini(config, ini_path)  # 不應拋例外
            content = ini_path.read_text()
        assert "support_tree_type = branching" in content


class TestSupportEnforcersOnly:
    """5.1: 強制區佈點開關——欄位到位、功能待用。"""

    def test_can_be_set_true(self):
        config = SLAConfig(support_enforcers_only=True)
        assert config.support_enforcers_only is True

        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = Path(tmpdir) / "config.ini"
            generate_config_ini(config, ini_path)  # 不應拋例外
            content = ini_path.read_text()
        assert "support_enforcers_only = 1" in content

    def test_default_is_false(self):
        config = SLAConfig()
        assert config.support_enforcers_only is False


# ---------------------------------------------------------------------------
# add-pad-global-params change: 11 個底墊全域參數（僅後端範圍，F2）
# ---------------------------------------------------------------------------

STANDARD_PAD_FIELDS = {
    "pad_wall_thickness": 2.0,
    "pad_wall_height": 0.0,
    "pad_brim_size": 1.6,
    "pad_max_merge_distance": 50.0,
    "pad_around_object": False,
    "pad_around_object_everywhere": False,
    "pad_object_gap": 1.0,
    "pad_object_connector_stride": 10.0,
    "pad_object_connector_width": 0.5,
    "pad_object_connector_penetration": 0.3,
}


class TestStandardPadGlobalParams:
    """1.1: 10 個標準底墊全域參數。"""

    def test_custom_values_written_to_ini(self):
        custom = {
            "pad_wall_thickness": 3.5,
            "pad_wall_height": 2.0,
            "pad_brim_size": 2.5,
            "pad_max_merge_distance": 40.0,
            "pad_around_object": True,
            "pad_around_object_everywhere": True,
            "pad_object_gap": 1.5,
            "pad_object_connector_stride": 8.0,
            "pad_object_connector_width": 0.8,
            "pad_object_connector_penetration": 0.4,
        }
        config = SLAConfig(**custom)
        for field, value in custom.items():
            assert getattr(config, field) == value

        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = Path(tmpdir) / "config.ini"
            generate_config_ini(config, ini_path)
            content = ini_path.read_text()
        assert "pad_wall_thickness = 3.5" in content
        assert "pad_wall_height = 2.0" in content
        assert "pad_brim_size = 2.5" in content
        assert "pad_max_merge_distance = 40.0" in content
        assert "pad_around_object = 1" in content
        assert "pad_around_object_everywhere = 1" in content
        assert "pad_object_gap = 1.5" in content
        assert "pad_object_connector_stride = 8.0" in content
        assert "pad_object_connector_width = 0.8" in content
        assert "pad_object_connector_penetration = 0.4" in content

    def test_defaults_match_engine(self):
        """未提供時，套用與 PrintConfig.cpp 一致的引擎預設值。"""
        config = SLAConfig()
        for field, default in STANDARD_PAD_FIELDS.items():
            assert getattr(config, field) == default


class TestPadWallSlope:
    """2.1: 底墊側壁斜度——合法範圍 45–90 度，範圍外一律拒絕。"""

    @pytest.mark.parametrize("value", [45, 67.5, 90])
    def test_legal_values_accepted(self, value):
        config = SLAConfig(pad_wall_slope=value)
        assert config.pad_wall_slope == value

        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = Path(tmpdir) / "config.ini"
            generate_config_ini(config, ini_path)
            content = ini_path.read_text()
        assert f"pad_wall_slope = {value}" in content

    @pytest.mark.parametrize("value", [0, 44.9, 90.1, 120, -10])
    def test_illegal_values_rejected(self, value):
        with pytest.raises(ValueError):
            SLAConfig(pad_wall_slope=value)

    def test_default_is_90(self):
        config = SLAConfig()
        assert config.pad_wall_slope == 90.0


class TestZeroElevationPadFields:
    """3.1: zero-elevation 專屬欄位——不論開關狀態皆可設定，不做條件驗證。

    引擎 SLAPrint.cpp:48-51 的 is_zero_elevation() 為
    pad_enable AND pad_around_object；兩者同時為 true 才讀這 5 個值，
    否則整組被引擎忽略，不報錯。API 層 SHALL NOT 對此加任何條件驗證。
    """

    ZERO_ELEVATION_FIELDS = {
        "pad_around_object_everywhere": True,
        "pad_object_gap": 2.5,
        "pad_object_connector_stride": 5.0,
        "pad_object_connector_width": 0.7,
        "pad_object_connector_penetration": 0.6,
    }

    def test_settable_when_pad_enable_false(self):
        config = SLAConfig(pad_enable=False, **self.ZERO_ELEVATION_FIELDS)
        for field, value in self.ZERO_ELEVATION_FIELDS.items():
            assert getattr(config, field) == value

    def test_settable_when_pad_around_object_false(self):
        config = SLAConfig(pad_around_object=False, **self.ZERO_ELEVATION_FIELDS)
        for field, value in self.ZERO_ELEVATION_FIELDS.items():
            assert getattr(config, field) == value

    def test_no_validation_error_when_both_conditions_unmet(self):
        """兩個開關都關著時，送出這 5 個值仍不觸發任何驗證錯誤。"""
        config = SLAConfig(
            pad_enable=False,
            pad_around_object=False,
            **self.ZERO_ELEVATION_FIELDS,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            ini_path = Path(tmpdir) / "config.ini"
            generate_config_ini(config, ini_path)  # 不應拋例外
            content = ini_path.read_text()
        assert "pad_object_gap = 2.5" in content
