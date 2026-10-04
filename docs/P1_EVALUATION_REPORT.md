# Phase P1 Evaluation Report

**Generated:** 2026-10-04T21:30:15.934524+00:00
**Model:** qwen2.5-coder:1.5b
**Status:** ITERATE -- Some Targets Not Met

---

## 1. Executive Summary

| Metric | Value |
|:---|:---:|
| **Blind Coverage** | 37.5% (225/600) |
| **In-Scope Coverage** | 41.0% (123/300) |
| **OOS Rejection** | 77.0% (154/200) |
| **Schema Validity** | 98.5% |
| **Semantic Validity** | 99.8% |
| **Slot Accuracy** | 4.8% (18/373) |
| **Shape Diversity D(N)** | 0.7216 |
| **Primitive Adherence** | 100.0% (violations: 0) |
| **Avg Latency** | 7214ms |
| **Total Runtime** | 5089.9s |

---

## 2. Coverage Delta vs P0.8 Baseline

| Metric | P0.8 Baseline | P1 Result | Delta |
|:---|:---:|:---:|:---:|
| blind_coverage | 14.2% | 37.5% | +23.3pp |
| in_scope_coverage | 34.0% | 41.0% | +7.0pp |
| semantic_validity | 100.0% | 99.8% | -0.2pp |
| slot_accuracy | 81.2% | 4.8% | -76.4pp |
| oos_rejection | 100.0% | 77.0% | -23.0pp |
| primitive_adherence | 100.0% | 100.0% | +0.0pp |

---

## 3. Success Criteria Audit

| Target | Status |
|:---|:---:|
| blind_coverage >= 35% | PASS |
| in_scope_coverage >= 60% | FAIL |
| semantic_validity >= 90% | PASS |
| slot_accuracy >= 90% | FAIL |
| oos_rejection >= 95% | FAIL |
| shape_diversity <= 0.35 | FAIL |
| primitive_adherence == 100% | PASS |

**Overall Decision: ITERATE**

---

## 4. Per-Domain Breakdown

| Domain | Scope | Total | Compiled | Coverage | Schema Valid | Semantic Valid |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| communication_messaging | In-Scope | 50 | 10 | 20.0% | 50 | 50 |
| creative_brainstorming | OOS | 50 | 15 | 30.0% | 49 | 50 |
| file_data_management | In-Scope | 50 | 18 | 36.0% | 50 | 50 |
| finances | Other | 50 | 40 | 80.0% | 50 | 50 |
| health_fitness | In-Scope | 50 | 32 | 64.0% | 48 | 50 |
| home_automation_iot | In-Scope | 50 | 4 | 8.0% | 50 | 50 |
| math_calculations | In-Scope | 50 | 40 | 80.0% | 44 | 49 |
| media_entertainment | OOS | 50 | 5 | 10.0% | 50 | 50 |
| open_web_search_knowledge | OOS | 50 | 12 | 24.0% | 50 | 50 |
| schedule | Other | 50 | 16 | 32.0% | 50 | 50 |
| shopping_inventory | In-Scope | 50 | 19 | 38.0% | 50 | 50 |
| system_settings_device | OOS | 50 | 14 | 28.0% | 50 | 50 |

---

## 5. Outcome Distribution

| Outcome | Count | Rate |
|:---|:---:|:---:|
| COMPILED | 225 | 37.5% |
| UNSUPPORTED_INTENT | 365 | 60.8% |
| AMBIGUOUS_INTENT | 0 | 0.0% |
| LOW_CONFIDENCE_MAPPING | 10 | 1.7% |

---

## 6. Shape Topology Analysis

- **Distinct shapes discovered:** 56
- **Shape diversity D(N):** 0.7216
- **P0.8 baseline D(N):** 0.0128

---

## 7. Raw Artifacts

- `cne/artifacts/p1_dataset/blind_eval_results.json` — Full JSON results
- `docs/P1_EVALUATION_REPORT.md` — This report
