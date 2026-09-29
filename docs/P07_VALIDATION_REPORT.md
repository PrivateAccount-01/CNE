# CNE Phase P0.7: Realistic Language & Shape Validation Report (Revision 3)

**Phase Status:** GO (Decision Gate Evaluated)  
**Execution Timestamp:** 2026-09-29T19:33:34Z  
**Total Queries Evaluated:** 1550 (Anchored Corpus) + 300 (Topology-Blind Workload)  

---

## 1. Executive Summary & Decision Gate Outcome

Phase P0.7 rigorously validates the foundational architectural assumption of CNE: **do realistic queries cluster into reusable computational shapes?**

To eliminate circularity, this evaluation separates **surface-to-semantic stability** from **workload coverage & topology diversity**.

| Metric / Requirement | Target Specification | Empirical Result | Gate Status |
| :--- | :---: | :---: | :---: |
| **Prerequisite Measurement Hygiene (§4)** | Zero self-memo leak in Oracle | **Verified** (Oracle runs before CNE write) | **PASS** |
| **Steady-State Trial Independence** | Decouple timing noise from state accumulation | **Verified** (Fresh pre-warmed fabric per trial) | **PASS** |
| **Semantic Gold Topology Routing (§5)** | Routing Accuracy $\ge 90.0\%$ | **99.12%** | **PASS** |
| **Compiler Coverage (§5.1)** | Transparent empirical disclosure | **80.9%** (1254/1550) | **DISCLOSED** |
| **Non-Trivial Shape Diversity $D(N)$ (§7)** | $D(N) \le 0.40$ | **0.0129** (16 shapes / 1237 queries) | **PASS** |
| **Blind Workload Rejection Rate (§Issue 1)** | Unguided assistant requests | **52.0%** (156/300) | **REPORTED** |
| **Novel Shapes in Blind Pass (§Issue 1)** | Distinct from 16 anchored shapes | **2 novel shapes** (22.2% rate) | **DISCOVERED** |
| **Cross-Batch Stability (§8)** | $\Delta D \le 0.05$, Jaccard $\ge 65\%$ | Jaccard = **68.8%**, $\Delta D$ = **0.0022** | **PASS** |
| **Adversarial Families Verification (§6.4)** | All 6 families (A1–A6) pass end-to-end | **6/6 Families Passed** | **PASS** |
| **Structural Outlier G0 Check (§5.2)** | 0 domain nodes, $\le 2$ new prims | **100% frozen primitives**, 0 new primitives | **PASS** |
| **Extended G1b Discrimination (§10.7)** | 7 topologies $\implies$ 7 distinct shapes | **7 distinct shape keys** | **PASS** |
| **Realistic Co-Measurement G2 ($R^*$)** | $R^* \ge 25.0\%$ | **77.61%** | **PASS** |
| **Realistic Co-Measurement G3 ($A_{\text{corpus}}$)**| $A_{\text{corpus}} \le 20.0\%$ | **10.92%** | **PASS** |
| **Realistic Co-Measurement Net Savings** | $\Delta C > 0$ | **+54.80 ms** | **PASS** |

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
| **LOW_CONFIDENCE** | 0 | 50 | 0 | 0 |

### Precision, Recall, and F1 Metrics

| Outcome Class | Precision | Recall | F1 Score | Ground Truth Count |
| :--- | :---: | :---: | :---: | :---: |
| **COMPILED** | 99.2% | 93.8% | 96.4% | 1327 |
| **UNSUPPORTED_INTENT** | 62.4% | 100.0% | 76.9% | 123 |
| **AMBIGUOUS_INTENT** | 76.9% | 80.0% | 78.4% | 50 |
| **LOW_CONFIDENCE_MAPPING** | 0.0% | 0.0% | 0.0% | 50 |

* **Topology Routing Accuracy:** **99.12%** on gold-compilable queries.
* **Slot Extraction Accuracy:** **79.32%** exact match across all extracted slots.
* **Coverage Disclosure:** The compiler successfully compiles 80.9% (1254/1550) of the realistic query stream, rejecting ambiguous and out-of-domain requests without artificial post-hoc threshold conditioning.

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
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **LLM Paraphrases** | 907 | 16 | 0.0176 | 3.6191 | 0.9048 | 100.0% | 100.0% | 100.0% |
| **Adversarial Families** | 330 | 4 | 0.0121 | 1.7925 | 0.8962 | 100.0% | 100.0% | 100.0% |
| **Template Canonical** | 7 | 7 | 1.0000 | 2.8074 | 1.0000 | 100.0% | 0.0% | 0.0% |

> **Scientific Clarification: Compiler Convergence vs. Open Workload Diversity**  
> $D(N)$ measures how rapidly new incoming queries create novel graph shapes vs. reusing existing shapes in the parameterized compiler grammar. P0.7 establishes **compiler convergence** (syntactic paraphrases of known computational tasks cleanly collapse to a compact set of semantic canonical shapes). It does **not** claim that unconstrained human user requests across open domains naturally collapse into a small shape space.

---

## 3b. Open-World Topology-Blind Workload Evaluation (§Issue 1)

To evaluate the foundational workload diversity question without generator bias, **300 natural requests** were generated across four personal assistant domains (finances, calendar, health/fitness, and shopping/inventory) with **zero mention of CNE's 7 topologies**.

| Metric | Anchored Corpus (1,550 queries) | Topology-Blind Workload (300 queries) | Delta / Finding |
| :--- | :---: | :---: | :--- |
| **Total Evaluated** | 1,550 | 300 | Independent zero-hint sample |
| **Compiled Requests** | 80.9% (1254) | 48.0% (144) | Common subtasks mapped to compiler |
| **Unsupported Rate** | 12.7% (197) | 37.7% | Open-ended queries (forecasting, advice) rejected |
| **Total Rejection Rate** | **19.1%** | **52.0%** | **+32.9% higher rejection** on blind input |
| **Distinct Shapes** | 16 | 9 | Active shapes in blind workload |
| **Novel Shapes Discovered** | 0 (baseline) | **2** | **22.2%** of blind shapes are structurally novel |

> **Scientific Finding on Workload Diversity**:  
> 1. When requests are unguided, **rejection rises from 19.1% to 52.0%**, proving that open-world assistant workloads contain a substantial volume of requests outside the current 7-topology compiler grammar.  
> 2. Among requests that *do* compile, the emergence of **2 novel shapes** (`8532756b`, `f5fb271f`) proves that the 7-topology set was indeed incomplete, and unconstrained queries explore parameterized shape variations beyond the original hand-crafted templates.

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
| :--- | :--- | :--- | :---: | :---: |
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

Evaluated under the **decoupled measurement protocol** with stratified sampling across all 7 topologies:

### Steady-State Independent Trials (Pure Timing Noise)

| Metric | Mean Latency | Std Dev | Gate Specification | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Baseline Cost ($C_{\text{baseline}}$)** | 87.06 ms | $\pm$ 5.94 ms | - | - |
| **Oracle Cost ($C_{\text{oracle}}$)** | 19.49 ms | - | - | - |
| **CNE Total Cost ($C_{\text{CNE}}$)** | 32.27 ms | $\pm$ 1.86 ms | - | - |
| **Control Overhead Ratio ($A_{\text{corpus}}$)** | **10.92%** | - | $A \le 20.0\%$ | **PASS** |
| **Recoverable Mass ($R^*$)** | **77.61%** | - | $R^* \ge 25.0\%$ | **PASS** |
| **Net Computation Savings ($\Delta C$)** | **+54.80 ms** | - | $\Delta C > 0$ | **PASS** |
| **Optimization Capture Ratio** | **81.07%** | - | $\le 100.0\%$ | **PASS** |

### Multi-Session State Evolution Progression

| Session | Total CNE Latency | Control Overhead | Net Savings | State Reuse Intensity |
| :--- | :---: | :---: | :---: | :---: |
| **Session 1 ($S_1$)** | 42.78 ms | 11.2% | +38.36 ms | 1.04 events / created state |
| **Session 2 ($S_2$)** | 9.04 ms | 10.2% | +79.50 ms | 3.07 events / created state |
| **Session 3 ($S_3$)** | 8.97 ms | 10.5% | +76.51 ms | 5.11 events / created state |

---

## 8. Progression to Phase P1

All requirements of Phase P0.7 (Revision 3) are satisfied under rigorous experimental conditions. The system qualifies for **Phase P1 (Learned Controller)** under the stated narrowed claims.
