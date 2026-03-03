from __future__ import annotations

import re
import time

from chat_pre_check.domain.models import RequestContext, RouteDecision, TraceStep


SPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """文本归一化：小写化、标点空格化、压缩多余空白。"""
    text = text.strip().lower()
    text = text.replace("，", " ").replace("。", " ").replace("？", " ").replace("！", " ")
    text = SPACE_RE.sub(" ", text)
    return text


class NormalizeMiddleware:
    """标准化输入文本，写入 `ctx.norm_text`。"""

    name = "normalize"

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        started = time.perf_counter()
        ctx.norm_text = normalize_text(ctx.input_text)
        elapsed = (time.perf_counter() - started) * 1000
        ctx.trace.add_step(
            TraceStep(
                step=self.name,
                decision="continue",
                reason="normalized",
                latency_ms=elapsed,
                extra={"norm_text": ctx.norm_text},
            )
        )
        return None
