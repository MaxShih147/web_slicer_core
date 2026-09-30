"""
Tests for generate_hollow() and cut_with_plane() carrying the engine's raw
stderr in their failure `error` — Tasks 4.1-4.3 (merge-engine-result-classifiers).

Before this change, a missing output file (exit 0 but no mesh written) always
returned a hardcoded canned message, discarding whatever the engine actually
printed. cut_with_plane's canned message additionally *guessed* a specific
cause ("The cut height may be outside the model bounds") that may not be
true. Now: non-empty stderr is preserved verbatim in `error`; the canned
message is only a fallback for the (rare) case of truly empty stderr, and no
longer guesses a reason.

Isolated by monkeypatching agent.sla_operations.run_prusa_cli — the real
slicer binary is never invoked. Async is driven synchronously via
asyncio.run (no pytest-asyncio dependency), matching test_run_support_generation.py.
"""

import asyncio

import pytest

from agent import sla_operations
from agent.models import CutConfig, SLAConfig


def _stub_cli(monkeypatch, *, stdout=b"", stderr=b"", returncode=0):
    """Replace run_prusa_cli with a fake that never launches a process."""

    async def fake_run_prusa_cli(cmd, stderr_file=None, stdout_file=None):
        if stdout_file:
            with open(stdout_file, "wb") as f:
                f.write(stdout)
        if stderr_file:
            with open(stderr_file, "wb") as f:
                f.write(stderr)
        return returncode, stdout, stderr

    monkeypatch.setattr(sla_operations, "run_prusa_cli", fake_run_prusa_cli)


@pytest.fixture
def job_dir(tmp_path):
    job_id = "job-1"
    d = tmp_path / job_id
    (d / "input").mkdir(parents=True)
    (d / "output").mkdir()
    (d / "input" / "model.stl").write_bytes(b"solid model\nendsolid\n")
    return d


class TestGenerateHollowCarriesRawStderr:
    def test_missing_output_with_nonempty_stderr_includes_engine_text(self, job_dir, monkeypatch):
        """4.1: exit 0, no hollow.stl, stderr non-empty -> error contains the
        engine's own text, not just the canned message."""
        _stub_cli(
            monkeypatch,
            stdout=b"",
            stderr=b"Support mesh is empty: nothing to hollow\n",
            returncode=0,
        )
        result = asyncio.run(sla_operations.generate_hollow(job_dir, SLAConfig()))
        assert result.success is False
        assert "Support mesh is empty: nothing to hollow" in result.error

    def test_missing_output_with_empty_stderr_falls_back_to_canned_message(self, job_dir, monkeypatch):
        """The canned message is still used, but only when there is truly
        nothing from the engine to show."""
        _stub_cli(monkeypatch, stdout=b"", stderr=b"", returncode=0)
        result = asyncio.run(sla_operations.generate_hollow(job_dir, SLAConfig()))
        assert result.success is False
        assert result.error  # some message, not blank
        assert "not generated" in result.error.lower()


class TestCutCarriesRawStderrNotAGuess:
    def test_missing_output_with_nonempty_stderr_includes_engine_text(self, job_dir, monkeypatch):
        """4.2: exit 0, no combined.stl, stderr non-empty -> error contains
        the engine's own text."""
        _stub_cli(
            monkeypatch,
            stdout=b"",
            stderr=b"error: cut plane does not intersect the object\n",
            returncode=0,
        )
        result = asyncio.run(sla_operations.cut_with_plane(job_dir, CutConfig()))
        assert result.success is False
        assert "error: cut plane does not intersect the object" in result.error

    def test_missing_output_with_empty_stderr_does_not_guess_a_reason(self, job_dir, monkeypatch):
        """4.3: the canned fallback message must not claim a specific cause
        like 'the cut height may be outside the model bounds' — that was a
        guess, not something the engine actually said."""
        _stub_cli(monkeypatch, stdout=b"", stderr=b"", returncode=0)
        result = asyncio.run(sla_operations.cut_with_plane(job_dir, CutConfig()))
        assert result.success is False
        assert result.error
        assert "bounds" not in result.error.lower()
        assert "may be" not in result.error.lower()
