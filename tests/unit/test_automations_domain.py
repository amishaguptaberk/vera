from vera_domain import automations as dom
from vera_domain.investigation import INVESTIGATION_V3


def test_seeded_v3_has_21_nodes_and_is_valid() -> None:
    assert len(dom.WORKFLOW_V3.nodes) == 21
    assert dom.validate(dom.WORKFLOW_V3) == []


def test_executed_subgraph_comes_from_the_seeded_v3_graph() -> None:
    keys = [n["key"] for n in INVESTIGATION_V3["nodes"]]
    sub = dom.executed_subgraph(dom.WORKFLOW_V3, keys)
    assert sub["nodes"] == INVESTIGATION_V3["nodes"]
    assert sub["edges"] == INVESTIGATION_V3["edges"]


def test_all_six_scenarios_reach_close() -> None:
    results = dom.run_checks(dom.WORKFLOW_V3)
    assert [r.scenario for r in results] == [
        "Missing receipt · confirmed by callback",
        "Cardholder recognizes it · receipt attached",
        "Contradictory receipt",
        "Cardholder does not respond",
        "Unanswered callback",
        "Reviewer returns case",
    ]
    assert all(r.passed and r.last_step == "close_or_monitor" for r in results)


def test_changing_visual_category_does_not_change_behavior() -> None:
    g = dom.apply_patch(
        dom.WORKFLOW_V3,
        [dom.PatchOp(op="update_node", key="live_verification", changes={"category": "action"})],
    )
    assert dom.validate(g) == []
    before = [r.model_dump() for r in dom.run_checks(dom.WORKFLOW_V3)]
    assert [r.model_dump() for r in dom.run_checks(g)] == before
    keys = [n["key"] for n in INVESTIGATION_V3["nodes"]]
    g2 = dom.apply_patch(
        dom.WORKFLOW_V3,
        [dom.PatchOp(op="update_node", key="pc1", changes={"category": "agent"})],
    )
    assert dom.executed_subgraph(g2, keys) == dom.executed_subgraph(dom.WORKFLOW_V3, keys)


def test_violations_name_node_and_rule() -> None:
    g = dom.apply_patch(
        dom.WORKFLOW_V3,
        [
            dom.PatchOp(
                op="remove_edge",
                edge=dom.Edge(source="pc1", target="analyst_handoff", outcome="contradictory"),
            )
        ],
    )
    issues = dom.validate(g)
    assert [(v.rule, v.node_ids) for v in issues] == [(5, ["pc1"])]
    assert "contradictory" in issues[0].message


def test_retry_limit_exceeded_fails_scenario() -> None:
    s = dom.Scenario(name="loop", script={"reviewer_approval": ["rejected"]})
    r = dom.run_scenario(dom.WORKFLOW_V3, s)
    assert not r.passed and "retry limit 2" in (r.reason or "")
