# dev-interface

web_slicer_core 的輕量化開發測試前端。RD 內部用。

用途：改完 slicer core（PrusaSlicer fork）之後，用最短路徑看見支撐產生的結果。

架構細節、API 契約、擴充方式見 [SPEC.md](SPEC.md)。

---

## 啟動

### 1. 先啟動 agent

在 `web_slicer_core` 根目錄：

```bat
scripts\run_agent.bat
```

Agent 跑在 `https://127.0.0.1:5179`。它需要 `slicer-engine.exe` 已經建置完成。

### 2. 啟動 dev-interface

```bat
cd dev-interface
npm install
npm run dev
```

開 <http://localhost:5180>。

不用處理憑證警告，也不用管 CORS。Vite proxy 已經處理掉了。

---

## 操作

1. **選擇 STL 檔案** — 模型出現在場景，藍色。
2. **調整支撐參數** — 六個數值，滑鼠移到標籤上有說明。
3. **按「產生支撐」** — 支撐出現，橘紅色。面板顯示耗時與 jobId。
4. **下載 support.stl** — 想丟去別的軟體比對時用。

視角操作：**左鍵旋轉．滾輪縮放．右鍵位移**。

---

## 工作迴圈

```
改 slicer core → 重新 build → 重啟 agent → 按「重新產生支撐」→ 看結果
```

STL 留在記憶體。重新產生不用重選檔案。

---

## 常見狀況

| 現象 | 原因 | 處理 |
|---|---|---|
| 面板顯示「agent 未連線」 | agent 沒跑 | 執行 `scripts\run_agent.bat` |
| 黃色提示 SUPPORT_NOT_NEEDED | 模型自撐，後端沒產生支撐柱 | 這是正常結果，不是錯誤。調小臨界角度或換模型 |
| 紅色 `[JOB_FAILED]` | slicer-engine 執行失敗 | 看 agent console 的錯誤輸出 |
| 紅色 `[JOB_TIMEOUT]` | 超過 120 秒還沒完成 | 模型太大，或 engine 卡住 |
| 支撐和模型錯位 | 後端座標系 bug | 不要在前端補位移，見 SPEC.md 第 7 節 |

---

## 這個工具不做的事

不做完整切片、不做層預覽、不上雲端、沒有測試。

需要那些請用 `web/`（v1 API，完整切片流程）或 DS-Online。

理由見 [SPEC.md](SPEC.md) 第 1 節。
