from __future__ import annotations

from chat_pre_check.domain.models import TraceCollector


def render_trace(trace: TraceCollector, level: str = "compact") -> dict:
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
