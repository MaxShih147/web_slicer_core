#!/usr/bin/env bash
# Formal macOS engine artifact gate — tasks 5.4 / 5.7 (and qa checks for 5.6).
#
# Usage:
#   ./scripts/scan_slicer_engine_macos.sh [artifact-root]
#   SLICER_ENGINE_EXPECT_FLAVOR=consumer|qa ./scripts/scan_slicer_engine_macos.sh …
#
# Exit 0 = PASS (fail closed otherwise).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ART_ROOT="${1:-${SLICER_ENGINE_ARTIFACT_DIR:-$ROOT_DIR/third_party/slicer-engine}}"
EXPECT_FLAVOR="${SLICER_ENGINE_EXPECT_FLAVOR:-consumer}"
BIN="$ART_ROOT/bin/slicer-engine"
MANIFEST="$ART_ROOT/engine-artifact-manifest.json"
REPORT_DIR="${SLICER_ENGINE_SCAN_REPORT_DIR:-$ART_ROOT}"
REPORT_JSON="$REPORT_DIR/scan-report.json"

mkdir -p "$REPORT_DIR"

python3 - "$ART_ROOT" "$BIN" "$MANIFEST" "$EXPECT_FLAVOR" "$REPORT_JSON" <<'PY'
import json, os, re, subprocess, sys
from pathlib import Path

art_root = Path(sys.argv[1])
bin_path = Path(sys.argv[2])
manifest_path = Path(sys.argv[3])
expect_flavor = sys.argv[4]
report_path = Path(sys.argv[5])
notes = []
failures = []

def fail(msg: str) -> None:
    failures.append(msg)

def run(cmd, check=True):
    return subprocess.run(cmd, text=True, capture_output=True, check=check)

report = {
    "schema": "slicer-engine-macos-scan/1.0",
    "artifact_root": str(art_root),
    "expect_flavor": expect_flavor,
    "verdict": "PASS",
    "checks": {},
    "notes": notes,
    "failures": failures,
}

# --- layout ---
if not bin_path.is_file() or not os.access(bin_path, os.X_OK):
    fail(f"missing executable: {bin_path}")
if not manifest_path.is_file():
    fail(f"missing manifest: {manifest_path}")

# No dSYM / PDB / unstripped in consumer tree
leaks = []
for p in art_root.rglob("*"):
    name = p.name.lower()
    if name.endswith(".dsym") or name.endswith(".pdb") or name.endswith(".unstripped"):
        leaks.append(str(p.relative_to(art_root)))
    if p.is_dir() and name.endswith(".dsym"):
        leaks.append(str(p.relative_to(art_root)))
report["checks"]["debug_leaks"] = leaks
if leaks:
    fail(f"debug artifacts in consumer tree: {leaks}")

# Brand path tokens (filename/path only; slicer-* is allowed)
brand_path_re = re.compile(r"(prusa|slic3r)", re.I)
bad_paths = []
for p in art_root.rglob("*"):
    rel = str(p.relative_to(art_root))
    # avoid false positive on nothing — 'slicer' does not match slic3r
    if brand_path_re.search(rel):
        bad_paths.append(rel)
report["checks"]["brand_paths"] = bad_paths
if bad_paths:
    fail(f"brand tokens in artifact paths: {bad_paths}")

# --- manifest ---
manifest = {}
if manifest_path.is_file():
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report["checks"]["manifest_flavor"] = manifest.get("flavor")
    report["checks"]["engine_build_id"] = manifest.get("engine_build_id")
    if manifest.get("flavor") != expect_flavor:
        fail(f"manifest flavor={manifest.get('flavor')!r} != expect {expect_flavor!r}")
    post = manifest.get("post_strip_sha256")
    if bin_path.is_file() and post:
        actual = run(["shasum", "-a", "256", str(bin_path)]).stdout.split()[0]
        report["checks"]["post_strip_sha256_manifest"] = post
        report["checks"]["post_strip_sha256_actual"] = actual
        if actual != post:
            fail("disk sha256 != manifest post_strip_sha256")
    if expect_flavor == "qa":
        qd = manifest.get("qa_delta")
        if not isinstance(qd, dict):
            fail("qa flavor missing qa_delta object")
        else:
            report["checks"]["qa_delta"] = qd
            if qd.get("harness_compile_flag") != "BUNDLE_QA_CRASH_HARNESS":
                fail("qa_delta.harness_compile_flag must be BUNDLE_QA_CRASH_HARNESS")
            if not qd.get("consumer_equivalent_build_id"):
                notes.append("qa_delta.consumer_equivalent_build_id empty (set when pairing builds)")
    else:
        if manifest.get("qa_delta") not in (None, {}):
            # allow null only
            if manifest.get("qa_delta") is not None:
                fail("consumer manifest must have qa_delta=null")

# --- codesign ---
if bin_path.is_file():
    cs = run(["codesign", "-dv", "--verbose=2", str(bin_path)], check=False)
    cs_text = (cs.stdout or "") + (cs.stderr or "")
    m = re.search(r"^Identifier=(.*)$", cs_text, re.M)
    ident = (m.group(1).strip() if m else "")
    report["checks"]["codesign_identifier"] = ident
    if ident != "slicer-engine":
        fail(f"codesign Identifier={ident!r} (want slicer-engine)")
    if re.search(r"prusa|slic3r", ident, re.I):
        fail("codesign Identifier branded")

# --- nm brand (5.4) ---
def nm_brand(flags):
    if not bin_path.is_file():
        return -1
    r = run(["nm"] + flags + [str(bin_path)], check=False)
    if r.returncode not in (0, 1):  # nm may return 1 on empty
        out = r.stdout or ""
    else:
        out = r.stdout or ""
    return sum(1 for line in out.splitlines() if re.search(r"slic3r|prusa", line, re.I))

g = nm_brand(["-gU"])
l = nm_brand(["-U"])
report["checks"]["nm_brand_global"] = g
report["checks"]["nm_brand_local"] = l
if g != 0:
    fail(f"nm -gU brand hits={g} (want 0)")
if l != 0:
    fail(f"nm -U brand hits={l} (want 0)")

# --- harness inspection (5.7 for consumer; 5.6 expects present for qa) ---
HARNESS_MARKERS = [
    "bundle_qa_crash",
    "BUNDLE_QA_CRASH",
    "bundle_force_prusa",
    "BUNDLE_FORCE_PRUSA",
    "bundle_force_stack_overflow",
    "maybe_force_crash",
    "ForcedException",
    "force_stack_overflow",
    "force_segfault",
]
harness_hits = []
if bin_path.is_file():
    strings = run(["strings", str(bin_path)], check=False).stdout or ""
    nm_out = run(["nm", str(bin_path)], check=False).stdout or ""
    blob = strings + "\n" + nm_out
    for tok in HARNESS_MARKERS:
        if tok in blob:
            harness_hits.append(tok)
report["checks"]["harness_markers"] = harness_hits
if expect_flavor == "consumer":
    if harness_hits:
        fail(f"consumer binary contains harness markers: {harness_hits}")
else:
    # qa should contain compile-time harness evidence
    if not any(t in harness_hits for t in ("bundle_qa_crash", "BUNDLE_QA_CRASH", "maybe_force_crash")):
        fail("qa binary missing expected harness markers (was it built with BUNDLE_QA_CRASH_HARNESS=ON?)")

report["verdict"] = "FAIL" if failures else "PASS"
report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
sys.exit(0 if report["verdict"] == "PASS" else 1)
PY
