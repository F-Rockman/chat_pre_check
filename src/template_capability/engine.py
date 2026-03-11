from __future__ import annotations

from template_capability.config import TemplateConfig, load_template_config
from template_capability.extractors import extract_slots, normalize_text
from template_capability.models import ActionOption, DecisionType, RouteDecision, TemplateDefinition
from template_capability.scoring import (
    example_similarity_score,
    keyword_overlap_score,
    slot_fit_score,
    weighted_score,
)


class TemplateCapabilityEngine:
    """独立模板引擎：跨模板打分，输出模板路由/追问/拒答。"""

    def __init__(self, config: TemplateConfig) -> None:
        self.config = config

    @classmethod
    def from_file(cls, path: str) -> "TemplateCapabilityEngine":
        return cls(load_template_config(path))

    def route(self, input_text: str) -> RouteDecision:
        norm_text = normalize_text(input_text)
        slots = extract_slots(norm_text)
        ranked = self._rank_templates(norm_text, slots)
        top = ranked[0] if ranked else None

        if top is None or top["score"] < self.config.match_threshold:
            return RouteDecision(
                type=DecisionType.REFUSE,
                message="未命中可信模板，请换一种更接近模板能力的问法。",
                slots=slots,
                options=self._refuse_options(ranked),
                trace={
                    "norm_text": norm_text,
                    "top_candidates": ranked[:5],
                    "threshold": self.config.match_threshold,
                },
            )

        template = top["template"]
        missing_slots = [
            slot
            for slot in template.slot_schema.get("required", [])
            if slots.get(slot) in (None, "")
        ]
        if missing_slots:
            primary = missing_slots[0]
            return RouteDecision(
                type=DecisionType.CLARIFY,
                message=f"模板已命中，但缺少必填参数：{primary}。",
                scene=template.scene_id,
                template_id=template.template_id,
                slots=slots,
                missing_slots=missing_slots,
                options=self._clarify_options(primary),
                trace={
                    "norm_text": norm_text,
                    "selected_template": top["trace"],
                    "missing_slots": missing_slots,
                },
            )

        return RouteDecision(
            type=DecisionType.ROUTE_TEMPLATE,
            message="已命中可执行模板。",
            scene=template.scene_id,
            template_id=template.template_id,
            slots=slots,
            trace={
                "norm_text": norm_text,
                "selected_template": top["trace"],
            },
        )

    def _rank_templates(
        self,
        norm_text: str,
        slots: dict[str, object],
    ) -> list[dict[str, object]]:
        ranked: list[dict[str, object]] = []
        for template in self.config.templates:
            rule_score = max(
                keyword_overlap_score(norm_text, template.keywords),
                example_similarity_score(norm_text, template.examples),
            )
            if self._contains_negative_keyword(norm_text, template.negative_keywords):
                rule_score = 0.0
            score_parts = {
                "rule": rule_score,
                "slot_fit": slot_fit_score(template.slot_schema, slots),
            }
            total = weighted_score(score_parts, self.config.weights)
            ranked.append(
                {
                    "template": template,
                    "score": total,
                    "trace": {
                        "scene": template.scene_id,
                        "template_id": template.template_id,
                        "label": template.label,
                        "score": total,
                        "score_parts": score_parts,
                    },
                }
            )
        ranked.sort(key=lambda item: float(item["score"]), reverse=True)
        return ranked

    @staticmethod
    def _contains_negative_keyword(text: str, keywords: list[str]) -> bool:
        lowered = text.lower()
        return any(keyword.lower() in lowered for keyword in keywords)

    def _refuse_options(self, ranked: list[dict[str, object]], limit: int = 3) -> list[ActionOption]:
        options: list[ActionOption] = []
        for item in ranked[:limit]:
            template = item["template"]
            if not isinstance(template, TemplateDefinition):
                continue
            options.append(
                ActionOption(
                    label=template.label,
                    preset_slots={},
                    slot_value=template.template_id,
                )
            )
        if options:
            return options
        return [ActionOption(label="试试：近24小时接口错误包告警Top10")]

    @staticmethod
    def _clarify_options(slot_name: str) -> list[ActionOption]:
        if slot_name == "time_range":
            return [
                ActionOption(label="近24小时", preset_slots={"time_range": "last_24h"}),
                ActionOption(label="近7天", preset_slots={"time_range": "last_7d"}),
                ActionOption(label="昨天", preset_slots={"time_range": "yesterday"}),
            ]
        if slot_name == "topn":
            return [
                ActionOption(label="Top5", preset_slots={"topn": 5}, slot_value=5),
                ActionOption(label="Top10", preset_slots={"topn": 10}, slot_value=10),
                ActionOption(label="Top20", preset_slots={"topn": 20}, slot_value=20),
            ]
        if slot_name == "protocol":
            return [
                ActionOption(label="BGP", preset_slots={"protocol": "bgp"}, slot_value="bgp"),
                ActionOption(label="OSPF", preset_slots={"protocol": "ospf"}, slot_value="ospf"),
                ActionOption(label="ISIS", preset_slots={"protocol": "isis"}, slot_value="isis"),
            ]
        if slot_name == "region_id":
            return [
                ActionOption(label="华东", preset_slots={"region_id": "east_cn"}, slot_value="east_cn"),
                ActionOption(label="华南", preset_slots={"region_id": "south_cn"}, slot_value="south_cn"),
                ActionOption(label="华北", preset_slots={"region_id": "north_cn"}, slot_value="north_cn"),
            ]
        if slot_name == "device_id":
            return [ActionOption(label="请补充设备 IP", preset_slots={})]
        if slot_name == "metric":
            return [
                ActionOption(label="丢包率", preset_slots={"metric": "packet_loss"}, slot_value="packet_loss"),
                ActionOption(label="时延", preset_slots={"metric": "latency"}, slot_value="latency"),
                ActionOption(label="CPU", preset_slots={"metric": "cpu_usage"}, slot_value="cpu_usage"),
            ]
        return [ActionOption(label=f"请补充 {slot_name}", preset_slots={})]
