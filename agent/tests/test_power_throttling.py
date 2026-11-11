"""agent-large-model-perf, spec agent-power-throttling (design D1, D7).

The Win32 layer is replaced by a fake kernel32 so the parameters, handle
handling and failure paths are checked on any platform; one smoke test makes
the real call on the test process itself, on Windows only.
"""

import asyncio
import ctypes
import logging
import sys

import pytest

from agent import power_throttling as pt
from agent import sla_operations


class _FakeKernel32:
    """Records calls; behaviour switches let each test pick a failure."""

    def __init__(self, open_ok=True, set_ok=True, raise_on_set=False):
        self.open_ok = open_ok
        self.set_ok = set_ok
        self.raise_on_set = raise_on_set
        self.opened = []
        self.closed = []
        self.set_calls = []

    def GetCurrentProcess(self):
        return -1  # the pseudo handle Windows returns

    def OpenProcess(self, access, inherit, pid):
        self.opened.append((access, inherit, pid))
        return 0x1234 if self.open_ok else 0

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1

    def SetProcessInformation(self, handle, info_class, state_ref, size):
        if self.raise_on_set:
            raise OSError("boom")
        state = state_ref._obj
        self.set_calls.append(
            (handle, info_class, state.Version, state.ControlMask, state.StateMask, size)
        )
        return 1 if self.set_ok else 0


class _State(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


@pytest.fixture
def fake_win(monkeypatch):
    k32 = _FakeKernel32()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(pt, "_load", lambda: (k32, _State))
    monkeypatch.setattr(pt, "_last_error", lambda: 87)
    return k32


@pytest.mark.real_power_throttling
class TestDisableExecutionThrottling:
    def test_self_uses_pseudo_handle_and_turns_speed_throttling_off(self, fake_win, caplog):
        caplog.set_level(logging.INFO, logger=pt.__name__)
        assert pt.disable_execution_throttling() is True
        assert fake_win.opened == []
        assert fake_win.closed == []  # the pseudo handle is never closed
        [(handle, cls, version, control, state, size)] = fake_win.set_calls
        assert handle == -1
        assert cls == 4  # ProcessPowerThrottling
        assert (version, control, state) == (1, 0x1, 0)
        assert size == ctypes.sizeof(_State)
        assert "disabled for the agent" in caplog.text

    def test_child_opens_with_set_information_and_closes_handle(self, fake_win):
        assert pt.disable_execution_throttling(4321, "engine") is True
        assert fake_win.opened == [(0x0200, False, 4321)]
        assert fake_win.set_calls[0][0] == 0x1234
        assert fake_win.closed == [0x1234]

    def test_open_process_failure_only_warns(self, fake_win, caplog):
        fake_win.open_ok = False
        assert pt.disable_execution_throttling(4321, "engine") is False
        assert fake_win.set_calls == []
        assert "OpenProcess failed (error 87)" in caplog.text

    def test_set_information_failure_only_warns_and_still_closes(self, fake_win, caplog):
        fake_win.set_ok = False
        assert pt.disable_execution_throttling(4321, "engine") is False
        assert fake_win.closed == [0x1234]
        assert "SetProcessInformation error 87" in caplog.text
        assert "engine" in caplog.text

    def test_exception_is_swallowed_and_handle_closed(self, fake_win, caplog):
        fake_win.raise_on_set = True
        assert pt.disable_execution_throttling(4321) is False
        assert fake_win.closed == [0x1234]
        assert "OSError" in caplog.text

    def test_load_failure_is_swallowed(self, monkeypatch, caplog):
        monkeypatch.setattr(sys, "platform", "win32")

        def broken():
            raise OSError("no kernel32")

        monkeypatch.setattr(pt, "_load", broken)
        assert pt.disable_execution_throttling() is False
        assert "no kernel32" in caplog.text

    def test_other_platforms_do_nothing_and_log_nothing(self, monkeypatch, caplog):
        monkeypatch.setattr(sys, "platform", "darwin")

        def must_not_load():
            raise AssertionError("kernel32 must not be loaded off Windows")

        monkeypatch.setattr(pt, "_load", must_not_load)
        caplog.set_level(logging.DEBUG, logger=pt.__name__)
        assert pt.disable_execution_throttling() is False
        assert pt.disable_execution_throttling(4321) is False
        assert caplog.records == []


@pytest.mark.real_power_throttling
class TestDisableForChild:
    @pytest.mark.parametrize("pid", [None, 0, -5, "123", True, 1.5])
    def test_no_usable_pid_never_targets_the_agent(self, fake_win, pid):
        class P:
            pass

        proc = P()
        if pid is not None:
            proc.pid = pid
        assert pt.disable_for_child(proc) is False
        assert fake_win.set_calls == []

    def test_real_pid_is_passed_through(self, fake_win):
        class P:
            pid = 999

        assert pt.disable_for_child(P()) is True
        assert fake_win.opened[0][2] == 999


class TestEngineSpawnWiring:
    """Every slicer-engine spawn opts its child out (spec: run_prusa_cli)."""

    def test_run_prusa_cli_opts_out_the_spawned_engine_once(self, monkeypatch):
        class Proc:
            pid = 4242
            returncode = 0

            async def communicate(self):
                return b"", b""

        async def fake_exec(*args, **kwargs):
            return Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        asyncio.run(sla_operations.run_prusa_cli(["engine", "--help"]))
        assert pt._test_calls == [(4242, "slicer-engine (pid 4242)")]

    def test_every_create_subprocess_exec_in_the_agent_is_followed_by_the_opt_out(self):
        """Source-level guard: a new engine spawn site must not forget D1."""
        from pathlib import Path

        agent_dir = Path(pt.__file__).parent
        for path in agent_dir.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            spawns = text.count("asyncio.create_subprocess_exec(")
            if spawns:
                assert text.count("disable_for_child(process)") == spawns, path.name


@pytest.mark.real_power_throttling
@pytest.mark.skipif(sys.platform != "win32", reason="real Win32 call")
def test_real_call_on_this_process_succeeds_on_windows():
    assert pt.disable_execution_throttling(label="pytest") is True
