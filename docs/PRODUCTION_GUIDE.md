# chat_pre_check 生产使用指导书

本文面向工程实施与运营配置，重点覆盖：
- 如何启动与接入 `chat_pre_check`
- 如何定义和维护追问规则、拒答规则、业务模板
- 如何在网络运维复杂场景下扩展配置与测试

## 1. 系统定位
`chat_pre_check` 是对话场景前置校验引擎，只负责路由决策：
- `refuse`：不在能力范围/策略限制/依赖不可用
- `clarify`：缺少关键槽位，触发追问
- `route_template`：命中稳定模板
- `route_nl2sql`：模板未命中时兜底

不负责 NL2SQL 生成、SQL 执行、前端渲染。

## 2. 快速启动
1. 安装依赖
```bash
pip install -e ".[dev]"
```

2. 校验配置
```bash
python scripts/check_config.py --config-dir configs
```

3. （可选）构建向量索引
```bash
python scripts/build_vector_indices.py --search-url http://localhost:9200 --config-dir configs
python scripts/build_vector_indices.py --search-url http://localhost:9200 --search-backend elasticsearch --config-dir configs
```

4. 启动 API
```bash
uvicorn chat_pre_check.interfaces.api.app:create_app --factory --reload
```

### 2.1 无 OpenSearch 运行可行性
可行，但建议用于以下场景：
- PoC、离线环境、低成本部署、边缘节点
- 能力范围较收敛，且接受召回率低于向量检索版

当前已提供本地 fallback 能力（启发式检索 + 规则解析）：
```bash
python livemain.py --without-opensearch
```

### 2.2 检索后端部署切换说明（ES 当前 / OS 下一版）
当前工程支持 `Elasticsearch` 与 `OpenSearch` 双后端，通过开关切换。

后端开关优先级（高 -> 低）：
1. 命令行参数：`--search-backend`
2. 环境变量：`CHAT_PRE_CHECK_SEARCH_BACKEND`
3. 配置文件：`configs/vector.json -> search_backend`
4. 默认值：`opensearch`

可选值：
- `elasticsearch`（或 `es`）
- `opensearch`

#### A. 当前版本部署到 Elasticsearch（推荐你当前环境使用）
1. 设置后端与地址
```bash
# Linux/macOS
export CHAT_PRE_CHECK_SEARCH_BACKEND=elasticsearch
export CHAT_PRE_CHECK_OS_URL=http://<es-host>:9200

# Windows PowerShell
$env:CHAT_PRE_CHECK_SEARCH_BACKEND="elasticsearch"
$env:CHAT_PRE_CHECK_OS_URL="http://<es-host>:9200"
```

2. 构建向量索引
```bash
python scripts/build_vector_indices.py \
  --search-url http://<es-host>:9200 \
  --search-backend elasticsearch \
  --config-dir configs
```

3. 启动服务
```bash
uvicorn chat_pre_check.interfaces.api.app:create_app --factory --reload
```

4. 本地探活（可选）
```bash
python livemain.py --search-backend elasticsearch --os-url http://<es-host>:9200
```

#### B. 下一版本切换到 OpenSearch
1. 先准备 OpenSearch 集群地址（不要直接复用 ES 索引）
2. 切换后端开关
```bash
# Linux/macOS
export CHAT_PRE_CHECK_SEARCH_BACKEND=opensearch
export CHAT_PRE_CHECK_OS_URL=http://<os-host>:9200

# Windows PowerShell
$env:CHAT_PRE_CHECK_SEARCH_BACKEND="opensearch"
$env:CHAT_PRE_CHECK_OS_URL="http://<os-host>:9200"
```

3. 在 OpenSearch 上重建索引
```bash
python scripts/build_vector_indices.py \
  --search-url http://<os-host>:9200 \
  --search-backend opensearch \
  --config-dir configs
```

4. 重启服务并验证
```bash
uvicorn chat_pre_check.interfaces.api.app:create_app --factory --reload
python livemain.py --search-backend opensearch --os-url http://<os-host>:9200
```

#### C. 灰度与回滚建议
- 灰度：先在一台实例上设置 `CHAT_PRE_CHECK_SEARCH_BACKEND=opensearch`，观察路由准确率和稳定性指标后再全量。
- 回滚：将该变量改回 `elasticsearch` 并重启实例即可，应用层无代码回滚依赖。
- 建议：ES 与 OpenSearch 使用各自集群和各自索引生命周期管理，避免同名索引造成运维混淆。

## 3. 对外接口
### 3.1 请求
`POST /v1/precheck/route`

```json
{
  "input_text": "近24小时接口错误包告警Top10",
  "context": {},
  "tenant_id": "tenant_a",
  "role": "analyst",
  "trace_level": "compact"
}
```

### 3.2 响应
```json
{
  "type": "route_template",
  "message": "已命中可执行模板。",
  "scene": "alarm.query",
  "template_id": "tpl_interface_alarm_topn",
  "slots": {},
  "missing_slots": [],
  "options": [],
  "out_of_scope_reason": null,
  "trace": {}
}
```

## 4. 配置模型（核心）
配置目录：
- `configs/capabilities.json`（统一能力定义：scene/template/seed_case/recommendation/slot_policy）
- `configs/rules.json`
- `configs/thresholds.json`
- `configs/vector.json`（含 `search_backend` 开关：`opensearch` / `elasticsearch`）

seed_case 批量导入与字段规范见：
- [SEED_CASE_SPEC.md](D:/GitHub/chat_pre_check/docs/SEED_CASE_SPEC.md)

### 4.1 Scene（场景）
每个 `capability` 内的 `slots/scope` 定义能力边界、必填槽位、默认值、追问策略。

关键字段：
- `scene_id`
- `required_slots`
- `conditional_slots`
- `defaults`
- `keywords` / `examples`

实践建议：
- `required_slots` 只放对路由有决定性的槽位。
- 通过 `defaults` 减少追问轮次（如 `time_range=last_24h`）。
- `conditional_slots` 用于意图触发型必填（如 `intent=trend` 时必须有 `device_id`）。

### 4.2 Template（模板）
每个 `capability.templates[*]` 定义“稳定可控查询”。

关键字段：
- `template_id`, `scene_id`
- `keywords`, `negative_keywords`
- `slot_schema.required/optional`
- `examples`

实践建议：
- `negative_keywords` 必须覆盖容易误命中的反例词（如“相关性”“同比”）。
- `examples` 至少覆盖 3 种写法：短句、口语、带过滤条件。
- 模板命中但缺参时，必须回 `clarify`，不直接降级 NL2SQL。

### 4.3 Rule（拒答/策略）
关键字段位于 `rules.json`：
- `unknown_domain_keywords`
- `unsupported_domain_keywords`
- `policy_block_keywords`
- `data_unavailable_keywords`
- `permission_rules`
- `max_input_chars` / `min_input_chars`

实践建议：
- 关键词规则按“高风险优先”排序维护。
- 权限规则采用“角色 + 关键词”双条件，避免误拦截。
- 输入长度限制建议在 500~2000 之间按业务压力调节。

## 5. 如何定义追问规则
追问由 `SlotClarifierMiddleware` + `SlotPolicyEngine` 触发，策略如下：
- 先补默认值，再检查缺失槽位。
- 一轮最多追问 N 个槽位（可配置）。
- 槽位优先级由 `capabilities.json -> slot_policy_defaults / capability.slot_policy` 配置，不再写死代码。

配置方法：
1. 在 `capability.slots.required` 声明基础必填槽位。
2. 在 `capability.slots.conditional` 声明意图相关必填槽位。
3. 在 `capabilities.json` 中配置 `slot_policy_defaults` 与 `capability.slot_policy` 的 `priority/ask_cost/defaultable/infer_from/applies_when`。
4. 在 `RecommendationService.slot_clarify_options()` 中维护槽位候选按钮。

示例（条件追问）：
```json
{
  "if_slot": "intent",
  "equals": "trend",
  "required_slots": ["device_id"]
}
```

## 6. 如何定义拒答规则
拒答分为两类：
- 业务拒答：未知域、不支持域、权限不足、策略拦截
- 系统拒答：OpenSearch/向量检索失败、流水线异常

要求：
- 所有拒答必须附带 3~6 个可点击推荐。
- `trace.reason` 必须可定位（例如 `policy_blocked`、`scene_retrieval_failed`）。

### 6.1 能力边界拒答（Seed Scope Guard）
当 `vector.json -> seed_scope_guard.enabled=true` 时：
- 引擎会检索 `seed_case_v1`（通过 `search_seed_cases` 接口）
- 若 `top1_score < min_score` 或命中数不足，返回 `out_of_seed_scope`
- 同时返回相近 seed case 作为推荐按钮

这样可以把 NL2SQL 能力控制在你确认过的能力边界内，后续能力增强后再逐步放开阈值或关闭守卫。

## 7. 网络运维领域扩展方法
### 7.1 推荐槽位字典
建议统一 canonical 值：
- `metric`：`packet_loss`, `latency`, `jitter`, `cpu_usage`, `memory_usage`, `bandwidth_usage`, `throughput`
- `protocol`：`bgp`, `ospf`, `isis`, `mpls`
- `object_scope`：`network`, `core_network`, `device`, `port`, `interface`, `link`, `site`

### 7.2 典型模板清单
已内置示例：
- `tpl_interface_alarm_topn`
- `tpl_bgp_flap_topn`
- `tpl_device_cpu_hotspot`
- `tpl_packet_loss_region_rank`

扩展时建议：
- 每个模板至少 2 个真实问法示例。
- 明确 required slots，避免执行歧义。
- 用 `negative_keywords` 抑制跨模板误命中。

## 8. 测试策略
### 8.1 默认测试（不依赖 OpenSearch）
```bash
python -m pytest -q -m "not integration"
```

### 8.2 基础验收（20条）
```bash
python -m pytest -q tests/acceptance/test_routing_acceptance.py
```

### 8.3 网络运维扩展验收
```bash
python -m pytest -q tests/acceptance/test_network_ops_extended.py
```

### 8.4 集成测试（真实 OpenSearch）
```bash
python -m pytest -q -m integration --os-base-url http://localhost:9200
```

### 8.5 准确率与稳定性基线
先生成网络运维 benchmark 数据：
```bash
python scripts/build_network_ops_benchmark_datasets.py
```

数据集说明：
- `benchmark/network_ops_business_golden_v1.json`：业务黄金集（衡量真实准确率）
- `benchmark/network_ops_regression_local_fallback_v1.json`：本地回归集（衡量稳定性/回归）

评测命令：
```bash
python scripts/eval_network_ops_benchmark.py --dataset benchmark/network_ops_business_golden_v1.json --profile local_fallback --repeat 3
python scripts/eval_network_ops_benchmark.py --dataset benchmark/network_ops_regression_local_fallback_v1.json --profile local_fallback --repeat 3 --min-accuracy 1.0 --min-stability 1.0
```

## 9. 生产运维建议
1. 监控指标
- `decision_type_count{type}`
- `refuse_reason_count{reason}`
- `clarify_missing_slot_count{slot}`
- `middleware_latency_ms{step}`
- `retrieval_error_count{component}`

2. 回放机制
- 持久化 `trace.request_id + trace.steps + input_text + decision`。
- 按误杀/漏放样本回放阈值和配置变更效果。

3. 变更流程
- 配置改动先过 `check_config.py`。
- 先跑 `acceptance` 再灰度，最后全量。
- 模板/规则每次改动必须附带新增测试样例。
