# capabilities.json 字段与设计指南（业务开发版）

本文是业务同学和应用开发同学维护 `configs/capabilities.json` 的主文档。  
目标是回答三个问题：

1. 每个字段是什么、做什么、怎么填。  
2. 为什么这么设计，运行时会怎么被消费。  
3. 如何用同一套配置支撑模板路由、追问、拒答边界与 NL2SQL 兜底。

## 1. 设计原则

1. 单一事实源：业务配置统一放在 `capabilities.json`。  
2. 配置与运行解耦：配置层使用 `capability.intents`，运行层自动编译为 `scenes/templates/seed_cases` 视图。  
3. 强约束优先：能模板化的能力尽量模板化，不能模板化再走 NL2SQL。  
4. 可治理：每个 intent 都有唯一 `case_id`，支持批量导入、评测、回放和追责。

## 2. 顶层结构

```json
{
  "version": "v1",
  "slot_policy_defaults": {},
  "capabilities": []
}
```

## 3. 顶层字段说明

### 3.1 `version`

- 类型：`string`
- 是否必填：是
- 作用：配置版本标识，用于后续演进和兼容治理。
- 建议：当前固定 `v1`。

### 3.2 `slot_policy_defaults`

全局槽位追问策略默认值，给所有 capability 兜底。

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `max_ask_per_turn` | `int` | 否 | 单轮最多追问多少个槽位。 |
| `slots` | `object` | 否 | 槽位级默认策略字典。 |
| `slots.*` | `object` | 否 | 通配符，所有槽位默认值。 |
| `slots.<slot>.priority` | `float` | 否 | 追问优先级，越大越优先问。 |
| `slots.<slot>.ask_cost` | `float` | 否 | 追问成本，越大越倾向不问。 |
| `slots.<slot>.defaultable` | `bool` | 否 | 是否允许自动补默认值。 |
| `slots.<slot>.infer_from` | `list[str]` | 否 | 可从哪些上下文字段推断该槽位。 |

## 4. `capabilities[]` 字段说明

`capabilities` 是业务能力清单，每个元素代表一个场景能力。

### 4.1 capability 基础字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `capability_id` | `string` | 是 | 能力唯一 ID，运行期映射为 `scene_id`。建议 `domain.intent`。 |
| `description` | `string` | 是 | 场景描述，用于维护和检索语义增强。 |
| `enabled` | `bool` | 否 | 场景总开关。默认 `true`。 |
| `scope` | `object` | 是 | 场景范围定义（关键词/示例）。 |
| `slots` | `object` | 是 | 场景级槽位约束。 |
| `slot_policy` | `object` | 否 | 覆盖全局默认的场景级追问策略。 |
| `recommendations` | `list` | 否 | 拒答/澄清时推荐项。 |
| `intents` | `list` | 否 | 统一意图定义（seed + 可选 template）。 |

### 4.2 `scope`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `scope.keywords` | `list[str]` | 否 | 场景关键词，ScopeGate 规则分输入。 |
| `scope.examples` | `list[str]` | 否 | 场景问法样例，向量和规则共同使用。 |

设计建议：

1. `keywords` 放高区分词，不放过于通用词（如“查询”）。  
2. `examples` 同时覆盖短句、口语、带过滤条件三类问法。

### 4.3 `slots`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `slots.required` | `list[str]` | 否 | 场景基础必填槽位。 |
| `slots.conditional` | `list[object]` | 否 | 条件必填规则。 |
| `slots.defaults` | `object` | 否 | 默认槽位值。 |
| `slots.clarify_policy` | `object` | 否 | 澄清策略，如主追问槽位顺序。 |

`slots.conditional` 子字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `if_slot` | `string` | 是 | 被判断的槽位名。 |
| `equals` | `string` | 是 | 触发值。 |
| `required_slots` | `list[str]` | 是 | 触发后必须补齐的槽位。 |

常见默认值模式：

```json
{
  "time_range": {
    "mode": "relative",
    "preset": "last_24h"
  }
}
```

### 4.4 `slot_policy`

`slot_policy` 用来覆盖 `slot_policy_defaults`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `max_ask_per_turn` | `int` | 否 | 当前 capability 的单轮追问上限。 |
| `slots.<slot>.priority` | `float` | 否 | 槽位优先级覆盖。 |
| `slots.<slot>.ask_cost` | `float` | 否 | 追问成本覆盖。 |
| `slots.<slot>.defaultable` | `bool` | 否 | 是否可默认覆盖。 |
| `slots.<slot>.infer_from` | `list[str]` | 否 | 推断来源覆盖。 |
| `slots.<slot>.applies_when` | `object` | 否 | 条件生效，避免全局误触发。 |

### 4.5 `recommendations`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `label` | `string` | 是 | 给用户展示的推荐文案。 |
| `intent` | `string` | 是 | 推荐目标能力 ID。 |
| `preset_slots` | `object` | 否 | 预置槽位，减少用户输入。 |
| `need_followup_slots` | `list[str]` | 否 | 点推荐后仍需继续追问的槽位。 |

`preset_slots` 常见子字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `time_range.mode` | `string` | 时间模式，常用 `relative`。 |
| `time_range.preset` | `string` | 时间预置值，如 `last_24h`、`last_7d`、`yesterday`。 |
| `object_scope` | `string` | 查询对象范围。 |
| `region_id` | `string` | 地域 ID。 |
| `severity` | `string` | 告警级别。 |
| `metric` | `string` | 指标编码。 |
| `topn` | `int` | TopN 值。 |

## 5. `intents[]` 统一定义（核心）

每个 `intent` 默认先作为 seed case（用于能力边界与相似推荐）；  
当携带 `template` 时，还会编译为模板路由项。

### 5.1 intent 基础字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `case_id` | `string` | 是 | 全局唯一，建议 `seed_<domain>_<intent>_<window>`。 |
| `label` | `string` | 建议 | 展示文案。 |
| `text` | `string` | 建议 | 标准问法，用于 seed 检索。 |
| `enabled` | `bool` | 否 | intent 开关。 |
| `route_type` | `string` | 否 | 推荐路由类型，常见 `route_template/route_nl2sql`。 |
| `tags` | `list[str]` | 否 | 治理标签（域/对象/时窗）。 |
| `priority` | `int` | 否 | 治理优先级，默认 100。 |
| `owner` | `string` | 否 | 责任人/团队。 |
| `risk_level` | `string` | 否 | `low/medium/high`。 |
| `slots` | `object` | 否 | seed 预置槽位。 |
| `keywords` | `list[str]` | 否 | 兼容字段，不建议新配置使用。 |
| `examples` | `list[str]` | 否 | 兼容字段，不建议新配置使用。 |
| `negative_keywords` | `list[str]` | 否 | 兼容字段，不建议新配置使用。 |
| `template_id` | `string` | 否 | 兼容字段，不建议新配置使用。 |
| `slot_schema` | `object` | 否 | 兼容字段，不建议新配置使用。 |

补充说明：

1. `case_id` 在同一个 capability 内必须唯一，建议全局唯一。  
2. `text/label/examples` 至少提供一种可用语料。  
3. `route_type` 不决定最终路由，只是推荐和治理语义，最终仍由流水线判定。
4. 新配置统一走 `intent.template`，兼容字段仅用于平滑迁移。

### 5.2 `intent.template` 字段

`template` 存在时，表示该 intent 同时承载可执行模板。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `template.template_id` | `string` | 是（有 template 时） | 模板唯一 ID。 |
| `template.keywords` | `list[str]` | 否 | 模板规则关键词。 |
| `template.negative_keywords` | `list[str]` | 否 | 负向词，命中时抑制模板得分。 |
| `template.slot_schema.required` | `list[str]` | 否 | 模板必填槽位。 |
| `template.slot_schema.optional` | `list[str]` | 否 | 模板可选槽位。 |
| `template.examples` | `list[str]` | 否 | 模板问法样例。 |
| `template.enabled` | `bool` | 否 | 模板开关。 |

## 6. 运行时编译规则（必须理解）

加载 `capabilities.json` 后，系统会做编译：

1. `capability` -> `scene` 视图。  
2. `intent` -> `seed_case` 视图。  
3. `intent.template` -> `template` 视图。  
4. `slot_policy_defaults + capability.slot_policy` -> 运行期 `slot_policies`。

这意味着：

1. 配置层只维护 `intents` 即可。  
2. 运行时仍保持 seed 与 template 分离语义，不会互相污染判分逻辑。  
3. 模板匹配失败时仍可走 NL2SQL 或澄清，不会被 seed 定义强行路由。

## 7. 业务建模建议

### 7.1 什么时候只配 seed intent

适用：问题形式多变、SQL 模板尚不稳定、只想先做能力边界治理。  
做法：只填 `case_id/label/text`，不挂 `template`。

### 7.2 什么时候配 intent + template

适用：问法稳定、槽位规则清晰、结果可控。  
做法：在同一个 intent 下补齐 `template` 字段和 `slot_schema`。

### 7.3 什么时候需要追问而不是拒答

1. 在支持场景内且只是缺参数：走 `clarify`。  
2. 不在能力范围或种子边界外：走 `refuse`。  
3. 能默认补齐的参数尽量在 `slots.defaults` 配置，不要增加用户负担。

## 8. 命名规范建议

1. `capability_id`：`domain.action`，如 `alarm.query`。  
2. `case_id`：`seed_<domain>_<intent>_<window>`，如 `seed_alarm_topn_core_24h`。  
3. `template_id`：`tpl_<domain>_<intent>`，如 `tpl_alarm_topn`。

## 9. 发布前检查清单

1. `python scripts/check_config.py --config-dir configs` 通过。  
2. 新增/修改 intent 后至少覆盖一个验收样例。  
3. 新增模板时，必须配置 `negative_keywords` 防误命中。  
4. 必填槽位与默认槽位无冲突。  
5. 变更后至少回归：
   - `tests/unit`
   - `tests/acceptance/test_routing_acceptance.py`
   - benchmark 回归集

## 10. 最小可用示例

```json
{
  "capability_id": "device.query",
  "description": "设备状态查询",
  "enabled": true,
  "scope": {
    "keywords": ["设备", "离线", "趋势"],
    "examples": ["昨天华东离线设备数"]
  },
  "slots": {
    "required": ["time_range"],
    "conditional": [
      {
        "if_slot": "intent",
        "equals": "trend",
        "required_slots": ["device_id"]
      }
    ],
    "defaults": {
      "time_range": {
        "mode": "relative",
        "preset": "last_24h"
      }
    },
    "clarify_policy": {
      "primary_slots": ["device_id", "time_range"]
    }
  },
  "intents": [
    {
      "case_id": "seed_device_cpu_hotspot",
      "label": "近24小时设备CPU利用率Top10",
      "text": "近24小时设备CPU利用率Top10",
      "route_type": "route_template",
      "template": {
        "template_id": "tpl_device_cpu_hotspot",
        "keywords": ["cpu", "top", "设备"],
        "negative_keywords": ["相关性", "关联率"],
        "slot_schema": {
          "required": ["time_range", "topn", "metric"],
          "optional": ["region_id"]
        },
        "examples": ["近24小时设备CPU利用率Top10"]
      }
    }
  ]
}
```
