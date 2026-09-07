## Why

診所同機多帳號會對切片核心並行下指令。現行 `BackgroundTasks` 可同時觸發多個 Prusa／engine 作業，結果可能互踩或串到錯誤的 `job_id`。本 change 對齊權威規格 `improve-multi-account-local-backends` 的 S-lite：全域 FIFO，不新增順位欄位與 cancel。

## What Changes

- 同一行程內，切片、找支撐、挖空、切割、ortho pipeline 等 engine 作業進入**單一全域佇列**，FIFO 執行。
- 同時 running 的 engine job ≤ 1。後到者維持既有 `pending`，前者結束後才變 `processing`。
- 結果仍依既有 `job_id` 查詢；不新增排隊順位 API、不新增 cancel。

## Capabilities

### New Capabilities

- `slicer-engine-job-queue`：全域 FIFO，避免多帳號 engine 指令並行互踩，結果不串帳。

### Modified Capabilities

- （無）既有 job 狀態契約不改形狀。

## Impact

- `agent/jobs.py`、`agent/ortho_pipeline.py`、呼叫 `BackgroundTasks.add_task` 的路徑行為變為排隊後執行。
- `GET /api/jobs/{job_id}` 與 v2 狀態查詢維持。
- 單一連線舊切片路徑應仍可完成。
