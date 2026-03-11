# Test Report

Generated on 2026-03-11.

## Static Regression

- `python -m pytest -q`
- Result: `133 passed, 1 skipped`
- Raw output: `reports/pytest_report.txt`

## Evaluation Corpus

- `python tools/evaluate_matcher.py`
- Total cases: `75`
- Passed: `75`
- Failed: `0`
- Pass rate: `100.00%`
- JSON report: `reports/evaluation_report.json`
- Text report: `reports/evaluation_report.txt`

## Live LLM Slot Fallback

- Benchmark script: `python tools/benchmark_llm_slot_fallback.py --json --output reports/llm_slot_benchmark.json`
- Case count: `5`
- Baseline fully matched: `0/5`
- With template-level LLM slot fallback: `5/5`
- Improved cases: `5`
- Average LLM elapsed time: `1135.35 ms`
- Max LLM elapsed time: `1553.79 ms`
- Queries completed within `3s`: `5/5`
- Raw benchmark: `reports/llm_slot_benchmark.json`

## Live Test

- `python -m pytest -q tests/test_live_llm_slot_fallback.py`
- Result: `1 passed in 1.87s`
- Raw output: `reports/live_llm_slot_pytest.txt`

## Notes

- The live LLM benchmark used the DashScope OpenAI-compatible endpoint with model `qwen3-coder-plus`.
- The template-level LLM path was only used after top1 template selection, not during full template recall.
