"""
Tests for optimize-slice-config-flow 階段 5：download.prz config/preview 降級。

涵蓋 specs/slice-config-intake/spec.md 場景：
  - body 為空時從 prz_config.json 降級讀取並回傳
  - body 顯式提供 config 時以 body 為優先（不讀檔）
  - body 為空且無 prz_config.json → 拋錯
  - 缺 preview 不致失敗（_decode_preview_rgb(None) 回 None）
"""

import json
import shutil
import uuid

import pytest

from agent.api_v2 import _decode_preview_rgb, _resolve_prz_download_config
from agent.jobs import get_job_dir


@pytest.fixture()
def job_with_prz_config():
    """建立一個含 prz_config.json 的暫時 job 目錄，測後清除。"""
    job_id = f"test_{uuid.uuid4().hex}"
    job_dir = get_job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    prz_config = {
        "Machine": {"machine_type": "sonic_4k_2022"},
        "Print": {"Layer Height": 0.05, "Exposure Time": 2.5},
    }
    with open(job_dir / "prz_config.json", "w") as f:
        json.dump(prz_config, f)
    yield job_id, prz_config
    shutil.rmtree(job_dir, ignore_errors=True)


class TestPrzDownloadConfigFallback:
    def test_empty_body_falls_back_to_persisted(self, job_with_prz_config):
        """body 為空 → 從 prz_config.json 讀取並回傳。"""
        job_id, prz_config = job_with_prz_config
        resolved = _resolve_prz_download_config(job_id, {})
        assert resolved == prz_config

    def test_explicit_body_takes_priority(self, job_with_prz_config):
        """body 顯式提供 config → 以 body 為優先，不讀檔。"""
        job_id, prz_config = job_with_prz_config
        body = {"Print": {"Layer Height": 0.10}}
        resolved = _resolve_prz_download_config(job_id, body)
        assert resolved == body
        assert resolved != prz_config

    def test_empty_body_no_persisted_raises(self):
        """body 為空且無 prz_config.json → 拋錯。"""
        job_id = f"test_missing_{uuid.uuid4().hex}"  # 不建立目錄/檔案
        with pytest.raises(Exception):
            _resolve_prz_download_config(job_id, {})

    def test_missing_preview_returns_none(self):
        """缺 preview 不致失敗：_decode_preview_rgb(None) 回 None。"""
        assert _decode_preview_rgb(None) is None