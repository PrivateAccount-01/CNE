# Phase P0.8 Deliverable 3: Domain Triage of Blind-Corpus Workload

**Status:** Completed  
**Author:** CNE Architecture & Systems Team  
**Scope:** Formal classification and architectural boundary analysis of the 8 zero/near-zero-coverage domains identified during Phase P0.7 and Phase P0.8 topology-blind workload evaluations.

---

## 1. Executive Summary & Triage Overview

In Phase P0.7 and P0.8, an unguided, multi-domain topology-blind evaluation consisting of **600 natural personal assistant requests across 12 distinct domains** was submitted to the compiler without topology hints or structural guidance. While core structured-data domains (finances, schedule, health/fitness, shopping/inventory) achieved meaningful compilation and novel shape emergence, 8 domains exhibited zero or near-zero coverage.

This document establishes the explicit technical, algebraic, and state-fabric rationale for each of those 8 domains. No new templates are constructed by default; only domains classified as **`IN SCOPE, CHEAP`** are eligible for immediate template integration, while **`IN SCOPE, DEFERRED`** domains define requirements for future State Fabric connectors, and **`OUT OF SCOPE`** domains define explicit rejection boundaries for Phase P1's learned controller.

### Domain Triage Summary Table

| Domain | Empirical Coverage (P0.8) | Classification | Primitives Required | Architectural Prerequisite / Boundary Justification |
| :--- | :---: | :---: | :---: | :--- |
| **`system_settings_device`** | 0.0% (0/50) | **OUT OF SCOPE** | None | Imperative OS device actuation ($\text{Eff} \supseteq \{\text{WriteExternal}, \text{StateMutate}\}$); un-memoizable hardware action. |
| **`communication_messaging`** | 0.0% (0/50) | **IN SCOPE, DEFERRED** | 0 new (`Observe`, `Filter`, `Emit`) | Read queries require Messaging State Fabric adapter; message sending is an un-memoizable external side-effect. |
| **`file_data_management`** | 0.0% (0/50) | **IN SCOPE, DEFERRED** | 0 new (`Observe`, `Filter`, `Emit`) | Read metadata search requires Filesystem Index Observer; destructive file mutation/deletion is out of scope. |
| **`home_automation_iot`** | 0.0% (0/50) | **IN SCOPE, DEFERRED** | 0 new (`Observe`, `Filter`, `Reduce`, `Emit`) | Telemetry queries require High-Frequency Streaming State Fabric; physical device actuation is out of scope. |
| **`media_entertainment`** | 0.0% (0/50) | **OUT OF SCOPE** | None | Playback control is external app actuation; media trivia is open QA. No user-owned structured state DAG. |
| **`open_web_search_knowledge`** | 0.0% (0/50) | **OUT OF SCOPE** | None | Open-world unconstrained external information retrieval; distinct from personal structured computation reduction. |
| **`math_calculations`** | 0.0% (0/50) | **IN SCOPE, CHEAP** | 0 new (`Literal`, `Map`, `Emit`) | Template only (`Literal -> Map -> Emit`). Degenerate zero-state computation with $R^* \approx 0$ (no state reuse). |
| **`creative_brainstorming`** | 12.0% (6/50) | **OUT OF SCOPE** | None | Stochastic autoregressive text generation; non-deterministic ($\tau > 0$), zero subexpression cache reuse. |

---

## 2. Per-Domain Architectural Rationale

### 2.1 `system_settings_device` (0.0% Coverage) — **OUT OF SCOPE**
Requests in this domain (e.g., *"Turn on Bluetooth"*, *"Set display brightness to 70%"*, *"Mute all notifications until tomorrow morning"*) represent imperative hardware actuation calls. Under CNE's Atomic Effect Algebra (§3 of Theory), these operations declare mandatory side-effects $\text{Eff} \supseteq \{\text{WriteExternal}, \text{StateMutate}\}$ and an execution policy of `Never` or `Ask` in automated pipelines. They produce no reusable intermediate analytical state, do not compute reductions over personal records, and cannot be memoized or soundly eliminated. CNE is a computational necessity engine over personal state graphs, not an OS device driver or RPC router; routing hardware commands into CNE would introduce control overhead with zero recoverable mass ($R^* = 0$).

### 2.2 `communication_messaging` (0.0% Coverage) — **IN SCOPE, DEFERRED**
This domain exhibits a bimodal structure. Active message transmission (e.g., *"Send a text to John saying I'm running 10 minutes late"*, *"Draft an email to the project team"*) constitutes external non-idempotent side-effects ($\text{WriteExternal}$) that bypass memoization. Conversely, read-only message search and metadata querying (e.g., *"Show unread Slack messages from yesterday matching project X"*, *"Find emails from Alice with PDF attachments"*) map cleanly to CNE's existing primitive set: `Observe(messages) -> Filter -> Emit` with **0 new primitives**. Supporting this domain safely requires a structured **Messaging Schema Adapter** in the State Fabric (e.g., IMAP/Slack snapshot models with sound dependency keys $K = (\text{channel}, \text{thread}, \text{timestamp})$ and invalidation hooks on incoming message events). It is deferred until that state adapter is engineered.

### 2.3 `file_data_management` (0.0% Coverage) — **IN SCOPE, DEFERRED**
Read-only filesystem queries (e.g., *"Find all PDF files larger than 50MB modified this month"*, *"List images taken in Seattle in 2024"*) represent structured metadata reductions that map directly to `Observe(filesystem_index) -> Filter -> Emit` without any new primitives. However, imperative filesystem manipulations (e.g., *"Organize my Downloads folder by file type"*, *"Delete duplicate photos in Vacation folder"*) involve disk mutations that fall outside CNE's read-oriented reduction model. Read-only filesystem querying is in scope but deferred until a **Local Filesystem Index Observer** is implemented in the State Fabric, capable of tracking file-modification timestamps and emitting sound delta events $\Delta = (\text{file\_mod}, \text{path}, \text{mtime})$.

### 2.4 `home_automation_iot` (0.0% Coverage) — **IN SCOPE, DEFERRED**
Physical appliance actuation (e.g., *"Turn off living room lights"*, *"Unlock the front door"*) constitutes side-effecting hardware control and is strictly out of scope. In contrast, historical or aggregated telemetry inspection (e.g., *"What was the average temperature and humidity in the nursery over the last 24 hours?"*) is a canonical `Observe(telemetry) -> Filter -> Reduce -> Emit` computation. The technical barrier is architectural: IoT telemetry operates on high-frequency streaming deltas (Hz to kHz) with volatile time-to-live bounds, whereas CNE's current State Fabric is architected for transactional snapshot consistency (financial accounts, calendar tables). This domain is in scope for telemetry queries, but deferred until a **Streaming Time-Series State Fabric** extension is developed.

### 2.5 `media_entertainment` (0.0% Coverage) — **OUT OF SCOPE**
Requests in this domain fall into two categories: third-party streaming playback controls (e.g., *"Play lo-fi beats playlist on Spotify"*, *"Resume podcast episode from yesterday"*) and encyclopedic media trivia (e.g., *"What movie won Best Picture in 2020?"*). Media playback is external application actuation without data transformation, while trivia lookup is open-world question answering. Neither workload exercises computational necessity, dependency tracking, or state-fabric caching over user-owned structured records. Integrating this domain would misrepresent CNE's mission as an application controller rather than an analytical computation compiler.

### 2.6 `open_web_search_knowledge` (0.0% Coverage) — **OUT OF SCOPE**
Queries such as *"Who was the 16th president of the United States?"*, *"What causes the Northern Lights?"*, and *"Current population of Tokyo"* represent open-world web search and general knowledge retrieval. These operations access unconstrained, unindexed external web corpora where responses are synthesized text rather than deterministic computations over structured state. CNE's necessity model relies on well-defined dependency keys and observable state boundaries ($K = (\text{source}, \text{granularity}, \text{predicate})$); open web search has an unbounded dependency surface that cannot be soundly invalidated or cached. Modeling general web search as a CNE DAG represents a fundamental category error.

### 2.7 `math_calculations` (0.0% Coverage in P0.8; 8.0% Miscompiled in P0.7) — **IN SCOPE, CHEAP**
In Phase P0.7, 4 queries in `math_calculations` (8.0%) compiled spuriously because financial phrasing (e.g., *"What is 15 percent off of an item that costs $129.99?"*) tripped the `expense` keyword matcher and shoehorned the question into a transaction-ledger sum. In Phase P0.8, these were cleanly rejected (0.0% compiled, 0 misinterpretations). 

From a compiler representation standpoint, pure scalar math (unit conversions, tip calculations, compound interest, geometry formulas) requires **zero new primitives** and **zero new external data sources**; it is trivially expressible as `Literal(prompt_values) -> Map(formula_fn) -> Emit`. It is classified as **`IN SCOPE, CHEAP`** because it requires only a single parameterized template and zero State Fabric modifications. 

**Architectural Caveat**: Because the inputs are prompt-contained literals rather than stateful records in the State Fabric, the computation observes no persistent data source ($K = \emptyset$). Consequently, the theoretical recoverable mass is near zero ($R^* \approx 0$), as execution latency for scalar arithmetic in Python/native code ($\approx 1\,\mu\text{s}$) is far lower than compiler parsing overhead ($\approx 1\,\text{ms}$), yielding net savings $\Delta C < 0$. While cheap to template, it represents a degenerate zero-state computation that bypasses CNE's core reuse value proposition.

### 2.8 `creative_brainstorming` (12.0% Coverage) — **OUT OF SCOPE**
Requests such as *"Write a poem about autumn leaves"*, *"Brainstorm 5 name ideas for an eco-friendly coffee shop"*, and *"Draft a thank-you note to my manager"* represent open-ended generative writing. In Phase P0.8, 6 queries (12.0%) matched partial keywords, but general generation cannot be expressed as a deterministic DAG. Generative LLM synthesis is stochastic (sampling temperature $\tau > 0$), lacks formal outcome contract bounds, and possesses no subexpression recurrence or state-invalidation semantics. Open-ended text generation is the responsibility of conversational foundation models, completely outside the scope of CNE's deterministic computation compiler.

---

## 3. Downstream Implications for Phase P1

1. **Target Distribution**: Only domains classified as `IN SCOPE, CHEAP` (`math_calculations`) or `IN SCOPE, DEFERRED` (retrieval facets of `communication_messaging`, `file_data_management`, and `home_automation_iot`) are admitted into Phase P1's target evaluation universe.
2. **Explicit Rejection Boundaries**: Domains classified as `OUT OF SCOPE` (`system_settings_device`, `media_entertainment`, `open_web_search_knowledge`, `creative_brainstorming`) must be treated as explicit negative rejection cases. Phase P1's learned controller will be evaluated on its ability to classify these queries as `UNSUPPORTED_INTENT` rather than hallucinating invalid computational graphs.
