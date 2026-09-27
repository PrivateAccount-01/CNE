"""
Module 5: Signature System Extreme Tests.
18 black-box tests for shape key invariance, memo key sensitivity,
cost class boundaries, and canonical form stability.
"""
import pytest
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion
from cne.semantic_ir.types import SemanticType
from cne.signature.canonicalization import Canonicalizer
from cne.signature.shape_key import SemanticShapeKey
from cne.signature.memo_key import MemoKey, SystemVersions
from cne.signature.cost_class import CostClass, CostTier
from cne.signature.policy_state import PolicyState
from cne.signature.signature import ComputationalSignature


def _make_expense_graph(label_prefix=""):
    """Helper: builds an expense-like graph with parameterized labels."""
    g = SemanticIRGraph()
    obs = IRNode(id=f"{label_prefix}obs", op=OpKind.OBSERVE,
                 attributes={"source": "transactions", "granularity": "source",
                              "description": f"{label_prefix}Observe spending"},
                 output_type=SemanticType.collection(SemanticType.numeric()))
    g.add_node(obs)
    filt = IRNode(id=f"{label_prefix}filt", op=OpKind.FILTER,
                  inputs=[f"{label_prefix}obs"],
                  attributes={"predicate": lambda x: True,
                              "label": f"{label_prefix}filter step"},
                  output_type=SemanticType.collection(SemanticType.numeric()))
    g.add_node(filt)
    red = IRNode(id=f"{label_prefix}red", op=OpKind.REDUCE,
                 inputs=[f"{label_prefix}filt"],
                 attributes={"op": lambda a, b: a + b, "init": 0.0},
                 output_type=SemanticType.numeric())
    g.add_node(red)
    emit = IRNode(id=f"{label_prefix}emit", op=OpKind.EMIT,
                  inputs=[f"{label_prefix}red"],
                  output_type=SemanticType.numeric())
    g.add_node(emit)
    g.root_id = f"{label_prefix}emit"
    return g


# ---------- Shape Key Tests ----------

def test_shape_key_wording_invariance():
    """Different labels/descriptions → same shape key (Section 8.1, 10)."""
    g1 = _make_expense_graph("compare_spending_")
    g2 = _make_expense_graph("tell_me_how_much_")
    sk1 = SemanticShapeKey.from_graph(g1)
    sk2 = SemanticShapeKey.from_graph(g2)
    assert sk1 == sk2


def test_shape_key_topology_discrimination():
    """Different topology → different shape key (G1b)."""
    # Graph 1: Observe → Filter → Reduce → Emit
    g1 = _make_expense_graph()

    # Graph 2: Observe → Map → Emit (different topology)
    g2 = SemanticIRGraph()
    obs = IRNode(id="obs", op=OpKind.OBSERVE,
                 attributes={"source": "data", "granularity": "source"})
    g2.add_node(obs)
    m = IRNode(id="map", op=OpKind.MAP, inputs=["obs"],
               attributes={"fn": lambda x: x})
    g2.add_node(m)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["map"])
    g2.add_node(emit)
    g2.root_id = "emit"

    sk1 = SemanticShapeKey.from_graph(g1)
    sk2 = SemanticShapeKey.from_graph(g2)
    assert sk1 != sk2


def test_shape_key_caching():
    """Second call returns cached key (performance optimization)."""
    g = _make_expense_graph()
    sk1 = SemanticShapeKey.from_graph(g)
    sk2 = SemanticShapeKey.from_graph(g)
    assert sk1 is sk2  # Same object (cached)


# ---------- Memo Key Tests ----------

def test_memo_key_input_sensitivity():
    """Different inputs → different memo key (Section 8.2)."""
    g = _make_expense_graph()
    mk1 = MemoKey.from_graph(g, input_data={"query": "food expenses"})
    mk2 = MemoKey.from_graph(g, input_data={"query": "travel expenses"})
    assert mk1 != mk2


def test_memo_key_version_sensitivity():
    """Different model version → different memo key."""
    g = _make_expense_graph()
    v1 = SystemVersions(model_version="v1.5")
    v2 = SystemVersions(model_version="v2.0")
    mk1 = MemoKey.from_graph(g, versions=v1)
    mk2 = MemoKey.from_graph(g, versions=v2)
    assert mk1 != mk2


def test_memo_key_policy_and_schema_version_sensitivity():
    """Policy, knowledge, and schema versions must alter memo identity."""
    g = _make_expense_graph()
    v_base = SystemVersions()
    v_policy = SystemVersions(policy_version="2.0.0")
    v_know = SystemVersions(knowledge_version="2.0.0")
    v_schema = SystemVersions(schema_version="2.0.0")

    mk_base = MemoKey.from_graph(g, versions=v_base)
    mk_pol = MemoKey.from_graph(g, versions=v_policy)
    mk_know = MemoKey.from_graph(g, versions=v_know)
    mk_sch = MemoKey.from_graph(g, versions=v_schema)

    assert mk_base != mk_pol
    assert mk_base != mk_know
    assert mk_base != mk_sch


def test_memo_key_contract_sensitivity():
    """Different OutcomeContracts on identical graphs produce different memo keys."""
    from cne.contracts.outcome_contract import OutcomeContract, ContractType
    g = _make_expense_graph()

    c_exact = OutcomeContract(contract_type=ContractType.EXACT)
    c_approx1 = OutcomeContract(contract_type=ContractType.APPROXIMATE_NUMERIC, tolerances={"rel_tol": 1e-4})
    c_approx2 = OutcomeContract(contract_type=ContractType.APPROXIMATE_NUMERIC, tolerances={"rel_tol": 1e-2})
    c_dec = OutcomeContract(contract_type=ContractType.DECISION, decision_boundary=100.0)

    mk_exact = MemoKey.from_graph(g, contract=c_exact)
    mk_ap1 = MemoKey.from_graph(g, contract=c_approx1)
    mk_ap2 = MemoKey.from_graph(g, contract=c_approx2)
    mk_dec = MemoKey.from_graph(g, contract=c_dec)

    assert mk_exact != mk_ap1
    assert mk_ap1 != mk_ap2
    assert mk_exact != mk_dec


def test_memo_key_same_computation():
    """Same graph + same inputs → same memo key."""
    g = _make_expense_graph()
    mk1 = MemoKey.from_graph(g, input_data={"q": "test"})
    mk2 = MemoKey.from_graph(g, input_data={"q": "test"})
    assert mk1 == mk2


# ---------- Cost Class Tests ----------

def test_cost_class_trivial_graph():
    """1-node pure graph with low cardinality → TRIVIAL."""
    g = SemanticIRGraph()
    lit = IRNode(id="lit", op=OpKind.LITERAL, attributes={"value": 42})
    g.add_node(lit)
    g.root_id = "lit"
    cc = CostClass.from_graph(g, cardinality_hint=1)
    assert cc.tier == CostTier.TRIVIAL


def test_cost_class_heavy_join():
    """Graph with JOIN → should be HEAVY."""
    g = SemanticIRGraph()
    left = IRNode(id="left", op=OpKind.OBSERVE,
                  attributes={"source": "table_a"})
    right = IRNode(id="right", op=OpKind.OBSERVE,
                   attributes={"source": "table_b"})
    g.add_node(left)
    g.add_node(right)
    join = IRNode(id="join", op=OpKind.JOIN, inputs=["left", "right"])
    g.add_node(join)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["join"])
    g.add_node(emit)
    g.root_id = "emit"
    cc = CostClass.from_graph(g)
    assert cc.tier == CostTier.HEAVY


def test_cost_class_cardinality_100k():
    """Cardinality > 100k → HEAVY regardless of graph structure."""
    g = _make_expense_graph()
    cc = CostClass.from_graph(g, cardinality_hint=200000)
    assert cc.tier == CostTier.HEAVY


def test_cost_class_is_worth_optimizing():
    """TRIVIAL → not worth, others → worth optimizing."""
    g_trivial = SemanticIRGraph()
    lit = IRNode(id="lit", op=OpKind.LITERAL, attributes={"value": 1})
    g_trivial.add_node(lit)
    g_trivial.root_id = "lit"
    cc_trivial = CostClass.from_graph(g_trivial, cardinality_hint=1)
    assert not cc_trivial.is_worth_optimizing()

    g_heavy = _make_expense_graph()
    cc_heavy = CostClass.from_graph(g_heavy, cardinality_hint=50000)
    assert cc_heavy.is_worth_optimizing()


# ---------- Anti-reuse & False-difference pairs (Section 9) ----------

def test_anti_reuse_pair_memo_differs():
    """Section 9: Anti-reuse pair — same topology but different filter params
    → shape key MAY match, memo key MUST differ."""
    g1 = SemanticIRGraph()
    obs1 = IRNode(id="obs", op=OpKind.OBSERVE,
                  attributes={"source": "transactions", "granularity": "source"})
    g1.add_node(obs1)
    filt1 = IRNode(id="filt", op=OpKind.FILTER, inputs=["obs"],
                   attributes={"predicate": lambda x: True,
                                "exclude_transfers": True},
                   output_type=SemanticType.collection(SemanticType.numeric()))
    g1.add_node(filt1)
    red1 = IRNode(id="red", op=OpKind.REDUCE, inputs=["filt"],
                  attributes={"op": lambda a, b: a + b, "init": 0.0})
    g1.add_node(red1)
    emit1 = IRNode(id="emit", op=OpKind.EMIT, inputs=["red"])
    g1.add_node(emit1)
    g1.root_id = "emit"

    g2 = SemanticIRGraph()
    obs2 = IRNode(id="obs", op=OpKind.OBSERVE,
                  attributes={"source": "transactions", "granularity": "source"})
    g2.add_node(obs2)
    filt2 = IRNode(id="filt", op=OpKind.FILTER, inputs=["obs"],
                   attributes={"predicate": lambda x: True,
                                "exclude_transfers": False},  # DIFFERENT
                   output_type=SemanticType.collection(SemanticType.numeric()))
    g2.add_node(filt2)
    red2 = IRNode(id="red", op=OpKind.REDUCE, inputs=["filt"],
                  attributes={"op": lambda a, b: a + b, "init": 0.0})
    g2.add_node(red2)
    emit2 = IRNode(id="emit", op=OpKind.EMIT, inputs=["red"])
    g2.add_node(emit2)
    g2.root_id = "emit"

    mk1 = MemoKey.from_graph(g1)
    mk2 = MemoKey.from_graph(g2)
    assert mk1 != mk2  # Memo keys MUST differ


def test_false_difference_pair_shape_matches():
    """Section 9: False-difference pair — different surface wording,
    same computation → same shape key and same cost class."""
    g1 = _make_expense_graph("compare_spending_")
    g2 = _make_expense_graph("tell_me_amount_")

    sk1 = SemanticShapeKey.from_graph(g1)
    sk2 = SemanticShapeKey.from_graph(g2)
    assert sk1 == sk2

    cc1 = CostClass.from_graph(g1)
    cc2 = CostClass.from_graph(g2)
    assert cc1.tier == cc2.tier


# ---------- Canonicalization ----------

def test_canonicalization_filters_wording_attrs():
    """'name', 'description', 'raw_query' attributes are stripped."""
    g = SemanticIRGraph()
    node = IRNode(id="n1", op=OpKind.MAP, inputs=[],
                  attributes={"name": "my_map", "description": "does stuff",
                              "raw_query": "original text", "fn": lambda x: x})
    g.add_node(node)
    g.root_id = "n1"
    descriptors, _ = Canonicalizer.canonicalize_graph(g)
    attrs = descriptors[0]["attributes"]
    assert "name" not in attrs
    assert "description" not in attrs
    assert "raw_query" not in attrs


def test_canonicalization_callable_handling():
    """Lambda/callable → qualname string in canonical form."""
    g = SemanticIRGraph()
    def my_function(x): return x
    node = IRNode(id="n1", op=OpKind.MAP, inputs=[],
                  attributes={"fn": my_function})
    g.add_node(node)
    g.root_id = "n1"
    descriptors, _ = Canonicalizer.canonicalize_graph(g)
    fn_val = descriptors[0]["attributes"].get("fn")
    assert fn_val == "my_function"


# ---------- ComputationalSignature ----------

def test_signature_compute_all_projections():
    """ComputationalSignature.compute produces all 4 projections."""
    g = _make_expense_graph()
    sig = ComputationalSignature.compute(g, cardinality_hint=100)
    assert sig.shape_key is not None
    assert sig.memo_key is not None
    assert sig.cost_class is not None
    assert isinstance(sig.shape_key, SemanticShapeKey)
    assert isinstance(sig.memo_key, MemoKey)
    assert isinstance(sig.cost_class, CostClass)


# ---------- PolicyState ----------

def test_policy_state_admissible_actions():
    """Budget filtering returns only feasible actions."""
    ps = PolicyState(
        belief={"A": 0.5, "B": 0.5},
        action_set=[
            {"id": "cheap", "cost": {"latency": 5.0}},
            {"id": "expensive", "cost": {"latency": 100.0}},
            {"id": "moderate", "cost": {"latency": 15.0}},
        ],
        budget={"latency": 20.0}
    )
    admissible = ps.get_admissible_actions()
    ids = [a["id"] for a in admissible]
    assert "cheap" in ids
    assert "moderate" in ids
    assert "expensive" not in ids


def test_policy_state_no_admissible():
    """All actions exceed budget → empty admissible set."""
    ps = PolicyState(
        belief={"A": 1.0},
        action_set=[
            {"id": "a1", "cost": {"latency": 50.0}},
            {"id": "a2", "cost": {"latency": 100.0}},
        ],
        budget={"latency": 10.0}
    )
    assert ps.get_admissible_actions() == []


def test_cost_class_empty_graph():
    """Graph with 0 nodes — should handle gracefully."""
    g = SemanticIRGraph()
    cc = CostClass.from_graph(g, cardinality_hint=0)
    # 0 nodes, no external calls → TRIVIAL
    assert cc.tier == CostTier.TRIVIAL
    assert cc.estimated_op_count == 0
