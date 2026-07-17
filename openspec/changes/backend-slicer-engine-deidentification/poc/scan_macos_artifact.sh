#!/usr/bin/env bash
# Scanner prototype for macOS de-id PoC (nm + .ips token scan).
# Usage:
#   ./scan_macos_artifact.sh <binary> [ips...]
# Exit 0 = L1 identity OK and no blocking findings per PoC rules;
# Exit 1 = FAIL (see report).
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <binary> [ips...]" >&2
  exit 2
fi

BIN="$1"; shift || true
python3 - "$BIN" "$@" <<'PY'
import pathlib, re, sys, subprocess, json

bin_path = pathlib.Path(sys.argv[1])
ips_paths = [pathlib.Path(p) for p in sys.argv[2:]]

def run(cmd):
    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)

def nm_counts(path, flags):
    try:
        out = run(["nm"] + flags + [str(path)])
    except Exception:
        return -1
    return sum(1 for line in out.splitlines() if re.search(r"slic3r|prusa", line, re.I))

report = {
    "binary": str(bin_path),
    "sha256": run(["shasum", "-a", "256", str(bin_path)]).split()[0],
    "nm_global_brand": nm_counts(bin_path, ["-gU"]),
    "nm_local_brand": nm_counts(bin_path, ["-U"]),
    "ips": [],
    "verdict": "PASS",
    "notes": [],
}

# codesign identity
try:
    cs = subprocess.check_output(["codesign", "-dv", "--verbose=2", str(bin_path)], text=True, stderr=subprocess.STDOUT)
except Exception as e:
    cs = str(e)
m = re.search(r"^Identifier=(.*)$", cs, re.M)
ident = m.group(1).strip() if m else ""
report["codesign_identifier"] = ident
if "prusa" in ident.lower() or "slic3r" in ident.lower():
    report["verdict"] = "FAIL"
    report["notes"].append("codesign Identifier still branded")

tokens = [
    "prusaslicer", "prusa-slicer", "prusa3d", "slic3r", "libslic3r",
    "com.prusa3d.slic3r", "slic3r_main", "slic3r_tbb", "prusaslicer_build",
]

for ips in ips_paths:
    text = ips.read_text(errors="replace")
    tf = text.casefold()
    entry = {"file": str(ips), "tokens": {}, "procName": None, "codeSigningID": None, "threads": []}
    for tok in tokens:
        entry["tokens"][tok] = tf.count(tok)
    pm = re.search(r'"procName"\s*:\s*"([^"]+)"', text)
    csid = re.search(r'"codeSigningID"\s*:\s*"([^"]+)"', text)
    entry["procName"] = pm.group(1) if pm else None
    entry["codeSigningID"] = csid.group(1) if csid else None
    entry["threads"] = re.findall(r'"name"\s*:\s*"(slic3r_[^"]*|slicer-[^"]*)"', text)[:8]
    entry["Slic3r_namespace"] = text.count("Slic3r::")
    # L1 checks
    if entry["procName"] and re.search(r"prusa|slic3r", entry["procName"], re.I):
        report["verdict"] = "FAIL"
        report["notes"].append(f"{ips.name}: branded procName")
    if entry["tokens"]["prusaslicer"] > 0 or entry["tokens"]["prusa-slicer"] > 0:
        report["verdict"] = "FAIL"
        report["notes"].append(f"{ips.name}: prusaslicer path/name tokens")
    if entry["tokens"]["slic3r_main"] > 0:
        report["verdict"] = "FAIL"
        report["notes"].append(f"{ips.name}: slic3r_main thread still present")
    # L2 stack readability
    if entry["Slic3r_namespace"] > 0:
        report["verdict"] = "FAIL"
        report["notes"].append(f"{ips.name}: readable Slic3r:: stack symbols remain ({entry['Slic3r_namespace']})")
    report["ips"].append(entry)

# Static gate for PoC close: after visibility+strip, global brand should be near-zero.
# Soft note if only static provided.
if report["nm_global_brand"] > 50 and not ips_paths:
    report["notes"].append("high nm global brand hits; expect visibility+strip before close")

print(json.dumps(report, indent=2, ensure_ascii=False))
sys.exit(0 if report["verdict"] == "PASS" else 1)
PY
