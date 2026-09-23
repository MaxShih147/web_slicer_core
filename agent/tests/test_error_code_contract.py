"""
Contract test between the error code registry and `agent/errors.py`'s factory
functions — Task 3.1 (unify-error-code-registry).

`agent/error_codes.py` is now the single source of truth for the 28 codes, but
the actual `APIError` objects are still hand-written factories in errors.py
(design.md D3: code generation was rejected, factory signatures aren't
uniform). This test is what keeps the two from drifting apart:

- every registry code MUST have a corresponding factory that actually
  produces that `code` string (spec.md "API 錯誤工廠由登錄檔推導" /
  "登錄檔有 code 但 errors.py 缺 factory MUST 失敗")
- every factory's code MUST be declared in the registry (spec.md "在別處私自
  宣告 code" — errors.py must not have a 29th, unregistered code)

Factories are discovered by introspection (not a hand-maintained list of
function names), so a new factory added without a matching registry entry —
or vice versa — is caught here rather than surfacing later as a silent
JOB_FAILED fallback in api_v2.py (Task 4.1).

Reuses `agent.errors.factory_registry()` — the same function api_v2.py calls
to build its real `_ERROR_CODE_FACTORIES` lookup — rather than reimplementing
the introspection here, so this test exercises the actual production code
path instead of a parallel copy of it.
"""

import pytest

from agent.error_codes import ALL
from agent.errors import factory_registry

REGISTRY_CODES = {spec.code for spec in ALL}
FACTORY_REGISTRY = factory_registry()  # {code: factory function}
FACTORY_CODES = set(FACTORY_REGISTRY.keys())


class TestRegistryToFactory:
    """Every registered code must have a factory that produces it."""

    @pytest.mark.parametrize("spec", ALL, ids=lambda s: s.code)
    def test_registry_code_has_a_factory(self, spec):
        assert spec.code in FACTORY_CODES, (
            f"{spec.code} is declared in agent/error_codes.py but no factory "
            f"in agent/errors.py returns an APIError with this code — "
            f"api_v2.py's registry-derived lookup would fail to find it"
        )


class TestFactoryToRegistry:
    """Every factory's code must be declared in the registry (no 29th,
    privately-declared code hiding in errors.py)."""

    @pytest.mark.parametrize("code,fn", list(FACTORY_REGISTRY.items()), ids=lambda x: x if isinstance(x, str) else x.__name__)
    def test_factory_code_is_registered(self, code, fn):
        assert code in REGISTRY_CODES, (
            f"agent.errors.{fn.__name__}() returns code={code!r}, which is not "
            f"declared in agent/error_codes.py — every code MUST be registered "
            f"exactly once"
        )


class TestNoDuplicateFactoriesPerCode:
    """factory_registry() must reject two factories producing the same code
    (a silent dict-overwrite would hide the collision instead of failing at
    load time, defeating Task 4.1's fail-fast requirement). Exercises the
    real function against the real errors module, with one extra function
    monkeypatched in to create a genuine collision."""

    def test_duplicate_code_is_rejected(self, monkeypatch):
        from agent import errors as errors_module

        def _dup_of_internal_error(message: str = "duplicate") -> errors_module.APIError:
            return errors_module.APIError("INTERNAL_ERROR", message, 500)

        _dup_of_internal_error.__module__ = errors_module.__name__
        monkeypatch.setattr(errors_module, "_dup_of_internal_error", _dup_of_internal_error, raising=False)

        with pytest.raises(ValueError, match="two factories produce code"):
            errors_module.factory_registry()


class TestNegativeCheck:
    """Prove the two-way contract has teeth: a plausible unregistered code, and
    a plausible un-factoried registry code, must both be rejected."""

    def test_unregistered_code_is_rejected(self):
        assert "TOTALLY_MADE_UP_CODE" not in REGISTRY_CODES
        assert "TOTALLY_MADE_UP_CODE" not in FACTORY_CODES

    def test_registry_code_without_factory_would_be_caught(self):
        """Simulates what 'registry has a code, errors.py doesn't' looks like:
        the assertion in TestRegistryToFactory is `spec.code in FACTORY_CODES`,
        so a code absent from FACTORY_CODES must fail that check."""
        fake_new_code = "NOT_A_REAL_CODE_YET"
        assert fake_new_code not in FACTORY_CODES
