"""
Tests for optimize-slice-config-flow 階段 3（API center 欄位）& 階段 4（execute 合併）。

涵蓋 specs/slice-config-intake/spec.md 場景：
  - POST /slices 接受 center 頂層欄位；未帶 center 的舊請求不報錯（向後相容）
  - execute 合併：base(mechado) ← override(snake)，欄位級 last-write-wins
      (a) 新流程只送 mechado → 純萃取
      (b) mechado + PUT snake 覆蓋 → 被覆蓋欄位取 snake 值，其餘取 mechado
      (c) 舊流程（無 mechado、僅 snake）→ 等同 _convert_v2_config_to_sla(snake)
"""

import asyncio

from agent.api_v2 import (
    _build_sla_config,
    _convert_v2_config_to_sla,
    _pending_jobs,
    create_slice_job,
    V2SliceCreateRequest,
)


def _mechado():
    return {
        "Machine": {
            "machine_type": "sonic_4k_2022",
            "image_size": [3840, 2160],
            "bed_size": [0.0, 0.0, 134.0, 75.0],
        },
        "Print": {"Layer Height": 0.05},
        "Advanced": {
            "Anti-aliasing": True,
            "Anti-aliasing Level": 2,
            "Grey Level": 0,
            "Image Blur Pixel": 1,
        },
    }


class TestCreateSliceJobCenterField:
    """階段 3.2：API center 欄位與向後相容。"""

    def test_center_stored_in_pending(self):
        """帶 center 的 POST /slices 應將 center 存入 _pending_jobs。"""
        req = V2SliceCreateRequest(prz_config=_mechado(), center=[10.0, -5.0])
        resp = asyncio.run(create_slice_job(req))
        job_id = resp.data["jobId"]
        try:
            assert _pending_jobs[job_id]["center"] == [10.0, -5.0]
            assert _pending_jobs[job_id]["prz_config"] is not None
        finally:
            _pending_jobs.pop(job_id, None)

    def test_legacy_request_without_center_ok(self):
        """未帶 center 的舊請求應成功建立、不報錯，且 pending 不含 center key。"""
        req = V2SliceCreateRequest(config={"layer_height": 0.05})  # 無 center / 無 prz_config
        resp = asyncio.run(create_slice_job(req))
        job_id = resp.data["jobId"]
        try:
            assert resp.success is True
            assert "center" not in _pending_jobs[job_id]
        finally:
            _pending_jobs.pop(job_id, None)


class TestExecuteMergeStrategy:
    """階段 4.2：base(mechado) ← override(snake) 三條路徑。"""

    def test_new_flow_pure_extraction(self):
        """(a) 只送 mechado → SLAConfig 完全來自萃取。"""
        sla = _build_sla_config(_mechado(), snake_config=None, center=[10.0, -5.0])
        assert sla.layer_height == 0.05
        assert sla.display_width == 134.0
        assert sla.display_height == 75.0
        assert sla.anti_aliasing_level == 2
        assert sla.printer_model == "sonic_4k_2022"
        assert sla.center_x == 77.0   # 10 + 134/2
        assert sla.center_y == 32.5   # -5 + 75/2

    def test_put_snake_overrides_mechado(self):
        """(b) mechado + PUT {layer_height:0.10} → layer_height 取 0.10，其餘維持 mechado。"""
        sla = _build_sla_config(_mechado(), snake_config={"layer_height": 0.10})
        assert sla.layer_height == 0.10            # snake 覆蓋
        assert sla.display_width == 134.0          # 未被覆蓋 → mechado 萃取值
        assert sla.anti_aliasing_level == 2

    def test_legacy_flow_matches_old_converter(self):
        """(c) 無 mechado、僅 snake → 等同 _convert_v2_config_to_sla(snake)，逐欄位。"""
        snake = {
            "layer_height": 0.05,
            "printer_model": "sonic_4k_2022",
            "display_pixels_x": 3840,
            "display_pixels_y": 2160,
            "display_width": 134.0,
            "display_height": 75.0,
            "anti_aliasing": True,
            "anti_aliasing_level": 2,
            "gray_level": 0,
            "blur": 1,
        }
        new_sla = _build_sla_config(prz_config=None, snake_config=snake)
        old_sla = _convert_v2_config_to_sla(snake)
        for field in (
            "layer_height", "printer_model", "display_pixels_x", "display_pixels_y",
            "display_width", "display_height", "anti_aliasing", "anti_aliasing_level",
            "gray_level", "blur",
        ):
            assert getattr(new_sla, field) == getattr(old_sla, field), f"欄位 {field} 不一致"