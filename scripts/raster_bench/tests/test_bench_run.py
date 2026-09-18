"""run_bench.py: input verification, engine invocation, outputs and failure paths.

The engine is replaced by a fake ``run_engine`` that writes minimal archives,
so failure paths a real engine rarely produces (non-zero exit, a missing
preview zip) are exercised deterministically. One test runs a real child
process through ``run_engine`` to check timestamps, stderr capture and the
GetProcessMemoryInfo probe.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest

import make_fixtures as fx
import run_bench as rb
from conftest import case_of, write_zip

RASTER_TIMING = {"layers": 2, "threads": 8, "wall_s": 1.2, "thread_s": {"reset": 0.1}}
# The bench fixture stubs hardware_threads; tests that need the real one take it from here.
REAL_HARDWARE_THREADS = rb.hardware_threads


# ── helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture
def bench(manifest, tmp_path):
    """A work dir with built slab fixtures, a fake engine dir and the synthetic manifest loaded.

    The machine is pinned to 8 hardware threads so thread counts in meta.json do
    not depend on the machine running the tests.
    """
    work = tmp_path / "work"
    for case_id in ("slab", "slab-frozen"):
        fx.build_case(manifest, case_of(manifest, case_id), None, work)
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / fx.ENGINE_EXE).write_bytes(b"fake engine")
    if rb.ENGINE_CORE is not None:
        (engine / rb.ENGINE_CORE).write_bytes(b"fake core library")
    with mock.patch.object(rb.fx, "load_manifest", side_effect=lambda: json.loads(json.dumps(manifest))), \
            mock.patch.object(rb, "hardware_threads", return_value=(8, "test")):
        yield {"work": work, "engine": engine, "manifest": manifest, "tmp": tmp_path}


def freeze(bench, content=b"frozen support mesh"):
    support = bench["work"] / "fixtures" / "slab-frozen" / "support.stl"
    support.write_bytes(content)
    case = case_of(bench["manifest"], "slab-frozen")
    case["support"]["sha256"] = fx.sha256_file(support)
    case["support"]["model_sha256"] = case["model"]["sha256"]
    return support


def fake_engine(exit_code=0, write_sl1=True, write_preview=True, stderr=None, memory=None):
    """A run_engine replacement; records (cmd, env, cwd) of every call on .calls."""
    calls = []

    def run(cmd, env, cwd):
        calls.append({"cmd": cmd, "env": env, "cwd": Path(cwd)})
        sl1 = Path(cmd[cmd.index("--output") + 1])
        ext = "rle" if env.get("SLA_LAYER_RLE") else "png"
        if write_sl1:
            write_zip(sl1, {"config.ini": b"x", "prusaslicer.ini": b"y",
                            f"model00000.{ext}": b"layer0", f"model00001.{ext}": b"layer1"})
        if write_preview:
            write_zip(sl1.with_name("model_preview.zip"),
                      {"model_preview00000.png": b"p0", "model_preview00001.png": b"p1"})
        return {
            "exit_code": exit_code,
            "total_wall_s": 2.0,
            "stdout_lines": [
                (0.10, b" 70% => Merging slices and calculating statistics\r\n"),
                (0.20, b" 73% => Rasterizing layers\r\n"),
                (1.50, b"100% => Rasterizing layers\r\n"),
                (1.70, b"100% => Slicing done\r\n"),
            ],
            "stderr": stderr if stderr is not None else
            ("[raster-timing] " + json.dumps(RASTER_TIMING) + "\n").encode(),
            "memory": memory if memory is not None else {
                "peak_working_set_bytes": 123456789, "peak_pagefile_usage_bytes": 234567890,
                "memory_source": "GetProcessMemoryInfo", "memory_note": None},
        }

    run.calls = calls
    return run


def run_main(bench, *extra, case="slab", engine=None):
    engine = engine or fake_engine()
    argv = ["--work", str(bench["work"]), "--engine", str(bench["engine"]), "--case", case,
            "--build", "base", "--repeat", "1", "--platform", "windows", *extra]
    with mock.patch.object(rb, "run_engine", side_effect=engine) as patched:
        code = rb.main(argv)
    return code, engine.calls, patched


def runs(bench):
    return sorted(p.name for p in (bench["work"] / "runs").iterdir()) if (bench["work"] / "runs").exists() else []


# ── success ───────────────────────────────────────────────────────────────────

def test_successful_run_writes_fingerprints_timing_and_meta(bench, capsys):
    code, calls, _ = run_main(bench, "--threads", "8")

    assert code == 0
    run_dir = bench["work"] / "runs" / "windows-base-slab-t8-r1"
    assert sorted(p.name for p in run_dir.iterdir()) == [
        "layers.sha256", "meta.json", "preview.sha256", "stderr.log", "stdout.log", "timing.json"]
    assert [line.split("  ")[0] for line in (run_dir / "layers.sha256").read_text().splitlines()] == [
        "model00000.rle", "model00001.rle"]
    assert (run_dir / "preview.sha256").read_text().count("\n") == 2

    timing = json.loads((run_dir / "timing.json").read_text())
    assert timing["rasterizing_wall_s"] == pytest.approx(1.5)
    assert timing["raster_timing"] == [RASTER_TIMING]
    assert timing["peak_working_set_bytes"] == 123456789
    assert timing["memory_source"] == "GetProcessMemoryInfo" and timing["memory_note"] is None
    assert timing["total_wall_s"] == 2.0

    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["threads"] == 8 and meta["threads_requested"] == 8
    assert meta["schema_version"] == 2 and meta["repeat"] == 1 and meta["platform"] == "windows"
    assert meta["engine"]["exe_sha256"] == fx.sha256_file(bench["engine"] / fx.ENGINE_EXE)
    assert meta["counts"] == {"layers": 2, "preview": 2}
    assert meta["excluded_entries"]["layers"] == ["config.ini", "prusaslicer.ini"]
    assert meta["env"] == {"SLA_LAYER_RLE": "1"}
    assert meta["variant"] == {"label": None, "disable_rle": False, "raster_param_overrides": {}}
    assert str(bench["tmp"]) not in json.dumps(meta)
    assert json.loads(capsys.readouterr().out)["run"] == "windows-base-slab-t8-r1"


def test_command_mirrors_run_slicing(bench):
    code, calls, _ = run_main(bench, "--threads", "2")
    cmd, env = calls[0]["cmd"], calls[0]["env"]
    fixture = bench["work"] / "fixtures" / "slab"

    assert code == 0
    assert cmd[0] == str(bench["engine"] / fx.ENGINE_EXE)
    assert cmd[1:4] == ["--export-sla", "--export-preview-pngs", "0.1"]
    assert cmd[cmd.index("--center") + 1] == "105.84,59.185"
    assert cmd[cmd.index("--load") + 1] == str(fixture / "config.ini")
    assert cmd[cmd.index("--threads") + 1] == "2"
    assert cmd[-1] == str(fixture / "model.stl")
    assert "--import-support-stl" not in cmd and "--export-support-stl" not in cmd
    assert env["SLA_LAYER_RLE"] == "1"


def test_default_threads_omits_flag(bench):
    code, calls, _ = run_main(bench)

    assert code == 0
    assert "--threads" not in calls[0]["cmd"]
    assert runs(bench) == ["windows-base-slab-tdefault-r1"]


def test_default_threads_records_hardware_count_not_null(bench):
    code, _, _ = run_main(bench)
    meta = json.loads((bench["work"] / "runs" / "windows-base-slab-tdefault-r1" / "meta.json").read_text())

    assert code == 0
    assert meta["threads"] == 8
    assert meta["threads_requested"] is None


def test_requested_threads_are_capped_at_hardware_count(bench):
    code, calls, _ = run_main(bench, "--threads", "12")
    meta = json.loads((bench["work"] / "runs" / "windows-base-slab-t12-r1" / "meta.json").read_text())

    assert code == 0
    assert calls[0]["cmd"][calls[0]["cmd"].index("--threads") + 1] == "12"
    assert meta["threads"] == 8
    assert meta["threads_requested"] == 12


def test_meta_records_threads_source(bench):
    code, _, _ = run_main(bench)
    meta = json.loads((bench["work"] / "runs" / "windows-base-slab-tdefault-r1" / "meta.json").read_text())

    assert code == 0
    assert meta["threads_source"] == "test"


@pytest.mark.parametrize("requested, expected", [(None, 6), (1, 1), (6, 6), (16, 6)])
def test_effective_threads_follows_engine_rule(monkeypatch, requested, expected):
    monkeypatch.setattr(rb, "hardware_threads", lambda: (6, "fake"))
    assert rb.effective_threads(requested) == (expected, "fake")


# ── hardware thread count: the oneTBB rule (pure) ─────────────────────────────

@pytest.mark.parametrize("mask, group, all_groups, expected", [
    (0xFF, 8, 8, 8),                 # unrestricted, one group
    (0x0F, 8, 8, 4),                 # affinity restricted to four processors
    (0x01, 8, 8, 1),                 # a single processor
    ((1 << 64) - 1, 64, 128, 128),   # unrestricted, two full groups
])
def test_threads_from_affinity_follows_tbb_rule(mask, group, all_groups, expected):
    assert rb.threads_from_affinity(mask, group, all_groups) == expected


def test_zero_affinity_mask_is_refused():
    with pytest.raises(rb.BenchError, match="several processor groups"):
        rb.threads_from_affinity(0, 8, 8)


def test_all_groups_count_below_mask_is_refused():
    with pytest.raises(rb.BenchError, match="GetActiveProcessorCount returned 4"):
        rb.threads_from_affinity(0xFF, 8, 4)


# ── hardware thread count: Windows call failures (fake kernel32) ──────────────

class FakeKernel32:
    """Stands in for kernel32; each call's return value is configurable."""

    def __init__(self, affinity_ok=True, process_mask=0xFF, processors=8, all_groups=8):
        self.affinity_ok, self.process_mask = affinity_ok, process_mask
        self.processors, self.all_groups = processors, all_groups

    def GetCurrentProcess(self):
        return -1

    def GetProcessAffinityMask(self, handle, process_mask, system_mask):
        if not self.affinity_ok:
            return 0
        process_mask._obj.value = self.process_mask
        system_mask._obj.value = self.process_mask
        return 1

    def GetNativeSystemInfo(self, info):
        info._obj.dwNumberOfProcessors = self.processors

    def GetActiveProcessorCount(self, group):
        return self.all_groups


def fake_loader(kernel32):
    """A _load_kernel32 replacement; only dwNumberOfProcessors of SYSTEM_INFO is read."""
    import ctypes

    class SystemInfo(ctypes.Structure):
        _fields_ = [("dwNumberOfProcessors", ctypes.c_ulong)]

    return lambda: (kernel32, ctypes.c_size_t, SystemInfo)


def test_fake_kernel32_restricted_affinity_is_counted(monkeypatch):
    monkeypatch.setattr(rb, "_load_kernel32", fake_loader(FakeKernel32(process_mask=0b1010)))
    assert rb._windows_hardware_threads() == 2


def test_affinity_call_failure_is_refused(monkeypatch):
    monkeypatch.setattr(rb, "_load_kernel32", fake_loader(FakeKernel32(affinity_ok=False)))
    with pytest.raises(rb.BenchError, match="GetProcessAffinityMask failed"):
        rb._windows_hardware_threads()


def test_active_processor_count_failure_is_refused(monkeypatch):
    monkeypatch.setattr(rb, "_load_kernel32", fake_loader(FakeKernel32(all_groups=0)))
    with pytest.raises(rb.BenchError, match="GetActiveProcessorCount failed"):
        rb._windows_hardware_threads()


@pytest.mark.parametrize("error", [OSError("kernel32 not loadable"), AttributeError("no GetActiveProcessorCount")])
def test_kernel32_load_error_is_refused(monkeypatch, error):
    def broken():
        raise error

    monkeypatch.setattr(rb, "_load_kernel32", broken)
    with pytest.raises(rb.BenchError, match="cannot query processor affinity") as exc:
        rb._windows_hardware_threads()
    assert exc.value.__cause__ is error


# ── hardware thread count: the real Windows call ──────────────────────────────

@pytest.mark.skipif(os.name != "nt", reason="GetProcessAffinityMask is Windows-only")
def test_real_affinity_count_is_within_cpu_count():
    count, source = rb.hardware_threads()
    assert 1 <= count <= os.cpu_count()
    assert source == "GetProcessAffinityMask"


def _hardware_threads_in_child(extra_env: dict) -> str:
    import subprocess

    env = {k: v for k, v in os.environ.items() if k != "PYTHON_CPU_COUNT"}
    env.update(extra_env)
    code = (f"import sys; sys.path.insert(0, {str(Path(rb.__file__).parent)!r}); "
            "import run_bench; print(run_bench.hardware_threads()[0])")
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.mark.skipif(os.name != "nt", reason="GetProcessAffinityMask is Windows-only")
def test_python_cpu_count_override_is_ignored():
    assert _hardware_threads_in_child({"PYTHON_CPU_COUNT": "1"}) == _hardware_threads_in_child({})


# ── hardware thread count: non-Windows fallbacks ──────────────────────────────

def test_posix_uses_sched_getaffinity(monkeypatch):
    monkeypatch.setattr(rb, "IS_WINDOWS", False)
    monkeypatch.setattr(rb.os, "sched_getaffinity", lambda pid: {0, 1, 2}, raising=False)
    assert rb.hardware_threads() == (3, "sched_getaffinity")


@pytest.mark.parametrize("env, xoptions", [({"PYTHON_CPU_COUNT": "4"}, {}), ({}, {"cpu_count": "4"})])
def test_macos_refuses_cpu_count_override(monkeypatch, env, xoptions):
    monkeypatch.setattr(rb, "IS_WINDOWS", False)
    monkeypatch.delattr(rb.os, "sched_getaffinity", raising=False)
    monkeypatch.delenv("PYTHON_CPU_COUNT", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(rb.sys, "_xoptions", xoptions)
    with pytest.raises(rb.BenchError, match="PYTHON_CPU_COUNT or -X cpu_count"):
        rb.hardware_threads()


def test_macos_falls_back_to_cpu_count(monkeypatch):
    monkeypatch.setattr(rb, "IS_WINDOWS", False)
    monkeypatch.delattr(rb.os, "sched_getaffinity", raising=False)
    monkeypatch.delenv("PYTHON_CPU_COUNT", raising=False)
    monkeypatch.setattr(rb.sys, "_xoptions", {})
    monkeypatch.setattr(rb.os, "cpu_count", lambda: 10)
    assert rb.hardware_threads() == (10, "cpu_count")


def test_macos_unknown_cpu_count_is_refused(monkeypatch):
    monkeypatch.setattr(rb, "IS_WINDOWS", False)
    monkeypatch.delattr(rb.os, "sched_getaffinity", raising=False)
    monkeypatch.delenv("PYTHON_CPU_COUNT", raising=False)
    monkeypatch.setattr(rb.sys, "_xoptions", {})
    monkeypatch.setattr(rb.os, "cpu_count", lambda: None)
    with pytest.raises(rb.BenchError, match="hardware threads"):
        rb.hardware_threads()


@pytest.mark.skipif(rb.ENGINE_CORE is None, reason="the core library is part of the identity on Windows only")
def test_meta_records_sha256_of_both_engine_binaries(bench):
    code, _, _ = run_main(bench)
    engine = json.loads((bench["work"] / "runs" / "windows-base-slab-tdefault-r1" / "meta.json").read_text())["engine"]

    assert code == 0
    assert engine["exe_sha256"] == fx.sha256_file(bench["engine"] / fx.ENGINE_EXE)
    assert engine["core_sha256"] == fx.sha256_file(bench["engine"] / rb.ENGINE_CORE)
    assert engine["exe_sha256"] != engine["core_sha256"]


@pytest.mark.skipif(rb.ENGINE_CORE is None, reason="the core library is part of the identity on Windows only")
def test_same_build_id_different_core_gives_different_identity(bench):
    (bench["engine"] / "engine_build_id.txt").write_text("20260904T070913Z")
    run_main(bench)
    (bench["engine"] / rb.ENGINE_CORE).write_bytes(b"another core library")
    run_main(bench, "--repeat", "2")
    first, second = (
        json.loads((bench["work"] / "runs" / f"windows-base-slab-tdefault-r{n}" / "meta.json").read_text())["engine"]
        for n in (1, 2)
    )

    assert first["exe_sha256"] == second["exe_sha256"]
    assert first["core_sha256"] != second["core_sha256"]


def test_archives_are_deleted_unless_kept(bench):
    run_main(bench)
    code, _, _ = run_main(bench, "--repeat", "2", "--keep-archives")

    assert code == 0
    assert not (bench["work"] / "runs" / "windows-base-slab-tdefault-r1" / "model.sl1").exists()
    kept = bench["work"] / "runs" / "windows-base-slab-tdefault-r2"
    assert (kept / "model.sl1").is_file() and (kept / "model_preview.zip").is_file()


def test_frozen_support_is_imported(bench):
    support = freeze(bench)
    code, calls, _ = run_main(bench, case="slab-frozen")
    cmd = calls[0]["cmd"]

    assert code == 0
    assert cmd[cmd.index("--import-support-stl") + 1] == str(support)
    assert "--export-support-stl" not in cmd


def test_inherited_sla_variables_are_dropped(bench, monkeypatch):
    monkeypatch.setenv("SLA_RASTER_FASTPATH", "0")
    code, calls, _ = run_main(bench, "--raster-env", "SLA_RASTER_TIMING=1")

    assert code == 0
    sla_env = {k: v for k, v in calls[0]["env"].items() if k.upper().startswith("SLA_")}
    assert sla_env == {"SLA_LAYER_RLE": "1", "SLA_RASTER_TIMING": "1"}
    meta = json.loads((bench["work"] / "runs" / "windows-base-slab-tdefault-r1" / "meta.json").read_text())
    assert meta["inherited_sla_env_dropped"] == ["SLA_RASTER_FASTPATH"]


def test_raster_env_does_not_change_params_hash(bench):
    run_main(bench)
    run_main(bench, "--repeat", "2", "--raster-env", "SLA_RASTER_VERIFY=1")

    metas = [json.loads((bench["work"] / "runs" / name / "meta.json").read_text()) for name in runs(bench)]
    assert metas[0]["params_sha256"] == metas[1]["params_sha256"]


# ── reference variants (task 0.16) ────────────────────────────────────────────

def test_disable_rle_leaves_layer_rle_unset(bench):
    run_main(bench)
    code, calls, _ = run_main(bench, "--disable-rle")

    assert code == 0
    assert "SLA_LAYER_RLE" not in calls[0]["env"]
    run_dir = bench["work"] / "runs" / "windows-base-slab-norle-tdefault-r1"
    assert (run_dir / "layers.sha256").read_text().splitlines()[0].startswith("model00000.png  ")
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["variant"]["disable_rle"] is True and meta["variant"]["label"] == "norle"
    assert meta["env"] == {}
    normal = json.loads((bench["work"] / "runs" / "windows-base-slab-tdefault-r1" / "meta.json").read_text())
    assert meta["params_sha256"] != normal["params_sha256"]


def test_raster_param_override_generates_run_config(bench):
    fixture_ini = bench["work"] / "fixtures" / "slab" / "config.ini"
    fixture_sha = fx.sha256_file(fixture_ini)
    code, calls, _ = run_main(bench, "--raster-param", "blur=1")

    assert code == 0
    run_dir = bench["work"] / "runs" / "windows-base-slab-blur1-tdefault-r1"
    cmd = calls[0]["cmd"]
    loaded = Path(cmd[cmd.index("--load") + 1])
    assert loaded.name == "config.ini" and loaded.parent != fixture_ini.parent
    run_ini = (run_dir / "config.ini").read_text().splitlines()
    assert "blur = 1" in run_ini and "anti_aliasing_level = 1" in run_ini
    assert fx.sha256_file(fixture_ini) == fixture_sha

    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["variant"]["raster_param_overrides"] == {"blur": 1}
    assert meta["params"]["raster_params"]["blur"] == 1
    assert meta["inputs"]["config_ini_sha256"] == fx.sha256_file(run_dir / "config.ini") != fixture_sha
    assert "<run>/config.ini" in meta["command"]
    assert calls[0]["env"]["SLA_LAYER_RLE"] == "1"


def test_variants_combine_in_label(bench):
    code, _, _ = run_main(bench, "--disable-rle", "--raster-param", "blur=1", "--raster-param", "anti_aliasing=0")

    assert code == 0
    assert runs(bench) == ["windows-base-slab-norle-antialiasing0-blur1-tdefault-r1"]


@pytest.mark.parametrize("item, message", [
    ("exposure=1", "not a raster param"),
    ("blur=0", "equals the manifest value"),
    ("blur=soft", "not a valid int"),
    ("anti_aliasing=maybe", "not a valid bool"),
    ("gamma_correction=x", "not a valid float"),
    ("blur", "expects KEY=VALUE"),
])
def test_invalid_raster_param_is_a_usage_error(bench, capsys, item, message):
    code, calls, _ = run_main(bench, "--raster-param", item)

    assert code == 2
    assert message in capsys.readouterr().err
    assert calls == [] and runs(bench) == []


def test_duplicate_raster_param_is_a_usage_error(bench, capsys):
    code, _, _ = run_main(bench, "--raster-param", "blur=1", "--raster-param", "blur=2")

    assert code == 2
    assert "more than once" in capsys.readouterr().err


# ── refusals before the engine runs ───────────────────────────────────────────

def assert_refused(bench, capsys, code, patched, *fragments):
    assert code == 1
    err = capsys.readouterr().err
    for fragment in fragments:
        assert fragment in err, (fragment, err)
    patched.assert_not_called()
    assert [name for name in runs(bench) if not name.startswith(".partial-")] == []
    assert not [p for p in (bench["work"] / "runs").glob(".partial-*")] if (bench["work"] / "runs").exists() else True


def test_frozen_support_hash_mismatch_is_refused(bench, capsys):
    support = freeze(bench)
    recorded = case_of(bench["manifest"], "slab-frozen")["support"]["sha256"]
    support.write_bytes(b"a different mesh")
    code, _, patched = run_main(bench, case="slab-frozen")

    assert_refused(bench, capsys, code, patched, "support.stl sha256 mismatch",
                   f"manifest {recorded}", f"actual {fx.sha256_file(support)}")
    assert support.read_bytes() == b"a different mesh"


def test_missing_frozen_support_is_refused_and_not_regenerated(bench, capsys):
    support = freeze(bench)
    support.unlink()
    code, _, patched = run_main(bench, case="slab-frozen")

    assert_refused(bench, capsys, code, patched, "missing frozen support", "support.stl")
    assert not support.exists()


def test_unfrozen_support_is_refused(bench, capsys):
    code, _, patched = run_main(bench, case="slab-frozen")

    assert_refused(bench, capsys, code, patched, "support is not frozen yet")


def test_tampered_model_is_refused(bench, capsys):
    model = bench["work"] / "fixtures" / "slab" / "model.stl"
    model.write_bytes(model.read_bytes() + b"x")
    code, _, patched = run_main(bench)

    assert_refused(bench, capsys, code, patched, "model.stl sha256 mismatch")


def test_config_not_matching_manifest_is_refused(bench, capsys):
    ini = bench["work"] / "fixtures" / "slab" / "config.ini"
    ini.write_text(ini.read_text().replace("blur = 0", "blur = 1"))
    code, _, patched = run_main(bench)

    assert_refused(bench, capsys, code, patched, "config.ini sha256", "differs from the manifest's config")


def test_model_not_recorded_in_manifest_is_refused(bench, capsys):
    """model.stl and fixture.json agree, but the manifest records a different model."""
    case_of(bench["manifest"], "slab")["model"]["sha256"] = "c" * 64
    code, _, patched = run_main(bench)

    assert_refused(bench, capsys, code, patched, "model.stl sha256 mismatch: manifest " + "c" * 64)


def test_unrecorded_model_is_refused(bench, capsys):
    case_of(bench["manifest"], "slab")["model"] = {"sha256": None, "geometry_sha256": None}
    code, _, patched = run_main(bench)

    assert_refused(bench, capsys, code, patched, "manifest has no model sha256 yet")


def test_edited_geometry_without_rebuild_is_refused(bench, capsys):
    """Changing the layout in the manifest must not silently benchmark the old model.stl."""
    case_of(bench["manifest"], "slab")["geometry"]["size_mm"] = [21.0, 10.0, 2.0]
    code, _, patched = run_main(bench)

    assert_refused(bench, capsys, code, patched, "manifest geometry changed since model.stl was recorded")


def test_support_frozen_for_another_model_is_refused(bench, capsys):
    freeze(bench)
    case_of(bench["manifest"], "slab-frozen")["support"]["model_sha256"] = "b" * 64
    code, _, patched = run_main(bench, case="slab-frozen")

    assert_refused(bench, capsys, code, patched, "support.stl was frozen for model " + "b" * 64)


def test_support_without_model_binding_is_refused(bench, capsys):
    freeze(bench)
    del case_of(bench["manifest"], "slab-frozen")["support"]["model_sha256"]
    code, _, patched = run_main(bench, case="slab-frozen")

    assert_refused(bench, capsys, code, patched, "support.stl was frozen for model None")


def test_fixture_built_from_other_source_is_refused(bench, capsys):
    record_path = bench["work"] / "fixtures" / "slab" / "fixture.json"
    record = json.loads(record_path.read_text())
    record["source"] = {"filename": "other.stl", "sha256": "0" * 64}
    record_path.write_text(json.dumps(record))
    code, _, patched = run_main(bench)

    assert_refused(bench, capsys, code, patched, "was not built from the manifest's current source")


def test_missing_fixture_is_refused(bench, capsys):
    (bench["work"] / "fixtures" / "slab" / "model.stl").unlink()
    code, _, patched = run_main(bench)

    assert_refused(bench, capsys, code, patched, "missing", "make_fixtures.py")


def test_missing_engine_is_refused(bench, capsys):
    (bench["engine"] / fx.ENGINE_EXE).unlink()
    code, _, patched = run_main(bench)

    assert_refused(bench, capsys, code, patched, "engine not found")


@pytest.mark.skipif(rb.ENGINE_CORE is None, reason="the core library is part of the identity on Windows only")
def test_missing_core_library_is_refused(bench, capsys):
    (bench["engine"] / rb.ENGINE_CORE).unlink()
    code, _, patched = run_main(bench)

    assert_refused(bench, capsys, code, patched, "engine core library not found")


def test_unknown_thread_count_refuses_run_without_partial(bench, capsys):
    with mock.patch.object(rb, "hardware_threads",
                           side_effect=rb.BenchError("cannot determine the number of hardware threads")):
        code, _, patched = run_main(bench)

    assert_refused(bench, capsys, code, patched, "cannot determine the number of hardware threads")
    assert not (bench["work"] / "runs").exists()


def test_kernel32_failure_through_main_refuses_run(bench, capsys, monkeypatch):
    def broken():
        raise AttributeError("function 'GetActiveProcessorCount' not found")

    # Undo the fixture's stub so main() goes through the Windows query itself.
    monkeypatch.setattr(rb, "hardware_threads", REAL_HARDWARE_THREADS)
    monkeypatch.setattr(rb, "IS_WINDOWS", True)
    monkeypatch.setattr(rb, "_load_kernel32", broken)
    code, _, patched = run_main(bench)

    assert_refused(bench, capsys, code, patched, "cannot query processor affinity", "GetActiveProcessorCount")
    assert not (bench["work"] / "runs").exists()


def test_existing_run_directory_is_never_overwritten(bench, capsys):
    run_main(bench)
    meta = (bench["work"] / "runs" / "windows-base-slab-tdefault-r1" / "meta.json").read_bytes()
    code, _, patched = run_main(bench)

    assert code == 1
    assert "refusing to overwrite" in capsys.readouterr().err
    patched.assert_not_called()
    assert (bench["work"] / "runs" / "windows-base-slab-tdefault-r1" / "meta.json").read_bytes() == meta


@pytest.mark.parametrize("extra", [
    ["--repeat", "0"], ["--threads", "0"], ["--build", "a/b"], ["--raster-env", "SLA_LAYER_RLE=0"],
    ["--raster-env", "sla_raster_x=1"],
])
def test_bad_arguments_exit_with_usage_error(bench, extra):
    with pytest.raises(SystemExit) as exc:
        run_main(bench, *extra)
    assert exc.value.code == 2


# ── engine failures (mocked) ──────────────────────────────────────────────────

def test_engine_nonzero_exit_fails_and_keeps_partial_logs(bench, capsys):
    code, calls, _ = run_main(bench, engine=fake_engine(exit_code=3, write_sl1=False, write_preview=False,
                                                        stderr=b"engine exploded\n"))

    assert code == 1
    err = capsys.readouterr().err
    assert "engine failed (exit 3" in err and "partial run kept for inspection" in err
    assert not (bench["work"] / "runs" / "windows-base-slab-tdefault-r1").exists()
    partials = list((bench["work"] / "runs").glob(".partial-windows-base-slab-tdefault-r1-*"))
    assert len(partials) == 1
    assert (partials[0] / "stderr.log").read_bytes() == b"engine exploded\n"
    assert not (partials[0] / "meta.json").exists()


def test_engine_nonzero_exit_fails_even_with_archive(bench, capsys):
    code, _, _ = run_main(bench, engine=fake_engine(exit_code=1))

    assert code == 1
    assert "engine failed (exit 1, .sl1 exists: True)" in capsys.readouterr().err


def test_zero_exit_without_sl1_fails(bench, capsys):
    code, _, _ = run_main(bench, engine=fake_engine(write_sl1=False))

    assert code == 1
    assert ".sl1 exists: False" in capsys.readouterr().err


def test_missing_preview_zip_fails(bench, capsys):
    code, _, _ = run_main(bench, engine=fake_engine(write_preview=False))

    assert code == 1
    assert "engine wrote no model_preview.zip" in capsys.readouterr().err
    assert not (bench["work"] / "runs" / "windows-base-slab-tdefault-r1").exists()


def test_archive_without_layer_entries_fails(bench, capsys):
    def engine(cmd, env, cwd):
        result = fake_engine()(cmd, env, cwd)
        write_zip(Path(cmd[cmd.index("--output") + 1]), {"config.ini": b"only metadata"})
        return result
    engine.calls = []

    code, _, _ = run_main(bench, engine=engine)

    assert code == 1
    assert "empty fingerprint: 0 layer entries" in capsys.readouterr().err


# ── progress and stderr parsing ───────────────────────────────────────────────

def test_rasterizing_wall_needs_start_and_following_label():
    assert rb.rasterizing_wall([{"t_s": 1.0, "percent": 70, "label": "Merging slices"}]) == (
        None, "no 'Rasterizing layers' progress line on stdout")
    assert rb.rasterizing_wall([{"t_s": 1.0, "percent": 73, "label": "Rasterizing layers"}])[0] is None
    events = [{"t_s": 1.0, "percent": 73, "label": "Rasterizing layers"},
              {"t_s": 3.0, "percent": 99, "label": "Rasterizing layers"},
              {"t_s": 3.5, "percent": 100, "label": "Slicing done"}]
    assert rb.rasterizing_wall(events) == (2.5, None)


def test_raster_timing_lines_are_parsed_and_bad_json_is_kept():
    stderr = b"noise\n[raster-timing] {\"layers\": 3}\n[raster-timing] {broken\n"
    records = rb.raster_timing_records(stderr)

    assert records[0] == {"layers": 3}
    assert "parse_error" in records[1] and records[1]["raw"] == "[raster-timing] {broken"


# ── non-Windows memory fallback ───────────────────────────────────────────────

def test_unmeasured_memory_is_recorded_as_null_with_warning(bench, capsys):
    code, _, _ = run_main(bench, engine=fake_engine(memory=rb.PeakMemoryProbe.unmeasured()))

    assert code == 0
    assert "warning: peak memory not measured" in capsys.readouterr().err
    timing = json.loads((bench["work"] / "runs" / "windows-base-slab-tdefault-r1" / "timing.json").read_text())
    assert timing["peak_working_set_bytes"] is None and timing["peak_pagefile_usage_bytes"] is None
    assert timing["memory_source"] is None and "Windows-only" in timing["memory_note"]


def test_run_engine_skips_probe_when_unsupported(tmp_path, monkeypatch):
    """With the probe unsupported the child still runs to completion; the probe is never built."""
    monkeypatch.setattr(rb, "MEMORY_PROBE_SUPPORTED", False)
    with mock.patch.object(rb, "PeakMemoryProbe", wraps=rb.PeakMemoryProbe) as probe_cls:
        probe_cls.unmeasured = rb.PeakMemoryProbe.unmeasured
        result = rb.run_engine([sys.executable, "-c", "print(' 73% => Rasterizing layers', flush=True)"],
                               dict(os.environ), tmp_path)

    probe_cls.assert_not_called()
    assert result["exit_code"] == 0
    assert [e["label"] for e in rb.progress_events(result["stdout_lines"])] == ["Rasterizing layers"]
    assert result["memory"]["peak_working_set_bytes"] is None
    assert result["memory"]["memory_note"].startswith("peak memory not measured on ")


# ── real child process ────────────────────────────────────────────────────────

@pytest.mark.skipif(os.name != "nt", reason="GetProcessMemoryInfo is Windows-only")
def test_run_engine_timestamps_stdout_captures_stderr_and_reads_peak_memory(tmp_path):
    # The venv python.exe is a launcher that spawns the real interpreter, so its
    # own working set would be tiny; use the base interpreter as the child.
    python = getattr(sys, "_base_executable", sys.executable)
    script = textwrap.dedent("""
        import sys, time
        print(" 73% => Rasterizing layers", flush=True)
        block = bytearray(200 * 1024 * 1024)
        block[::4096] = b"\\x01" * len(block[::4096])
        time.sleep(0.3)
        print("100% => Slicing done", flush=True)
        sys.stderr.write("[raster-timing] {\\"layers\\": 1}\\n" * 2000)
    """)
    result = rb.run_engine([python, "-c", script], dict(os.environ), tmp_path)

    assert result["exit_code"] == 0
    events = rb.progress_events(result["stdout_lines"])
    assert [e["label"] for e in events] == ["Rasterizing layers", "Slicing done"]
    wall, note = rb.rasterizing_wall(events)
    assert note is None and wall >= 0.25
    assert len(rb.raster_timing_records(result["stderr"])) == 2000
    assert result["memory"]["peak_working_set_bytes"] > 150 * 1024 * 1024
    assert result["memory"]["memory_source"] == "GetProcessMemoryInfo"
    assert result["total_wall_s"] >= wall
