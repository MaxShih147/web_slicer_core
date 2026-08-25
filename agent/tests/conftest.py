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
