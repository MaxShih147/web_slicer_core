"""
Tests for the v1 POST /api/jobs upload endpoint rejecting out-of-range
support point parameters — guard-support-density-bounds.

The range guards live in SLAConfig, so v1 picks them up too, but it keeps its
own pre-existing error shape: every config failure is wrapped as HTTP 400
"Invalid config: ...", not the v2 422 CONFIG_VALIDATION_ERROR. This change
does not alter that; these tests pin it.

Drives the real endpoint function directly (asyncio.run), matching
test_config_validation_422.py. The config is parsed before any job is
created, so create_job is patched to fail loudly if it is ever reached.

agent.main is imported inside a fixture, not at module level: importing it
attaches a handler to the "agent" logger and turns propagate off, which hides
agent.* records from caplog in every test that runs afterwards. The fixture
puts the logger back the way it found it.
"""

import asyncio
import io
import json
import logging

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile

_MINIMAL_STL = (
    b"solid test\n"
    b"facet normal 0 0 1\nouter loop\n"
    b"vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
    b"endloop\nendfacet\n"
    b"endsolid test\n"
)


@pytest.fixture(scope="module")
def main_module():
    agent_logger = logging.getLogger("agent")
    saved = (list(agent_logger.handlers), agent_logger.level, agent_logger.propagate)
    from agent import main

    yield main
    agent_logger.handlers[:] = saved[0]
    agent_logger.setLevel(saved[1])
    agent_logger.propagate = saved[2]


@pytest.fixture
def upload(main_module, monkeypatch):
    def _fail(job_id):
        raise AssertionError(f"create_job must not run for a rejected config (job {job_id})")

    monkeypatch.setattr(main_module, "create_job", _fail)

    def _upload(config: dict):
        file = UploadFile(file=io.BytesIO(_MINIMAL_STL), filename="model.stl")
        return asyncio.run(
            main_module.create_slicing_job(BackgroundTasks(), file, json.dumps(config))
        )

    return _upload


@pytest.mark.parametrize(
    "config, field",
    [
        ({"support_points_density_relative": -1}, "support_points_density_relative"),
        ({"support_points_density_relative": 10001}, "support_points_density_relative"),
        ({"support_points_min_distance": 150}, "support_points_min_distance"),
    ],
    ids=["negative-density", "density-over-limit", "min-distance-over-limit"],
)
def test_out_of_range_value_keeps_v1_400(upload, config, field):
    with pytest.raises(HTTPException) as exc_info:
        upload(config)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail.startswith("Invalid config:")
    assert field in exc_info.value.detail
