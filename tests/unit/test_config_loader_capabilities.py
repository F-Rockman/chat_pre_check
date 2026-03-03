from __future__ import annotations

from chat_pre_check.infrastructure.config.loader import _compile_capabilities, load_app_config


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


def test_compile_intents_into_template_and_seed_views() -> None:
    capabilities = [
        {
            "capability_id": "device.query",
            "description": "device query",
            "scope": {"keywords": ["设备"], "examples": ["查设备"]},
            "slots": {"required": ["time_range"], "conditional": [], "defaults": {}},
            "intents": [
                {
                    "case_id": "seed_device_trend",
                    "label": "设备告警趋势",
                    "text": "近7天设备A告警趋势",
                    "keywords": ["设备", "告警", "趋势"],
                    "examples": ["近7天设备A告警趋势", "设备A今天告警趋势"],
                    "negative_keywords": ["相关性"],
                    "enabled": True,
                    "template": {
                        "template_id": "tpl_alarm_trend_device",
                        "slot_schema": {
                            "required": ["device_id", "time_range"],
                            "optional": ["severity"],
                        },
                    },
                }
            ],
        }
    ]
    _scenes, templates, _cases, seed_cases, _slot_policies = _compile_capabilities(
        capabilities=capabilities,
        slot_policy_defaults={},
    )
    assert len(templates) == 1
    assert templates[0]["template_id"] == "tpl_alarm_trend_device"
    assert templates[0]["scene_id"] == "device.query"
    assert templates[0]["keywords"] == ["设备", "告警", "趋势"]
    assert len(seed_cases) == 1
    assert seed_cases[0]["case_id"] == "seed_device_trend"
    assert seed_cases[0]["template_id"] == "tpl_alarm_trend_device"
