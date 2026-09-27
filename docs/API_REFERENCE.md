# CNE Python API Reference

This reference documents the public Python interfaces for the Computation Necessity Engine (`cne`).

---

## 1. `cne.semantic_ir` — Semantic IR & Primitives

### `IRNode`
Represents a single node in the hardware-agnostic semantic task graph.

```python
from cne.semantic_ir.nodes import IRNode, OpKind
from cne.semantic_ir.types import SemanticType

node = IRNode(
    id="filter_1",
    op=OpKind.FILTER,
    inputs=["observe_0"],
    attributes={"predicate": lambda x: x["amount"] > 100},
    output_type=SemanticType.collection(SemanticType.numeric()),
    declared_effects=None
)
```

- **`id`** (`str`): Unique identifier for the node.
- **`op`** (`OpKind`): One of the 11 frozen primitives (`OBSERVE`, `MAP`, `FILTER`, `REDUCE`, `JOIN`, `BRANCH`, `ITERATE`, `CHOOSE`, `UPDATE`, `CALL`, `EMIT`) or `LITERAL`.
- **`inputs`** (`List[str]`): List of upstream node IDs providing input data.
- **`attributes`** (`Dict[str, Any]`): Structural configuration, functions, or parameters.
- **`output_type`** (`SemanticType`): Semantic type descriptor (`numeric`, `string`, `collection`, `record`, `any`).
- **`declared_effects`** (`Optional[EffectSet]`): Explicit declared side effects.
- **`get_immediate_effects() -> EffectSet`**: Returns intrinsic immediate effects of this node.

### `SemanticIRGraph`
Represents the directed acyclic graph (DAG) of semantic computation.

```python
from cne.semantic_ir.nodes import SemanticIRGraph

graph = SemanticIRGraph()
graph.add_node(node)
order = graph.topological_order()
cloned_graph = graph.clone()
```

- **`add_node(node: IRNode)`**: Registers a node.
- **`topological_order() -> List[str]`**: Returns topologically sorted list of node IDs.
- **`clone() -> SemanticIRGraph`**: Performs a fast structural clone.

### `SemanticEvaluator`
Deterministic interpreter for Semantic IR graphs.

```python
from cne.semantic_ir.evaluator import SemanticEvaluator

evaluator = SemanticEvaluator()
result, ctx = evaluator.execute(graph, initial_env={"transactions": [...]})
```

- **`execute(graph, initial_env=None, max_iterations=1000) -> Tuple[Any, ExecutionContext]`**: Executes graph deterministically and returns computed outcome and dependency tracing context.

---

## 2. `cne.contracts` — Outcome Contracts

### `OutcomeContract`
Defines acceptable outcome tolerance and contract equivalence.

```python
from cne.contracts.outcome_contract import OutcomeContract, ContractType

contract = OutcomeContract(
    contract_type=ContractType.APPROXIMATE,
    epsilon=0.01,
    relative_epsilon=0.05
)
```

- **`contract_type`** (`ContractType`): `EXACT`, `APPROXIMATE`, `SET_EQUIVALENT`, `ORDERED_TOP_K`, `MONOTONIC`, or `DECISION_INVARIANT`.
- **`epsilon`** (`float`): Absolute numeric error tolerance.
- **`relative_epsilon`** (`float`): Relative error tolerance.
- **`top_k`** (`int`): Number of ranked elements for `ORDERED_TOP_K`.
- **`custom_equivalence`** (`Optional[Callable[[Any, Any], bool]]`): Custom equivalence predicate override.
- **`is_equivalent(v1: Any, v2: Any) -> bool`**: Tests whether two outcomes satisfy contract equivalence ($v_1 \equiv_C v_2$).
- **`satisfies_constraints(val: Any) -> bool`**: Verifies whether an outcome satisfies domain constraints.

---

## 3. `cne.effects` — Effect Algebra & Policies

### `EffectSet`
Immutable atomic effect container.

```python
from cne.effects.effect_set import EffectSet, Effect

effects = EffectSet((Effect.ReadExternal, Effect.StateMutate))
assert effects.is_pure is False
```

- **`EffectSet.pure() -> EffectSet`**: Returns empty effect set (pure).
- **`EffectSet.read_external() -> EffectSet`**: Returns `{ReadExternal}` set.
- **`union(other: EffectSet) -> EffectSet`**: Algebraic union of effects.
- **`derive_policy() -> ExecutionPolicy`**: Derives the most restrictive policy (`Never`, `Ask`, `Interactive`, `Safe`).

---

## 4. `cne.signature` — Computational Signatures

### `MemoKey`
Cryptographic identity for exact computation reuse.

```python
from cne.signature.memo_key import MemoKey

memo_key = MemoKey.from_graph(graph, input_data={"param": 100})
print(memo_key.key_hash)
```

- **`from_graph(graph, input_data=None, versions=None, dependency_snapshot=None) -> MemoKey`**: Generates SHA-256 hash over canonical topological graph representation and version vector.

### `SemanticShapeKey`
Projection capturing control-flow topology and operator types while remaining invariant to prompt phrasing.

```python
from cne.signature.shape_key import SemanticShapeKey

shape_key = SemanticShapeKey.from_graph(graph)
```

### `CostClass`
Categorizes workload complexity for runtime cost gating.

```python
from cne.signature.cost_class import CostClass, CostTier

cost_cls = CostClass.from_graph(graph, cardinality_hint=5000)
assert cost_cls.tier == CostTier.HEAVY
```

---

## 5. `cne.state` — Local State Fabric

### `LocalStateFabric`
Manages working, semantic, computational, and archive state tiers.

```python
from cne.state.fabric import LocalStateFabric
from cne.state.state_entry import StateClass

fabric = LocalStateFabric(capacity=1000)
fabric.put(
    entry_id="entry_01",
    state_class=StateClass.COMPUTATIONAL,
    value=150.0,
    memo_key=memo_key,
    contract=contract
)

cached = fabric.get_by_memo_key(memo_key)
```

- **`put(...) -> StateEntry`**: Inserts or updates an entry in the fabric.
- **`get_by_memo_key(memo_key: MemoKey) -> Optional[StateEntry]`**: O(1) lookup of active verified entries.
- **`invalidate_dependencies(deltas: List[Dict[str, Any]]) -> int`**: Evaluates invalidation predicates against stored entries and cascades `STALE` transitions.

---

## 6. `cne.optimizer` — Necessity Optimizer

### `ComputationNecessityEngine`
Master coordinator for end-to-end query execution.

```python
from cne.optimizer.necessity_engine import ComputationNecessityEngine

engine = ComputationNecessityEngine(fabric=fabric, evaluator=evaluator)
res = engine.execute_query(
    graph=graph,
    contract=contract,
    env=environment_data,
    query_id="query_123"
)

print(res.value)
print("Control Latency (ns):", res.costs.control_ns)
print("Execution Latency (ns):", res.costs.execution_ns)
print("State Reused:", res.reused_state)
```

- **`execute_query(graph, contract, env, query_id, baseline_cost_hint_ns) -> CNEExecutionResult`**:
  Executes the 10-stage pipeline: signature generation $\to$ memo lookup $\to$ cost gating $\to$ static optimization $\to$ execution $\to$ contract verification $\to$ state persistence.

### `StaticOptimizer`
Performs compile-time dead code elimination, constant folding, static slicing, and contract simplification.

```python
from cne.optimizer.static.static_optimizer import StaticOptimizer

opt = StaticOptimizer()
result = opt.optimize(graph, contract)
optimized_graph = result.optimized_graph
```

---

## 7. `cne.verify` — Verifier & Confidence Intervals

### `WilsonScoreCI`
Computes exact binomial confidence bounds for statistical auditing.

```python
from cne.verify.verifier import WilsonScoreCI

lb, ub = WilsonScoreCI.compute_interval(successes=495, total=500, confidence=0.95)
print(f"95% CI Lower Bound: {lb:.4f}")
```
