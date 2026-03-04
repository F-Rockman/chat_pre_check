# chat_pre_check

对话场景前置校验引擎（拒答/推荐、追问、模板命中、NL2SQL 路由）。

## 快速 Demo（本地）
直接跑内置 demo（离线 mock，不依赖检索后端）：
```bash
python main.py
```

## Live 一把跑（推荐 VSCode）
优先连接本地向量检索后端（OpenSearch/Elasticsearch），连不上自动切到无检索后端的本地 fallback：
```bash
python livemain.py
```

指定后端为 Elasticsearch：
```bash
python livemain.py --search-backend elasticsearch --os-url http://localhost:9200
```

强制无检索后端模式：
```bash
python livemain.py --without-opensearch
# 等价参数：
# python livemain.py --without-search-backend
```

必须用检索后端（不可用则退出）：
```bash
python livemain.py --require-opensearch
# 等价参数：
# python livemain.py --require-search-backend
```

跑网络运维 demo 集：
```bash
python main.py --demo-set network_ops
```

交互模式：
```bash
python main.py --interactive
```

真实依赖联调（live）：
```bash
python main.py --mode live --os-url http://localhost:9200 --demo-set all
```

## 核心能力
- 洋葱架构：`domain -> application -> infrastructure -> interfaces`
- 决策链路：`Normalize -> InputGuard -> Policy -> FlowRouter -> Extract -> Prefill(AC) -> Enrich -> Scope -> Scene -> Clarify -> ReportRouter/Template -> SeedGuard -> NL2SQL`
- 规则 + 向量融合（`intfloat/multilingual-e5-base` + ES/OS 检索后端）
- FastAPI 接口：`POST /v1/precheck/route`
- 20 条验收样例（拒答、追问、模板命中、NL2SQL 分流）

## 快速开始
```bash
pip install -e ".[dev]"
python scripts/check_config.py --config-dir configs
uvicorn chat_pre_check.interfaces.api.app:create_app --factory --reload
```

## 构建向量索引
```bash
python scripts/build_vector_indices.py --search-url http://localhost:9200 --config-dir configs
python scripts/build_vector_indices.py --search-url http://localhost:9200 --search-backend elasticsearch --config-dir configs
```

## LLM 单次增强（可选）
默认关闭；仅在分流不确定时单次调用，失败自动降级规则链路。

1. 配置开关：`configs/rules.json -> llm.enabled=true`
2. 环境变量：
```bash
set CHAT_PRE_CHECK_LLM_BASE_URL=https://coding.dashscope.aliyuncs.com/v1
set CHAT_PRE_CHECK_LLM_MODEL=qwen3.5-plus
set CHAT_PRE_CHECK_LLM_API_KEY=<your_token>
```
3. 约束：
- 每请求最多 1 次调用
- 超时默认 2500ms（可配置）
- 默认关闭思维链输出（`enable_thinking=false`）并启用 JSON 响应模式（`response_format_json=true`）
- 默认只在“分流歧义”触发 LLM（`flow_router.llm_on_low_confidence=false`）
- 不依赖 LLM 也可正常运行

## 导出 AC 提参词表（数据库 -> ac_terms.json）
从检索库（设备/地域索引）导出词条并生成 `configs/ac_terms.json`：
```bash
python scripts/export_ac_terms.py \
  --search-url http://localhost:9200 \
  --search-backend elasticsearch \
  --config-dir configs \
  --output configs/ac_terms.json \
  --merge-existing
```

启用 AC 预提参（`configs/vector.json`）：
- `param_prefill.enabled=true`
- `param_prefill.dictionary_file=ac_terms.json`
- `param_prefill.domain_router.max_domains=2`（按场景/关键词只激活部分业务域）
- `param_prefill.slot_domain_priority`（同槽位跨域冲突仲裁）

`seed_case_v1` 接口已预留（默认关闭能力边界拦截）：
- 索引名配置：`configs/vector.json -> seed_case_index`
- 后端开关：`configs/vector.json -> search_backend`（`opensearch` / `elasticsearch`）
- 守卫开关：`configs/vector.json -> seed_scope_guard.enabled`
- 统一能力定义：`configs/capabilities.json`

## intents 批量导入（seed 来源）
```bash
python scripts/import_seed_cases.py \
  --input templates/seed_cases_template.csv \
  --input-format csv \
  --config-dir configs \
  --output configs/capabilities.json \
  --merge-mode upsert \
  --on-duplicate keep_last
```
导入结果会写入 `configs/capabilities.json -> capability.intents`（统一定义，运行期自动编译出 `seed_cases/templates` 视图）。

## 测试
```bash
python -m pytest -q -m "not integration"
python -m pytest -q tests/acceptance/test_routing_acceptance.py
python -m pytest -q tests/acceptance/test_network_ops_extended.py
python -m pytest -q -m integration --os-base-url http://localhost:9200
```

## 准确率与稳定性评测（网络运维）
生成 benchmark 数据集（业务黄金集 + 本地回归集）：
```bash
python scripts/build_network_ops_benchmark_datasets.py
```

评测业务黄金集（看当前能力准确率）：
```bash
python scripts/eval_network_ops_benchmark.py \
  --dataset benchmark/network_ops_business_golden_v1.json \
  --profile local_fallback \
  --repeat 3 \
  --report-file benchmark/report_business_local.json
```

评测本地回归集（卡稳定性回归）：
```bash
python scripts/eval_network_ops_benchmark.py \
  --dataset benchmark/network_ops_regression_local_fallback_v1.json \
  --profile local_fallback \
  --repeat 3 \
  --min-accuracy 1.0 \
  --min-stability 1.0
```

## 指导文档
- capabilities 配置字段与业务建模指南：[docs/CAPABILITIES_GUIDE.md](docs/CAPABILITIES_GUIDE.md)
- 部署、后端切换与链路架构指南：[docs/DEPLOYMENT_AND_ARCHITECTURE_GUIDE.md](docs/DEPLOYMENT_AND_ARCHITECTURE_GUIDE.md)
- 对话式前置处理 V1 总体设计稿（含配置草案、时序图、决策表）：[docs/V1_CONVERSATIONAL_PRECHECK_DESIGN.md](docs/V1_CONVERSATIONAL_PRECHECK_DESIGN.md)
- 对话式前置处理 V1 最小落地实施清单（按文件/测试/提交拆分）：[docs/V1_MINIMAL_IMPLEMENTATION_CHECKLIST.md](docs/V1_MINIMAL_IMPLEMENTATION_CHECKLIST.md)
- 版本变更记录：[CHANGELOG.md](CHANGELOG.md)
