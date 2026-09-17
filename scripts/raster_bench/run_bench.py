#!/usr/bin/env python
"""Run the slicer engine once on a raster benchmark case and record the result.

Spec: ``raster-performance-baseline`` (openspec change optimize-raster-canvas-scan).

  python scripts/raster_bench/run_bench.py --case ID --engine DIR --build LABEL
         --repeat N [--threads N] [--raster-env SLA_RASTER_X=V ...] [--keep-archives]
         [--disable-rle] [--raster-param KEY=VALUE ...]

One invocation is one run. Its output goes to
``work/runs/<platform>-<build>-<case>[-<variant>]-t<threads>-r<repeat>/``:

  layers.sha256    decompressed per-entry fingerprints of the .sl1 layer files
  preview.sha256   the same for the preview zip images
  timing.json      total wall time, rasterizing wall time from the progress lines,
                   parsed ``[raster-timing]`` stderr lines, peak working set
  meta.json        platform, engine identity, inputs, environment, parameter hash
  stdout.log / stderr.log
  config.ini       only for a variant with --raster-param: the config actually loaded

Reference variants (the ``<variant>`` segment, e.g. ``norle`` or ``blur1``)
deviate from the manifest on purpose, for the special baselines of task 0.16:
--disable-rle leaves SLA_LAYER_RLE unset so the engine writes PNG layers, and
--raster-param KEY=VALUE overrides one of the manifest's raster_params (e.g.
blur=1). The fixture's own config.ini is still verified against the manifest;
the overridden config is generated into the run directory. Both change
params_sha256, so a variant never shares a parameter hash with a normal run.

Inputs are verified before the engine starts and the run is refused on any
mismatch; nothing is regenerated here. The model must match fixture.json and
the manifest's ``model.sha256``, the manifest geometry must still hash to
``model.geometry_sha256``, the config must match what the manifest now
describes, and a frozen support.stl must match the SHA-256 in manifest.json and
be bound (``support.model_sha256``) to that same model. Regenerating a missing or
different support mesh would silently change the basis of every comparison.

The run works in a ``.partial-*`` directory and is renamed into place only when
it succeeded, so an existing run directory is always a complete run and is never
overwritten. A failed run leaves its partial directory, with logs, for inspection.

The .sl1 and preview zip are deleted after fingerprinting unless --keep-archives
is given: a 16K case is hundreds of megabytes per run.

Peak memory is read with GetProcessMemoryInfo on Windows only. On other
platforms the run completes normally and the memory fields in timing.json are
null, with ``memory_note`` saying why.

Exit code: 0 = success, 1 = refused or failed, 2 = usage error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR))

import make_fixtures as fx  # noqa: E402  (also puts the repo root on sys.path)
from fingerprint import FingerprintError, fingerprint_archive, write_fingerprint  # noqa: E402

from agent.jobs import normalize_stage_label, parse_progress_line  # noqa: E402
from agent.preview_scale import preview_scale_for  # noqa: E402
from agent.sla_operations import _english_locale_env, generate_config_ini  # noqa: E402

RASTERIZING_LABEL = normalize_stage_label("Rasterizing layers")
RASTER_TIMING_PREFIX = "[raster-timing]"
RASTER_ENV_RE = re.compile(r"^(SLA_RASTER_[A-Z0-9_]+)=(.*)$")
RASTER_PARAM_RE = re.compile(r"^([a-z_]+)=(\S+)$")
LABEL_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PLATFORM_LABELS = {"win32": "windows", "darwin": "macos"}
# Peak memory is only measured where GetProcessMemoryInfo exists. Elsewhere the
# run still produces fingerprints and timings, with memory recorded as null.
MEMORY_PROBE_SUPPORTED = os.name == "nt"


class BenchError(Exception):
    """A refusal or failure that should end the run with exit code 1."""


class UsageError(Exception):
    """Invalid arguments that can only be checked against the manifest; exit code 2."""


# ── peak memory ───────────────────────────────────────────────────────────────

class PeakMemoryProbe:
    """Peak working set of a child process via GetProcessMemoryInfo (no psutil).

    The handle is opened right after the child starts. Holding it keeps the
    process object alive after exit, so the peak counters can still be read once
    the process has finished, which is the only moment the peak is final.
    """

    source = "GetProcessMemoryInfo"

    @staticmethod
    def unmeasured() -> dict:
        return {
            "peak_working_set_bytes": None,
            "peak_pagefile_usage_bytes": None,
            "memory_source": None,
            "memory_note": f"peak memory not measured on {sys.platform}: GetProcessMemoryInfo is Windows-only",
        }

    def __init__(self, pid: int):
        if os.name != "nt":
            raise BenchError("peak memory measurement is implemented for Windows only")
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        self._ctypes = ctypes
        self._counters_type = PROCESS_MEMORY_COUNTERS
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self._psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD,
        ]
        self._psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        process_query_limited_information, process_vm_read = 0x1000, 0x0010
        self._handle = self._kernel32.OpenProcess(
            process_query_limited_information | process_vm_read, False, pid
        )
        if not self._handle:
            raise BenchError(f"OpenProcess({pid}) failed: WinError {ctypes.get_last_error()}")

    def read(self) -> dict:
        counters = self._counters_type()
        counters.cb = self._ctypes.sizeof(counters)
        if not self._psapi.GetProcessMemoryInfo(self._handle, self._ctypes.byref(counters), counters.cb):
            raise BenchError(f"GetProcessMemoryInfo failed: WinError {self._ctypes.get_last_error()}")
        return {
            "peak_working_set_bytes": int(counters.PeakWorkingSetSize),
            "peak_pagefile_usage_bytes": int(counters.PeakPagefileUsage),
            "memory_source": self.source,
            "memory_note": None,
        }

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


# ── engine run ────────────────────────────────────────────────────────────────

def run_engine(cmd: list[str], env: dict, cwd: Path) -> dict:
    """Run the engine, timestamping each stdout line as it arrives.

    Both pipes are drained on their own threads; reading only one would deadlock
    once the other pipe's buffer fills. The engine fflushes after every progress
    line (ProcessActions.cpp status callback), so arrival time is emission time.
    """
    stdout_lines: list[tuple[float, bytes]] = []
    stderr_chunks: list[bytes] = []

    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd)
    probe = None
    if MEMORY_PROBE_SUPPORTED:
        try:
            probe = PeakMemoryProbe(proc.pid)
        except BenchError:
            proc.kill()
            proc.wait()
            raise

    def drain_stdout():
        for raw in iter(proc.stdout.readline, b""):
            stdout_lines.append((time.perf_counter() - t0, raw))

    def drain_stderr():
        for chunk in iter(lambda: proc.stderr.read(65536), b""):
            stderr_chunks.append(chunk)

    readers = [threading.Thread(target=drain_stdout), threading.Thread(target=drain_stderr)]
    for reader in readers:
        reader.start()
    try:
        exit_code = proc.wait()
        total_wall_s = time.perf_counter() - t0
        for reader in readers:
            reader.join()
        memory = probe.read() if probe is not None else PeakMemoryProbe.unmeasured()
    finally:
        if probe is not None:
            probe.close()

    return {
        "exit_code": exit_code,
        "total_wall_s": total_wall_s,
        "stdout_lines": stdout_lines,
        "stderr": b"".join(stderr_chunks),
        "memory": memory,
    }


def progress_events(stdout_lines: list[tuple[float, bytes]]) -> list[dict]:
    events = []
    for t, raw in stdout_lines:
        parsed = parse_progress_line(raw.decode("utf-8", errors="replace"))
        if parsed is not None:
            events.append({"t_s": round(t, 4), "percent": parsed[0], "label": parsed[1]})
    return events


def rasterizing_wall(events: list[dict]) -> tuple[float | None, str | None]:
    """Time from the first "Rasterizing layers" line to the next line with another label.

    The next label is "Slicing done", emitted when rasterization has finished and
    before the archives are written, so archive I/O is not counted.
    """
    start = next((e for e in events if normalize_stage_label(e["label"]) == RASTERIZING_LABEL), None)
    if start is None:
        return None, "no 'Rasterizing layers' progress line on stdout"
    after = events[events.index(start) + 1:]
    end = next((e for e in after if normalize_stage_label(e["label"]) != RASTERIZING_LABEL), None)
    if end is None:
        return None, "no progress line after 'Rasterizing layers'"
    return round(end["t_s"] - start["t_s"], 4), None


def raster_timing_records(stderr: bytes) -> list[dict]:
    records = []
    for line in stderr.decode("utf-8", errors="replace").splitlines():
        if not line.startswith(RASTER_TIMING_PREFIX):
            continue
        payload = line[len(RASTER_TIMING_PREFIX):].strip()
        try:
            records.append(json.loads(payload))
        except json.JSONDecodeError as exc:
            records.append({"parse_error": str(exc), "raw": line})
    return records


# ── inputs ────────────────────────────────────────────────────────────────────

def verify_inputs(manifest: dict, case: dict, fixture_dir: Path, scratch: Path) -> dict:
    """Check every input against its recorded hash. Never regenerates anything."""
    case_id = case["id"]
    model_stl = fixture_dir / "model.stl"
    config_ini = fixture_dir / "config.ini"
    fixture_json = fixture_dir / "fixture.json"
    for path in (model_stl, config_ini, fixture_json):
        if not path.is_file():
            raise BenchError(f"case {case_id}: missing {path}; build it with make_fixtures.py")
    fixture = json.loads(fixture_json.read_text(encoding="utf-8"))

    geometry = case["geometry"]
    expected_source = (
        {"filename": manifest["sources"][geometry["source"]]["filename"],
         "sha256": manifest["sources"][geometry["source"]]["sha256"]}
        if geometry["type"] == "layout" else None
    )
    if fixture.get("case") != case_id or fixture.get("source") != expected_source:
        raise BenchError(
            f"case {case_id}: fixture.json was not built from the manifest's current source "
            f"(fixture {fixture.get('source')}, manifest {expected_source})"
        )

    model_sha = fx.sha256_file(model_stl)
    if model_sha != fixture["model_stl"]["sha256"]:
        raise BenchError(
            f"case {case_id}: model.stl sha256 mismatch: fixture.json {fixture['model_stl']['sha256']}, "
            f"actual {model_sha}"
        )
    recorded_model = case["model"]
    if recorded_model["sha256"] is None:
        raise BenchError(f"case {case_id}: manifest has no model sha256 yet; record it with make_fixtures.py")
    if model_sha != recorded_model["sha256"]:
        raise BenchError(
            f"case {case_id}: model.stl sha256 mismatch: manifest {recorded_model['sha256']}, actual {model_sha}"
        )
    current_geometry = fx.geometry_sha256(manifest, case)
    if current_geometry != recorded_model["geometry_sha256"]:
        raise BenchError(
            f"case {case_id}: manifest geometry changed since model.stl was recorded "
            f"(recorded {recorded_model['geometry_sha256']}, current {current_geometry}); rebuild deliberately"
        )

    # The config must still be exactly what the manifest describes today.
    expected_ini = scratch / "expected_config.ini"
    generate_config_ini(fx.build_sla_config(manifest, case), expected_ini)
    config_sha = fx.sha256_file(config_ini)
    expected_config_sha = fx.sha256_file(expected_ini)
    expected_ini.unlink()
    if config_sha != expected_config_sha:
        raise BenchError(
            f"case {case_id}: config.ini sha256 {config_sha} differs from the manifest's config "
            f"{expected_config_sha}; rebuild the fixture deliberately"
        )

    support_stl, support_sha = None, None
    if case["support"]["mode"] == "frozen":
        recorded = case["support"]["sha256"]
        support_stl = fixture_dir / "support.stl"
        if recorded is None:
            raise BenchError(f"case {case_id}: support is not frozen yet (manifest sha256 is null)")
        if not support_stl.is_file():
            raise BenchError(f"case {case_id}: missing frozen support {support_stl}")
        support_sha = fx.sha256_file(support_stl)
        if support_sha != recorded:
            raise BenchError(
                f"case {case_id}: support.stl sha256 mismatch: manifest {recorded}, actual {support_sha}"
            )
        bound_model = case["support"].get("model_sha256")
        if bound_model != model_sha:
            raise BenchError(
                f"case {case_id}: support.stl was frozen for model {bound_model}, "
                f"not for the current model.stl {model_sha}"
            )

    return {
        "model_stl": model_stl, "model_stl_sha256": model_sha,
        "config_ini": config_ini, "config_ini_sha256": config_sha,
        "support_stl": support_stl, "support_stl_sha256": support_sha,
    }


def engine_identity(engine_dir: Path) -> dict:
    exe = engine_dir / fx.ENGINE_EXE
    if not exe.is_file():
        raise BenchError(f"engine not found: {exe}")
    core = engine_dir / "slicer_core.dll"
    identity = {
        "dir_name": engine_dir.name,
        "exe_sha256": fx.sha256_file(exe),
        "core_sha256": fx.sha256_file(core) if core.is_file() else None,
        "fork_commit": None,
        "fork_tree": None,
    }
    build_info = engine_dir / "build_info.json"
    if build_info.is_file():
        fork = json.loads(build_info.read_text(encoding="utf-8")).get("fork", {})
        identity["fork_commit"] = fork.get("commit")
        identity["fork_tree"] = fork.get("tree")
    return identity


def engine_env(manifest: dict, raster_env: dict[str, str], disable_rle: bool = False) -> tuple[dict, list[str]]:
    """Locale-pinned environment with SLA_* coming only from the manifest and --raster-env.

    Inherited SLA_* variables are dropped so a stray SLA_RASTER_FASTPATH=0 in the
    user's shell cannot change a run without showing up in meta.json. With
    disable_rle the manifest's SLA_LAYER_RLE is not set either.
    """
    env = _english_locale_env()
    dropped = sorted(name for name in env if name.upper().startswith("SLA_"))
    for name in dropped:
        del env[name]
    env.update({k: v for k, v in manifest["engine_env"].items() if not (disable_rle and k == "SLA_LAYER_RLE")})
    env.update(raster_env)
    return env, dropped


def parse_raster_overrides(manifest: dict, pairs: list[str]) -> dict:
    """Turn --raster-param KEY=VALUE items into typed overrides of manifest raster_params."""
    base = manifest["raster_params"]
    overrides = {}
    for item in pairs:
        match = RASTER_PARAM_RE.match(item)
        if match is None:
            raise UsageError(f"--raster-param expects KEY=VALUE, got {item!r}")
        key, raw = match.groups()
        if key not in base:
            raise UsageError(f"--raster-param: {key!r} is not a raster param; known: {sorted(base)}")
        if key in overrides:
            raise UsageError(f"--raster-param: {key!r} given more than once")
        current = base[key]
        try:
            if isinstance(current, bool):
                if raw.lower() not in ("0", "1", "true", "false"):
                    raise ValueError(raw)
                value = raw.lower() in ("1", "true")
            elif isinstance(current, int):
                value = int(raw)
            else:
                value = float(raw)
        except ValueError:
            raise UsageError(f"--raster-param: {key}={raw!r} is not a valid {type(current).__name__}") from None
        if value == current:
            raise UsageError(f"--raster-param: {key}={raw} equals the manifest value; not a variant")
        overrides[key] = value
    return overrides


def variant_label(disable_rle: bool, overrides: dict) -> str:
    """Run-directory segment naming how a run deviates from the manifest ("" for none)."""
    parts = ["norle"] if disable_rle else []
    for key in sorted(overrides):
        value = overrides[key]
        parts.append(f"{key.replace('_', '')}{int(value) if isinstance(value, bool) else value}")
    return "-".join(parts)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--case", required=True, metavar="ID", help="case id from manifest.json")
    parser.add_argument("--engine", required=True, metavar="DIR", help="engine directory containing slicer-engine.exe")
    parser.add_argument("--build", required=True, metavar="LABEL", help="build label for the run directory, e.g. base")
    parser.add_argument("--repeat", required=True, type=int, metavar="N", help="repeat number, 1-based")
    parser.add_argument("--threads", type=int, metavar="N", help="pass --threads N (default: engine default)")
    parser.add_argument("--raster-env", action="append", default=[], metavar="SLA_RASTER_NAME=VALUE",
                        help="extra SLA_RASTER_* environment variable for the engine; repeatable")
    parser.add_argument("--platform", default=PLATFORM_LABELS.get(sys.platform, sys.platform),
                        help="platform label (default: %(default)s)")
    parser.add_argument("--work", default=str(fx.DEFAULT_WORK_DIR), help="working directory (default: %(default)s)")
    parser.add_argument("--keep-archives", action="store_true", help="keep model.sl1 and model_preview.zip")
    parser.add_argument("--disable-rle", action="store_true",
                        help="reference variant: do not set SLA_LAYER_RLE (engine writes PNG layers)")
    parser.add_argument("--raster-param", action="append", default=[], metavar="KEY=VALUE",
                        help="reference variant: override a manifest raster param, e.g. blur=1; repeatable")
    args = parser.parse_args(argv)

    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    if args.threads is not None and args.threads < 1:
        parser.error("--threads must be >= 1")
    for name in ("build", "platform"):
        if not LABEL_RE.match(getattr(args, name)):
            parser.error(f"--{name} may only contain letters, digits, '.', '_' and '-'")
    raster_env = {}
    for item in args.raster_env:
        match = RASTER_ENV_RE.match(item)
        if match is None:
            parser.error(f"--raster-env expects SLA_RASTER_NAME=VALUE, got {item!r}")
        raster_env[match.group(1)] = match.group(2)
    args.raster_env = raster_env
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    work_dir = Path(args.work)
    engine_dir = Path(args.engine)
    runs_dir = work_dir / "runs"

    partial = None
    try:
        manifest = fx.load_manifest()
        try:
            overrides = parse_raster_overrides(manifest, args.raster_param)
        except UsageError as exc:
            print(f"usage error: {exc}", file=sys.stderr)
            return 2
        case = fx.select_cases(manifest, [args.case])[0]
        variant = variant_label(args.disable_rle, overrides)
        threads_label = f"t{args.threads}" if args.threads is not None else "tdefault"
        segments = [args.platform, args.build, args.case] + ([variant] if variant else [])
        run_id = "-".join(segments + [threads_label, f"r{args.repeat}"])
        run_dir = runs_dir / run_id
        if run_dir.exists():
            raise BenchError(f"run directory already exists, refusing to overwrite: {run_dir}")
        engine = engine_identity(engine_dir)

        runs_dir.mkdir(parents=True, exist_ok=True)
        partial = Path(tempfile.mkdtemp(prefix=f".partial-{run_id}-", dir=runs_dir))
        fixture_dir = work_dir / "fixtures" / case["id"]
        inputs = verify_inputs(manifest, case, fixture_dir, partial)

        machine = manifest["machines"][case["machine"]]
        config = fx.build_sla_config(manifest, case, **overrides)
        config_ini, config_placeholder = inputs["config_ini"], "<fixture>/config.ini"
        if overrides:
            config_ini, config_placeholder = partial / "config.ini", "<run>/config.ini"
            generate_config_ini(config, config_ini)
            inputs["config_ini_sha256"] = fx.sha256_file(config_ini)
        preview_scale, preview_n = preview_scale_for(max(machine["display_pixels_x"], machine["display_pixels_y"]))
        center = f"{config.center_x},{config.center_y}"
        sl1 = partial / "model.sl1"
        preview_zip = partial / "model_preview.zip"

        # Same argument order as agent/jobs.py run_slicing.
        cmd = [
            str(engine_dir / fx.ENGINE_EXE),
            "--export-sla",
            "--export-preview-pngs", preview_scale,
            "--output", str(sl1),
            "--center", center,
            "--load", str(config_ini),
        ]
        if inputs["support_stl"] is not None:
            cmd += ["--import-support-stl", str(inputs["support_stl"])]
        if args.threads is not None:
            cmd += ["--threads", str(args.threads)]
        cmd.append(str(inputs["model_stl"]))
        placeholders = {
            str(engine_dir / fx.ENGINE_EXE): f"<engine>/{fx.ENGINE_EXE}",
            str(sl1): "<run>/model.sl1",
            str(config_ini): config_placeholder,
            str(inputs["model_stl"]): "<fixture>/model.stl",
        }
        if inputs["support_stl"] is not None:
            placeholders[str(inputs["support_stl"])] = "<fixture>/support.stl"

        env, dropped_env = engine_env(manifest, args.raster_env, args.disable_rle)
        started_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = run_engine(cmd, env, partial)
        (partial / "stdout.log").write_bytes(b"".join(raw for _, raw in result["stdout_lines"]))
        (partial / "stderr.log").write_bytes(result["stderr"])

        if result["exit_code"] != 0 or not sl1.is_file():
            raise BenchError(
                f"engine failed (exit {result['exit_code']}, .sl1 exists: {sl1.is_file()}); "
                f"see {partial / 'stderr.log'}"
            )
        if not preview_zip.is_file():
            raise BenchError(f"engine wrote no {preview_zip.name}; see {partial / 'stderr.log'}")

        layers = fingerprint_archive(sl1, "layers")
        preview = fingerprint_archive(preview_zip, "preview")
        if not layers.entries or not preview.entries:
            raise BenchError(
                f"empty fingerprint: {len(layers.entries)} layer entries, {len(preview.entries)} preview entries"
            )
        write_fingerprint(partial / "layers.sha256", layers)
        write_fingerprint(partial / "preview.sha256", preview)

        events = progress_events(result["stdout_lines"])
        raster_wall_s, raster_wall_note = rasterizing_wall(events)
        timing = {
            "total_wall_s": round(result["total_wall_s"], 4),
            "rasterizing_wall_s": raster_wall_s,
            "rasterizing_wall_note": raster_wall_note,
            "raster_timing": raster_timing_records(result["stderr"]),
            **result["memory"],
            "exit_code": result["exit_code"],
            "progress": events,
        }

        pixel_env = {name: value for name, value in env.items() if name in manifest["engine_env"]}
        params = {
            "raster_params": {**manifest["raster_params"], **overrides},
            "engine_env": pixel_env,
            "machine": machine,
            "preview_scale": preview_scale,
            "center": center,
            "config_ini_sha256": inputs["config_ini_sha256"],
            "model_stl_sha256": inputs["model_stl_sha256"],
            "support_stl_sha256": inputs["support_stl_sha256"],
        }
        meta = {
            "schema_version": 1,
            "run_id": run_id,
            "platform": args.platform,
            "build": args.build,
            "case": case["id"],
            "machine": case["machine"],
            "threads": args.threads,
            "cpu_count": os.cpu_count(),
            "repeat": args.repeat,
            "variant": {"label": variant or None, "disable_rle": args.disable_rle,
                        "raster_param_overrides": overrides},
            "started_at_utc": started_at,
            "engine": engine,
            "inputs": {k: v for k, v in inputs.items() if k.endswith("_sha256")},
            "preview_scale": preview_scale,
            "preview_n": preview_n,
            "env": {name: env[name] for name in sorted(env) if name.upper().startswith("SLA_")},
            "inherited_sla_env_dropped": dropped_env,
            "command": [placeholders.get(arg, arg) for arg in cmd],
            # Hash of everything that determines the output pixels. Threads,
            # repeat and SLA_RASTER_* diagnostics are deliberately left out so
            # runs that must produce identical fingerprints share one hash.
            "params": params,
            "params_sha256": hashlib.sha256(
                json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "counts": {"layers": len(layers.entries), "preview": len(preview.entries)},
            "excluded_entries": {"layers": layers.excluded, "preview": preview.excluded},
            "archives_kept": args.keep_archives,
        }
        if timing["memory_note"]:
            print(f"warning: {timing['memory_note']}", file=sys.stderr)
        (partial / "timing.json").write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")
        (partial / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

        if not args.keep_archives:
            sl1.unlink()
            preview_zip.unlink()
        os.replace(partial, run_dir)
        partial = None
    except (BenchError, fx.FixtureError, FingerprintError, zipfile.BadZipFile, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        if partial is not None:
            if any(partial.glob("*.log")):
                print(f"partial run kept for inspection: {partial}", file=sys.stderr)
            else:
                shutil.rmtree(partial, ignore_errors=True)
        return 1

    print(json.dumps({
        "run": run_id,
        "layers": meta["counts"]["layers"],
        "preview": meta["counts"]["preview"],
        "total_wall_s": timing["total_wall_s"],
        "rasterizing_wall_s": timing["rasterizing_wall_s"],
        "peak_working_set_bytes": timing["peak_working_set_bytes"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
