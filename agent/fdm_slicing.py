"""FDM (FFF) slicing via PrusaSlicer CLI.

Independent from `sla_operations` — different output format (gcode), different
metadata (filament length / print time vs. resin / layer count).
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Optional

from .config import PRUSA_SLICER_CLI
from .jobs_fdm import (
    FDMJobStatus,
    get_fdm_input_path,
    get_fdm_job_dir,
    write_fdm_status,
)


# PrusaSlicer writes G-code summary lines like:
#   ; estimated printing time (normal mode) = 1h 23m 45s
#   ; filament used [mm] = 1234.56
_RE_PRINT_TIME = re.compile(
    r"^;\s*estimated printing time\s*\([^)]+\)\s*=\s*(.+)$",
    re.IGNORECASE,
)
_RE_FILAMENT_MM = re.compile(
    r"^;\s*filament used \[mm\]\s*=\s*([\d.]+)",
    re.IGNORECASE,
)


def _parse_duration(text: str) -> Optional[float]:
    """`1h 23m 45s` -> seconds."""
    total = 0.0
    matched = False
    for n, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([dhms])", text):
        matched = True
        v = float(n)
        if unit == "d":
            total += v * 86400
        elif unit == "h":
            total += v * 3600
        elif unit == "m":
            total += v * 60
        elif unit == "s":
            total += v
    return total if matched else None


def _parse_gcode_summary(gcode_path: Path) -> tuple[Optional[float], Optional[float]]:
    """Read the trailing comment block of a PrusaSlicer-emitted G-code file.

    PrusaSlicer puts its summary near the end of the file, so we tail the last
    ~64 KB rather than scanning the whole thing (G-code can be 100+ MB).
    """
    print_time_s: Optional[float] = None
    filament_mm: Optional[float] = None

    try:
        size = gcode_path.stat().st_size
        with open(gcode_path, "rb") as f:
            f.seek(max(0, size - 65536))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None, None

    for line in tail.splitlines():
        if print_time_s is None:
            m = _RE_PRINT_TIME.match(line)
            if m:
                print_time_s = _parse_duration(m.group(1))
                continue
        if filament_mm is None:
            m = _RE_FILAMENT_MM.match(line)
            if m:
                try:
                    filament_mm = float(m.group(1))
                except ValueError:
                    pass
        if print_time_s is not None and filament_mm is not None:
            break

    return print_time_s, filament_mm


async def run_fdm_slicing(job_id: str):
    """Slice the job's input STL into G-code with PrusaSlicer's default FFF profile.

    PoC: no config knobs yet — uses whatever printer/filament/print profile
    PrusaSlicer ships as default (Original Prusa i3 MK3, 0.4 nozzle, generic PLA).
    Future: accept a profile selector or an inline FFFConfig.
    """
    job_dir = get_fdm_job_dir(job_id)
    input_path = get_fdm_input_path(job_id)
    output_path = job_dir / "output" / "model.gcode"
    stderr_file = job_dir / "stderr.log"

    write_fdm_status(job_id, FDMJobStatus.PROCESSING)

    if input_path is None:
        write_fdm_status(job_id, FDMJobStatus.FAILED, error="Input STL not found")
        return

    cmd = [
        str(PRUSA_SLICER_CLI),
        "--export-gcode",
        "--output", str(output_path),
        str(input_path),
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        with open(stderr_file, "wb") as f:
            f.write(stderr)

        if process.returncode != 0:
            write_fdm_status(
                job_id, FDMJobStatus.FAILED,
                error=f"PrusaSlicer exit {process.returncode}: "
                      f"{stderr.decode('utf-8', errors='replace')[-500:]}",
            )
            return

        if not output_path.exists():
            write_fdm_status(job_id, FDMJobStatus.FAILED, error="G-code not produced")
            return

        print_time_s, filament_mm = _parse_gcode_summary(output_path)
        write_fdm_status(
            job_id, FDMJobStatus.COMPLETED,
            has_gcode=True,
            estimated_print_time_s=print_time_s,
            filament_used_mm=filament_mm,
        )

    except Exception as e:
        write_fdm_status(job_id, FDMJobStatus.FAILED, error=str(e))
