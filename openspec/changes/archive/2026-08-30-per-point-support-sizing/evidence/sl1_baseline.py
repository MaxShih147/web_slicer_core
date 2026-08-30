#!/usr/bin/env python
"""`.sl1` 逐層 SHA-256 回歸基準 —— openspec/changes/per-point-support-sizing 任務 1.3 / 1.4。

為什麼不直接雜湊整包 `.sl1`：zip 內含 mtime，且 `config.ini` 有 `fileCreationTimestamp`，
兩者每次執行都不同。故改為逐層檔（`model#####.rle` / `.png`）各取 SHA-256，
層檔名以 `agent.prz_encoder.sl1_layer_names()` 判定（與後端同一真值來源），
再另外記錄濾掉時間戳後的 `config.ini` / `prusaslicer.ini` 雜湊與統計數據。

模型與參數沿用 fork 內既有的迴歸資產（`tests/data/sla_thin/cfg_base.ini`），
兩組情境：A 自撐（關支撐與底筏）、B 需支撐（cfg_base 原樣，支撐與底筏皆開）。

用法：
  產生基準： python sl1_baseline.py --out <evidence>/baseline-<UTCts>
  比對基準： python sl1_baseline.py --compare <evidence>/baseline-<UTCts>/baseline.json

離開碼：0 = 全部一致 / 產生成功，1 = 有差異或執行失敗。
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
from agent.prz_encoder import sl1_layer_names  # noqa: E402

FORK = REPO_ROOT / "third_party" / "prusaslicer_fork"
CFG_BASE = FORK / "tests" / "data" / "sla_thin" / "cfg_base.ini"
DEFAULT_ENGINE = (REPO_ROOT / "third_party" / "prusaslicer_build" / "src"
                  / "Release" / "slicer-engine.exe")

# `.sl1` 內 `config.ini` 每次執行都會變動的欄位，比對前先剔除。
VOLATILE_SL1_KEYS = {"fileCreationTimestamp"}

RUNS = [
    {
        "name": "A-selfsupport-cube",
        "kind": "自撐",
        "model": "third_party/prusaslicer_fork/tests/data/20mm_cube.obj",
        # 實心立方體平貼底板：關支撐、關底筏，即為自撐情境。
        "overrides": {"supports_enable": "0", "pad_enable": "0"},
    },
    {
        "name": "B-supported-cyl25x30",
        "kind": "需支撐",
        "model": "third_party/prusaslicer_fork/tests/data/sla_thin/reg_cyl25x30.stl",
        # cfg_base 原樣：supports_enable = 1、pad_enable = 1、elevation 5.0。
        "overrides": {},
    },
]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# 引擎的實作程式碼在 `slicer_core.dll`，不在 `slicer-engine.exe`。
# 兩者必須一起比對，否則會出現「exe 雜湊相同、dll 已重建」的靜默誤判：
# 實測 exe 可在 dll 換掉之後仍維持同一個雜湊（連結器未重連），
# 此時只看 exe 會回報「引擎未變」而讓回歸比對失去意義。
ENGINE_BINARIES = ("sha256", "core_dll_sha256")


def sha256_file_optional(path):
    """檔案不存在時回傳 None，而非拋例外。

    dll 只在本 fork 的打包配置下存在；他處建置的引擎可能沒有這個檔案，
    缺檔不應讓整個基準工具無法執行。
    """
    path = Path(path)
    if not path.is_file():
        return None
    return sha256_file(path)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def build_ini(dest, overrides):
    """由 cfg_base.ini 套用 overrides 產生本次執行的 ini（逐行取代，不改順序）。"""
    lines = CFG_BASE.read_text(encoding="utf-8").splitlines()
    seen = set()
    out = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in overrides:
                line = "{} = {}".format(key, overrides[key])
                seen.add(key)
        out.append(line)
    for key, value in overrides.items():
        if key not in seen:
            out.append("{} = {}".format(key, value))
    dest.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    return dest


def filtered_ini_digest(raw):
    """濾掉 VOLATILE_SL1_KEYS 後的內容雜湊。"""
    kept = []
    for line in raw.decode("utf-8", "replace").splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in VOLATILE_SL1_KEYS:
            continue
        kept.append(line)
    return sha256_bytes("\n".join(kept).encode("utf-8"))


def parse_sl1_stats(zf):
    """由 .sl1 內 config.ini 取統計數據（欄位對應 agent/jobs.py::parse_sl1_metadata）。"""
    stats = {"estimated_print_time": None, "resin_volume_ml": None}
    if "config.ini" not in zf.namelist():
        return stats
    for raw_line in zf.read("config.ini").decode("utf-8", "ignore").splitlines():
        if "=" not in raw_line:
            continue
        key, value = (p.strip() for p in raw_line.split("=", 1))
        if key == "printTime":
            stats["estimated_print_time"] = float(value)
        elif key == "usedMaterial":
            stats["resin_volume_ml"] = float(value)
    return stats


def digest_sl1(sl1_path):
    with zipfile.ZipFile(sl1_path, "r") as zf:
        names = zf.namelist()
        layer_names = sl1_layer_names(names)
        layers = [{"name": n, "sha256": sha256_bytes(zf.read(n))} for n in layer_names]
        rollup = "\n".join(l["name"] + " " + l["sha256"] for l in layers)
        result = {
            "layer_count": len(layer_names),
            "layers": layers,
            "layers_rollup_sha256": sha256_bytes(rollup.encode("ascii")),
            "config_ini_sha256": (filtered_ini_digest(zf.read("config.ini"))
                                  if "config.ini" in names else None),
            "prusaslicer_ini_sha256": (sha256_bytes(zf.read("prusaslicer.ini"))
                                       if "prusaslicer.ini" in names else None),
            "non_layer_entries": sorted(n for n in names if n not in set(layer_names)),
        }
        result.update(parse_sl1_stats(zf))
    return result


def slice_once(engine, run, workdir):
    model = REPO_ROOT / run["model"]
    if not model.is_file():
        raise SystemExit("找不到模型: {}".format(model))
    ini = build_ini(workdir / (run["name"] + ".ini"), run["overrides"])
    out_sl1 = workdir / "model.sl1"
    cmd = [
        str(engine), "--export-sla",
        "--output", str(out_sl1),
        "--center", "60,34",
        "--load", str(ini),
        str(model),
    ]
    env = dict(os.environ, LC_ALL="C", LANG="C", LANGUAGE="C")
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                          env=env, cwd=str(REPO_ROOT))
    if not out_sl1.is_file():
        sys.stderr.write((proc.stdout or "")[-4000:] + "\n")
        sys.stderr.write((proc.stderr or "")[-4000:] + "\n")
        raise SystemExit("{}: 切片未產生 .sl1（returncode={}）".format(
            run["name"], proc.returncode))
    entry = {
        "name": run["name"],
        "kind": run["kind"],
        "model": run["model"],
        "model_sha256": sha256_file(model),
        "ini_sha256": sha256_file(ini),
        "overrides": run["overrides"],
        "returncode": proc.returncode,
        "sl1": digest_sl1(out_sl1),
    }
    return entry, ini, proc


def git_head(path):
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def collect(engine, keep_dir=None):
    runs = []
    tmp = Path(tempfile.mkdtemp(prefix="sl1_baseline_"))
    try:
        for run in RUNS:
            wd = tmp / run["name"]
            wd.mkdir(parents=True)
            entry, ini, _ = slice_once(engine, run, wd)
            runs.append(entry)
            if keep_dir:
                dst = Path(keep_dir) / "runs"
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(ini), str(dst / ini.name))
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    engine_path = str(engine)
    if engine_path.startswith(str(REPO_ROOT)):
        engine_path = str(engine.relative_to(REPO_ROOT)).replace("\\", "/")
    return {
        "engine": {
            "path": engine_path,
            "sha256": sha256_file(engine),
            "core_dll_sha256": sha256_file_optional(engine.parent / "slicer_core.dll"),
        },
        "fork_head": git_head(FORK),
        "cfg_base_sha256": sha256_file(CFG_BASE),
        "runs": runs,
    }


def compare(baseline, current):
    ok = True
    for base_run in baseline["runs"]:
        cur = next((r for r in current["runs"] if r["name"] == base_run["name"]), None)
        if cur is None:
            print("  x FAIL {}: 本次未產生".format(base_run["name"]))
            ok = False
            continue
        b, c = base_run["sl1"], cur["sl1"]
        diffs = []
        if b["layer_count"] != c["layer_count"]:
            diffs.append("layer_count {}->{}".format(b["layer_count"], c["layer_count"]))
        if b["layers_rollup_sha256"] != c["layers_rollup_sha256"]:
            bad = [bl["name"] for bl, cl in zip(b["layers"], c["layers"])
                   if bl["sha256"] != cl["sha256"]]
            diffs.append("逐層雜湊不同 {}/{} 層（首個 {}）".format(
                len(bad), b["layer_count"], bad[:3]))
        for key in ("resin_volume_ml", "estimated_print_time", "config_ini_sha256",
                    "prusaslicer_ini_sha256"):
            if b[key] != c[key]:
                diffs.append("{} {}->{}".format(key, b[key], c[key]))
        if diffs:
            ok = False
            print("  x FAIL {}: {}".format(base_run["name"], "; ".join(diffs)))
        else:
            print("  PASS   {} (layers={}, resin={} mL, time={} s)".format(
                base_run["name"], b["layer_count"], b["resin_volume_ml"],
                b["estimated_print_time"]))
    report_engine_drift(baseline["engine"], current["engine"])
    return ok


def report_engine_drift(base_engine, cur_engine):
    """比對 exe 與 slicer_core.dll 兩個二進位，並分別報告。

    不改變比對結果（回歸仍以 `.sl1` 輸出為準），但必須讓「引擎其實變了」
    這件事無法被漏看——尤其是 exe 未重連、只有 dll 重建的情形。
    """
    changed = []
    unknown = []
    for key in ENGINE_BINARIES:
        b, c = base_engine.get(key), cur_engine.get(key)
        label = "slicer-engine.exe" if key == "sha256" else "slicer_core.dll"
        if b is None or c is None:
            unknown.append(label)
        elif b != c:
            changed.append(label)
    if changed:
        print("  註記：引擎二進位與基準不同（{}）；比對仍以輸出為準".format(
            "、".join(changed)))
    if unknown:
        print("  註記：無法比對（基準或本次缺少雜湊）：{}".format("、".join(unknown)))
    if not changed and not unknown:
        print("  註記：引擎二進位與基準完全相同（exe 與 slicer_core.dll 皆是）")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", default=str(DEFAULT_ENGINE))
    ap.add_argument("--out", help="產生基準：寫入 <DIR>/baseline.json")
    ap.add_argument("--compare", help="比對基準：與此 baseline.json 逐層比對")
    args = ap.parse_args()

    engine = Path(args.engine).resolve()
    if not engine.is_file():
        raise SystemExit("找不到切片器: {}".format(engine))

    if args.compare:
        baseline = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        print("重跑並與基準比對: {}".format(args.compare))
        current = collect(engine)
        print("---------------------------------------------")
        ok = compare(baseline, current)
        print("---------------------------------------------")
        print("結果: PASS（逐層雜湊與統計數據完全一致）" if ok else "結果: FAIL（出現差異）")
        return 0 if ok else 1

    if not args.out:
        ap.error("需指定 --out 或 --compare")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = collect(engine, keep_dir=out_dir)
    dest = out_dir / "baseline.json"
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    for r in data["runs"]:
        s = r["sl1"]
        print("  {:<24} {:<4} layers={:<5} resin={} mL  time={} s  rollup={}".format(
            r["name"], r["kind"], s["layer_count"], s["resin_volume_ml"],
            s["estimated_print_time"], s["layers_rollup_sha256"][:16]))
    print("基準已寫入: {}".format(dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
