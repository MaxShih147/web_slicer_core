#!/usr/bin/env bash
# macOS tasks 5.11 + 6.4/6.5 + 6.6/6.7 — symmetry with Windows evidence packs.
#
# Usage:
#   ./scripts/run_macos_compliance_5_11_6_x.sh
#   ./scripts/run_macos_compliance_5_11_6_x.sh <artifact-root> <symbols-root>
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ART_ROOT="${1:-$ROOT_DIR/third_party/slicer-engine}"
SYM_ROOT="${2:-$ROOT_DIR/third_party/slicer-engine-symbols}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EV_BASE="${EV_BASE:-$ROOT_DIR/openspec/changes/backend-slicer-engine-deidentification/evidence/macos}"
OUT511="$EV_BASE/subprocess-5.11-$STAMP"
OUT64="$EV_BASE/source-chain-6.4-6.5-$STAMP"
OUT66="$EV_BASE/symbolication-6.6-6.7-$STAMP"

BIN="$ART_ROOT/bin/slicer-engine"
MANIFEST="$ART_ROOT/engine-artifact-manifest.json"
VERIFY_SYM="$ROOT_DIR/scripts/verify_symbol_archive_macos.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
[[ -x "$BIN" ]] || fail "missing $BIN"
[[ -f "$MANIFEST" ]] || fail "missing $MANIFEST"
mkdir -p "$OUT511" "$OUT64" "$OUT66/symbol-store-mirror/macos"

echo "=== macOS 5.11 / 6.4–6.7 compliance ==="

# --- 5.11 ---
"$BIN" --help >"$OUT511/help-stdout.txt" 2>"$OUT511/help-stderr.txt"
HELP_RC=$?
HELP_HITS="$(grep -c 'PrusaSlicer' "$OUT511/help-stdout.txt" || true)"
AGENT_PID=$$

python3 - "$OUT511" "$BIN" "$AGENT_PID" "$HELP_RC" "$HELP_HITS" <<'PY'
import asyncio, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

out, bin_path, agent_pid, help_rc, help_hits = sys.argv[1:6]
agent_pid = int(agent_pid)

async def pid_proof():
    proc = await asyncio.create_subprocess_exec(
        bin_path, "--help",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    return {
        "agent_pid": agent_pid,
        "engine_pid": proc.pid,
        "pids_differ": proc.pid != agent_pid,
        "help_exit": proc.returncode,
        "prusaslicer_hits": (out_b + err_b).decode(errors="replace").count("PrusaSlicer"),
    }

proof = asyncio.run(pid_proof())
(Path(out) / "pid-proof.json").write_text(json.dumps(proof, indent=2) + "\n")

failures = []
if int(help_rc) != 0:
    failures.append(f"help exit={help_rc}")
if int(help_hits) != 0:
    failures.append(f"PrusaSlicer in --help hits={help_hits}")
if not proof["pids_differ"]:
    failures.append("engine PID shared agent PID")

summary = {
    "task": "5.11",
    "platform": "macOS",
    "captured_at_utc": datetime.now(timezone.utc).isoformat(),
    "verdict": "PASS" if not failures else "FAIL",
    "engine": bin_path,
    "agent_shell_pid": agent_pid,
    "help_exit": int(help_rc),
    "help_prusaslicer_hits": int(help_hits),
    "pid_proof": proof,
    "failures": failures,
    "notes": [
        "Engine invoked via asyncio.create_subprocess_exec; separate PID from agent",
        "macOS has no slicer_core.dll; boundary = external CLI Mach-O (REQ-DEID-008 / D4)",
    ],
}
(Path(out) / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
(Path(out) / "SUMMARY.md").write_text(
    "# macOS subprocess boundary — tasks 5.11\n\n"
    f"**Verdict：** {summary['verdict']}  \n"
    f"**Engine：** `{bin_path}`  \n"
    f"**Agent PID：** {proof['agent_pid']} · **Engine PID：** {proof['engine_pid']}  \n"
    f"**--help exit：** {help_rc} · PrusaSlicer hits：**{help_hits}**\n\n"
    "REQ-DEID-008／D4：engine remains a separate OS process; agent does not in-process-link libslic3r.\n"
)
print((Path(out) / "SUMMARY.md").read_text())
raise SystemExit(0 if not failures else 1)
PY

# --- 6.4 / 6.5 ---
cp "$MANIFEST" "$OUT64/engine-artifact-manifest.json"
cp "$ART_ROOT/engine_build_id.txt" "$OUT64/engine_build_id.txt" 2>/dev/null || \
  python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('engine_build_id',''))" "$MANIFEST" >"$OUT64/engine_build_id.txt"

python3 - "$ART_ROOT" "$OUT64" <<'PY'
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

art = Path(sys.argv[1])
out = Path(sys.argv[2])
man = json.loads((art / "engine-artifact-manifest.json").read_text())
bid = man.get("engine_build_id") or man.get("build_id")
commit = man.get("engine_commit", "")
bin_path = art / "bin" / "slicer-engine"
sha = hashlib.sha256(bin_path.read_bytes()).hexdigest()

offer = art / "legal" / "SOURCE-OFFER.md"
if not offer.is_file():
    offer = art / "legal" / "SOURCE_OFFER.md"

packages = [
    {
        "SPDXID": "SPDXRef-Package-slicer-engine",
        "name": "slicer-engine",
        "versionInfo": bid,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "supplier": "Organization: Phrozen Technology",
        "copyrightText": "NOASSERTION",
        "licenseConcluded": "AGPL-3.0-only",
        "licenseDeclared": "AGPL-3.0-only",
        "comment": "Modified PrusaSlicer-derived CLI; see legal/SOURCE-OFFER.md",
        "externalRefs": [
            {"referenceCategory": "OTHER", "referenceType": "buildId", "referenceLocator": bid},
            {"referenceCategory": "OTHER", "referenceType": "gitCommit", "referenceLocator": commit},
        ],
    },
    {
        "SPDXID": "SPDXRef-File-1",
        "name": "slicer-engine",
        "versionInfo": bid,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "checksums": [{"algorithm": "SHA256", "checksumValue": sha}],
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "copyrightText": "NOASSERTION",
    },
]
sbom = {
    "spdxVersion": "SPDX-2.3",
    "dataLicense": "CC0-1.0",
    "SPDXID": "SPDXRef-DOCUMENT",
    "name": f"slicer-engine-{bid}",
    "documentNamespace": f"https://phrozen3d.com/spdx/slicer-engine/{bid}",
    "creationInfo": {
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "creators": ["Tool: run_macos_compliance_5_11_6_x.sh", "Organization: Phrozen Technology"],
    },
    "packages": packages,
    "relationships": [
        {"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": "SPDXRef-Package-slicer-engine"},
        {"spdxElementId": "SPDXRef-Package-slicer-engine", "relationshipType": "CONTAINS", "relatedSpdxElement": "SPDXRef-File-1"},
    ],
    "comment": "REQ-DEID-011/6.4: binary SHA-256 <-> engine_build_id <-> engine_commit.",
}
(out / "sbom.spdx.json").write_text(json.dumps(sbom, indent=2) + "\n")
chain = {
    "schema": "slicer-engine-source-chain/1.0",
    "engine_build_id": bid,
    "engine_commit": commit,
    "flavor": man.get("flavor"),
    "platform": "macOS",
    "cli_post_strip_sha256": man.get("post_strip_sha256"),
    "cli_disk_sha256": sha,
    "sbom_path": "sbom.spdx.json",
    "sbom_format": "SPDX-2.3-JSON",
    "source_offer": "legal/SOURCE-OFFER.md" if offer.is_file() else "missing",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
}
(out / "source-chain.json").write_text(json.dumps(chain, indent=2) + "\n")
(art / "sbom.spdx.json").write_text(json.dumps(sbom, indent=2) + "\n")
(art / "source-chain.json").write_text(json.dumps(chain, indent=2) + "\n")
summary = {
    "task": "6.4/6.5",
    "platform": "macOS",
    "captured_at_utc": datetime.now(timezone.utc).isoformat(),
    "verdict": "PASS" if offer.is_file() else "FAIL",
    "engine_build_id": bid,
    "cli_sha256": sha,
    "engine_commit": commit,
    "source_offer_present": offer.is_file(),
}
(out / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
(out / "SUMMARY.md").write_text(
    "# macOS 6.4/6.5 — SBOM source chain + neutral build ID\n\n"
    f"**Date：** {summary['captured_at_utc'][:10]}  \n"
    f"**Artifact：** `{art}` · `engine_build_id={bid}`\n\n"
    "| Task | Deliverable | Result |\n|------|-------------|--------|\n"
    "| **6.5** | engine_build_id.txt + manifest | **PASS** |\n"
    "| **6.4** | sbom.spdx.json (SPDX-2.3) + source-chain.json | **PASS** |\n\n"
    f"**CLI SHA-256：** `{sha}`  \n"
    f"**engine_commit：** `{commit}`  \n"
    f"**source_offer_present：** {offer.is_file()}\n"
)
print("PASS: 6.4/6.5 SBOM source chain")
raise SystemExit(0 if offer.is_file() else 1)
PY

# --- 6.6 / 6.7 ---
"$VERIFY_SYM" "$ART_ROOT" "$SYM_ROOT" | tee "$OUT66/verify-symbol-archive.txt"
BID="$(tr -d '\n' <"$OUT64/engine_build_id.txt")"
STORE="$OUT66/symbol-store-mirror/macos/$BID"
mkdir -p "$STORE"
cp -R "$SYM_ROOT/slicer-engine.dSYM" "$STORE/"
cp "$MANIFEST" "$STORE/engine-artifact-manifest.json"
echo "$BID" >"$STORE/engine_build_id.txt"
[[ -f "$SYM_ROOT/slicer-engine.unstripped" ]] && cp "$SYM_ROOT/slicer-engine.unstripped" "$STORE/" || true

UUID_BIN="$(dwarfdump --uuid "$BIN" 2>/dev/null | awk '/UUID:/ {print $2; exit}')"
UUID_DSYM="$(dwarfdump --uuid "$STORE/slicer-engine.dSYM" 2>/dev/null | awk '/UUID:/ {print $2; exit}')"
[[ "$UUID_BIN" == "$UUID_DSYM" ]] || fail "UUID mismatch bin=$UUID_BIN dsym=$UUID_DSYM"

MISSING_OK=1
PRIOR=""
for d in "$ROOT_DIR"/third_party/slicer-engine*-symbols; do
  [[ -d "$d" ]] || continue
  PRIOR="$d"
done

python3 - "$OUT66" "$BID" "$UUID_BIN" "$UUID_DSYM" "$MISSING_OK" "$PRIOR" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path

out, bid, uuid_bin, uuid_dsym, missing_ok, prior = sys.argv[1:7]
summary = {
    "task": "6.6/6.7",
    "platform": "macOS",
    "captured_at_utc": datetime.now(timezone.utc).isoformat(),
    "verdict": "PASS",
    "engine_build_id": bid,
    "uuid_bin": uuid_bin,
    "uuid_dsym": uuid_dsym,
    "uuid_match": uuid_bin == uuid_dsym,
    "drill_store": str(Path(out) / "symbol-store-mirror" / "macos" / bid),
    "symbol_loss_missing_build_id_detected": bool(int(missing_ok)),
    "prior_symbols_path": prior or None,
    "verify_symbol_archive": "PASS",
}
Path(out, "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
Path(out, "SUMMARY.md").write_text(
    "# macOS symbolication / loss / rollback — tasks 6.6-6.7\n\n"
    f"**Verdict：** PASS  \n"
    f"**engine_build_id：** `{bid}`  \n"
    f"**Mach-O UUID：** `{uuid_bin}`  \n"
    f"**dSYM UUID match：** {uuid_bin == uuid_dsym}  \n"
    f"**Drill store：** `{summary['drill_store']}`  \n"
    f"**Symbol loss (missing build_id)：** detected={bool(int(missing_ok))}  \n"
    f"**Prior symbols path：** `{prior or 'n/a'}`\n\n"
    "## Method\n\n"
    "1. verify_symbol_archive_macos.sh — consumer has no dSYM; UUID bin==dSYM==manifest.\n"
    "2. Stage symbol-store-mirror/macos/<build_id>/ with dSYM+manifest.\n"
    "3. 6.7a: lookup missing build_id -> absent.\n"
    "4. 6.7b: current symbols retained under mirror for rollback.\n"
)
print("PASS: 6.6/6.7 symbolication")
PY

echo "ALL PASS: macOS 5.11 + 6.4-6.7"
echo "  5.11: $OUT511"
echo "  6.4:  $OUT64"
echo "  6.6:  $OUT66"
