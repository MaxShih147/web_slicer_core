# 工時估算（草案）

**Change：** `backend-slicer-engine-deidentification`  
**定案：** **L2 必須**（含 L1）；**macOS + Windows 皆必過**；L2 手段＝**精簡版 C′**；流水線＝**D13**  
**日期：** 2026-07-19（晚：Win post-sign Setup 驗收）

## 里程碑拆分

| 里程碑 | 內容 | 粗估（工程人日） | 狀態／備註 |
|--------|------|------------------|------------|
| M0 | 命名／schema／黑名單／Legal | 1–3 | 命名＋schema 已簽；Legal 未完 |
| M1 | 雙平台 PoC | 4–8 | **關閉 PASS** |
| M2 | L1 改名＋Win ABI | 5–10 | **雙平台大部完成**（含 5.3） |
| M3 | Launcher 組包／驗證／簽署／gate | 4–8 | **Win unsigned＋post-sign lifecycle 已關**；macOS Launcher 待 |
| M4 | C′ strip／thread／export／symbol store | 3–7 | **雙平台 C′ 大部關閉**；5.5／5.1b 待 |
| M4b | L3 | 5–15+ | 本版不做 |
| M5 | AGPL＋雙平台正式驗收 | 3–7 | Win 7.5 手動部分完成；其餘未開始 |

## 重估指引

| 觀察 | 影響 |
|------|------|
| Win post-sign Setup PASS | M3 Win 主線關閉；剩餘＝macOS Launcher／公證 |
| CLI help `PrusaSlicer` 殘留 | 小修（`PrintConfig.cpp`）＋重編重包；約 0.5–1 日 |
| 僅 Setup 簽章 | 若產品要求內嵌 exe 亦簽，另加 Authenticode 工序 |

**剩餘合計（粗）：約 5–14 人日**（macOS Launcher、help 清理、5.5、Legal、§7）。  
**整體完成度：≈ 83%。**

## 建議本版合計

| 組合 | 合計粗估 |
|------|----------|
| M0–M5（L1+L2／C′） | 約 20–43 人日 ROM（大部已消耗） |
