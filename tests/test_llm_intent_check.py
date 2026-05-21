from __future__ import annotations

from template_capability.config import TemplateConfig
from template_capability.engine import TemplateCapabilityEngine
from template_capability.fallback import IntentVerificationResult
from template_capability.models import MatcherSettings, SlotExtractorDefinition, TemplateDefinition


class StubIntentVerifier:
    def __init__(self, result: IntentVerificationResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def verify_intent(
        self,
        *,
        input_text: str,
        normalized_text: str,
        template: TemplateDefinition,
        candidate,
    ) -> IntentVerificationResult | None:
        self.calls.append(
            {
                "input_text": input_text,
                "normalized_text": normalized_text,
                "template_id": template.template_id,
                "candidate_score": candidate.score,
            }
        )
        return self.result


def build_ip_server_engine(verifier: StubIntentVerifier | None = None) -> TemplateCapabilityEngine:
    return TemplateCapabilityEngine(
        TemplateConfig(
            settings=MatcherSettings(
                match_threshold=0.25,
                ambiguity_margin=0.03,
                recall_top_k=10,
                weights={
                    "lexical": 0.3,
                    "sample": 0.0,
                    "vector": 0.0,
                    "fusion": 0.0,
                    "slot_fit": 0.35,
                    "constraint": 0.35,
                    "structure": 0.0,
                },
                llm_intent_check_enabled=verifier is not None,
                llm_intent_check_min_score=0.25,
                llm_intent_check_min_confidence=0.65,
            ),
            templates=[
                TemplateDefinition(
                    template_id="server.info.by_ip",
                    query_mode="metric_query",
                    description="查询指定 IP 的服务器信息",
                    utterances=["查询 ip 为 10.0.0.1 的服务器信息"],
                    required_slots=["selector_ip"],
                    optional_slots=[],
                    must_terms=[["ip", "ip地址"], ["服务器"], ["信息"]],
                    negative_terms=[],
                    slot_constraints={},
                    slot_extractors={
                        "selector_ip": SlotExtractorDefinition(
                            slot_name="selector_ip",
                            extractors=[
                                {
                                    "type": "regex",
                                    "patterns": [
                                        {
                                            "pattern": "(?:ip|ip地址)\\s*(?:为)?\\s*([0-9]{1,3}(?:\\.[0-9]{1,3}){3})",
                                            "group": 1,
                                            "value_type": "string",
                                        }
                                    ],
                                }
                            ],
                        )
                    },
                )
            ],
        ),
        llm_template_intent_verifier=verifier,
    )


def test_llm_intent_check_allows_same_intent_top1():
    verifier = StubIntentVerifier(
        IntentVerificationResult(matched=True, confidence=0.92, trace={"reason": "same intent"})
    )
    payload = build_ip_server_engine(verifier).match("ip为10.0.0.1的服务器信息").to_dict()

    assert payload["template_id"] == "server.info.by_ip"
    assert payload["status"] == "matched"
    assert payload["slots"]["selector_ip"] == "10.0.0.1"
    assert payload["trace"]["intent_check"]["matched"] is True
    assert verifier.calls[0]["template_id"] == "server.info.by_ip"


def test_llm_intent_check_blocks_different_intent_top1():
    verifier = StubIntentVerifier(
        IntentVerificationResult(
            matched=False,
            confidence=0.91,
            trace={"reason": "query asks for ip or name alternative lookup"},
        )
    )
    payload = build_ip_server_engine(verifier).match("ip为10.0.0.1或名称为web01的服务器信息").to_dict()

    assert payload["template_id"] == -1
    assert payload["status"] == "unmatched"
    assert payload["trace"]["reason"] == "llm_intent_mismatch"
    assert payload["trace"]["intent_check"]["matched"] is False
    assert payload["trace"]["intent_check"]["trace"]["reason"] == "query asks for ip or name alternative lookup"


def test_low_confidence_llm_intent_mismatch_does_not_override_rules():
    verifier = StubIntentVerifier(
        IntentVerificationResult(matched=False, confidence=0.4, trace={"reason": "not sure"})
    )
    payload = build_ip_server_engine(verifier).match("ip为10.0.0.1的服务器信息").to_dict()

    assert payload["template_id"] == "server.info.by_ip"
    assert payload["trace"]["intent_check"]["applied"] is False
    assert payload["trace"]["intent_check"]["matched"] is True
    assert payload["trace"]["intent_check"]["raw_matched"] is False
