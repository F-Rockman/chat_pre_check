from __future__ import annotations

from template_capability.openai_client import parse_json_content


def test_parse_json_content_strips_think_tags():
    payload = parse_json_content(
        "<think>先分析一下 query</think>"
        '{"slots": {"topn": 10}}'
    )

    assert payload == {"slots": {"topn": 10}}


def test_parse_json_content_accepts_markdown_json_block():
    payload = parse_json_content(
        "这里是结果：\n"
        "```json\n"
        '{"slots": {"cpu_threshold": 80}}\n'
        "```"
    )

    assert payload == {"slots": {"cpu_threshold": 80}}


def test_parse_json_content_accepts_content_arrays():
    payload = parse_json_content(
        [
            {"text": "<think>先想一下</think>"},
            {"text": '{"slots": {"memory_threshold": 70}}'},
        ]
    )

    assert payload == {"slots": {"memory_threshold": 70}}
