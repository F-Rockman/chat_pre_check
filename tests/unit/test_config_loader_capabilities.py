from __future__ import annotations

from chat_pre_check.infrastructure.config.loader import load_app_config


def test_loader_compiles_capabilities_to_runtime_config() -> None:
    config = load_app_config("configs")
    assert len(config.capabilities) >= 1
    assert len(config.scenes) >= 1
    assert len(config.templates) >= 1
    assert len(config.seed_cases) >= 1
    assert "default" in config.slot_policies
    assert "scenes" in config.slot_policies


def test_compiled_template_has_scene_id() -> None:
    config = load_app_config("configs")
    for template in config.templates:
        assert template.get("scene_id")
        assert template.get("template_id")
