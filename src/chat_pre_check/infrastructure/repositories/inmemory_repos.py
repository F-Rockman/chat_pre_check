from __future__ import annotations

from typing import Any


class InMemorySceneRepository:
    """内存场景仓库。"""

    def __init__(self, scenes: list[dict[str, Any]]) -> None:
        self._scenes = [scene for scene in scenes if scene.get("enabled", True)]
        self._by_id = {scene["scene_id"]: scene for scene in self._scenes}

    def all_enabled(self) -> list[dict[str, Any]]:
        return list(self._scenes)

    def get(self, scene_id: str) -> dict[str, Any] | None:
        return self._by_id.get(scene_id)


class InMemoryTemplateRepository:
    """内存模板仓库。"""

    def __init__(self, templates: list[dict[str, Any]]) -> None:
        self._templates = [template for template in templates if template.get("enabled", True)]

    def all_enabled(self) -> list[dict[str, Any]]:
        return list(self._templates)

    def by_scene(self, scene_id: str) -> list[dict[str, Any]]:
        return [template for template in self._templates if template.get("scene_id") == scene_id]


class InMemoryCaseRepository:
    """内存案例仓库。"""

    def __init__(self, cases: list[dict[str, Any]]) -> None:
        self._cases = [item for item in cases if item.get("enabled", True)]

    def all_enabled(self) -> list[dict[str, Any]]:
        return list(self._cases)
