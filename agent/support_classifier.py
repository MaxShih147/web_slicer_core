"""
Support-generation result classifier — the five-step decision tree.

This is a pure function: given the raw ``stdout`` / ``stderr`` of the
support-only PrusaSlicer CLI run (plus whether the support STL landed on
disk), it returns a structured classification. It deliberately does NOT look
at the process exit code — the fork's ``validate()`` failures return exit 0
(``return 1`` in a ``bool`` function), so the exit code is not a reliable
signal (see openspec/changes/add-support-generation-error-codes, design D1).

Decision order (first match wins):

    Step 0  output hits the point/model mismatch marker
                                                    -> FAILED + SUPPORT_POINTS_MODEL_MISMATCH
    Step 1  stderr hits a known validate() error   -> FAILED + specific code
            stderr hits a non-support validate error-> FAILED + fallback
    Step 2  stdout/stderr hits model-out-of-bounds  -> FAILED + MODEL_OUT_OF_BOUNDS
    Step 3  stdout hits a "no real supports" marker -> COMPLETED + SUPPORT_NOT_NEEDED
    Step 4  stdout hits a "has supports" marker      -> COMPLETED + has_support_mesh
    Step 5  nothing attributable / conflicting       -> FAILED + fallback (fail-closed)

All markers are matched as English substrings. The validate() strings are
translatable (``_u8L``), so the engine locale must be pinned to English for
Step 1 to stay reliable (enforced separately; see Task 7). The Step 0 marker and
the stdout markers (Step 2-4) are raw literals and are not translated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from .models import JobStatus

# Neutral supportOutcome value — NOT an error code; rides on a COMPLETED job.
SUPPORT_NOT_NEEDED = "SUPPORT_NOT_NEEDED"

# Fallback error code for anything unattributable (fail-closed).
FALLBACK_CODE = "SUPPORT_GENERATION_FAILED"

# ─── Step 0: imported support points do not belong to this model ──────────────
# Printed verbatim to stderr by ProcessActions.cpp before print->apply(), so the
# run aborts before validate() and before any positive stdout marker can appear.
# The literal is a contract with the fork; it is defined once in
# src/libslic3r/SLA/SupportPointIO.hpp as support_points_model_mismatch_marker
# and is pinned by test_support_string_contract.py.
#
# Checked FIRST, ahead of the fail-closed fallback, so "the model changed" is
# never flattened into the generic "support generation failed" — the two need
# different fixes on the caller's side (regenerate the points vs. adjust
# settings). Like every other rule here it keys on text only, never on the
# returncode: this fork exits 0 from several failing paths.
MODEL_MISMATCH_MARKER = (
    "SUPPORT_POINTS_MODEL_MISMATCH: imported support points do not match this model"
)
MODEL_MISMATCH_CODE = "SUPPORT_POINTS_MODEL_MISMATCH"

# ─── Step 1: known SLAPrint::validate() messages → specific support code ───────
# Distinctive English substrings taken from src/libslic3r/SLAPrint.cpp::validate().
# The messages are mutually exclusive; list order only fixes determinism.
VALIDATE_CODE_MAP = (
    ("Cannot proceed without support points", "SUPPORT_POINTS_REQUIRED"),
    ("Elevation is too low for object", "SUPPORT_ELEVATION_TOO_LOW"),
    ("The endings of the support pillars", "SUPPORT_PAD_GAP_CONFLICT"),
    ("Invalid Head penetration", "SUPPORT_HEAD_PENETRATION_INVALID"),
    ("Invalid pinhead diameter", "SUPPORT_HEAD_TOO_WIDE"),
)

# validate() errors that are genuine failures but not support-specific. Matched
# at Step 1 (before the stdout markers) so a validate failure always wins over a
# stray marker, per the "Step 1 first" ordering. They route to the fallback code.
NONSPECIFIC_VALIDATE_MARKERS = (
    "xposition time is out of printer profile bounds",  # "Exposition"/"Initial exposition"
    "Disabling the 'Use tilt' function",
)

# ─── Step 2: model placement failure (printed on stdout) ──────────────────────
OUT_OF_BOUNDS_MARKER = "no object is fully inside the print volume"
OUT_OF_BOUNDS_CODE = "MODEL_OUT_OF_BOUNDS"

# ─── Step 3/4: authoritative stdout markers (raw literals, not translated) ─────
NOT_NEEDED_MARKERS = ("(pad only)", "No support/pad mesh generated")
HAS_SUPPORT_MARKERS = ("(supports only)", "(includes supports and pad)")


@dataclass(frozen=True)
class SupportClassification:
    """Structured outcome of a support-generation run."""

    status: JobStatus
    error_code: Optional[str] = None
    support_outcome: Optional[str] = None
    has_support_mesh: bool = False
    detail: Optional[str] = None


def _to_text(stream: Union[str, bytes, bytearray, None]) -> str:
    if stream is None:
        return ""
    if isinstance(stream, (bytes, bytearray)):
        return bytes(stream).decode("utf-8", errors="replace")
    return str(stream)


def _raw_appendix(stdout_text: str, stderr_text: str) -> str:
    return f"stdout:\n{stdout_text}\n---\nstderr:\n{stderr_text}"


def classify_support_result(
    stdout: Union[str, bytes, None],
    stderr: Union[str, bytes, None],
    support_stl_exists: bool,
) -> SupportClassification:
    """Classify a support-only CLI run from its text output (never the exit code)."""
    out = _to_text(stdout)
    err = _to_text(stderr)

    # ── Step 0: imported points reject the model → dedicated code ────────────
    # Scanned on both streams for the same reason as Step 2: the marker goes to
    # stderr today, and a future stream reshuffle must not silently downgrade
    # this to the fallback code.
    if MODEL_MISMATCH_MARKER in err or MODEL_MISMATCH_MARKER in out:
        return SupportClassification(
            status=JobStatus.FAILED,
            error_code=MODEL_MISMATCH_CODE,
            has_support_mesh=False,
            detail=_raw_appendix(out, err),
        )

    # ── Step 1: known validate() errors on stderr ────────────────────────────
    for needle, code in VALIDATE_CODE_MAP:
        if needle in err:
            return SupportClassification(
                status=JobStatus.FAILED,
                error_code=code,
                detail=err.strip() or None,
            )
    for needle in NONSPECIFIC_VALIDATE_MARKERS:
        if needle in err:
            # Attributed to the fallback code, so the debug appendix MUST carry
            # BOTH raw streams (spec: "失敗時原始輸出可供除錯"), consistent with
            # every other SUPPORT_GENERATION_FAILED path below.
            return SupportClassification(
                status=JobStatus.FAILED,
                error_code=FALLBACK_CODE,
                detail=_raw_appendix(out, err),
            )

    # ── Step 2: model out of bounds (marker on stdout; scan stderr too) ───────
    if OUT_OF_BOUNDS_MARKER in out or OUT_OF_BOUNDS_MARKER in err:
        return SupportClassification(
            status=JobStatus.FAILED,
            error_code=OUT_OF_BOUNDS_CODE,
            detail=_raw_appendix(out, err),
        )

    # ── Positive detection: scan stdout for the authoritative markers ─────────
    not_needed = any(m in out for m in NOT_NEEDED_MARKERS)
    has_support = any(m in out for m in HAS_SUPPORT_MARKERS)

    # Conflicting mutually-exclusive markers (e.g. unexpected multi-object
    # output) → fail-closed rather than arbitrarily trusting one marker.
    if not_needed and has_support:
        return SupportClassification(
            status=JobStatus.FAILED,
            error_code=FALLBACK_CODE,
            detail=_raw_appendix(out, err),
        )

    # ── Step 3: neutral "no real supports" → COMPLETED (not an error) ─────────
    if not_needed:
        return SupportClassification(
            status=JobStatus.COMPLETED,
            support_outcome=SUPPORT_NOT_NEEDED,
            has_support_mesh=False,
        )

    # ── Step 4: real support pillars → COMPLETED with a mesh ──────────────────
    if has_support:
        # Marker is authoritative and is only printed inside the write-success
        # branch, so the STL must exist. If it somehow doesn't, that is a
        # marker/file inconsistency → fail-closed (never upgrade to success on
        # a missing file).
        if not support_stl_exists:
            return SupportClassification(
                status=JobStatus.FAILED,
                error_code=FALLBACK_CODE,
                detail=_raw_appendix(out, err),
            )
        return SupportClassification(
            status=JobStatus.COMPLETED,
            has_support_mesh=True,
        )

    # ── Step 5: unattributable → fail-closed with the raw streams attached ────
    return SupportClassification(
        status=JobStatus.FAILED,
        error_code=FALLBACK_CODE,
        detail=_raw_appendix(out, err),
    )