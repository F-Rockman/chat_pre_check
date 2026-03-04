from __future__ import annotations

from chat_pre_check.application.middlewares.flow_router import FlowRouterMiddleware
from chat_pre_check.application.services.llm_assist import FlowLLMResult
from chat_pre_check.application.services.recommendation import RecommendationService
from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason
from chat_pre_check.domain.models import RequestContext
from chat_pre_check.infrastructure.repositories.inmemory_repos import InMemorySceneRepository


class _StubLLM:
    def __init__(self, result: FlowLLMResult | None) -> None:
        self.enabled = True
        self.result = result
        self.calls = 0

    def infer_flow(self, **kwargs):  # noqa: ANN003
        self.calls += 1
        return self.result


class _ErrorLLM:
    def __init__(self) -> None:
        self.enabled = True
        self.calls = 0

    def infer_flow(self, **kwargs):  # noqa: ANN003
        self.calls += 1
        raise RuntimeError("llm_request_failed:timeout")


def _build_router(scene_defs, **kwargs):  # noqa: ANN001
    recommendation = RecommendationService(scenes=scene_defs, templates=[], cases=[])
    return FlowRouterMiddleware(
        scene_repository=InMemorySceneRepository(scene_defs),
        recommendation_service=recommendation,
        router_config=kwargs.get("router_config", {"enabled": True, "min_confidence": 0.3}),
        llm_assist=kwargs.get("llm_assist"),
    )


def test_flow_router_selects_report_from_entry_phrase() -> None:
    scenes = [
        {
            "scene_id": "alarm.query",
            "description": "alarm",
            "required_slots": [],
            "defaults": {},
            "keywords": ["告警"],
            "examples": ["查告警"],
            "flow_type": "query",
            "entry_phrases": ["查告警"],
            "enabled": True,
        },
        {
            "scene_id": "report.inspect",
            "description": "report",
            "required_slots": [],
            "defaults": {},
            "keywords": ["报告", "巡检"],
            "examples": ["生成巡检报告"],
            "flow_type": "report",
            "entry_phrases": ["生成巡检报告", "生成报告"],
            "enabled": True,
        },
    ]
    router = _build_router(scenes)
    ctx = RequestContext(input_text="帮我生成巡检报告", norm_text="帮我生成巡检报告")
    decision = router.process(ctx)
    assert decision is None
    assert ctx.flow_type == "report"
    assert ctx.scene is None


def test_flow_router_returns_refuse_when_flow_unknown() -> None:
    scenes = [
        {
            "scene_id": "alarm.query",
            "description": "alarm",
            "required_slots": [],
            "defaults": {},
            "keywords": ["告警"],
            "examples": ["查告警"],
            "flow_type": "query",
            "entry_phrases": ["查告警"],
            "enabled": True,
        }
    ]
    router = _build_router(
        scenes,
        router_config={"enabled": True, "min_confidence": 0.8, "ambiguous_gap": 0.05},
    )
    ctx = RequestContext(input_text="hello world", norm_text="hello world")
    decision = router.process(ctx)
    assert decision is not None
    assert decision.type == DecisionType.REFUSE
    assert decision.out_of_scope_reason == OutOfScopeReason.UNKNOWN_DOMAIN
    assert decision.flow_type == "unknown"


def test_flow_router_llm_called_once_when_ambiguous() -> None:
    scenes = [
        {
            "scene_id": "alarm.query",
            "description": "alarm",
            "required_slots": [],
            "defaults": {},
            "keywords": ["查询"],
            "examples": ["查询数据"],
            "flow_type": "query",
            "entry_phrases": [],
            "enabled": True,
        },
        {
            "scene_id": "report.inspect",
            "description": "report",
            "required_slots": [],
            "defaults": {},
            "keywords": ["查询"],
            "examples": ["查询报告"],
            "flow_type": "report",
            "entry_phrases": [],
            "enabled": True,
        },
    ]
    stub = _StubLLM(
        FlowLLMResult(
            flow_type="report",
            scene="report.inspect",
            slots={"time_range": "today"},
            confidence=0.91,
            latency_ms=12.0,
            raw_text='{"flow_type":"report"}',
        )
    )
    router = _build_router(
        scenes,
        router_config={"enabled": True, "min_confidence": 0.9, "ambiguous_gap": 0.1},
        llm_assist=stub,
    )
    ctx = RequestContext(input_text="查询", norm_text="查询")
    decision = router.process(ctx)
    assert decision is None
    assert stub.calls == 1
    assert ctx.llm_calls == 1
    assert ctx.flow_type == "report"
    assert ctx.scene is None
    assert ctx.entities.get("llm_scene_hint") == "report.inspect"
    assert ctx.slots["time_range"] == "today"


def test_flow_router_falls_back_to_rules_when_llm_raises() -> None:
    scenes = [
        {
            "scene_id": "alarm.query",
            "description": "alarm",
            "required_slots": [],
            "defaults": {},
            "keywords": ["查询"],
            "examples": ["查询数据"],
            "flow_type": "query",
            "entry_phrases": [],
            "enabled": True,
        },
        {
            "scene_id": "report.inspect",
            "description": "report",
            "required_slots": [],
            "defaults": {},
            "keywords": ["查询"],
            "examples": ["查询报告"],
            "flow_type": "report",
            "entry_phrases": [],
            "enabled": True,
        },
    ]
    stub = _ErrorLLM()
    router = _build_router(
        scenes,
        router_config={"enabled": True, "min_confidence": 0.9, "ambiguous_gap": 0.1},
        llm_assist=stub,
    )
    ctx = RequestContext(input_text="查询", norm_text="查询")
    decision = router.process(ctx)
    assert decision is None
    assert stub.calls == 1
    assert ctx.flow_type == "query"
    assert "llm_error" in ctx.trace.summary


def test_flow_router_skips_llm_on_low_confidence_by_default() -> None:
    scenes = [
        {
            "scene_id": "alarm.query",
            "description": "alarm",
            "required_slots": [],
            "defaults": {},
            "keywords": ["告警"],
            "examples": ["查告警"],
            "flow_type": "query",
            "entry_phrases": [],
            "enabled": True,
        }
    ]
    stub = _StubLLM(
        FlowLLMResult(
            flow_type="report",
            scene="report.inspect",
            slots={},
            confidence=0.9,
            latency_ms=10.0,
            raw_text='{"flow_type":"report"}',
        )
    )
    router = _build_router(
        scenes,
        router_config={"enabled": True, "min_confidence": 0.9, "ambiguous_gap": 0.1},
        llm_assist=stub,
    )
    ctx = RequestContext(input_text="hello world", norm_text="hello world")
    decision = router.process(ctx)
    assert decision is not None
    assert decision.type == DecisionType.REFUSE
    assert stub.calls == 0
