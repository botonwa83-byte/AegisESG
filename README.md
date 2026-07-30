# 中国能源上市公司可持续发展（ESG）评价系统

本项目依据目录内的《2025中国能源上市公司可持续发展（ESG）评价报告》和
《行标定量指标》实现一套可审计、可复现的评价流水线。

## 已实现范围

- 37项定量指标、43项定性指标和原报告权重；
- 定量80%、定性20%的总分合成；
- 正向、负向、双向指标及1%/99%缩尾；
- 定性指标0/20/50/80/100档评分；
- 缺失、不适用、待复核和已确认状态；
- 数据来源URL、文件、页码、证据文本和置信度；
- 年度样本正态评分、E/S/G分项、披露率和并列排名；
- 与PDF相同字段顺序的前200 CSV/HTML榜单；
- FastAPI查询接口、本地审计库及MySQL 8.4生产表结构；
- 公开文档URL清单下载、SHA-256审计留痕。
- 上交所公告自动发现、官方镜像下载回退及真实PDF有效性校验；
- 财务事实公式派生和PDF页码文本候选抽取。
- 四交易所标准快照合并、能源行业复核、ST排除、A/H去重和公司池决策审计。

## 重要边界

2025报告说明其原始数据还包括Choice终端和青绿数据，且没有公开以下内容：

- 632家公司的全部80项原始观测；
- 正态函数的具体参数和极端值剔除明细；
- 公司治理所用国资委工业领域“优秀值”的年度参数；
- 43项定性指标逐公司的判断证据；
- 缺失数据的精确处理细则。

因此本系统提供的是**公开方法论兼容、计算过程透明的独立评价**，不能声称与
报告发布机构的官方分数完全一致。要精确复刻官方榜单，必须获得上述授权数据
和参数并固化成新的方法论版本。

## 快速验证

```bash
export PYTHONPATH=src
python3 scripts/generate_demo_data.py
python3 -m aegis_esg.cli score data/samples/demo_observations.csv \
  --output-dir output/demo \
  --title "2025中国能源上市公司可持续发展（ESG）评价前200名单"
python3 -m unittest discover -s tests -v
```

输出包括：

- `ranking.csv`：PDF式两行结构，每家公司包含“指标数值/指标分值”；
- `ranking.html`：浏览器查看和A3横向打印；
- `ranking.json`：包含80项下钻计算参数和贡献分值。

运行API：

```bash
export PYTHONPATH=src
python3 -m aegis_esg.cli init-db var/aegis.db
AEGIS_DB=var/aegis.db uvicorn aegis_esg.api:app --host 0.0.0.0 --port 8000
```

启动后访问`http://127.0.0.1:8000/dashboard`可查看本地只读开发进度看板，包括港股公司×37项
定量指标覆盖、E/S/G维度缺口、关键指标优先级和冲突候选证据。看板展示的是`pending`候选审计
状态，不代表正式评分或已确认数据。

下载冲突复核模板并由审核人填写`action`（`confirm`或`reject`）、候选值、审核人、带时区时间和
理由后，可安全生成确认观测、剩余候选和独立审计：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli apply-conflict-review \
  data/review/hkex_indicator_candidates_2026-07-29.csv signed-review.csv \
  --confirmed output/review/confirmed.csv \
  --unresolved output/review/unresolved.csv \
  --audit output/review/audit.csv
```

主要接口：

- `GET /health`
- `GET /api/v1/progress`
- `GET /api/v1/review-conflicts`
- `GET /api/v1/review-template`
- `GET /api/v1/methodology`
- `POST /api/v1/observations`
- `GET /api/v1/rankings?report_year=2024`
- `GET /api/v1/companies/{stock_code}/score?report_year=2024`

## 数据生产流程

1. 建立当年能源上市公司范围，排除ST、*ST并冻结样本版本；
2. 从交易所、巨潮资讯和公司官网下载上一年度年报及ESG报告；
3. 原文件上传OSS，同时记录URL、发布时间和SHA-256；
4. 规则抽取37项定量指标，财务指标优先使用合规结构化接口；
5. 定性指标和低置信度字段进入人工复核；
6. 只有`confirmed`数据进入年度评分批次；
7. 冻结输入Hash、方法论版本、代码版本和样本统计参数；
8. 生成前200排名、指标下钻和异常诊断；
9. 与`data/reference/2025_top35_excerpt.csv`做趋势回归，而非强行拟合官方分数。

详细的生产数据规则见[数据流水线](docs/data-pipeline.md)，MySQL建表脚本见
[`sql/mysql/schema.sql`](sql/mysql/schema.sql)。

## 2026真实榜单试点

参考报告的评价总体为632家公司，公开榜单只列前200名。当前候选池有40个证券代码，
排除2个A/H重复证券后纳入38家公司；真正完成报告采集、指标抽取并进入统计的是其中
25家，完成率为3.96%。当前结果只能称为试点，不能称为全市场榜单。

当前试点以2025报告期公开数据生成2026评价输入。上交所25家公司已发现并成功
下载41份正式报告（25份年报、16份ESG/可持续发展报告），失败0份。长江电力
作为首个端到端样本：

- 官方年报和ESG报告已下载并保存SHA-256；
- 已从经审计财务事实派生18项确认指标；
- 已从ESG报告抽取4项带页码的待复核候选；
- 当前尚不满足80项完整性；除营业增长率、ROE、研发占比和每股分红外，多数指标未达到20家公司
  的统计样本门槛，因此不能发布正式名次。

批量规则候选经过脚注、担保阈值、季度表、单位和公式假阳性清洗后，由
`public-disclosure-v3`策略确认367项，覆盖20类指标和全部25家公司。资产负债表、
利润表、现金流量表精算值，年报直接披露值及ESG一致单值分别记录判定原因；
当前未决候选为0。

可用以下命令重建公司池覆盖审计：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli universe-audit \
  data/universe/energy_pilot_2026.csv \
  --observations data/confirmed/pilot_2025_auto_confirmed.csv \
  --expected-companies 632 \
  --output output/audit/pilot_universe_coverage.json
```

正式输出必须使用`score --release --universe ... --expected-companies 632`；未达到完整公司池、
数据覆盖、四个交易所和行业分类要求时会被拒绝。

可复现文件位于`data/manifests/`、`data/raw/document_index.csv`和`data/real/`。
阶段明细见[真实榜单开发进度](docs/real-ranking-progress.md)。

全市场底表建设已取得首份真实交易所快照：截至2026-07-28的深交所官方名单共2,896家，
已保存原始XLSX、标准CSV、质量报告和SHA-256来源记录。该数字是全部深市公司数，不等于
能源评价纳入数；能源细分行业筛选完成前，正式统计仍保持38家入池、25家完成数据处理。

上交所官方底表也已完成：主板1,698家、科创板612家，合计2,310家。港交所官方完整证券表
已筛出主板/GEM普通股2,785只；沪深港标准底表现有7,991只证券，全部通过重复代码和来源
完整性检查。北交所官方快照另含332家公司及248条官方新旧代码映射，四市场母表合计
8,323只证券。后续按细分行业筛选，并用明确主体证据完成A/H去重。

参考PDF图片榜单已OCR得到227个唯一证券代码（对应前200家公司中的多地上市证券），其中
175个沪深代码、49个港股代码和3个北交所旧代码均已与交易所真实底表匹配。
该种子集为能源行业范围提供了确定证据，但其余
432家公司仍需通过完整细分行业口径识别，不能由前200榜单反推。

历史迁移、港股缺失代码签名解析与前200新增种子合并后，当前可审计候选池为614家公司，
距632家目标还差18家。
该差额必须通过最新细分行业名录识别，不能用20个重复H股证券补足主体数。
