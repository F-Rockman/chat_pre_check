from __future__ import annotations

from chat_pre_check.domain.models import TraceCollector


def render_trace(trace: TraceCollector, level: str = "compact") -> dict:
    """按级别渲染 trace，debug 输出完整 topk/extra，compact 输出摘要字段。"""
    if level == "debug":
        return {
            "request_id": trace.request_id,
            "summary": trace.summary,
            "steps": [
                {
                    "step": step.step,
                    "decision": step.decision,
                    "reason": step.reason,
                    "latency_ms": step.latency_ms,
                    "score": step.score,
                    "topk": step.topk,
                    "extra": step.extra,
                }
                for step in trace.steps
            ],
        }

    return {
        "request_id": trace.request_id,
        "summary": trace.summary,
        "steps": [
            {
                "step": step.step,
                "decision": step.decision,
                "reason": step.reason,
                "latency_ms": step.latency_ms,
                "score": step.score,
            }
            for step in trace.steps
        ],
    }
