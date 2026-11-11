"""
Shared pytest fixtures for the agent test suite.

Task 5.5 (add-slicing-progress).
"""

import pytest

from agent import jobs
from agent.engine_job_queue import reset_engine_job_queue_for_tests


@pytest.fixture(autouse=True)
def _isolate_job_progress():
    """Reset the in-memory slice-progress store around every test.

    The store is module-level state in ``agent.jobs``, so without this any test
    that records progress would leak into later ones and make results depend on
    collection order. Autouse (rather than opt-in) because Sections 6 and 7 add
    tests in other files that also touch the store — an opt-in fixture would
    silently miss them.

    Clearing on both sides keeps a test isolated even if an earlier one failed
    part-way through and left an entry behind.
    """
    jobs.job_progress.clear()
    reset_engine_job_queue_for_tests()
    yield
    jobs.job_progress.clear()
    reset_engine_job_queue_for_tests()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_power_throttling: let agent.power_throttling reach the real Win32 API",
    )


@pytest.fixture(autouse=True)
def _no_real_power_throttling(request, monkeypatch):
    """Keep the suite from touching real processes' power settings.

    Engine fakes report made-up pids (4242, ...); on Windows the EcoQoS opt-out
    (agent-large-model-perf D1) would otherwise OpenProcess() whatever really
    has that pid. Tests that exercise the module itself opt back in with
    ``@pytest.mark.real_power_throttling`` and stub the Win32 layer themselves.
    """
    if request.node.get_closest_marker("real_power_throttling"):
        yield
        return
    from agent import power_throttling

    calls = []

    def _recording(pid=None, label=""):
        calls.append((pid, label))
        return False

    monkeypatch.setattr(power_throttling, "disable_execution_throttling", _recording)
    power_throttling._test_calls = calls
    yield
