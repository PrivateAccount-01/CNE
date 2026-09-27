# CNE — Master Implementation Specification

### Latest consolidated build baseline after v1.5 measurement hardening

Use this as the **single source of truth for your from-scratch implementation**.

It consolidates:

* the frozen v1.5 architecture,
* all measurement fixes through the latest review,
* the six remaining measurement issues,
* the three required pre-experiment additions,
* the final instrumentation clarifications,
* the exact phase/gate structure,
* implementation order,
* benchmark rules,
* and the research/business boundary.

The previously generated build report is **not part of the specification**. Treat it as something you independently inspect or reproduce. Do not copy its implementation just because it happens to exist.

The architecture is frozen. From here, failures should change code, tests, parameters, workload assumptions, or measurement definitions only when justified. The human tendency to redesign the entire building because one lightbulb failed is hereby outlawed.

---

# 1. Core objective

CNE, the **Computation Necessity Engine**, is a local execution system that attempts to reduce unnecessary computation by determining:

1. what computation is actually necessary for a requested outcome,
2. what prior computation remains valid,
3. what can be reused,
4. what can be eliminated safely,
5. what execution strategy satisfies the outcome under resource constraints.

The central execution question is:

$$
\text{Given }G,S,C,B,\text{ find a cheaper admissible execution satisfying }C
$$

where:

* \(G\) = semantic task graph,
* \(S\) = available current and persistent state,
* \(C\) = Outcome Contract,
* \(B\) = resource budget.

The optimizer does **not** get to declare computation unnecessary merely because it is expensive. It needs an admissible reason that preserves the contract.

---

# 2. Target execution envelope

This is part of the specification and must not disappear from implementation documents.

```text
Primary:
  Android
  6–8 GB RAM
  ARM CPU
  no NPU dependency
  offline-capable

Secondary:
  optional USB compute tier

Baseline evaluation:
  no cloud dependency
```

The CPU-only path is the primary research target.

USB is a secondary execution substrate. It must never become necessary for the core CNE claim.

---

# 3. Frozen architecture

## 3.1 End-to-end pipeline

```text
Query Interface
      ↓
Semantic Compiler + Controller
      ↓
Computational Signature
      ↓
Outcome Contract
      ↓
Static Optimizer
      ↓
Local State Fabric
      ↓
Runtime Optimizer
      ↓
Physical Planner
      ↓
Execution Engine
      ↓
Verifier / Auditor
      ↓
Outcome
      ↓
Useful state persisted back into State Fabric
```

---

## 3.2 Component responsibilities

| Component               | Responsibility                                            | Must not know                      |
| ----------------------- | --------------------------------------------------------- | ---------------------------------- |
| Query Interface         | NL request, context, user state                           | Physical execution                 |
| Semantic Compiler       | Request → typed Semantic IR + Contract                    | Hardware/model placement           |
| Computational Signature | Canonical computation descriptors                         | Surface wording                    |
| Outcome Contract        | Defines acceptable result                                 | Implementation technique           |
| Static Optimizer        | Compile-time elimination/simplification                   | Runtime state                      |
| Local State Fabric      | Working, semantic, computational, archive state           | Any single model family            |
| Runtime Optimizer       | Validity, reuse, bounds, conditional execution, cost gate | Specific neural architecture       |
| Physical Planner        | Lower semantic work to CPU/neural/retrieval/USB           | Task wording                       |
| Execution Engine        | Executes surviving operations                             | Domain-specific special cases      |
| Verifier/Auditor        | Determines evidence status                                | —                                  |
| Learning Loop           | Improves models/policies offline                          | Online self-modifying safety rules |

---

# 4. Semantic IR

The Semantic IR is hardware-agnostic.

```text
Observe
Map
Filter
Reduce
Join
Branch
Iterate
Choose
Update
Call
Emit
```

These are the semantic primitives.

The physical layer may contain:

```text
HashJoin
VectorSearch
NeuralInfer
MemoLookup
CPU
USB
```

The semantic layer must not contain those hardware choices.

---

# 5. Primitive semantics

## `Observe`

Reads external or stateful information.

Conceptually:

```text
Observe(source)
    → value
    → DependencyKey
```

The dependency identity is mandatory for sound invalidation.

---

## `Map`

Applies a function over a collection.

```text
Map(f, xs)
```

The effect of `f` contributes to the node's effect set.

---

## `Reduce`

Folds a collection.

```text
Reduce(op, init, xs)
```

The effect of the operator and initialization contributes to the node's effect set.

---

## `Filter`

Semantic convenience for filtering by a predicate.

Keep it named rather than blindly expanding it because the optimizer needs to reason about:

* cardinality,
* predicate dependencies,
* selective execution,
* potential incremental invalidation.

---

## `Join`

Semantic convenience for relational combination.

Keep it named because join structure matters to:

* dependency analysis,
* cardinality,
* cost,
* physical lowering.

---

## `Branch`

A lazy control region.

The body of an unselected branch must not execute.

```text
Branch(condition,
       then_region,
       else_region)
```

This is crucial. An eager implementation would destroy selective execution.

---

## `Iterate`

Also a lazy control region.

Only the iterations actually required by the semantics should execute.

---

## `Choose`

Selects among runtime actions under resource and outcome constraints.

Formal decision rule:

$$
a^*=
\arg\max_a E[\Delta U(a)]
$$

subject to:

$$
C_i(a)\le B_i
$$

for:

```text
latency
energy
memory
CPU
thermal
```

Do not introduce learned policy logic initially.

---

## `Update`

Finite Bayesian belief update.

Constraint:

$$
N\le50
$$

For evidence \(e\):

$$
P(h|e)=
\frac{P(e|h)P(h)}
{\sum_{h'}P(e|h')P(h')}
$$

Complexity:

$$
O(N)
$$

per evidence item.

The first implementation should be exact and deterministic.

---

## `Call`

Invokes a declared tool/model.

Every callable operation must have an explicitly declared effect set.

---

## `Emit`

Produces the final semantic output.

The output must be evaluated against the Outcome Contract rather than merely string-compared in every case.

---

# 6. Effect system

This is frozen.

Do **not** turn it back into a hierarchy.

```text
EffectSet ⊆ {
    ReadExternal,
    WriteExternal,
    Nondeterministic,
    Interactive
}

Pure = {}
```

General propagation:

$$
E(node)
=
E(inputs)
\cup
E(body/function\ arguments)
$$

Examples:

```text
Map(f, xs)
    E = E(xs) ∪ E(f)

Reduce(op, init, xs)
    E = E(xs) ∪ E(op) ∪ E(init)
```

A node with:

```text
{ReadExternal, WriteExternal}
```

must retain both effects.

---

## 6.1 Execution policy is separate

Effects describe semantics.

Policies describe what CNE may do operationally.

| Effect set           | Cacheable                                | Retryable          |
| -------------------- | ---------------------------------------- | ------------------ |
| `{}`                 | Yes                                      | Yes                |
| `{ReadExternal}`     | Conditional on valid dependency snapshot | Usually            |
| `{Nondeterministic}` | Normally no                              | Policy-dependent   |
| `{WriteExternal}`    | No                                       | Only if idempotent |
| `{Interactive}`      | No                                       | Usually no         |

For multiple effects, use the most restrictive policy.

Example:

```text
{ReadExternal, WriteExternal}
```

is not cacheable.

---

# 7. Static vs runtime effects

For a lazy `Branch`:

$$
E_{\text{static}}(Branch)
=
\bigcup_{r\in reachable\ regions}E(r)
$$

At runtime:

$$
E_{\text{runtime}}(Branch)
=
E(r_{\text{taken}})
$$

The same principle applies to `Iterate`.

Static optimization cannot use knowledge that exists only after runtime path selection.

This is a safety invariant.

---

# 8. Computational Signature

Do not implement one monolithic "signature."

There are four projections.

| Projection         | Purpose                                               |
| ------------------ | ----------------------------------------------------- |
| Semantic shape key | Group equivalent computational structures             |
| Memo key           | Identify reusable exact computation                   |
| Cost class         | Determine whether optimization overhead is worthwhile |
| Policy state       | Input to `Choose`                                     |

---

## 8.1 Semantic shape key

Based on:

```text
topology
control flow
types
```

It should be largely invariant to wording.

---

## 8.2 Memo key

Memo identity must distinguish computations whose outputs can differ.

General invariant:

> A memo key is valid only when all output-determining execution semantics are identical or contract-equivalent.

Starting identity fields:

```text
model_version
tokenizer_version
runtime_version
semantic_compiler_version
policy_version
knowledge_version
schema_version
```

Potential additional fields, when relevant:

```text
execution precision/configuration
randomness seed
determinism mode
locale/time semantics
model quantization
weights identity
other output-determining runtime configuration
```

The general rule is authoritative. The field list is not.

Do not make the memo key unnecessarily massive in P0.

---

## 8.3 Cost class

Cost depends on:

$$
C=f(
operation,
cardinality,
state\ residency,
model\ residency,
device,
thermal\ state
)
$$

The purpose is not to predict the exact cost perfectly.

It is to answer:

> Is spending effort on optimization likely to be cheaper than simply executing?

---

## 8.4 Policy state

Conceptually:

```text
{
    belief,
    action_set,
    budget,
    contract_impact
}
```

Used by `Choose`.

---

# 9. Signature test corpus

The corpus must exercise all four relevant combinations.

| Wording   | Computation | Expected |
| --------- | ----------- | -------- |
| Similar   | Same        | Merge    |
| Similar   | Different   | Separate |
| Different | Same        | Merge    |
| Different | Different   | Separate |

### Anti-reuse pair

```text
Compare expenses excluding transfers
Compare expenses including transfers
```

Same broad topology.

Therefore:

```text
shape key may match
memo key must differ
```

### False-difference pair

```text
Compare spending this month with last month
Tell me how much more I spent this month than the previous month
```

Different surface wording.

Expected:

```text
same shape key
same cost class
```

Do not expect memo keys to be identical merely because wording differs. Memo identity concerns actual computation/input identity.

---

# 10. G1 semantics

## G1a: invariance

At least:

$$
\ge80\%
$$

of members of a paraphrase group should map to the same computational structure.

Important clarification:

For G1a, "same signature" should mean **semantic shape invariance**, not necessarily identical memo key.

Different input values can legitimately produce different memo keys.

---

## G1b: topology discrimination

Different genuine computational topologies must receive distinct shape keys.

No numeric threshold initially.

Report the complete distribution.

---

## G1c: memo-key sensitivity

The anti-reuse pair must differ at the memo-key level.

The false-difference pair must share:

```text
shape key
cost class
```

---

# 11. Outcome Contract

The contract defines what must remain valid.

```text
OutcomeContract {
    output_schema,
    required_facts,
    constraints,
    tolerances,
    decision_boundary,
    acceptable_equivalence,
    provenance_requirements
}
```

Contract equivalence is:

$$
A\equiv_C B
$$

meaning A and B satisfy the same declared Outcome Contract.

---

## 11.1 Contract types

### Exact

Example:

```text
17 × 43
```

Correctness:

```text
exact equality
```

### Set-valued

Example:

```text
transactions with >20% increase
```

Correctness:

```text
same qualifying set
```

### Approximate numeric

Example:

```text
risk estimate
```

Correctness:

```text
error <= declared tolerance
```

### Decision

Example:

```text
Escalate / don't escalate
```

Correctness:

```text
same decision under declared policy
```

### Structured explanation

Required facts must remain present.

Wording can differ.

### No-solution

Explicit insufficiency is a valid contract outcome.

This becomes particularly important in G4.

---

# 12. Local State Fabric

Four state classes.

| State         | Contents                                            | Lifetime                        |
| ------------- | --------------------------------------------------- | ------------------------------- |
| Working       | session state, active buffers, KV-like state        | short-lived                     |
| Semantic      | facts, entities, preferences                        | long-lived                      |
| Computational | outputs, dependencies, proofs, bounds, cost history | long-lived, conditionally valid |
| Archive       | compressed provenance/audit history                 | cold/on-disk                    |

Lifecycle:

```text
created
→ verified
→ active
→ stale
→ superseded
→ archived
→ deleted
```

---

# 13. Dependency model

This is one of CNE's most important implementation areas.

A dependency model based only on "rows actually read" is insufficient.

Example:

```text
Aggregate(Category=Food)
```

currently uses:

```text
41
58
61
77
```

A new Travel transaction should not invalidate it.

A new Food transaction must invalidate it.

Therefore dependencies have to cover both:

```text
existing matching entities
```

and:

```text
future changes that would newly satisfy the predicate
```

---

## 13.1 Two dependency granularities

### Coarse

```text
source
table
document
```

### Fine

```text
exact key
row
field
range
predicate
join relationship
```

The optimizer should use the cheapest granularity that remains correct.

---

## 13.2 Predicate/range dependency requirement

A computation over:

```text
Filter(Category == Food)
```

must be capable of receiving invalidation from:

```text
new Food row
```

even though that row did not exist when the computation was created.

Equivalent implementation mechanisms are acceptable:

```text
predicate subscriptions
range subscriptions
index-aware change notifications
predicate-version tracking
equivalent mechanisms
```

The implementation can choose the concrete structure.

The semantic requirement is what matters.

---

## 13.3 Architectural Boundary: Mutation Notification Authority

Validity checking of fine-grained dependencies is sound *only if every underlying data mutation routes through `notify_data_mutation()`* on the State Fabric / Dependency Manager.

There is no ambient out-of-band polling or independent inspection of arbitrary external data sources at query time. Therefore:
1. Every state mutation path (including real external data sources, database hooks, filesystem watchers, or synthetic mutation generators added during P1+ integration) **must invoke `notify_data_mutation()`**.
2. Any unnotified mutation violates the soundness invariant of the fine-grained dependency snapshot, causing stale memo entries to appear active.
3. This is a hard architectural boundary on the data ingestion contract, not an optional runtime optimization.

---

# 14. Computational memory correctness

Persistence must never silently change correctness.

Eviction may reduce reuse and increase cost.

It must not alter:

```text
contract correctness
dependency soundness
audit semantics
```

Storage/eviction is therefore a performance issue, not a semantic bypass.

Retention policy must exist before P0.6e.

---

# 15. State Reuse Ratio

Add this measurement to G3.

$$
StateReuseRatio
=
\frac{
UsefulPriorStateReused
}{
TotalStateCreated
}
$$

"Useful" means the prior state actually avoids or replaces computation.

Mere storage or retrieval does not count.

Measure it over a clearly defined evaluation window.

---

# 16. Amortized Computation Savings

Also add to G3.

$$
AmortizedSavings
=
\frac{
C_{\text{from-scratch}}
-
C_{\text{stateful}}
}{
N_{\text{subsequent tasks}}
}
$$

The stateful cost must include:

```text
state lookup
dependency validation
state management
storage overhead
actual execution
```

Otherwise the metric can make persistence look artificially cheap.

P0.6e passes only if persistence creates genuine computational benefit, not merely persistent files.

---

# 17. `Choose`

The objective is frozen.

$$
a^*
=
\arg\max_a E[\Delta U(a)]
$$

subject to:

$$
C_i(a)\le B_i
$$

for:

```text
latency
energy
memory
CPU
thermal
```

Do not collapse raw units into an arbitrary scalar.

`LocalUtility` is a temporary restricted form of `OutcomeContract`:

```text
scalar terminal utility
+
decision boundary
```

---

## 17.1 Build order

1. Exact finite oracle.
2. Confirm Semantic IR represents the action loop.
3. Greedy `Choose`.
4. Compare greedy against oracle.
5. If necessary, bounded lookahead depth 2–3.
6. Only then learned policy.

Pass criterion:

$$
\ge4/5
$$

test scenarios must match the hand-computed oracle.

No learned policy before this.

---

# 18. Necessity Analyzer

The analyzer has two passes.

## Static pass

Order:

```text
reachability
→ constant folding
→ static effect analysis
→ static dependency slicing
→ exact contract simplification
```

Use:

```text
E_static
```

for effect analysis.

Never use runtime path knowledge during static analysis.

---

## Runtime pass

Order conceptually:

```text
memo validity
→ dependency validation
→ specialization
→ bounds
→ Choose
→ device/resource constraints
→ update cost observations
```

The precise internal order can be tuned without changing the architecture.

---

# 19. Cost gate

```text
if class_prior_cost(query_class) < THRESHOLD:
    execute directly
else:
    run analyzer
```

Do not attempt to estimate full execution cost by already doing the expensive work.

The threshold is intended as a **P1 gate**, not a P0.6 blocker.

It requires:

```text
cost-class taxonomy
+
real per-class cost observations
```

from earlier phases.

---

# 20. G2 oracle

This is the formal recoverable-computation upper-bound experiment.

Let:

$$
\mathcal A(G,S,C)
$$

be the set of admissible, information-honest, contract-testable execution plans.

The oracle chooses:

$$
G^*
=
\arg\min_{G'\in\mathcal A(G,S,C)}
C(G')
$$

subject to:

$$
G'\equiv_C G
$$

and:

$$
R^*
=
\frac{
C_{\text{baseline}}-C(G^*)
}{
C_{\text{baseline}}
}
$$

---

# 21. G2 admissibility rules

An intervention is admissible only if it:

1. preserves graph typing,
2. preserves control semantics,
3. explicitly satisfies downstream inputs,
4. preserves required effects,
5. remains testable under the same Outcome Contract,
6. uses only information available before the skipped work.

---

## 21.1 Information availability

Required:

$$
I_{\text{intervention}}
\subseteq
I_{\text{available before skipped work}}
$$

Allowed information:

```text
current inputs
persistent computational state
dependency metadata
pre-established proofs
pre-established bounds
Outcome Contract
already-computed upstream values
```

Not allowed:

```text
output of the computation being skipped
```

---

# 22. G2 hindsight-validation distinction

This distinction must be encoded explicitly.

The oracle **may use the baseline execution's result offline to validate whether a candidate intervention satisfies the contract**.

It may not use that result to manufacture the intervention itself.

So:

```text
Allowed:

candidate intervention
        ↓
run baseline offline
        ↓
compare candidate vs baseline under C

Not allowed:

run baseline
        ↓
observe output X
        ↓
invent "replace computation with X"
        ↓
claim recoverable savings
```

The latter is omniscience, not optimization.

---

# 23. G2 train/evaluation split

This is now mandatory.

For evaluated query \(q\):

```text
training corpus must exclude q
```

Exclusion covers:

```text
q input
q output
q-derived artifacts
q-specific proofs
q-specific bounds
q-specific learned statistics
q-specific optimization artifacts
```

A bound learned from a corpus containing the evaluated query is contaminated.

The same principle should apply to learned cost priors and policies once those become data-driven.

---

# 24. Primary cost metric `C`

Before G2/G3 results are generated, declare the primary scalar cost metric.

Do not silently switch among:

```text
latency
CPU
energy
RAM
thermal
```

A clean initial choice is:

```text
C = wall-clock execution latency
```

with the other resource metrics recorded separately.

The important requirement is that the primary metric be:

```text
predeclared
measurable
identical across baseline/CNE comparisons
```

---

# 25. G3 cost decomposition

Define:

$$
C_{\text{CNE}}(q)
=
C_{\text{CNE-control}}(q)
+
C_{\text{CNE-execution}}(q)
$$

Control includes everything CNE does to decide, validate, plan, or persist.

That includes:

```text
semantic compilation
signature generation
effect propagation
dependency lookup/checking
memo lookup
cost-gate evaluation
necessity analysis
Choose
physical lowering/planning
verification/auditing
state persistence
other CNE decision machinery
```

Execution is the actual work performed after CNE has made its choices.

---

# 26. Instrumentation boundary

This boundary must be implemented and verified **before any `A` number is reported**.

In particular:

```text
memo lookup
dependency validation
cost-gate evaluation
effect propagation
signature generation
physical planning/lowering
```

are control overhead.

They must not accidentally appear inside execution time.

Instrument separate timers/counters for:

```text
control
execution
verification
persistence
```

Then demonstrate that:

$$
C_{\text{CNE}}
=
C_{\text{CNE-control}}
+
C_{\text{CNE-execution}}
$$

within measurement tolerance.

---

# 27. Optimizer overhead `A`

Per query:

$$
A(q)
=
\frac{
C_{\text{CNE-control}}(q)
}{
C_{\text{baseline}}(q)
}
$$

Also compute corpus-level:

$$
A_{\text{corpus}}
=
\frac{
\sum_q C_{\text{CNE-control}}(q)
}{
\sum_q C_{\text{baseline}}(q)
}
$$

The primary G3 rule can use the corpus-level form:

$$
A_{\text{corpus}}\le20\%
$$

while preserving the per-query distribution.

---

# 28. G3 net savings

Per query:

$$
\Delta C(q)
=
C_{\text{baseline}}(q)
-
C_{\text{CNE}}(q)
$$

Primary corpus condition:

$$
\Delta C_{\text{total}}
=
\sum_i
[
C_{\text{baseline}}(q_i)
-
C_{\text{CNE}}(q_i)
]
>0
$$

and:

$$
A_{\text{corpus}}\le20\%
$$

Secondary reporting:

```text
median per-query savings
p95 per-query overhead
fraction of queries with negative savings
State Reuse Ratio
Amortized Computation Savings
```

Do not collapse the secondary distribution into a pass/fail rule yet.

---

# 29. Isolation of optimizer overhead

Measure `A` partly on cases where CNE eventually chooses:

```text
full baseline-equivalent execution
```

This gives a cleaner estimate of control cost.

The purpose is to prevent the savings mechanism from artificially hiding its own control overhead.

---

# 30. G4 incremental correctness

G4 must prove two things:

## Correctness

$$
A\equiv_C B
$$

where:

```text
A = incremental stateful execution
B = clean-slate recomputation
```

## Selectivity

Only the stale dependency cone may execute again, unless an explicitly justified admissible intervention applies.

So G4 requires both:

```text
contract-equivalent result
+
correct selective recomputation trace
```

A system that recomputes the entire graph and gets the correct answer has not demonstrated incremental execution.

---

# 31. G4 test matrix

The 100-case synthetic suite must explicitly cover:

```text
matching-row insertion
nonmatching-row insertion

matching-row deletion
nonmatching-row deletion

predicate-field modification
key modification

rows entering a range
rows leaving a range

join-key appearance
join-key disappearance
```

---

# 32. G4 no-solution cases

Add:

### Case A: genuine insufficiency

Baseline:

```text
insufficient evidence
```

CNE:

```text
insufficient evidence
```

and the skipped computation would not have changed the result.

Must pass.

### Case B: spurious insufficiency

CNE skips a branch that would have generated required evidence.

CNE:

```text
insufficient evidence
```

Baseline:

```text
actual answer
```

This is a false-prune failure.

Must be caught.

Merely matching the string `"insufficient evidence"` is not sufficient to establish contract equivalence.

---

# 33. G5 verification model

Three levels.

| Level     | Evidence                                                   | Permitted claim                          |
| --------- | ---------------------------------------------------------- | ---------------------------------------- |
| Certified | proof, dependency theorem, exact bound, contract invariant | "This node cannot affect the outcome."   |
| Audited   | model score, sampling, historical success                  | "We predict this can be safely omitted." |
| Fallback  | full execution                                             | no optimization claim                    |

Only Certified can make the absolute safety claim.

---

# 34. G5 confidence terminology

Keep these separate:

```text
model confidence score >= 0.9
```

versus:

```text
statistical confidence level = 95%
```

They are not the same thing.

---

# 35. G5 calibration

Bootstrap:

```text
offline synthetic tasks
+
full forced verification
+
online forced verification of random 10% of all prunes
+
conservative 0.9 model-confidence warm start
```

The sample floor:

$$
n\ge460
$$

applies specifically to labeled prunes inside the:

```text
model confidence >= 0.9
```

region.

It does not mean 460 total prunes proves 95% correctness.

---

# 36. G5 acceptance criterion

Before results are seen, freeze:

```text
confidence interval method
confidence level
sample handling rule
```

The intended starting choice can be:

```text
Wilson interval
95% confidence level
```

but the important part is the **pre-declaration**.

Then:

$$
LB_{\text{CI}}
\ge95\%
$$

must hold for prune correctness.

Observed accuracy alone is insufficient.

---

# 37. G6 threshold-freezing protocol

This needs to be a separate, timestamped experiment step.

### Step 1

Run **P4 baseline characterization only**.

No CNE comparison results are available to the threshold-setting process.

### Step 2

Determine the acceptable thresholds for:

```text
latency
energy
thermal
RAM
```

using the baseline characterization methodology.

### Step 3

Create a timestamped threshold-freeze artifact.

Example conceptually:

```text
g6_thresholds/
    baseline_characterization.json
    thresholds_frozen.json
    timestamp.txt
```

### Step 4

After freezing, run CNE.

No threshold modification based on observed CNE performance.

This prevents post-hoc goal-setting.

---

# 38. G7 USB rule

CPU-only CNE must independently satisfy G6.

USB may:

```text
extend feasible workload range
```

but cannot be necessary to establish the core benefit.

The phone remains authoritative.

Transmit coarse compiled jobs/subgraphs rather than constantly streaming huge tensor states back and forth.

---

# 39. Ablation ladder

Baseline ladder:

```text
B(-1) Oracle upper bound
        ↓
B0 Direct baseline
        ↓
B1 Semantic representation
        ↓
B2 Persistent state
        ↓
B3 Dependency invalidation
        ↓
B4 Static elimination
        ↓
B5 Runtime necessity
        ↓
B6 Bounds
        ↓
B7 Learned controller
```

Optimization Capture:

$$
OptimizationCapture
=
\frac{
CNE\ savings
}{
Oracle\ maximum\ savings
}
$$

This tells you how much of the theoretically recoverable opportunity CNE actually captures.

---

# 40. Leave-one-out ablation

The incremental ladder alone is insufficient because components may interact.

Run:

```text
full system minus B1
full system minus B2
full system minus B3
...
full system minus B7
```

Compare those results with the standard incremental ladder.

If the two attribution approaches disagree materially, record the interaction.

Do not assume:

$$
Effect(A+B)=Effect(A)+Effect(B)
$$

For example, dependency invalidation can make runtime necessity dramatically more useful on recurring workloads.

---

# 41. Phase plan

## P0: Executor

Build the minimum execution engine capable of executing typed Semantic IR.

Required:

```text
typed nodes
deterministic execution
collections
control regions
basic contracts
basic dependency objects
```

Do not build:

```text
LLM compiler
learned policy
Android packaging
USB acceleration
```

yet.

---

# 42. P0.5: Break Test

Purpose:

> deliberately try to break the semantic execution foundation.

Test:

```text
type violations
invalid edges
missing inputs
incorrect branch activation
effect propagation errors
lazy-control violations
invalid dependency identities
contract mismatches
deterministic replay
```

The objective is not optimization.

It is finding whether the executor is semantically trustworthy enough to become the foundation for optimization experiments.

---

# 43. P0.6a: Workload structure and signatures

Corpus:

```text
200 queries
100 expense
100 troubleshooting
```

plus explicit adversarial cases.

Build:

```text
paraphrase groups
anti-reuse pairs
false-difference pairs
different-topology fixtures
```

Run:

```text
G0
G1a
G1b
G1c
```

before continuing.

---

# 44. G0

Standalone fixtures:

```text
expense
troubleshooting
scheduling
```

All three must be representable with:

```text
≤2 new primitives
zero domain-specific nodes
```

G0 is a **smoke test**, not evidence of general expressiveness.

Do not report:

```text
"G0 passed, therefore CNE is expressive."
```

Correct interpretation:

```text
"The frozen semantic primitive set can represent the three required starter fixtures."
```

---

# 45. P0.6b: Cross-domain Semantic IR

Required evidence:

```text
executable Semantic IR
baseline execution cost
```

Test the same primitives across domains rather than adding special-purpose nodes.

The goal is to determine whether domain variation is represented through composition rather than architecture growth.

---

# 46. P0.6c: `Choose`

Build only:

```text
exact finite decision oracle
```

then:

```text
Semantic representation
→ greedy policy
→ oracle comparison
```

No learned controller yet.

Pass:

$$
4/5
$$

or better against the exact oracle.

If greedy fails, use depth:

```text
2–3 bounded lookahead
```

before introducing learning.

---

# 47. P0.6d: Full Outcome Contract + Static Optimizer

Implement:

```text
OutcomeContract
effect analysis
reachability
constant folding
partial evaluation
dependency slicing
contract simplification
control/execution instrumentation
```

The instrumentation boundary must be validated here before any G3 `A` figure.

This phase is also where the cost-accounting architecture becomes measurable.

---

# 48. P0.6e: Persistent State

Implement:

```text
working state
semantic state
computational state
archive
```

with:

```text
validity lifecycle
dependency tracking
predicate-aware invalidation
retention/eviction
provenance
```

Then test:

```text
G4
State Reuse Ratio
Amortized Computation Savings
```

---

# 49. P1: Learned Controller

Only after:

```text
G0
G1
P0.6b
P0.6c
P0.6d
P0.6e
```

are functioning.

The learning loop may improve:

```text
signature mapping
cost priors
policy decisions
necessity scores
```

but safety rules are not modified autonomously.

---

# 50. P2: State Reuse

Now evaluate repeated/related workloads.

Focus on:

```text
memo validity
dependency invalidation
state reuse
incremental recomputation
amortized savings
```

This is where "computation becomes cheaper over time" becomes experimentally measurable.

---

# 51. P3: Necessity Optimizer

This is the first phase that should generate the real:

```text
recoverable mass R*
optimizer overhead A
```

against the fixed oracle.

Required outputs:

```text
baseline cost
oracle cost
CNE cost
control cost
execution cost
R*
A
ΔC_total
median savings
p95 overhead
negative-savings fraction
State Reuse Ratio
Amortized Computation Savings
```

---

# 52. P4: Bounds + Lookahead

Only after the basic optimizer establishes its actual savings.

Implement:

```text
learned bounds
bounded lookahead
```

Do not build complicated lookahead mechanisms before the simpler strategy demonstrates a need for them.

This is also where the final baseline characterization for G6 should occur.

---

# 53. P5: Calibration + Audit

Implement:

```text
certified evidence
audited evidence
fallback
sampling
confidence calibration
CI-based G5 gate
```

The evaluation split and sampling rules must already be frozen.

---

# 54. P6: Android deployment

Only after the execution/optimization system works in controlled environments.

Target:

```text
Android
6–8 GB RAM
ARM CPU
offline
no NPU assumption
```

Measure:

```text
latency
energy
RAM
thermal behavior
```

against the frozen G6 thresholds.

---

# 55. P7: USB tier

Only after G7's CPU-only path is established.

USB exists to:

```text
expand feasible execution
```

not:

```text
rescue an otherwise invalid CNE architecture
```

---

# 56. Engineering layout

Recommended starting repository:

```text
/cne
  /semantic_ir
      nodes
      types
      regions
      evaluator

  /contracts
      outcome_contract
      local_utility

  /effects
      effect_set
      propagation
      execution_policy

  /signature
      shape_key
      memo_key
      cost_class
      policy_state
      canonicalization

  /compiler
      deterministic_fixtures
      fixture_compiler
      nl_compiler       # later

  /optimizer
      /static
          reachability
          folding
          slicing
          contract_simplification

      /runtime
          memo
          dependencies
          predicate_dependencies
          bounds
          cost_gate
          choose

  /state
      /working
      /semantic
      /computational
      /archive
      retention
      eviction

  /executor
      /deterministic
      /retrieval
      /neural
      /tools

  /planner
      physical_lowering
      cpu
      neural
      retrieval
      usb

  /verify
      certified
      audited
      fallback
      calibration

  /bench
      corpus
      fixtures
      g0
      g1
      g2_oracle
      g3_measurement
      g4_state
      g5_calibration
      ablations

  /artifacts
      thresholds
      reports
      manifests
      provenance

  /tests
      unit
      property
      integration
      gate
```

This is a decomposition of the frozen architecture, not a new architecture.

---

# 57. Implementation language strategy

Prototype semantics in:

```text
Python
```

Use it for:

```text
P0
P0.5
P0.6
oracle
benchmarking
measurement
```

Port stable core components to:

```text
Rust
```

before making performance claims.

Do not optimize Python prematurely.

The research question is computation reduction, not "how fast can we make a badly measured Python prototype."

---

# 58. Benchmark discipline

Every benchmark must freeze:

```text
input corpus
dataset snapshot
software revision
configuration
device
execution mode
random seed where applicable
primary cost metric
evaluation partition
thresholds
```

No comparison should silently change any of those.

---

# 59. Train/test contamination rule

This applies beyond G2.

Any artifact influencing a query's optimization decision must be trained or derived without using:

```text
that query
its output
or artifacts derived from it
```

This includes:

```text
learned bounds
cost priors
learned policies
calibration models
query-specific optimization statistics
```

A model that "already saw the answer" is not a valid demonstration of predictive optimization.

---

# 60. G3 aggregation

Report:

### Primary

$$
\Delta C_{\text{total}}
$$

### Secondary

```text
median per-query savings
p95 per-query overhead
negative-savings fraction
State Reuse Ratio
Amortized Computation Savings
```

Do not rely only on mean savings.

Do not later change aggregation simply because one aggregation makes the system look better.

---

# 61. Current gate table

| Gate | Requirement                                                                            |
| ---- | -------------------------------------------------------------------------------------- |
| G0   | Three standalone fixtures representable, ≤2 new primitives, zero domain-specific nodes |
| G1a  | ≥80% paraphrase-group invariance                                                       |
| G1b  | Distinct genuine topologies → distinct shape keys                                      |
| G1c  | Anti-reuse memo keys differ; false-difference shape+cost match                         |
| G2   | Information-honest admissible intervention oracle                                      |
| G3   | Positive total savings + corpus overhead \(A\le20\%\)                                  |
| G4   | 100/100 contract-correct selective incremental state tests                             |
| G5   | ≥460 high-confidence-region labels + CI lower bound ≥95%                               |
| G6   | Frozen baseline-only resource thresholds passed                                        |
| G7   | CPU-only path independently clears G6                                                  |

---

# 62. Optimization Capture

Use:

$$
OptimizationCapture
=
\frac{
CNE\ Savings
}{
Oracle\ Maximum\ Savings
}
$$

Interpret carefully.

A low number can mean:

```text
the available opportunity was small
```

or:

```text
the optimizer failed to capture available opportunity
```

That is why the oracle and the ablation ladder exist.

---

# 63. Failure diagnosis rule

When something fails:

### Do not immediately add architecture.

First classify the failure as one of:

```text
primitive-set failure
workload-assumption failure
cost-model failure
optimization-mechanism failure
measurement failure
implementation bug
```

Then repair that specific category.

This rule remains binding.

---

# 64. What must not be built early

Before G0/G1, do **not** build:

```text
learned necessity model
large neural controller
full NL compiler
Android runtime
USB execution
complex RL policy
large persistent memory subsystem
fancy vector database
domain-specific primitives
```

The first implementation should be deliberately boring.

That is good.

---

# 65. Exact first implementation sequence

Start from an empty repository.

### Step 1

Create the Semantic IR types.

### Step 2

Create deterministic executor.

### Step 3

Implement effect sets and propagation.

### Step 4

Implement lazy `Branch` and `Iterate`.

### Step 5

Implement `OutcomeContract`.

### Step 6

Implement Computational Signature projections.

### Step 7

Implement three G0 fixtures:

```text
expense
troubleshooting
scheduling
```

### Step 8

Build G1 corpus infrastructure.

### Step 9

Run:

```text
G0
G1a
G1b
G1c
```

### Step 10

Do not proceed to learned optimization because the temptation will be enormous and largely unhelpful.

### Step 11

Build G2 oracle.

### Step 12

Build exact `Choose` oracle.

### Step 13

Build static optimizer.

### Step 14

Build persistent computational state.

### Step 15

Build predicate-aware dependency tracking.

### Step 16

Run G4 state correctness.

### Step 17

Implement G3 instrumentation and full cost accounting.

### Step 18

Run P3 to obtain actual \(R^*\), \(A\), and savings.

### Step 19

Only then build learned controller/bounds/lookahead where justified.

---

# 66. Evidence hierarchy

Keep these distinctions explicit in every report.

```text
Implementation works
        ≠
Semantic primitive set is adequate
        ≠
Signature works
        ≠
Computation savings exist
        ≠
Savings exceed optimizer overhead
        ≠
Savings persist over state reuse
        ≠
Learned pruning is calibrated
        ≠
Real Android hardware benefits
```

Each requires its own gate.

---

# 67. What the research must ultimately demonstrate

The architecture is not the research result.

The meaningful evidence chain is:

```text
Workload structure
        ↓
Reusable computational structure exists
        ↓
Relevant state can remain valid
        ↓
Some computation can be eliminated/reused
        ↓
Oracle establishes available recoverable mass
        ↓
CNE captures some fraction of it
        ↓
Optimization overhead does not erase savings
        ↓
Incremental state stays correct
        ↓
Learned elimination can be calibrated
        ↓
CPU-first Android deployment retains the benefit
```

And the ablation system determines which mechanism actually contributed.

---

# 68. Business/research boundary

Keep business material outside the technical core specification.

The business-side claim should eventually be evaluated separately around:

```text
lower total cost of ownership
data locality/control
offline capability
domain-specific deployment
persistent computational savings
```

Do not make unsupported claims such as "data never leaves the device" merely because the architecture is local. That would require deployment guarantees such as network controls, sandboxing, package integrity, encryption, and auditing.

The important dependency is:

```text
Track A: CNE research
Track B: product/business
```

Track B does not need the entire CNE research program to start exploring product applications.

The specific product property that does depend on later CNE evidence is:

```text
compounding cheaper-over-time execution
```

because that requires P2/P3 evidence of useful state reuse and amortized savings.

Keep that dependency recorded in the business boundary document rather than reopening this architecture specification.

---

# 69. Final "do not reinterpret" rules

These are the rules I would literally put at the top of your local repository.

```text
1. The architecture is frozen.

2. Semantic IR is hardware-agnostic.

3. Branch and Iterate are lazy.

4. Effects are sets, never a severity hierarchy.

5. Static analysis uses conservative reachable-region effects.

6. Runtime knowledge may not leak backward into static analysis.

7. Shape key, memo key, cost class, and policy state are separate projections.

8. Memo validity requires all output-determining execution semantics to match
   or be contract-equivalent.

9. Outcome correctness is contract equivalence, not always byte equality.

10. Fine-grained dependency tracking must handle future matching inserts,
    not just previously read rows.

11. G2 may use baseline output to validate candidate interventions,
    but not to invent the intervention.

12. G2 candidate information must be available before skipped work executes.

13. G2/G5 learned artifacts must use clean evaluation splits.

14. CNE control overhead includes decision, validation, planning, lookup,
    analysis, and persistence work.

15. No A number is reported before control/execution instrumentation is verified.

16. G3 uses a predeclared scalar primary cost metric.

17. G4 requires both contract correctness and stale-cone execution correctness.

18. No-solution is a real contract case and must be tested.

19. 460 is a sample floor, not proof of 95% correctness.

20. G5 uses a predeclared statistical acceptance rule.

21. G6 thresholds are frozen from baseline-only characterization before
    CNE results are seen.

22. CPU-only must clear G6 before USB is relevant.

23. Incremental ablations do not imply additive effects.

24. Run leave-one-out ablations before making component-attribution claims.

25. Experiment failure does not automatically justify a new architecture component.

26. Python first, Rust before performance claims.

27. No learned controller before the exact oracle and foundational gates work.

28. No Android/USB optimization work before the research core earns it.
```

---

# 70. The actual starting point

Your local project should therefore begin as:

```text
EMPTY REPOSITORY
        ↓
Semantic types
        ↓
Deterministic executor
        ↓
Effects
        ↓
Contracts
        ↓
Signatures
        ↓
3 G0 fixtures
        ↓
G0
        ↓
200-query G1 corpus
        ↓
G1a / G1b / G1c
        ↓
STOP IF FAILED
        ↓
G2 information-honest oracle
        ↓
Choose oracle
        ↓
Static optimizer
        ↓
Persistent state
        ↓
Predicate-aware dependencies
        ↓
G4
        ↓
Cost instrumentation
        ↓
P3 / G2 / G3
        ↓
Ablations
        ↓
Learned controller
        ↓
Calibration
        ↓
Android
        ↓
USB
```

## Final status

**This is the build plan I would use now.**

The architecture is frozen. The remaining work is implementation, instrumentation, benchmark discipline, and falsification. The most important thing you can do differently from the earlier iterations is **stop revising the architecture unless an experiment proves the architecture itself is wrong**.

Everything before G2 should be relatively small and deterministic. Once G0/G1 are genuinely passing from your own scratch implementation, the project stops being a design exercise and becomes an empirical one. That is the point at which the numbers get to decide whether CNE is actually doing anything interesting.
