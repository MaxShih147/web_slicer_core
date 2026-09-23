"""Single source of truth for backend API error codes.

This module IS the registry. `agent/tools/error_codes.py --write` generates
`docs/err_code_spec.md` and `docs/error_codes.json` from `ALL` below — those
two files are read-only; edit `note` (and everything else) here instead.

`owner` classification (see openspec/changes/unify-error-code-registry/design.md
D2, corrected 2026-09-17 against actual code):

- "engine": the slicing engine can determine this failure from its own
  process output alone, via a fixed string needle that a classifier matches
  against stdout/stderr. `engine_needles` MUST be non-empty for these.
- "python": everything else — request/job/HTTP-context codes, and codes whose
  detection point is Python even when the underlying failure originates in
  engine work (e.g. HOLLOW_GENERATION_FAILED, decided by checking the
  subprocess exit code and whether the output file exists — see
  agent/sla_operations.py:generate_hollow — not by matching an engine string).
  SUPPORT_GENERATION_FAILED is the classifiers' catch-all when nothing
  matched, so it has no needle of its own and is "python" too.
"""

from dataclasses import dataclass
from typing import Literal, Tuple

Owner = Literal["engine", "python"]


@dataclass(frozen=True)
class ErrorCodeSpec:
    code: str
    http_status: int
    retryable: bool
    owner: Owner
    note: str
    engine_needles: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.owner not in ("engine", "python"):
            raise ValueError(f"{self.code}: owner must be 'engine' or 'python', got {self.owner!r}")
        if self.owner == "engine" and not self.engine_needles:
            raise ValueError(f"{self.code}: owner='engine' requires at least one engine_needles entry")


# ─── generic / request / job codes ─────────────────────────────────────────────

_GENERIC: Tuple[ErrorCodeSpec, ...] = (
    ErrorCodeSpec(
        code="INTERNAL_ERROR",
        http_status=500,
        retryable=True,
        owner="python",
        note="非預期的伺服器錯誤",
    ),
    ErrorCodeSpec(
        code="VALIDATION_ERROR",
        http_status=400,
        retryable=False,
        owner="python",
        note="請求參數格式或值域錯誤（型別錯誤、非法 enum 值、content-type 不符等）",
    ),
    ErrorCodeSpec(
        code="MISSING_BODY",
        http_status=400,
        retryable=False,
        owner="python",
        note="必要欄位或檔案缺失",
    ),
    # add-support-param-validation Task 4: distinct from VALIDATION_ERROR
    # (400, request-shape problems — bad JSON, wrong content-type, unsupported
    # file type). This is specifically a SLAConfig field failing its own
    # pydantic validator (e.g. pad_wall_slope outside 45–90, an unrecognised
    # enum value) — semantically "syntactically fine, value not acceptable",
    # so 422 per REST convention, not 400. Introducing a second code lets
    # VALIDATION_ERROR keep its existing 400 everywhere it's already used
    # (~26 call sites) instead of splitting one code across two statuses.
    ErrorCodeSpec(
        code="CONFIG_VALIDATION_ERROR",
        http_status=422,
        retryable=False,
        owner="python",
        note="切片／支撐設定欄位未通過驗證（如 pad_wall_slope 超出 45–90 度範圍、非法列舉值），訊息含欄位名",
    ),
    ErrorCodeSpec(
        code="JOB_NOT_FOUND",
        http_status=404,
        retryable=False,
        owner="python",
        note="指定的 job_id 不存在",
    ),
    ErrorCodeSpec(
        code="JOB_ALREADY_EXECUTED",
        http_status=409,
        retryable=False,
        owner="python",
        note="Job 已執行，不再接受修改",
    ),
    ErrorCodeSpec(
        code="JOB_STILL_PROCESSING",
        http_status=200,
        retryable=True,
        owner="python",
        note="Job 尚未完成，無法下載結果",
    ),
    ErrorCodeSpec(
        code="JOB_FAILED",
        http_status=409,
        retryable=False,
        owner="python",
        note="Job 執行失敗，無法下載結果",
    ),
    ErrorCodeSpec(
        code="MODEL_NOT_FOUND",
        http_status=404,
        retryable=False,
        owner="python",
        note="Job 上沒有模型，或指定的 source 檔案不存在",
    ),
)

# ─── model / mesh preprocessing codes ──────────────────────────────────────────

_MESH: Tuple[ErrorCodeSpec, ...] = (
    ErrorCodeSpec(
        code="INVALID_MODEL",
        http_status=422,
        retryable=False,
        owner="engine",
        note="STL 內容損壞、格式無效、或幾何載入失敗",
        engine_needles=("Error: file is empty:",),
    ),
    ErrorCodeSpec(
        code="FILE_NOT_FOUND",
        http_status=404,
        retryable=False,
        owner="python",
        note="輸出檔案不存在（job 完成但檔案遺失）",
    ),
    ErrorCodeSpec(
        code="BOOLEAN_FAILED",
        http_status=422,
        retryable=False,
        owner="python",
        note="Boolean 幾何計算失敗（non-manifold、self-intersecting 等）",
    ),
    ErrorCodeSpec(
        code="BOOLEAN_INVALID_MESH",
        http_status=422,
        retryable=False,
        owner="python",
        # 2026-09-17：err_code_spec.md 原表沒有這一列（見 proposal.md 的漂移說明），
        # note 依 errors.py:boolean_invalid_mesh() 的訊息與其在 boolean 流程中的
        # 前置檢查角色改寫，非逐字抄錄。
        note="Boolean 運算前偵測到模型網格本身含幾何錯誤（如 non-manifold），無法處理",
    ),
    ErrorCodeSpec(
        code="NO_DRAIN_HOLES",
        http_status=422,
        retryable=False,
        owner="python",
        note="在目前幾何中找不到可放置 drain hole 的 wall edge",
    ),
    ErrorCodeSpec(
        code="NO_HEX_GRID_CELLS",
        http_status=422,
        retryable=False,
        owner="python",
        note="Hex grid 演算法未產生任何 cell，參數可能超出 hollow mesh 範圍",
    ),
    ErrorCodeSpec(
        code="HOLLOW_GENERATION_FAILED",
        http_status=422,
        retryable=False,
        owner="python",
        note="PrusaSlicer 無法產生 hollow interior mesh（幾何太薄、太複雜等）",
    ),
)

# ─── support generation codes ──────────────────────────────────────────────────
# 對應 generate-supports 的 SLAPrint::validate() 失敗與結果分類（見
# openspec/changes/add-support-generation-error-codes、agent/support_classifier.py）。

_SUPPORT: Tuple[ErrorCodeSpec, ...] = (
    ErrorCodeSpec(
        code="SUPPORT_HEAD_TOO_WIDE",
        http_status=422,
        retryable=False,
        owner="engine",
        note="支撐 pinhead 直徑對此幾何無效（`Invalid pinhead diameter`）",
        engine_needles=("Invalid pinhead diameter",),
    ),
    ErrorCodeSpec(
        code="SUPPORT_HEAD_PENETRATION_INVALID",
        http_status=422,
        retryable=False,
        owner="engine",
        note="支撐 head penetration 值無效（`Invalid Head penetration`）",
        engine_needles=("Invalid Head penetration",),
    ),
    ErrorCodeSpec(
        code="SUPPORT_ELEVATION_TOO_LOW",
        http_status=422,
        retryable=False,
        owner="engine",
        note="物件抬升高度過低，無法產生支撐（`Elevation is too low for object`）",
        engine_needles=("Elevation is too low for object",),
    ),
    ErrorCodeSpec(
        code="SUPPORT_POINTS_REQUIRED",
        http_status=422,
        retryable=False,
        owner="engine",
        note="缺少必要支撐點（`Cannot proceed without support points`）",
        engine_needles=("Cannot proceed without support points",),
    ),
    ErrorCodeSpec(
        code="SUPPORT_PAD_GAP_CONFLICT",
        http_status=422,
        retryable=False,
        owner="engine",
        note="支撐柱底部落於物件與 pad 的間隙（pillar/pad gap 衝突）",
        engine_needles=("The endings of the support pillars",),
    ),
    ErrorCodeSpec(
        code="MODEL_OUT_OF_BOUNDS",
        http_status=422,
        retryable=False,
        owner="engine",
        note="沒有物件完全落在成型體積內（`no object is fully inside the print volume`）",
        engine_needles=("no object is fully inside the print volume",),
    ),
    ErrorCodeSpec(
        code="SUPPORT_GENERATION_FAILED",
        http_status=422,
        retryable=False,
        owner="python",
        note="支撐生成失敗且無法歸因至更具體代碼（fail-closed fallback，附原始 stdout/stderr）",
    ),
    ErrorCodeSpec(
        code="SUPPORT_POINTS_MODEL_MISMATCH",
        http_status=422,
        retryable=False,
        owner="engine",
        # 2026-09-17：err_code_spec.md 原表沒有這一列，note 依
        # errors.py:support_points_model_mismatch() 的 docstring 改寫，非逐字抄錄。
        note="匯入的支撐點與目前模型不符（依指紋比對判定），不可重試，只能對目前模型重新產生支撐點",
        engine_needles=(
            "SUPPORT_POINTS_MODEL_MISMATCH: imported support points do not match this model",
        ),
    ),
    # merge-engine-result-classifiers Task 3.1: two new engine-owned codes,
    # symmetric across both the support and slicing flows from the start
    # (see agent/engine_rules.py — both rows carry flows=("support","slice")).
    ErrorCodeSpec(
        code="SUPPORT_POINT_SAMPLING_FAILED",
        http_status=422,
        retryable=False,
        owner="engine",
        note="引擎的支撐點取樣演算法失敗，無法在此模型上取樣出支撐島；建議微調模型擺放角度後重試（`SLA support point generator has failed.`）",
        engine_needles=("SLA support point generator has failed.",),
    ),
    ErrorCodeSpec(
        code="SHRINKAGE_COMPENSATION_INVALID",
        http_status=422,
        retryable=False,
        owner="engine",
        note="物件的縮放與收縮補償使轉換矩陣不可逆（零縮放或零收縮補償），支撐點座標無法映射回輸入模型（`the object transform is not invertible`）",
        # Needle is "the object transform is" (not the full ".. not invertible"
        # phrase): the C++ source splits this message across two adjacent
        # string literals ("...is " / "not invertible..." on the next line),
        # so only the first half is a *contiguous* substring of the raw
        # source text. The compiled/runtime string still concatenates them,
        # so this shorter needle matches both the source-contract test and
        # actual engine stderr.
        engine_needles=("the object transform is",),
    ),
)

# ─── slicing codes ──────────────────────────────────────────────────────────────
# 對應已分類的 SLA 切片失敗（見 agent/slicing_classifier.py）。

_SLICING: Tuple[ErrorCodeSpec, ...] = (
    ErrorCodeSpec(
        code="PAD_CONFIG_INVALID",
        http_status=422,
        retryable=False,
        owner="engine",
        note="Pad brim 過小，無法在目前組態下產生底座（`Pad brim size is too small`）",
        engine_needles=("Pad brim size is too small",),
    ),
    ErrorCodeSpec(
        code="EXPOSURE_TIME_OUT_OF_RANGE",
        http_status=422,
        retryable=False,
        owner="engine",
        note="曝光時間超出印表機設定檔的允許範圍"
        "（`Exposition/Initial exposition time is out of printer profile bounds`）",
        engine_needles=("xposition time is out of printer profile bounds",),
    ),
    ErrorCodeSpec(
        code="MODEL_MESH_UNSLICEABLE",
        http_status=422,
        retryable=False,
        owner="engine",
        note="模型幾何無法切片（幾何破損或 non-manifold，`can not be sliced`）",
        engine_needles=("can not be sliced",),
    ),
    ErrorCodeSpec(
        code="UNPRINTABLE_OBJECT",
        http_status=422,
        retryable=False,
        owner="engine",
        note="模型包含無法列印的層（建議調整支撐設定，`There are unprintable objects`）",
        engine_needles=("There are unprintable objects",),
    ),
    ErrorCodeSpec(
        code="PAD_GENERATION_FAILED",
        http_status=422,
        retryable=False,
        owner="engine",
        note="在目前組態下無法為此模型產生底座 mesh（`No pad can be generated`）",
        engine_needles=("No pad can be generated",),
    ),
)

ALL: Tuple[ErrorCodeSpec, ...] = _GENERIC + _MESH + _SUPPORT + _SLICING

_codes = [spec.code for spec in ALL]
_duplicates = sorted({code for code in _codes if _codes.count(code) > 1})
if _duplicates:
    raise ValueError(f"duplicate error codes in registry: {_duplicates}")
del _codes, _duplicates
