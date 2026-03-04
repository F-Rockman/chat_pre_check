from __future__ import annotations


def test_seed_scope_guard_runs_after_template_matcher(test_engine) -> None:
    names = [middleware.name for middleware in test_engine.pipeline.middlewares]
    assert "flow_router" in names
    assert "scope_gate" in names
    assert "template_matcher" in names
    assert "report_router" in names
    assert "seed_scope_guard" in names
    assert "nl2sql_router" in names
    assert names.index("flow_router") < names.index("scope_gate")
    assert names.index("scope_gate") < names.index("report_router")
    assert names.index("report_router") < names.index("template_matcher")
    assert names.index("template_matcher") < names.index("seed_scope_guard")
    assert names.index("seed_scope_guard") < names.index("nl2sql_router")
