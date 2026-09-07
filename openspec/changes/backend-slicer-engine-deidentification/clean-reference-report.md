# 已知乾淨參考報告（Clean Reference Report）

**Status：** `approved`  
**對應 task：** 2.4b［REQ-DEID-006］  
**Change：** `backend-slicer-engine-deidentification`  
**用途：** [`blacklist.md`](./blacklist.md) §2.1 正向 diff／品牌歸因複核之 macOS 參考錨點  

---

## 批准

| 欄位 | 內容 |
|------|------|
| 批准日 | **2026-07-17** |
| 批准人 | **Vance** |
| 角色 | Backend／Product |
| 有效期 | 至正式 consumer Release 另立「簽署包」參考報告前有效；OS major 變更或 flags／strip 流程變更時 MUST 重批 |
| 適用範圍 | **macOS arm64 PoC／工程驗收 diff**；不取代正式雙平台簽署包 Gate 4 證據 |

---

## 參考產物

| 項目 | 值 |
|------|-----|
| Evidence run | `poc/evidence/m1-close-20260717T032408Z/` |
| OS | macOS 26.5.1 (25F80) |
| Arch | arm64 |
| Scanner verdict | **PASS**（`SCAN.json`） |
| 報告結論 | [`poc/REPORT.md`](./poc/REPORT.md) |

### Hash（SHA-256）

| 檔案 | sha256 |
|------|--------|
| `work/slicer-engine`（stripped consumer-like） | `632962c7ea9e550f71dc6ca97e5c74cc4282fe7533b4bb31efd00b1ec44cc59f` |
| `SCAN.json` | `2125ba094e067b29945d4b469bf4d245faefc2a77dd1ac89d8241e2ef86be5b9` |
| `SUMMARY.md` | `91e8b88a5666a2f70fca2e85ca2d4ba64e880342e97aa77d5b279faf7e58054c` |
| `ips/overflow.ips` | `ba00aa1b7c4061184f3fed5fdf4ee094f5e9c378c578b2eb14d263b252a9b67d` |
| `ips/segfault.ips` | `a5f990f5c98e3de0e455722c8340e412dd59b92a74ea379cc96d7d42f65888c7` |
| `ips/exception.ips` | `93efc79b5161a0359e64dd473695ce8884d6a47c371bb38e7c74f8ec52e23cdb` |

### 建立方式（必須可重現）

1. Fork 以 `-fvisibility=hidden -fvisibility-inlines-hidden` 建置 `slicer-engine`  
2. dSYM 封存後 plain `strip`；`codesign --identifier slicer-engine`  
3. 崩潰當下無同 UUID 可發現 dSYM／未 strip 複本（PoC 另以 LC_UUID patch 隔離快取）  
4. `BUNDLE_QA_CRASH_MODE=overflow|segfault|exception` 各產一份 `.ips`  
5. `poc/scan_macos_artifact.sh` → PASS  

### 參考報告預期特徵（diff 時不得因此 FAIL）

- `procName`／`codeSigningID` = `slicer-engine`  
- thread 名含 `slicer-worker`／`slicer-engine`  
- `Slic3r::` = 0、`slic3r_main` = 0、`prusaslicer` = 0  
- 主堆疊可為 **imageOffset only**（無品牌函式名）  

### 明確非本參考範圍

- Windows／WER（另見 tasks **2.5**／[`poc/REPORT-WIN.md`](./poc/REPORT-WIN.md)；本報告僅 macOS）  
- 已公證／Authenticode 的正式 Bundle 包  
- `nm` brand 歸零（PoC 殘餘 ≈172 屬 5.1）  

---

## 使用方式

後續 macOS 動態驗收：將新 `.ips` 與本目錄三份參考報告做正向 diff；僅**可歸因第三方品牌／來源**之新增殘留得判 FAIL（見 blacklist §2.1）。
