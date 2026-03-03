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
- 决策链路：`Normalize -> Extract -> Prefill(AC) -> Enrich -> Policy -> Scope -> Scene -> SeedGuard -> Clarify -> Template -> NL2SQL`
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

## seed_case 批量导入
```bash
python scripts/import_seed_cases.py \
  --input templates/seed_cases_template.csv \
  --input-format csv \
  --config-dir configs \
  --output configs/capabilities.json \
  --merge-mode upsert \
  --on-duplicate keep_last
```

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
- 生产使用与规则设计指南：[docs/PRODUCTION_GUIDE.md](docs/PRODUCTION_GUIDE.md)
- seed_case 字段规范与导入指南：[docs/SEED_CASE_SPEC.md](docs/SEED_CASE_SPEC.md)
- 检索后端切换（ES 当前 / OS 下一版）：`docs/PRODUCTION_GUIDE.md` 的 `2.2` 小节
- 检索后端双栈开发指南：[docs/SEARCH_BACKEND_ARCHITECTURE_GUIDE.md](docs/SEARCH_BACKEND_ARCHITECTURE_GUIDE.md)
- 版本变更记录：[CHANGELOG.md](CHANGELOG.md)
