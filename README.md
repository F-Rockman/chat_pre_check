# chat_pre_check

对话场景前置校验引擎（拒答/推荐、追问、模板命中、NL2SQL 路由）。

## 快速 Demo（本地）
直接跑内置 demo（离线 mock，不依赖 OpenSearch）：
```bash
python main.py
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
- 决策链路：`Normalize -> Extract -> Enrich -> Policy -> Scope -> Scene -> Clarify -> Template -> NL2SQL`
- 规则 + 向量融合（`intfloat/multilingual-e5-base` + OpenSearch）
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
python scripts/build_vector_indices.py --os http://localhost:9200 --config-dir configs
```

`seed_case_v1` 接口已预留（默认关闭能力边界拦截）：
- 索引名配置：`configs/vector.json -> seed_case_index`
- 守卫开关：`configs/vector.json -> seed_scope_guard.enabled`
- 槽位追问策略：`configs/slot_policies.json`

## seed_case 批量导入
```bash
python scripts/import_seed_cases.py \
  --input templates/seed_cases_template.csv \
  --input-format csv \
  --config-dir configs \
  --output configs/seed_cases.json \
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

## 指导文档
- 生产使用与规则设计指南：[docs/PRODUCTION_GUIDE.md](docs/PRODUCTION_GUIDE.md)
- seed_case 字段规范与导入指南：[docs/SEED_CASE_SPEC.md](docs/SEED_CASE_SPEC.md)
