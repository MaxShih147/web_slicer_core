# 工時估算（草案）

**Change：** `backend-slicer-engine-deidentification`  
**定案：** **L2 必須**（含 L1）；**macOS + Windows 皆必過**；L2 手段＝**精簡版 C′**；流水線＝**D13**（fork strip；Launcher 只驗證＋簽署）  
**日期：** 2026-07-17（晚：macOS 產品化進度更新）

## 里程碑拆分

| 里程碑 | 內容 | 粗估（工程人日） | 狀態／備註 |
|--------|------|------------------|------------|
| M0 | 命名／artifact-manifest schema／黑名單／Legal 輸入 | 1–3 | **部分完成**：命名＋schema 已簽核；Legal 未完；Win baseline **已關閉** |
| M1 | 可行性＋雙平台 PoC（含 **未 strip vs strip** `.ips` 對照）＋scanner 原型 | 4–8 | **雙平台已關閉（PASS）**：macOS 2.4＋Windows 2.5／2.6 PoC |
| M2 | L1 改名重包 + ID／Version + Win shim／export ABI | 5–10 | **macOS 大部完成**（3.1／3.2／3.4）；Win 正式 export=1／組包路徑 → **5.3／§4** |
| M3 | Bundle-Launcher 雙平台組包／驗證／簽署／final gate（**不**二次 strip） | 4–8 | **未開始**（macOS post-strip manifest 本機樣品已有；正式交接＋Win 仍缺） |
| M4 | **C′：visibility＋strip＋全部 thread＋Win export＋symbol store** | **3–7** | **macOS 5.1 流水線已落地**（nm≈172 未收斂；5.2／5.5 待）；Win **5.3** 未做 |
| M4b | （可選）C-full／OLLVM／packer | 5–15+ | **L3；本版不做** |
| M5 | AGPL evidence、雙平台驗收 | 3–7 | 未開始 |

## M1 完成後重估（±25% 指引）

| 觀察 | 對後續影響 |
|------|------------|
| macOS C′ 可達 L2（乾淨環境） | M4 macOS 風險下降；重點轉殘餘 nm＋thread 全站稽核＋正式 CI |
| Windows PoC PASS（2.5） | Win ABI／VERSIONINFO／PDBALTPATH／三 crash **已證明**；剩餘最大項＝**export 收斂為 1（5.3）**＋正式組包 |
| `strip -x` 否決；須 visibility＋plain `strip` | 已寫入 2.2／design；避免返工 |
| dSYM／UUID 符號污染 | 驗收／CI 必須「無同 UUID 符號」；加 0.5–1 日自動化防呆 |
| compile-time harness（2.6 PoC） | 機制已落地；consumer OFF 稽核＋qa_delta manifest → 5.6／5.7 |
| LocalDumps 不穩（Win） | 正式 WER runbook 需加強；PoC 已用 cdb 等價取證 |
| macOS D13 package（2026-07-17） | manifest／strip／codesign 產品化已通；殘餘 nm≈172 仍卡 5.1 收斂 |

**剩餘合計（粗）：** 已消耗 M0 部分＋**M1 雙平台**＋**M2／M4 macOS 大部**；建議剩餘 **約 10–24 人日**（視 nm 收斂／export=1／公證／Legal）。

## 建議本版合計

| 組合 | 合計粗估 |
|------|----------|
| **M0+M1+M2+M3+M4+M5**（L1+L2／C′ 雙平台） | **約 20–43 人日**（ROM；**M1 雙平台已完成**） |
| 含 M4b（L3） | 再視評估追加（本版預設不加） |

## 風險緩衝

| 項目 | 影響 |
|------|------|
| Win export 清到 1（cereal mangled） | 5.3 可能吃掉 1–3 日 |
| AGPL／Legal | 可平行；不擋工程 PoC |
| Launcher 簽署／公證 | M3 緩衝勿砍 |
| 符號污染（macOS dSYM／Win PDB） | CI 防呆必要 |
