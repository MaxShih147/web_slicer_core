"""
engine-error-code-table Task 3.4: the engine's own code list and the agent's
registry must agree, code for code, in both directions.

The engine side is read from the fork source (the X-macro in
EngineErrorCodes.hpp) rather than from a built binary, so this runs without an
engine build. It checks the fork as checked out: until the submodule pointer
moves (Section 7), that is whatever commit the working tree is on.
"""
import re
from pathlib import Path

import pytest

from agent.error_codes import ALL

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENGINE_CODES_HPP = (
    _REPO_ROOT / "third_party" / "prusaslicer_fork" / "src" / "libslic3r" / "EngineErrorCodes.hpp"
)


def _engine_code_list() -> set:
    if not _ENGINE_CODES_HPP.exists():
        pytest.skip(f"fork submodule source not checked out: {_ENGINE_CODES_HPP}")
    src = _ENGINE_CODES_HPP.read_text(encoding="utf-8")
    start = src.index("#define PHZ_ENGINE_ERROR_CODES(X)")
    end = src.index("// clang-format on", start)
    return set(re.findall(r"X\(([A-Z_]+),", src[start:end]))


def _registry_engine_codes() -> set:
    return {spec.code for spec in ALL if spec.owner == "engine"}


def test_every_engine_code_is_in_the_registry():
    """Spec: 引擎新增代號但 Python 未跟進 → 契約測試 MUST 失敗並指出該代號."""
    missing = _engine_code_list() - _registry_engine_codes()
    assert not missing, (
        f"the engine declares codes agent/error_codes.py has no owner=engine entry for: "
        f"{sorted(missing)}"
    )


def test_every_registry_engine_code_is_declared_by_the_engine():
    """Spec: Python 標為 engine 但引擎沒有 → 契約測試 MUST 失敗."""
    missing = _registry_engine_codes() - _engine_code_list()
    assert not missing, (
        f"agent/error_codes.py marks these owner=engine but EngineErrorCodes.hpp "
        f"does not declare them: {sorted(missing)}"
    )
