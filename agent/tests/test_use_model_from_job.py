"""`use-model-from` 的 source_job_id 路徑逃逸防禦 — 任務 2.1~2.5
（optimize-support-regeneration）。

`POST /api/v2/slices/{job_id}/use-model-from/{source_job_id}` 把 `source_job_id`
直接餵給 `get_job_dir()` 組成檔案系統路徑。job id 是伺服器產生的權杖，呼叫端
永遠不該自己發明一個，因此任何超出該字元集的輸入都是探測而非手誤。

真正危險的是**反斜線**：它不是 URL 的路徑分隔字元，所以 `..%5Csecret` 會以
單一路徑片段的形式通過路由，接著在 Windows 上被當成目錄分隔字元，讓
`JOBS_DIR / source_job_id` 指到 job 儲存區之外。

下列測試不只斷言錯誤碼，還在 job 儲存區**外面**放一個誘餌檔案，並斷言它
不會被讀到——只斷言錯誤碼的話，即使逃逸成功但恰好檔名對不上，測試一樣
會綠，那就測不到真正的東西。

修正前的實測（任務 2.3 基準線）證實了漏洞為真而非理論：

    '..\\secret'      -> HTTP 200，誘餌外洩 = True     ← 真的讀到儲存區外的檔案
    '..%5Csecret'     -> HTTP 200，誘餌外洩 = True     ← 同上（URL 編碼形式）
    'a.b'             -> HTTP 404 MODEL_NOT_FOUND      ← 進到程式碼但路徑不存在

**為何不用 `../../etc` 當測試案例**：正斜線會讓 Starlette 的路由比對不到這條
POST 路由，直接回 405，請求根本到不了 `use_model_from_job()`。用它當測試等於
測路由而不是測防禦，修正前後都不會變。含點號的 `a.b` 才是真正會進到程式碼、
且修正前後行為會改變的案例。
"""

import inspect
import struct

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agent import jobs
from agent.api_v2 import (
    _SOURCE_FILE_DIRS,
    _pending_jobs,
    _require_safe_job_id,
    router,
    use_model_from_job,
)
from agent.errors import APIError

SOURCE_JOB_ID = "abc12345"
TARGET_JOB_ID = "def67890"
SOURCE_FILE = "ortho_result.stl"


def _valid_stl(marker: bytes = b"") -> bytes:
    """一個面積非零的合法單面二進位 STL。

    `marker` 寫進 80 bytes 的標頭。標頭不參與幾何解析，但端點是以
    `read_bytes()` 原封不動存下整份檔案，所以標頭差異會出現在 `stl_data`
    裡——這讓測試能斷言「讀到的是哪一個檔案」，而不只是「有讀到東西」。
    """
    header = marker.ljust(80, b"\x00") + struct.pack("<I", 1)
    facet = struct.pack(
        "<12fH",
        0.0, 0.0, 1.0,
        0.0, 0.0, 0.0,
        1.0, 0.0, 0.0,
        0.0, 1.0, 0.0,
        0,
    )
    return header + facet


@pytest.fixture
def client(tmp_path, monkeypatch):
    """把 JOBS_DIR 指到 tmp_path/jobs，並掛上與正式環境相同的錯誤處理器。

    沒有這個處理器，APIError 會直接從 TestClient 拋出來，測到的就不是
    真正的 HTTP 回應形狀。
    """
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(jobs, "JOBS_DIR", jobs_dir)

    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(APIError)
    async def _api_error_handler(request: Request, exc: APIError):
        return exc.to_response()

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _clean_pending():
    """`_pending_jobs` 是模組層級 dict，不清會讓測試之間互相污染。"""
    _pending_jobs.clear()
    yield
    _pending_jobs.clear()


@pytest.fixture
def bait(tmp_path):
    """在 job 儲存區**外面**放一個誘餌檔案。

    路徑刻意排成 `<tmp>/secret/output/ortho_result.stl`，使得
    `JOBS_DIR / "..\\secret" / "output" / "ortho_result.stl"` 一旦逃逸成功
    就會正好命中它。回傳檔案內容供斷言比對。
    """
    content = _valid_stl()
    bait_path = tmp_path / "secret" / "output" / SOURCE_FILE
    bait_path.parent.mkdir(parents=True)
    bait_path.write_bytes(content)
    return content


def _make_pending_target():
    """建立一個 pending job 作為引用的目標，讓請求能走到路徑組成那一步。"""
    _pending_jobs[TARGET_JOB_ID] = {"config": {}, "models": [], "status": "created"}


def _make_source_job():
    """在 JOBS_DIR 內建立一個合法的來源 job 及其 output 檔案。"""
    source_out = jobs.JOBS_DIR / SOURCE_JOB_ID / "output"
    source_out.mkdir(parents=True, exist_ok=True)
    (source_out / SOURCE_FILE).write_bytes(_valid_stl())


def _post(client, source_job_id, source_file=SOURCE_FILE):
    return client.post(
        f"/api/v2/slices/{TARGET_JOB_ID}/use-model-from/{source_job_id}",
        params={"source_file": source_file},
    )


def _plant(subdir, filename, marker):
    """在來源 job 的指定子目錄放一份帶標記的 STL，回傳其位元組內容。"""
    path = jobs.JOBS_DIR / SOURCE_JOB_ID / subdir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _valid_stl(marker)
    path.write_bytes(content)
    return content


def _referenced_bytes():
    """取出被引用進來的模型位元組（沒有模型時直接讓測試以 IndexError 失敗）。"""
    return _pending_jobs[TARGET_JOB_ID]["models"][0]["stl_data"]


# ── 案例 1：合法 job id 必須通過檢驗 ────────────────────────────────────────


def test_legal_job_id_is_accepted(client):
    """2.2：伺服器產生格式的 job id SHALL 通過檢驗並完成引用。

    這一筆守的是「防禦不能擋到正常流量」。少了它，一個無條件拒絕的實作
    也能讓下面兩個逃逸測試變綠。
    """
    _make_pending_target()
    _make_source_job()

    resp = _post(client, SOURCE_JOB_ID)

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["sourceJobId"] == SOURCE_JOB_ID
    assert len(_pending_jobs[TARGET_JOB_ID]["models"]) == 1


# ── 案例 2、3：路徑逃逸必須被擋下 ───────────────────────────────────────────


def test_backslash_escape_is_rejected(client, bait):
    """2.2：含反斜線的 source_job_id SHALL 被拒並回 JOB_NOT_FOUND。

    這是本次要修的實際漏洞。修正前此請求回 HTTP 200 並把 job 儲存區外的
    誘餌檔案吸收成這個 job 的模型——是真的資料外洩，不是理論風險。
    """
    _make_pending_target()

    resp = _post(client, "..\\secret")

    assert resp.status_code == 404
    assert resp.json()["code"] == "JOB_NOT_FOUND"

    # 最關鍵的一條：儲存區外的誘餌沒有被讀進來
    assert _pending_jobs[TARGET_JOB_ID]["models"] == []


def test_dotted_job_id_is_rejected(client, bait):
    """2.2：含點號的 source_job_id SHALL 被拒並回 JOB_NOT_FOUND。

    修正前此請求會一路走到路徑組成才因檔案不存在而回 MODEL_NOT_FOUND——
    也就是說它進到了程式碼、碰了檔案系統，只是恰好沒命中東西。修正後
    SHALL 在組成任何路徑之前就被擋下。
    """
    _make_pending_target()

    resp = _post(client, "a.b")

    assert resp.status_code == 404
    assert resp.json()["code"] == "JOB_NOT_FOUND"
    assert _pending_jobs[TARGET_JOB_ID]["models"] == []


def test_require_safe_job_id_returns_its_input_verbatim():
    """規格 R5：通過檢驗時 `_require_safe_job_id()` SHALL 原樣回傳該字串。

    這條保證目前在生產端沒有被觀察到——`use_model_from_job()` 是把回傳值丟掉、
    只取它「不通過就拋錯」的副作用。所以規格寫了、但沒有任何東西守著它。
    直接測函式本體是唯一能釘住這條保證的地方。

    順帶涵蓋規格所述的合法字元集與 1～64 的長度邊界：一個字元、64 個字元、
    底線與連字號，都必須原樣回傳（而非被正規化、截斷或轉換大小寫）。
    """
    for job_id in ["valid_id", "a", "A" * 64, "abc12345", "a_b-c_D-9"]:
        assert _require_safe_job_id(job_id) == job_id

    # 對照：長度超出上限的字串不屬於「通過」的情況，仍須被拒
    with pytest.raises(APIError) as excinfo:
        _require_safe_job_id("A" * 65)
    assert excinfo.value.code == "JOB_NOT_FOUND"


# ── source_file 的目錄查表與拒絕規則 — 任務 2.7、2.10 ───────────────────────
#
# 舊實作先試 `output/`，找不到再退回 `input/`。那個 fallback 有兩個問題：一個
# 未收錄的檔名有兩次命中機會，而且呼叫端無從得知自己拿到的究竟是哪一個目錄裡
# 的檔案。下列測試因此不只斷言狀態碼——每個檔案都帶不同的標頭標記，斷言比對的
# 是「讀到的是哪一份」。只斷言 200 的話，退回 fallback 的實作一樣會綠。


@pytest.fixture
def outside_bait(tmp_path):
    """在 job 儲存區外放一個誘餌，供 source_file 路徑穿越案例使用。

    位置刻意選在 `<tmp>/loot.stl`：修正前的路徑組成是
    `JOBS_DIR/<job>/output/<source_file>`，因此 `../../../loot.stl` 恰好三層
    上溯命中它。深度算錯的話，測試會因為「檔案不存在」而不是「防禦生效」
    而通過——那就測不到東西了。
    """
    content = _valid_stl(b"LOOT")
    (tmp_path / "loot.stl").write_bytes(content)
    return content


def test_model_stl_reads_input_only(client, outside_bait):
    """2.7：`model.stl` SHALL 只讀 `input/`。

    `output/` 放了同名誘餌。若實作仍以 output 優先，這裡會讀到誘餌而失敗。
    """
    _make_pending_target()
    wanted = _plant("input", "model.stl", b"INPUT")
    _plant("output", "model.stl", b"OUTPUT-DECOY")

    resp = _post(client, SOURCE_JOB_ID, "model.stl")

    assert resp.status_code == 200
    assert _referenced_bytes() == wanted


def test_ortho_result_reads_output_only(client):
    """2.7：`ortho_result.stl` SHALL 只讀 `output/`。

    與上一筆對稱：誘餌改放 `input/`，擋住「一律讀 input」這種相反的錯法。
    """
    _make_pending_target()
    wanted = _plant("output", SOURCE_FILE, b"OUTPUT")
    _plant("input", SOURCE_FILE, b"INPUT-DECOY")

    resp = _post(client, SOURCE_JOB_ID, SOURCE_FILE)

    assert resp.status_code == 200
    assert _referenced_bytes() == wanted


def test_unlisted_filename_is_rejected(client):
    """2.7：不在對應表中的檔名 SHALL 回 `VALIDATION_ERROR`。

    刻意選 `boolean.stl`——它是端點現行的預設值，且磁碟上根本不存在。
    """
    _make_pending_target()
    _make_source_job()

    resp = _post(client, SOURCE_JOB_ID, "boolean.stl")

    assert resp.status_code == 400
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert _pending_jobs[TARGET_JOB_ID]["models"] == []


@pytest.mark.parametrize(
    "source_file",
    ["../../../loot.stl", "..\\..\\..\\loot.stl"],
    ids=["forward-slash", "backslash"],
)
def test_source_file_traversal_is_rejected(client, outside_bait, source_file):
    """2.7：路徑穿越字串 SHALL 回 `VALIDATION_ERROR` 且不得存取檔案系統。

    修正前這兩種寫法都回 HTTP 200 並把儲存區外的誘餌吸收成模型——與
    `source_job_id` 那半邊不同，這裡連 URL 編碼技巧都不需要，因為
    `source_file` 是查詢參數而非路徑片段，正斜線不會被路由攔下。
    """
    _make_pending_target()
    _make_source_job()

    resp = _post(client, SOURCE_JOB_ID, source_file)

    assert resp.status_code == 400
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert _pending_jobs[TARGET_JOB_ID]["models"] == []


@pytest.mark.parametrize("source_file", sorted(_SOURCE_FILE_DIRS))
def test_listed_filename_is_not_rejected_for_its_dot(client, source_file):
    """2.7：對應表中的每個檔名 SHALL 不因含點號而被拒。

    `source_job_id` 的規則禁止點號，但檔名一定含點號。這一筆守的是那條規則
    不被誤套到檔名上，並順帶確認表中沒有任何一項是「收錄了卻拿不到」的死條目。
    """
    _make_pending_target()
    wanted = _plant(_SOURCE_FILE_DIRS[source_file], source_file, b"WANTED")

    resp = _post(client, SOURCE_JOB_ID, source_file)

    assert resp.status_code == 200
    assert _referenced_bytes() == wanted


def test_missing_input_file_does_not_fall_back_to_output(client):
    """2.10：對應表指向 `input` 但檔案不存在時 SHALL 回 `MODEL_NOT_FOUND`。

    這是移除 fallback 的迴歸測試。`output/model.stl` 存在且可讀，舊實作會
    高高興興地把它交出去；新實作 MUST NOT 去看它。
    """
    _make_pending_target()
    _plant("output", "model.stl", b"OUTPUT-DECOY")

    resp = _post(client, SOURCE_JOB_ID, "model.stl")

    assert resp.status_code == 404
    assert resp.json()["code"] == "MODEL_NOT_FOUND"
    assert _pending_jobs[TARGET_JOB_ID]["models"] == []


# ── 端點預設值 — 任務 2.13 ──────────────────────────────────────────────────
#
# 舊預設值是 `boolean.stl`，磁碟上沒有任何寫入者會產生這個檔名（它只是
# `main.py:1066` 下載回應的檔名）。加上對應表之後，這個預設值會讓不帶參數的
# 呼叫直接撞上 `VALIDATION_ERROR`——查表規則本身正確，錯的是預設值。


def test_missing_source_job_is_reported_as_model_not_found(client):
    """來源 job 目錄不存在時 SHALL 回 `MODEL_NOT_FOUND`。

    規格 job-file-reference-safety「引用失敗須為明確的錯誤回應」要求呼叫端
    能據此判定需退回完整上傳，因此錯誤碼必須明確、不得是泛用的 500 或
    未處理例外。這裡的 job id 格式完全合法，所以它會通過 `_require_safe_job_id()`
    一路走到存在性檢查——測到的是「合法但不存在」，而非「被檢驗擋下」。
    """
    _make_pending_target()

    resp = _post(client, "gone1234", "model.stl")

    assert resp.status_code == 404
    assert resp.json()["code"] == "MODEL_NOT_FOUND"
    assert _pending_jobs[TARGET_JOB_ID]["models"] == []


def test_lookup_table_only_maps_to_real_subdirectories():
    """對應表的值 SHALL 只有 `input` 與 `output` 兩種。

    這條守的是拼字。`test_listed_filename_is_not_rejected_for_its_dot` 把檔案
    種在 `_SOURCE_FILE_DIRS[name]` 再讀回來，是自我一致而非正確性——把
    `"output"` 打成 `"ouput"` 的話那筆照樣會綠，但真實端點會永遠回 404，因為
    磁碟上沒有那個目錄。值域檢查便宜，而且是唯一擋得住這種錯的東西。
    """
    assert set(_SOURCE_FILE_DIRS.values()) <= {"input", "output"}


def test_default_source_file_is_in_the_lookup_table():
    """2.13：端點預設值 SHALL 是對應表中的項目。

    這一筆直接檢查函式簽章，不經過 HTTP。缺陷的本質是「預設值與對應表脫節」，
    在這個層級釘住它，日後有人改動任一邊都會立刻被抓到——只靠下面那筆
    happy path 的話，得先有人想到要用預設值呼叫才會發現。
    """
    default = inspect.signature(use_model_from_job).parameters["source_file"].default

    assert default in _SOURCE_FILE_DIRS


def test_omitted_source_file_uses_the_default(client):
    """2.13：不帶 `source_file` 呼叫時 SHALL 查表命中，MUST NOT 回 `VALIDATION_ERROR`。

    `output/` 放了同名誘餌，因此本筆同時確認預設值走的是對應表指定的
    `input/`，而不是回到舊的「先試 output」路徑。
    """
    _make_pending_target()
    wanted = _plant("input", "model.stl", b"DEFAULT-INPUT")
    _plant("output", "model.stl", b"OUTPUT-DECOY")

    resp = client.post(
        f"/api/v2/slices/{TARGET_JOB_ID}/use-model-from/{SOURCE_JOB_ID}"
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["sourceJobId"] == SOURCE_JOB_ID
    assert _referenced_bytes() == wanted
