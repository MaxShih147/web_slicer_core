"""
Single shared table of (engine output -> error code) rules, consulted by both
`support_classifier.classify_support_result()` and
`slicing_classifier.classify_slice_result()` for the subset of their decision
logic that used to be duplicated as two hand-copied
``(needle, code)`` tuples (`support_classifier.VALIDATE_CODE_MAP` and
`slicing_classifier._VALIDATE_CODE_MAP`) — see
openspec/changes/merge-engine-result-classifiers.

Each row is keyed on `code` (never on the matcher string), and carries which
flows it applies to. A rule shared by both flows appears exactly once here,
with ``flows=("support", "slice")`` — so fixing one flow's blind spot to a
message the other flow already recognized is a one-line data change, not a
second hand-copy.

Not in scope here (kept local to each classifier, since neither was ever
duplicated across both flows): the model/support-point mismatch marker, the
model-out-of-bounds marker, the support flow's positive "has supports" /
"not needed" success markers, the slice flow's process()-exception map
(`_PROCESS_CODE_MAP`), its STL-parse-error detection, and its empty-model
marker.

`exit_code` is deliberately NOT a field here (design D3): the fork's
`validate()` failures used to return process exit 0 (`return 1` inside `bool`
functions), and engines built before engine-error-code-table Section 4 still
do, so exit code is not a reliable classification signal. No code needs
`exit_code == 0` any more; the call-site legacy branch that did was removed in
engine-error-code-table Section 6.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional, Tuple, Union

# engine-error-code-table D2: the engine reports a failure as one stdout line,
# "PHZ_ERROR " followed by a JSON object carrying at least "code".
ENGINE_ERROR_PREFIX = "PHZ_ERROR "


def engine_codes(stdout: str) -> Tuple[str, ...]:
    """Every code the engine declared on stdout, in output order. A line that
    is not valid JSON, or has no string "code", is skipped: a garbled report
    must fall back to the string layer, not break classification."""
    codes = []
    for line in stdout.splitlines():
        if not line.startswith(ENGINE_ERROR_PREFIX):
            continue
        try:
            payload = json.loads(line[len(ENGINE_ERROR_PREFIX):])
        except ValueError:
            continue
        code = payload.get("code") if isinstance(payload, dict) else None
        if isinstance(code, str):
            codes.append(code)
    return tuple(codes)


@dataclass(frozen=True)
class EngineCode:
    """Matches when the engine itself declared `code` on stdout
    (engine-error-code-table). Placed ahead of Substring in every row: the
    engine is the side that actually made the decision, the English text is
    only a translatable message about it."""

    code: str

    def matches(self, stderr: str, stdout: str) -> bool:
        return self.code in engine_codes(stdout)


@dataclass(frozen=True)
class Substring:
    """Matches when `text` is a substring of the engine's stderr. Kept as the
    second layer until a bundle with the coded engine has shipped (design D4,
    merge-engine-result-classifiers design D2)."""

    text: str

    def matches(self, stderr: str, stdout: str) -> bool:
        return self.text in stderr


Matcher = Union[EngineCode, Substring]


@dataclass(frozen=True)
class Rule:
    code: str
    flows: Tuple[str, ...]  # "support" and/or "slice"
    stream: str  # "stdout" | "stderr" | "both" — informational: the stream
    # the row's Substring reads. EngineCode always reads stdout (design D2).
    matchers: Tuple[Matcher, ...]
    priority: int
    fallback_by_design: bool = False


# Priorities only need to break ties between rules that could both match the
# same text; in practice these validate() messages are mutually exclusive
# (each run prints at most one), so the exact ordering here has never been
# load-bearing — see the identical comment this replaces in each classifier.
ENGINE_RULES: Tuple[Rule, ...] = (
    Rule(
        code="SUPPORT_POINTS_REQUIRED",
        # Task 2.3: previously support-only. The slice flow used to have no
        # code for this message and fell all the way to bare JOB_FAILED.
        flows=("support", "slice"),
        stream="stderr",
        matchers=(EngineCode("SUPPORT_POINTS_REQUIRED"), Substring("Cannot proceed without support points"),),
        priority=10,
    ),
    Rule(
        code="SUPPORT_ELEVATION_TOO_LOW",
        flows=("support", "slice"),
        stream="stderr",
        matchers=(EngineCode("SUPPORT_ELEVATION_TOO_LOW"), Substring("Elevation is too low for object"),),
        priority=20,
    ),
    Rule(
        code="SUPPORT_PAD_GAP_CONFLICT",
        flows=("support", "slice"),
        stream="stderr",
        matchers=(EngineCode("SUPPORT_PAD_GAP_CONFLICT"), Substring("The endings of the support pillars"),),
        priority=30,
    ),
    Rule(
        code="SUPPORT_HEAD_PENETRATION_INVALID",
        flows=("support", "slice"),
        stream="stderr",
        matchers=(EngineCode("SUPPORT_HEAD_PENETRATION_INVALID"), Substring("Invalid Head penetration"),),
        priority=40,
    ),
    Rule(
        code="SUPPORT_HEAD_TOO_WIDE",
        flows=("support", "slice"),
        stream="stderr",
        matchers=(EngineCode("SUPPORT_HEAD_TOO_WIDE"), Substring("Invalid pinhead diameter"),),
        priority=50,
    ),
    Rule(
        code="PAD_CONFIG_INVALID",
        # Task 2.2: previously slice-only. The support flow used to have no
        # code for this message and fell all the way to SUPPORT_GENERATION_FAILED.
        flows=("slice", "support"),
        stream="stderr",
        matchers=(EngineCode("PAD_CONFIG_INVALID"), Substring("Pad brim size is too small"),),
        priority=60,
    ),
    Rule(
        code="EXPOSURE_TIME_OUT_OF_RANGE",
        flows=("slice",),
        stream="stderr",
        # Covers both "Exposition time..." (F-12) and "Initial exposition
        # time..." (F-13).
        matchers=(EngineCode("EXPOSURE_TIME_OUT_OF_RANGE"), Substring("xposition time is out of printer profile bounds"),),
        priority=70,
    ),
    # Task 2.4 (D5): a known validate() message with deliberately no dedicated
    # code — flagged fallback_by_design=True so it reads as "seen and
    # intentionally routed to the fallback", not as a gap in this table.
    # code is a literal here (not imported) to avoid a circular import with
    # support_classifier, which imports find_code from this module; it must
    # match support_classifier.FALLBACK_CODE.
    Rule(
        code="SUPPORT_GENERATION_FAILED",
        flows=("support",),
        stream="stderr",
        matchers=(Substring("Disabling the 'Use tilt' function"),),
        priority=80,
        fallback_by_design=True,
    ),
    # Tasks 3.2/3.3: two new engine-owned codes, symmetric across both flows
    # from the start (unlike the legacy rows above, neither was ever
    # duplicated-and-drifted — these are brand new).
    Rule(
        code="SUPPORT_POINT_SAMPLING_FAILED",
        flows=("support", "slice"),
        stream="stderr",
        matchers=(EngineCode("SUPPORT_POINT_SAMPLING_FAILED"), Substring("SLA support point generator has failed."),),
        priority=90,
    ),
    Rule(
        code="SHRINKAGE_COMPENSATION_INVALID",
        flows=("support", "slice"),
        stream="stderr",
        # Shortened to the pre-line-break half of the source's split string
        # literal — see the matching comment on this code's engine_needles
        # in agent/error_codes.py.
        matchers=(EngineCode("SHRINKAGE_COMPENSATION_INVALID"), Substring("the object transform is"),),
        priority=100,
    ),
    # engine-error-code-table D6. Support flow only: in a slice the .sl1 is
    # already written when the support STL fails, and the engine reports the
    # failure and drops it (like a failed preview ZIP), so the slice stands.
    Rule(
        code="SUPPORT_MESH_EXPORT_FAILED",
        flows=("support",),
        stream="stderr",
        matchers=(EngineCode("SUPPORT_MESH_EXPORT_FAILED"), Substring("Failed to export support mesh"),),
        priority=110,
    ),
)


def find_code(flow: str, stderr: str, stdout: str = "") -> Optional[Rule]:
    """Return the rule for `flow` that the engine output hits, or None.

    Matchers are tried in tiers: every rule's EngineCode first, then every
    rule's Substring — a code the engine declared always wins over an English
    message, whatever the rule priorities (spec: 命中 EngineCode 時直接採用).
    Within a tier, the lowest `priority` number wins. Only rules listed for
    `flow` are consulted, so a code the engine declares for a failure this
    flow deliberately routes elsewhere (e.g. EXPOSURE_TIME_OUT_OF_RANGE in the
    support flow) is not picked up here either. Callers distinguish
    `fallback_by_design` rules via the returned `Rule.fallback_by_design`."""
    candidates = sorted((r for r in ENGINE_RULES if flow in r.flows), key=lambda r: r.priority)
    for tier in (EngineCode, Substring):
        for rule in candidates:
            if any(isinstance(m, tier) and m.matches(stderr, stdout) for m in rule.matchers):
                return rule
    return None
