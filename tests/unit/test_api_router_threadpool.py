from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from chat_pre_check.domain.enums import DecisionType
from chat_pre_check.domain.models import RouteDecision, RouteRequest
from chat_pre_check.interfaces.api import router as router_module


class _DummyEngine:
    def __init__(self) -> None:
        self.last_request: RouteRequest | None = None

    def route(self, request: RouteRequest) -> RouteDecision:
        self.last_request = request
        return RouteDecision(
            type=DecisionType.ROUTE_NL2SQL,
            message="ok",
            scene="alarm.analysis",
            slots={"time_range": "last_24h"},
            trace={"summary": {"source": "unit_test"}},
        )


def test_route_endpoint_uses_threadpool(monkeypatch) -> None:
    engine = _DummyEngine()
    called: dict[str, object] = {}

    async def _fake_threadpool(func, *args, **kwargs):
        called["func"] = func
        called["args"] = args
        called["kwargs"] = kwargs
        return func(*args, **kwargs)

    monkeypatch.setattr(router_module, "run_in_threadpool", _fake_threadpool)

    app = FastAPI()
    app.include_router(router_module.get_router(lambda: engine))
    client = TestClient(app)

    response = client.post(
        "/v1/precheck/route",
        json={
            "input_text": "查询上海区域告警",
            "context": {"scene": "alarm.analysis"},
            "tenant_id": "tenant_a",
            "role": "ops_admin",
            "trace_level": "compact",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "route_nl2sql"
    assert body["scene"] == "alarm.analysis"
    assert body["slots"]["time_range"] == "last_24h"

    assert called["func"] == engine.route
    request = called["args"][0]
    assert isinstance(request, RouteRequest)
    assert request.input_text == "查询上海区域告警"
    assert request.context == {"scene": "alarm.analysis"}
    assert request.tenant_id == "tenant_a"
    assert request.role == "ops_admin"
    assert request.trace_level == "compact"
    assert engine.last_request is request

