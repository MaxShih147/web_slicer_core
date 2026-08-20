"""
SLA slicing result classifier.

Mirrors the support_classifier approach for the main slice flow.  Called by
run_slicing() after the CLI process exits; classifies both failure paths:

  A) Non-zero exit — classify stderr for known validate() / process() messages.
  B) Zero exit + missing output file — scan stdout/stderr for the two special
     cases that produce exit 0 but no .sl1:
       • F-17 model-out-of-bounds  (message written to stdout by ProcessActions)
       • F-06 empty STL geometry   (message written to stderr by LoadPrintData)

Decision order (first match wins):
  Step 1  validate() patterns on stderr              -> FAILED + specific code
  Step 2  process() exception patterns on stderr     -> FAILED + specific code
  Step 3  STL parse error pattern on stderr          -> FAILED + INVALID_MODEL
  Step 4  unclassified non-zero exit                 -> FAILED, no code (JOB_FAILED)
  Step 5  (zero-exit) model-out-of-bounds on stdout  -> FAILED + MODEL_OUT_OF_BOUNDS
  Step 6  (zero-exit) empty model on stderr          -> FAILED + INVALID_MODEL
  Step 7  (zero-exit) other missing-output           -> FAILED, no code (JOB_FAILED)
  —       exit 0 + output present                    -> None  (success, caller handles)

All needle strings are English substrings of the untranslated C++ messages.
The slicer locale must be pinned to English (enforced separately) for Steps 1-3
to remain reliable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

# ─── Path A: stderr patterns — validate() errors (exit ≠ 0) ──────────────────
# Taken from SLAPrint.cpp::validate() and SLA/Pad.cpp::PadConfig::validate().
# Ordered most-specific first; first match wins.
_VALIDATE_CODE_MAP: tuple[tuple[str, str], ...] = (
    ("Elevation is too low for object",                "SUPPORT_ELEVATION_TOO_LOW"),
    ("The endings of the support pillars",             "SUPPORT_PAD_GAP_CONFLICT"),
    ("Pad brim size is too small",                     "PAD_CONFIG_INVALID"),
    # Covers both "Exposition time..." (F-12) and "Initial exposition time..." (F-13).
    ("xposition time is out of printer profile bounds", "EXPOSURE_TIME_OUT_OF_RANGE"),
    ("Invalid Head penetration",                       "SUPPORT_HEAD_PENETRATION_INVALID"),
    ("Invalid pinhead diameter",                       "SUPPORT_HEAD_TOO_WIDE"),
)

# ─── Path A: stderr patterns — process() exceptions (exit ≠ 0) ───────────────
# Taken from SLAPrintSteps.cpp throw sites.
_PROCESS_CODE_MAP: tuple[tuple[str, str], ...] = (
    ("can not be sliced",             "MODEL_MESH_UNSLICEABLE"),   # F-18 RuntimeError
    ("There are unprintable objects", "UNPRINTABLE_OBJECT"),        # F-19 SlicingError
    ("No pad can be generated",       "PAD_GENERATION_FAILED"),     # F-20 SlicingError
)

# ─── Path B: zero-exit special cases ─────────────────────────────────────────

# F-17 — ProcessActions.cpp writes this to stdout when print->empty() is true.
# support_classifier scans both stdout and stderr; we do the same defensively.
_OUT_OF_BOUNDS_MARKER = "no object is fully inside the print volume"
_OUT_OF_BOUNDS_CODE = "MODEL_OUT_OF_BOUNDS"

# F-06 — LoadPrintData.cpp writes this to stderr when model.objects.empty(),
# but continues (no return false), so exit code stays 0 and no output is created.
_EMPTY_MODEL_MARKER = "Error: file is empty:"
_EMPTY_MODEL_CODE = "INVALID_MODEL"

# ─── Path A: STL parse error ──────────────────────────────────────────────────
# F-05 — LoadPrintData.cpp: `cerr << file << ": " << e.what()`.
# The full path contains the input basename before the ": " separator, so
# matching "<basename>:" reliably identifies a parse-time exception (not a
# validate/process message).
_INVALID_MODEL_CODE = "INVALID_MODEL"


@dataclass(frozen=True)
class SliceClassification:
    """
    Failure outcome of a slice CLI run.

    ``error``      — human-readable detail forwarded to write_job_status();
                     passed as ``detail`` to the APIError factory.
    ``error_code`` — specific code string, or None → generic JOB_FAILED.
    """
    error: Optional[str]
    error_code: Optional[str]


def _decode(stream: Union[str, bytes, bytearray, None]) -> str:
    if stream is None:
        return ""
    if isinstance(stream, (bytes, bytearray)):
        return bytes(stream).decode("utf-8", errors="replace")
    return str(stream)


def classify_slice_result(
    exit_code: int,
    stdout: Union[str, bytes, None],
    stderr: Union[str, bytes, None],
    input_filename: str,
    output_file_exists: bool,
) -> Optional[SliceClassification]:
    """
    Classify a slice CLI run.

    Returns a ``SliceClassification`` describing any failure, or ``None`` when
    the run succeeded (exit 0 and output file present).

    Parameters
    ----------
    exit_code         : process return code
    stdout / stderr   : raw CLI output captured from the subprocess
    input_filename    : basename of the uploaded model (e.g. ``"model.stl"``);
                        used to detect STL parse errors (F-05)
    output_file_exists: whether the expected .sl1 output was created on disk
    """
    out = _decode(stdout)
    err = _decode(stderr)

    # ── Path A: non-zero exit ─────────────────────────────────────────────────
    if exit_code != 0:
        # Step 1: validate() patterns
        for needle, code in _VALIDATE_CODE_MAP:
            if needle in err:
                return SliceClassification(error=err.strip() or None, error_code=code)

        # Step 2: process() exception patterns
        for needle, code in _PROCESS_CODE_MAP:
            if needle in err:
                return SliceClassification(error=err.strip() or None, error_code=code)

        # Step 3: STL parse error — "<filepath>: <exception.what()>"
        if f"{input_filename}:" in err:
            return SliceClassification(error=err.strip() or None, error_code=_INVALID_MODEL_CODE)

        # Step 4: unclassified — preserve backward-compatible error string
        return SliceClassification(
            error=f"Exit code {exit_code}: {err}",
            error_code=None,
        )

    # ── Path B: zero exit but output file absent ──────────────────────────────
    if not output_file_exists:
        # Step 5: F-17 model out of bounds (stdout; also scan stderr defensively)
        if _OUT_OF_BOUNDS_MARKER in out or _OUT_OF_BOUNDS_MARKER in err:
            return SliceClassification(
                error=(out.strip() or err.strip()) or None,
                error_code=_OUT_OF_BOUNDS_CODE,
            )

        # Step 6: F-06 empty model geometry (stderr)
        if _EMPTY_MODEL_MARKER in err:
            return SliceClassification(error=err.strip() or None, error_code=_EMPTY_MODEL_CODE)

        # Step 7: other zero-exit / no-output — unclassified
        return SliceClassification(error="Output file not created", error_code=None)

    # exit 0 + output present → success; caller proceeds normally
    return None
