# Getting Started with CNE

Welcome to the **Computation Necessity Engine (CNE)**. This guide walks you through installing CNE, building your first semantic task graph, defining outcome contracts, executing queries, and observing computation reduction.

---

## 1. Installation

CNE is designed to be lightweight with zero external runtime dependencies.

### Prerequisites
- Python 3.10+ (Python 3.10, 3.11, or 3.12 supported)
- `pip` or virtual environment manager

### Setup

```bash
# Clone the repository
git clone https://github.com/PrivateAccount-01/CNE.git
cd CNE

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install development & test dependencies
pip install -r requirements-dev.txt
pip install -e .
```

---

## 2. Quickstart: Building and Executing a Semantic Graph

Let's build a practical computation: filtering high-value transactions and calculating their total spend under an approximate contract.

```python
from cne.semantic_ir.nodes import SemanticIRGraph, IRNode, OpKind
from cne.semantic_ir.types import SemanticType
from cne.contracts.outcome_contract import OutcomeContract, ContractType
from cne.optimizer.necessity_engine import ComputationNecessityEngine

# 1. Define the Semantic Task Graph
graph = SemanticIRGraph()

# Node 1: Observe transactions from account store
obs = IRNode(
    id="obs_transactions",
    op=OpKind.OBSERVE,
    attributes={"source": "transactions", "granularity": "predicate"},
    output_type=SemanticType.collection(SemanticType.record({
        "id": SemanticType.string(),
        "amount": SemanticType.numeric(),
        "category": SemanticType.string()
    }))
)
graph.add_node(obs)

# Node 2: Filter for amount > 50.0
filt = IRNode(
    id="filter_high_value",
    op=OpKind.FILTER,
    inputs=["obs_transactions"],
    attributes={"predicate": lambda tx: tx["amount"] > 50.0}
)
graph.add_node(filt)

# Node 3: Map to extract amount
map_amt = IRNode(
    id="map_amounts",
    op=OpKind.MAP,
    inputs=["filter_high_value"],
    attributes={"fn": lambda tx: tx["amount"]}
)
graph.add_node(map_amt)

# Node 4: Reduce to compute sum
red = IRNode(
    id="reduce_sum",
    op=OpKind.REDUCE,
    inputs=["map_amounts"],
    attributes={"op": lambda a, b: a + b, "init": 0.0}
)
graph.add_node(red)

# Node 5: Emit result
emit = IRNode(
    id="emit_total",
    op=OpKind.EMIT,
    inputs=["reduce_sum"]
)
graph.add_node(emit)
graph.root_id = "emit_total"

# 2. Define Outcome Contract (Allowing 1% tolerance)
contract = OutcomeContract(
    contract_type=ContractType.APPROXIMATE,
    epsilon=0.5,
    relative_epsilon=0.01
)

# 3. Initialize Environment Data
env = {
    "transactions": [
        {"id": "tx_1", "amount": 120.0, "category": "Electronics"},
        {"id": "tx_2", "amount": 25.0,  "category": "Coffee"},
        {"id": "tx_3", "amount": 80.0,  "category": "Groceries"},
        {"id": "tx_4", "amount": 15.0,  "category": "Transport"},
    ]
}

# 4. Execute with CNE
engine = ComputationNecessityEngine()

# First run: compiles, evaluates, and stores in Local State Fabric
result1 = engine.execute_query(graph, contract, env, query_id="query_01")
print(f"First execution total: ${result1.value:.2f}")
print(f"Reused State: {result1.reused_state} | Execution Latency: {result1.costs.execution_ns / 1000:.1f} µs")

# Second run with same state: 0 execution cost, direct memo hit!
result2 = engine.execute_query(graph, contract, env, query_id="query_02")
print(f"Second execution total: ${result2.value:.2f}")
print(f"Reused State: {result2.reused_state} | Execution Latency: {result2.costs.execution_ns / 1000:.1f} µs")
```

---

## 3. Running the Test Suites

### Extreme Black-Box Stress Tests (148 Tests)
To run the full extreme testing suite across all 8 modules:

```bash
pytest cne/tests/extreme -v
```

Expected output:
```text
cne/tests/extreme/test_contracts_extreme.py ....................         [ 13%]
cne/tests/extreme/test_dependencies_extreme.py ....................      [ 27%]
cne/tests/extreme/test_effects_extreme.py ..............                 [ 36%]
cne/tests/extreme/test_evaluator_extreme.py .........................    [ 53%]
cne/tests/extreme/test_optimizer_extreme.py ......................       [ 68%]
cne/tests/extreme/test_signature_extreme.py ..................           [ 80%]
cne/tests/extreme/test_state_extreme.py .................                [ 91%]
cne/tests/extreme/test_verification_extreme.py ............              [100%]
============================== 148 passed in 2.23s ==============================
```

### Master Benchmark Gates (Gates G0 through G7)
To run the master benchmark gate suite:

```bash
python -m cne.bench.run_all_gates
```

### Full Unit and Property Tests
```bash
pytest cne/tests/unit cne/tests/property
```
