from __future__ import annotations

from chat_pre_check.demo.local_runtime import LocalHeuristicRetriever, build_local_fallback_engine
from chat_pre_check.domain.models import RouteRequest
from chat_pre_check.infrastructure.config.loader import load_app_config


def test_local_retriever_search_seed_cases():
    cfg = load_app_config("configs")
    retriever = LocalHeuristicRetriever(cfg.scenes, cfg.templates, cfg.seed_cases)
    hits = retriever.search_seed_cases("近24小时告警top10", topk=5)
    assert len(hits) >= 1


def test_local_fallback_engine_routes_template():
    engine = build_local_fallback_engine("configs")
    decision = engine.route(RouteRequest(input_text="近24小时接口错误包告警Top10"))
    payload = decision.to_dict()
    assert payload["type"] == "route_template"
    assert payload["template_id"] == "tpl_interface_alarm_topn"


def test_local_fallback_engine_routes_nl2sql():
    engine = build_local_fallback_engine("configs")
    decision = engine.route(RouteRequest(input_text="近90天核心网告警同比环比"))
    payload = decision.to_dict()
    assert payload["type"] == "route_nl2sql"
