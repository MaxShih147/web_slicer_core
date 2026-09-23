"""
Contract test for the error code registry — Task 2.1 (unify-error-code-registry).

`agent/error_codes.py` is the single source of truth for the backend's error
codes (originally 28, see openspec/changes/unify-error-code-registry/design.md;
30 after merge-engine-result-classifiers Task 3.1 added
SUPPORT_POINT_SAMPLING_FAILED and SHRINKAGE_COMPENSATION_INVALID, both
owner="engine"; 31 after add-support-param-validation Task 4 added
CONFIG_VALIDATION_ERROR, owner="python"). This test pins the shape of that
registry: every code declared exactly once, all required fields populated,
`owner` restricted to the two known values with the exact split those changes
together produce (15 engine / 16 python), and every `owner="engine"` record
carrying at least
one engine_needles string (required by ErrorCodeSpec.__post_init__ and by the
error-code-registry spec's "owner 為 engine 但 engine_needles 為空 MUST 拋錯"
scenario).

The owner-split expectation (15/15) is an independently-sourced literal, not
derived from ALL itself — it comes from manually classifying each code against
agent/sla_operations.py, agent/api_v2.py, agent/support_classifier.py and
agent/slicing_classifier.py (see unify-error-code-registry/design.md's
2026-09-17 correction note for the methodology). A tautological
`Counter(...) == Counter(...)` computed from ALL would pass even if every code
were mis-tagged; this literal catches that. Update EXPECTED_TOTAL /
EXPECTED_OWNER_COUNTS deliberately whenever a future change adds codes — that
is expected maintenance, not a red flag.
"""

import collections

import pytest

from agent.error_codes import ALL, ErrorCodeSpec

EXPECTED_TOTAL = 31
EXPECTED_OWNER_COUNTS = collections.Counter({"engine": 15, "python": 16})


class TestRegistryShape:
    def test_total_count(self):
        assert len(ALL) == EXPECTED_TOTAL

    def test_codes_unique(self):
        codes = [spec.code for spec in ALL]
        duplicates = sorted({code for code in codes if codes.count(code) > 1})
        assert duplicates == [], f"duplicate error codes: {duplicates}"

    def test_all_entries_are_error_code_spec(self):
        assert all(isinstance(spec, ErrorCodeSpec) for spec in ALL)


class TestRequiredFields:
    @pytest.mark.parametrize("spec", ALL, ids=lambda s: s.code)
    def test_code_is_nonempty_string(self, spec):
        assert isinstance(spec.code, str) and spec.code != ""

    @pytest.mark.parametrize("spec", ALL, ids=lambda s: s.code)
    def test_http_status_is_valid(self, spec):
        assert isinstance(spec.http_status, int) and 100 <= spec.http_status <= 599

    @pytest.mark.parametrize("spec", ALL, ids=lambda s: s.code)
    def test_retryable_is_bool(self, spec):
        assert isinstance(spec.retryable, bool)

    @pytest.mark.parametrize("spec", ALL, ids=lambda s: s.code)
    def test_note_is_nonempty_string(self, spec):
        assert isinstance(spec.note, str) and spec.note != ""

    @pytest.mark.parametrize("spec", ALL, ids=lambda s: s.code)
    def test_engine_needles_is_tuple_of_strings(self, spec):
        assert isinstance(spec.engine_needles, tuple)
        assert all(isinstance(needle, str) and needle != "" for needle in spec.engine_needles)


class TestOwnerClassification:
    def test_owner_has_only_two_values(self):
        assert set(spec.owner for spec in ALL) == {"engine", "python"}

    def test_owner_distribution(self):
        actual = collections.Counter(spec.owner for spec in ALL)
        assert actual == EXPECTED_OWNER_COUNTS

    @pytest.mark.parametrize(
        "spec", [s for s in ALL if s.owner == "engine"], ids=lambda s: s.code
    )
    def test_engine_owner_has_needles(self, spec):
        assert len(spec.engine_needles) > 0, (
            f"{spec.code}: owner='engine' but engine_needles is empty — "
            f"this should be unreachable since ErrorCodeSpec.__post_init__ "
            f"raises on construction, so seeing this means that guard broke"
        )


class TestNegativeCheck:
    """Prove the owner-count check has teeth: a plausible wrong split
    (the pre-correction 14/14 design.md once claimed) must NOT match."""

    def test_wrong_split_would_be_rejected(self):
        wrong = collections.Counter({"engine": 14, "python": 14})
        actual = collections.Counter(spec.owner for spec in ALL)
        assert actual != wrong
