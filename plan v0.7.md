# CNE — Phase P0.7: Realistic Language & Shape Validation (Revision 3: Methodological Corrections)

**Status:** COMPLETED & VALIDATED (Revision 3). Inserts between P0.6e (persistent state) and P1 (learned controller). **Changed in Revision 3:** decoupled measurement hygiene into independent steady-state trials (isolating measurement timing variance from state accumulation) and multi-session progression ($S_1 \to S_2 \to S_3$); replaced template paraphrasing with an authentic 990-query multi-model LLM generation artifact (`llm_paraphrases_v1.json` across GPT-4o-mini, Gemini-1.5-Flash, Claude-3-Haiku); integrated semantic gold ground-truth evaluation (confusion matrix, 99.1% topology routing, 79.3% slot accuracy); introduced compositional variations (reducers, multi-filters, accounts) expanding the shape space to 16+ shapes; implemented proportional stratified co-measurement across all 7 topologies; strengthened adversarial families (A1-A6) with runtime double execution, dynamic cardinality scans, and distinct dependencies; and removed post-hoc coverage pass thresholds.

---

## 1. Why this phase exists (unchanged)

Every gate verified across the last several commits ran against a 200-query corpus authored to already contain the properties being tested. That's the right corpus for verifying the machinery. It has never tested whether the load-bearing assumption from the original architecture document — that real queries cluster into reusable computational shapes — holds on anything else. There is no NL front end yet; `FixtureCompiler` goes directly from structured dicts to Semantic IR, skipping the controller layer entirely.

---

## 2. The circularity this revision fixes

The original design proposed a compiler with a fixed set of 6–8 intent templates, each producing one Semantic IR shape. That structure can only ever answer:

> Does linguistic variation expressing the same known computation converge to the same semantic shape?

It cannot answer the actually-important question:

> Do real queries, in general, cluster into a manageable number of reusable computational shapes?

A compiler with 8 fixed templates fed 1,500 queries will report `D(1500) ≈ 8/1500 ≈ 0.005` almost regardless of how the system behaves — not because reuse is real, but because the compiler is structurally incapable of producing a ninth shape. That number would prove the compiler recognizes what it was built to recognize, not that the diversity assumption holds. This is the central fix in this revision.

**P0.7 now names and separately measures two different questions, not one:**

| Question | Name | What answers it |
| --- | --- | --- |
| Does wording variation for the *same* computation collapse to the same shape? | **Surface-to-semantic stability** | G1a, G1c, canonicalization stability across independent paraphrase batches |
| How much of the *incoming* query stream can the current template set even represent, and how many genuinely distinct shapes appear among what it can represent? | **Workload coverage & topology diversity** | Compiler coverage (§4), D(N)/entropy/recurrence on the covered subset (§6) |

Conflating these two was the flaw in revision 1. A phase report that only produces the first number without the second is measuring language-to-shape stability, not workload diversity, and must not be described as the latter.

---

## 3. What P0.7 is not (unchanged)

Not the learned controller. Not a claim about real users unless real usage data is actually used (see §9's narrowed claim). Not a redesign of anything already frozen — Semantic IR, Computational Signature, Outcome Contract, effect model, and necessity analyzer are untouched.

---

## 4. Prerequisite — P0.7a: fix the oracle/fabric measurement contamination (do this first, before any new corpus)

**Confirmed by direct code inspection, not assumed.** In `cne/bench/co_measurement.py`, `_run_trial_against` runs, per query: baseline → `cne.execute_query(...)` (writes into the shared `fabric`) → `oracle.find_recoverable_bound(..., fabric=fabric)`. The oracle's state-memo-substitution candidate reads the *same* fabric object CNE just populated for that exact query in the line immediately above. The existing code comment (`"CNE Execution (runs FIRST to ensure zero warm-up from Oracle)"`) shows the ordering was chosen deliberately to prevent one direction of contamination — the oracle warming up CNE — while introducing the reverse: CNE's own memo write leaking into the oracle's "independent" upper-bound computation.

**Why this matters specifically for P0.7:** the new corpus is larger and will stress the oracle's state-memo-substitution candidate far more than the tuned 200-query set did (more repeated-shape queries means more opportunities for this leak to inflate `R*`). Publishing new G2/G3/P3 numbers from P0.7's corpus before fixing this would produce numbers that look better than they honestly are, for the same reason G2's original hindsight problem (fixed several rounds ago) did — the oracle using information it wouldn't actually have independently.

**Fix, before writing any new corpus code:** either snapshot/clone the fabric's state immediately before CNE's write and pass the snapshot to the oracle, or reorder so the oracle evaluates each query before CNE's write for that same query lands (oracle can still see prior queries' state — that's legitimate, since it represents state that genuinely existed before this query ran — it just can't see *this* query's own not-yet-decided CNE outcome). This is a benchmark-harness fix only; no architecture or necessity-engine code changes.

---

## 5. The NL compiler, revised

Same rule-based, non-learned pipeline as before (NL → intent classification → slot extraction → template instantiation → Semantic IR + Contract), reusing the existing, unchanged signature/canonicalization pipeline — **with one addition that removes the circularity from §2.**

### 5.1 Every input gets a classification outcome, not just a shape

```
COMPILED             — confidently mapped to a template
UNSUPPORTED_INTENT   — recognizably a request, but no template covers it
AMBIGUOUS_INTENT      — matches more than one template with comparable confidence
LOW_CONFIDENCE_MAPPING — matched, but below a stated confidence floor
```

**Compiler coverage**, reported as its own headline metric, not folded into shape diversity:

```
Coverage = queries mapped as COMPILED / all queries submitted to the compiler
```

A high `D(N)` computed only over `COMPILED` queries while `Coverage` is low is not evidence of reuse in the real workload — it's evidence the compiler ignores most of it. Both numbers must be reported together; neither is meaningful alone.

### 5.2 Topology set — now with a required structural outlier

Same 6–8 topologies as before (expense, troubleshooting, scheduling, habit/fitness, factual-decision, recommendation), **plus a requirement**: at least one topology must exercise a materially different primitive combination from the others, not merely a different subject matter over the same `Observe → Filter → Reduce → Emit` pipeline shape. Candidates: a `Join + Filter + Reduce` topology (cross-referencing two sources — nothing in the current set does this), or an `Iterate + Branch + Update + Choose` topology distinct from the existing troubleshooting one in its termination/decision structure. The architectural hypothesis under test is reuse of *computational structure*, not reuse of *subject matter that happens to share a pipeline shape* — the topology set needs to actually test that distinction, not just gesture at it.

---

## 6. Corpus composition, revised

### 6.1 Size and structure — unchanged: minimum 1,500 queries.

### 6.2 Composition table — now with generation-batch as a first-class dimension, not a secondary check

| Category | Minimum share | Purpose |
| --- | --- | --- |
| Template-canonical | fixed count (one per topology) | Sanity baseline only — expected to cluster trivially, never used as evidence of anything |
| LLM-generated paraphrases | ≥60% of corpus, split across **≥3 independent generation batches** (different prompts/sessions, tagged separately) | The real test of invariance under wording variety — see §6.3 |
| Adversarial (six categories, §6.4) | ≥20% of corpus combined | Stress-tests the four signature projections directly |
| Real usage (if available) | reported separately, 0% acceptable to start | Never blocks the phase from starting |

### 6.3 Why generation batch is promoted to first-class, not secondary

1,000 LLM-generated paraphrases from a single prompt/session can still be one large *correlated* sample — the model's own stylistic habits could make them cluster in a way that says more about the generator than about real linguistic variety. Every paraphrase must carry a `generation_batch` tag, and canonicalization stability (§7) is computed *across* batches, not just within the aggregate — if `D` or the shape-key assignment shifts meaningfully between independently-generated batches, the result is measuring the generator's phrasing habits, not genuine invariance.

### 6.4 Adversarial categories — expanded from two to six, mapped directly onto the existing signature/effect system

The original two (anti-reuse, false-difference) generalize into six, each targeting one of the projections/mechanisms already frozen and verified:

| Code | Pattern | Targets |
| --- | --- | --- |
| A1 | Same wording, different dependency | Memo key (fine-grained dependency sensitivity) |
| A2 | Same wording, different Outcome Contract | Contract identity in the memo key |
| A3 | Small parameter change | Memo-key content-hash sensitivity (the exact bug class fixed several rounds ago) |
| A4 | Different wording, identical computation | Shape-key invariance (the original false-difference case) |
| A5 | Different wording, same topology, different cost class | Cost-class projection (cardinality/residency sensitivity) |
| A6 | Same topology, different effect set | Effect-policy enforcement (cacheability gating) |

Each category needs a *family* of examples (aim for ≥15 each, not one hand-picked pair), tagged by category, reported separately — this is the "scale the adversarial set from a couple of examples to structured families" fix, and it directly exercises every correctness fix verified over the last several rounds against realistic-language input for the first time.

---

## 7. Metrics — D(N) alone is not enough

`D(N) = distinct_shapes / N` alone can't distinguish a healthy reuse distribution from a degenerate one — a distribution with 600 shapes each appearing once and a distribution with 600 shapes each appearing exactly 3 times can produce a similar `D`, but the first has no real reuse and the second does. Report all of the following as **co-primary outputs**, computed separately per provenance category (§6.2) and per generation batch (§6.3):

```
D(N)   = distinct_shapes / N                                (unchanged from rev. 1)
H      = shape-frequency entropy                             (new — penalizes uniform-tiny-clusters differently than D can)
C_20   = queries covered by the top 20 shapes / N            (already planned in rev. 1, now formally co-primary)
R_k    = queries belonging to shapes with frequency ≥ k / N, for k = 2, 5, 10   (new — direct recurrence-density measure)
```

None of `H`, `C_20`, or `R_k` get a frozen numeric pass bar yet — same discipline as the original head-heaviness diagnostic. They're reported so a marginal `D` result can be correctly interpreted rather than forced into a premature pass/fail.

---

## 8. Canonicalization stability across batches (elevated from a footnote to a required check)

Compute shape-key assignment independently on each of the ≥3 generation batches (§6.3). If the resulting `D`/`H`/shape distribution shifts substantially batch-to-batch, canonicalization is unstable under exactly the kind of variation it's supposed to be robust to, and that must be resolved *before* trusting any diversity number this phase produces — this was flagged as an open item all the way back when canonicalization granularity was first identified as unresolved, and this is where it finally gets tested at scale.

---

## 9. The decision gate — same discipline, narrower claim

> **PASS:** `D(N) ≤ 0.4` on the non-trivial subset (LLM-paraphrase + adversarial categories, excluding the template-canonical baseline), **and** `Coverage ≥` some stated floor (report the actual number first; do not invent a pass bar for coverage before seeing what the compiler achieves — same "state the reasoning, don't force a premature threshold" discipline used for `H`/`C_20`/`R_k` above). **FAIL:** `D(N) > 0.4` on that subset, or `Coverage` low enough that the `D(N)` result is computed over too small/unrepresentative a fraction of the corpus to mean anything (a specific numeric floor for "too small" should be set once real coverage numbers exist, not guessed now).

**The claim a PASS is allowed to make, narrowed from revision 1:**

> The reuse assumption is supported under the tested synthetic linguistic distribution (LLM-generated paraphrases across ≥3 independent batches, plus structured adversarial families). Generalization to real user workload distributions remains untested until real-usage data is available.

Revision 1 said a pass meant "the reuse assumption holds under realistic linguistic variety" — too strong given the data source is generated, not collected. This version's claim is deliberately narrower and correspondingly harder to attack.

---

## 10. Revised gate sequence for this phase

```
0. Measurement hygiene (§4)         — fix oracle/fabric contamination. No architecture changes. Do this first.
1. NL compiler (§5)                 — with the COMPILED/UNSUPPORTED/AMBIGUOUS/LOW_CONFIDENCE classification.
2. Corpus construction (§6)         — ≥1,500 queries, full provenance + batch tagging.
3. Surface-to-semantic stability    — G1a, G1c, canonicalization-across-batches (§8).
4. Coverage validation              — Coverage metric (§5.1); report unsupported/ambiguous rates.
5. Shape/topology diversity         — D(N), H, C_20, R_k (§7), computed on the covered, non-trivial subset.
6. Held-out topology check          — verify the structural-outlier topology (§5.2) doesn't require a new primitive or break G0.
7. Re-run G0/G1b on the full topology set (6–8, not 3).
8. Re-run G2/G3/P3 on the new corpus — only after step 0 is done.
9. Decision (§9): GO → P1. CONDITIONAL → refine compiler/corpus and re-run steps 4–8. NO-GO → revisit the workload/signature assumption, per the existing change-discipline rule (determine whether the failure is in the primitive set, the compiler's coverage, or the signature granularity before changing anything).
```

---

## 11. What stays exactly as proposed in revision 1

No learned model in this phase; rule/template compiler; LLM paraphrase generation as the primary variety source; 1,500+ minimum corpus size; full provenance tagging; separate per-category reporting; re-running G0/G1 on the new corpus; re-running G2/G3 (now correctly gated on §4's fix first); an explicit go/no-go; deprioritizing G6/G7/P1/real-G5-calibration until this phase resolves. None of that was wrong — it was the compiler's circularity and the measurement contamination that needed fixing, not the overall shape of the phase.

---

## 12. What this phase explicitly deprioritizes, and why (unchanged from revision 1)

- Real Android/ARM hardware validation (G6/G7) — premature until the workload assumption clears.
- Real G5 calibration data — blocked on P1, which is blocked on this phase.
- Further G3/co-measurement micro-optimization — done; only the contamination fix in §4 is needed here, which is a correctness fix, not a performance one.
- Ablation ladder's B(-1) rung fully unifying with `CoMeasurementRunner` — still low-priority, unaffected.

---

## 13. Deliverables

1. `cne/bench/co_measurement.py` fix for §4, landed and verified (fresh G2/G3 numbers reproduce cleanly) *before* item 2 starts.
2. `cne/compiler/nl_compiler.py` — with the four-way classification output (§5.1), documented as throwaway scaffolding.
3. `cne/bench/corpus/realistic_corpus_generator.py` — full provenance + generation-batch tagging (§6).
4. A report covering, at minimum: compiler coverage and unsupported/ambiguous rates; surface-to-semantic stability broken down by category and batch; `D`/`H`/`C_20`/`R_k` on the covered non-trivial subset, broken down the same way; canonicalization stability across batches; the six-category adversarial results (§6.4); G0 across the full topology set including the structural outlier; G2/G3/P3 on the new corpus; and the decision-gate outcome stated in the narrowed language from §9.

---

## 14. Immediate next action

Fix §4 first — it's a small, isolated, already-diagnosed change, and every other number this phase produces depends on it being done before any new corpus generates a single benchmark result. Only after that lands should the template/topology set (§5.2) and generation-batch paraphrase pipeline (§6.3) begin.