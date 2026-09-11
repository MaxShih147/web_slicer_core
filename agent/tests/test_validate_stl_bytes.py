"""_validate_stl_bytes() 的無效模型邊界案例 — 任務 1.1~1.3（optimize-support-regeneration）。

本檔案的目的是為「`trimesh.load()` 改用 `process=False`」建立行為基準線。

任務 1.4 會把 `_validate_stl_bytes()` 的 `trimesh.load()` 改成 `process=False`。
那個改動的唯一安全前提是：**跳過的是幾何「處理」，不是幾何「檢查」**。
下列六個案例在改動前後 MUST 表現完全一致——前五個被攔截、第六個通過。
任何一個案例的行為改變，都代表 `process=False` 不安全，必須立刻停手。

案例是刻意挑選的，各自打在驗證邏輯的不同分支上：

  空 bytes / 亂數位元組     -> trimesh 連解析都失敗
  宣告 0 面 / ASCII 空 solid -> 解析成功但 len(mesh.faces) == 0
  宣告 10 面但資料截斷      -> 標頭與實際內容不一致
  單一零面積三角面          -> 解析成功且有面，是唯一該通過的一筆

最後一筆特別重要：它是零面積的退化三角形，正是 `process=True` 的頂點合併
最可能「處理掉」的東西。它現在會通過，改動後也 MUST 通過——本變更不得
藉機收緊或放寬既有的判定範圍。

另有一筆面積非零的合法三角面作為正向案例（任務 1.6）。少了它，一個
「永遠拋錯」的實作也能讓上述六筆全部通過。
"""

import struct

import pytest

from agent.api_v2 import _validate_stl_bytes
from agent.errors import APIError


# ── 六個案例的位元組建構 ────────────────────────────────────────────────────
#
# 二進位 STL 的格式：80 bytes 標頭 + 4 bytes 三角面數（小端序 uint32）
#                    + 每個三角面 50 bytes（12 個 float32 + 2 bytes 屬性）


def _binary_stl_header(triangle_count: int) -> bytes:
    """只有標頭與面數欄位，不含任何三角面資料。"""
    return b"\x00" * 80 + struct.pack("<I", triangle_count)


def empty_bytes() -> bytes:
    """案例 1：完全空的輸入。"""
    return b""


def zero_triangle_stl() -> bytes:
    """案例 2：結構完整，但標頭宣告三角面數為 0。"""
    return _binary_stl_header(0)


def truncated_stl() -> bytes:
    """案例 3：標頭宣告 10 個三角面，其後卻沒有任何三角面資料。"""
    return _binary_stl_header(10)


def random_bytes() -> bytes:
    """案例 4：不構成任何已知 STL 結構的位元組。"""
    return bytes(range(256)) * 4


def ascii_empty_solid() -> bytes:
    """案例 5：語法合法但不含任何 facet 的 ASCII STL。"""
    return b"solid x\nendsolid x\n"


def zero_area_facet_stl() -> bytes:
    """案例 6：一個三個頂點全為原點的退化三角面。

    預期通過，且是 process=False 最可能改變行為的一筆。
    """
    return _binary_stl_header(1) + b"\x00" * 50


def _facet(normal, v0, v1, v2) -> bytes:
    """組出一個三角面：12 個 float32 加上 2 bytes 屬性欄位。"""
    return struct.pack("<12fH", *normal, *v0, *v1, *v2, 0)


def valid_single_triangle_stl() -> bytes:
    """正向案例：一個面積非零的合法三角面。"""
    return _binary_stl_header(1) + _facet(
        (0.0, 0.0, 1.0),
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
    )


# ── 前五個案例：必須被攔截 ──────────────────────────────────────────────────

REJECTED_CASES = [
    pytest.param(empty_bytes(), id="empty-bytes"),
    pytest.param(zero_triangle_stl(), id="zero-triangle-count"),
    pytest.param(truncated_stl(), id="truncated-triangle-data"),
    pytest.param(random_bytes(), id="random-bytes"),
    pytest.param(ascii_empty_solid(), id="ascii-empty-solid"),
]


@pytest.mark.parametrize("content", REJECTED_CASES)
def test_invalid_model_is_rejected(content):
    """1.2：五個無效輸入 SHALL 一律被攔截並拋出 INVALID_MODEL。

    斷言 `code == "INVALID_MODEL"`（而非只斷言有例外）同時涵蓋了任務 1.7：
    底層解析器對這些輸入拋出的例外型別各不相同——空 bytes 是 ValueError、
    亂數位元組是 ModuleNotFoundError——能斷言到這個 code，就證明它們全都
    被 `_validate_stl_bytes()` 的 `except Exception` 收攏並轉換成 APIError，
    沒有任何一種以未處理的內部錯誤形式洩漏出去。
    """
    with pytest.raises(APIError) as excinfo:
        _validate_stl_bytes(content, "model")

    assert excinfo.value.code == "INVALID_MODEL"


# ── 兩個必須通過的案例 ──────────────────────────────────────────────────────


def test_zero_area_facet_is_accepted():
    """1.2：單一零面積三角面 SHALL 通過驗證。

    這一筆記錄的是現行行為，不是理想行為。驗證的語意只有「可解析」與
    「非空網格」，退化三角形兩項都滿足。改用 process=False 之後這裡
    MUST 仍然通過——本變更不得收緊判定範圍。
    """
    _validate_stl_bytes(zero_area_facet_stl(), "model")


def test_valid_single_triangle_is_accepted():
    """1.6：一份最小的有效二進位 STL SHALL 通過驗證。

    前面的案例全在證明「什麼會被擋下來」，這一筆證明擋下來的不是全部——
    少了它，一個永遠拋錯的實作也能讓整份測試檔通過。
    """
    _validate_stl_bytes(valid_single_triangle_stl(), "model")
