from fastapi.testclient import TestClient

from chat_pre_check.interfaces.api.app import create_app


def test_route_api_contract(test_engine):
    app = create_app(engine_override=test_engine)
    client = TestClient(app)
    response = client.post(
        "/v1/precheck/route",
        json={"input_text": "查告警", "trace_level": "compact"},
    )
    assert response.status_code == 200
    body = response.json()
    for field in ["type", "message", "slots", "missing_slots", "options", "trace"]:
        assert field in body


def test_healthz():
    app = create_app()
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
