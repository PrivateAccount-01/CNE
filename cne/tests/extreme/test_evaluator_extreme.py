"""
Module 1: Semantic IR Evaluator Extreme Tests.
25 black-box tests designed from the specification — NOT from reading implementation.
Pushes evaluator to boundary conditions, degenerate inputs, and scale extremes.
"""
import pytest
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion
from cne.semantic_ir.types import SemanticType
from cne.semantic_ir.evaluator import SemanticEvaluator


# ---------- Degenerate / Boundary inputs ----------

def test_empty_graph_execution():
    """Graph with zero nodes — should not crash, should return None."""
    g = SemanticIRGraph()
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val is None
    assert ctx.executed_nodes == []


def test_single_literal_graph():
    """Minimal 1-node graph with a literal value."""
    g = SemanticIRGraph()
    lit = IRNode(id="lit", op=OpKind.LITERAL, attributes={"value": 42})
    g.add_node(lit)
    g.root_id = "lit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == 42
    assert "lit" in ctx.executed_nodes


# ---------- Depth stress ----------

def test_deep_chain_50_maps():
    """50 chained Map nodes: each doubles the input."""
    g = SemanticIRGraph()
    lit = IRNode(id="start", op=OpKind.LITERAL, attributes={"value": 1})
    g.add_node(lit)
    prev = "start"
    for i in range(50):
        nid = f"map_{i}"
        m = IRNode(id=nid, op=OpKind.MAP, inputs=[prev],
                   attributes={"fn": lambda x: x * 2 if isinstance(x, (int, float)) else x})
        g.add_node(m)
        prev = nid
    g.root_id = prev
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == 2 ** 50
    assert len(ctx.executed_nodes) == 51  # 1 literal + 50 maps


def test_deep_chain_200_maps():
    """200 chained Map nodes: identity function, testing recursion depth."""
    g = SemanticIRGraph()
    lit = IRNode(id="start", op=OpKind.LITERAL, attributes={"value": "hello"})
    g.add_node(lit)
    prev = "start"
    for i in range(200):
        nid = f"m_{i}"
        m = IRNode(id=nid, op=OpKind.MAP, inputs=[prev],
                   attributes={"fn": lambda x: x})
        g.add_node(m)
        prev = nid
    g.root_id = prev
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == "hello"
    assert len(ctx.executed_nodes) == 201


# ---------- Observe edge cases ----------

def test_observe_missing_source():
    """Observe from a source not present in environment."""
    g = SemanticIRGraph()
    obs = IRNode(id="obs", op=OpKind.OBSERVE,
                 attributes={"source": "nonexistent_table"})
    g.add_node(obs)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["obs"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g, initial_env={})
    assert val is None
    assert len(ctx.observed_dependencies) >= 1


def test_observe_none_value():
    """Observe returns None when the source value is explicitly None."""
    g = SemanticIRGraph()
    obs = IRNode(id="obs", op=OpKind.OBSERVE,
                 attributes={"source": "data"})
    g.add_node(obs)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["obs"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g, initial_env={"data": None})
    assert val is None


# ---------- Filter edge cases ----------

def test_filter_all_rejected():
    """Filter rejects every element — result should be empty list."""
    g = SemanticIRGraph()
    lit = IRNode(id="data", op=OpKind.LITERAL,
                 attributes={"value": [1, 2, 3, 4, 5]})
    g.add_node(lit)
    filt = IRNode(id="filt", op=OpKind.FILTER, inputs=["data"],
                  attributes={"predicate": lambda x: x > 100})
    g.add_node(filt)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["filt"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == []


def test_filter_empty_collection():
    """Filter on empty list — result should be empty list."""
    g = SemanticIRGraph()
    lit = IRNode(id="data", op=OpKind.LITERAL, attributes={"value": []})
    g.add_node(lit)
    filt = IRNode(id="filt", op=OpKind.FILTER, inputs=["data"],
                  attributes={"predicate": lambda x: True})
    g.add_node(filt)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["filt"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == []


# ---------- Reduce edge cases ----------

def test_reduce_empty_collection():
    """Reduce on empty list — should return init value."""
    g = SemanticIRGraph()
    lit = IRNode(id="data", op=OpKind.LITERAL, attributes={"value": []})
    g.add_node(lit)
    red = IRNode(id="red", op=OpKind.REDUCE, inputs=["data"],
                 attributes={"op": lambda a, b: a + b, "init": 0.0})
    g.add_node(red)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["red"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == 0.0


def test_reduce_single_element():
    """Reduce on single-element list."""
    g = SemanticIRGraph()
    lit = IRNode(id="data", op=OpKind.LITERAL, attributes={"value": [42]})
    g.add_node(lit)
    red = IRNode(id="red", op=OpKind.REDUCE, inputs=["data"],
                 attributes={"op": lambda a, b: a + b, "init": 0})
    g.add_node(red)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["red"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == 42


# ---------- Join edge cases ----------

def test_join_empty_left():
    """Join with empty left input — result should be empty."""
    g = SemanticIRGraph()
    left = IRNode(id="left", op=OpKind.LITERAL, attributes={"value": []})
    right = IRNode(id="right", op=OpKind.LITERAL,
                   attributes={"value": [{"id": 1}]})
    g.add_node(left)
    g.add_node(right)
    join = IRNode(id="join", op=OpKind.JOIN, inputs=["left", "right"],
                  attributes={"on": lambda l, r: True})
    g.add_node(join)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["join"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == []


def test_join_empty_both():
    """Join with both inputs empty — result should be empty."""
    g = SemanticIRGraph()
    left = IRNode(id="left", op=OpKind.LITERAL, attributes={"value": []})
    right = IRNode(id="right", op=OpKind.LITERAL, attributes={"value": []})
    g.add_node(left)
    g.add_node(right)
    join = IRNode(id="join", op=OpKind.JOIN, inputs=["left", "right"],
                  attributes={"on": lambda l, r: True})
    g.add_node(join)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["join"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == []


def test_join_large_cartesian():
    """Join 100×100 cartesian product — should produce 10000 pairs."""
    g = SemanticIRGraph()
    left = IRNode(id="left", op=OpKind.LITERAL,
                  attributes={"value": list(range(100))})
    right = IRNode(id="right", op=OpKind.LITERAL,
                   attributes={"value": list(range(100))})
    g.add_node(left)
    g.add_node(right)
    join = IRNode(id="join", op=OpKind.JOIN, inputs=["left", "right"],
                  attributes={"on": lambda l, r: True})
    g.add_node(join)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["join"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert len(val) == 10000


# ---------- Branch edge cases ----------

def test_branch_missing_region():
    """Branch references a nonexistent region — should not crash."""
    g = SemanticIRGraph()
    cond = IRNode(id="cond", op=OpKind.LITERAL, attributes={"value": True})
    g.add_node(cond)
    branch = IRNode(id="br", op=OpKind.BRANCH, inputs=["cond"],
                    attributes={"then_region": "nonexistent_region",
                                "else_region": "also_nonexistent"})
    g.add_node(branch)
    g.root_id = "br"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    # Should fallback gracefully — not crash
    assert "br" in ctx.executed_nodes


def test_branch_null_condition():
    """Branch condition is None (falsy) — should take else branch."""
    g = SemanticIRGraph()
    cond = IRNode(id="cond", op=OpKind.LITERAL, attributes={"value": None})
    g.add_node(cond)

    then_reg = SemanticRegion(id="then_reg")
    then_node = IRNode(id="then_val", op=OpKind.LITERAL,
                       attributes={"value": "THEN_TAKEN"})
    then_reg.add_node(then_node)
    then_reg.root_id = "then_val"
    g.add_region(then_reg)

    else_reg = SemanticRegion(id="else_reg")
    else_node = IRNode(id="else_val", op=OpKind.LITERAL,
                       attributes={"value": "ELSE_TAKEN"})
    else_reg.add_node(else_node)
    else_reg.root_id = "else_val"
    g.add_region(else_reg)

    branch = IRNode(id="br", op=OpKind.BRANCH, inputs=["cond"],
                    attributes={"then_region": "then_reg",
                                "else_region": "else_reg"})
    g.add_node(branch)
    g.root_id = "br"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == "ELSE_TAKEN"
    assert "then_val" not in ctx.executed_nodes
    assert "else_val" in ctx.executed_nodes


def test_nested_branch_3_deep():
    """Branch inside Branch inside Branch — 3 levels deep."""
    g = SemanticIRGraph()
    cond1 = IRNode(id="c1", op=OpKind.LITERAL, attributes={"value": True})
    g.add_node(cond1)

    # Level 3 (innermost): literal result
    inner_reg = SemanticRegion(id="inner_reg")
    inner_lit = IRNode(id="inner_lit", op=OpKind.LITERAL,
                       attributes={"value": "DEEP_RESULT"})
    inner_reg.add_node(inner_lit)
    inner_reg.root_id = "inner_lit"
    g.add_region(inner_reg)

    inner_else = SemanticRegion(id="inner_else")
    inner_else_lit = IRNode(id="ie_lit", op=OpKind.LITERAL,
                            attributes={"value": "INNER_ELSE"})
    inner_else.add_node(inner_else_lit)
    inner_else.root_id = "ie_lit"
    g.add_region(inner_else)

    # Level 2: branch that selects inner_reg
    mid_reg = SemanticRegion(id="mid_reg")
    mid_cond = IRNode(id="mc", op=OpKind.LITERAL, attributes={"value": True})
    mid_reg.add_node(mid_cond)
    mid_br = IRNode(id="mid_br", op=OpKind.BRANCH, inputs=["mc"],
                    attributes={"then_region": "inner_reg",
                                "else_region": "inner_else"})
    mid_reg.add_node(mid_br)
    mid_reg.root_id = "mid_br"
    g.add_region(mid_reg)

    mid_else = SemanticRegion(id="mid_else")
    mid_else_lit = IRNode(id="me_lit", op=OpKind.LITERAL,
                          attributes={"value": "MID_ELSE"})
    mid_else.add_node(mid_else_lit)
    mid_else.root_id = "me_lit"
    g.add_region(mid_else)

    # Level 1 (outermost): branch that selects mid_reg
    outer_br = IRNode(id="outer_br", op=OpKind.BRANCH, inputs=["c1"],
                      attributes={"then_region": "mid_reg",
                                  "else_region": "mid_else"})
    g.add_node(outer_br)
    g.root_id = "outer_br"

    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == "DEEP_RESULT"


# ---------- Iterate edge cases ----------

def test_iterate_empty_items():
    """Iterate over empty collection — should return init value."""
    g = SemanticIRGraph()
    items = IRNode(id="items", op=OpKind.LITERAL, attributes={"value": []})
    g.add_node(items)
    iterate = IRNode(id="iter", op=OpKind.ITERATE, inputs=["items"],
                     attributes={"init": 0,
                                 "step_fn": lambda acc, item: acc + item})
    g.add_node(iterate)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["iter"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == 0


def test_iterate_with_stop_condition():
    """Iterate exits early when stop condition is met."""
    g = SemanticIRGraph()
    items = IRNode(id="items", op=OpKind.LITERAL,
                   attributes={"value": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]})
    g.add_node(items)
    iterate = IRNode(id="iter", op=OpKind.ITERATE, inputs=["items"],
                     attributes={"init": 0,
                                 "step_fn": lambda acc, item: acc + item,
                                 "stop_condition": lambda acc: acc >= 10})
    g.add_node(iterate)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["iter"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    # 1+2+3+4 = 10, stop at 10
    assert val == 10


def test_iterate_100_items():
    """Iterate over 100 items — accumulate sum."""
    g = SemanticIRGraph()
    items = IRNode(id="items", op=OpKind.LITERAL,
                   attributes={"value": list(range(1, 101))})
    g.add_node(items)
    iterate = IRNode(id="iter", op=OpKind.ITERATE, inputs=["items"],
                     attributes={"init": 0,
                                 "step_fn": lambda acc, item: acc + item})
    g.add_node(iterate)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["iter"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == 5050  # sum(1..100) = 5050


# ---------- Update (Bayesian) edge cases ----------

def test_update_50_hypotheses():
    """Bayesian update with N=50 (spec maximum). Must remain O(N)."""
    prior = {f"H{i}": 1.0 / 50 for i in range(50)}
    def lh(h, ev):
        return 0.9 if h == "H0" else 0.1 / 49
    post = SemanticEvaluator._bayesian_update(prior, "evidence", lh)
    assert len(post) == 50
    assert post["H0"] > 0.5  # H0 should dominate
    total = sum(post.values())
    assert abs(total - 1.0) < 1e-6  # Must sum to 1


def test_update_zero_likelihood_all():
    """All likelihoods are 0 — degenerate case, should produce uniform."""
    prior = {"A": 0.5, "B": 0.3, "C": 0.2}
    def lh(h, ev):
        return 0.0
    post = SemanticEvaluator._bayesian_update(prior, "obs", lh)
    # When all likelihoods are zero, spec says uniform over hypothesis space
    assert len(post) == 3
    for v in post.values():
        assert abs(v - 1.0 / 3) < 1e-6


def test_update_single_hypothesis():
    """Prior with only 1 hypothesis — posterior should be 1.0."""
    prior = {"only": 1.0}
    def lh(h, ev):
        return 0.5
    post = SemanticEvaluator._bayesian_update(prior, "obs", lh)
    assert abs(post["only"] - 1.0) < 1e-6


# ---------- Choose edge cases ----------

def test_choose_no_feasible_action():
    """All actions exceed budget — should return None."""
    g = SemanticIRGraph()
    lit = IRNode(id="belief", op=OpKind.LITERAL,
                 attributes={"value": {"A": 0.5, "B": 0.5}})
    g.add_node(lit)
    choose = IRNode(id="choose", op=OpKind.CHOOSE, inputs=["belief"],
                    attributes={
                        "actions": [
                            {"id": "a1", "cost": {"latency": 100.0}},
                            {"id": "a2", "cost": {"latency": 200.0}},
                        ],
                        "budget": {"latency": 10.0},
                        "utility_fn": lambda act, b: 1.0
                    })
    g.add_node(choose)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["choose"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val is None


def test_choose_single_action():
    """Only one action available and feasible — must select it."""
    g = SemanticIRGraph()
    lit = IRNode(id="belief", op=OpKind.LITERAL,
                 attributes={"value": {"A": 1.0}})
    g.add_node(lit)
    choose = IRNode(id="choose", op=OpKind.CHOOSE, inputs=["belief"],
                    attributes={
                        "actions": [
                            {"id": "only_action", "cost": {"latency": 1.0}},
                        ],
                        "budget": {"latency": 10.0},
                        "utility_fn": lambda act, b: 5.0
                    })
    g.add_node(choose)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["choose"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val is not None
    assert val["id"] == "only_action"


# ---------- Call edge cases ----------

def test_call_missing_tool():
    """Call references a nonexistent tool — should return None, not crash."""
    g = SemanticIRGraph()
    call = IRNode(id="call", op=OpKind.CALL,
                  attributes={"target": "nonexistent_tool"})
    g.add_node(call)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["call"])
    g.add_node(emit)
    g.root_id = "emit"
    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val is None
