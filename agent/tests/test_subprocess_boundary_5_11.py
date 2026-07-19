"""REQ-DEID-008 / tasks 5.11 — engine must stay out-of-process (subprocess boundary).

Asserts the agent launches slicer-engine as a separate OS process and does not
load slicer_core.dll into the agent process address space.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from agent import config


def _engine_cli() -> Path:
    cli = Path(config.SLICER_ENGINE_CLI)
    if not cli.is_file():
        pytest.skip(f"slicer-engine CLI not found: {cli}")
    return cli


@pytest.mark.asyncio
async def test_engine_runs_as_separate_process():
    """create_subprocess_exec must spawn a distinct PID for --help."""
    cli = _engine_cli()
    agent_pid = os.getpid()

    proc = await asyncio.create_subprocess_exec(
        str(cli),
        "--help",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.pid is not None
    assert proc.pid != agent_pid, "engine must not share agent PID (in-process link forbidden)"

    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, (stderr or stdout).decode("utf-8", errors="replace")
    text = (stdout + stderr).decode("utf-8", errors="replace")
    assert "slicer-engine" in text.lower() or "Slicer Engine" in text
    assert "PrusaSlicer" not in text


def test_agent_process_does_not_map_engine_dll():
    """Agent Python process must not have slicer_core.dll loaded (Win) / no in-process link."""
    if sys.platform != "win32":
        pytest.skip("Windows module enumeration")

    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        pytest.skip("ctypes unavailable")

    # Enumerate modules in this process via ToolHelp32
    TH32CS_SNAPMODULE = 0x00000008
    TH32CS_SNAPMODULE32 = 0x00000010
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class MODULEENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("th32ModuleID", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("GlblcntUsage", wintypes.DWORD),
            ("ProccntUsage", wintypes.DWORD),
            ("modBaseAddr", ctypes.POINTER(wintypes.BYTE)),
            ("modBaseSize", wintypes.DWORD),
            ("hModule", wintypes.HMODULE),
            ("szModule", wintypes.WCHAR * 256),
            ("szExePath", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CreateToolhelp32Snapshot = kernel32.CreateToolhelp32Snapshot
    CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    Module32FirstW = kernel32.Module32FirstW
    Module32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
    Module32FirstW.restype = wintypes.BOOL
    Module32NextW = kernel32.Module32NextW
    Module32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
    Module32NextW.restype = wintypes.BOOL
    CloseHandle = kernel32.CloseHandle

    snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, os.getpid())
    if snap == INVALID_HANDLE_VALUE or snap is None:
        pytest.skip("CreateToolhelp32Snapshot failed")

    names: list[str] = []
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
        ok = Module32FirstW(snap, ctypes.byref(entry))
        while ok:
            names.append(entry.szModule.lower())
            ok = Module32NextW(snap, ctypes.byref(entry))
    finally:
        CloseHandle(snap)

    forbidden = ("slicer_core.dll", "prusaslicer.dll", "libslic3r")
    hits = [n for n in names if any(f in n for f in forbidden)]
    assert not hits, f"agent process mapped engine libraries (AGPL boundary break): {hits}"


def test_config_points_at_external_cli_path():
    """SLICER_ENGINE_CLI must be a filesystem path to an executable, not empty."""
    cli = Path(config.SLICER_ENGINE_CLI)
    assert cli.name.lower().startswith("slicer-engine") or "slicer-engine" in str(cli).lower()
    assert "prusaslicer" not in cli.name.lower()
