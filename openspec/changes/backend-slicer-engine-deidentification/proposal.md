## 緣由

Local agent（`web_slicer_core`）經 **Bundle-Launcher** 打包後，SLA 切片引擎以獨立 CLI subprocess 執行（維持 AGPL 行程邊界）。正式包在安裝路徑、程序監看器，以及 **macOS DiagnosticReports**／**Windows 行程名、模組路徑、WER／傾印** 中，會暴露 `PrusaSlicer`、`com.prusa3d.slic3r`、`Slic3r::*` 等技術指紋。

與「基礎資安防護：避免用戶發現我們使用的技術」衝突。Max：OS 報錯勿顯示 Prusa。實測 mac stack 詳細，故必須做到 **L2（OS crash report 可讀指紋去品牌）**，且 **Win／macOS 雙平台皆要達標**。dll／exe／Mach-O **改名重包仍為必要基線**（L1）；L2 採 **精簡版 C′**（strip＋thread 名＋Win export），**不做**全面 namespace／OLLVM（屬 L3）。

本 change 類型為 **Feature**，不是 Bug／優化。

證據：`macOS_system_report.md`（抬頭 + stack 指紋；Parent=Python agent）。2026-07-17 實測正式 macOS 包未 strip（約 5 萬全域符號仍含 `Slic3r`）。

## 變更內容

- **L1（必要）：** Win dll／exe、mac Mach-O／CLI **改名重包**；macOS `codeSigningID`／Info.plist 與 Version、Win VERSIONINFO 去品牌；agent／Launcher 路徑雙平台同步（命名見 `naming-manifest.md`）。
- **L2／C′（必要）：** fork 完成可見性＋strip、**全部** thread call site、Win export／DLL ABI、RTTI／例外實測；Launcher 依 artifact manifest 只驗證＋簽署（D13）。動態驗收以 release-equivalent qa 為主，consumer 必過靜態＋inspection。
- **加深評估（L3／D／E）：** 全面 namespace、OLLVM、packer、Crash 攔截等 **不取代** A+B+C′；預設本版不產品化。
- **平台：** macOS 與 Windows **對等必驗**。
- **發布治理：** 最終簽署 artifact；pre／post_strip／post-sign hash；內部 symbols；CI fail-closed；AGPL／來源揭露義務。

## 非目標

- 前端資安深度審查、Chloe UI、海地交接、安裝流程簡化。
- 將 CLI 改為 in-process linking／FFI 或破壞 AGPL 邊界。
- 隱藏或移除 AGPL、copyright、修改聲明、Corresponding Source offer。
- 對有能力的逆向工程者保證無法辨識底層技術（L3）；本功能是特定產品與 OS diagnostics 表面的品牌指紋最小化，不是 confidentiality control。
- 全面 C++ namespace `Slic3r::`→`slice::`、OLLVM／控制流混淆、或以 `strings` 全面清品牌作為 L2 驗收。
- 在未完成評估與 release review 前導入 packer 或攔截系統 Crash Reporter。

## 能力範圍

### 新增能力

- `slicer-engine-deidentification`：後端切片引擎 L1+L2 去識別（雙平台）與加深技術評估準則。

### 修改之既有能力

- _（無既有 specs 專章；變更建置輸出、符號策略、Launcher 包版與 agent 路徑，不改切片 API 語意。）_

## 影響面

| 元件 | 影響 |
|------|------|
| **prusaslicer_fork／建置** | 檔名、ID／Version、**C′：strip／thread／Win export（L2）**；Win＋mac |
| **agent** | CLI 路徑／設定語意 |
| **Bundle-Launcher** | 雙平台組包、簽章／公證 |
| **AGPL／OSS compliance** | 維持 subprocess-only，並補齊修改後 Program 的 license、notice、exact source offer 與 legal sign-off |
| **前端／UI** | 非本 change |

## 工作定位

1. 標題：**後端切片引擎去識別：Prusa CLI 改名重包與 OS Crash Report 指紋屏蔽（L2／雙平台）**
2. 定案：**L1+L2 必須**；**Win+macOS 必須**；L2 手段＝**A+B+C′（精簡版 C）**
3. Vance 兩路：① 改名＝L1 必要；② L2＝**strip＋thread＋Win export**（非全面 namespace／OLLVM；後者屬 L3）
