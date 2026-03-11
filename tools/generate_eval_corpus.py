from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path


DEFAULT_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"
DEFAULT_MODEL = "qwen3-coder-plus"


def parse_args() -> argparse.Namespace:
    """定义离线评测语料生成脚本参数。"""
    parser = argparse.ArgumentParser(description="Generate evaluation corpus with an OpenAI-compatible LLM.")
    parser.add_argument("--config", default="configs/templates.json")
    parser.add_argument("--output", default="tests/fixtures/evaluation_cases.generated.json")
    parser.add_argument("--base-url", default=os.environ.get("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--model", default=os.environ.get("DASHSCOPE_MODEL", DEFAULT_MODEL))
    return parser.parse_args()


def build_prompt(config_text: str) -> str:
    """把模板配置压成一个“只产评测语料 JSON”的窄任务。"""
    return f"""你在为一个“问数模板匹配引擎”生成离线评测语料。只生成中文 query，不要解释。

背景：
- 这是问数模板匹配，不是分析、报告、总结类任务。
- 需要覆盖：语序变化、口语化、省略、带噪声、同义词、提参顺序变化。
- 对于 partial：query 应该明显指向某个模板，但缺少必填槽位。
- 对于 unmatched：query 必须是不该命中任何模板的内容，尤其是分析、报告、预测、根因、总结等。
- 不要发明配置中不存在的 template_id。

模板配置如下：
{config_text}

输出 JSON，对象结构必须是：
{{
  "matched": [{{"text": "...", "template_id": "..."}}],
  "partial": [{{"text": "...", "template_id": "..."}}],
  "unmatched": [{{"text": "..."}}],
  "not_full_match": [{{"text": "..."}}]
}}

要求：
- matched 至少 24 条，每个模板至少 5 条
- partial 至少 12 条，每个模板至少 2 条
- unmatched 至少 12 条
- not_full_match 至少 8 条
- 只返回 JSON，不要 markdown，不要解释
"""


def generate_corpus(
    *,
    api_key: str,
    base_url: str,
    model: str,
    config_text: str,
) -> dict[str, object]:
    """调用兼容 OpenAI 协议的模型生成一份评测语料。"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You generate strict JSON for evaluation datasets."},
            {"role": "user", "content": build_prompt(config_text)},
        ],
        # 语料生成需要一定多样性，但仍然要避免过度发散。
        "temperature": 0.5,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    # 这里不做复杂兜底处理；如果模型侧返回坏 JSON，应该直接暴露出来，方便调 prompt。
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.load(response)
    content = body["choices"][0]["message"]["content"]
    return json.loads(content)


def main() -> None:
    """语料生成脚本主入口。"""
    args = parse_args()
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise SystemExit("Missing DASHSCOPE_API_KEY in environment.")

    # 直接把当前配置全文喂给模型，保证它只能围绕现有模板造样本。
    config_text = Path(args.config).read_text(encoding="utf-8")
    payload = generate_corpus(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        config_text=config_text,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # 仅打印输出路径，避免把大块语料刷到终端。
    print(output_path)


if __name__ == "__main__":
    main()
