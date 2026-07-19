# 工時估算（草案）

**Change：** `backend-slicer-engine-deidentification`  
**定案：** **L2 必須**（含 L1）；**macOS + Windows 皆必過**；L2 手段＝**精簡版 C′**；流水線＝**D13**  
**日期：** 2026-07-19（夜：≈92–94%；mac 晚上 consumer 已回灌 `…2111`）

## 里程碑拆分

| 里程碑 | 內容 | 粗估（工程人日） | 狀態／備註 |
|--------|------|------------------|------------|
| M0 | 命名／schema／黑名單／Legal | 1–3 | 命名＋schema＋**1.6 Legal approved**；缺 1.5 Security |
| M1 | 雙平台 PoC | 4–8 | **關閉 PASS** |
| M2 | L1 改名＋Win ABI | 5–10 | **雙平台完成**（CLI 簽過包雙平台已清） |
| M3 | Launcher 組包／驗證／簽署／gate | 4–8 | **雙平台手動閉環**（含 mac 晚上回灌）；CI／mac 4.6 待 |
| M4 | C′ strip／thread／export／symbol store | 3–7 | **雙平台 C′ 關閉**；5.5 Win＝OneDrive＋mac drill；演練／5.1b 待 |
| M4b | L3 | 5–15+ | 本版不做 |
| M5 | AGPL＋雙平台正式驗收 | 3–7 | §6＋1.6＋雙平台 legal／Win 7.3 已關；**7.6 SLA／7.4–7.5 CI 未** |

## 重估指引

| 觀察 | 影響 |
|------|------|
| 雙平台 Launcher §4 手動 PASS＋mac 晚上回灌 | M3 主線關閉；剩餘＝CI／mac 4.6 |
| ~~CLI help~~／~~Legal 1.6~~／~~mac legal 回灌~~ | **已關** |
| 僅 Setup 簽章 | 若產品要求內嵌 exe 亦簽，另加 Authenticode 工序 |

**整體完成度：≈ 92–94%**（mac 回灌已關；主殘留 §7.6／CI）。  
**剩餘合計（粗）：約 2–6 人日**（§7 SLA／CI、resources、mac 4.6、1.5、演練）。

## 建議本版合計

| 組合 | 合計粗估 |
|------|----------|
| M0–M5（L1+L2／C′） | 約 20–43 人日 ROM（大部已消耗） |
