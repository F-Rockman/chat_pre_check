from __future__ import annotations

import time
from typing import Any

from chat_pre_check.application.services.recommendation import RecommendationService
from chat_pre_check.domain.enums import DecisionType, OutOfScopeReason
from chat_pre_check.domain.models import RequestContext, RouteDecision, TraceStep


class PolicyGuardMiddleware:
    name = "policy_guard"

    def __init__(
        self,
        rules: dict[str, Any],
        recommendation_service: RecommendationService,
    ) -> None:
        self.rules = rules
        self.recommendation_service = recommendation_service

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        text = ctx.norm_text

        if self._contains_any(text, self.rules.get("policy_block_keywords", [])):
            return self._refuse(
                ctx,
                started,
                OutOfScopeReason.POLICY_BLOCKED,
                "请求触发策略限制，无法继续处理。",
                "policy_blocked",
            )

        if self._contains_any(text, self.rules.get("unknown_domain_keywords", [])):
            return self._refuse(
                ctx,
                started,
                OutOfScopeReason.UNKNOWN_DOMAIN,
                "当前仅支持数据查询分析场景。",
                "unknown_domain",
            )

        if self._contains_any(text, self.rules.get("unsupported_domain_keywords", [])):
            return self._refuse(
                ctx,
                started,
                OutOfScopeReason.UNSUPPORTED_DOMAIN,
                "该业务域暂未接入，可先尝试告警或设备类查询。",
                "unsupported_domain",
            )

        permission_rules = self.rules.get("permission_rules", [])
        for rule in permission_rules:
            if ctx.role in rule.get("roles", []) and self._contains_any(
                text, rule.get("keywords", [])
            ):
                return self._refuse(
                    ctx,
                    started,
                    OutOfScopeReason.PERMISSION_DENIED,
                    "当前角色暂无该查询权限。",
                    "permission_denied",
                )

        if self._contains_any(text, self.rules.get("data_unavailable_keywords", [])):
            return self._refuse(
                ctx,
                started,
                OutOfScopeReason.DATA_UNAVAILABLE,
                "当前数据源不可用，请稍后重试。",
                "data_unavailable",
            )

        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason="passed",
                latency_ms=elapsed,
            )
        )
        return None

    @staticmethod
    def _contains_any(text: str, keywords: list[str]) -> bool:
        return any(keyword.lower() in text for keyword in keywords)

    def _refuse(
        self,
        ctx: RequestContext,
        started: float,
        reason: OutOfScopeReason,
        message: str,
        trace_reason: str,
    ) -> RouteDecision:
        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="refuse",
                reason=trace_reason,
                latency_ms=elapsed,
            )
        )
        return RouteDecision(
            type=DecisionType.REFUSE,
            message=message,
            slots=dict(ctx.slots),
            options=self.recommendation_service.refuse_options(ctx, reason),
            out_of_scope_reason=reason,
        )
