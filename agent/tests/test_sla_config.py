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
