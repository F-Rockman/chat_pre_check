from __future__ import annotations

import json
from typing import Any

from chat_pre_check.bootstrap import build_engine
from chat_pre_check.demo.fakes import DemoDeviceResolver, DemoRegionResolver, DemoVectorRetriever
from chat_pre_check.domain.models import RouteRequest


def build_mock_demo_engine(config_dir: str = "configs"):
    """构建稳定、可重复的本地 mock 运行时。"""
    return build_engine(
        config_dir=config_dir,
        retriever_override=DemoVectorRetriever(),
        device_resolver_override=DemoDeviceResolver(),
        region_resolver_override=DemoRegionResolver(),
    )


def route_payload(
    engine,
    text: str,
    *,
    role: str | None = None,
    tenant_id: str | None = None,
    trace_level: str = "compact",
) -> dict[str, Any]:
    """执行单条输入并返回序列化后的路由结果。"""
    decision = engine.route(
        RouteRequest(
            input_text=text,
            role=role,
            tenant_id=tenant_id,
            trace_level=trace_level,
        )
    )
    return decision.to_dict()


def print_route_summary(
    text: str,
    payload: dict[str, Any],
    *,
    show_trace: bool = False,
) -> None:
    """渲染 demo/live runner 共用的人类可读输出。"""
    print("=" * 80)
    print(f"INPUT      : {text}")
    print(f"TYPE       : {payload['type']}")
    print(f"SCENE      : {payload.get('scene')}")
    print(f"TEMPLATE   : {payload.get('template_id')}")
    print(f"MESSAGE    : {payload.get('message')}")
    print(f"MISSING    : {payload.get('missing_slots')}")
    print(f"SLOTS      : {json.dumps(payload.get('slots', {}), ensure_ascii=False)}")
    options = payload.get("options", [])
    if options:
        print("OPTIONS    :")
        for idx, option in enumerate(options, start=1):
            print(f"  {idx}. {option.get('label')}")
    if show_trace:
        print("TRACE      :")
        print(json.dumps(payload.get("trace", {}), ensure_ascii=False, indent=2))
