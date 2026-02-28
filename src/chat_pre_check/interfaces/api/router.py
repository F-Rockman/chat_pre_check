from __future__ import annotations

from fastapi import APIRouter, Depends

from chat_pre_check.domain.models import RouteRequest
from chat_pre_check.interfaces.api.dto import RouteRequestDTO, RouteResponseDTO


def get_router(engine_provider) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("/v1/precheck/route", response_model=RouteResponseDTO)
    async def route(
        payload: RouteRequestDTO,
        engine=Depends(engine_provider),
    ) -> RouteResponseDTO:
        decision = engine.route(
            RouteRequest(
                input_text=payload.input_text,
                context=payload.context,
                tenant_id=payload.tenant_id,
                role=payload.role,
                trace_level=payload.trace_level,
            )
        )
        return RouteResponseDTO.model_validate(decision.to_dict())

    return router
