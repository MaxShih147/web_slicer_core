# 工時估算（草案）

**Change：** `backend-slicer-engine-deidentification`  
**定案：** **L2 必須**（含 L1）；**macOS + Windows 皆必過**；L2 手段＝**精簡版 C′**；流水線＝**D13**（fork strip；Launcher 只驗證＋簽署）  
**日期：** 2026-07-17（C′／D13 定案；**M1 macOS PoC 關閉後更新**）

## 里程碑拆分

| 里程碑 | 內容 | 粗估（工程人日） | 狀態／備註 |
|--------|------|------------------|------------|
| M0 | 命名／artifact-manifest schema／黑名單／Legal 輸入 | 1–3 | **部分完成**：命名＋schema 已簽核；Legal／Win baseline 未完 |
| M1 | 可行性＋雙平台 PoC（含 **未 strip vs strip** `.ips` 對照）＋scanner 原型 | 4–8 | **macOS 已關閉（PASS）**；Windows PoC 仍缺 → 剩餘約 2–4 日量級 |
| M2 | L1 改名重包 + ID／Version + Win shim／export ABI | 5–10 | 未開始（PoC 已證明 macOS 改名可行） |
| M3 | Bundle-Launcher 雙平台組包／驗證／簽署／final gate（**不**二次 strip） | 4–8 | 未開始 |
| M4 | **C′：visibility＋strip＋全部 thread＋Win export＋symbol store** | **3–7** | macOS flags 已定案（2.2）；產品化＋Win 未做 |
| M4b | （可選）C-full／OLLVM／packer | 5–15+ | **L3；本版不做** |
| M5 | AGPL evidence、雙平台驗收 | 3–7 | 未開始 |

## M1 完成後重估（±25% 指引）

| 觀察 | 對後續影響 |
|------|------------|
| macOS C′ 可達 L2（乾淨環境） | M4 macOS 風險下降；重點轉 dSYM 隔離＋manifest＋殘餘 nm |
| `strip -x` 否決；須 visibility＋plain `strip` | 已寫入 2.2／design；避免返工 |
| dSYM／UUID 符號污染 | 驗收／CI 必須「無同 UUID 符號」；加 0.5–1 日自動化防呆 |
| Exception site 需 `noexcept`／abort 路徑 | harness 設計已有解；compile-time 化仍在 M4／5.6 |
| Windows 未測 | **最大剩餘不確定性**；勿壓縮 M1 剩餘／M2 Win 緩衝 |

**剩餘合計（粗）：** 在原 20–43 人日中，已消耗約 M0 部分＋M1 macOS；建議剩餘 **約 16–35 人日**（視 Win baseline／公證／Legal），待 2.5 後再縮窄。

## 建議本版合計

| 組合 | 合計粗估 |
|------|----------|
| **M0+M1+M2+M3+M4+M5**（L1+L2／C′ 雙平台） | **約 20–43 人日**（ROM；M1 macOS 已完成） |
| 含 M4b（L3） | 再視評估追加（本版預設不加） |

## 風險緩衝

| 項目 | 影響 |
|------|------|
| Win shim／export 原子遷移 | M2／M4 +1–3 日 |
| Windows baseline 未收集 | 阻塞 Win L2 |
| 公證／Authenticode | M3 +1–2 日 |
| Legal／OSS source-offer 流程尚未建立 | M0／M5 +1–3 日 |
| CI 無 mac／win final artifact runner | M3／M5 +2–5 日 |
| Strip 後內部 symbolication 流程未就緒 | M4／M5 +1–2 日 |
| 同 UUID dSYM 污染導致假 FAIL／假洩漏 | 驗收腳本須隔離（PoC 已證） |

## 假設與 staffing

- 至少包含 Backend／C++、Release Engineering、Windows build、QA Automation、Security、Legal／OSS owner。
- macOS architecture 以實際發行矩陣計；仍發布 x86_64 時必須另產一份動態驗收紀錄。
- **不含**全面 C++ namespace refactor、OLLVM、packer／anti-tamper 產品化。

## 非本估算範圍

前端、UI、安裝流程、海地交接、L3 產品化。
