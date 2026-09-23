"""
Test for run_slicing() resetting ALL support_*/pad_* fields to backend
defaults when input/support.stl is imported — Task 6 (add-support-param-validation),
support-param-validation spec.md "匯入支撐時須重設支撐與底墊參數".

Before this change, only supports_enable/pad_enable were forced off; every
other support_*/pad_* field kept whatever the user had set (dead values the
engine ignores in this mode, per design.md D2, but still visible in
config.ini/config.json — misleading, and exactly the kind of stale state a
future reader would trust by mistake). Now every field in both families is
reset to SLAConfig()'s own default.

Isolated the same way as test_run_support_generation.py: agent.jobs.JOBS_DIR
monkeypatched to a tmp dir, agent.sla_operations.run_prusa_cli stubbed so the
real slicer binary is never invoked.
"""

import asyncio

import pytest

from agent import jobs, sla_operations
from agent.models import SLAConfig


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    job_id = "import-support-job"
    (tmp_path / job_id / "input").mkdir(parents=True)
    (tmp_path / job_id / "output").mkdir()
    (tmp_path / job_id / "input" / "model.stl").write_bytes(b"solid m\nendsolid m\n")
    return job_id


def _stub_cli(monkeypatch, *, stdout=b"(includes supports and pad)\n", stderr=b"", returncode=0):
    async def fake_run_prusa_cli(cmd, stderr_file=None, stdout_file=None):
        if stdout_file:
            with open(stdout_file, "wb") as f:
                f.write(stdout)
        if stderr_file:
            with open(stderr_file, "wb") as f:
                f.write(stderr)
        return returncode, stdout, stderr

    monkeypatch.setattr(sla_operations, "run_prusa_cli", fake_run_prusa_cli)


_NON_DEFAULT_SUPPORT_PAD_OVERRIDES = {
    "supports_enable": True,
    "pad_enable": True,
    "support_head_front_diameter": 0.9,
    "support_pillar_diameter": 2.5,
    "support_object_elevation": 8.0,
    "pad_wall_thickness": 3.3,
    "pad_wall_slope": 60.0,
    "pad_brim_size": 4.0,
}


class TestImportedSupportResetsAllFields:
    def test_config_json_has_backend_defaults_for_every_support_and_pad_field(self, job, monkeypatch):
        (jobs.JOBS_DIR / job / "input" / "support.stl").write_bytes(b"solid s\nendsolid s\n")
        _stub_cli(monkeypatch)

        config = SLAConfig(**_NON_DEFAULT_SUPPORT_PAD_OVERRIDES)
        asyncio.run(jobs.run_slicing(job, config))

        import json

        written = json.loads((jobs.get_job_dir(job) / "config.json").read_text())
        defaults = SLAConfig().model_dump()
        for field_name, value in written.items():
            if field_name.startswith("support_") or field_name.startswith("pad_"):
                assert value == defaults[field_name], (
                    f"{field_name} was not reset to its backend default under "
                    f"import_support: got {value!r}, expected {defaults[field_name]!r}"
                )

    def test_without_imported_support_fields_pass_through_unchanged(self, job, monkeypatch):
        """Sanity: the reset is conditional on support.stl actually existing —
        the self-generated-support path must keep the user's values."""
        _stub_cli(monkeypatch)

        config = SLAConfig(**_NON_DEFAULT_SUPPORT_PAD_OVERRIDES)
        asyncio.run(jobs.run_slicing(job, config))

        import json

        written = json.loads((jobs.get_job_dir(job) / "config.json").read_text())
        for field_name, value in _NON_DEFAULT_SUPPORT_PAD_OVERRIDES.items():
            assert written[field_name] == value
