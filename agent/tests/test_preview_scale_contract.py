"""Contract tests for the preview-scale call sites — Phase 2
(slice-preview-quantized-scale).

Two layers of protection, because this regression has an unusual shape.

**Source-code lock.** Re-hardcoding ``--export-preview-pngs "0.25"`` would not
turn any functional test red: the output stays a perfectly valid preview ZIP,
just the wrong size for whichever machine is affected. Nothing raises, nothing
logs. Only a source-level contract catches it. Mirrors the established pattern
in ``test_slice_progress_string_contract.py`` / ``test_support_string_contract.py``.

**Behaviour.** The lock proves the literal is gone; these prove the right value
actually reaches the command line — including the ``config is None`` path, which
is a live route (``main.py`` leaves ``sla_config`` None when the legacy
``POST /api/jobs`` caller omits the config) and not defensive padding.
"""

import asyncio
import re
from pathlib import Path

import pytest

from agent import jobs, sla_operations
from agent.jobs import run_slicing
from agent.models import SLAConfig
from agent.preview_scale import preview_scale_for
from agent.sla_operations import slice_model

_AGENT_DIR = Path(__file__).resolve().parents[1]
_JOBS_PY = _AGENT_DIR / "jobs.py"
_SLA_OPS_PY = _AGENT_DIR / "sla_operations.py"

_CLI_FLAG = "--export-preview-pngs"

# A string literal sitting directly after the flag == the value was hardcoded.
_HARDCODED_ARG = re.compile(r'"' + re.escape(_CLI_FLAG) + r'"\s*,\s*"')


@pytest.fixture(scope="module")
def jobs_src():
    return _JOBS_PY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sla_ops_src():
    return _SLA_OPS_PY.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 原始碼契約鎖
# ---------------------------------------------------------------------------

class TestSourceContract:
    @pytest.mark.parametrize("name", ["jobs_src", "sla_ops_src"])
    def test_call_site_still_passes_the_flag(self, name, request):
        """Sanity: the flag itself must not have been dropped."""
        src = request.getfixturevalue(name)
        assert f'"{_CLI_FLAG}"' in src

    @pytest.mark.parametrize("name", ["jobs_src", "sla_ops_src"])
    def test_scale_is_not_hardcoded(self, name, request):
        """The value after the flag MUST NOT be a string literal."""
        src = request.getfixturevalue(name)
        assert not _HARDCODED_ARG.search(src), (
            f"{name}: a literal scale was re-hardcoded after {_CLI_FLAG} — "
            f"the quantiser is bypassed and the wrong machines get the wrong "
            f"preview size, silently"
        )

    @pytest.mark.parametrize("name", ["jobs_src", "sla_ops_src"])
    def test_call_site_goes_through_the_helper(self, name, request):
        src = request.getfixturevalue(name)
        assert "preview_scale_for" in src, (
            f"{name}: must obtain the scale from preview_scale.preview_scale_for"
        )

    @pytest.mark.parametrize("name", ["jobs_src", "sla_ops_src"])
    def test_long_side_uses_max_of_both_axes(self, name, request):
        """Guards design D2: the engine swaps pw/ph in portrait orientation
        (SL1.cpp:390-393), so display_pixels_x is not the raster width. Only
        max() is invariant under that swap."""
        src = request.getfixturevalue(name)
        assert "display_pixels_x" in src and "display_pixels_y" in src
        assert re.search(r"max\(\s*[\w.]*display_pixels_x", src), (
            f"{name}: the long side must be max(display_pixels_x, "
            f"display_pixels_y), never display_pixels_x alone"
        )


class TestSourceContractHasTeeth:
    """Prove the lock would actually fire — a regex that matches nothing is
    indistinguishable from a passing test."""

    def test_regex_matches_the_old_hardcoded_form(self):
        old = '        "--export-preview-pngs", "0.25",\n'
        assert _HARDCODED_ARG.search(old)

    def test_regex_ignores_the_helper_form(self):
        new = '        "--export-preview-pngs", preview_scale,\n'
        assert not _HARDCODED_ARG.search(new)


# ---------------------------------------------------------------------------
# 行為測試：值真的到得了命令列
# ---------------------------------------------------------------------------

JOB = "b2c3d4e5"


def _reader(payload: bytes) -> asyncio.StreamReader:
    stream = asyncio.StreamReader()
    stream.feed_data(payload)
    stream.feed_eof()
    return stream


class _FakeProc:
    """Minimal stand-in for the engine subprocess. Non-zero exit keeps
    run_slicing on its short failure path — we only care about argv."""

    returncode = 1
    pid = 4242

    def open_streams(self):
        self.stdout = _reader(b"")
        self.stderr = _reader(b"")

    async def wait(self):
        return self.returncode


@pytest.fixture
def captured_argv(tmp_path, monkeypatch):
    """Run run_slicing against a stubbed engine and capture its command line."""
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    job_dir = tmp_path / JOB
    (job_dir / "input").mkdir(parents=True)
    (job_dir / "output").mkdir()
    monkeypatch.setattr(jobs, "notify_launcher_if_prusa_crashed", lambda rc: None)

    argv = []

    async def fake_exec(*args, **kwargs):
        argv.extend(args)
        proc = _FakeProc()
        proc.open_streams()
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return argv


def _preview_arg(argv) -> str:
    """The value passed right after the flag."""
    assert _CLI_FLAG in argv, f"{_CLI_FLAG} missing from {argv}"
    return argv[argv.index(_CLI_FLAG) + 1]


def _config(w: int, h: int) -> SLAConfig:
    return SLAConfig(display_pixels_x=w, display_pixels_y=h)


# (標籤, w, h, 期望送出的 scale 字串)
_CASES = [
    ("16K",            15120, 6230, "0.1"),
    ("sonic_cs_plus",   7536, 3240, "0.2"),
    ("sonic_ls_plus",   3840, 2400, "0.25"),
    ("5760 幅面",       5760, 3600, "0.25"),
]


@pytest.mark.parametrize("label,w,h,expected", _CASES, ids=[c[0] for c in _CASES])
def test_run_slicing_passes_the_quantised_scale(label, w, h, expected, captured_argv):
    asyncio.run(run_slicing(JOB, _config(w, h)))
    assert _preview_arg(captured_argv) == expected


def test_run_slicing_without_config_falls_back_to_the_ceiling(captured_argv):
    """main.py:612-613 leaves sla_config None on the legacy endpoint; no --load
    is passed, so the engine uses its built-in preset and Python cannot know the
    format. N=4 is the only honest answer — and it equals today's behaviour."""
    asyncio.run(run_slicing(JOB))
    assert _preview_arg(captured_argv) == "0.25"


@pytest.mark.parametrize("label,w,h,expected", _CASES, ids=[c[0] for c in _CASES])
def test_run_slicing_matches_the_helper(label, w, h, expected, captured_argv):
    """The call site must not re-derive the value by its own arithmetic."""
    asyncio.run(run_slicing(JOB, _config(w, h)))
    scale_str, _ = preview_scale_for(max(w, h))
    assert _preview_arg(captured_argv) == scale_str


def test_run_slicing_uses_the_long_side_in_portrait(captured_argv):
    """Axes swapped: the quantiser must still see 15120, not 6230."""
    asyncio.run(run_slicing(JOB, _config(6230, 15120)))
    assert _preview_arg(captured_argv) == "0.1"


@pytest.fixture
def captured_cli(tmp_path, monkeypatch):
    """Capture the command line built by sla_operations.slice_model()."""
    argv = []

    async def fake_cli(cmd, stderr_file=None, stdout_file=None):
        argv.extend(cmd)
        return 1, b"", b""  # non-zero: slice_model returns early

    monkeypatch.setattr(sla_operations, "run_prusa_cli", fake_cli)
    return argv


@pytest.mark.parametrize("label,w,h,expected", _CASES, ids=[c[0] for c in _CASES])
def test_slice_model_passes_the_quantised_scale(
    label, w, h, expected, tmp_path, captured_cli
):
    job_dir = tmp_path / "job"
    (job_dir / "input").mkdir(parents=True)
    (job_dir / "output").mkdir()

    asyncio.run(slice_model(job_dir, _config(w, h)))
    assert _preview_arg(captured_cli) == expected


def test_slice_model_uses_the_long_side_in_portrait(tmp_path, captured_cli):
    job_dir = tmp_path / "job"
    (job_dir / "input").mkdir(parents=True)
    (job_dir / "output").mkdir()

    asyncio.run(slice_model(job_dir, _config(6230, 15120)))
    assert _preview_arg(captured_cli) == "0.1"
