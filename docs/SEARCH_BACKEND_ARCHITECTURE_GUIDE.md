# 检索后端双栈能力开发指南（Elasticsearch / OpenSearch）

## 1. 文档目的
本文面向后续开发、学习、重构，说明当前检索后端双栈能力（`Elasticsearch` 与 `OpenSearch`）的设计与实现。

覆盖内容：
- 架构与职责边界
- 当前能力与限制
- 运行流程与调用链路
- 关键技术点与实现细节
- 使用方式（配置、环境变量、命令行）
- 后续重构建议与演进方向

## 2. 功能定位
`chat_pre_check` 是一个路由决策引擎，向量检索是其中一层能力。
本次能力的定位是：
- 让引擎在不改业务中间件逻辑的前提下，支持两种检索后端：`OpenSearch`、`Elasticsearch`
- 通过开关切换后端，支持“当前 ES、下版本 OS”的平滑迁移
- 保持本地 fallback、mock、benchmark 等流程不受影响

## 3. 总体架构

### 3.1 分层视角
- `interfaces`：API / CLI / livemain 入口，接收开关参数
- `bootstrap`：组装引擎与依赖，完成后端客户端注入
- `application`：中间件流水线（Scope/Template/Enrich 等）
- `infrastructure`：检索客户端、检索器、统一能力配置加载、索引构建脚本

### 3.2 关键组件
- 后端选择工厂：`src/chat_pre_check/infrastructure/resolvers/search_client_factory.py`
- OpenSearch 客户端：`.../resolvers/opensearch_client.py`
- Elasticsearch 客户端：`.../resolvers/elasticsearch_client.py`
- 混合检索器（向量 + 文本融合）：`.../retrievers/opensearch_vector_retriever.py`
- 引擎装配：`src/chat_pre_check/bootstrap.py`

## 4. 代码地图（职责速查）

| 文件 | 角色 | 关键点 |
|---|---|---|
| `bootstrap.py` | 依赖装配 | 读取配置，调用 `build_search_client`，注入 retriever/resolver |
| `search_client_factory.py` | 后端工厂 | 统一解析后端开关，返回 `opensearch/elasticsearch` 客户端 |
| `opensearch_client.py` | OS 实现 | `knn_vector` 索引、`knn` 查询、`text_search`、重试 |
| `elasticsearch_client.py` | ES 实现 | `dense_vector` 索引、`knn` 查询 + `script_score` 回退、重试 |
| `opensearch_vector_retriever.py` | 后端无关检索器 | 调用 `client.knn_search/text_search`，进行融合打分 |
| `infrastructure/extractors/ac_prefill.py` | AC 提参算法 | 分域 AC 管理器、词表加载、候选合并 |
| `application/middlewares/param_prefill.py` | 预提参中间件 | 域路由 + 结果仲裁 + 上下文写入 |
| `device_resolver.py` / `region_resolver.py` | 实体解析 | 依赖 `client.text_search`，对设备/地域候选归一化 |
| `interfaces/api/app.py` | API 入口 | 支持 `CHAT_PRE_CHECK_SEARCH_BACKEND` |
| `interfaces/cli/main.py` | CLI 入口 | 支持 `--search-backend` |
| `livemain.py` | 运维/联调入口 | 统一后端探活与索引存在性检查 |
| `scripts/build_vector_indices.py` | 索引构建 | 支持 `--search-backend`，按后端建索引并写入 |
| `scripts/export_ac_terms.py` | AC 词表导出 | 从设备/地域索引导出词条并生成 `ac_terms.json` |
| `configs/capabilities.json` | 统一能力定义 | `capability.intents` 统一定义（seed + optional template） |
| `configs/vector.json` | 配置默认值 | `search_backend` 默认配置 |
| `validator.py` | 配置校验 | 校验 `search_backend` 可选值合法性 |

## 5. 核心能力清单

### 5.1 后端切换能力
- 支持后端值：
  - `opensearch`
  - `elasticsearch`
  - `es`（别名，等价 `elasticsearch`）
- 解析优先级（高 -> 低）：
  1. 函数参数 / 命令行参数 `search_backend`
  2. 环境变量 `CHAT_PRE_CHECK_SEARCH_BACKEND`
  3. 配置 `configs/vector.json -> search_backend`
  4. 默认 `opensearch`

### 5.2 统一客户端契约（当前为约定，未显式 Protocol）
检索客户端需实现以下方法：
- `ping() -> bool`
- `index_exists(index_name) -> bool`
- `ensure_vector_index(index_name, dimension)`
- `bulk_index(index_name, docs)`
- `knn_search(index_name, vector, topk, must_filters=None)`
- `text_search(index_name, text, topk, must_filters=None, fields=None)`

### 5.3 统一检索流程
`OpenSearchVectorRetriever`（名称历史遗留）同时适配 ES/OS：
- 向量召回：`knn_search`
- 关键词召回：`text_search`
- 融合：归一化后按 `fusion_alpha` 加权

## 6. 关键流程

### 6.1 引擎启动流程（API/CLI/livemain 共用）
1. `load_app_config` 读取 `vector.json`
   - 同时加载 `capabilities.json` 并编译成运行期对象
2. `build_engine` 根据 `os_url` 决定是否走远端检索
3. 若走远端：
   - 调用 `build_search_client` 选择 ES/OS 客户端
   - 注入 `OpenSearchVectorRetriever`（泛化使用）
   - 注入 `DeviceResolver` / `RegionResolver`
4. 若不走远端：
   - 注入 `EmptyRetriever` + `NoopResolver`
   - 继续本地规则流程

### 6.2 单次请求路由流程（与后端相关步骤）
`PrecheckEngine.route` -> middleware pipeline：
1. `ParamPrefillMiddleware`（可开关）
   - AC 状态机在本地文本内匹配词表，提前产出 `device_id/region_id/object_scope...`
2. `EntityEnricherMiddleware`
   - 调用设备/地域 resolver，resolver 内部走 `text_search`
3. `ScopeGateMiddleware`
   - 调用 `retriever.search_scene`，内部走 `knn + text` 融合
4. `SeedScopeGuardMiddleware`（可选）
   - 调用 `search_seed_cases`
5. `TemplateMatcherMiddleware`
   - 调用 `search_template`，内部走 `knn + text` 融合

### 6.3 索引构建流程
`scripts/build_vector_indices.py`：
1. 加载配置 + 向量模型
2. 调用 `build_search_client` 选择后端
3. 构建 scene/template/seed_case 文档
4. `ensure_vector_index` 建索引
5. `bulk_index` 写入文档

### 6.4 业务场景处理链路（输入 -> 中间 -> 输出）

#### 6.4.1 输入
- 输入对象：`RouteRequest`
- 关键字段：
  - `input_text`：用户自然语言文本（主输入）
  - `context.scene`：上游已确认场景（可选，命中时会覆盖场景识别）
  - `context.slots`：上游已抽取槽位（可选）
  - `role`：权限判断输入

#### 6.4.2 中间处理（按实际执行顺序）

| 步骤 | 中间件 | 主要动作 | 产出与分支 |
|---|---|---|---|
| 1 | `NormalizeMiddleware` | 文本归一化（去首尾空格、统一大小写、标点归一） | 写入 `ctx.norm_text`；继续 |
| 2 | `InputGuardMiddleware` | 校验输入长度上下限 | 空输入 -> `CLARIFY`；超长 -> `REFUSE`；否则继续 |
| 3 | `EntityExtractorMiddleware` | 规则抽取实体（时间、topN、严重级别、意图等） | 写入 `ctx.entities/ctx.slots`；继续 |
| 4 | `ParamPrefillMiddleware` | 分域 AC：先路由域，再匹配，再仲裁（设备/地域/KPI/告警） | 命中后写入 `ctx.entities`，满足阈值时可自动落槽位；未命中继续 |
| 5 | `EntityEnricherMiddleware` | 调用 `device/region resolver` 做实体候选补全 | 正常合并候选并落槽位；resolver 异常时若已有预提参则继续，否则 `REFUSE(data_unavailable)` |
| 6 | `PolicyGuardMiddleware` | 关键词与权限策略拦截 | 命中策略/权限/域外词 -> `REFUSE`；否则继续 |
| 7 | `ScopeGateMiddleware` | 场景识别与范围判定（规则分 + 向量分 + 实体覆盖分融合） | 低于 `T_scope` -> `REFUSE(unsupported_domain)`；与次高分差小于 `T_scene_gap` -> `CLARIFY(scene)`；否则写入 `ctx.scene` 并继续 |
| 8 | `SceneRouterMiddleware` | 兜底同步场景（含 `context.scene` 覆盖） | 更新 `ctx.scene`；继续 |
| 9 | `SeedScopeGuardMiddleware` | 基于 seed case 做能力边界守卫（可开关） | 关闭则跳过；检索失败 -> `REFUSE(data_unavailable)`；低于 `min_score/min_hits` 或场景不在白名单 -> `REFUSE(out_of_seed_scope)`；否则继续 |
| 10 | `SlotClarifierMiddleware` | 补默认槽位、计算必填/条件必填槽位、选择追问槽位 | 槽位不全 -> `CLARIFY(missing_slots)`；槽位齐全继续 |
| 11 | `TemplateMatcherMiddleware` | 模板匹配（规则分 + 向量分 + 槽位适配分融合） | 分低于 `T_template` -> 继续；命中但缺槽位 -> `CLARIFY`；命中且槽位齐全 -> `ROUTE_TEMPLATE` |
| 12 | `NL2SQLRouterMiddleware` | 模板未命中的最终路由 | 返回 `ROUTE_NL2SQL` |

#### 6.4.3 每一步“干了啥”的核心技术点
- `ScopeGate`：不是只靠向量召回，而是把 `rule/vector/entity` 三路分数做加权，减少单一路径误判。
- `ParamPrefill`：分域 AC 把“可确定参数”提前落到上下文，并通过域仲裁降低跨表冲突。
- `SeedScopeGuard`：在“场景已判定”后再做能力边界裁剪，防止路由到尚未开放的 NL2SQL 能力面。
- `SlotClarifier`：支持 `slots.required + slots.conditional + slots.defaults`，不是固定字段表。
- `TemplateMatcher`：支持 `negative_keywords` 将规则分直接置 0，避免反向语义误命中模板。

#### 6.4.4 输出
- 输出对象：`RouteDecision`
- 关键字段：
  - `type`：`refuse / clarify / route_template / route_nl2sql`
  - `scene`：最终场景（若已识别）
  - `template_id`：命中模板时返回
  - `slots`：当前可用槽位（含抽取、补全、默认值）
  - `missing_slots`：需用户补充的槽位列表
  - `options`：可执行建议项（拒答或澄清时）
  - `out_of_scope_reason`：拒答原因枚举
  - `trace`：全链路决策轨迹（用于诊断与评测）

#### 6.4.5 典型业务场景结果
1. 输入“查昨天华东离线设备数”
   - 常见路径：`normalize -> extract/enrich -> scope_gate(命中设备场景) -> slot_clarifier(槽位齐) -> template_matcher(命中模板)`
   - 输出：`ROUTE_TEMPLATE`（含 `scene/template_id/slots`）
2. 输入“看告警”
   - 常见路径：场景可识别，但缺关键槽位（如时间范围/范围对象）
   - 输出：`CLARIFY`（`missing_slots` + 引导选项）
3. 输入“帮我写营销文案”
   - 常见路径：`policy_guard` 或 `scope_gate` 判定域外
   - 输出：`REFUSE`（`out_of_scope_reason=unknown_domain/unsupported_domain`）

## 7. ES 与 OS 的实现差异

### 7.1 索引映射
- OpenSearch：
  - 向量字段类型：`knn_vector`
  - 索引设置：`index.knn = true`
- Elasticsearch：
  - 向量字段类型：`dense_vector`
  - 启用索引：`index: true`, `similarity: cosine`

### 7.2 向量查询
- OpenSearch：`knn` 查询
- Elasticsearch：
  - 优先 `knn` 查询
  - 异常时回退 `script_score`（`cosineSimilarity + 1.0`）

### 7.3 运行风险差异
- ES 版本兼容性对 `knn` 支持影响较大，回退路径性能更敏感
- OS 的 `knn_vector` 能力依赖插件/配置一致性

## 8. 配置与使用说明

### 8.1 配置文件
`configs/vector.json`：
```json
{
  "search_backend": "opensearch",
  "param_prefill": {
    "enabled": false,
    "dictionary_file": "ac_terms.json",
    "auto_commit": true,
    "commit_score": 0.95,
    "min_gap": 0.05,
    "max_candidates_per_slot": 3,
    "domain_penalty": 0.2,
    "domain_priority": { "device": 1.0, "region": 0.9, "kpi": 0.8, "alarm": 0.7 },
    "slot_domain_priority": { "device_id": ["device"], "region_id": ["region"] },
    "domain_router": {
      "enabled": true,
      "max_domains": 2,
      "scene_domains": { "device.query": ["device", "region"] },
      "keyword_domains": { "kpi": ["cpu", "内存", "时延"] }
    },
    "skip_remote_resolver_when_prefilled": true
  }
}
```

`configs/capabilities.json`：
- 单一业务配置源：`capability -> scope/slots/intents/recommendations/slot_policy`
- 运行期由 loader 编译为 `scenes/templates/cases/seed_cases/slot_policies`

`configs/ac_terms.json`（可由服务数据库导出）：
- 词条字段：`term/domain/aliases/slot/value/entity_id/entity_name/score/metadata`
- 典型槽位：`region_id`、`device_id`、`object_scope`、`severity`、`alarm_status`

### 8.2 环境变量
```bash
CHAT_PRE_CHECK_SEARCH_BACKEND=elasticsearch
CHAT_PRE_CHECK_OS_URL=http://localhost:9200
```

### 8.3 命令行
- API 启动（使用环境变量）
```bash
uvicorn chat_pre_check.interfaces.api.app:create_app --factory --reload
```
- CLI
```bash
python -m chat_pre_check.interfaces.cli.main "近24小时告警" --os-url http://localhost:9200 --search-backend elasticsearch
```
- livemain
```bash
python livemain.py --os-url http://localhost:9200 --search-backend elasticsearch
```
- 构建索引
```bash
python scripts/build_vector_indices.py --search-url http://localhost:9200 --search-backend elasticsearch --config-dir configs
```
- 导出 AC 词表（设备/地域）
```bash
python scripts/export_ac_terms.py --search-url http://localhost:9200 --search-backend elasticsearch --config-dir configs --output configs/ac_terms.json --merge-existing
```

## 9. 错误处理与降级策略

### 9.1 客户端层
- ES/OS 客户端统一带重试（`max_retries`, `retry_backoff_sec`）
- ES 缺依赖时在初始化明确报错（提示安装 `elasticsearch` 包）

### 9.2 流水线层
- `scene_retrieval_failed` / `template_retrieval_failed` -> `refuse(data_unavailable)`
- `resolver_unavailable`：
  - 无预提参与无已落槽位 -> `refuse(data_unavailable)`
  - 有 AC 预提参候选或已落槽位 -> 继续后续流程（避免过度拒答）
- 无远端地址时自动走 `EmptyRetriever + NoopResolver`，不中断服务

### 9.3 运维层（livemain）
- 先 `ping`
- 再检查关键索引是否存在（`scene/template/device/region`）
- 不可用时可退到 `local_fallback`

## 10. 当前测试覆盖
- 单测：
  - `tests/unit/test_search_client_factory.py`（开关解析与依赖保护）
  - 全量 `tests/unit` 通过
- 验收/基准：
  - `tests/acceptance/*` 通过
  - `tests/benchmark/*` 通过
- 集成：
  - 当前已有 OpenSearch 集成测试
  - Elasticsearch 集成测试仍建议补充

## 11. 后续重构建议

### 11.1 优先级 P0（建议近期做）
- 增加 `SearchClient` Protocol，替代当前 `Any` 类型
- 将 `OpenSearchVectorRetriever` 重命名为更中性的 `HybridVectorRetriever`
- 新增 Elasticsearch 集成测试（与 OpenSearch 集成测试对齐）

### 11.2 优先级 P1（建议中期做）
- 统一命名：逐步将 `os_url` 迁移为 `search_url`（保留兼容别名）
- 客户端参数标准化：证书、超时、连接池参数统一抽象
- 索引 mapping 版本化（ES/OS 各自 schema 版本）

### 11.3 优先级 P2（长期优化）
- 支持后端自动探测（仅在显式允许时）
- 支持多后端并行读灰度（compare mode）
- 将索引构建流程纳入 CI/CD 发布工序

## 12. 新同学学习路径
1. 先看 `bootstrap.py`，理解依赖装配和后端注入点
2. 再看 `search_client_factory.py`，掌握开关解析优先级
3. 阅读 ES/OS 客户端实现，明确差异（mapping + knn）
4. 阅读 `opensearch_vector_retriever.py`，理解融合检索
5. 最后看 `scope_gate/template_matcher`，理解检索结果如何影响路由决策

---

如需做“从 ES 到 OS 的发布迁移”，建议配合 `docs/PRODUCTION_GUIDE.md` 的 `2.2` 小节一并使用。
