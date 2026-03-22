# Template Authoring Guide

面向之后维护 [templates.json](D:/GitHub/chat_pre_check_blank/configs/templates.json) 的人。

这份文档只解决一件事：怎样把模板写得更稳、更容易命中、也更不容易和别的模板打架。

它不是代码说明，也不是运行说明。它是模板配置规范。

如果你当前卡在“参数到底怎么抽、regex 怎么写、哪些参数该交给模板级 LLM”，直接看配套文档：

- [slot_extractors_authoring_guide.md](D:/GitHub/chat_pre_check_blank/docs/slot_extractors_authoring_guide.md)
- [typical_template_examples.md](D:/GitHub/chat_pre_check_blank/docs/typical_template_examples.md)

## 建议同时维护两层文档

推荐把模板知识分成两层维护：

- 示例层
  沉淀“这个场景通常怎么起模板骨架”，见 [typical_template_examples.md](D:/GitHub/chat_pre_check_blank/docs/typical_template_examples.md)
- 指导层
  解释“为什么这么拆、哪些槽位该必填、哪些冲突要靠约束解决”，也就是当前这份文档

这样分层的好处是：

- 新需求先能快速找到相似示例，不必从零开始写
- 设计原则和业务示例不会混成一份越来越长的配置手册
- 后续新增场景时，可以先补示例，再把共性的拆模规律回收进指导文档

## 适用范围

当前工程只支持“问数”场景，所以模板设计也只围绕以下几类 query：

- 问数量：`昨天北京掉线设备数`
- 问排行：`近24小时接口错误包告警前十`
- 问列表：`查询最近 cpu 大于 80 的设备列表`
- 问多条件列表：`查询最近 cpu 大于 80 且内存大于 70 的设备列表`

不适合放进模板体系的 query：

- `为什么最近告警很多`
- `帮我分析一下根因`
- `给我一份日报`
- `预测下周走势`

这些应该直接被 `blocked_terms` 或模板 `negative_terms` 拦掉。

## 先看结论

一个模板写得稳，通常满足这 6 条：

1. `description` 足够单一，不混多个意图。
2. `utterances` 覆盖 4 到 8 条真实变体，而不是只改几个字。
3. `must_terms` 把模板最核心的语义锚点写清楚。
4. `required_slots` 只放真正缺了就不能执行查询的参数。
5. `slot_constraints` 把容易冲突的条件钉死。
6. `slot_extractors` 只写这个模板真正需要的参数，不做“全局大而全”。

当前还支持 3 个兼容增量字段：

- `required_one_of`
  用来表达“一组槽位至少满足一个”
- `conditional_required`
  用来表达“给了 A 就必须给 B”
- `mutually_exclusive_slots`
  用来表达“这几个槽位不能同时出现”

这 3 个字段不会影响旧模板，只有你显式配置了它们才会生效。

另外，`blocked_terms / must_terms / negative_terms` 现在也支持匹配模式：

- 默认字符串写法仍然是 `substring`
- 需要边界控制时，可以改成对象写法
- 当前支持 `substring / whole_word / exact`

## 顶层结构

当前配置文件结构：

```jsonc
{
  "matcher": {
    // 全局匹配参数
  },
  "query_rewrite": {
    // 前置行业黑话 / 别名改写
  },
  "slot_extractors": {
    // 根级共享 extractor，当前只建议保留兼容用途
  },
  "templates": [
    // 业务模板列表
  ]
}
```

重点：

- `query_rewrite` 负责全局前置改写，不参与模板选型
- 现在推荐把参数抽取下沉到每个模板的 `slot_extractors`
- 根级 `slot_extractors` 不要再往“大一统参数字典”方向扩

## 最小模板骨架

下面这个骨架是推荐起点。实际新增模板时，先从这个结构复制。

```jsonc
{
  "template_id": "device.cpu.over.list",
  "query_mode": "metric_query",
  "description": "查询CPU利用率超过阈值的设备列表",
  "utterances": [
    "查询最近cpu大于80的设备列表",
    "近24小时cpu高于90的设备清单",
    "列出华东cpu超过85的设备"
  ],
  "required_slots": ["query_operator", "cpu_threshold"],
  "optional_slots": ["time_range", "region_id"],
  "must_terms": [
    ["设备", "设别", "主机"],
    ["cpu", "cup"],
    ["大于", "大余", "高于", "超过", ">", ">=", "不低于"],
    ["列表", "清单", "列出", "哪些设备", "设备有哪些", "设备名单"]
  ],
  "negative_terms": ["原因", "根因", "总结", "报告", "预测"],
  "slot_constraints": {
    "entity_type": ["device"],
    "metric": ["cpu_usage"],
    "query_operator": ["list"]
  },
  "slot_extractors": {
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
              "terms": ["最近"],
              "value": {"mode": "relative", "preset": "recent"}
            }
          ]
        }
      ]
    },
    "query_operator": {
      "extractors": [
        {
          "type": "keyword_value",
          "cases": [
            {
              "terms": ["设备列表", "列表", "清单", "列出", "哪些设备", "设备有哪些"],
              "value": "list"
            }
          ]
        }
      ]
    },
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
            }
          ]
        }
      ]
    }
  },
  "llm_slot_extraction": {
    "enabled": true,
    "slots": ["time_range", "region_id", "cpu_threshold", "query_operator"],
    "instructions": "仅补充时间、区域、CPU阈值和列表算子，不要发明别的条件。"
  },
  "metadata": {
    "metric_code": "device_cpu_over_list"
  }
}
```

## 模板字段逐项说明

下面按模板对象里的每个字段来讲。

### `template_id`

作用：

- 模板唯一标识
- 直接作为匹配结果返回给下游

推荐写法：

- 用稳定、可读、可分层的英文点分结构
- 推荐模式：`实体.指标/场景.操作`
- 例如：
  - `device.offline.count`
  - `alarm.interface.error.topn`
  - `device.cpu.memory.over.list`

不要这样写：

- `tmpl_001`
- `deviceQueryTemplate`
- `cpu超80设备列表`

为什么：

- 点分结构方便后续做统计、路由、评测覆盖
- 不要把中文、临时编号、业务上下文耦进去

### `query_mode`

作用：

- 标记模板所属的能力大类

当前建议：

- 统一写 `metric_query`

除非：

- 你后面明确在代码里扩过新的 query mode

重点：

- `query_mode` 不是 `count / topn / list`
- 在当前工程里，它主要回答“这是不是问数模板”
- 真正区分查询形态的是 `query_operator`

也就是说：

- `query_mode = metric_query`
  表示这是问数能力
- `query_operator = count / topn / list`
  表示这条模板最终是问数量、问排行还是问列表

### `description`

作用：

- 进入 BM25F 和向量召回
- 也会进 LLM 补参 prompt

推荐写法：

- 用一句短句，明确模板在查什么
- 只写一个意图，不要写成解释文

推荐示例：

- `查询离线设备数量`
- `查询区域丢包率排名`
- `查询CPU和内存同时超过阈值的设备列表`

不推荐示例：

- `这是一个查询最近设备健康情况的模板`
- `查询设备情况`
- `查询设备列表或者数量`

为什么：

- 太泛会让召回漂
- 写两个意图会让模板自己和自己冲突

### `utterances`

作用：

- 是最重要的召回语料之一
- 会进入 `sample` 相似度
- 也会影响向量召回

推荐数量：

- 每个模板至少 4 条
- 常规模板 5 到 8 条最合适

推荐覆盖方式：

- 语序变化
- 提参顺序变化
- 同义表达
- 口语化
- 常见 typo

比如这个模板：

- `查询最近cpu大于80的设备列表`
- `近24小时cpu高于90的设备清单`
- `列出华东cpu超过85的设备`
- `最近7天上海cpu利用率大于70的设备有哪些`
- `查询cup大余88的设别列表`

好的 `utterances` 特征：

- 不是同一句话机械替换一个词
- 覆盖真实输入习惯

坏的 `utterances` 特征：

- 只有 1 条
- 全是书面语
- 没有提参位置变化
- 没有列表 / 数量 / 排名等操作变化

### `required_slots`

作用：

- 决定命中后是 `matched` 还是 `partial`

原则：

- 缺了这个槽位，下游查询就无法执行，才放进 `required_slots`

例如：

- `device.offline.count`
  - `time_range` 可能是必填
  - `region_id` 可能是必填
  - `query_operator` 也建议必填
- `device.cpu.over.list`
  - `query_operator` 必填
  - `cpu_threshold` 必填
  - `time_range` 可以选填

常见错误：

- 把所有能抽的参数都塞进 `required_slots`
- 这样会导致大量本应 `matched` 的 query 变成 `partial`

### `optional_slots`

作用：

- 这些槽位会参与打分，但缺失不会阻止模板完整命中

适合放什么：

- 时间如果允许默认值
- 区域如果允许查全局
- 次要过滤条件

不适合放什么：

- 缺了就没法执行的核心条件

### `required_one_of`

作用：

- 表达“一组槽位至少给一个”

适合场景：

- `ip / mac / name` 三选一
- `device_id / device_name` 二选一

推荐：

- 只在多个定位方式本质互斥、但任意一个都能执行时使用
- 尽量配 `description`，方便 trace 和人工排查

示例：

```jsonc
"required_one_of": [
  {
    "slots": ["selector_ip", "selector_mac", "selector_name"],
    "description": "至少给一种设备定位方式"
  }
]
```

### `conditional_required`

作用：

- 表达“触发条件出现后，另一些槽位也必须出现”

适合场景：

- 给了 `selector_type`，就必须给 `selector_value`
- 给了 `query_operator = topn`，就必须给 `topn`

示例：

```jsonc
"conditional_required": [
  {
    "when_any": ["selector_type"],
    "require": ["selector_value"],
    "description": "给了定位类型就必须给具体值"
  }
]
```

### `mutually_exclusive_slots`

作用：

- 表达“一组槽位不能同时成立”

适合场景：

- 同一条 query 里不能同时给 `selector_ip` 和 `selector_name`
- 两种互斥定位方式不应该混用

示例：

```jsonc
"mutually_exclusive_slots": [
  {
    "slots": ["selector_ip", "selector_name"],
    "description": "同一次查询里不要同时给 ip 和名称"
  }
]
```

### `must_terms`

作用：

- 这是模板最重要的语义锚点之一
- 每一组至少要尽量代表一个“不可缺失的概念”

规则：

- 外层数组：多个语义组
- 内层数组：同义词集合

例子：

```jsonc
"must_terms": [
  ["设备", "主机"],
  ["离线", "掉线"],
  ["多少", "有多少", "数量", "数", "总数"]
]
```

这个设计表示：

- 设备概念必须出现
- 离线概念必须出现
- 数量概念必须出现

推荐写法：

- 每一组只放一类同义词
- 一个模板一般 3 到 6 组
- 默认继续直接写字符串
- 英文缩写、设备编码、设备名这类 token 化表达，再考虑 `whole_word`

不推荐写法：

```jsonc
"must_terms": [
  ["设备", "离线", "多少"]
]
```

为什么不好：

- 这会把完全不同的概念混成一组
- 只要命中其中一个就算通过，约束力几乎没有

如果你需要边界匹配，可以写成对象：

```jsonc
"must_terms": [
  [{"term": "idc", "match_mode": "whole_word"}],
  ["设备"],
  ["数量", "多少"]
]
```

### `negative_terms`

作用：

- 模板级否定词
- 命中后该模板直接不匹配

适合放什么：

- 明显会把 query 带到别的任务类型的词

典型值：

- `原因`
- `根因`
- `报告`
- `总结`
- `预测`

什么时候要加模板级 `negative_terms`：

- 某个模板特别容易被“分析类问法”误命中

什么时候可以只靠全局 `blocked_terms`：

- 所有模板都不应该接受的词

匹配模式建议：

- 中文短语默认继续用 `substring`
- 英文缩写、设备编码、厂商简称，再考虑 `whole_word`
- `exact` 只在你真的要整句完全相等时再用

### `slot_constraints`

作用：

- 把模板和槽位值钉死
- 是模板去歧义的关键字段

例子：

```jsonc
"slot_constraints": {
  "entity_type": ["device"],
  "metric": ["cpu_usage"],
  "query_operator": ["list"]
}
```

推荐：

- 对容易冲突的模板，尽量把 `entity_type / metric / query_operator` 写上

什么时候必须写：

- 同一个实体下有多个模板
- 同一个操作词可能对应多个模板
- 仅靠 `must_terms` 还不够区分

常见错误：

- 觉得已经有 `must_terms` 了，所以不写 `slot_constraints`
- 结果相近模板互相抢

### `slot_extractors`

作用：

- 这是当前推荐的参数定义位置
- 每个模板只定义自己要用的参数

为什么下沉到模板：

- 同一个槽位名，在不同模板里可能需要不同提参规则
- 你当前业务里做不到统一参数字典，这是合理的

原则：

- 只定义这个模板真正需要的槽位
- 不要为“未来可能复用”提前做大而全抽参

推荐：

- `time_range`
- `region_id`
- `query_operator`
- 业务阈值，如 `cpu_threshold`

不推荐：

- 为了统一而把所有模板都挂一堆无关 extractor

### `llm_slot_extraction`

作用：

- 允许模板在“已命中 top1”后，用 LLM 定向补少量槽位

字段：

- `enabled`
- `slots`
- `instructions`

推荐写法：

```jsonc
"llm_slot_extraction": {
  "enabled": true,
  "slots": ["topn"],
  "instructions": "仅补充TopN，不要生成时间、区域或别的条件。"
}
```

关键原则：

- `slots` 一定要是白名单
- `instructions` 一定要窄
- 不要写成“尽量补齐所有缺失参数”

推荐场景：

- `前十`、`前五` 这种规则 regex 没完全覆盖的中文数字
- 口语化数字表达
- 个别模板的窄补参

不推荐场景：

- 模板都没稳定命中时，让 LLM 帮你选模板
- 一次补很多业务值

### `metadata`

作用：

- 原样透传给下游

适合放什么：

- 稳定业务编码
- 模板归类信息

例如：

```jsonc
"metadata": {
  "metric_code": "device_cpu_over_list"
}
```

不适合放什么：

- 会参与打分的字段
- 运行时临时状态

## `slot_extractors` 里的 extractor 怎么写

当前只支持两类：

- `keyword_value`
- `regex`

### `keyword_value`

适合：

- 时间枚举
- 区域枚举
- 实体类型
- 操作类型
- 严重级别

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

写好它的关键：

- `terms` 里放“用户真的会说”的词
- 不要只放规范术语

### `regex`

适合：

- `topn`
- 各种阈值
- 数值型参数

示例：

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

写好它的关键：

- 尽量覆盖提参位置变化
- 写边界值约束
- 对 typo 做有限兼容

例如阈值建议至少写两种方向：

- `cpu 大于 80`
- `大于 80 的 cpu`

## 3 类模板的推荐写法

### 数量类模板

适合：

- `昨天北京掉线设备数`

建议：

- `required_slots` 里通常放 `query_operator`
- `must_terms` 里必须有数量概念组
- `slot_constraints.query_operator` 明确写 `count`

### 排名类模板

适合：

- `近24小时接口错误包告警前十`

建议：

- `required_slots` 里通常要有 `topn`
- `must_terms` 里必须有排行概念组
- `llm_slot_extraction.slots` 可以只放 `topn`

### 列表类模板

适合：

- `查询最近 cpu 大于 80 的设备列表`

建议：

- `required_slots` 里放 `query_operator` 和关键阈值
- `must_terms` 里必须有“列表”概念组
- `slot_constraints.query_operator` 明确写 `list`

## 多条件模板怎么写才不容易打架

这是最容易出问题的部分。

以这三个模板为例：

- `device.cpu.over.list`
- `device.cpu.memory.over.list`
- `device.cpu.memory.disk.over.list`

推荐做法：

1. `description` 明确写条件数
2. `utterances` 里真实覆盖双条件、三条件表达
3. `required_slots` 里把多出来的阈值写成必填
4. `llm_slot_extraction.slots` 只允许补当前模板自己的阈值

为什么：

- 双条件 query 应该优先落到双条件模板
- 三条件模板不能因为名字像就抢走双条件 query

## 什么时候该用前置 `query_rewrite`

`query_rewrite` 和 `slot_extractors` 解决的不是一类问题。

`query_rewrite` 更适合：

- 跨多个模板都会出现的行业黑话
- 内部简称
- 别名统一
- 你希望在进入召回前就统一口径的表达
- 适合单独抽成词典文件维护的全局映射

典型例子：

- `北二小 -> 北京第二小学`
- `错包 -> 错误包`
- `思科设备 -> cisic`

推荐放到 `query_rewrite` 的原因：

- 它们不是某个单一模板的局部参数问题
- 它们会同时影响召回、must_terms、模板内提参
- 越早统一，后面的模板定义越稳定

推荐长期做法：

- 模板继续放在 `templates.json`
- 行业黑话、别名、内部简称单独放到 `query_rewrite` 的词典文件
- 让模板和词典分开迭代，减少互相影响

不推荐放到 `query_rewrite` 的情况：

- 只在某个模板里才成立的同义词
- 需要抽成槽位值的自由文本
- 需要结合模板语义才能决定改写目标

这类场景更适合：

- 模板自己的 `slot_extractors`
- 或模板级 LLM 补参

补充：

- 如果你担心英文缩写误改写，可以在规则里使用 `match_mode = whole_word`
- `whole_word` 更适合英文、数字、设备编码这类有明显 token 边界的表达

## 复杂单设备指标查询怎么拆

下面这个场景很典型：

- `查询[时间][ip/mac/名称]为[xxx]的[xx网络设备]的[cpu利用率/内存利用率]的[最大/最小/趋势/平均]`

这个场景建议不要直接按所有维度做笛卡尔拆分，否则模板数量会很快失控。

推荐拆法：

1. 先按“查询形态”拆模板
2. 再把“定位方式、指标、设备类型”下沉成槽位

第一版通常拆成 2 个模板就够：

- 聚合值模板
  负责 `最大 / 最小 / 平均`
- 趋势模板
  负责 `趋势`

不推荐第一版就拆：

- `ip` 一个模板、`mac` 一个模板、`名称` 一个模板
- `cpu` 一个模板、`内存` 一个模板

原因：

- `趋势` 和 `最大/最小/平均` 的结果形态不同，是真正的模板边界
- `ip/mac/名称` 更像“定位同一台设备的不同方式”，更适合做槽位
- `cpu/内存` 在很多场景下只是 `metric` 的不同取值，不一定要立刻拆模板

推荐槽位设计：

- `selector_type`
  值域：`ip / mac / name`
- `selector_value`
  值域：自由文本或结构化标识
- `metric`
  值域：`cpu_usage / memory_usage`
- `aggregation`
  仅聚合模板使用，值域：`max / min / avg`
- `entity_type`
  如果不同设备类型只是过滤条件，先做可选槽位；如果下游查询逻辑不同，再升级成强约束

关键点：

- 不要把 `selector_ip / selector_mac / selector_name` 都放进 `required_slots`
- 现在可以用 `required_one_of` 表达“多选一必填”
- 这类场景更适合统一成 `selector_type + selector_value`

补充说明：

- 这个场景的完整骨架见 [typical_template_examples.md](D:/GitHub/chat_pre_check_blank/docs/typical_template_examples.md)
- 如果你要做趋势模板，记得同步检查全局 `blocked_terms`，避免把 `趋势 / 走势` 提前拦掉

## 新增模板的推荐流程

建议按这个顺序做：

1. 先判断是不是问数场景
2. 给模板起稳定 `template_id`
3. 写一句单意图的 `description`
4. 先列 5 条真实 `utterances`
5. 定义 `required_slots / optional_slots`
6. 写 `must_terms`
7. 写 `slot_constraints`
8. 再写模板自己的 `slot_extractors`
9. 如果 regex 不够稳，再决定要不要开 `llm_slot_extraction`
10. 补评测样本
11. 跑 `pytest` 和 `evaluate_matcher`

## 常见坏味道

下面这些基本都会导致效果变差。

### 坏味道 1：一个模板写两个意图

错误示例：

- `查询设备列表或数量`

问题：

- 列表和数量是两个不同操作
- 应拆成两个模板

### 坏味道 2：`must_terms` 分组太随意

错误示例：

```jsonc
"must_terms": [
  ["设备", "掉线", "数量"]
]
```

问题：

- 约束失效

### 坏味道 3：`required_slots` 过多

错误表现：

- 大量 query 明明已经能查，却总是 `partial`

### 坏味道 4：`slot_constraints` 太少

错误表现：

- 多个模板互相抢

### 坏味道 5：`llm_slot_extraction.slots` 过宽

错误示例：

```jsonc
"llm_slot_extraction": {
  "enabled": true,
  "slots": ["time_range", "region_id", "metric", "entity_type", "query_operator", "topn"],
  "instructions": "尽量补齐所有参数"
}
```

问题：

- 太容易胡编
- 不利于控制风险

## 好模板和坏模板对比

好模板：

```jsonc
{
  "description": "查询离线设备数量",
  "required_slots": ["time_range", "region_id", "query_operator"],
  "must_terms": [
    ["设备"],
    ["离线", "掉线"],
    ["多少", "有多少", "数量", "数", "总数"]
  ],
  "slot_constraints": {
    "entity_type": ["device"],
    "metric": ["offline_count"],
    "query_operator": ["count"]
  }
}
```

坏模板：

```jsonc
{
  "description": "查询设备情况",
  "required_slots": [],
  "must_terms": [
    ["设备"]
  ],
  "slot_constraints": {}
}
```

差别：

- 好模板在“查什么、怎么查、查哪类实体”上都钉死了
- 坏模板几乎会误吸一切和设备有关的 query

## 什么时候该开 LLM 补参

建议开：

- 模板本身容易稳定命中
- 缺的只是 1 到 2 个值型参数
- 规则提参对中文数字、口语化表达不够稳

建议不开：

- 模板之间本来就分不清
- 缺的不是参数，而是意图本身不清楚
- 想让 LLM 代替模板设计

## 上线前检查清单

每个新模板上线前，至少过一遍这个清单。

- `template_id` 是否稳定可读
- `description` 是否只有一个意图
- `utterances` 是否覆盖真实变体
- `required_slots` 是否只保留真正必需参数
- `must_terms` 是否按语义组拆开
- `slot_constraints` 是否足够钉死模板
- `slot_extractors` 是否只定义本模板需要的槽位
- `llm_slot_extraction.slots` 是否足够窄
- 是否补了 `matched / partial / unmatched` 样本
- 是否跑过 `python -m pytest -q`
- 是否跑过 `python tools/evaluate_matcher.py`

## 最后建议

如果你以后要自己加模板，最重要的不是“写更多模板”，而是“每个模板都写得窄、准、可解释”。

模板一旦开始泛化成“这个也能接，那个也能接”，后面的维护成本会急剧上升。

当前这套体系里，最有价值的顺序应该一直是：

1. 先把模板边界写清楚
2. 再把规则提参写清楚
3. 最后才考虑让 LLM 补少量参数
