# 对话式前置处理 V1 最小落地实施清单

## 1. 目标与边界

本清单用于把 `docs/V1_CONVERSATIONAL_PRECHECK_DESIGN.md` 拆分成可执行开发任务，要求：

1. 保持洋葱模式与中间件流水线，不重写架构。
2. 每个阶段可独立提交、独立回滚。
3. 每个阶段都包含对应测试与验收门槛。
4. 优先保证落地效果，再逐步增强。

## 2. 总体实施策略

1. 先做“可用分流 + 可控追问”，再接 LLM，最后做推荐增强。
2. LLM 默认关闭，灰度开启，保证稳定发布。
3. 每阶段只改最小文件集合，避免一次改动过大。

## 3. 里程碑拆分（建议 6 次提交）

## M1. 配置与模型打底（Flow 基础字段）

### 目标

1. 在不改行为的前提下，完成 `query/report/direct/unknown` 的数据结构落位。
2. 建立后续 FlowRouter、LLM、追问轮次的配置入口。

### 代码改动

1. `configs/capabilities.json`
2. `configs/rules.json`
3. `src/chat_pre_check/infrastructure/config/loader.py`
4. `src/chat_pre_check/infrastructure/config/validator.py`
5. `src/chat_pre_check/domain/models.py`
6. `src/chat_pre_check/interfaces/api/dto.py`

### 具体内容

1. capability 新增可选字段：`flow_type`、`router_priority`、`entry_phrases`、`clarify`、`llm_assist`、`execution`。
2. rules 新增块：`flow_router`、`llm`、`clarify`、`recommendation`、`context`。
3. Request/Response 上下文字段扩展但保持兼容（字段可选，不强制输入）。

### 测试新增/修改

1. `tests/unit/test_config_loader_capabilities.py`
2. `tests/unit/test_config_validator.py`
3. `tests/contract/test_api_contract.py`

### 验收标准

1. `python scripts/check_config.py --config-dir configs` 通过。
2. 所有已有 unit/contract 不回归。

### 提交建议

1. `feat: add v1 flow/context config schema scaffolding`

## M2. FlowRouter 中间件（规则优先，无 LLM）

### 目标

1. 在现有洋葱链路中增加“业务流分流层”。
2. 实现 `query/report/direct/unknown` 的稳定分流。

### 代码改动

1. `src/chat_pre_check/application/middlewares/flow_router.py`（新增）
2. `src/chat_pre_check/bootstrap.py`（注入中间件顺序）
3. `src/chat_pre_check/application/middlewares/scope_gate.py`（按 flow 过滤候选）
4. `src/chat_pre_check/application/services/recommendation.py`（flow-aware 推荐）

### 测试新增/修改

1. `tests/unit/test_flow_router.py`（新增）
2. `tests/unit/test_pipeline_order.py`（更新顺序断言）
3. `tests/acceptance/test_routing_acceptance.py`（新增 flow 分流样例）

### 验收标准

1. 安全拒答仍在分流前触发。
2. query/report 基础分流正确率可达可测阈值（建议 >= 0.9，样例集）。

### 提交建议

1. `feat: add flow router middleware with rule-first routing`

## M3. ClarifyManager 轮次控制（3-5 轮）

### 目标

1. 把追问从“单轮判定”升级为“多轮可控（3-5轮）”。
2. 达上限后自动拒答并给推荐，不死循环追问。

### 代码改动

1. `src/chat_pre_check/application/middlewares/slot_clarifier.py`（轮次控制）
2. `src/chat_pre_check/domain/models.py`（`clarify_round/pending_slots`）
3. `src/chat_pre_check/application/engine.py`（context merge 规则）
4. `src/chat_pre_check/interfaces/api/dto.py`（context 字段兼容）
5. `src/chat_pre_check/application/services/slot_policy.py`（可选：按轮次降噪）

### 测试新增/修改

1. `tests/unit/test_slot_clarifier_rounds.py`（新增）
2. `tests/unit/test_engine_basic.py`（上下文透传）
3. `tests/acceptance/test_network_ops_extended.py`（多轮追问场景）

### 验收标准

1. 追问上限可配置（3-5）。
2. 到上限行为稳定：返回 `refuse` 且有推荐。

### 提交建议

1. `feat: add clarify rounds and context-driven follow-up control`

## M4. 报告流最小闭环（Report 路由）

### 目标

1. 让 `report` 流可被独立识别并路由。
2. 至少支持“报告模板命中 + 报告规划兜底”两种结果。

### 代码改动

1. `configs/capabilities.json`（新增 `report.inspect` 能力）
2. `src/chat_pre_check/application/middlewares/report_template_matcher.py`（新增）
3. `src/chat_pre_check/application/middlewares/report_router.py` 或复用 `nl2sql_router.py`
4. `src/chat_pre_check/domain/enums.py`（可选新增 `route_report`）
5. `src/chat_pre_check/domain/models.py`（响应字段可选扩展）
6. `src/chat_pre_check/bootstrap.py`（插入 report 分支）

### 测试新增/修改

1. `tests/unit/test_report_flow.py`（新增）
2. `tests/acceptance/test_report_acceptance.py`（新增）
3. `tests/contract/test_api_contract.py`（确保字段兼容）

### 验收标准

1. “生成巡检报告”至少可稳定进入 `report` 流。
2. query/report 不串流。

### 提交建议

1. `feat: add minimal report flow routing and execution fallback`

## M5. LLM 单次增强（灰度开关）

### 目标

1. 仅在不确定场景触发 LLM 一次，提高分流与缺槽位判断稳定性。
2. 严格控制调用次数和时延。

### 代码改动

1. `src/chat_pre_check/application/services/llm_assist.py`（新增）
2. `src/chat_pre_check/infrastructure/llm/client.py`（新增）
3. `src/chat_pre_check/application/middlewares/flow_router.py`（接入单次增强）
4. `src/chat_pre_check/application/middlewares/slot_clarifier.py`（可选增强）
5. `configs/rules.json`（llm 开关与阈值）
6. `src/chat_pre_check/bootstrap.py`（注入 LLM 依赖）

### 测试新增/修改

1. `tests/unit/test_llm_assist_single_call.py`（新增，校验每请求 <=1 次）
2. `tests/unit/test_flow_router.py`（低置信触发逻辑）
3. `tests/unit/test_robustness.py`（超时降级）

### 验收标准

1. 默认 `llm.enabled=false` 行为与 M4 一致。
2. 开启后可观测字段齐全：`llm_called`、`llm_latency_ms`、`llm_fallback`。
3. 超时/异常不影响主流程可用。

### 提交建议

1. `feat: add single-call llm assist with timeout fallback`

## M6. 推荐增强（相似度+热度）

### 目标

1. 拒答与追问推荐从“静态模板优先”升级为“相似度+热度”。
2. 保持轻实现，不引入复杂实时计算。

### 代码改动

1. `src/chat_pre_check/application/services/recommendation.py`
2. `src/chat_pre_check/application/services/hot_queries.py`（新增，可内存或文件）
3. `configs/rules.json`（推荐权重与窗口）
4. `src/chat_pre_check/application/engine.py`（请求结束后可选埋点）

### 测试新增/修改

1. `tests/unit/test_recommendation_service.py`
2. `tests/unit/test_hot_queries.py`（新增）
3. `tests/benchmark/test_network_ops_benchmark.py`（增加推荐稳定性断言）

### 验收标准

1. 推荐结果可解释：输出相似度与热度组成信息（trace）。
2. 同一输入在固定窗口内推荐稳定。

### 提交建议

1. `feat: add hybrid recommendation ranking with hot query signals`

## 4. 每阶段固定回归脚本

每个里程碑完成后执行：

1. `python scripts/check_config.py --config-dir configs`
2. `python -m pytest -q -p no:cacheprovider tests/unit`
3. `python -m pytest -q -p no:cacheprovider tests/acceptance/test_routing_acceptance.py tests/acceptance/test_network_ops_extended.py tests/contract/test_api_contract.py`

在 M5、M6 后追加：

1. `python -m pytest -q -p no:cacheprovider tests/benchmark/test_network_ops_benchmark.py`

## 5. 提交节奏与回滚策略

提交建议：

1. 严格按 M1~M6 顺序，禁止跨阶段大并发改动。
2. 每个提交只包含一个里程碑目标。
3. 每个提交前跑完阶段回归脚本。

回滚建议：

1. M5 LLM 风险最高，必须可通过配置一键关闭。
2. M2/M3 属于主链路变更，若回退需同时回退对应测试与配置字段。
3. 报告流（M4）可用 feature flag 独立关闭，不影响 query 主流程。

## 6. 最小派工建议（按角色）

1. 架构开发：M1、M2、M3（主链路与配置）
2. 业务开发：M4（报告流）
3. 平台开发：M5（LLM 接入）
4. 算法/策略：M6（推荐增强）
5. 测试开发：每阶段同步补齐 unit/acceptance/benchmark

