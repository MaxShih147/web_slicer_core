# Task 2.7 — Golden output tolerance／performance budget（approved）

| Field | Value |
|-------|--------|
| **Decision** | **approved** |
| **Date** | 2026-07-19 |
| **Requirement** | REQ-DEID-014；`design.md` D12 |
| **Applies to** | tasks **7.6**（functional／performance regression） |
| **Approver** | Product／QA（session confirmation 2026-07-19） |

## 0. How to read the numbers vs the literature

| Layer | What it is | Authority |
|-------|------------|-----------|
| **A. Practice pattern** | Use golden／characterization comparison；do not require brittle exact equality when outputs are non-deterministic；use performance budgets／gates；prioritize smoke／risk-based suites | Published books、vendor docs、ISTQB glossary、engineering blogs cited in §2 |
| **B. Numeric constants** | size **±5%**；wall-clock **≤ baseline × 1.20**；7.6 **minimal matrix** as MUST | **Product／QA signed policy for this change only**（§1） |
| **C. Not claimed** | That any ISO／RFC／paper **mandates** the exact figures ±5% or +20% | — |

Section 2 only cites sources for **Layer A**. Layer B is recorded as an explicit product decision so 7.6 can be judged without re-negotiation.

---

## 1. Confirmed policy（寫死）

### 1.1 Output（golden tolerance）

| Rule | Value |
|------|--------|
| Bit-identical SHA-256 | **NOT required** |
| Output size band | within **±5%** of baseline size for the same fixture／success path |
| Exit codes | MUST match baseline semantics（success＝0；intentional failure＝non-zero） |
| Output presence | success path MUST produce expected artifact（at least `.sl1` for SLA export） |
| User-visible stderr／help | MUST NOT introduce blacklist brand tokens（e.g. `PrusaSlicer`） |
| Agent contract | `SLICER_ENGINE_BIN` launchable；job failure／crash semantics unchanged |

**Baseline note：** Compare against the **same de-identified consumer**（same fixture）， not upstream PrusaSlicer official binaries.

### 1.2 Performance budget

| Rule | Value |
|------|--------|
| Metric | wall-clock of the same success fixture on the same machine |
| Pass | `actual ≤ baseline × 1.20`（**+20%**） |
| Fail | exceeds +20%，or hang／timeout（timeout＝`max(baseline × 3, 10 min)`） |
| Recording | note cold／warm；record `engine_build_id`／post-sign hash |

### 1.3 Scope for task 7.6（this release）

| Tier | Status | Cases |
|------|--------|--------|
| **Minimal matrix** | **MUST** for 7.6 close | (1) `--help`／`--help-fff`；(2) missing／invalid input；(3) `--export-sla` + fixed fixture（extend 3.6 job `5731d266` class）；(4) optional packaged agent → engine smoke |
| **acceptance-procedure §6 extended** | **SHOULD／後補** | generate-supports、hollow／drill、cut、3MF、timeout／cancel、full install→slice→uninstall |

Both macOS and Windows MUST run the **same minimal matrix**；platform deltas are recorded in evidence only.

### 1.4 Evidence expectations

- Artifact under test＝**signed consumer**（mac：DMG／app `…2111` engine；Win：post-sign Setup install tree）
- Per case：fixture hash、exit、duration、output size、PASS／FAIL
- Suggested paths：`evidence/macos/.../functional-7.6-...`、`evidence/windows/.../functional-7.6-...`

---

## 2. Cited practice basis（文獻／正規實務；不含自行推估）

### 2.1 Project requirements（normative for this repo）

| Citation | Bibliographic note | What the text requires（paraphrase of in-repo MUST） |
|----------|---------------------|------------------------------------------------------|
| OpenSpec `REQ-DEID-014` | `openspec/changes/backend-slicer-engine-deidentification/specs/slicer-engine-deidentification/spec.md` | De-id MUST NOT change API contract、exit semantics、file format、or acceptable slice results；MUST run golden／integration regression；**performance degradation threshold MUST be signed off before implementation** |
| OpenSpec D12 | `design.md` § D12 | Both platforms need golden／integration regression；**output tolerance and performance budget MUST be signed after PoC** |
| Acceptance §6 | `acceptance-procedure.md` §6 | Lists full functional regression surfaces；states tolerances／perf gates MUST be signed（task 2.7） |
| Prior smoke evidence | `evidence/macos-productize-5.2-3.5-3.6.md` | Documents prior macOS help／fail／`--export-sla`→`.sl1` sample（feeds minimal matrix design） |

### 2.2 Non–bit-identical golden／characterization（supports §1.1 “SHA not required”）

| # | Citation | Type | Verifiable statement from the source | Maps to our policy |
|---|----------|------|--------------------------------------|--------------------|
| R1 | Michael C. Feathers,《Working Effectively with Legacy Code》, Prentice Hall, 2005, ISBN-13: 978-0131177055 | Book（primary） | Introduces **characterization tests**：tests that document **actual** current behavior so changes that alter behavior are detected（see also Feathers’ later notes on characterization testing） | 7.6 compares against a recorded baseline of the de-id consumer’s actual outputs／exit codes—not against a wishful “perfect” upstream binary |
| R2 | Michael Feathers, “Characterization Testing”, personal essay — https://michaelfeathers.silvrback.com/characterization-testing | Author primary | Characterization testing documents what the system **actually does**; purpose is not to assert wished-for behavior | Same as R1 |
| R3 | “Characterization test”, Wikipedia — https://en.wikipedia.org/wiki/Characterization_test | Secondary summary of R1＋community practice | States characterization／Golden Master testing depends on repeatability；**“Volatile and non-deterministic values need to be masked/removed”** from both golden master and current result, or the technique becomes impractical | Justifies **NOT requiring bit-identical SHA** when outputs may contain volatile fields；compare stable properties instead |
| R4 | ApprovalTests（Java）documentation, “Scrubbers” — https://github.com/approvals/ApprovalTests.Java/blob/master/approvaltests/docs/Scrubbers.md | Widely used approval／golden tooling | Documents **scrubbers** that replace non-deterministic values（GUIDs、dates、etc.）before approval comparison so tests are reproducible | Same pattern：do not fail solely because unstable bytes differ；compare scrubbed／stable criteria |
| R5 | GoogleTest floating-point docs — https://google.github.io/googletest/reference/assertions.html （also Advanced topics discussing why naive exact equality fails for floats） | De-facto unit-test standard library | Provides `EXPECT_NEAR`／ULP-based approximate equality because **exact equality is often inappropriate** for real-valued results | Supports the *practice* of **tolerance bands** instead of exact equality when comparing continuous／noisy quantities（we apply an analogous relative size band in §1.1 as product policy） |

**Explicit non-claim：** R1–R5 do **not** prescribe “±5% of file size”. The ±5% figure is §1 Layer B（product-approved constant）.

### 2.3 Performance budgets／gates（supports §1.2 “budget before ship”）

| # | Citation | Type | Verifiable statement from the source | Maps to our policy |
|---|----------|------|--------------------------------------|--------------------|
| R6 | Addy Osmani, “Start Performance Budgeting” — https://addyosmani.com/blog/performance-budgets/ | Industry practice（Google Chrome／web performance advocacy） | Defines a **performance budget** as a limit the team is not allowed to exceed（examples include load-time thresholds and size thresholds） | We set an explicit wall-clock budget relative to baseline before judging 7.6 |
| R7 | web.dev, “Performance budgets 101” — https://web.dev/articles/performance-budgets-101 | Google web.dev documentation | “A performance budget is a set of limits imposed on metrics that affect site performance”；budgets are defined early as a decision reference | Same：2.7 must exist before 7.6 PASS／FAIL |
| R8 | Netflix Technology Blog, “Fixing Performance Regressions Before they Happen” — https://netflixtechblog.com/fixing-performance-regressions-before-they-happen-eab2602b86fe | Production eng. case study | States that identical code／tests **do not** return identical metrics in practice；**background noise** exists（CPU、GC、network、etc.）and must be filtered／accounted for when detecting regressions | Justifies a **non-zero** allowed delta vs baseline（otherwise single-run noise fails the gate）. Does **not** prescribe +20% |
| R9 | Criterion.rs user guide（Rust benchmarking）— https://bheisler.github.io/criterion.rs/book/ （statistical comparison／significance） | Widely used benchmark harness | Documents that CI／shared machines are noisy and recommends **statistical** comparison rather than naive single-run equality | Reinforces R8：performance gates need noise-aware policy；our +20% single-run relative band is a **simpler product-chosen** gate for E2E wall-clock（not a Criterion default） |

**Explicit non-claim：** R6–R9 do **not** prescribe “+20% wall-clock”. The +20% figure is §1 Layer B（product-approved constant）, chosen as this change’s release gate.

### 2.4 Smoke／risk-based scope（supports §1.3 “minimal matrix MUST”）

| # | Citation | Type | Verifiable statement from the source | Maps to our policy |
|---|----------|------|--------------------------------------|--------------------|
| R10 | ISTQB Glossary — **risk-based testing** — https://glossary.istqb.org/ （term: risk-based testing）；also mirrored definitions in ISTQB glossary PDFs | International testing body glossary | Risk-based testing：approach that uses identified **product risk levels to guide the test process**（reduce product risk／inform stakeholders） | 7.6 MUST scope is prioritized to highest-risk surfaces for *this* change（CLI contract／exit／SLA export）， with §6 remainder deferred as SHOULD |
| R11 | ISTQB Glossary — **smoke test** — https://glossary.istqb.org/ （term: smoke test）；Expert-level glossary PDF wording also: a subset covering main functionality to check crucial functions work before deeper testing | International testing body glossary | Smoke test＝suite covering **main functionality** to determine the build works properly **before planned deeper testing** | §1.3 “minimal matrix” is the smoke／intake gate for 7.6；§6 extended list remains planned deeper coverage（SHOULD／後補） |

**Explicit non-claim：** ISTQB does not list our four CLI cases. Case selection is product／QA scope under R10–R11 patterns, aligned with existing 3.6 smoke evidence（§2.1）.

### 2.5 Bibliography（copy-paste stable）

1. Feathers, M. C. (2005). *Working Effectively with Legacy Code*. Prentice Hall. ISBN 978-0131177055.  
2. Feathers, M. “Characterization Testing”. https://michaelfeathers.silvrback.com/characterization-testing  
3. Wikipedia contributors. “Characterization test”. https://en.wikipedia.org/wiki/Characterization_test  
4. ApprovalTests. “Scrubbers”. https://github.com/approvals/ApprovalTests.Java/blob/master/approvaltests/docs/Scrubbers.md  
5. GoogleTest. “Assertions Reference”／floating-point comparison. https://google.github.io/googletest/reference/assertions.html  
6. Osmani, A. “Start Performance Budgeting”. https://addyosmani.com/blog/performance-budgets/  
7. web.dev. “Performance budgets 101”. https://web.dev/articles/performance-budgets-101  
8. Netflix Technology Blog. “Fixing Performance Regressions Before they Happen”. https://netflixtechblog.com/fixing-performance-regressions-before-they-happen-eab2602b86fe  
9. Criterion.rs Book. https://bheisler.github.io/criterion.rs/book/  
10. ISTQB. *Standard Glossary of Terms Used in Software Testing* — entries **risk-based testing**, **smoke test**. https://glossary.istqb.org/  
11. In-repo：`REQ-DEID-014`、`design.md` D12、`acceptance-procedure.md` §6、`evidence/macos-productize-5.2-3.5-3.6.md`

---

## 3. Sign-off

| Role | Name／note | Date | Result |
|------|------------|------|--------|
| Product／QA | Confirmed in working session（輸出 ±5%＋非 bit-identical；效能 +20%；7.6＝最小矩陣） | 2026-07-19 | **approved** |
| Backend | — | — | noted／optional |

After this file exists, task **2.7** is closed for gating **7.6**. Execute 7.6 against §1； do not re-negotiate Layer B numbers mid-run without a new approved revision of this document.
