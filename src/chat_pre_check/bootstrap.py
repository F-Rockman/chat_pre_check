from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from chat_pre_check.application.engine import PrecheckEngine
from chat_pre_check.application.middlewares.entity_enricher import EntityEnricherMiddleware
from chat_pre_check.application.middlewares.entity_extractor import EntityExtractorMiddleware
from chat_pre_check.application.middlewares.input_guard import InputGuardMiddleware
from chat_pre_check.application.middlewares.nl2sql_router import NL2SQLRouterMiddleware
from chat_pre_check.application.middlewares.normalize import NormalizeMiddleware
from chat_pre_check.application.middlewares.param_prefill import ParamPrefillMiddleware
from chat_pre_check.application.middlewares.policy_guard import PolicyGuardMiddleware
from chat_pre_check.application.middlewares.scene_router import SceneRouterMiddleware
from chat_pre_check.application.middlewares.seed_scope_guard import SeedScopeGuardMiddleware
from chat_pre_check.application.middlewares.scope_gate import ScopeGateMiddleware
from chat_pre_check.application.middlewares.slot_clarifier import SlotClarifierMiddleware
from chat_pre_check.application.middlewares.template_matcher import TemplateMatcherMiddleware
from chat_pre_check.application.pipeline import MiddlewarePipeline
from chat_pre_check.application.services.recommendation import RecommendationService
from chat_pre_check.application.services.slot_policy import SlotPolicyEngine
from chat_pre_check.domain.enums import OutOfScopeReason
from chat_pre_check.domain.models import RequestContext, SearchHit
from chat_pre_check.infrastructure.config.loader import load_app_config
from chat_pre_check.infrastructure.embedding.e5_embedder import E5Embedder
from chat_pre_check.infrastructure.extractors.ac_prefill import build_slot_prefiller
from chat_pre_check.infrastructure.repositories.inmemory_repos import (
    InMemoryCaseRepository,
    InMemorySceneRepository,
    InMemoryTemplateRepository,
)
from chat_pre_check.infrastructure.resolvers.device_resolver import DeviceResolver
from chat_pre_check.infrastructure.resolvers.noop_resolver import NoopResolver
from chat_pre_check.infrastructure.resolvers.region_resolver import RegionResolver
from chat_pre_check.infrastructure.resolvers.search_client_factory import (
    build_search_client,
)
from chat_pre_check.infrastructure.retrievers.opensearch_vector_retriever import (
    OpenSearchVectorRetriever,
)


class EmptyRetriever:
    def search_scene(self, query_text: str, topk: int = 5) -> list[SearchHit]:
        return []

    def search_template(
        self, scene_id: str, query_text: str, topk: int = 5
    ) -> list[SearchHit]:
        return []

    def search_seed_cases(self, query_text: str, topk: int = 5) -> list[SearchHit]:
        return []


def _local_timezone() -> str:
    tzname = datetime.now().astimezone().tzinfo
    if tzname is None:
        return "UTC"
    # ZoneInfo has key; fallback to string.
    if isinstance(tzname, ZoneInfo):
        return tzname.key
    return str(tzname)


def build_engine(
    config_dir: str = "configs",
    *,
    os_url: str | None = None,
    search_backend: str | None = None,
    os_username: str | None = None,
    os_password: str | None = None,
    os_bearer_token: str | None = None,
    retriever_override=None,
    device_resolver_override=None,
    region_resolver_override=None,
) -> PrecheckEngine:
    config = load_app_config(config_dir)
    scene_repo = InMemorySceneRepository(config.scenes)
    template_repo = InMemoryTemplateRepository(config.templates)
    case_repo = InMemoryCaseRepository(config.cases)
    recommendation_service = RecommendationService(
        scenes=scene_repo.all_enabled(),
        templates=template_repo.all_enabled(),
        cases=case_repo.all_enabled(),
    )

    thresholds = config.thresholds
    vector_cfg = config.vector
    scene_weights = vector_cfg["fusion_weights"]["scene"]
    template_weights = vector_cfg["fusion_weights"]["template"]
    prefill_cfg = vector_cfg.get("param_prefill", {})
    if not isinstance(prefill_cfg, dict):
        prefill_cfg = {}
    slot_prefiller = build_slot_prefiller(config_dir=config_dir, prefill_cfg=prefill_cfg)
    default_timezone = vector_cfg.get("default_timezone", _local_timezone())
    slot_policy_engine = SlotPolicyEngine(config.slot_policies)

    retriever = retriever_override
    device_resolver = device_resolver_override
    region_resolver = region_resolver_override
    if retriever is None or device_resolver is None or region_resolver is None:
        os_url = os_url or os.getenv("CHAT_PRE_CHECK_OS_URL")
        if os_url:
            _, client = build_search_client(
                vector_cfg=vector_cfg,
                base_url=os_url,
                backend_override=search_backend,
                username=os_username or os.getenv("CHAT_PRE_CHECK_OS_USERNAME"),
                password=os_password or os.getenv("CHAT_PRE_CHECK_OS_PASSWORD"),
                bearer_token=os_bearer_token or os.getenv("CHAT_PRE_CHECK_OS_BEARER_TOKEN"),
                timeout=int(os.getenv("CHAT_PRE_CHECK_OS_TIMEOUT", "5")),
                max_retries=int(os.getenv("CHAT_PRE_CHECK_OS_MAX_RETRIES", "1")),
                retry_backoff_sec=float(
                    os.getenv("CHAT_PRE_CHECK_OS_RETRY_BACKOFF_SEC", "0.2")
                ),
            )
            retriever = retriever or OpenSearchVectorRetriever(
                client=client,
                embedder=E5Embedder(
                    model_name=vector_cfg["model_name"],
                    device=vector_cfg.get("device", "cpu"),
                ),
                scene_index=vector_cfg["scene_index"],
                template_index=vector_cfg["template_index"],
                seed_case_index=vector_cfg.get("seed_case_index"),
                query_vector_cache_size=int(vector_cfg.get("query_vector_cache_size", 1024)),
            )
            device_resolver = device_resolver or DeviceResolver(
                client=client,
                index_name=vector_cfg.get("device_index", "assets_device_v1"),
            )
            region_resolver = region_resolver or RegionResolver(
                client=client,
                index_name=vector_cfg.get("region_index", "assets_region_v1"),
            )
        else:
            retriever = retriever or EmptyRetriever()
            device_resolver = device_resolver or NoopResolver()
            region_resolver = region_resolver or NoopResolver()

    pipeline = MiddlewarePipeline(
        [
            NormalizeMiddleware(),
            InputGuardMiddleware(
                recommendation_service=recommendation_service,
                max_input_chars=int(config.rules.get("max_input_chars", 1000)),
                min_input_chars=int(config.rules.get("min_input_chars", 1)),
            ),
            EntityExtractorMiddleware(default_timezone=default_timezone),
            ParamPrefillMiddleware(
                prefiller=slot_prefiller,
                enabled=bool(prefill_cfg.get("enabled", False)),
                auto_commit=bool(prefill_cfg.get("auto_commit", True)),
                commit_score=float(prefill_cfg.get("commit_score", 0.95)),
                min_gap=float(prefill_cfg.get("min_gap", 0.05)),
                max_candidates_per_slot=int(prefill_cfg.get("max_candidates_per_slot", 3)),
                router_config=prefill_cfg.get("domain_router", {}),
                arbiter_config={
                    "domain_priority": prefill_cfg.get("domain_priority", {}),
                    "slot_domain_priority": prefill_cfg.get(
                        "slot_domain_priority", {}
                    ),
                    "domain_penalty": prefill_cfg.get("domain_penalty", 0.2),
                },
            ),
            EntityEnricherMiddleware(
                device_resolver=device_resolver,
                region_resolver=region_resolver,
                recommendation_service=recommendation_service,
                commit_score=thresholds["resolver_commit_score"],
                min_gap=thresholds["resolver_min_gap"],
                skip_resolver_when_prefilled=bool(
                    prefill_cfg.get("skip_remote_resolver_when_prefilled", True)
                ),
            ),
            PolicyGuardMiddleware(
                rules=config.rules,
                recommendation_service=recommendation_service,
            ),
            ScopeGateMiddleware(
                scene_repository=scene_repo,
                retriever=retriever,
                recommendation_service=recommendation_service,
                thresholds=thresholds,
                fusion_weights=scene_weights,
                scene_topk=int(vector_cfg.get("scene_topk", 5)),
            ),
            SceneRouterMiddleware(scene_repository=scene_repo),
            SlotClarifierMiddleware(
                scene_repository=scene_repo,
                recommendation_service=recommendation_service,
                slot_policy_engine=slot_policy_engine,
            ),
            TemplateMatcherMiddleware(
                template_repository=template_repo,
                retriever=retriever,
                recommendation_service=recommendation_service,
                threshold=thresholds["T_template"],
                fusion_weights=template_weights,
                template_topk=int(vector_cfg.get("template_topk", 5)),
            ),
            # Only enforce seed scope when request is about to fallback to NL2SQL.
            SeedScopeGuardMiddleware(
                retriever=retriever,
                recommendation_service=recommendation_service,
                guard_config=vector_cfg.get("seed_scope_guard", {}),
            ),
            NL2SQLRouterMiddleware(),
        ]
    )
    return PrecheckEngine(
        pipeline=pipeline,
        fallback_options=recommendation_service.refuse_options(
            ctx=RequestContext(input_text="", norm_text=""),
            reason=OutOfScopeReason.DATA_UNAVAILABLE,
        ),
    )
