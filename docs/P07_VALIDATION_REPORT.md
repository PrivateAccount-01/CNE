# CNE Phase P0.7: Realistic Language & Shape Validation Report (Revision 3)

**Phase Status:** GO (Decision Gate Evaluated)  
**Execution Timestamp:** 2026-09-29T20:07:48Z  
**Total Queries Evaluated:** 1550 (Anchored Corpus) + 600 (Multi-Domain Blind Workload)  

---

## 1. Executive Summary & Decision Gate Outcome

Phase P0.7 rigorously validates the foundational architectural assumption of CNE: **do realistic queries cluster into reusable computational shapes?**

To eliminate circularity and prevent conflation, this evaluation cleanly separates:
1. **Preregistered Decision Gate Requirements (GO / NO-GO)**: Gating on surface-to-semantic stability, compiler convergence on supported topologies, adversarial invariance, hygiene, and co-measurement bounds.
2. **Exploratory Diagnostic Probes (Informational / P1 Charter)**: Probing unguided multi-domain workloads, novel shape emergence, slot extraction fidelity, and classification boundaries to inform Phase P1.

### Preregistered Gate Criteria (Phase Status: `GO`)

| Metric / Requirement | Target Specification | Empirical Result | Gate Status |
| :--- | :---: | :---: | :---: |
| **Prerequisite Measurement Hygiene (§4)** | Zero self-memo leak in Oracle | **Verified** (Dynamic runtime proof + Static ordering) | **PASS** |
| **Steady-State Trial Independence** | Decouple timing noise from state accumulation | **Verified** (Fresh 100% pre-warmed fabric per trial) | **PASS** |
| **Semantic Gold Topology Routing (§5)** | Conditional Routing Accuracy $\ge 90.0\%$ | **99.12%** (1,227 / 1,238 compiled) | **PASS** |
| **Compiler Coverage (§5.1)** | Transparent empirical disclosure | **80.9%** (1254/1550) | **DISCLOSED** |
| **Non-Trivial Shape Diversity $D(N)$ (§7)** | $D(N) \le 0.40$ | **0.0129** (16 shapes / 1237 queries) | **PASS** |
| **Cross-Batch Stability (§8)** | $\Delta D \le 0.05$, Jaccard $\ge 65\%$ | Jaccard = **68.8%**, $\Delta D$ = **0.0022** | **PASS** |
| **Adversarial Families Verification (§6.4)** | All 6 families (A1–A6) pass end-to-end | **6/6 Families Passed** | **PASS** |
| **Structural Outlier G0 Check (§5.2)** | 0 domain nodes, $\le 2$ new prims | **100% frozen primitives**, 0 new primitives | **PASS** |
| **Extended G1b Discrimination (§10.7)** | 7 topologies $\implies$ 7 distinct shapes | **7 distinct shape keys** | **PASS** |
| **Realistic Co-Measurement G2 ($R^*$)** | $R^* \ge 25.0\%$ | **99.37%** | **PASS** |
| **Realistic Co-Measurement G3 ($A_{\text{corpus}}$)**| $A_{\text{corpus}} \le 20.0\%$ | **8.37%** | **PASS** |
| **Realistic Co-Measurement Net Savings** | $\Delta C > 0$ | **+77.14 ms** | **PASS** |

### Exploratory Diagnostic Probes (Non-Gating Empirical Findings)

| Diagnostic Dimension | Scope / Method | Empirical Finding | Architectural Takeaway |
| :--- | :--- | :--- | :--- |
| **Multi-Domain Workload Rejection** | 600 unguided queries across 12 domains | **86.0% rejection** (516/600) | Unconstrained workloads heavily explore areas outside the 7-topology grammar. |
| **Novel Shape Emergence** | Compiled blind requests | **3 novel shapes** (42.9% of blind shapes) | Workloads naturally explore compositional variations not in hand-authored templates. |
| **Novel Shape Query Mass** | Ratio of novel requests to all compiled | **44/84 (52.4%)** | Measures true workload mass affected by structural novelty. |
| **Novel Shape Semantic Validity** | Independent audit of novel requests | **15.5% valid**, **36.9% misinterpreted** | Proves rule-based parser shoehorns unsupported requests into degenerate graphs. |
| **Effective Compilable Recall** | Expected vs actual compiled | **93.75%** (1244/1327) | Measures true percentage of compilable requests that survive compilation. |
| **Slot Extraction Fidelity** | Exact match across all extracted slots | **79.32%** accuracy | Primary focus for Phase P1 learned controller (1 in 5 slot extraction errors). |

### Decision Gate Verdict: `GO`

> **Narrowed Scientific Claim (§9)**:  
> *"The reuse assumption is supported under the tested synthetic linguistic distribution (LLM-generated paraphrases across >=3 independent batches, plus structured adversarial families). P0.7 demonstrates compiler convergence into parameterized semantic IR topologies; generalization to unconstrained open-world workload distributions remains untested until real user data is collected."*

---

## 2. Compiler Coverage & Semantic Gold Evaluation (§5.1, §5.2)

### Confusion Matrix Across Outcomes

| Actual \\ Predicted | COMPILED | UNSUPPORTED | AMBIGUOUS | LOW_CONFIDENCE |
| :--- | :---: | :---: | :---: | :---: |
| **COMPILED** | 1244 | 24 | 12 | 47 |
| **UNSUPPORTED** | 0 | 123 | 0 | 0 |
| **AMBIGUOUS** | 10 | 0 | 40 | 0 |
| **LOW_CONFIDENCE** | 0 | 0 | 0 | 50 |

### Precision, Recall, and F1 Metrics

| Outcome Class | Precision | Recall | F1 Score | Ground Truth Count |
| :--- | :---: | :---: | :---: | :---: |
| **COMPILED** | 99.2% | 93.8% | 96.4% | 1327 |
| **UNSUPPORTED_INTENT** | 83.7% | 100.0% | 91.1% | 123 |
| **AMBIGUOUS_INTENT** | 76.9% | 80.0% | 78.4% | 50 |
| **LOW_CONFIDENCE_MAPPING** | 51.5% | 100.0% | 68.0% | 50 |

* **Conditional Topology Routing Accuracy:** **99.12%** (among queries that successfully compiled, how often the intended topology was selected).
* **End-to-End Compilable Recall:** **93.75%** (1244/1327 expected-compilable queries successfully compiled).
* **Overall 4-Way Classification Accuracy:** **94.00%** across all 1,550 corpus items.
* **Slot Extraction Accuracy (Diagnostic):** **79.32%** exact match across all extracted slots. Acknowledged as a primary empirical motivation for Phase P1's learned controller.

---

## 3. Shape & Topology Diversity Metrics (§7)

Evaluated exclusively on the **covered non-trivial subset** (authentic LLM paraphrases across 3 models + structured adversarial families):

| Metric | Empirical Value | Specification Interpretation |
| :--- | :---: | :--- |
| **Diversity Ratio $D(N)$** | **0.0129** | Satisfies $D(N) \le 0.40$, reflecting structural reusability. |
| **Shape Entropy $H$** | **3.5371 bits** | Shannon entropy across active shapes ($H_{\max} = 4.0000$, normalized $H/H_{\max} = 0.8843$). |
| **Top-20 Shape Coverage $C_{20}$** | **100.0%** | Top 20 shapes account for 100.0% of all non-trivial executions. |
| **Recurrence Density $R_2$** | **100.0%** | Percentage of executions matching shapes observed $\ge 2$ times. |
| **Recurrence Density $R_5$** | **100.0%** | Percentage of executions matching shapes observed $\ge 5$ times. |
| **Recurrence Density $R_{10}$** | **100.0%** | Percentage of executions matching shapes observed $\ge 10$ times. |

### Provenance Category Breakdown

| Category | Queries | Distinct Shapes | $D(N)$ | Entropy $H$ | $H/H_{\max}$ | $C_{20}$ | $R_2$ | $R_{10}$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **LLM Paraphrases** | 907 | 16 | 0.0176 | 3.6191 | 0.9048 | 100.0% | 100.0% | 100.0% |
| **Adversarial Families** | 330 | 4 | 0.0121 | 1.7925 | 0.8962 | 100.0% | 100.0% | 100.0% |
| **Template Canonical** | 7 | 7 | 1.0000 | 2.8074 | 1.0000 | 100.0% | 0.0% | 0.0% |

> **Scientific Clarification: Compiler Convergence vs. Open Workload Diversity**  
> $D(N)$ measures how rapidly new incoming queries create novel graph shapes vs. reusing existing shapes in the parameterized compiler grammar. P0.7 establishes **compiler convergence** (syntactic paraphrases of known computational tasks cleanly collapse to a compact set of semantic canonical shapes). It does **not** claim that unconstrained human user requests across open domains naturally collapse into a small shape space.

---

## 3b. Multi-Domain Topology-Blind Workload Evaluation & Semantic Audit

To evaluate workload diversity beyond hand-authored templates, **600 natural personal assistant requests** across **12 realistic domains** were submitted to the frozen compiler with **zero topology hints and zero labels**.

### Domain-by-Domain Compilation & Rejection Breakdown

| Domain | Total | Compiled | Rejected | Unsupported | Ambiguous | Low Conf |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **communication_messaging** | 50 | 0 (0.0%) | 50 (100.0%) | 50 | 0 | 0 |
| **creative_brainstorming** | 50 | 6 (12.0%) | 44 (88.0%) | 37 | 7 | 0 |
| **file_data_management** | 50 | 0 (0.0%) | 50 (100.0%) | 50 | 0 | 0 |
| **finances** | 50 | 30 (60.0%) | 20 (40.0%) | 20 | 0 | 0 |
| **health_fitness** | 50 | 10 (20.0%) | 40 (80.0%) | 34 | 0 | 6 |
| **home_automation_iot** | 50 | 0 (0.0%) | 50 (100.0%) | 50 | 0 | 0 |
| **math_calculations** | 50 | 4 (8.0%) | 46 (92.0%) | 46 | 0 | 0 |
| **media_entertainment** | 50 | 0 (0.0%) | 50 (100.0%) | 46 | 0 | 4 |
| **open_web_search_knowledge** | 50 | 0 (0.0%) | 50 (100.0%) | 50 | 0 | 0 |
| **schedule** | 50 | 24 (48.0%) | 26 (52.0%) | 16 | 0 | 10 |
| **shopping_inventory** | 50 | 10 (20.0%) | 40 (80.0%) | 37 | 0 | 3 |
| **system_settings_device** | 50 | 0 (0.0%) | 50 (100.0%) | 50 | 0 | 0 |

### Novel Shape Workload Mass & Semantic Validation Audit

Among the 84 queries that compiled, exactly **3 novel shapes** (`8532756b`, `ca879588`, `f5fb271f`) emerged that were never present in the 1,550-query anchored corpus.

* **Novel Shape Type Rate:** **42.9%** (3 novel shapes / 7 total blind shapes).
* **Novel Shape Workload Mass:** **44/84 (52.4%)** of compiled requests landed in novel shapes.
* **Semantically Valid Novel Mass:** **13/84 (15.5%)** represents genuine compositional variation (e.g. single-filter category sums without arbitrary threshold filters).
* **Misinterpreted Novel Mass:** **31/84 (36.9%)** represents spurious compiler fallbacks (e.g. inflation comparison, debit categorization, or rate-of-change alerts collapsed into naked sums).

| Shape Key | Queries | Semantic Graph Structure | Sample Queries | Validation Breakdown | Rationale & Failure Modes |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `8532756b` | 17 | `Observe -> Map -> Reduce -> Emit` | • "Show me all recurring subscription charges debited this month"<br>• "Compare my grocery expenditures in Q1 versus Q2 and identify biggest inflationary price increases"<br>• "Categorize all uncategorized debit purchases from my weekend trip to Seattle" | **0 Valid** (0.0%), **17 Misinterpreted** (100.0%) | Misinterpreted: Query semantics do not match the instantiated fixture topology; Query requested comparative/trend analysis, but compiler produced a non-comparative scalar reduction; Query requested categorical classification/tagging, but compiler produced an aggregation sum; Query requested predictive notification, but compiler generated a static reduction |
| `ca879588` | 3 | `Observe -> Filter -> Map -> Reduce -> Emit` | • "What was my largest single expense in the last 90 days?"<br>• "Please what was my largest single expense in the last 90 days?"<br>• "Can you what was my largest single expense in the last 90 days?" | **0 Valid** (0.0%), **3 Misinterpreted** (100.0%) | Misinterpreted: Time duration '90 days' was erroneously extracted as a monetary amount threshold |
| `f5fb271f` | 24 | `Observe -> Filter -> Map -> Reduce -> Emit` | • "How much money did I spend on restaurant dining over the weekend?"<br>• "Alert me if my monthly utility expenses increase by more than 20% compared to last year"<br>• "Can you project my bank savings balance for next quarter if I reduce discretionary spending by 15%?" | **13 Valid** (54.2%), **11 Misinterpreted** (45.8%) | Valid: Valid compositional single-filter category aggregation (filtered by category without arbitrary threshold)<br>Misinterpreted: Query requested comparative/trend analysis, but compiler produced a non-comparative scalar reduction; Query requested financial forecasting/projection, but compiler produced an historical aggregation; Query semantics do not match the instantiated fixture topology |

> **Key Scientific Insights on Workload Diversity**:  
> 1. **Domain Boundary Rejection (86.0%)**: As assistant requests move away from structured core data (finances, calendar) toward system settings, communication, file management, home automation, and web search, the rejection rate approaches 100%. A fixed-template compiler cannot serve as an open assistant runtime.  
> 2. **Novel Shape Dual Reality**: Open workloads naturally explore valid compositional variants (15.5% of compiled workload), but rule-based keyword matching also creates false compilation fallbacks (36.9% of compiled workload) where complex requests are shoehorned into degraded graphs. This provides direct empirical justification for Phase P1's learned controller.

---

## 4. Surface-to-Semantic Stability Across Independent Batches (§8)

Paraphrases were generated across three independent model sessions:
* **Batch 1 (Formal / Technical - GPT-4o-mini, $T=0.7$):** $D = 0.0472$, $H = 3.5722$
* **Batch 2 (Conversational - Gemini-1.5-Flash, $T=0.9$):** $D = 0.0463$, $H = 3.2133$
* **Batch 3 (Compound / Multi-Clause - Claude-3-Haiku, $T=1.0$):** $D = 0.0485$, $H = 3.6676$

* **Jaccard Shape Overlap:** 68.8%
* **Max D-Ratio Variance Across Batches:** 0.0022 ($\le 0.05$)
* **Conclusion:** Canonicalization is robust to model-specific linguistic bias and stylistic variations.

---

## 5. Structured Adversarial Family Results (§6.4)

| Family | Name | Test Pattern | Result | Status |
| :--- | :--- | :--- | :--- | :---: |
| **A1** | Dependency Sensitivity | Same text, different accounts/sources | Distinct observe sources & memo keys, isolated invalidation | **PASS** |
| **A2** | Contract Identity | Same text, different OutcomeContracts | Distinct memo keys across contract types | **PASS** |
| **A3** | Parameter Sensitivity | Micro threshold delta ($100.00 vs $100.01) | Distinct memo keys | **PASS** |
| **A4** | Shape Invariance | Diverse surface phrasings, identical computation | Exactly 1 collapsed ShapeKey | **PASS** |
| **A5** | Cost Class Projection | Cardinality 10 vs 100,000 | Dynamic scan derivers distinct cost brackets | **PASS** |
| **A6** | Effect Enforcement | Pure vs WriteExternal runtime double-execution | Run 2 reuses pure state; external write strictly forbids memoization | **PASS** |

---

## 6. Structural Outlier & Full 7-Topology Gate Verification (§5.2, §10.6-7)

The required **Structural Outlier Topology** (`cross_source_join_aggregate`) cross-references two heterogeneous data sources:
$$\text{Observe}(\text{orders}) + \text{Observe}(\text{inventory}) \to \text{Join} \to \text{Filter} \to \text{Map} \to \text{Reduce} \to \text{Emit}$$

* **Primitive Compliance (G0 Extended):** Evaluated across all 7 fixtures; uses strictly the 11 frozen primitives (0 domain-specific primitives).
* **Topology Discrimination (G1b Extended):** 7 distinct computational topologies produce exactly 7 distinct, non-colliding `SemanticShapeKey` hashes.

---

## 7. Realistic Corpus Co-Measurement (G2 / G3 / P3)

Evaluated under the **decoupled measurement protocol** with balanced sampling across all 7 topologies AND generation batches (`batch_1`, `batch_2`, `batch_3`, `canonical`, and adversarial families):

### Steady-State Independent Trials (Uniform 100% Pre-Warmed Workload)

| Metric | Mean Latency | Std Dev | Gate Specification | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Baseline Cost ($C_{\text{baseline}}$)** | 87.63 ms | $\pm$ 2.33 ms | - | - |
| **Oracle Cost ($C_{\text{oracle}}$)** | 0.55 ms | - | - | - |
| **CNE Total Cost ($C_{\text{CNE}}$)** | 10.49 ms | $\pm$ 0.72 ms | - | - |
| **Control Overhead Ratio ($A_{\text{corpus}}$)** | **8.37%** | - | $A \le 20.0\%$ | **PASS** |
| **Recoverable Mass ($R^*$)** | **99.37%** | - | $R^* \ge 25.0\%$ | **PASS** |
| **Net Computation Savings ($\Delta C$)** | **+77.14 ms** | - | $\Delta C > 0$ | **PASS** |
| **Optimization Capture Ratio** | **88.58%** | - | $\le 100.0\%$ | **PASS** |

### Multi-Session State Evolution Progression

| Session | Total CNE Latency | Control Overhead | Net Savings | State Reuse Intensity |
| :--- | :---: | :---: | :---: | :---: |
| **Session 1 ($S_1$)** | 39.52 ms | 8.6% | +51.45 ms | 2.33 events / created state |
| **Session 2 ($S_2$)** | 10.31 ms | 8.8% | +76.98 ms | 5.67 events / created state |
| **Session 3 ($S_3$)** | 11.10 ms | 8.1% | +76.54 ms | 9.00 events / created state |

> **Caveat on Multi-Session Evaluation**: This experiment evaluates state buildup under repeated sessions of an identical workload. Invalidation under continuous data arrival and mutations is separately verified under Extreme Test suites (21 state fabric tests, 20 dependency tests).

---

## 8. Progression to Phase P1 & Provenance Disclosures

### Provenance Classification
The 990 LLM paraphrases carry **recorded provenance metadata** across three distinct prompt/model configurations (`gpt-4o-mini`, `gemini-1.5-flash`, `claude-3-haiku`) generated via local scripts. In accordance with strict scientific discipline, we explicitly distinguish between *recorded metadata provenance* (present in the artifact) and *independently auditable cryptographic server traces* (which would require external third-party logging).

### Decision Gate Verdict: `GO`
All requirements of Phase P0.7 (Revision 3) are satisfied under rigorous experimental conditions. Phase P0.7 demonstrates **surface-to-semantic stability and compiler convergence** on its supported task universe. The exploratory diagnostic probes demonstrate that open assistant workloads require adaptive learned semantic generalization, formally clearing the runway for **Phase P1 (Learned Controller)**.
