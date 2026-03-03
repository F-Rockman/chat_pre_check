from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from chat_pre_check.domain.models import RouteRequest
from chat_pre_check.interfaces.api.dto import RouteRequestDTO, RouteResponseDTO


def get_router(engine_provider) -> APIRouter:
    """创建 API 路由，注入引擎提供器以支持测试替换。"""
    router = APIRouter()

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("/v1/precheck/route", response_model=RouteResponseDTO)
    async def route(
        payload: RouteRequestDTO,
        engine=Depends(engine_provider),
    ) -> RouteResponseDTO:
        # 将同步路由链路放入线程池，避免阻塞 FastAPI 事件循环。
        decision = await run_in_threadpool(
            engine.route,
            RouteRequest(
                input_text=payload.input_text,
                context=payload.context,
                tenant_id=payload.tenant_id,
                role=payload.role,
                trace_level=payload.trace_level,
            ),
        )
        return RouteResponseDTO.model_validate(decision.to_dict())

    return router
