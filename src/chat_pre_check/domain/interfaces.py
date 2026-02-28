from __future__ import annotations

from typing import Any, Protocol

from chat_pre_check.domain.models import (
    Candidate,
    RequestContext,
    RouteDecision,
    SearchHit,
)


class Middleware(Protocol):
    name: str

    def process(self, ctx: RequestContext) -> RouteDecision | None:
        ...


class Resolver(Protocol):
    def resolve(self, text: str, topk: int = 5) -> list[Candidate]:
        ...


class Embedder(Protocol):
    def encode_queries(self, texts: list[str]) -> Any:
        ...

    def encode_passages(self, texts: list[str]) -> Any:
        ...


class Retriever(Protocol):
    def search_scene(self, query_text: str, topk: int = 5) -> list[SearchHit]:
        ...

    def search_template(
        self, scene_id: str, query_text: str, topk: int = 5
    ) -> list[SearchHit]:
        ...

    def search_seed_cases(self, query_text: str, topk: int = 5) -> list[SearchHit]:
        ...


class SceneRepository(Protocol):
    def all_enabled(self) -> list[dict[str, Any]]:
        ...

    def get(self, scene_id: str) -> dict[str, Any] | None:
        ...


class TemplateRepository(Protocol):
    def all_enabled(self) -> list[dict[str, Any]]:
        ...

    def by_scene(self, scene_id: str) -> list[dict[str, Any]]:
        ...


class CaseRepository(Protocol):
    def all_enabled(self) -> list[dict[str, Any]]:
        ...
