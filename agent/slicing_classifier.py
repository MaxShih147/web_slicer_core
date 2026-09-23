"""
SLA slicing result classifier.

Mirrors the support_classifier approach for the main slice flow.  Called by
run_slicing() after the CLI process exits; classifies both failure paths:

  A) Non-zero exit — classify stderr for known validate() / process() messages.
  B) Zero exit + missing output file — the same validate() scan, for engines
     that still exit 0 on a validate failure.

Two "nothing to print" cases apply to either path, whatever the exit code:
  • F-17 model-out-of-bounds  (message written to stdout by ProcessActions)
  • F-06 empty STL geometry   (message written to stderr by LoadPrintData)

Decision order (first match wins):
  Step 0  (either path) support-point/model mismatch -> FAILED +
                                                        SUPPORT_POINTS_MODEL_MISMATCH
  Step 5  (either path) model-out-of-bounds          -> FAILED + MODEL_OUT_OF_BOUNDS
  Step 6  (either path) empty model on stderr        -> FAILED + INVALID_MODEL
  Step 1  (non-zero) validate() patterns on stderr   -> FAILED + specific code
  Step 2  (non-zero) process() exception patterns    -> FAILED + specific code
  Step 3  (non-zero) STL parse error pattern         -> FAILED + INVALID_MODEL
  Step 4  (non-zero) unclassified                    -> FAILED, no code (JOB_FAILED)
  Step 6.x (zero-exit) validate() patterns           -> FAILED + specific code
  Step 7  (zero-exit) other missing-output           -> FAILED, no code (JOB_FAILED)
  —       exit 0 + output present                    -> None  (success, caller handles)

Steps 5 and 6 keep their numbers from when they sat on the zero-exit path only
(engine-error-code-table Section 6 moved them); the tests refer to them by
number.

All needle strings are English substrings of the untranslated C++ messages.
The slicer locale must be pinned to English (enforced separately) for Steps 1-3
to remain reliable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

# Single source of truth for the mismatch marker/code: the same literal the
# support flow matches on, pinned against the fork source by
# test_support_string_contract.py. Importing it here means the contract test
# protects this path too, instead of a second copy drifting unnoticed.
from .engine_rules import ENGINE_ERROR_PREFIX, engine_codes, find_code
from .support_classifier import MODEL_MISMATCH_CODE, MODEL_MISMATCH_MARKER

# ─── Path A: stderr patterns — validate() errors (exit ≠ 0) ──────────────────
# Taken from SLAPrint.cpp::validate() and SLA/Pad.cpp::PadConfig::validate().
# Ordered most-specific first; first match wins.
#
# merge-engine-result-classifiers: classify_slice_result() no longer reads
# this constant — both Step 1 (below) and Step 6.x now query the shared
# agent.engine_rules.ENGINE_RULES table (flow="slice") instead, so a fix like
# SUPPORT_POINTS_REQUIRED gaining the "slice" flow (Task 2.3) takes effect
# with no code change here. This tuple is kept, frozen at its original six
# entries, purely because test_slicing_classifier.py imports and pins it
# (`test_validate_map_covers_expected_six_codes`) — it documents "what this
# flow used to see" and no longer needs updating.
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


def _with_engine_lines(error: str, stdout: str) -> str:
    """Append the engine's own PHZ_ERROR lines to an unclassified error.
    Reached when the engine declared a code this flow does not map — e.g. one
    from an engine newer than this registry (engine-error-code-table D5). The
    code must not become the error_code, but the line is what a person
    debugging it needs, so it rides along in the detail."""
    lines = [line for line in stdout.splitlines() if line.startswith(ENGINE_ERROR_PREFIX)]
    return "\n".join([error, *lines]) if lines else error


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
    declared = engine_codes(out)

    # ── Step 0: imported support points do not describe this model ────────
    # Sits ahead of BOTH paths: before the exit-code split, before the
    # output-file check, and before the success return.
    #
    # Why before the exit-code split: --import-support-points is rejected in
    # ProcessActions.cpp before print->apply(), so validate() never runs and
    # none of Steps 1-6 can fire. Without this rule the run lands on Step 4 or
    # Step 7 with error_code=None, i.e. a bare JOB_FAILED, and the caller
    # cannot tell 'the model changed' from any other slice failure.
    #
    # Why before the success return: an .sl1 must never be accepted from a run
    # that rejected its own point list. The abort cannot produce one today,
    # so this only pins the fail-closed direction.
    if (MODEL_MISMATCH_CODE in declared
            or MODEL_MISMATCH_MARKER in err or MODEL_MISMATCH_MARKER in out):
        return SliceClassification(
            error=(err.strip() or out.strip()) or None,
            error_code=MODEL_MISMATCH_CODE,
        )

    # ── Steps 5-6: nothing to print (either path) ─────────────────────────────
    # Checked for any failed run, whatever the exit code, ahead of Step 1 as
    # they always were on the zero-exit path, so both paths keep one order.
    # merge-engine-result-classifiers left these two on the zero-exit path only,
    # as a named legacy branch; engine-error-code-table Section 6 removed it.
    if exit_code != 0 or not output_file_exists:
        # Step 5: F-17 model out of bounds (stdout; also scan stderr defensively)
        if (_OUT_OF_BOUNDS_CODE in declared
                or _OUT_OF_BOUNDS_MARKER in out or _OUT_OF_BOUNDS_MARKER in err):
            return SliceClassification(
                error=(out.strip() or err.strip()) or None,
                error_code=_OUT_OF_BOUNDS_CODE,
            )

        # Step 6: F-06 empty model geometry (stderr)
        if _EMPTY_MODEL_CODE in declared or _EMPTY_MODEL_MARKER in err:
            return SliceClassification(error=err.strip() or None, error_code=_EMPTY_MODEL_CODE)

    # ── Path A: non-zero exit ─────────────────────────────────────────────────
    if exit_code != 0:
        # Step 1: validate() patterns — queries the shared ENGINE_RULES table
        # (not _VALIDATE_CODE_MAP above — see its docstring) so a fix like
        # SUPPORT_POINTS_REQUIRED gaining the "slice" flow (Task 2.3) takes
        # effect here with no code change.
        rule = find_code("slice", err, out)
        if rule is not None:
            return SliceClassification(error=err.strip() or None, error_code=rule.code)

        # Step 2: process() exception patterns — the code the engine declared
        # first, the English needle second (engine-error-code-table D4).
        for _needle, code in _PROCESS_CODE_MAP:
            if code in declared:
                return SliceClassification(error=err.strip() or None, error_code=code)
        for needle, code in _PROCESS_CODE_MAP:
            if needle in err:
                return SliceClassification(error=err.strip() or None, error_code=code)

        # Step 3: STL parse error — "<filepath>: <exception.what()>"
        if f"{input_filename}:" in err:
            return SliceClassification(error=err.strip() or None, error_code=_INVALID_MODEL_CODE)

        # Step 4: unclassified — preserve backward-compatible error string
        return SliceClassification(
            error=_with_engine_lines(f"Exit code {exit_code}: {err}", out),
            error_code=None,
        )

    # ── Path B: zero exit but output file absent ──────────────────────────────
    if not output_file_exists:
        # Step 6.x: validate() errors — the fork's process_actions() returns 1 (bool
        # true) on validate failure, so the process exits 0 even though validate()
        # wrote a recognisable error to stderr. Reuses the same ENGINE_RULES
        # query as Path A Step 1 so there is only one source of truth for the
        # needle -> code mapping.
        rule = find_code("slice", err, out)
        if rule is not None:
            return SliceClassification(error=err.strip() or None, error_code=rule.code)

        # Step 7: other zero-exit / no-output — unclassified
        return SliceClassification(
            error=_with_engine_lines("Output file not created", out), error_code=None
        )

    # exit 0 + output present → success; caller proceeds normally
    return None
