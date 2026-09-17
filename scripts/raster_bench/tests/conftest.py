"""Shared fixtures for the raster benchmark tool tests.

Run from the repository root:  .venv\\Scripts\\python.exe -m pytest scripts/raster_bench/tests

Nothing here touches patient data, the real ``work/`` directory, the committed
manifest on disk, or a real slicer engine: source models are synthetic
tetrahedra, every tool writes under pytest's tmp_path, and engine runs are
replaced by fakes that write minimal archives.
"""
from __future__ import annotations

import copy
import os
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

BENCH_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_DIR))

import make_fixtures as fx  # noqa: E402

REAL_MANIFEST = fx.load_manifest()


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch):
    """No test may see a models directory or SLA_* switches from the developer's shell."""
    monkeypatch.delenv(fx.MODELS_ENV, raising=False)
    for name in [n for n in list(os.environ) if n.upper().startswith("SLA_")]:
        monkeypatch.delenv(name, raising=False)
    # Any accidental manifest write-back must fail loudly instead of editing the real file.
    monkeypatch.setattr(fx, "save_manifest", _forbidden_save_manifest)


def _forbidden_save_manifest(*args, **kwargs):
    raise AssertionError("tests must not write the committed manifest.json")


def write_tetra_stl(path: Path, attr: int = 7) -> Path:
    """A 10 mm tetrahedron as binary STL with non-zero attribute bytes."""
    v = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]], dtype=np.float32)
    faces = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (0, 3, 2)]
    records = np.zeros(len(faces), dtype=fx._STL_DTYPE)
    for i, face in enumerate(faces):
        tri = v[list(face)]
        normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
        records[i]["normal"] = normal / np.linalg.norm(normal)
        records[i]["vertices"] = tri
    records["attr"] = attr
    path.write_bytes(b"synthetic tetra".ljust(80, b" ") + np.uint32(len(records)).tobytes() + records.tobytes())
    return path


@pytest.fixture
def models_dir(tmp_path) -> Path:
    directory = tmp_path / "models"
    directory.mkdir()
    write_tetra_stl(directory / "tetra.stl")
    return directory


@pytest.fixture
def manifest(models_dir) -> dict:
    """The real machines and raster params with synthetic cases.

    Cases: ``layout-x2`` (two tetrahedra, no support), ``slab`` (no support) and
    ``slab-frozen`` (a slab whose support mode is frozen, sha256 not yet set).
    No model hash is recorded yet; building a case records it into this dict.
    """
    data = copy.deepcopy(REAL_MANIFEST)
    data["sources"] = {"tetra": {"filename": "tetra.stl", "sha256": fx.sha256_file(models_dir / "tetra.stl")}}
    data["cases"] = [
        {"id": "layout-x2", "role": "test", "machine": "sonic_mighty_revo_16k",
         "geometry": {"type": "layout", "source": "tetra", "offsets_mm": [[0.0, 0.0], [20.0, 0.0]]},
         "model": {"sha256": None, "geometry_sha256": None},
         "support": {"mode": "none", "sha256": None}},
        {"id": "slab", "role": "test", "machine": "sonic_mighty_revo_16k",
         "geometry": {"type": "slab", "size_mm": [20.0, 10.0, 2.0]},
         "model": {"sha256": None, "geometry_sha256": None},
         "support": {"mode": "none", "sha256": None}},
        {"id": "slab-frozen", "role": "test", "machine": "sonic_mighty_revo_16k",
         "geometry": {"type": "slab", "size_mm": [20.0, 10.0, 2.0]},
         "model": {"sha256": None, "geometry_sha256": None},
         "support": {"mode": "frozen", "sha256": None}},
    ]
    return data


def case_of(manifest: dict, case_id: str) -> dict:
    return fx.select_cases(manifest, [case_id])[0]


def write_zip(path: Path, entries: dict[str, bytes], year: int = 2024,
              compression: int = zipfile.ZIP_DEFLATED) -> Path:
    with zipfile.ZipFile(path, "w", compression) as zf:
        for name, data in entries.items():
            zf.writestr(zipfile.ZipInfo(name, date_time=(year, 1, 1, 0, 0, 0)), data, compress_type=compression)
    return path
