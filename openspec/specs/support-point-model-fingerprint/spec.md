# support-point-model-fingerprint Specification

## Purpose
定義支撐點清單所攜帶的模型指紋契約：指紋由哪些幾何量構成、對 `ModelObject` 原始網格計算而不套用 instance 變換、量化門檻（0.1 µm）為何足以吸收浮點格式化誤差、指紋涵蓋與不涵蓋的變動範圍，以及匯入時比對不符須直接拒絕而非降級為自動生成。

## Requirements

### Requirement: 匯出的支撐點清單須攜帶模型指紋

匯出的 JSON SHALL 於頂層攜帶一枚模型指紋。指紋 SHALL 描述產生這批支撐點的那份模型，使匯入端能判定點清單是否仍然對應同一份幾何。

#### Scenario: 匯出檔案含指紋
- **WHEN** 執行支撐點匯出
- **THEN** 匯出 JSON SHALL 含 `model_fingerprint` 欄位
- **AND** 該欄位 SHALL 含面數、包圍盒與頂點校驗和三個組成部分

### Requirement: 指紋須由幾何量構成並對原始網格計算

指紋 SHALL 由三角面數、量化後的包圍盒（min 與 max，量化至 0.1 µm）以及量化後的頂點座標校驗和構成。計算 SHALL 針對 `ModelObject` 的原始網格頂點，MUST NOT 套用任何 instance 變換。系統 MUST NOT 以上傳檔案的位元組雜湊作為指紋。

#### Scenario: 指紋不受排版影響
- **GIVEN** 同一份模型
- **WHEN** 分別以不同的 `center` 參數執行匯出
- **THEN** 兩次產生的指紋 SHALL 完全相同

#### Scenario: 未變動的模型重新匯出指紋一致
- **GIVEN** 同一份未經任何修改的模型網格
- **WHEN** 重複執行匯出兩次
- **THEN** 兩次產生的指紋 SHALL 完全相同

### Requirement: 匯入時須比對指紋並在不符時拒絕

匯入支撐點清單時，系統 SHALL 對當前模型重新計算指紋並與 JSON 中攜帶的指紋比對。不符時系統 SHALL 拒絕載入並終止，MUST NOT 繼續生成支撐。系統 MUST NOT 在指紋不符時降級為自動生成支撐點，亦 MUST NOT 靜默套用錯位的支撐點。

#### Scenario: 指紋相符時正常執行
- **GIVEN** 一份支撐點 JSON 與產生它的同一份模型
- **WHEN** 執行 `--import-support-points` 並生成支撐
- **THEN** 支撐 SHALL 正常生成

#### Scenario: 指紋不符時拒絕
- **GIVEN** 一份支撐點 JSON 與一份不同的模型
- **WHEN** 執行 `--import-support-points`
- **THEN** 系統 SHALL 終止並回報模型不一致
- **AND** MUST NOT 產生任何支撐網格或切片輸出

#### Scenario: 不得降級為自動生成
- **GIVEN** 指紋不符的情境
- **WHEN** 執行 `--import-support-points`
- **THEN** 系統 MUST NOT 改以自動偵測產生支撐點後繼續切片

### Requirement: 指紋須能偵測所有會使支撐點失準的模型變動

指紋 SHALL 對**任何使原始網格幾何改變的操作**產生不同的值：頂點平移、旋轉、縮放，以及任何改變網格面數或頂點座標的操作（包含以編輯網格方式實作的挖空與打孔）。

指紋僅對 `ModelObject` 的原始網格計算，**不涵蓋以參數／管線步驟實作、不改動原始網格的操作**。本 fork 的 `hollowing_enable` 與 drain hole 屬於後者：它們是 `slaposHollowing` / `slaposDrillHoles` 的管線設定，`ModelObject::mesh()` 不變，因此指紋亦不變。此為刻意的界線——挖空只改內部，外表面不動，既有支撐點仍然貼合；界線之外的風險（打孔可能落在支撐點位置上）由孔洞編輯流程自行負責，不由指紋承擔。

#### Scenario: 平移被偵測
- **GIVEN** 一份模型與其匯出的支撐點 JSON
- **WHEN** 將模型的所有頂點沿 X 軸平移 5 mm 後嘗試匯入該 JSON
- **THEN** 指紋比對 SHALL 判定不符

#### Scenario: 旋轉被偵測
- **WHEN** 將模型的所有頂點繞 Y 軸旋轉 15 度後嘗試匯入原 JSON
- **THEN** 指紋比對 SHALL 判定不符

#### Scenario: 縮放被偵測
- **WHEN** 將模型的所有頂點縮放為 1.1 倍後嘗試匯入原 JSON
- **THEN** 指紋比對 SHALL 判定不符

#### Scenario: 使原始網格面數改變的操作被偵測
- **WHEN** 對模型執行任何使原始網格面數改變的操作（例如以編輯網格方式實作的挖空或打孔）後嘗試匯入原 JSON
- **THEN** 指紋比對 SHALL 判定不符

#### Scenario: 不改動原始網格的參數式操作不影響指紋
- **GIVEN** 同一份模型，其 `ModelObject::mesh()` 未被改動
- **WHEN** 僅開啟 `hollowing_enable` 之類的管線參數後重新匯出
- **THEN** 指紋 SHALL 維持不變
- **AND** 既有的支撐點 SHALL 仍可匯入

#### Scenario: 對稱模型的一百八十度旋轉被偵測
- **GIVEN** 一份繞 Z 軸旋轉 180 度後包圍盒與面數皆不變的對稱模型
- **WHEN** 旋轉後嘗試匯入原 JSON
- **THEN** 頂點校驗和 SHALL 使指紋比對判定不符

### Requirement: 指紋量化門檻須容忍浮點格式化誤差

量化門檻 SHALL 為 0.1 µm（小數第 4 位）。此門檻 SHALL 遠低於任何實際列印解析度，同時 SHALL 足以吸收同一網格重複匯出時可能產生的浮點格式化差異，避免誤判作廢。

#### Scenario: 最低有效位差異不造成誤判
- **GIVEN** 兩份幾何相同、但部分頂點座標相差單一 float 最低有效位的網格
- **WHEN** 分別計算指紋
- **THEN** 兩者的指紋 SHALL 相同

#### Scenario: 超過門檻的差異被判定不符
- **GIVEN** 兩份網格，其中一份的單一頂點沿 X 軸位移 1 µm
- **WHEN** 分別計算指紋
- **THEN** 兩者的指紋 SHALL 不同
