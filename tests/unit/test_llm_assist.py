from __future__ import annotations

from chat_pre_check.application.services.llm_assist import FlowLLMAssistService


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    def chat_json(self, **kwargs):  # noqa: ANN003
        self.calls += 1
        return type(
            "Resp",
            (),
            {
                "content": self.content,
                "latency_ms": 12.3,
            },
        )()


def test_llm_assist_parses_plain_json() -> None:
    svc = FlowLLMAssistService(
        client=_FakeClient(
            '{"flow_type":"report","scene":"report.inspect","slots":{"time_range":"today"},"confidence":0.91}'
        ),
        enabled=True,
    )
    result = svc.infer_flow(
        input_text="生成报告",
        flow_candidates=[("query", 0.4), ("report", 0.5)],
        scene_candidates=[("report.inspect", 0.5)],
        slots={},
    )
    assert result is not None
    assert result.flow_type == "report"
    assert result.scene == "report.inspect"
    assert result.slots["time_range"] == "today"


def test_llm_assist_parses_code_fence_json() -> None:
    svc = FlowLLMAssistService(
        client=_FakeClient(
            "```json\n{\"flow_type\":\"query\",\"scene\":\"alarm.query\",\"slots\":{},\"confidence\":0.7}\n```"
        ),
        enabled=True,
    )
    result = svc.infer_flow(
        input_text="查告警",
        flow_candidates=[("query", 0.4), ("report", 0.2)],
        scene_candidates=[("alarm.query", 0.4)],
        slots={},
    )
    assert result is not None
    assert result.flow_type == "query"
    assert result.scene == "alarm.query"


def test_llm_assist_normalizes_non_standard_flow_type() -> None:
    svc = FlowLLMAssistService(
        client=_FakeClient(
            '{"flow_type":"report_generation","scene":"report.inspect","slots":{},"confidence":0.9}'
        ),
        enabled=True,
    )
    result = svc.infer_flow(
        input_text="生成报告",
        flow_candidates=[("query", 0.4), ("report", 0.5)],
        scene_candidates=[("report.inspect", 0.5)],
        slots={},
    )
    assert result is not None
    assert result.flow_type == "report"
