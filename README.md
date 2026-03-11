# template-capability

面向“问数”场景的通用模板匹配能力。

这个工程的定位不是 POC，也不是业务 demo。它是一个纯中间层能力，负责在注册一批问数模板后，快速判断用户 query 是否命中某个模板。

返回结果只有三类：

- `matched`：命中模板且必填槽位齐全
- `partial`：命中模板但缺少必填槽位
- `unmatched`：没有可信模板，返回 `template_id = -1`

## 目标与边界

这个工程只做：

1. 配置驱动的槽位抽取
2. 模板候选召回
3. 模板精排打分
4. 命中模板 / 部分命中 / `-1`
5. 模板回归评测

这个工程不做：

1. 报告、总结、根因、预测等非问数场景
2. 下游查询执行
3. 追问文案生成
4. 业务实体写死在代码里
5. 在线大模型逐模板全量推断

## 核心设计

整体链路：

1. `normalize_text`：文本标准化
2. 文本召回候选模板，不做全局统一提参
3. `BM25F` + `char ngram` + `vector search`：多路候选召回
4. 命中候选后，按模板自己的 `slot_extractors` 做模板内提参
5. `RRF` + 动态权重重排：融合多路召回，按 query 复杂度调权
6. `slot_fit` + `constraint` + `structure_score`：模板约束和结构校验
7. 可选模板级 LLM 补参：只在已命中模板上窄触发
8. 阈值和歧义判断：输出 `matched / partial / unmatched`

设计原则：

- 模板定义和槽位定义都配置化
- 参数抽取默认下沉到模板，不依赖全局统一参数字典
- 匹配支持提参、语序变化、口语化表达
- 大模型默认不进入主链路；只支持命中后的模板级窄触发补参
- 向量后端可替换，默认按 `512` 维接口设计
- 模板扩展后必须可批量评测

## 目录结构

```text
.
|-- configs/
|   `-- templates.json
|-- src/template_capability/
|   |-- config.py
|   |-- engine.py
|   |-- evaluation.py
|   |-- extractors.py
|   |-- models.py
|   |-- scoring.py
|   `-- vector_index.py
|-- tests/
|   |-- fixtures/evaluation_cases.json
|   |-- test_engine.py
|   |-- test_extractors.py
|   |-- test_generalization.py
|   |-- test_evaluation_corpus.py
|   |-- test_evaluation_report.py
|   `-- test_engine_capabilities.py
|-- tools/
|   |-- evaluate_matcher.py
|   `-- generate_eval_corpus.py
|-- main.py
`-- README.md
```

## 运行方式

安装：

```bash
pip install -e ".[dev]"
```

单条输入：

```bash
python main.py --input "过去24小时接口错包告警前10名"
```

交互模式：

```bash
python main.py --interactive
```

开启模板级 LLM 补参：

```bash
$env:DASHSCOPE_API_KEY="***"
python main.py --llm-slot-fallback --input "近24小时接口错误包告警前十"
```

运行测试：

```bash
python -m pytest -q
```

## 输出契约

示例：

```json
{
  "template_id": "alarm.interface.error.topn",
  "status": "matched",
  "score": 0.96,
  "query_mode": "metric_query",
  "slots": {
    "time_range": {
      "mode": "relative",
      "preset": "last_24h"
    },
    "topn": 10,
    "entity_type": "interface",
    "metric": "error_packet",
    "query_operator": "topn"
  },
  "missing_slots": [],
  "metadata": {
    "metric_code": "interface_error_alarm_topn"
  },
  "trace": {}
}
```

字段说明：

- `template_id`：命中的模板；未命中时为 `-1`
- `status`：`matched / partial / unmatched`
- `score`：最终融合分
- `query_mode`：当前模板类型，当前主要是 `metric_query`
- `slots`：抽出的槽位
- `missing_slots`：`partial` 时缺失的必填槽位
- `metadata`：模板透传字段
- `trace`：调试轨迹，不建议下游业务强依赖

## 配置说明

主配置文件是 [templates.json](D:/GitHub/chat_pre_check_blank/configs/templates.json)。

如果你要自己新增模板，优先看单独的模板编写文档：

- [template_authoring_guide.md](D:/GitHub/chat_pre_check_blank/docs/template_authoring_guide.md)

顶层结构：

```json
{
  "matcher": {},
  "slot_extractors": {},
  "templates": []
}
```

### matcher

示例字段：

- `match_threshold`
  最终总分达到这个阈值才允许进入 `matched / partial`
  值越低，召回更激进，但误匹配会增加
- `ambiguity_margin`
  top1 和 top2 的分差小于这个值时直接返回 `-1`
  用来避免两个模板都像时硬选错
- `recall_top_k`
  每一路召回保留多少候选进入融合
  模板规模在几百到一两千时，`20-50` 通常够用
- `weights`
  最终重排时各子分数的基础权重
  当前支持：`lexical / sample / vector / fusion / slot_fit / constraint / structure`
- `lexical_field_weights`
  BM25F 的字段权重
  当前字段：`description / utterances / must_terms`
  一般 `must_terms` 应该最高，因为它决定模板语义锚点
- `fusion_rrf_k`
  RRF 的倒数排序参数
  值越大，不同召回路之间的 rank 差异被压得越平
- `vector.dimension`
  向量维度
  当前主流程按 `512` 维设计，后续替换真实向量接口时保持一致即可
- `blocked_terms`
  全局拦截词
  命中后直接返回 `unmatched`
  适合放 `报告 / 分析 / 总结 / 根因 / 预测` 这类明确非问数词
- `llm_fallback`
  模板选择阶段的 LLM 兜底
  只建议在 `partial` 或接近阈值的 `unmatched` 上窄触发
  不建议作为主链路能力
- `llm_slot_fallback`
  模板已命中后的 LLM 补参开关
  这是当前更推荐的用法
  只在 top1 模板比较稳定，但还有少量关键槽位没抽到时补参

`weights` 的含义：

- `lexical`
  BM25F 词法匹配分
  适合稳住领域关键词、固定词组
- `sample`
  基于模板示例问法的 `char ngram` 相似度
  对语序变化、轻微口语化更稳
- `vector`
  向量召回分
  用来处理更弱的表达改写
- `fusion`
  多路召回经 RRF 融合后的排序分
  用来减少单一路召回偏置
- `slot_fit`
  槽位覆盖度
  query 抽到的关键参数越齐，分越高
- `constraint`
  模板约束分
  包括 `must_terms` 命中和 `slot_constraints` 一致性
- `structure`
  结构一致性分
  用来惩罚“query 有的条件模板接不住”或“模板要求的关键过滤条件没给全”

建议：

- `match_threshold` 不要太低，否则误匹配会明显增加
- `blocked_terms` 主要放非问数意图词，如 `报告 / 分析 / 根因 / 预测`
- `llm_fallback` 只建议在 `partial` 或接近阈值的 `unmatched` 上窄触发
- `llm_slot_fallback` 只建议在 top1 模板已稳定命中、但缺少少量关键参数时触发

`llm_slot_fallback` 细项：

- `enabled`
  是否启用模板级 LLM 补参
- `max_missing_slots`
  最多允许缺多少个必填槽位时触发 LLM
  建议控制在 `1-2`
- `min_score`
  top1 模板分数至少达到多少才允许触发 LLM
  这能避免把 LLM 用在本来就不稳定的命中上
- `allow_on_matched`
  即使已经 `matched`，是否还允许 LLM 二次补参
  默认建议关闭，除非你确实需要补充可选槽位

### slot_extractors

根级 `slot_extractors` 现在主要用于兼容旧配置；主路径推荐把参数抽取下沉到每个模板的 `slot_extractors`。

槽位抽取内置两类抽取器：

- `keyword_value`
- `regex`

`keyword_value` 适合：

- 时间表达
- 区域
- 指标
- 查询算子
- 严重级别

`regex` 适合：

- `topn`
- 数字类参数
- 格式稳定的标识

模板内 `keyword_value` 示例：

```json
{
  "slot_extractors": {
    "time_range": {
      "extractors": [
        {
          "type": "keyword_value",
          "cases": [
            {
              "terms": ["近24小时", "过去24小时", "24小时内"],
              "value": {
                "mode": "relative",
                "preset": "last_24h"
              }
            }
          ]
        }
      ]
    }
  }
}
```

模板内 `regex` 示例：

```json
{
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
}
```

### templates

模板字段：

- `template_id`：唯一标识
- `query_mode`：模板类型
- `description`：模板说明
- `utterances`：示例表达，用于召回和相似度
- `required_slots`：必填槽位
- `optional_slots`：可选槽位
- `must_terms`：必须出现的语义组；每组任一词命中即可
- `negative_terms`：模板级负向词
- `slot_constraints`：槽位约束
- `slot_extractors`：该模板自己的参数抽取规则
- `llm_slot_extraction`：该模板的可选 LLM 补参配置
- `metadata`：业务透传字段

重点字段解释：

- `must_terms`
  这是模板的语义锚点
  每组里命中任意一个词就算该组通过
  如果一个模板很容易和别的模板打架，先加固这里
- `slot_constraints`
  用来限制抽出来的槽位值必须落在模板允许范围内
  比如 `query_operator` 必须是 `list`，或者 `severity` 必须是 `critical`
- `slot_extractors`
  当前推荐的参数定义位置
  模板需要什么参数，就在模板内定义什么参数
  不追求全局统一参数字典
- `llm_slot_extraction`
  控制该模板是否允许 LLM 补参，以及补哪些槽位
  这是模板级开关，不是全局一刀切

模板示例：

```json
{
  "template_id": "device.offline.count",
  "query_mode": "metric_query",
  "description": "查询离线设备数量",
  "utterances": [
    "昨天华东离线设备数",
    "近24小时广州离线设备数量"
  ],
  "required_slots": ["time_range", "region_id", "query_operator"],
  "optional_slots": [],
  "must_terms": [
    ["设备"],
    ["离线", "掉线"],
    ["多少", "有多少", "数量", "数", "总数"]
  ],
  "negative_terms": ["原因", "根因", "报告", "总结", "预测"],
  "slot_constraints": {
    "entity_type": ["device"],
    "metric": ["offline_count"],
    "query_operator": ["count"]
  },
  "slot_extractors": {
    "time_range": {
      "extractors": []
    }
  },
  "llm_slot_extraction": {
    "enabled": true,
    "slots": ["time_range", "region_id", "query_operator"],
    "instructions": "仅补充时间、区域和数量算子，不要发明额外条件。"
  },
  "metadata": {
    "metric_code": "device_offline_count"
  }
}
```

`llm_slot_extraction` 字段说明：

- `enabled`
  该模板是否允许走 LLM 补参
- `slots`
  允许 LLM 补的槽位白名单
  不在这个列表里的槽位，即使缺失也不让 LLM 填
- `instructions`
  给 LLM 的模板级补充说明
  这里最好写成非常窄的约束，而不是泛泛的自然语言说明

## 匹配算法

当前不是严格字符串匹配，而是混合算法：

1. `BM25F` 多字段词法召回
2. `char ngram` 样本相似度
3. `vector search` 向量召回
4. 命中候选后，按模板本地 extractor 抽参
5. `RRF` 融合多路召回排名
6. 动态权重重排
7. `slot_fit_score` 槽位覆盖度
8. `constraint_score` 模板约束得分
9. `structure_score` 结构一致性得分
10. 可选模板级 LLM 补参

最终分数：

```text
total_score =
  lexical * w1
  + sample * w2
  + vector * w3
  + fusion * w4
  + slot_fit * w5
  + constraint * w6
  + structure * w7
```

为什么这样设计：

- `BM25F` 比单文本 BM25 更适合模板多字段匹配
- `char ngram` 对中文短句、语序变化、口语化更稳
- `vector search` 处理更弱的表达改写
- `RRF` 能把多路召回的优势合并起来，减少单路偏置
- 动态权重会在多条件 query 上自动提高 `structure` 和 `slot_fit` 权重
- `slot_fit` 保证模板参数完整性
- `constraint` 防止“看起来像，但其实不是这个模板”
- `structure_score` 会同时惩罚两类问题：
  query 里多出的条件模板接不住；模板要求的关键过滤条件 query 没给全

## 向量接口接入

向量后端定义在 [vector_index.py](D:/GitHub/chat_pre_check_blank/src/template_capability/vector_index.py)。

当前默认实现：

- `HashingVectorProvider`
- `InMemoryVectorIndex`

这只是本地占位实现，便于测试和脱离外部服务运行。

后续替换真实向量服务时，建议保持同样的职责边界：

1. 离线为模板文档建立向量索引
2. 在线只对 query 编码一次
3. 返回 `[(template_id, score)]`
4. 向量维度保持 `512`

最低需要实现的接口：

```python
class VectorSearchBackend(Protocol):
    def build(self, documents: dict[str, str]) -> None:
        ...

    def search(self, query_text: str, top_k: int) -> list[tuple[str, float]]:
        ...
```

接入建议：

- 不要在 `search()` 里重新为所有模板编码
- 不要把外部向量服务耦合到 `engine.py` 里
- 保持 `engine` 只依赖统一 backend 接口

## 开发流程

### 新增一个模板

推荐顺序：

1. 在 [templates.json](D:/GitHub/chat_pre_check_blank/configs/templates.json) 添加模板定义
2. 直接在该模板下定义 `slot_extractors`
3. 给模板补 `matched / partial / unmatched` 样本
4. 运行批量评测
5. 根据失败样本调模板和阈值

### 新增一个槽位

推荐顺序：

1. 先判断这个槽位是否能通过 `keyword_value` 或 `regex` 表达
2. 如果可以，优先只改配置
3. 如果配置表达不了，再扩 `extractors.py`
4. 补抽取测试和回归样本

不要做的事：

- 不要把具体区域、指标、协议硬编码回 Python
- 不要把模板追问文案混入能力层
- 不要为了一个模板改全局逻辑
- 不要先做全局通用抽参，再去套模板；优先按模板内规则抽参

### 调权重和阈值

优先调：

- `match_threshold`
- `ambiguity_margin`
- `weights.structure`
- `weights.slot_fit`
- `weights.lexical`
- `weights.fusion`
- `lexical_field_weights.must_terms`
- `must_terms`
- `slot_constraints`

不建议优先靠大量堆同义词解决误匹配。先看是不是模板约束不够、负向词不够、评测样本不够。

## 批量评测

评测入口是 [evaluate_matcher.py](D:/GitHub/chat_pre_check_blank/tools/evaluate_matcher.py)。

命令：

```bash
python tools/evaluate_matcher.py
python tools/evaluate_matcher.py --json --output reports/evaluation_report.json
python tools/evaluate_matcher.py --fail-on-errors
```

报告内容：

- 总体通过率
- `matched / partial / unmatched / not_full_match` 分桶结果
- 每个模板的样本覆盖情况
- 没有任何评测样本的新模板
- 失败样本明细

适合接入：

- 本地开发回归
- CI 校验
- 模板发布前检查

## 评测语料

静态评测集在 [evaluation_cases.json](D:/GitHub/chat_pre_check_blank/tests/fixtures/evaluation_cases.json)。

分四类：

- `matched`：必须完整命中
- `partial`：必须命中模板但缺少槽位
- `unmatched`：必须返回 `-1`
- `not_full_match`：不能返回 `matched`

当前测试覆盖：

- 槽位抽取
- 多表达泛化
- 非问数意图拦截
- 歧义模板返回 `-1`
- `1000` 模板规模回归
- 可替换向量后端
- 批量评测报告统计

## LLM 造样本

LLM 默认只用于离线造测试样本，不用于在线匹配主链路。

如果需要在线兜底，当前代码支持两类 LLM 钩子：

1. `llm_fallback`：模板选择兜底
2. `llm_slot_fallback`：模板已命中后的定向补参

模板级补参更适合你当前这种“参数定义强依赖模板”的场景。

在线使用时建议遵守以下约束：

1. 默认关闭
2. 只在 `partial` 或接近阈值的 `unmatched` 上触发
3. 只看前 `N` 个候选模板，不做全量模板推断
4. 优先用于补关键槽位或在 top 候选里做裁决
5. 不要覆盖 `blocked_terms` 命中的 query

当前已提供一个兼容 OpenAI 协议的模板级补参实现：

- [fallback.py](D:/GitHub/chat_pre_check_blank/src/template_capability/fallback.py) 里的 `OpenAICompatibleTemplateSlotResolver`

最小可用方式：

1. 设置 `DASHSCOPE_API_KEY`
2. 使用 [main.py](D:/GitHub/chat_pre_check_blank/main.py) 的 `--llm-slot-fallback`
3. 只让它在模板已经比较稳定命中、但缺少少量关键参数时补参

当前 `main.py` 额外支持：

- `--llm-slot-fallback`
- `--llm-slot-base-url`
- `--llm-slot-model`
- `--llm-slot-timeout`

脚本在 [generate_eval_corpus.py](D:/GitHub/chat_pre_check_blank/tools/generate_eval_corpus.py)。

命令：

```bash
$env:DASHSCOPE_API_KEY="***"
python tools/generate_eval_corpus.py
```

默认参数：

- `base_url = https://coding.dashscope.aliyuncs.com/v1`
- `model = qwen3-coder-plus`

这个脚本会：

1. 读取当前模板配置
2. 调用兼容 OpenAI 协议的模型
3. 生成 `matched / partial / unmatched / not_full_match` 候选样本
4. 输出到 `tests/fixtures/`

注意：

- 生成样本后不要直接全量信任
- 需要人工筛掉不合理样本
- 最终应该把确认后的样本固化到静态评测集

## LLM 补参评测

已经提供一个在线 benchmark 脚本：

- [benchmark_llm_slot_fallback.py](D:/GitHub/chat_pre_check_blank/tools/benchmark_llm_slot_fallback.py)

命令：

```bash
$env:DASHSCOPE_API_KEY="***"
python tools/benchmark_llm_slot_fallback.py
python tools/benchmark_llm_slot_fallback.py --json
```

这个脚本会对一组“规则抽参容易漏，但模板语义其实已经命中”的样例做对比：

- 不开 LLM 时的结果
- 开 LLM 补参后的结果
- 每条 query 的总耗时
- 每次 LLM 调用自身的耗时

另外还提供了一条默认跳过的在线测试：

- [test_live_llm_slot_fallback.py](D:/GitHub/chat_pre_check_blank/tests/test_live_llm_slot_fallback.py)

手动运行：

```bash
$env:RUN_LIVE_LLM_TESTS="1"
$env:DASHSCOPE_API_KEY="***"
python -m pytest -q tests/test_live_llm_slot_fallback.py
```

## 代码入口说明

主要文件职责：

- [main.py](D:/GitHub/chat_pre_check_blank/main.py)：CLI 入口
- [engine.py](D:/GitHub/chat_pre_check_blank/src/template_capability/engine.py)：主匹配流程
- [extractors.py](D:/GitHub/chat_pre_check_blank/src/template_capability/extractors.py)：标准化和槽位抽取
- [scoring.py](D:/GitHub/chat_pre_check_blank/src/template_capability/scoring.py)：召回、相似度、约束打分
- [vector_index.py](D:/GitHub/chat_pre_check_blank/src/template_capability/vector_index.py)：向量后端抽象和默认实现
- [evaluation.py](D:/GitHub/chat_pre_check_blank/src/template_capability/evaluation.py)：批量评测和报告
- [config.py](D:/GitHub/chat_pre_check_blank/src/template_capability/config.py)：配置加载
- [models.py](D:/GitHub/chat_pre_check_blank/src/template_capability/models.py)：核心数据模型

## 常见问题

### 为什么 query 看起来像模板，却返回 `-1`

常见原因：

- 命中了全局 `blocked_terms`
- top1 分数低于 `match_threshold`
- top1 和 top2 太接近，触发 `ambiguity_margin`
- 模板约束不足导致被误判成歧义

### 为什么 query 命中了模板，但只是 `partial`

因为模板语义已经比较明确，但缺少必填槽位，比如：

- 缺时间
- 缺 `topn`
- 缺区域
- 缺数量意图

### 为什么要把 `query_operator` 当作必填槽位

这是为了把“看指标”与“问数量/问排行”区分开。否则很多非问数 query 会被错误当成完整命中。

## 当前状态

当前仓库已具备：

- 配置驱动模板匹配
- 通用槽位抽取
- 可替换 `512` 维向量后端
- 静态评测集
- 批量评测报告
- LLM 离线造样本脚本

当前本地回归：

```bash
python -m pytest -q
python tools/evaluate_matcher.py
```
