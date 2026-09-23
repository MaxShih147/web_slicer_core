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
`validate()` failures return process exit 0 in several paths (`return 1`
inside `bool` functions), so exit code is not a reliable classification
signal. The one place exit code still matters (`output_file_exists` aside)
is call-site-local legacy handling — see
`slicing_classifier._LEGACY_EXIT0_ONLY_CODES`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Substring:
    """Matches when `text` is a substring of the engine output. The only
    matcher type today; `matchers` is a list so a future matcher type (e.g. a
    structured `EngineCode` matcher once the engine outputs codes directly,
    see the deferred `engine-error-code-table` change) can be inserted ahead
    of it without changing any rule's other fields."""

    text: str

    def matches(self, haystack: str) -> bool:
        return self.text in haystack


@dataclass(frozen=True)
class Rule:
    code: str
    flows: Tuple[str, ...]  # "support" and/or "slice"
    stream: str  # "stdout" | "stderr" | "both" — informational; every rule
    # today is "stderr", and both classifiers already scan only stderr for
    # these messages, so this field is not yet consulted by find_code().
    matchers: Tuple[Substring, ...]
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
        matchers=(Substring("Cannot proceed without support points"),),
        priority=10,
    ),
    Rule(
        code="SUPPORT_ELEVATION_TOO_LOW",
        flows=("support", "slice"),
        stream="stderr",
        matchers=(Substring("Elevation is too low for object"),),
        priority=20,
    ),
    Rule(
        code="SUPPORT_PAD_GAP_CONFLICT",
        flows=("support", "slice"),
        stream="stderr",
        matchers=(Substring("The endings of the support pillars"),),
        priority=30,
    ),
    Rule(
        code="SUPPORT_HEAD_PENETRATION_INVALID",
        flows=("support", "slice"),
        stream="stderr",
        matchers=(Substring("Invalid Head penetration"),),
        priority=40,
    ),
    Rule(
        code="SUPPORT_HEAD_TOO_WIDE",
        flows=("support", "slice"),
        stream="stderr",
        matchers=(Substring("Invalid pinhead diameter"),),
        priority=50,
    ),
    Rule(
        code="PAD_CONFIG_INVALID",
        # Task 2.2: previously slice-only. The support flow used to have no
        # code for this message and fell all the way to SUPPORT_GENERATION_FAILED.
        flows=("slice", "support"),
        stream="stderr",
        matchers=(Substring("Pad brim size is too small"),),
        priority=60,
    ),
    Rule(
        code="EXPOSURE_TIME_OUT_OF_RANGE",
        flows=("slice",),
        stream="stderr",
        # Covers both "Exposition time..." (F-12) and "Initial exposition
        # time..." (F-13).
        matchers=(Substring("xposition time is out of printer profile bounds"),),
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
        matchers=(Substring("SLA support point generator has failed."),),
        priority=90,
    ),
    Rule(
        code="SHRINKAGE_COMPENSATION_INVALID",
        flows=("support", "slice"),
        stream="stderr",
        # Shortened to the pre-line-break half of the source's split string
        # literal — see the matching comment on this code's engine_needles
        # in agent/error_codes.py.
        matchers=(Substring("the object transform is"),),
        priority=100,
    ),
)


def find_code(flow: str, text: str) -> Optional[Rule]:
    """Return the highest-priority (lowest `priority` number) rule for `flow`
    whose matcher hits `text`, or None. Callers distinguish
    `fallback_by_design` rules from specific-code rules via the returned
    `Rule.fallback_by_design` flag."""
    candidates = sorted((r for r in ENGINE_RULES if flow in r.flows), key=lambda r: r.priority)
    for rule in candidates:
        if any(m.matches(text) for m in rule.matchers):
            return rule
    return None
