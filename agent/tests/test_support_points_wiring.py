"""
Backend wiring tests for the support point interface — openspec change
per-point-support-sizing, task 7.6.

These pin the contracts the backend owes the engine and the caller. Every one
of them is a rule that is invisible at runtime until it is broken:

  - the export operation FORCES supports on. With supports disabled the engine
    skips the support point step and writes an empty list with no error, which
    the caller cannot tell apart from "this model needs none";
  - a caller supplied list is landed VERBATIM. A missing size key means "fall
    back to the global setting", and making that decision belongs to the engine.
    Filling one in here would freeze a value the caller never chose, silently;
  - the input list goes to input/, the exported list to output/;
  - --import-support-points reaches the CLI on both the support-generation and
    the slicing path.

The real slicer binary is never launched: run_prusa_cli is stubbed and the
command it was handed is captured for inspection. Async is driven with
asyncio.run, matching the other tests here (no pytest-asyncio dependency).
"""

import asyncio
import json

import pytest

from agent import jobs, sla_operations
from agent.models import SLAConfig
from agent.sla_operations import (
    OperationType,
    export_support_points,
    generate_supports,
    support_points_input_path,
    support_points_output_path,
    write_support_points_input,
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

@pytest.fixture
def job_dir(tmp_path):
    d = tmp_path / "job-1"
    (d / "input").mkdir(parents=True)
    (d / "output").mkdir()
    (d / "input" / "model.stl").write_bytes(b"solid model\n")
    return d


class CapturedCLI:
    """Records the command run_prusa_cli was handed, and optionally creates the
    file the engine would have written."""

    def __init__(self):
        self.commands = []

    def flag_value(self, flag, index=0):
        """The argument that followed `flag` in the recorded command."""
        cmd = self.commands[index]
        return cmd[cmd.index(flag) + 1]


def _stub_cli(monkeypatch, *, creates=None, stdout=b"", stderr=b"", returncode=0):
    captured = CapturedCLI()

    async def fake_run_prusa_cli(cmd, stderr_file=None, stdout_file=None):
        captured.commands.append(list(cmd))
        if creates is not None:
            creates.parent.mkdir(parents=True, exist_ok=True)
            creates.write_text(json.dumps(SAMPLE_EXPORT), encoding="utf-8")
        if stdout_file:
            with open(stdout_file, "wb") as f:
                f.write(stdout)
        if stderr_file:
            with open(stderr_file, "wb") as f:
                f.write(stderr)
        return returncode, stdout, stderr

    monkeypatch.setattr(sla_operations, "run_prusa_cli", fake_run_prusa_cli)
    return captured


# What the engine writes: every size frozen to a concrete value, no sentinels.
SAMPLE_EXPORT = {
    "version": 1,
    "model_fingerprint": {
        "face_count": 1908,
        "bbox_min": [-125000, -125000, 70000],
        "bbox_max": [125000, 125000, 370000],
        "vertex_checksum": "1a205a2be3f13857",
    },
    "points": [
        {
            "pos": [9.17, 5.84, 7.0],
            "type": "island",
            "head_front_radius": 0.4,
            "head_back_radius_mm": 0.5,
            "head_width_mm": 1.0,
            "head_penetration_mm": 0.3,
            "contact_sphere_radius": 0.0,
            "base_radius_mm": 2.0,
            "support_bracing_angle_deg": 45.0,
        }
    ],
}

# What a caller sends when it only wants to place a point by hand: position and
# type, nothing else. Every absent size key means "use the global setting".
MINIMAL_INPUT = {
    "version": 1,
    "points": [{"pos": [1.0, 2.0, 3.0], "type": "manual_add"}],
}


# --------------------------------------------------------------------------
# 7.1 / 7.2 — the export operation
# --------------------------------------------------------------------------

class TestExportCommandAssembly:
    def test_writes_to_the_output_directory(self, job_dir, monkeypatch):
        points_file = support_points_output_path(job_dir)
        cli = _stub_cli(monkeypatch, creates=points_file)

        result = asyncio.run(export_support_points(job_dir, SLAConfig()))

        assert cli.flag_value("--export-support-points") == str(points_file)
        assert points_file.parent == job_dir / "output"
        assert result.success
        assert result.operation == OperationType.EXPORT_SUPPORT_POINTS
        assert result.support_points_path == points_file

    def test_asks_for_nothing_but_the_points(self, job_dir, monkeypatch):
        """Any other export action would take the engine off the points-only
        fast path and make it build a tree, a pad and an archive."""
        cli = _stub_cli(monkeypatch, creates=support_points_output_path(job_dir))

        asyncio.run(export_support_points(job_dir, SLAConfig()))

        cmd = cli.commands[0]
        assert "--export-support-stl" not in cmd
        assert "--export-sla" not in cmd
        assert "--export-preview-pngs" not in cmd
        assert "--slice" not in cmd

    def test_forces_supports_on(self, job_dir, monkeypatch):
        """With supports off the engine skips the support point step entirely
        and returns an empty list without complaining."""
        _stub_cli(monkeypatch, creates=support_points_output_path(job_dir))
        config = SLAConfig(supports_enable=False)

        asyncio.run(export_support_points(job_dir, config))

        assert config.supports_enable is True
        written = (job_dir / "config.ini").read_text()
        assert "supports_enable = 1" in written

    def test_uses_the_coarse_detection_layer_height(self, job_dir, monkeypatch):
        """Point detection runs off island analysis, not print resolution, and
        this path produces no sl1 - so it slices coarse, like generate_supports."""
        _stub_cli(monkeypatch, creates=support_points_output_path(job_dir))
        config = SLAConfig(layer_height=0.05, initial_layer_height=0.05)

        asyncio.run(export_support_points(job_dir, config))

        written = (job_dir / "config.ini").read_text()
        coarse = sla_operations.SUPPORT_DETECTION_LAYER_HEIGHT
        assert f"layer_height = {coarse}" in written
        assert f"initial_layer_height = {coarse}" in written
        # The caller's own config is not mutated into the coarse height - only
        # the copy handed to the engine is.
        assert config.layer_height == 0.05

    def test_missing_file_is_a_failure_even_on_exit_zero(self, job_dir, monkeypatch):
        """This fork exits 0 from several failing paths, so the file is the
        only trustworthy evidence."""
        _stub_cli(monkeypatch, creates=None, stderr=b"something went wrong", returncode=0)

        result = asyncio.run(export_support_points(job_dir, SLAConfig()))

        assert result.success is False
        assert result.support_points_path is None
        assert "something went wrong" in result.error


# --------------------------------------------------------------------------
# 7.3 — landing the caller's list, verbatim
# --------------------------------------------------------------------------

class TestVerbatimLanding:
    def test_lands_in_the_input_directory(self, job_dir):
        path = write_support_points_input(job_dir, json.dumps(MINIMAL_INPUT))

        assert path == support_points_input_path(job_dir)
        assert path.parent == job_dir / "input"
        assert path.name == "support_points.json"

    def test_no_size_key_is_invented(self, job_dir):
        """The contract that matters most: a point given as pos + type must
        come back out as pos + type. Any key added here would be read by the
        engine as a deliberate, frozen value."""
        write_support_points_input(job_dir, json.dumps(MINIMAL_INPUT))

        landed = json.loads(support_points_input_path(job_dir).read_text())
        point = landed["points"][0]

        assert set(point) == {"pos", "type"}
        for absent in (
            "head_front_radius",
            "head_back_radius_mm",
            "head_width_mm",
            "head_penetration_mm",
            "contact_sphere_radius",
            "base_radius_mm",
            "support_bracing_angle_deg",
        ):
            assert absent not in point

    def test_raw_bytes_land_byte_for_byte(self, job_dir):
        """Given bytes, the file must be those bytes - not a reformatted
        equivalent. Re-encoding a float could move it in the last digit."""
        raw = b'{"version": 1, "points": [{"pos": [0.30000001192092896, 0, 0]}]}'

        write_support_points_input(job_dir, raw)

        assert support_points_input_path(job_dir).read_bytes() == raw

    def test_values_are_not_normalised(self, job_dir):
        """0.0 is a real value for contact_sphere_radius ("no contact sphere on
        this point"), not a missing one. Nothing here may round it away."""
        payload = {
            "version": 1,
            "points": [{"pos": [0, 0, 0], "contact_sphere_radius": 0.0,
                        "head_back_radius_mm": 0.9}],
        }
        write_support_points_input(job_dir, payload)

        landed = json.loads(support_points_input_path(job_dir).read_text())
        assert landed["points"][0]["contact_sphere_radius"] == 0.0
        assert landed["points"][0]["head_back_radius_mm"] == 0.9


class TestImportReachesTheCLI:
    def test_support_generation_passes_the_list(self, job_dir, monkeypatch):
        write_support_points_input(job_dir, json.dumps(MINIMAL_INPUT))
        cli = _stub_cli(monkeypatch, stdout=b"Generated (supports only)\n")
        (job_dir / "output" / "model_support.stl").write_bytes(b"solid s\n")

        asyncio.run(generate_supports(job_dir, SLAConfig()))

        assert cli.flag_value("--import-support-points") == str(
            support_points_input_path(job_dir)
        )

    def test_no_list_means_no_flag(self, job_dir, monkeypatch):
        """The existing path must be untouched when the interface is unused."""
        cli = _stub_cli(monkeypatch, stdout=b"Generated (supports only)\n")
        (job_dir / "output" / "model_support.stl").write_bytes(b"solid s\n")

        asyncio.run(generate_supports(job_dir, SLAConfig()))

        assert "--import-support-points" not in cli.commands[0]

    def test_input_file_stays_last_on_the_command_line(self, job_dir, monkeypatch):
        """The model path is positional and must not end up being consumed as
        the value of --import-support-points."""
        write_support_points_input(job_dir, json.dumps(MINIMAL_INPUT))
        cli = _stub_cli(monkeypatch, stdout=b"Generated (supports only)\n")
        (job_dir / "output" / "model_support.stl").write_bytes(b"solid s\n")

        asyncio.run(generate_supports(job_dir, SLAConfig()))

        assert cli.commands[0][-1] == str(job_dir / "input" / "model.stl")


class TestSlicingPathPassesTheList:
    """run_slicing is the other consumer, and it also owns the --import-support-stl
    path that the point list is mutually exclusive with."""

    @pytest.fixture
    def slicing_job(self, tmp_path, monkeypatch):
        monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
        job_id = "slice-job"
        d = tmp_path / job_id
        (d / "input").mkdir(parents=True)
        (d / "output").mkdir()
        (d / "input" / "model.stl").write_bytes(b"solid model\n")
        return job_id

    def _stub_slicing_cli(self, monkeypatch):
        captured = CapturedCLI()

        # create_subprocess_exec is called as (*cmd, ...), so the argv arrives
        # spread across positional parameters - not as one list.
        async def fake_run(*argv, **kwargs):
            captured.commands.append([str(a) for a in argv])
            raise RuntimeError("stop after command assembly")

        monkeypatch.setattr(jobs.asyncio, "create_subprocess_exec", fake_run)
        return captured

    def test_list_is_passed_when_present(self, slicing_job, monkeypatch):
        job_dir = jobs.get_job_dir(slicing_job)
        write_support_points_input(job_dir, json.dumps(MINIMAL_INPUT))
        cli = self._stub_slicing_cli(monkeypatch)

        asyncio.run(jobs.run_slicing(slicing_job, SLAConfig()))

        assert cli.commands, "the CLI was never assembled"
        assert cli.flag_value("--import-support-points") == str(
            support_points_input_path(job_dir)
        )

    def test_an_imported_mesh_wins_and_the_list_is_dropped(self, slicing_job, monkeypatch):
        """The engine refuses both together, and an imported mesh replaces the
        whole support track anyway - so the list is dropped, with a warning."""
        job_dir = jobs.get_job_dir(slicing_job)
        write_support_points_input(job_dir, json.dumps(MINIMAL_INPUT))
        (job_dir / "input" / "support.stl").write_bytes(b"solid s\n")
        cli = self._stub_slicing_cli(monkeypatch)

        asyncio.run(jobs.run_slicing(slicing_job, SLAConfig()))

        cmd = cli.commands[0]
        assert "--import-support-stl" in cmd
        assert "--import-support-points" not in cmd

    def test_no_list_leaves_the_command_unchanged(self, slicing_job, monkeypatch):
        cli = self._stub_slicing_cli(monkeypatch)

        asyncio.run(jobs.run_slicing(slicing_job, SLAConfig()))

        assert "--import-support-points" not in cli.commands[0]


class TestStaleOutputCannotFakeSuccess:
    """Success is judged on the output file existing, so a leftover from an
    earlier run has to be removed before the engine starts - otherwise a failed
    export hands the caller a list describing a different model, and tells them
    it worked."""

    def test_a_failed_export_does_not_return_the_previous_list(self, job_dir, monkeypatch):
        stale = support_points_output_path(job_dir)
        stale.write_text('{"version": 1, "points": [{"STALE": true}]}')

        _stub_cli(monkeypatch, creates=None, stderr=b"engine refused this model")

        result = asyncio.run(export_support_points(job_dir, SLAConfig()))

        assert result.success is False
        assert result.support_points_path is None
        assert not stale.exists()
        assert "engine refused this model" in result.error

    def test_a_successful_export_replaces_the_previous_list(self, job_dir, monkeypatch):
        points_file = support_points_output_path(job_dir)
        points_file.write_text('{"version": 1, "points": [{"STALE": true}]}')

        _stub_cli(monkeypatch, creates=points_file)

        result = asyncio.run(export_support_points(job_dir, SLAConfig()))

        assert result.success is True
        assert "STALE" not in points_file.read_text()


class TestWriteInputRejectsNonsense:
    """None serializes to "null" and 5 to "5" - both are valid JSON documents
    and neither is a support point list. Failing here beats making the engine
    report a parse error on a file the backend wrote itself."""

    @pytest.mark.parametrize("bad", [None, 5, 1.5, True, object()])
    def test_unsupported_types_raise(self, job_dir, bad):
        with pytest.raises(TypeError):
            write_support_points_input(job_dir, bad)

        assert not support_points_input_path(job_dir).exists()

    @pytest.mark.parametrize("good", [b'{"points":[]}', '{"points":[]}',
                                      {"points": []}, [{"pos": [0, 0, 0]}]])
    def test_supported_types_are_written(self, job_dir, good):
        path = write_support_points_input(job_dir, good)
        assert path.exists()


class TestStatusFlagsSurviveAnExport:
    """write_job_status rewrites status.json wholesale, so anything the export
    does not restate is silently reset. A point export says nothing about the
    support mesh."""

    @pytest.fixture
    def job(self, tmp_path, monkeypatch):
        monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
        job_id = "export-job"
        (tmp_path / job_id / "input").mkdir(parents=True)
        (tmp_path / job_id / "output").mkdir()
        return job_id

    def _stub(self, monkeypatch, job_id, *, succeeds=True):
        out = support_points_output_path(jobs.get_job_dir(job_id))

        async def fake(cmd, stderr_file=None, stdout_file=None):
            if succeeds:
                out.write_text(json.dumps(SAMPLE_EXPORT))
            return 0, b"", b"nope"

        monkeypatch.setattr(sla_operations, "run_prusa_cli", fake)

    def test_has_support_mesh_is_carried_across(self, job, monkeypatch):
        from agent.models import JobStatus

        jobs.write_job_status(job, JobStatus.COMPLETED, has_support_mesh=True)
        self._stub(monkeypatch, job)

        asyncio.run(jobs.run_support_points_export(job, SLAConfig()))

        data = jobs.read_job_status(job)
        assert data["status"] == JobStatus.COMPLETED.value
        assert data["has_support_mesh"] is True

    def test_it_is_carried_across_on_failure_too(self, job, monkeypatch):
        from agent.models import JobStatus

        jobs.write_job_status(job, JobStatus.COMPLETED, has_support_mesh=True)
        self._stub(monkeypatch, job, succeeds=False)

        asyncio.run(jobs.run_support_points_export(job, SLAConfig()))

        data = jobs.read_job_status(job)
        assert data["status"] == JobStatus.FAILED.value
        assert data["has_support_mesh"] is True

    def test_a_job_without_a_mesh_stays_without_one(self, job, monkeypatch):
        from agent.models import JobStatus

        jobs.write_job_status(job, JobStatus.COMPLETED, has_support_mesh=False)
        self._stub(monkeypatch, job)

        asyncio.run(jobs.run_support_points_export(job, SLAConfig()))

        assert jobs.read_job_status(job)["has_support_mesh"] is False


class TestSupportTreeExportReachesTheCLI:
    """
    The support as data rather than triangles: heads, pillars, junctions,
    pedestals and one record per BAR of bracing.

    A caller that draws supports itself needs this instead of the STL. An STL is
    one lump - there is no way to point at a single bar in it, and no way to take
    that bar away - and recovering bars from triangle soup means guessing by
    connected components. The engine has always held them one record per bar.
    """

    def test_generation_always_asks_for_the_tree(self, job_dir, monkeypatch):
        # Unconditional: it costs a small JSON file, and it is the only form in
        # which a caller can address one bar.
        cli = _stub_cli(monkeypatch, stdout=b"Generated (supports only)\n")
        (job_dir / "output" / "model_support.stl").write_bytes(b"solid s\n")

        asyncio.run(generate_supports(job_dir, SLAConfig()))

        assert cli.flag_value("--export-support-tree") == str(
            sla_operations.support_tree_output_path(job_dir)
        )

    def test_the_tree_goes_to_the_output_directory(self, job_dir):
        # Input is what the caller supplied; this is what the engine produced.
        path = sla_operations.support_tree_output_path(job_dir)
        assert path.parent == job_dir / "output"
        assert path.name.endswith(".json")

    def test_input_file_stays_last_on_the_command_line(self, job_dir, monkeypatch):
        """The model path is positional and must not be consumed as the value of
        --export-support-tree."""
        cli = _stub_cli(monkeypatch, stdout=b"Generated (supports only)\n")
        (job_dir / "output" / "model_support.stl").write_bytes(b"solid s\n")

        asyncio.run(generate_supports(job_dir, SLAConfig()))

        assert cli.commands[0][-1] == str(job_dir / "input" / "model.stl")
