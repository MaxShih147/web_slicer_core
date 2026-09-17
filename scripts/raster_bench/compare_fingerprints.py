#!/usr/bin/env python
"""Compare the fingerprints of two raster benchmark runs.

Spec: ``raster-performance-baseline``, "指紋比對規則".

  python scripts/raster_bench/compare_fingerprints.py BASE_RUN_DIR TEST_RUN_DIR [--allow-cross-platform]

Each run directory is one produced by run_bench.py and holds ``layers.sha256``,
``preview.sha256`` and ``meta.json``. Both fingerprint files are compared entry
by entry. For each file the report gives both entry counts, the first differing
entry in name order (the zero-padded names make that layer order) and the total
number of differing entries. An entry present on only one side is a difference,
so differing entry counts are always a mismatch.

Runs from different platforms are refused: pixel output across compilers and
math libraries is not expected to be byte-identical, so such a comparison can
never count as acceptance. --allow-cross-platform prints the report anyway, and
still exits 3 whatever it finds.

Exit code: 0 = all entries match, 1 = any difference, 2 = usage error or
unreadable input, 3 = platform labels differ (refused, or reported with
--allow-cross-platform).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR))

from fingerprint import FingerprintError, read_fingerprint  # noqa: E402

FINGERPRINT_FILES = ("layers.sha256", "preview.sha256")
EXIT_MATCH, EXIT_MISMATCH, EXIT_USAGE, EXIT_CROSS_PLATFORM = 0, 1, 2, 3


def compare_entries(base: list[tuple[str, str]], test: list[tuple[str, str]]) -> dict:
    base_map, test_map = dict(base), dict(test)
    differing = sorted(
        name for name in base_map.keys() | test_map.keys()
        if base_map.get(name) != test_map.get(name)
    )
    first = None
    if differing:
        name = differing[0]
        first = {"name": name, "base": base_map.get(name), "test": test_map.get(name)}
    return {
        "base_count": len(base),
        "test_count": len(test),
        "differing_count": len(differing),
        "first_difference": first,
    }


def load_run(run_dir: Path) -> tuple[dict, dict[str, list[tuple[str, str]]]]:
    meta_path = run_dir / "meta.json"
    if not meta_path.is_file():
        raise FingerprintError(f"missing {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    fingerprints = {}
    for name in FINGERPRINT_FILES:
        path = run_dir / name
        if not path.is_file():
            raise FingerprintError(f"missing {path}")
        fingerprints[name] = read_fingerprint(path)
    return meta, fingerprints


def _describe(side: str | None) -> str:
    return side if side is not None else "(absent)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("base", help="baseline run directory")
    parser.add_argument("test", help="run directory under test")
    parser.add_argument("--allow-cross-platform", action="store_true",
                        help="report differing platforms instead of refusing; never counts as a pass")
    args = parser.parse_args(argv)

    try:
        base_meta, base_fp = load_run(Path(args.base))
        test_meta, test_fp = load_run(Path(args.test))
    except (OSError, ValueError, FingerprintError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(f"base: {base_meta.get('run_id')}")
    print(f"test: {test_meta.get('run_id')}")

    cross_platform = base_meta.get("platform") != test_meta.get("platform")
    if cross_platform:
        message = f"platform labels differ: base {base_meta.get('platform')!r}, test {test_meta.get('platform')!r}"
        if not args.allow_cross_platform:
            print(f"error: {message}; refusing to compare (use --allow-cross-platform for a report)",
                  file=sys.stderr)
            return EXIT_CROSS_PLATFORM
        print(f"warning: {message}; report only, NOT valid for acceptance")

    for key in ("case", "params_sha256"):
        if base_meta.get(key) != test_meta.get(key):
            print(f"warning: {key} differs: base {base_meta.get(key)!r}, test {test_meta.get(key)!r}")

    mismatch = False
    for name in FINGERPRINT_FILES:
        result = compare_entries(base_fp[name], test_fp[name])
        status = "match" if result["differing_count"] == 0 else "MISMATCH"
        print(f"{name}: {status}")
        print(f"  entries: base {result['base_count']}, test {result['test_count']}")
        if result["differing_count"]:
            mismatch = True
            first = result["first_difference"]
            print(f"  first difference: {first['name']} "
                  f"(base {_describe(first['base'])}, test {_describe(first['test'])})")
            print(f"  differing entries: {result['differing_count']}")

    if cross_platform:
        print("result: cross-platform report (not an acceptance result)")
        return EXIT_CROSS_PLATFORM
    print(f"result: {'MISMATCH' if mismatch else 'MATCH'}")
    return EXIT_MISMATCH if mismatch else EXIT_MATCH


if __name__ == "__main__":
    sys.exit(main())
