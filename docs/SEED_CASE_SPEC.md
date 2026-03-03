# seed_case_v1 字段规范与批量导入说明

本文用于支撑 1000+ seed case 的并行填充与治理。

## 1. 目标
`seed_case_v1` 用于“能力边界判断”和“相似可做问题推荐”：
- 默认可关闭（`seed_scope_guard.enabled=false`）
- 后续 NL2SQL 能力增强后可逐步放开阈值或关闭守卫

## 2. 字段规范
### 2.1 必填字段
1. `case_id`：唯一 ID，建议 `seed_<domain>_<intent>_<window>`，例如 `seed_alarm_topn_core_24h`
2. `scene_id`：必须能映射 `configs/capabilities.json` 中 `capability_id`
3. `label`：给用户展示的短文案
4. `text`：用于向量/文本召回的标准问法

### 2.2 推荐字段
1. `route_type`：`route_template|route_nl2sql|clarify|refuse`
2. `slots`：对象，放结构化预置槽位
3. `tags`：数组，建议 2~6 个标签（域、意图、对象、时窗等）
4. `priority`：整型，默认 100（越高越优先治理）
5. `owner`：责任团队/人
6. `version`：如 `v1`
7. `enabled`：是否启用
8. `risk_level`：`low|medium|high`
9. `source`：`manual|offline_mining|ticket_feedback|prod_replay`
10. `notes`：备注

## 3. CSV/JSON 模板
模板文件：
- [seed_cases_template.csv](../templates/seed_cases_template.csv)
- [seed_cases_template.jsonl](../templates/seed_cases_template.jsonl)

CSV 中 `slots_json` 需是合法 JSON 对象字符串。

## 4. 批量导入脚本
脚本：
- [import_seed_cases.py](../scripts/import_seed_cases.py)

### 4.1 CSV 导入（替换模式）
```bash
python scripts/import_seed_cases.py \
  --input templates/seed_cases_template.csv \
  --input-format csv \
  --config-dir configs \
  --output configs/capabilities.json \
  --merge-mode replace \
  --on-duplicate error
```

### 4.2 JSONL 导入（增量 upsert）
```bash
python scripts/import_seed_cases.py \
  --input templates/seed_cases_template.jsonl \
  --input-format jsonl \
  --config-dir configs \
  --output configs/capabilities.json \
  --merge-mode upsert \
  --on-duplicate keep_last
```

### 4.3 非严格模式（收集错误不中断）
```bash
python scripts/import_seed_cases.py \
  --input seed_cases_batch.csv \
  --config-dir configs
```

严格模式示例（遇到首个错误立即失败）：
```bash
python scripts/import_seed_cases.py \
  --input seed_cases_batch.csv \
  --config-dir configs \
  --strict
```

## 5. 去重与合并策略
1. `--on-duplicate`
- `error`：重复 `case_id` 立即报错
- `keep_first`：保留第一条
- `keep_last`：保留最后一条

2. `--merge-mode`
- `replace`：输出仅使用当前导入
- `upsert`：按 `case_id` 合并到已有 `capabilities.json`

## 6. 质量门禁建议（1000+）
1. 唯一性：`case_id` 全局唯一
2. 覆盖性：每个 `scene` 至少 100+ 高质量 case
3. 代表性：每个主意图（topn/trend/analysis/correlation）都要覆盖
4. 可执行性：`route_template` case 要能匹配到现有模板
5. 可回归性：新批次导入后固定跑验收测试

## 7. 生产发布流程建议
1. 业务同学在 CSV/JSONL 模板填充
2. 导入脚本写入 `configs/capabilities.json` 中对应 `capability.intents`
   - 一个 intent 可选挂载 `template`，用于模板路由
   - 不再维护独立 `configs/seed_cases.json`
3. 向量索引构建：
```bash
python scripts/build_vector_indices.py --search-url http://localhost:9200 --config-dir configs
```
4. 灰度开启：
- 先设 `seed_scope_guard.enabled=true`
- `min_score` 先高后低（例如 `0.72 -> 0.65 -> 0.58`）
5. 观察指标：
- `out_of_seed_scope` 拒答率
- 推荐按钮点击率
- 误拒样本回放
