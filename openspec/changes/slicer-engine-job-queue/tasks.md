## 1. 全域 FIFO

- [x] 1.1 Write tests for 全域 FIFO：A running 時 B pending；同時 running engine ≤ 1；job_id 結果不串帳；單 job 回歸成功
- [x] 1.2 實作單一佇列串行 `run_slicing`／supports／hollow／cut／ortho 等 engine 任務
- [x] 1.3 確認不新增 cancel、不新增順位欄位；既有 `GET /api/jobs/{job_id}` 仍可用
