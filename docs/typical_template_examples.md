# Typical Template Examples

面向之后扩展 [templates.json](D:/GitHub/chat_pre_check_blank/configs/templates.json) 的人。

这份文档不讲完整规范，而是沉淀“可以直接参考的典型场景骨架”。

建议把文档分成两层来看：

- 这份示例库：回答“类似场景通常怎么起步”
- [template_authoring_guide.md](D:/GitHub/chat_pre_check_blank/docs/template_authoring_guide.md)：回答“为什么要这么拆模板”
- [slot_extractors_authoring_guide.md](D:/GitHub/chat_pre_check_blank/docs/slot_extractors_authoring_guide.md)：回答“槽位到底怎么抽”

## 怎么使用这份示例库

这些示例的定位是：

- 给模板作者一个可复制的起点
- 帮团队沉淀典型问数场景的拆模方式
- 作为评测样本和回归样本的来源

这些示例不是：

- 一份要求原样上线的最终配置
- 一份代替业务字段字典的全量模板库

使用建议：

1. 先找最接近的场景骨架
2. 按你们自己的实体、指标、业务编码替换字段
3. 再回到指导文档补齐设计理由和边界判断

## 示例 0：前置行业黑话改写

适合场景：

- 业务里有大量跨模板复用的简称、黑话、内部代号
- 你希望在进入召回前就先统一说法

典型例子：

- `北二小 -> 北京第二小学`
- `思科设备 -> cisic`
- `错包 -> 错误包`

推荐思路：

- 放到顶层 `query_rewrite`
- 不要塞进某一个模板的 `slot_extractors`
- 先做全局统一，再让模板按统一后的表达工作

骨架：

```jsonc
{
  "query_rewrite": {
    "enabled": true,
    "max_passes": 2,
    "dictionary_path": "configs/query_rewrite_rules.json",
    "reload_on_change": true,
    "rules": [
      {
        "rule_id": "alias.school.short_name",
        "source": "北二小",
        "target": "北京第二小学"
      },
      {
        "rule_id": "alias.vendor.cisco",
        "source": "思科设备",
        "target": "cisic"
      },
      {
        "rule_id": "alias.cpu_typo",
        "source": "cup",
        "target": "cpu",
        "match_mode": "whole_word"
      }
    ]
  }
}
```

建议：

- `source` 和 `target` 都写成稳定短语，不要写成过宽的单字
- 让 `query_rewrite` 负责全局说法统一，让模板继续只关心模板语义
- 需要独立维护时，把规则下沉到 `dictionary_path` 指向的词典文件
- 英文缩写类规则如果容易误伤，优先加 `match_mode = whole_word`

## 示例 1：数量类模板

适合问法：

- `昨天北京掉线设备数`
- `近24小时华东离线主机数量`

推荐思路：

- 一个模板只表达“数量”
- `query_operator` 固定为 `count`
- `time_range / region_id` 是否必填，按下游执行要求决定

骨架：

```jsonc
{
  "template_id": "device.offline.count",
  "query_mode": "metric_query",
  "description": "查询离线设备数量",
  "required_slots": ["time_range", "region_id", "query_operator"],
  "optional_slots": [],
  "must_terms": [
    ["设备", "主机"],
    ["离线", "掉线"],
    ["多少", "数量", "数", "总数"]
  ],
  "slot_constraints": {
    "entity_type": ["device"],
    "metric": ["offline_count"],
    "query_operator": ["count"]
  }
}
```

## 示例 2：排行类模板

适合问法：

- `近24小时接口错误包告警前十`
- `昨天华东丢包率最高的前5个网络`

推荐思路：

- 一个模板只表达“排行”
- `topn` 一般应是必填
- `llm_slot_extraction` 可以只对白名单槽位 `topn` 做窄补参

骨架：

```jsonc
{
  "template_id": "alarm.interface.error.topn",
  "query_mode": "metric_query",
  "description": "查询接口错误包告警排行",
  "required_slots": ["time_range", "topn"],
  "optional_slots": ["region_id"],
  "must_terms": [
    ["接口"],
    ["错误包", "错包"],
    ["top", "前", "排名", "排行"]
  ],
  "slot_constraints": {
    "entity_type": ["interface"],
    "metric": ["error_packet"],
    "query_operator": ["topn"]
  }
}
```

## 示例 3：多条件列表模板

适合问法：

- `查询最近cpu大于80且内存大于70的设备列表`
- `近24小时cpu高于90且内存高于80的主机清单`

推荐思路：

- 多一个过滤条件，就单独拆模板
- 多出来的阈值写进 `required_slots`
- 不要把双条件 query 硬塞到单条件模板里

骨架：

```jsonc
{
  "template_id": "device.cpu.memory.over.list",
  "query_mode": "metric_query",
  "description": "查询CPU和内存同时超过阈值的设备列表",
  "required_slots": ["query_operator", "cpu_threshold", "memory_threshold"],
  "optional_slots": ["time_range", "region_id"],
  "must_terms": [
    ["设备", "主机"],
    ["cpu", "cup"],
    ["内存", "memory"],
    ["列表", "清单", "列出", "哪些设备"]
  ],
  "slot_constraints": {
    "entity_type": ["device"],
    "query_operator": ["list"]
  }
}
```

## 示例 4：按设备定位方式查询单台网络设备资源指标

适合问法：

- `查询近24小时ip为10.1.1.1的交换机cpu利用率最大值`
- `昨天mac为aa:bb:cc:dd:ee:ff的路由器内存利用率平均值`
- `最近7天名称为core-sw-01的网络设备cpu趋势`

这个场景容易一上来拆成很多模板：

- `ip/mac/名称`
- `cpu/内存`
- `最大/最小/平均/趋势`
- `交换机/路由器/防火墙`

但第一版不建议这样做，因为组合会很快爆炸。

### 推荐拆法

第一版先拆 2 个模板：

- `network.device.resource.aggregate.by_selector`
  负责 `最大 / 最小 / 平均`
- `network.device.resource.trend.by_selector`
  负责 `趋势`

不建议第一版拆：

- `ip` 一个模板、`mac` 一个模板、`名称` 一个模板
- `cpu` 一个模板、`内存` 一个模板

因为这些更像槽位差异，不是查询形态差异。

### 推荐槽位设计

推荐槽位：

- `time_range`
- `selector_type`
  - `ip`
  - `mac`
  - `name`
- `selector_value`
- `entity_type`
  - `switch`
  - `router`
  - `firewall`
  - `network_device`
- `metric`
  - `cpu_usage`
  - `memory_usage`
- `aggregation`
  - `max`
  - `min`
  - `avg`

关键点：

- 不要把 `selector_ip / selector_mac / selector_name` 都写成必填
- 当前引擎不支持“3 选 1”式 `required_slots`
- 应统一为 `selector_type + selector_value`

### 聚合模板骨架

```jsonc
{
  "template_id": "network.device.resource.aggregate.by_selector",
  "query_mode": "metric_query",
  "description": "查询指定网络设备CPU或内存利用率的最大值最小值平均值",
  "utterances": [
    "查询近24小时ip为10.1.1.1的交换机cpu利用率最大值",
    "昨天mac为aa:bb:cc:dd:ee:ff的路由器内存利用率平均值",
    "最近7天名称为core-sw-01的网络设备cpu最小值"
  ],
  "required_slots": ["time_range", "selector_type", "selector_value", "metric", "aggregation"],
  "optional_slots": ["entity_type"],
  "must_terms": [
    ["ip", "ip地址", "mac", "mac地址", "名称", "设备名", "主机名"],
    ["cpu", "内存", "memory"],
    ["最大", "最大值", "最小", "最小值", "平均", "平均值"]
  ],
  "negative_terms": ["列表", "清单", "排行", "排名", "top", "趋势", "走势"],
  "slot_constraints": {
    "metric": ["cpu_usage", "memory_usage"],
    "aggregation": ["max", "min", "avg"]
  },
  "slot_extractors": {
    "selector_type": {
      "extractors": [
        {
          "type": "keyword_value",
          "cases": [
            {"terms": ["ip", "ip地址"], "value": "ip"},
            {"terms": ["mac", "mac地址"], "value": "mac"},
            {"terms": ["名称", "设备名", "主机名"], "value": "name"}
          ]
        }
      ]
    },
    "selector_value": {
      "extractors": [
        {
          "type": "regex",
          "patterns": [
            {
              "pattern": "(?:ip|ip地址)\\s*为\\s*([0-9]{1,3}(?:\\.[0-9]{1,3}){3})",
              "group": 1,
              "value_type": "string"
            },
            {
              "pattern": "(?:mac|mac地址)\\s*为\\s*([0-9a-f]{2}(?:[:\\-\\s][0-9a-f]{2}){5})",
              "group": 1,
              "value_type": "string"
            },
            {
              "pattern": "(?:名称|设备名|主机名)\\s*为\\s*([a-z0-9_.-]+)",
              "group": 1,
              "value_type": "string"
            }
          ]
        }
      ]
    },
    "metric": {
      "extractors": [
        {
          "type": "keyword_value",
          "cases": [
            {"terms": ["cpu", "cpu利用率", "cpu使用率"], "value": "cpu_usage"},
            {"terms": ["内存", "内存利用率", "内存使用率", "memory"], "value": "memory_usage"}
          ]
        }
      ]
    },
    "aggregation": {
      "extractors": [
        {
          "type": "keyword_value",
          "cases": [
            {"terms": ["最大", "最大值"], "value": "max"},
            {"terms": ["最小", "最小值"], "value": "min"},
            {"terms": ["平均", "平均值"], "value": "avg"}
          ]
        }
      ]
    }
  }
}
```

### 趋势模板骨架

```jsonc
{
  "template_id": "network.device.resource.trend.by_selector",
  "query_mode": "metric_query",
  "description": "查询指定网络设备CPU或内存利用率趋势",
  "required_slots": ["time_range", "selector_type", "selector_value", "metric"],
  "optional_slots": ["entity_type"],
  "must_terms": [
    ["ip", "ip地址", "mac", "mac地址", "名称", "设备名", "主机名"],
    ["cpu", "内存", "memory"],
    ["趋势", "趋势图"]
  ],
  "negative_terms": ["列表", "清单", "排行", "排名", "top", "最大", "最小", "平均"]
}
```

### 这个场景的设计理由

这样拆的原因是：

1. `趋势` 和 `最大/最小/平均` 的下游返回形态不同，应该拆模板
2. `ip/mac/名称` 只是设备定位方式，不应该拆成 3 条查询形态模板
3. `cpu/内存` 第一版更适合做成 `metric` 槽位，而不是一开始拆模板
4. `entity_type` 只有在下游查询逻辑真的不同的时候，才值得从可选槽位升级成强约束

### 这个场景的注意事项

- 如果全局 `blocked_terms` 里有 `趋势` 或 `走势`，趋势模板会在进入召回前就被拦掉
- `selector_value` 属于自由值，优先用“带前缀锚点”的 regex 抽，不要靠 `keyword_value`
- `MAC` 地址在标准化后可能从 `aa:bb:cc:dd:ee:ff` 变成带空格的形式，regex 要接受 `:`、`-`、空格三种分隔写法
- 如果设备名称允许中文或更自由的字符集，当前 regex 需要按业务规则单独放宽

## 建议长期维护的示例层

建议后面继续按业务沉淀这些“典型场景组”：

- 数量类
- 排行类
- 单条件列表类
- 多条件列表类
- 单设备定位查询类
- 聚合值查询类
- 趋势查询类

这样做的价值是：

- 新需求先对照已有骨架，不会每次都从零开始
- 评测样本和文档示例可以共用同一套场景语言
- 团队讨论复杂模板时，更容易对齐“这是新模板，还是已有模式的一个变体”
