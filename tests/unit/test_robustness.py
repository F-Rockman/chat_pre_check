from __future__ import annotations

from chat_pre_check.application.engine import PrecheckEngine
from chat_pre_check.bootstrap import build_engine
from chat_pre_check.domain.models import RouteRequest
from tests.fixtures.fakes import FakeDeviceResolver, FakeRegionResolver, FakeVectorRetriever


class _ExplodingPipeline:
    def run(self, ctx):
        raise RuntimeError("boom")


class _FailingSceneRetriever:
    def search_scene(self, query_text: str, topk: int = 5):
        raise RuntimeError("scene backend down")

    def search_template(self, scene_id: str, query_text: str, topk: int = 5):
        return []

    def search_seed_cases(self, query_text: str, topk: int = 5):
        return []


class _FailingTemplateRetriever:
    def search_scene(self, query_text: str, topk: int = 5):
        return FakeVectorRetriever().search_scene(query_text, topk)

    def search_template(self, scene_id: str, query_text: str, topk: int = 5):
        raise RuntimeError("template backend down")

    def search_seed_cases(self, query_text: str, topk: int = 5):
        return []


def test_empty_input_returns_clarify(test_engine):
    decision = test_engine.route(RouteRequest(input_text="   "))
    payload = decision.to_dict()
    assert payload["type"] == "clarify"
    assert "input_text" in payload["missing_slots"]


def test_too_long_input_returns_refuse(test_engine):
    decision = test_engine.route(RouteRequest(input_text="a" * 1200))
    payload = decision.to_dict()
    assert payload["type"] == "refuse"
    assert payload["out_of_scope_reason"] == "unsupported_domain"


def test_engine_failsafe_for_unhandled_exception():
    engine = PrecheckEngine(pipeline=_ExplodingPipeline())  # type: ignore[arg-type]
    decision = engine.route(RouteRequest(input_text="查告警"))
    payload = decision.to_dict()
    assert payload["type"] == "refuse"
    assert payload["out_of_scope_reason"] == "data_unavailable"
    assert len(payload["options"]) >= 3


def test_scene_retriever_failure_refused():
    engine = build_engine(
        config_dir="configs",
        retriever_override=_FailingSceneRetriever(),
        device_resolver_override=FakeDeviceResolver(),
        region_resolver_override=FakeRegionResolver(),
    )
    decision = engine.route(RouteRequest(input_text="近24小时接口告警top10"))
    payload = decision.to_dict()
    assert payload["type"] == "refuse"
    assert payload["out_of_scope_reason"] == "data_unavailable"


def test_template_retriever_failure_refused():
    engine = build_engine(
        config_dir="configs",
        retriever_override=_FailingTemplateRetriever(),
        device_resolver_override=FakeDeviceResolver(),
        region_resolver_override=FakeRegionResolver(),
    )
    decision = engine.route(RouteRequest(input_text="近24小时核心网告警Top10"))
    payload = decision.to_dict()
    assert payload["type"] == "refuse"
    assert payload["out_of_scope_reason"] == "data_unavailable"
