"""Opt the agent and its slicer-engine children out of Windows EcoQoS.

The Electron launcher has no foreground window, so on hybrid (P/E-core) CPUs
Windows treats the agent and every engine it spawns as background work and
throttles them: the same 5M-face slice spent 64 s in the engine when the agent
started it and 38 s with execution-speed throttling switched off for the engine
alone (agent-large-model-perf, design D1).

``SetProcessInformation(ProcessPowerThrottling)`` with
``ControlMask = EXECUTION_SPEED`` and ``StateMask = 0`` turns that throttling
off explicitly (a ControlMask of 0 hands the decision back to the system).
Whether a child inherits it is unverified, so the agent sets itself once at
startup and each engine right after it is spawned.

Best effort only: on any other platform this is a no-op, and on Windows every
failure is logged and swallowed -- never an exception for the caller.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)

# processthreadsapi.h
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
# PROCESS_INFORMATION_CLASS: ProcessMemoryPriority = 0, ProcessMemoryExhaustionInfo,
# ProcessAppMemoryInfo, ProcessInPrivateInfo, ProcessPowerThrottling = 4
PROCESS_POWER_THROTTLING_CLASS = 4
# winnt.h
PROCESS_SET_INFORMATION = 0x0200

_kernel32: Any = None
_state_type: Any = None


def _load() -> tuple[Any, Any]:
    """kernel32 and the PROCESS_POWER_THROTTLING_STATE struct, loaded once.

    Only ever called on win32: ctypes.WinDLL does not exist elsewhere, so
    nothing Windows-only is touched at import time (design D7)."""
    global _kernel32, _state_type
    if _kernel32 is None:
        import ctypes
        from ctypes import wintypes

        class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
            _fields_ = [
                ("Version", wintypes.ULONG),
                ("ControlMask", wintypes.ULONG),
                ("StateMask", wintypes.ULONG),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetCurrentProcess.argtypes = []
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.SetProcessInformation.restype = wintypes.BOOL
        k32.SetProcessInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        _state_type = PROCESS_POWER_THROTTLING_STATE
        _kernel32 = k32
    return _kernel32, _state_type


def _last_error() -> int:
    import ctypes

    return ctypes.get_last_error()


def disable_execution_throttling(pid: Optional[int] = None, label: str = "") -> bool:
    """Switch EcoQoS execution-speed throttling off for one process.

    ``pid=None`` targets the agent itself. Returns True when Windows accepted
    the setting; False on any other platform or on any failure (logged as a
    WARNING on Windows, nothing at all elsewhere). Never raises.
    """
    if sys.platform != "win32":
        return False

    target = label or ("agent" if pid is None else f"pid {pid}")
    try:
        import ctypes

        k32, state_type = _load()
        state = state_type(
            PROCESS_POWER_THROTTLING_CURRENT_VERSION,
            PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
            0,
        )
        if pid is None:
            # A pseudo handle: valid without opening, never closed.
            handle = k32.GetCurrentProcess()
            owned = False
        else:
            handle = k32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
            if not handle:
                logger.warning(
                    "EcoQoS opt-out skipped for %s: OpenProcess failed (error %d)",
                    target, _last_error(),
                )
                return False
            owned = True
        try:
            ok = k32.SetProcessInformation(
                handle,
                PROCESS_POWER_THROTTLING_CLASS,
                ctypes.byref(state),
                ctypes.sizeof(state),
            )
            if not ok:
                logger.warning(
                    "EcoQoS opt-out failed for %s: SetProcessInformation error %d",
                    target, _last_error(),
                )
                return False
        finally:
            if owned:
                k32.CloseHandle(handle)
    except Exception as exc:  # best effort: never reach the caller
        logger.warning("EcoQoS opt-out failed for %s: %s: %s", target, type(exc).__name__, exc)
        return False

    if pid is None:
        logger.info("EcoQoS execution-speed throttling disabled for the agent")
    else:
        logger.debug("EcoQoS execution-speed throttling disabled for %s", target)
    return True


def disable_for_child(process: Any, label: str = "slicer-engine") -> bool:
    """``disable_execution_throttling`` for a spawned subprocess.

    Reads ``process.pid`` defensively: a process object without an integer pid
    (a test double, or one that failed to start) is skipped rather than
    falling through to ``pid=None``, which would target the agent itself.
    Never raises."""
    try:
        pid = getattr(process, "pid", None)
    except Exception:
        return False
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    return disable_execution_throttling(pid, f"{label} (pid {pid})")
