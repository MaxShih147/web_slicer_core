"""Job management for the web_slicer_core agent."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from .config import JOBS_DIR, SLICER_ENGINE_CLI, EXPORT_PROJECT_3MF
from .engine_job_queue import serialized_engine_job
from .models import JobStatus, SLAConfig, _extract_prz_timing_config
from .preview_scale import preview_scale_for
from .prz_encoder import _compute_print_time, sl1_layer_names
from .sla_operations import generate_config_ini, notify_launcher_if_prusa_crashed

logger = logging.getLogger(__name__)


# --- 切片進度解析 ---------------------------------------------------------
# 切片引擎的 SLA CLI 以 ``printf("%3d%s %s\n", percent, "% =>", text)`` 把進度
# 寫到 stdout（fork 的 src/CLI/ProcessActions.cpp，status callback）。``%3d``
# 讓百分比靠右對齊到寬度 3，個位／十位數因此帶前導空白，解析必須容忍。
# 百分比後方緊接 ``% =>`` 再一個空格，末尾為階段標籤。
_PROGRESS_LINE_RE = re.compile(r"^\s*(\d{1,3})%\s*=>\s*(\S.*?)\s*$")


def parse_progress_line(line: str) -> Optional[tuple[int, str]]:
    """把單行 stdout 解析為 ``(百分比, 階段標籤)``。

    不是格式良好的進度事件時回傳 ``None`` —— 空行、CLI 的一般訊息、以及
    只是「長得像」進度行的輸入（缺少百分號、百分比非數字、標籤為空、
    百分比超出 0–100）。呼叫端靜默忽略 ``None``：畸形的一行絕不能中斷切片。
    """
    match = _PROGRESS_LINE_RE.match(line.rstrip("\r\n"))
    if match is None:
        return None

    percent = int(match.group(1))
    if not 0 <= percent <= 100:
        return None

    return percent, match.group(2)


# --- 階段標籤映射 ---------------------------------------------------------
# 引擎吐出的是英文自然語言標籤；後端映射為穩定識別碼後才對外，前端因此不必
# 依賴引擎的用字。權威定義見
# openspec/changes/add-slicing-progress/specs/slice-progress-reporting/spec.md。
STAGE_ASSEMBLING = "STAGE_ASSEMBLING"
STAGE_HOLLOWING = "STAGE_HOLLOWING"
STAGE_DRILLING = "STAGE_DRILLING"
STAGE_SLICING = "STAGE_SLICING"
STAGE_SUPPORT_POINTS = "STAGE_SUPPORT_POINTS"
STAGE_SUPPORT_TREE = "STAGE_SUPPORT_TREE"
STAGE_PAD = "STAGE_PAD"
STAGE_SLICING_SUPPORTS = "STAGE_SLICING_SUPPORTS"
STAGE_MERGING = "STAGE_MERGING"
STAGE_RASTERIZING = "STAGE_RASTERIZING"
STAGE_FINALIZING = "STAGE_FINALIZING"
# 由封存完成訊號產生，不對應任何引擎標籤（第 4 節）。
STAGE_ARCHIVED = "STAGE_ARCHIVED"

# 引擎標籤 → 識別碼。來源逐字取自 fork：
#   src/libslic3r/SLAPrintSteps.cpp 的 OBJ_STEP_LABELS（8）與 PRINT_STEP_LABELS（2）
#   src/libslic3r/SLAPrint.cpp 的收尾訊息（1）
# 這 11 條字串由 test_slice_progress_string_contract.py 對原始碼鎖定。
ENGINE_STAGE_LABEL_MAP: dict[str, str] = {
    "Assembling model from parts": STAGE_ASSEMBLING,
    "Hollowing model": STAGE_HOLLOWING,
    "Drilling holes into model.": STAGE_DRILLING,
    "Slicing model": STAGE_SLICING,
    "Generating support points": STAGE_SUPPORT_POINTS,
    "Generating support tree": STAGE_SUPPORT_TREE,
    "Generating pad": STAGE_PAD,
    "Slicing supports": STAGE_SLICING_SUPPORTS,
    "Merging slices and calculating statistics": STAGE_MERGING,
    "Rasterizing layers": STAGE_RASTERIZING,
    "Slicing done": STAGE_FINALIZING,
}

_TRAILING_PUNCTUATION = ".。!！?？:：;；,，"


def normalize_stage_label(label: str) -> str:
    """把引擎標籤正規化為比對用的鍵：小寫、收斂連續空白、去除尾端標點。

    去尾端標點是為了吸收 ``"Drilling holes into model."`` 這種帶句點的不一致；
    收斂空白與小寫則讓比對不受排版與大小寫調整影響。
    """
    collapsed = " ".join(label.split())
    return collapsed.rstrip(_TRAILING_PUNCTUATION).strip().lower()


# 正規化後的查表。在模組載入時建立，確保鍵衝突會立刻在啟動時暴露而非執行期。
_NORMALIZED_STAGE_LABELS: dict[str, str] = {
    normalize_stage_label(label): stage
    for label, stage in ENGINE_STAGE_LABEL_MAP.items()
}
assert len(_NORMALIZED_STAGE_LABELS) == len(ENGINE_STAGE_LABEL_MAP), (
    "階段標籤正規化後發生碰撞——兩個語意不同的標籤映射到同一個鍵"
)


def map_stage_label(label: str) -> str:
    """把引擎標籤映射為穩定識別碼。

    採正規化後**精確比對**，絕不使用子字串比對：``"Slicing model"`` /
    ``"Slicing supports"`` / ``"Slicing done"`` 共享前綴但語意完全不同，
    子字串比對必然誤判。

    未識別時降級為 :data:`STAGE_SLICING` 並記錄一筆含原始標籤的告警——這是
    這條字串耦合在執行期唯一的可觀測性手段，切片本身不受影響。
    """
    stage = _NORMALIZED_STAGE_LABELS.get(normalize_stage_label(label))
    if stage is None:
        logger.warning(
            "Unrecognized slice stage label, degrading to %s: %r "
            "(engine label may have drifted)",
            STAGE_SLICING,
            label,
        )
        return STAGE_SLICING
    return stage


# --- 封存完成訊號 ---------------------------------------------------------
# 引擎回報 100% 之後仍會寫出 .sl1 與 preview 封存檔，這段期間沒有任何進度事件。
# 封存全部寫完後 CLI 會印出這一行（fork 的 src/CLI/ProcessActions.cpp，接在
# export_print() + export_preview_zip() 之後），是「子進程真正做完」的唯一訊號。
#
# 逐字取自該處的字面量，**含尾端空格**（後面直接串接檔案路徑）。
# 由 test_slice_progress_string_contract.py 對原始碼鎖定。
ARCHIVE_DONE_MARKER = "Preview ZIP exported to "


def parse_progress_event(line: str) -> Optional[tuple[int, str]]:
    """把單行 stdout 解析為對外的 ``(百分比, 階段識別碼)``，否則回傳 ``None``。

    這是進度擷取的單一入口，涵蓋兩種來源：

    * 引擎的 ``百分比 => 標籤`` 進度行 —— 標籤經 :func:`map_stage_label` 映射。
    * 封存完成訊號 —— 產生 ``(100, STAGE_ARCHIVED)``。

    引擎自報完成與封存完成**百分比同為 100**，兩者的差別完全由階段識別碼承載：
    前者是 ``STAGE_FINALIZING``（還在寫檔），後者是 ``STAGE_ARCHIVED``（寫完了）。
    後端不對百分比做任何加權或縮放——進度條的權重分配屬於前端職責。
    """
    stripped = line.rstrip("\r\n")
    if stripped.lstrip().startswith(ARCHIVE_DONE_MARKER):
        return 100, STAGE_ARCHIVED

    parsed = parse_progress_line(stripped)
    if parsed is None:
        return None

    percent, label = parsed
    return percent, map_stage_label(label)


# --- 進度儲存 -------------------------------------------------------------
# 進程內記憶體，**不寫入 status.json**（design D3）：status.json 由
# write_job_status() 整包覆寫，且 read_job_status() 的 json.load 沒有半寫入容錯，
# 共用該檔會讓狀態查詢在切片途中解析失敗。
#
# 記憶體足夠的前提：Agent 以單一進程執行（main.py 的 uvicorn.run 未指定 workers），
# run_slicing 由 BackgroundTasks 在同進程執行，job 狀態查詢端點也在同進程。
#
# 生命週期：job 進入終態後由 run_slicing 清除（第 6 節），且清除必須發生在終態
# 寫入 status.json **之後**，否則會出現「狀態仍為執行中、但進度消失」的空窗。
job_progress: dict[str, dict] = {}


def set_job_progress(job_id: str, percent: int, stage: str) -> None:
    """記錄一筆進度事件。

    百分比**單調不減**：新值低於已記錄值時保留較高值。引擎的多物件迴圈理論上
    已保證單調，這層純屬防禦——成本為零，且能擋下解析誤判或未來引擎行為變動
    直接外流成用戶端可見的進度倒退。

    階段一律採用最新事件的值：單調保護只約束「使用者看到的數字」，不該阻擋
    階段推進。這正是封存尾段所需的行為——``STAGE_FINALIZING`` 與
    ``STAGE_ARCHIVED`` 百分比同為 100，兩者的差別完全由階段承載。
    """
    previous = job_progress.get(job_id)
    if previous is not None:
        percent = max(previous["percent"], percent)

    job_progress[job_id] = {"percent": percent, "stage": stage}


def get_job_progress(job_id: str) -> Optional[dict]:
    """讀回某個 job 的進度，未記錄時回傳 ``None``。

    ``None`` 的語意是「無進度可供提供」，API 層據此**整個省略** progress 欄位，
    不得填 0 或 null 佔位（前者會被用戶端誤判為進度倒退）。

    回傳的是副本，呼叫端無法經由它改動內部狀態。
    """
    progress = job_progress.get(job_id)
    return dict(progress) if progress is not None else None


def clear_job_progress(job_id: str) -> None:
    """清除某個 job 的進度。冪等——清除不存在的 job 不拋例外。

    冪等性是必要的：清除位於 run_slicing 的 finally，而例外路徑可能在進度
    尚未建立前就結束。
    """
    job_progress.pop(job_id, None)


def create_job_id() -> str:
    """Generate a unique job ID."""
    return str(uuid.uuid4())[:8]



def get_job_dir(job_id: str) -> Path:
    """Get the directory for a job."""
    return JOBS_DIR / job_id


def get_job_status_file(job_id: str) -> Path:
    """Get the status file path for a job."""
    return get_job_dir(job_id) / "status.json"


def job_exists(job_id: str) -> bool:
    """Check if a job exists."""
    return get_job_dir(job_id).exists()


def read_job_status(job_id: str) -> dict:
    """Read the job status from disk.

    Older status.json files predate the ``error_code`` / ``support_outcome``
    fields. They are normalized to ``None`` on read so every consumer sees a
    consistent shape: a FAILED job without ``error_code`` falls back to the
    generic JOB_FAILED, and a COMPLETED job without ``support_outcome`` simply
    carries no neutral hint.
    """
    status_file = get_job_status_file(job_id)
    if status_file.exists():
        with open(status_file, "r") as f:
            data = json.load(f)
    else:
        data = {
            "status": JobStatus.PENDING,
            "error": None,
            "layer_count": None,
            "estimated_print_time": None,
            "resin_volume_ml": None,
        }
    data.setdefault("error_code", None)
    data.setdefault("support_outcome", None)
    return data


def write_job_status(
    job_id: str,
    status: JobStatus,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
    support_outcome: Optional[str] = None,
    layer_count: Optional[int] = None,
    estimated_print_time: Optional[float] = None,
    resin_volume_ml: Optional[float] = None,
    has_support_mesh: bool = False,
    has_hollow_mesh: bool = False,
    has_cut_mesh: bool = False,
):
    """Write the job status to disk.

    ``error_code`` carries the specific failure code for FAILED jobs;
    ``support_outcome`` carries a neutral marker (e.g. ``SUPPORT_NOT_NEEDED``)
    on a COMPLETED job. Both are optional and absent from older status.json
    files, which readers treat as "no specific code" / "no neutral outcome".
    """
    status_file = get_job_status_file(job_id)
    data = {
        "status": status.value,
        "error": error,
        "error_code": error_code,
        "support_outcome": support_outcome,
        "layer_count": layer_count,
        "estimated_print_time": estimated_print_time,
        "resin_volume_ml": resin_volume_ml,
        "has_support_mesh": has_support_mesh,
        "has_hollow_mesh": has_hollow_mesh,
        "has_cut_mesh": has_cut_mesh,
    }
    with open(status_file, "w") as f:
        json.dump(data, f)


def create_job(job_id: str) -> Path:
    """Create a new job directory structure."""
    job_dir = get_job_dir(job_id)
    (job_dir / "input").mkdir(parents=True, exist_ok=True)
    (job_dir / "output").mkdir(exist_ok=True)
    write_job_status(job_id, JobStatus.PENDING)
    return job_dir


def _load_prz_config(job_dir: Path) -> Optional[dict]:
    """Load the persisted frontend config from jobs/{id}/prz_config.json.

    IO boundary (design D3, boundary 1): swallows file-missing / malformed-JSON
    errors and returns None so the caller can fall back to the fork estimate.
    """
    path = job_dir / "prz_config.json"
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):  # file absent / JSON corrupt
        return None


def resolve_estimated_print_time(
    prz_config: Optional[dict],
    total_layers: Optional[int],
    fallback: Optional[float],
) -> Optional[float]:
    """Resolve the PRZ physical print time, degrading to ``fallback`` on any failure.

    Pure function (design D3, boundary 2): no IO, no side effects. Null-guards
    sit outside the try (no exception-driven control flow); extraction and
    computation share a single try whose any failure returns ``fallback``.
    """
    if not prz_config or not total_layers:
        return fallback  # no config / no layers → use fork estimate
    try:
        timing = _extract_prz_timing_config(prz_config)
        return _compute_print_time(prz_config, total_layers, timing)
    except Exception:
        return fallback  # extraction / computation failure → use fork estimate


# --- 子進程串流讀取 -------------------------------------------------------
# 改為串流讀取後，**兩個串流必須並行 drain**（design D2）。只讀 stdout 會死鎖：
# 引擎持續往 stderr 寫 log，管線緩衝區填滿後子進程的 write 阻塞，於是它不再產出
# stdout，而父進程正等著 stdout 的下一行——雙方互鎖，切片永久停住且無錯誤可查。

# stderr 分塊讀取的塊大小。用 read(n) 而非 readline()：StreamReader 對單行長度
# 有上限（預設 64 KiB），引擎的 log 可能出現超長行，逐行讀會拋 LimitOverrunError
# 而讓本來會成功的切片失敗。stderr 只需整包落地為 log，本來就不需要行語意。
_STDERR_CHUNK_SIZE = 65536


async def _drain_stdout_progress(stream, job_id: str) -> Optional[float]:
    """逐行讀 stdout，把進度事件寫進 job_progress。

    stdout 的進度行很短，行導向讀取安全；解析失敗的行靜默忽略——畸形的一行
    絕不能中斷切片。

    回傳引擎回報運算完成（``STAGE_FINALIZING``）當下的 :func:`time.monotonic`
    時間點，供呼叫端量測封存尾段；該行未出現時回傳 ``None``。取第一次出現的
    時間，且用 monotonic 而非 wall clock，不受系統時間調整影響。
    """
    finalizing_at: Optional[float] = None

    while True:
        raw = await stream.readline()
        if not raw:
            break

        event = parse_progress_event(raw.decode("utf-8", errors="replace"))
        if event is None:
            continue

        percent, stage = event
        if stage == STAGE_FINALIZING and finalizing_at is None:
            finalizing_at = time.monotonic()

        set_job_progress(job_id, percent, stage)

    return finalizing_at


async def _drain_stderr(stream) -> bytes:
    """分塊讀完 stderr 並回傳原始 bytes。

    刻意不使用 ``readline()`` / ``async for``——見 :data:`_STDERR_CHUNK_SIZE`。
    """
    chunks: list[bytes] = []
    while True:
        chunk = await stream.read(_STDERR_CHUNK_SIZE)
        if not chunk:
            break
        chunks.append(chunk)

    return b"".join(chunks)


@serialized_engine_job
async def run_slicing(job_id: str, config: Optional[SLAConfig] = None):
    """Run PrusaSlicer in the background."""
    job_dir = get_job_dir(job_id)
    input_file = job_dir / "input" / "model.stl"
    output_file = job_dir / "output" / "model.sl1"
    support_stl_file = job_dir / "output" / "model_support.stl"
    stderr_file = job_dir / "stderr.log"
    config_file = job_dir / "config.ini"

    # Imported support mesh (dual-track binary rasterization): when the frontend
    # uploaded a separate support STL, the slicer must NOT self-generate supports
    # or a pad (the raft is part of the imported mesh). Force both off so the INI
    # is written with supports_enable=0 / pad_enable=0.
    import_support_file = job_dir / "input" / "support.stl"
    import_support = import_support_file.exists()
    if import_support and config is not None:
        config.supports_enable = False
        config.pad_enable = False

    # Check if supports are enabled
    supports_enabled = config.supports_enable if config else False

    # Update status to processing
    write_job_status(job_id, JobStatus.PROCESSING)

    # Generate config INI if config provided
    if config:
        generate_config_ini(config, config_file)
        # Also save config as JSON for reference
        with open(job_dir / "config.json", "w") as f:
            json.dump(config.model_dump(), f, indent=2)

    # Preview downscale ratio is derived from the printer format rather than
    # fixed: the consumer needs an absolute pixel width, so no single ratio can
    # serve 2560 and 15120 at once. The long side is max(x, y), not x, because
    # the engine swaps the pixel dimensions in portrait orientation.
    #
    # No config means no --load below, so the engine falls back to its built-in
    # preset and the real format is unknowable from here. preview_scale_for()
    # then yields the ceiling — which is exactly today's 0.25, so this path
    # keeps its current behaviour rather than guessing.
    preview_scale, _ = preview_scale_for(
        max(config.display_pixels_x, config.display_pixels_y) if config else 0
    )

    try:
        # Run PrusaSlicer CLI
        cmd = [
            str(SLICER_ENGINE_CLI),
            "--export-sla",
            "--export-preview-pngs", preview_scale,
            "--output", str(output_file),
        ]

        # Add support STL export if supports are enabled.
        # Mutually exclusive with --import-support-stl below: when a support STL
        # is imported, supports_enable was forced False above, so supports_enabled
        # is False here and this self-generated-support export branch is skipped.
        if supports_enabled:
            cmd.append("--export-support-stl")

        # Add center position
        if config:
            cmd.extend(["--center", f"{config.center_x},{config.center_y}"])

        # Add config file if generated
        if config and config_file.exists():
            cmd.extend(["--load", str(config_file)])

        # Import the separate support mesh as the support track (dual-track).
        if import_support:
            cmd.extend(["--import-support-stl", str(import_support_file)])

        cmd.append(str(input_file))

        # [layer-rle] Emit layers as PRZ-compatible RLE (not PNG) so the PRZ
        # download reads them verbatim — no PNG encode (slice) / decode
        # (download) round-trip. PRZ output is byte-identical (verified). The
        # layers.zip endpoint converts back to PNG on demand for the rare
        # PNG-expecting fallback.
        slice_env = {**os.environ, "SLA_LAYER_RLE": "1"}

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=slice_env,
        )

        # 兩個串流並行 drain（design D2）。只讀 stdout 會在 stderr 管線緩衝區
        # 填滿時死鎖；務必兩條 task 同時跑完再 wait() 收退出碼。
        finalizing_at, stderr = await asyncio.gather(
            _drain_stdout_progress(process.stdout, job_id),
            _drain_stderr(process.stderr),
        )
        await process.wait()

        # 封存尾段耗時：引擎自報 100% 之後仍要寫出 .sl1 與 preview 封存檔，這段
        # 期間完全沒有進度事件。前端需要這個數字才能合理配置該段的進度條寬度
        # （design Open Questions）——目前該寬度是估的，實測後再校準。
        # 未出現完成行時（例如切片中途失敗）不記錄，也不視為錯誤。
        if finalizing_at is not None:
            logger.info(
                "Archive tail elapsed %.2fs (job=%s): engine reported done while "
                "still writing the .sl1 and preview archives",
                time.monotonic() - finalizing_at,
                job_id,
            )

        # Save stderr for debugging
        with open(stderr_file, "wb") as f:
            f.write(stderr)

        notify_launcher_if_prusa_crashed(process.returncode)

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")
            write_job_status(job_id, JobStatus.FAILED, error=f"Exit code {process.returncode}: {error_msg}")
            return

        # Parse metadata from .sl1 (layers served directly from .sl1 on demand)
        if output_file.exists():
            layer_count, fork_print_time, resin_volume_ml = parse_sl1_metadata(output_file)

            # Sync estimated_print_time to the PRZ physical formula (single source
            # of truth, identical to the PRZ download path). Any failure degrades
            # to the fork SL1 estimate without affecting the COMPLETED status.
            prz_config = _load_prz_config(job_dir)
            if prz_config is None:
                logger.info(
                    "prz_config missing, falling back to fork time (job=%s)", job_id
                )
            estimated_print_time = resolve_estimated_print_time(
                prz_config, layer_count, fork_print_time
            )

            # Check if support mesh was generated
            has_support_mesh = support_stl_file.exists()

            # Experimental: Export 3MF project file for support inspection
            if EXPORT_PROJECT_3MF:
                await export_project_3mf(job_id, input_file, job_dir / "output")

            write_job_status(
                job_id,
                JobStatus.COMPLETED,
                layer_count=layer_count,
                estimated_print_time=estimated_print_time,
                resin_volume_ml=resin_volume_ml,
                has_support_mesh=has_support_mesh,
            )
        else:
            write_job_status(job_id, JobStatus.FAILED, error="Output file not created")

    except Exception as e:
        write_job_status(job_id, JobStatus.FAILED, error=str(e))

    finally:
        # 清除必須發生在終態寫入 status.json **之後**（spec：進度儲存生命週期）。
        # 反序會出現「狀態仍為執行中、但進度消失」的空窗，用戶端會看到進度倒退。
        # 放在 finally 是為了涵蓋例外路徑；clear 本身冪等，進度未建立也安全。
        clear_job_progress(job_id)


async def export_project_3mf(job_id: str, input_file: Path, output_dir: Path):
    """
    Experimental: Export 3MF project file to inspect support preservation.

    This runs a separate PrusaSlicer CLI invocation with --export-3mf.
    The 3MF file can be opened in PrusaSlicer GUI to check if supports
    are preserved or need to be reconstructed.
    """
    output_3mf = output_dir / "project_with_support.3mf"
    stderr_file = output_dir / "3mf_export_stderr.log"

    try:
        cmd = [
            str(SLICER_ENGINE_CLI),
            "--export-3mf",
            "--output", str(output_3mf),
            str(input_file),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        # Save stderr for debugging
        with open(stderr_file, "wb") as f:
            f.write(stderr)

        if process.returncode != 0:
            # Log but don't fail the job - this is experimental
            error_msg = stderr.decode("utf-8", errors="replace")
            print(f"[experimental] 3MF export failed for job {job_id}: {error_msg}")
        else:
            print(f"[experimental] 3MF exported: {output_3mf}")

    except Exception as e:
        # Log but don't fail the job
        print(f"[experimental] 3MF export error for job {job_id}: {e}")


def parse_sl1_metadata(sl1_file: Path) -> tuple[int, Optional[float], Optional[float]]:
    """Parse layer count and metadata from .sl1 file without extracting PNGs."""
    layer_count = 0
    estimated_print_time = None
    resin_volume_ml = None

    with zipfile.ZipFile(sl1_file, "r") as zf:
        if "config.ini" in zf.namelist():
            try:
                with zf.open("config.ini") as config_file:
                    for raw_line in config_file:
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, value = (part.strip() for part in line.split("=", 1))
                        if key == "printTime":
                            estimated_print_time = float(value)
                        elif key == "usedMaterial":
                            resin_volume_ml = float(value)
            except Exception:
                estimated_print_time = None
                resin_volume_ml = None

        # 層數以 sl1_layer_names() 統計（單一真值來源）：涵蓋 .rle（PRZ 快路徑）與
        # .png 兩種輸出，並排除縮圖污染。切片器改以 SLA_LAYER_RLE 輸出 .rle 後，
        # 舊的 endswith(".png") 會恆為 0，使 print-time 同步靜默失效。
        layer_count = len(sl1_layer_names(zf.namelist()))

    return layer_count, estimated_print_time, resin_volume_ml


def get_layer_png_from_sl1(job_id: str, layer_idx: int) -> Optional[bytes]:
    """Read a single layer as PNG bytes directly from the .sl1 archive.

    層檔以 sl1_layer_names() 定位（.rle 優先，否則 .png），涵蓋 RLE 與 PNG 兩種輸出。
    選中檔為 .rle 時以 rle_layer_to_png() 即時解碼。索引越界或解碼失敗（如缺解析度）
    皆回 None，由上層端點轉為 HTTP 404（維持既有契約，design D3）。
    """
    from .prz_decoder import rle_layer_to_png

    sl1_path = get_job_dir(job_id) / "output" / "model.sl1"
    if not sl1_path.exists():
        return None

    with zipfile.ZipFile(sl1_path, "r") as zf:
        layer_names = sl1_layer_names(zf.namelist())
        if not (0 <= layer_idx < len(layer_names)):
            return None
        name = layer_names[layer_idx]
        if name.endswith(".rle"):
            return rle_layer_to_png(zf, name)  # None on missing resolution → 404
        return zf.read(name)


def get_support_mesh_path(job_id: str) -> Optional[Path]:
    """Get the path to the support mesh STL file."""
    support_path = get_job_dir(job_id) / "output" / "model_support.stl"
    if support_path.exists():
        return support_path
    return None


def get_input_model_path(job_id: str) -> Optional[Path]:
    """Get the path to the original input model STL file."""
    model_path = get_job_dir(job_id) / "input" / "model.stl"
    if model_path.exists():
        return model_path
    return None


@serialized_engine_job
async def run_support_generation(job_id: str, config: Optional[SLAConfig] = None):
    """
    Generate support mesh only (without layer extraction).

    Uses the sla_operations API for clean implementation.
    """
    from .sla_operations import generate_supports

    job_dir = get_job_dir(job_id)
    write_job_status(job_id, JobStatus.PROCESSING)

    try:
        # Use default config if not provided
        if config is None:
            config = SLAConfig(supports_enable=True)

        result = await generate_supports(job_dir, config)
        classification = result.classification

        if classification is not None:
            # Drive status entirely from the classifier's structured verdict
            # (design D1/D4): failures carry the specific error_code; neutral
            # results ride on COMPLETED with a support_outcome; real success
            # sets has_support_mesh.
            if classification.status == JobStatus.FAILED:
                write_job_status(
                    job_id,
                    JobStatus.FAILED,
                    error=result.error,
                    error_code=classification.error_code,
                )
            else:
                write_job_status(
                    job_id,
                    JobStatus.COMPLETED,
                    layer_count=0,  # No layers extracted for support-only
                    support_outcome=classification.support_outcome,
                    has_support_mesh=classification.has_support_mesh,
                )
        elif result.success:
            # Defensive fallback: generate_supports always classifies, but keep
            # a safe path so a missing classification never silently drops status.
            write_job_status(
                job_id,
                JobStatus.COMPLETED,
                layer_count=0,
                has_support_mesh=True,
            )
        else:
            write_job_status(job_id, JobStatus.FAILED, error=result.error)

    except Exception as e:
        write_job_status(job_id, JobStatus.FAILED, error=str(e))


def get_hollow_mesh_path(job_id: str) -> Optional[Path]:
    """Get the path to the hollow interior mesh STL file."""
    hollow_path = get_job_dir(job_id) / "output" / "model_hollow.stl"
    if hollow_path.exists():
        return hollow_path
    return None


@serialized_engine_job
async def run_hollow_generation(job_id: str, config: Optional[SLAConfig] = None):
    """
    Generate hollow interior mesh only.

    Uses the sla_operations API for clean implementation.
    """
    from .sla_operations import generate_hollow

    job_dir = get_job_dir(job_id)
    write_job_status(job_id, JobStatus.PROCESSING)

    try:
        # Use default config if not provided
        if config is None:
            config = SLAConfig(hollowing_enable=True)

        result = await generate_hollow(job_dir, config)

        if result.success:
            write_job_status(
                job_id,
                JobStatus.COMPLETED,
                layer_count=0,  # No layers extracted for hollow-only
                has_hollow_mesh=True,
            )
        else:
            write_job_status(job_id, JobStatus.FAILED, error=result.error)

    except Exception as e:
        write_job_status(job_id, JobStatus.FAILED, error=str(e))


def get_cut_mesh_path(job_id: str) -> Optional[Path]:
    """Get the path to the combined cut mesh STL file (contains both upper and lower parts)."""
    output_dir = get_job_dir(job_id) / "output"

    # Check standard naming for combined file
    cut_path = output_dir / "model_cut.stl"
    if cut_path.exists():
        return cut_path

    # If no combined file, return upper part as default
    upper_path = output_dir / "model_upper.stl"
    if upper_path.exists():
        return upper_path

    return None


def get_cut_upper_mesh_path(job_id: str) -> Optional[Path]:
    """Get the path to the upper cut mesh STL file."""
    output_dir = get_job_dir(job_id) / "output"

    # Check for separated upper file
    upper_path = output_dir / "model_upper.stl"
    if upper_path.exists():
        return upper_path

    # Fallback to combined file
    cut_path = output_dir / "model_cut.stl"
    if cut_path.exists():
        return cut_path

    return None


def get_cut_lower_mesh_path(job_id: str) -> Optional[Path]:
    """Get the path to the lower cut mesh STL file."""
    output_dir = get_job_dir(job_id) / "output"

    # Check for separated lower file
    lower_path = output_dir / "model_lower.stl"
    if lower_path.exists():
        return lower_path

    return None


def get_drain_holes_path(job_id: str) -> Optional[Path]:
    """Get the path to the drain holes STL file."""
    drain_path = get_job_dir(job_id) / "output" / "model_drain_holes.stl"
    if drain_path.exists():
        return drain_path
    return None


def get_hex_grid_path(job_id: str) -> Optional[Path]:
    """Get the path to the hex grid STL file."""
    hex_path = get_job_dir(job_id) / "output" / "model_hex_grid.stl"
    if hex_path.exists():
        return hex_path
    return None


def get_boolean_mesh_path(job_id: str) -> Optional[Path]:
    """Get the path to the boolean result STL file."""
    output_dir = get_job_dir(job_id) / "output"

    # Check for any boolean result file
    for op in ["union", "difference", "intersection"]:
        bool_path = output_dir / f"model_boolean_{op}.stl"
        if bool_path.exists():
            return bool_path

    return None


@serialized_engine_job
async def run_cut_operation(job_id: str, cut_height: float, keep_mode: str = "both"):
    """
    Cut mesh at specified Z height.

    Uses the sla_operations API for clean implementation.

    Args:
        job_id: Job ID
        cut_height: Z height to cut at
        keep_mode: "both", "upper", or "lower"
    """
    from .models import CutConfig, CutMode
    from .sla_operations import cut_with_plane

    job_dir = get_job_dir(job_id)
    write_job_status(job_id, JobStatus.PROCESSING)

    try:
        # Convert string to CutMode enum
        mode = CutMode(keep_mode) if keep_mode in [m.value for m in CutMode] else CutMode.BOTH
        cut_config = CutConfig(cut_height=cut_height, keep_mode=mode)
        result = await cut_with_plane(job_dir, cut_config)

        if result.success:
            write_job_status(
                job_id,
                JobStatus.COMPLETED,
                layer_count=0,  # No layers for cut operation
                has_cut_mesh=True,
            )
        else:
            write_job_status(job_id, JobStatus.FAILED, error=result.error)

    except Exception as e:
        write_job_status(job_id, JobStatus.FAILED, error=str(e))
