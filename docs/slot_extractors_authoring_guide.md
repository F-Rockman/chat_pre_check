# Slot Extractors Authoring Guide

面向之后维护模板 `slot_extractors` 的人。

这份文档只讲一件事：怎么把参数抽取写得稳、可维护、可扩展。

如果上一份文档 [template_authoring_guide.md](D:/GitHub/chat_pre_check_blank/docs/template_authoring_guide.md) 解决的是“模板边界怎么设计”，这份文档解决的就是“模板里参数怎么抽”。

如果你想先找一个完整场景骨架，再回来细化 extractor，可以先看：

- [typical_template_examples.md](D:/GitHub/chat_pre_check_blank/docs/typical_template_examples.md)

## 先看结论

参数抽取不要追求“大而全”，而要追求“按模板最小可用”。

优先级建议一直是：

1. 能用 `keyword_value` 的，先用 `keyword_value`
2. 明确值型参数，用 `regex`
3. regex 已经很复杂还不稳，再考虑模板级 LLM 补参
4. 不要一上来就把所有参数交给 LLM

## 当前支持的 extractor 类型

当前代码只支持 2 类 extractor：

- `keyword_value`
- `regex`

对应实现位置：

- [extractors.py](D:/GitHub/chat_pre_check_blank/src/template_capability/extractors.py)

当前没有内置：

- 分词词典 extractor
- 枚举 + fuzzy match extractor
- 时间解析器
- 数字中文转阿拉伯数字解析器

所以你写配置时要基于这两个现实约束：

1. 要么用关键词映射固定值
2. 要么用 regex 抓取文本里的参数

## 什么时候适合规则抽取，什么时候适合 LLM 补参

这个判断非常重要。

### 适合规则抽取

这几类参数强烈建议优先规则抽：

- 时间枚举
  - `今天`
  - `昨天`
  - `近24小时`
  - `最近7天`
- 地域枚举
  - `华东`
  - `北京`
  - `上海`
- 操作类型
  - `count`
  - `topn`
  - `list`
- 实体类型
  - `device`
  - `interface`
  - `region`
- 严重级别
  - `critical`
  - `major`
- 简单数值参数
  - `top10`
  - `大于80`
  - `超过90%`

原因：

- 值域有限
- 格式相对稳定
- 可解释
- 可评测
- 成本极低

### 适合模板级 LLM 补参

这几类情况，规则往往会开始变脆，这时可以考虑模板级 LLM：

- 中文数字表达
  - `前十`
  - `前五`
  - `八十八`
  - `六十六`
- 规则已经命中模板，但值型参数没抽出来
  - 模板很稳定
  - 缺 1 到 2 个参数
- 个别模板特有的口语化参数表达
  - 不值得为一个边角 case 把全局 regex 写得很重

推荐原则：

- LLM 只补参数，不选模板
- LLM 只补白名单槽位
- LLM 只在 top1 模板已经稳定时触发

### 不适合交给 LLM 的情况

这些情况不要指望 LLM 来救：

- 模板本身边界没设计好
- `must_terms` 太弱
- `slot_constraints` 太少
- 两个模板本来就分不清
- 想让 LLM 自己决定这个 query 到底是哪类业务

这不是提参问题，是模板设计问题。

## `keyword_value` 专项指南

### 适合场景

`keyword_value` 最适合有限枚举值。

比如：

- 时间范围
- 区域
- 严重级别
- 查询操作
- 实体类型
- 指标名

### 结构

```jsonc
"query_operator": {
  "extractors": [
    {
      "type": "keyword_value",
      "cases": [
        {"terms": ["top", "前", "排名", "排行"], "value": "topn"},
        {"terms": ["列表", "清单", "列出", "哪些设备"], "value": "list"},
        {"terms": ["多少", "有多少", "数量", "数"], "value": "count"}
      ]
    }
  ]
}
```

### 字段解释

- `type`
  目前固定写 `keyword_value`
- `cases`
  一组映射规则
- `terms`
  命中任意一个 term，就返回对应的 `value`
- `value`
  返回给槽位的最终值

### 推荐写法

#### 1. `terms` 里放真实用户说法，不只放规范词

好的例子：

```jsonc
{"terms": ["列表", "清单", "列出", "哪些设备", "设备有哪些"], "value": "list"}
```

坏的例子：

```jsonc
{"terms": ["list"], "value": "list"}
```

为什么：

- 用户通常不会真的输入 `list`
- 规则要覆盖自然表达

#### 2. 一条 case 只映射一个值

好的例子：

```jsonc
{"terms": ["昨天", "昨日"], "value": {"mode": "relative", "preset": "yesterday"}}
```

坏的例子：

```jsonc
{"terms": ["昨天", "近24小时"], "value": {"mode": "relative", "preset": "yesterday"}}
```

为什么：

- 一个 case 里混不同语义，会让结果不可解释

#### 3. 同义词放一组，不同语义拆多组

好的例子：

```jsonc
[
  {"terms": ["今天", "今日"], "value": {"mode": "relative", "preset": "today"}},
  {"terms": ["昨天", "昨日"], "value": {"mode": "relative", "preset": "yesterday"}}
]
```

### `keyword_value` 最常见踩坑

#### 坑 1：term 太短，误命中过多

错误示例：

```jsonc
{"terms": ["数"], "value": "count"}
```

问题：

- `数` 太短，很多别的词里也会包含它

建议：

- 短词尽量跟更长词一起使用
- 或由别的 `must_terms`/`slot_constraints` 辅助约束

#### 坑 2：不同值的 terms 相互重叠

错误示例：

```jsonc
[
  {"terms": ["严重"], "value": "critical"},
  {"terms": ["次严重"], "value": "major"}
]
```

问题：

- `次严重` 也包含 `严重`
- 如果顺序不当，可能永远命中第一条

建议：

- 更具体的词写前面
- 或避免有包含关系的 term

#### 坑 3：想用 `keyword_value` 做自由文本解析

例如：

- 设备名
- 任意城市名
- 任意指标别名

这会迅速失控。枚举不完整时，宁可不要假装它是规则可控的。

### 典型场景：设备定位方式不要拆成多个并行必填槽位

比如这个场景：

- `查询近24小时ip为10.1.1.1的交换机cpu利用率最大值`
- `昨天mac为aa:bb:cc:dd:ee:ff的路由器内存平均值`
- `最近7天名称为core-sw-01的网络设备cpu趋势`

这类 query 很容易让人把槽位设计成：

- `selector_ip`
- `selector_mac`
- `selector_name`

但当前工程不支持“3 选 1 必填”这种结构，所以不推荐这样做。

更稳的设计是：

- `selector_type`
  用 `keyword_value` 抽 `ip / mac / name`
- `selector_value`
  用 `regex` 按前缀锚点抽真实值

这样做的好处是：

- 模板层更简单
- `required_slots` 更容易表达
- 后续扩一个新的定位方式时，只要增加 `selector_type` 的值和一条新 regex

## `regex` 专项指南

### 适合场景

`regex` 适合从文本里抓值。

最常见的是：

- `topn`
- 百分比阈值
- 数量阈值
- 简单格式化标识

### 结构

```jsonc
"topn": {
  "extractors": [
    {
      "type": "regex",
      "patterns": [
        {
          "pattern": "(?:top\\s*|前)\\s*(\\d+)",
          "group": 1,
          "value_type": "int",
          "min": 1,
          "max": 1000
        }
      ]
    }
  ]
}
```

### 字段解释

- `pattern`
  regex 本体
- `group`
  取哪个捕获组作为结果
- `value_type`
  目前支持 `string / int / float`
- `min / max`
  对数值型结果做边界过滤
- `value`
  如果你不想取捕获组，而是命中就返回固定值，可以直接写死

### 推荐写法

#### 1. 尽量一条 regex 只做一件事

好的例子：

```jsonc
{
  "pattern": "(?:top\\s*|前)\\s*(\\d+)",
  "group": 1,
  "value_type": "int",
  "min": 1,
  "max": 1000
}
```

坏的例子：

```jsonc
{
  "pattern": "(?:top\\s*|前|排名|排行|大于|高于|超过)(\\d+)",
  "group": 1,
  "value_type": "int"
}
```

为什么：

- 一条 regex 同时承担多个语义，后面根本调不动

#### 2. 同一个槽位允许多条 pattern，分别覆盖不同语序

推荐：

```jsonc
"cpu_threshold": {
  "extractors": [
    {
      "type": "regex",
      "patterns": [
        {
          "pattern": "(?:cpu|cup)(?:利用率|使用率)?\\s*(?:大于|大余|高于|超过|>|>=|不低于)\\s*(\\d+(?:\\.\\d+)?)\\s*%?",
          "group": 1,
          "value_type": "float",
          "min": 0,
          "max": 100
        },
        {
          "pattern": "(?:大于|大余|高于|超过|>|>=|不低于)\\s*(\\d+(?:\\.\\d+)?)\\s*%?\\s*的?\\s*(?:cpu|cup)(?:利用率|使用率)?",
          "group": 1,
          "value_type": "float",
          "min": 0,
          "max": 100
        }
      ]
    }
  ]
}
```

这比写一个巨长巨乱的万能 regex 更稳。

#### 3. 数值参数尽量带边界

好的例子：

```jsonc
{
  "pattern": "(\\d+(?:\\.\\d+)?)",
  "group": 1,
  "value_type": "float",
  "min": 0,
  "max": 100
}
```

为什么：

- 这能挡掉明显错误的提取
- 比如把设备编号误抓成阈值

#### 4. 允许有限 typo，但不要无限扩

例如：

- `cpu` / `cup`
- `大于` / `大余`

可以接受。

但不要：

- 为每个可能 typo 都继续堆规则

如果开始堆很多，就应该考虑模板级 LLM 补参了。

### `regex` 最常见踩坑

#### 坑 1：写得过宽，误抓无关数字

错误示例：

```jsonc
{
  "pattern": "(\\d+)",
  "group": 1,
  "value_type": "int"
}
```

问题：

- 任何数字都会被抓
- 时间、设备编号、区域编号都会混进来

#### 坑 2：只覆盖一种语序

例如只支持：

- `cpu 大于 80`

却不支持：

- `大于 80 的 cpu`

结果：

- 线上 query 一变形就漏抽

#### 坑 3：把中文数字也硬塞给 regex

例如：

- `前十`
- `八十八`

如果你没有完整中文数字解析器，直接上 regex 往往很脆。

这类 case 更适合模板级 LLM 补参。

## 什么时候该用 `keyword_value`

推荐：

- 值域有限
- 能列清楚
- 用户表达主要是枚举词

例如：

- `today / yesterday / last_24h`
- `device / interface / region`
- `count / list / topn`

不推荐：

- 任意数字
- 任意名称
- 任意自然语言短语

## 什么时候该用 `regex`

推荐：

- 值在文本里显式出现
- 形态较稳定
- 用几个 pattern 就能覆盖主要场景

例如：

- `top10`
- `前10`
- `cpu 大于 80`
- `内存高于 70`

不推荐：

- 中文口语数字表达占比很高
- 值和自然语言混得非常自由
- 需要真正的语言理解，不只是模式匹配

## 什么时候该交给模板级 LLM 补参

推荐触发条件：

1. 模板已经稳定命中 top1
2. 缺少的槽位不超过 `1-2`
3. 缺的是值型参数
4. 规则写下去会越来越难维护

最典型的可交给 LLM 的槽位：

- `topn`
  - `前十`
  - `前五`
- 百分比阈值
  - `八十`
  - `七十五`
  - `六十六`

不建议交给 LLM 的槽位：

- `metric`
- `entity_type`
- `query_operator`

这些更适合用规则和模板约束钉死。

## 推荐的槽位设计方式

### 时间槽位

推荐用 `keyword_value`

示例：

```jsonc
"time_range": {
  "extractors": [
    {
      "type": "keyword_value",
      "cases": [
        {
          "terms": ["近24小时", "过去24小时", "24小时内", "最近24小时"],
          "value": {"mode": "relative", "preset": "last_24h"}
        },
        {
          "terms": ["近7天", "过去7天", "7天内", "最近7天"],
          "value": {"mode": "relative", "preset": "last_7d"}
        },
        {
          "terms": ["今天", "今日"],
          "value": {"mode": "relative", "preset": "today"}
        },
        {
          "terms": ["昨天", "昨日"],
          "value": {"mode": "relative", "preset": "yesterday"}
        }
      ]
    }
  ]
}
```

建议：

- 只做枚举，不做复杂自然语言日期解析
- 真要支持更自由日期，再单独扩能力

### 区域槽位

推荐用 `keyword_value`

示例：

```jsonc
"region_id": {
  "extractors": [
    {
      "type": "keyword_value",
      "cases": [
        {"terms": ["华东"], "value": "east_cn"},
        {"terms": ["北京"], "value": "region_bj"},
        {"terms": ["上海"], "value": "region_sh"}
      ]
    }
  ]
}
```

建议：

- 只放当前模板真的允许的区域
- 模板不需要的区域不要硬放

### 设备定位槽位

适合：

- `ip为10.1.1.1`
- `mac为aa:bb:cc:dd:ee:ff`
- `名称为core-sw-01`

推荐设计：

- `selector_type` 用 `keyword_value`
- `selector_value` 用 `regex`

示例：

```jsonc
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
}
```

建议：

- regex 尽量带前缀锚点，比如 `ip为`、`mac为`、`名称为`
- 不要写成抓任意字符串，否则很容易把无关片段误抽成设备标识
- `MAC` 地址要同时接受 `:`、`-`、空格三种分隔形式
- 如果设备名允许中文或更复杂字符集，要按业务规则再单独放宽

### 操作槽位

推荐用 `keyword_value`

示例：

```jsonc
"query_operator": {
  "extractors": [
    {
      "type": "keyword_value",
      "cases": [
        {"terms": ["top", "前", "排名", "排行"], "value": "topn"},
        {"terms": ["列表", "清单", "列出", "哪些设备"], "value": "list"},
        {"terms": ["多少", "有多少", "数量", "数"], "value": "count"}
      ]
    }
  ]
}
```

建议：

- 和 `slot_constraints.query_operator` 配套使用

### 阈值槽位

推荐规则：

- 先用 regex 覆盖阿拉伯数字
- 中文数字频繁出现时，再配模板级 LLM 补参

例如 `cpu_threshold`：

```jsonc
"cpu_threshold": {
  "extractors": [
    {
      "type": "regex",
      "patterns": [
        {
          "pattern": "(?:cpu|cup)(?:利用率|使用率)?\\s*(?:大于|大余|高于|超过|>|>=|不低于)\\s*(\\d+(?:\\.\\d+)?)\\s*%?",
          "group": 1,
          "value_type": "float",
          "min": 0,
          "max": 100
        },
        {
          "pattern": "(?:大于|大余|高于|超过|>|>=|不低于)\\s*(\\d+(?:\\.\\d+)?)\\s*%?\\s*的?\\s*(?:cpu|cup)(?:利用率|使用率)?",
          "group": 1,
          "value_type": "float",
          "min": 0,
          "max": 100
        }
      ]
    }
  ]
}
```

对应 LLM 补参：

```jsonc
"llm_slot_extraction": {
  "enabled": true,
  "slots": ["cpu_threshold"],
  "instructions": "仅补充CPU阈值，不要生成时间、区域或别的参数。"
}
```

## 一个槽位该不该抽，先问自己 5 个问题

在给模板加一个 extractor 之前，先问：

1. 这个槽位是不是下游真正需要
2. 这个槽位是不是这个模板自己需要
3. 它是枚举值还是自由值
4. 它的表达是不是相对稳定
5. 为了覆盖它，规则复杂度会不会明显失控

如果第 5 条答案是“会”，优先考虑：

- 缩小模板支持范围
- 或让模板级 LLM 来补

## 推荐的配置顺序

写 extractor 时，建议按这个顺序：

1. 先写 `keyword_value`
2. 再写最核心的一条 regex
3. 再补语序变化
4. 再补有限 typo
5. 最后决定是否开 `llm_slot_extraction`

不要反过来：

- 一开始就堆很多 regex
- 最后发现根本维护不动

## 好 extractor 和坏 extractor 对比

### 好 extractor

```jsonc
"topn": {
  "extractors": [
    {
      "type": "regex",
      "patterns": [
        {
          "pattern": "(?:top\\s*|前)\\s*(\\d+)",
          "group": 1,
          "value_type": "int",
          "min": 1,
          "max": 1000
        }
      ]
    }
  ]
}
```

特点：

- 只做一件事
- 有边界
- 可解释

### 坏 extractor

```jsonc
"number": {
  "extractors": [
    {
      "type": "regex",
      "patterns": [
        {
          "pattern": "(\\d+)",
          "group": 1,
          "value_type": "int"
        }
      ]
    }
  ]
}
```

问题：

- 太泛
- 不知道它抓到的到底是什么数字

## 模板级 LLM 补参怎么配才安全

推荐：

```jsonc
"llm_slot_extraction": {
  "enabled": true,
  "slots": ["topn"],
  "instructions": "仅补充TopN参数，不要生成时间、区域、指标或别的条件。"
}
```

重点：

- `slots` 越少越好
- `instructions` 越窄越好

不要这样写：

```jsonc
"llm_slot_extraction": {
  "enabled": true,
  "slots": ["time_range", "region_id", "metric", "entity_type", "query_operator", "topn"],
  "instructions": "尽量帮我补齐所有参数"
}
```

为什么：

- 这几乎等于把整个模板解释权都交给模型
- 后面出错时很难收敛

## 上线前检查清单

每次新增或修改 extractor 前，过一下这个清单：

- 这个槽位是不是当前模板真的需要
- 这个槽位更适合 `keyword_value` 还是 `regex`
- regex 是否写了边界
- 是否覆盖了 2 到 3 个常见语序
- 是否为了少数 case 把规则复杂度拉得过高
- 是否应该把那部分 case 交给模板级 LLM 补参
- 是否补了对应测试样例
- 是否跑过 `python -m pytest -q`
- 是否跑过 `python tools/evaluate_matcher.py`

## 最后建议

参数抽取设计里，最危险的不是“写少了”，而是“写得太宽、太聪明、太想一次覆盖所有场景”。

当前这套体系里，最稳的做法一直是：

1. 模板先写窄
2. extractor 先写小
3. regex 先覆盖主流表达
4. 真的只剩少量边界 case，再用模板级 LLM 补参
