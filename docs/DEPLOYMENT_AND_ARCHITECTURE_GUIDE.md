# 部署与架构指南（ES/OS 双后端）

本文用于部署、联调与运维，覆盖：

1. 服务启动方式  
2. Elasticsearch / OpenSearch 切换  
3. 请求处理链路（输入 -> 中间 -> 输出）  
4. 向量索引与 AC 词表维护  
5. 测试与 benchmark 基线

## 1. 服务定位

`chat_pre_check` 是前置路由引擎，不负责最终 SQL 执行。  
输出决策类型：

1. `refuse`：拒答  
2. `clarify`：追问补参  
3. `route_template`：命中稳定模板  
4. `route_nl2sql`：模板未命中时兜底

## 2. 快速启动

```bash
pip install -e ".[dev]"
python scripts/check_config.py --config-dir configs
uvicorn chat_pre_check.interfaces.api.app:create_app --factory --reload
```

## 3. 检索后端切换（当前 ES / 下版 OS）

后端来源优先级（高 -> 低）：

1. 命令行 `--search-backend`  
2. 环境变量 `CHAT_PRE_CHECK_SEARCH_BACKEND`  
3. `configs/vector.json -> search_backend`  
4. 默认值 `opensearch`

可选值：

1. `elasticsearch`（或 `es`）  
2. `opensearch`

### 3.1 部署到 Elasticsearch

```bash
# Linux/macOS
export CHAT_PRE_CHECK_SEARCH_BACKEND=elasticsearch
export CHAT_PRE_CHECK_OS_URL=http://<es-host>:9200

# Windows PowerShell
$env:CHAT_PRE_CHECK_SEARCH_BACKEND="elasticsearch"
$env:CHAT_PRE_CHECK_OS_URL="http://<es-host>:9200"
```

索引构建：

```bash
python scripts/build_vector_indices.py \
  --search-url http://<es-host>:9200 \
  --search-backend elasticsearch \
  --config-dir configs
```

### 3.2 切换到 OpenSearch

```bash
# Linux/macOS
export CHAT_PRE_CHECK_SEARCH_BACKEND=opensearch
export CHAT_PRE_CHECK_OS_URL=http://<os-host>:9200

# Windows PowerShell
$env:CHAT_PRE_CHECK_SEARCH_BACKEND="opensearch"
$env:CHAT_PRE_CHECK_OS_URL="http://<os-host>:9200"
```

在 OS 上重建索引：

```bash
python scripts/build_vector_indices.py \
  --search-url http://<os-host>:9200 \
  --search-backend opensearch \
  --config-dir configs
```

### 3.3 回滚建议

1. 仅切回 `CHAT_PRE_CHECK_SEARCH_BACKEND=elasticsearch` 并重启。  
2. ES 与 OS 使用独立集群和独立索引名，避免同名混用。

## 4. 配置文件职责

| 文件 | 作用 |
|---|---|
| `configs/capabilities.json` | 业务能力定义（见 `CAPABILITIES_GUIDE.md`） |
| `configs/rules.json` | 拒答、权限、输入边界规则 |
| `configs/thresholds.json` | 各中间件阈值 |
| `configs/vector.json` | 检索后端、Embedding、索引名、融合权重、AC 预提参参数 |
| `configs/ac_terms.json` | AC 词表（设备/地域/KPI/告警等） |

## 5. 请求处理链路（业务视角）

输入：用户文本（`input_text`）

执行链路：

1. `Normalize`：文本归一化  
2. `InputGuard`：长度边界校验  
3. `PolicyGuard`：策略与权限拦截  
4. `FlowRouter`：query/report/direct/unknown 分流（可选单次 LLM 增强）  
5. `EntityExtractor`：规则抽取时间/topN/意图等  
6. `ParamPrefill(AC)`：AC 分域预提参，提前识别设备/地域/KPI/告警参数  
7. `EntityEnricher`：远程 resolver 补齐实体候选  
8. `ScopeGate`：场景判定（规则分 + 向量分 + 实体分融合）  
9. `SceneRouter`：场景同步/兜底  
10. `SlotClarifier`：缺槽位则追问  
11. `ReportRouter`：报告流直通  
12. `TemplateMatcher`：模板匹配（规则 + 向量 + 槽位适配）  
13. `SeedScopeGuard`：仅在模板未命中、即将走 NL2SQL 时进行能力边界守卫（可开关）  
14. `NL2SQLRouter`：模板未命中兜底

输出：`RouteDecision`

关键字段：

1. `type`  
2. `scene`  
3. `template_id`（若命中模板）  
4. `slots`  
5. `missing_slots`  
6. `options`  
7. `out_of_scope_reason`  
8. `trace`

## 6. AC 词表与提参流程

### 6.1 导出 AC 词表

```bash
python scripts/export_ac_terms.py \
  --search-url http://localhost:9200 \
  --search-backend elasticsearch \
  --config-dir configs \
  --output configs/ac_terms.json \
  --merge-existing
```

### 6.2 开关与关键参数（`vector.json -> param_prefill`）

| 参数 | 说明 |
|---|---|
| `enabled` | AC 预提参开关 |
| `dictionary_file` | 词表文件 |
| `auto_commit` | 是否自动写槽位 |
| `commit_score/min_gap` | 落槽位阈值与分差 |
| `domain_router` | 分域路由（场景/关键词/槽位） |
| `domain_priority` | 跨域优先级 |
| `slot_domain_priority` | 槽位级域优先级 |
| `domain_penalty` | 跨域惩罚系数 |
| `skip_remote_resolver_when_prefilled` | 预提参命中后是否跳过远程解析 |

### 6.3 Embedding 配置（`vector.json -> embedding`）

| 参数 | 说明 |
|---|---|
| `provider` | `sentence_transformers` / `openai_compatible` |
| `model` | 向量模型名 |
| `dimension` | 向量维度（会用于 ES/OS 索引建模） |
| `query_prefix/passage_prefix` | 查询/文档编码前缀（E5 推荐保留） |
| `base_url/endpoint_path` | 远程 Embedding 服务地址与路径（openai_compatible） |
| `api_key_env` | 远程 Embedding 密钥环境变量名 |

说明：构建索引脚本会使用 `embedding.dimension` 创建向量字段，避免 768/512 切换时索引错配。

## 7. LLM 接口可变配置（`rules.json -> llm`）

| 参数 | 说明 |
|---|---|
| `provider` | 当前支持 `openai_compatible` |
| `base_url/model` | 模型服务地址与模型名 |
| `base_url_env/model_env/api_key_env` | 环境变量映射 |
| `endpoint_path` | 聊天接口路径 |
| `api_key_header/api_key_prefix` | 鉴权 Header 名与前缀 |
| `model_field/messages_field/max_tokens_field` | 请求体字段名映射 |
| `response_content_path` | 响应内容路径（如 `choices.0.message.content`） |
| `request_extra` | 供应商扩展字段（JSON 对象） |

## 8. seed/intents 批量导入

```bash
python scripts/import_seed_cases.py \
  --input templates/seed_cases_template.csv \
  --input-format csv \
  --config-dir configs \
  --output configs/capabilities.json \
  --merge-mode upsert \
  --on-duplicate keep_last
```

导入目标是 `capability.intents`，不再维护独立 `seed_cases.json`。

## 9. API 示例

请求：

```json
{
  "input_text": "近24小时接口错误包告警Top10",
  "context": {},
  "tenant_id": "tenant_a",
  "role": "analyst",
  "trace_level": "compact"
}
```

响应：

```json
{
  "type": "route_template",
  "message": "已命中可执行模板。",
  "scene": "alarm.query",
  "template_id": "tpl_interface_alarm_topn",
  "slots": {},
  "missing_slots": [],
  "options": []
}
```

## 10. 测试与基线

### 9.1 单测

```bash
python -m pytest -q tests/unit
```

### 9.2 验收与 benchmark 测试

```bash
python -m pytest -q tests/acceptance/test_routing_acceptance.py
python -m pytest -q tests/acceptance/test_network_ops_extended.py
python -m pytest -q tests/benchmark/test_network_ops_benchmark.py
```

### 9.3 benchmark 评测

```bash
python scripts/eval_network_ops_benchmark.py \
  --dataset benchmark/network_ops_business_golden_v1.json \
  --profile local_fallback \
  --repeat 3

python scripts/eval_network_ops_benchmark.py \
  --dataset benchmark/network_ops_regression_local_fallback_v1.json \
  --profile local_fallback \
  --repeat 3 \
  --min-accuracy 1.0 \
  --min-stability 1.0
```

## 11. 运维建议

建议最少监控以下指标：

1. `decision_type_count{type}`  
2. `refuse_reason_count{reason}`  
3. `clarify_missing_slot_count{slot}`  
4. `middleware_latency_ms{step}`  
5. `retrieval_error_count{component}`

变更流程建议：

1. 配置改动先过 `check_config.py`。  
2. 先跑 unit + acceptance + benchmark。  
3. 小流量灰度后再全量。  
4. 所有模板与规则变更必须附带回归样例。
