"""Tests for jobs.get_layer_png_from_sl1() across RLE / PNG output
(spec: sl1-layer-access「單層取用支援 RLE 即時解碼，失敗回 None」, Task 3.2).

Pre-fix: only .png layers were located, so RLE-mode .sl1 always returned None
(the /layers/{idx}.png endpoint was effectively broken under SLA_LAYER_RLE).

No mocks: builds real .sl1 archives under a monkeypatched JOBS_DIR and exercises
the real function end-to-end.
"""

import io
import zipfile

import numpy as np
import pytest
from PIL import Image

import agent.jobs as jobs
from agent.prz_encoder import _rle_encode_layer


_W, _H = 8, 4


def _gray(marker: int) -> np.ndarray:
    """Distinct grayscale pattern per layer so we can assert the correct one."""
    g = np.zeros((_H, _W), dtype=np.uint8)
    g[0, :] = marker  # marker row distinguishes layers
    g[2, 1:4] = 200
    return g


def _make_job(tmp_path, monkeypatch, *, mode: str, n: int, with_ini: bool = True):
    """Create jobs/<id>/output/model.sl1 under a temp JOBS_DIR; return job_id + grays."""
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    job_id = "job0001"
    out_dir = tmp_path / job_id / "output"
    out_dir.mkdir(parents=True)
    grays = [_gray(10 + i) for i in range(n)]

    with zipfile.ZipFile(out_dir / "model.sl1", "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("config.ini", "printTime = 100\n")
        if with_ini:
            zf.writestr("prusaslicer.ini", f"display_pixels_x = {_W}\ndisplay_pixels_y = {_H}\n")
        for i, g in enumerate(grays):
            if mode == "rle":
                zf.writestr(f"model{i:05d}.rle", _rle_encode_layer(g))
            else:
                buf = io.BytesIO()
                Image.fromarray(g, "L").save(buf, format="PNG")
                zf.writestr(f"model{i:05d}.png", buf.getvalue())
    return job_id, grays


# ---------------------------------------------------------------------------
# 正常：RLE 合法 index → 正確 PNG bytes
# ---------------------------------------------------------------------------

def test_rle_valid_index_returns_decoded_png(tmp_path, monkeypatch):
    job_id, grays = _make_job(tmp_path, monkeypatch, mode="rle", n=3)

    for idx in range(3):
        png = jobs.get_layer_png_from_sl1(job_id, idx)
        assert png is not None
        img = Image.open(io.BytesIO(png))
        assert img.format == "PNG"
        assert img.size == (_W, _H)
        # 回傳的正是該 index 的層（marker row 相符）。
        assert np.array_equal(np.asarray(img.convert("L")), grays[idx])


def test_png_mode_still_works(tmp_path, monkeypatch):
    job_id, grays = _make_job(tmp_path, monkeypatch, mode="png", n=2)

    png = jobs.get_layer_png_from_sl1(job_id, 1)
    assert png is not None
    img = Image.open(io.BytesIO(png))
    assert np.array_equal(np.asarray(img.convert("L")), grays[1])


# ---------------------------------------------------------------------------
# 越界 → None
# ---------------------------------------------------------------------------

def test_index_out_of_range_returns_none(tmp_path, monkeypatch):
    job_id, _ = _make_job(tmp_path, monkeypatch, mode="rle", n=3)

    assert jobs.get_layer_png_from_sl1(job_id, -1) is None
    assert jobs.get_layer_png_from_sl1(job_id, 3) is None      # == N
    assert jobs.get_layer_png_from_sl1(job_id, 999) is None


# ---------------------------------------------------------------------------
# 解碼失敗（缺解析度）→ None
# ---------------------------------------------------------------------------

def test_rle_missing_resolution_returns_none(tmp_path, monkeypatch):
    # 無 prusaslicer.ini → rle_layer_to_png 回 None → 上層回 None（→404）
    job_id, _ = _make_job(tmp_path, monkeypatch, mode="rle", n=2, with_ini=False)

    assert jobs.get_layer_png_from_sl1(job_id, 0) is None


# ---------------------------------------------------------------------------
# 檔案不存在 → None
# ---------------------------------------------------------------------------

def test_missing_sl1_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    assert jobs.get_layer_png_from_sl1("nonexistent", 0) is None