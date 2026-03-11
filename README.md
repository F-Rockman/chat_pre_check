# template-capability

从原 `chat_pre_check` 工程中裁剪出来的独立模板能力工程。

这个工程只保留模板匹配闭环：

1. 文本归一化
2. 轻量槽位抽取
3. 跨模板打分匹配
4. 缺参追问
5. 模板路由或拒答

不包含：

1. Scene/Flow 分流
2. OpenSearch / Elasticsearch 检索
3. NL2SQL 兜底
4. 远程实体解析

## 快速开始

```bash
pip install -e ".[dev]"
python main.py --input "近24小时接口错误包告警Top10"
python main.py --interactive
```

## 返回类型

- `route_template`: 命中模板且参数齐全
- `clarify`: 模板已命中，但缺少必填槽位
- `refuse`: 未命中任何可信模板

## 模板来源

模板定义复制自原工程已设计的模板能力，当前包含：

- `alarm.query`
- `device.query`
- `alarm.analysis`

配置文件见 [templates.json](D:/GitHub/chat_pre_check_blank/configs/templates.json)。

## 测试

```bash
python -m pytest -q
```

