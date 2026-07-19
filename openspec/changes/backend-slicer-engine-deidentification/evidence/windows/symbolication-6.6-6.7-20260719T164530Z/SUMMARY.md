# Windows symbolication / loss / rollback ??tasks 6.6??.7

**Verdict嚗?* FAIL  
**engine_build_id嚗?* `20260719T162525Z`  
**PE RSDS GUID嚗?* `31CD05E0-C5CB-4F3B-8B98-6AC7F66B7F73`  
**PDB GUID嚗?* `` 繚 **match嚗?* False  
**Drill store嚗?* `D:\Repos\Phrozen\Bundle\web_slicer_core\openspec\changes\backend-slicer-engine-deidentification\evidence\windows\symbolication-6.6-6.7-20260719T164530Z\symbol-store-mirror\windows\20260719T162525Z`  
**OneDrive upload嚗?* `C:\Users\spd_y\OneDrive - 普羅森科技股份有限公司\Software Team\軟體測試\安裝檔\WebSlicer\Dental Center Core\slicer-engine-symbols\windows\20260719T162525Z`  
**Symbol loss (missing build_id)嚗?* detected=True  
**Rollback prior嚗?* `20260719T095415Z` present=True  
**QA segfault exit嚗?* -1073741819

## Method

1. Read RSDS GUID from `slicer_core.dll` via dumpbin /HEADERS.  
2. Parse matching GUID from archived `slicer_core.pdb`.  
3. Stage `symbol-store-mirror/windows/<build_id>/` and optionally sync to OneDrive store.  
4. 6.7a嚗ookup missing build_id ??fail.  
5. 6.7b嚗rior OneDrive `<build_id>` still present for rollback.  
6. QA `BUNDLE_QA_CRASH_MODE=segfault` non-zero exit (input for future WinDbg sessions).

PDB-free consumer `bin/` unchanged; symbols never copied into Setup.
