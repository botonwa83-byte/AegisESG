# aegisESP 系统全貌 Demo

## 这次演示展示什么

系统 Demo 不是单独展示排名，而是展示一条完整的“公开资料 → 证据 → 候选 → 自动预排名 → 风险审核 →
正式冻结门禁 → 可追溯发布”生产线：

1. `/dashboard`：全市场覆盖、37项定量指标、E/S/G维度、冲突候选、审核分层和冻结状态；
2. `/api/v1/methodology`：80项指标、定量/定性权重和方法论版本；
3. `/api/v1/progress`：机器可读的覆盖和缺口统计；
4. `/api/v1/review-conflicts`：真实证据页码、候选值和冲突审核入口；
5. `/api/v1/review-tiers`：自动确认、抽查和人工签名分层；
6. `/api/v1/resolution-freeze-audit`：正式冻结是否可用；
7. `/api/v1/rankings?report_year=2025`：开发数据库中已确认数据的接口排名；
8. `output/demo/real_data_demo_2025/ranking.html`：研究预排名结果页；
9. `external_readiness_2025.json`：E1/E2、抽样、专利和发布双签状态。

## 启动方式

在任意目录执行（不需要`sudo`；建议使用当前用户的Python环境）：

```bash
bash scripts/run_real_system_demo.sh
```

如果当前就在`scripts`目录，也可以执行：

```bash
bash run_real_system_demo.sh
```

重启已在运行的 Demo（会安全停止本项目记录的旧进程并保留日志）：

```bash
sh scripts/restart_real_system_demo.sh
```

脚本默认使用当前用户的 Python 环境，不要加`sudo`。日志位于`var/aegis-demo.log`，PID位于
`var/aegis-demo.pid`。

脚本会自动定位项目根目录并设置绝对`PYTHONPATH`。不建议使用`sudo`，否则可能切换到另一套Python
依赖环境；若必须使用，请确保该Python环境已安装`uvicorn`、`fastapi`和项目依赖。

浏览器打开：

```text
http://127.0.0.1:8000/dashboard
```

真正的领导演示首页是：

```text
http://127.0.0.1:8000/demo
```

`/dashboard`是研发数据看板；`/demo`才是系统全貌演示入口。

Demo页面已经产品化：敏感性、元数据、方法论和发布门禁使用结构化HTML页面；原始JSON接口只供系统
集成和开发调试，不作为领导演示入口。

原始文档查看使用`data/raw/all_markets_document_index.csv`全市场索引（当前809份文档，文件存在且SHA-256
校验通过）；企业详情优先提供本地PDF入口，外部交易所URL作为辅助入口。不要使用旧的40份试点索引判断全市场
文档是否下载。

可先打开`/demo/data-readiness`查看本地文档底座，再进入排名中心；该页展示索引文档数、覆盖企业、年报/ESG报告
数量、本地文件数和Hash登记数。

若本机端口受限，可换端口：

```bash
AEGIS_DEMO_PORT=4174 bash scripts/run_real_system_demo.sh
```

## 5—10分钟演示路线

1. 先看 Dashboard 顶部卡片：614家公司、9,015候选观测、8,125候选组、317冲突组、冻结未就绪。
2. 滚动到 E/S/G 覆盖和指标表，展示系统如何定位缺口，而不是只输出一个总分。
3. 进入冲突候选，展示同一公司指标的不同页码、证据文本和候选值。
4. 进入审核分层，说明7,794组可按自动政策处理，317组必须人工签名，自动化没有隐藏人工判断。
5. 查看`/api/v1/methodology`，说明37项定量+43项定性和固定权重。
6. 查看冻结审计，说明`valid`不等于`freeze_ready`，当前仍不能正式发布。
7. 最后打开研究排名 HTML，说明结果页只是系统流水线的一个输出，不是系统全貌。

## 当前演示边界

Dashboard 使用真实 v22 候选和审核分层，但数据仍处于研究/审核阶段；正式发布门禁为0/6。
演示时不能把“自动政策可处理”说成“正式已确认”，也不能填写或展示伪造签名。
