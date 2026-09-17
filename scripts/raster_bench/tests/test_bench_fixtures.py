"""make_fixtures.py: deterministic layouts, model directory rules, support freezing refusals."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest

import make_fixtures as fx
from conftest import case_of


def build(manifest, case_id, models_dir, work_dir) -> Path:
    fx.build_case(manifest, case_of(manifest, case_id), models_dir, work_dir)
    return work_dir / "fixtures" / case_id


# ── determinism ───────────────────────────────────────────────────────────────

def test_layout_is_byte_identical_across_builds(manifest, models_dir, tmp_path):
    first = build(manifest, "layout-x2", models_dir, tmp_path / "w1")
    second = build(manifest, "layout-x2", models_dir, tmp_path / "w2")

    for name in ("model.stl", "config.ini", "fixture.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_layout_places_copies_centred_with_zero_attributes(manifest, models_dir, tmp_path):
    out = build(manifest, "layout-x2", models_dir, tmp_path / "w")
    triangles = fx.read_binary_stl(out / "model.stl")
    flat = triangles["vertices"].reshape(-1, 3)

    assert len(triangles) == 8
    assert (triangles["attr"] == 0).all()
    np.testing.assert_allclose(flat.min(axis=0), [-15, -5, 0])
    np.testing.assert_allclose(flat.max(axis=0), [15, 5, 10])
    assert json.loads((out / "fixture.json").read_text())["model_stl"]["extent_mm"] == [30.0, 10.0, 10.0]


def test_first_build_records_model_and_geometry_then_verifies(manifest, models_dir, tmp_path):
    case = case_of(manifest, "layout-x2")
    first = fx.build_case(manifest, case, models_dir, tmp_path / "w")
    model = tmp_path / "w" / "fixtures" / "layout-x2" / "model.stl"

    assert first["manifest"] == "recorded"
    assert case["model"] == {"sha256": fx.sha256_file(model), "geometry_sha256": fx.geometry_sha256(manifest, case)}
    assert fx.build_case(manifest, case, models_dir, tmp_path / "w2")["manifest"] == "verified"


def test_geometry_digest_tracks_layout_and_source(manifest):
    case = case_of(manifest, "layout-x2")
    original = fx.geometry_sha256(manifest, case)

    case["geometry"]["offsets_mm"][1] = [21.0, 0.0]
    moved = fx.geometry_sha256(manifest, case)
    manifest["sources"]["tetra"]["sha256"] = "0" * 64
    assert len({original, moved, fx.geometry_sha256(manifest, case)}) == 3


def test_changed_layout_with_recorded_model_is_refused(manifest, models_dir, tmp_path):
    case = case_of(manifest, "layout-x2")
    fx.build_case(manifest, case, models_dir, tmp_path / "w")
    old_bytes = (tmp_path / "w" / "fixtures" / "layout-x2" / "model.stl").read_bytes()
    case["geometry"]["offsets_mm"][1] = [25.0, 0.0]

    with pytest.raises(fx.FixtureError, match="manifest records model sha256"):
        fx.build_case(manifest, case, models_dir, tmp_path / "w2")
    assert not (tmp_path / "w2" / "fixtures" / "layout-x2" / "model.stl").exists()
    assert not list((tmp_path / "w2" / "fixtures" / "layout-x2").glob("*.new"))
    with pytest.raises(fx.FixtureError, match="manifest records model sha256"):
        fx.build_case(manifest, case, models_dir, tmp_path / "w")
    assert (tmp_path / "w" / "fixtures" / "layout-x2" / "model.stl").read_bytes() == old_bytes


def test_main_writes_manifest_only_when_a_model_is_recorded(manifest, models_dir, tmp_path):
    saved = []
    argv = ["--models", str(models_dir), "--work", str(tmp_path / "w"), "--case", "layout-x2"]
    with mock.patch.object(fx, "load_manifest", side_effect=lambda: json.loads(json.dumps(manifest))), \
            mock.patch.object(fx, "save_manifest", side_effect=lambda m: saved.append(m)):
        assert fx.main(argv) == 0
        assert len(saved) == 1 and case_of(saved[0], "layout-x2")["model"]["sha256"] is not None
        manifest["cases"] = saved[0]["cases"]
        assert fx.main(argv) == 0
    assert len(saved) == 1


@pytest.mark.parametrize("mutate, message", [
    (lambda c: c.pop("model"), "'model' must be"),
    (lambda c: c.update(model={"sha256": "a" * 64, "geometry_sha256": None}), "both null or both set"),
    (lambda c: c["support"].update(sha256="b" * 64), "frozen support is bound to model None"),
    (lambda c: (c.update(model={"sha256": "a" * 64, "geometry_sha256": "g" * 64}),
                c["support"].update(sha256="b" * 64, model_sha256="c" * 64)), "bound to model " + "c" * 64),
])
def test_load_manifest_rejects_inconsistent_model_records(manifest, tmp_path, mutate, message):
    mutate(case_of(manifest, "slab-frozen"))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(fx.FixtureError, match=message):
        fx.load_manifest(path)


def test_committed_manifest_binds_every_frozen_support_to_its_model():
    manifest = fx.load_manifest()

    for case in manifest["cases"]:
        assert case["model"]["geometry_sha256"] == fx.geometry_sha256(manifest, case), case["id"]
        if case["support"]["mode"] == "frozen":
            assert case["support"]["sha256"] is not None
            assert case["support"]["model_sha256"] == case["model"]["sha256"], case["id"]


def test_rebuild_reports_unchanged_and_tampered_fixture_is_not_overwritten(manifest, models_dir, tmp_path):
    work = tmp_path / "w"
    case = case_of(manifest, "layout-x2")
    fx.build_case(manifest, case, models_dir, work)

    assert fx.build_case(manifest, case, models_dir, work)["model.stl"] == "unchanged"
    model = work / "fixtures" / "layout-x2" / "model.stl"
    model.write_bytes(model.read_bytes() + b"x")
    with pytest.raises(fx.FixtureError, match="refusing to overwrite model.stl"):
        fx.build_case(manifest, case, models_dir, work)
    assert model.read_bytes().endswith(b"x")


def test_config_ini_comes_from_sla_config_with_manifest_params(manifest, models_dir, tmp_path):
    ini = (build(manifest, "layout-x2", models_dir, tmp_path / "w") / "config.ini").read_text()

    for line in ("blur = 0", "anti_aliasing_level = 1", "gray_level = 1", "supports_enable = 0",
                 "pad_enable = 0", "display_pixels_x = 15120", "printer_technology = SLA"):
        assert line in ini.splitlines(), line


def test_overlapping_layout_is_refused(manifest, models_dir, tmp_path):
    case_of(manifest, "layout-x2")["geometry"]["offsets_mm"] = [[0.0, 0.0], [5.0, 0.0]]

    with pytest.raises(fx.FixtureError, match="overlap"):
        build(manifest, "layout-x2", models_dir, tmp_path / "w")


def test_plate_larger_than_bed_is_refused(manifest, tmp_path):
    case_of(manifest, "slab")["geometry"]["size_mm"] = [300.0, 10.0, 2.0]

    with pytest.raises(fx.FixtureError, match="does not fit"):
        build(manifest, "slab", None, tmp_path / "w")


# ── source models ─────────────────────────────────────────────────────────────

def test_source_hash_mismatch_is_refused_and_writes_no_model(manifest, models_dir, tmp_path):
    manifest["sources"]["tetra"]["sha256"] = "0" * 64

    with pytest.raises(fx.FixtureError, match="'tetra.stl' sha256 mismatch"):
        build(manifest, "layout-x2", models_dir, tmp_path / "w")
    assert not (tmp_path / "w" / "fixtures" / "layout-x2" / "model.stl").exists()


def test_source_is_found_in_subdirectories_but_must_be_unique(manifest, models_dir, tmp_path):
    (models_dir / "a").mkdir()
    (models_dir / "tetra.stl").rename(models_dir / "a" / "tetra.stl")
    build(manifest, "layout-x2", models_dir, tmp_path / "w")

    (models_dir / "b").mkdir()
    (models_dir / "b" / "tetra.stl").write_bytes((models_dir / "a" / "tetra.stl").read_bytes())
    with pytest.raises(fx.FixtureError, match="ambiguous"):
        build(manifest, "layout-x2", models_dir, tmp_path / "w2")


def test_missing_models_directory_fails_without_guessing(tmp_path, capsys):
    code = fx.main(["--work", str(tmp_path / "w"), "--case", "primary-16k-guide-x8"])

    assert code == 1
    err = capsys.readouterr().err
    assert "--models" in err and fx.MODELS_ENV in err
    assert not (tmp_path / "w").exists()


def test_models_env_pointing_nowhere_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(fx.MODELS_ENV, str(tmp_path / "nowhere"))

    assert fx.main(["--work", str(tmp_path / "w"), "--case", "tiny-16k-crown-x1"]) == 1
    assert "does not exist" in capsys.readouterr().err


def test_fullplate_slab_needs_no_models_directory(tmp_path, capsys):
    """The committed manifest's slab case builds with no --models and no env var."""
    assert fx.main(["--work", str(tmp_path / "w1"), "--case", "fullplate-16k-slab"]) == 0
    assert fx.main(["--work", str(tmp_path / "w2"), "--case", "fullplate-16k-slab"]) == 0

    one = tmp_path / "w1" / "fixtures" / "fullplate-16k-slab"
    two = tmp_path / "w2" / "fixtures" / "fullplate-16k-slab"
    assert fx.sha256_file(one / "model.stl") == fx.sha256_file(two / "model.stl")
    record = json.loads((one / "fixture.json").read_text())
    assert record["model_stl"]["extent_mm"] == [200.0, 110.0, 2.0]
    assert record["model_stl"]["triangles"] == 12
    assert record["source"] is None


def test_manifest_records_no_absolute_paths():
    text = fx.MANIFEST_PATH.read_text(encoding="utf-8")

    assert ":\\" not in text and ":/" not in text and '"/' not in text


# ── freeze-support ────────────────────────────────────────────────────────────

def test_freeze_refuses_existing_support_stl(manifest, tmp_path):
    out = build(manifest, "slab-frozen", None, tmp_path / "w")
    (out / "support.stl").write_bytes(b"old")

    with pytest.raises(fx.FixtureError, match="refusing to overwrite existing"):
        fx.freeze_support(manifest, case_of(manifest, "slab-frozen"), tmp_path / "w", tmp_path / "engine")
    assert (out / "support.stl").read_bytes() == b"old"


def test_freeze_refuses_when_manifest_already_has_a_hash(manifest, tmp_path):
    build(manifest, "slab-frozen", None, tmp_path / "w")
    case_of(manifest, "slab-frozen")["support"]["sha256"] = "a" * 64

    with pytest.raises(fx.FixtureError, match="frozen only once"):
        fx.freeze_support(manifest, case_of(manifest, "slab-frozen"), tmp_path / "w", tmp_path / "engine")


def test_freeze_refuses_model_not_recorded_in_manifest(manifest, tmp_path):
    build(manifest, "slab-frozen", None, tmp_path / "w")
    case_of(manifest, "slab-frozen")["geometry"]["size_mm"] = [21.0, 10.0, 2.0]
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / fx.ENGINE_EXE).write_bytes(b"fake engine")

    with mock.patch.object(fx.subprocess, "run") as run:
        with pytest.raises(fx.FixtureError, match="is not the model recorded in manifest.json"):
            fx.freeze_support(manifest, case_of(manifest, "slab-frozen"), tmp_path / "w", engine)
    run.assert_not_called()


def test_freeze_requires_engine_flag_pairing(capsys):
    with pytest.raises(SystemExit) as exc:
        fx.main(["--freeze-support"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit):
        fx.main(["--engine", "x"])


def test_freeze_runs_support_export_and_records_hash(manifest, tmp_path):
    """Success path with the engine and classifier mocked; the manifest write is captured."""
    work = tmp_path / "w"
    out = build(manifest, "slab-frozen", None, work)
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / fx.ENGINE_EXE).write_bytes(b"fake engine")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        output = Path(cmd[cmd.index("--output") + 1])
        (output.parent / "model_support.stl").write_bytes(b"support mesh")
        return subprocess.CompletedProcess(cmd, 0, b"done\n", b"")

    saved = []
    verdict = SimpleNamespace(has_support_mesh=True)
    with mock.patch.object(fx.subprocess, "run", side_effect=fake_run), \
            mock.patch.object(fx, "classify_support_result", return_value=verdict), \
            mock.patch.object(fx, "save_manifest", side_effect=lambda m: saved.append(json.loads(json.dumps(m)))):
        result = fx.freeze_support(manifest, case_of(manifest, "slab-frozen"), work, engine)

    cmd = calls[0]
    assert "--export-support-stl" in cmd and "--export-sla" not in cmd
    assert cmd[-1] == str(out / "model.stl")
    assert (out / "support.stl").read_bytes() == b"support mesh"
    assert result["sha256"] == fx.sha256_file(out / "support.stl")
    recorded = case_of(saved[0], "slab-frozen")["support"]
    assert recorded["sha256"] == result["sha256"]
    assert recorded["model_sha256"] == fx.sha256_file(out / "model.stl")
    assert recorded["model_sha256"] == case_of(saved[0], "slab-frozen")["model"]["sha256"]
    assert recorded["frozen_with"]["engine_exe_sha256"] == fx.sha256_file(engine / fx.ENGINE_EXE)
    assert not list(out.glob(".freeze-*"))


def test_freeze_without_support_mesh_fails_and_keeps_logs(manifest, tmp_path):
    work = tmp_path / "w"
    out = build(manifest, "slab-frozen", None, work)
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / fx.ENGINE_EXE).write_bytes(b"fake engine")
    verdict = SimpleNamespace(has_support_mesh=False, status=SimpleNamespace(value="failed"),
                              error_code="X", support_outcome="none")

    with mock.patch.object(fx.subprocess, "run",
                           return_value=subprocess.CompletedProcess([], 1, b"out", b"boom")), \
            mock.patch.object(fx, "classify_support_result", return_value=verdict):
        with pytest.raises(fx.FixtureError, match="produced no support mesh"):
            fx.freeze_support(manifest, case_of(manifest, "slab-frozen"), work, engine)

    assert not (out / "support.stl").exists()
    assert (out / "freeze_support.stderr.log").read_bytes() == b"boom"
