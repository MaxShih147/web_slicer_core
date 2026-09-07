## Context

權威規格在 `WebSlicer_PrinterControl` 的 `improve-multi-account-local-backends`。本目錄為 companion。提出者 Vance。S-lite：全域 FIFO，無順位／cancel。

## Goals / Non-Goals

**Goals:** 同進程 engine 作業序列化；`job_id` 結果不交叉。

**Non-Goals:** 排隊順位欄位、cancel／終止 Prusa、每帳號佇列、有限並行。

## Decisions

- 以行程內 `asyncio.Lock`（等待者 FIFO）包住 engine job 進入點，取得鎖之前不把 status 改成 `processing`。
- 進入點：`run_slicing`、`run_support_generation`、`run_hollow_generation`、`run_cut_operation`、`run_ortho_pipeline`。不包 `run_prusa_cli`（會與上層雙鎖死結）。
- 不改 HTTP 契約形狀。
