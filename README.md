# 中国能源上市公司可持续发展（ESG）评价系统

本项目依据《DL/T 2971—2025 能源企业环境保护、社会责任和公司治理披露指标体系与评价导则》、
目录内《2025中国能源上市公司可持续发展（ESG）评价报告》和《行标定量指标》实现一套可审计、
可复现的评价流水线。

## 已实现范围

- 37项定量指标、43项定性指标和行标权重（定量/定性内 E45%·S20%·G35%）；
- 定量80%、定性20%的总分合成；
- 正向、负向、双向指标及1%/99%缩尾；
- 定性指标0/20/50/80/100档评分（行标达成率为20/50/80/100）；
- DL/T 2971表1级别映射（AAA–C / NA）及披露不足一半不予评级；
- 缺失、不适用、待复核和已确认状态；
- 数据来源URL、文件、页码、证据文本和置信度；
- 年度样本正态评分、E/S/G分项、披露率和并列排名；
- 正式发布一年有效期、评价组长签名与治理优秀值齐全门禁（脚手架已就绪）；
- 与PDF相同字段顺序的前200 CSV/HTML榜单；
- FastAPI查询接口、本地审计库及MySQL 8.4生产表结构；
- 公开文档URL清单下载、SHA-256审计留痕。
- 上交所公告自动发现、官方镜像下载回退及真实PDF有效性校验；
- 财务事实公式派生和PDF页码文本候选抽取。
- 四交易所标准快照合并、能源行业复核、ST排除、A/H去重和公司池决策审计。

## 重要边界

2025报告与行标本身未随文公开以下参数，系统不能凭空补齐：

- 632家公司的全部80项原始观测；
- 正态函数的具体参数和极端值剔除明细；
- 公司治理所用国资委工业领域“优秀值”的年度参数（见下方注入流程）；
- 43项定性指标逐公司的判断证据；
- 缺失数据的精确处理细则。

因此当前默认方法论`ENERGY-ESG-2025-COMPAT-v1`是**公开方法论兼容、计算过程透明的独立评价**，
不能声称与报告发布机构的官方分数完全一致。要按 DL/T 2971 出具正式级别并启用治理优秀值峰打分，
须填入优秀值表并冻结`DLT2971-2025-v1`。

```bash
# 1) 生成录入工作包（含国资委表头别名与映射风险）
PYTHONPATH=src python3 -m aegis_esg.cli prepare-governance-benchmark-packet \
  --csv data/methodologies/governance_benchmarks_template_2025.csv \
  --html output/audit/governance_benchmark_packet_v1_2025.html \
  --summary output/audit/governance_benchmark_packet_v1_2025.json
# 2) 审计当前方法论是否齐全
PYTHONPATH=src python3 -m aegis_esg.cli audit-governance-benchmarks \
  --output output/audit/governance_benchmark_audit.json
# 3) 注入并冻结正式方法论（17项齐全后才会写成DLT2971-2025-v1）
PYTHONPATH=src python3 -m aegis_esg.cli apply-governance-benchmarks \
  data/methodologies/governance_benchmarks_2025.csv \
  --output-methodology data/methodologies/energy_esg_dlt2971_v1.json \
  --summary output/audit/governance_benchmark_apply.json
```

## 双轨排名设计

系统按“一套证据底座、两套隔离算法、三级输出”建设：

- **自动预排名**：不需要人工参与，使用版本化的系统自有算法自动分析公开数据，输出覆盖率、
  可信等级和缺失策略敏感性；它是研究结果，不冒充客户正式榜单；
- **审核候选排名**：在预排名基础上优先审核可能改变名次的冲突、高权重和弱证据项目，用于观察
  前200边界是否稳定；
- **正式排名**：严格执行客户确认的固定公司池、指标、权重、缺失规则和定性档位，高风险判断完成
  单审、双审或仲裁后冻结发布。

自动预排名算法与正式方法论必须使用不同版本号。自动推断可以进入预排名，但未经正式策略授权或
审核不得进入正式排名。“满足客户需求”指实现客户确认的方法和交付格式，不调整算法迎合预期名次。

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

在应用任何确认动作前，可只读生成候选审核分层：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli plan-review-tiers \
  data/review/hkex_indicator_candidates_2026-07-29.csv \
  --output output/audit/hkex_candidate_review_tiers_2026-07-29.csv \
  --summary output/audit/hkex_candidate_review_tiers_summary_2026-07-29.json
```

该命令区分现行策略可自动确认、冲突强制签名、一致多候选抽查和单候选抽查，不修改候选状态。
当前`public-disclosure-v6`还要求新指标同时通过官方报告类型、严格证据前缀和置信度门槛。可将结果
输出到明确的预览文件，供正式批次冻结前核验：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli resolve-pending \
  data/review/hkex_indicator_candidates_2026-07-29.csv \
  --confirmed output/review/hkex_auto_confirmed_preview_2026-07-29.csv \
  --unresolved output/review/hkex_unresolved_preview_2026-07-29.csv \
  --decisions output/audit/hkex_auto_resolution_decisions_preview_2026-07-29.csv

PYTHONPATH=src python3 -m aegis_esg.cli audit-resolution-preview \
  data/review/hkex_indicator_candidates_2026-07-29.csv \
  output/review/hkex_auto_confirmed_preview_2026-07-29.csv \
  output/review/hkex_unresolved_preview_2026-07-29.csv \
  output/audit/hkex_auto_resolution_decisions_preview_2026-07-29.csv \
  --output output/audit/hkex_resolution_preview_freeze_audit_2026-07-29.json
```

冻结校验逐组核对候选、确认、未决和决策日志。当前批次结构有效，但仍有7组需人工审核，因而
`valid=true`、`freeze_ready=false`；预览不会进入正式评分数据。

可从冻结分层中精确生成7组人工队列及空白签名模板：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli select-manual-review \
  data/review/hkex_indicator_candidates_2026-07-29.csv \
  output/audit/hkex_candidate_review_tiers_2026-07-29.csv \
  --output data/review/hkex_manual_review_candidates_2026-07-29.csv

PYTHONPATH=src python3 -m aegis_esg.cli review-template \
  data/review/hkex_manual_review_candidates_2026-07-29.csv \
  --output data/review/hkex_manual_review_template_2026-07-29.csv
```

下载冲突复核模板并由审核人填写`action`（`confirm`或`reject`）、候选值、审核人、带时区时间和
理由后，可安全生成确认观测、剩余候选和独立审计：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli apply-conflict-review \
  data/review/hkex_indicator_candidates_2026-07-29.csv signed-review.csv \
  --confirmed output/review/confirmed.csv \
  --unresolved output/review/unresolved.csv \
  --audit output/review/audit.csv
```

定性复核在单签闭环之上增加三层治理门禁：

- 批次清单：`qualitative-review-batch`按优先级创建批次并登记组键/文件SHA-256清单，未关闭批次
  禁止重复分配；`apply-qualitative-batch`校验组键哈希、拒绝跨批覆盖和已签名组覆盖，自动更新
  批次完成率与open/closed状态；
- 双人复核：`select-dual-review`筛出重大主观判断（确认80/100分、偏离建议档或拒绝80档建议），
  `apply-dual-review`强制不同第二审核人闭合，分歧进入仲裁，`apply-qualitative-arbitration`
  由区别于两名审核人的仲裁人终裁；
- 合并门禁：`merge-confirmed-observations`仅在方法论指标、confirmed状态且同组值一致时合并，
  冲突直接拒绝；`reprioritize-qualitative-gaps`按优先级、指标权重和ESG报告状态重排证据缺口。

定性证据采集覆盖年报和独立ESG报告两个来源，`merge-qualitative-candidates`按公司/指标/文件/
页码/匹配词/证据精确去重后统一进入复核规划：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli collect-esg-qualitative-evidence \
  output/audit/all_markets_document_coverage_2025.csv \
  data/raw/all_markets_document_index.csv \
  --report-year 2025 \
  --output data/review/all_markets_esg_qualitative_evidence_candidates_2025.csv \
  --summary output/audit/all_markets_esg_qualitative_evidence_summary_2025.json
```

主要接口：

- `GET /health`
- `GET /api/v1/progress`
- `GET /api/v1/review-tiers`
- `GET /api/v1/resolution-freeze-audit`
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
5. 自动预排名按系统算法生成定性建议、缺失情景和可信等级；
6. 正式排名只接收正式策略允许的自动决定和已审核数据，高风险项进入单审、双审或仲裁；
7. 先生成研究版及敏感性报告，再根据预计排名影响安排审核；
8. 冻结输入Hash、算法/方法论版本、缺失策略、代码版本和样本统计参数；
9. 生成前200排名、指标下钻和异常诊断，并与历史结果做趋势回归而非拟合预期名次。

详细的生产数据规则见[数据流水线](docs/data-pipeline.md)，MySQL建表脚本见
[`sql/mysql/schema.sql`](sql/mysql/schema.sql)。

从当前状态推进到正式发布的里程碑、依赖和逐阶段验收标准见
[开发完成路线图](docs/development-plan.md)。项目进度以六道机器门禁为准，不以候选数量替代正式确认。
工程能力与正式发布差距的逐项状态见
[工程完工与正式发布差距审计](docs/engineering-completion-audit.md)。
可用`advance-stage`按门禁自动判定下一研发阶段：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli advance-stage \
  output/audit/project_completion_v16_2025.json \
  --output output/audit/stage_assessment_2025.json
```
外部输入是否到位可用`audit-external-readiness`统一检查，结果不会代替真实审核或签名。
自动续接可使用`auto-stage`一次刷新两类状态，适合接入CI或定时任务。
拟申请发明专利的核心技术方案、模块化申请方向、商业秘密边界和对照实验见
[发明专利技术方案与研发取证计划](docs/patent-strategy.md)。

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

采集侧已统一沪港199份正式文档索引，614家公司中105家已有2025年年报、71家已有ESG报告；
`discover-szse`可为257家深市候选批量发现官方年报和ESG报告。发现结果仍需下载、PDF验证和
SHA-256入索引后才计为已采集。

深市真实批次现已完成257/257份2025年年报，并通过独立通用公告通道发现73份ESG报告；其中
13份新增ESG正文已下载校验，60份因官方静态站限速保留在可重试队列。沪港深统一索引现包含
469份文件、374家公司，采集计划中84家已有独立ESG报告、81家可直接抽取。上一轮批量文本抽取
得到833条候选，全市场614×37定量矩阵已有793项候选。

北交所公告适配器已按官方年度报告分类完成26/26家真实发现和PDF哈希采集，失败0。并入后四市场
统一索引为495份文件、400家公司，388家公司已有2025年年报；重跑文本抽取后候选仍为833条，
说明本批北交所年报尚未产生符合严格证据规则的新定量候选。

上交所全量阶段已完成239/239家公司，239份年报和96份ESG报告全部下载校验、失败0。四市场统一
索引现为789份文件并覆盖614家公司，其中602家已有年报、164家已有独立ESG报告。补齐847份文本
缓存及港股当前年度人民币表格、跨行/双语英文财务主表和折叠利润表规则扩展后，严格候选增至
4,902条；A股中文环境绩效表严格解析（显式年份列表头、人民币收入分母、拒绝产值/人均/发电量
口径）再增27条至4,929条，对应4,440个公司指标任务；矩阵仍缺18,278项，关键缺口5,130项，
37项定量指标均已有候选。90家已有2025年年报的港股公司现已全部产生严格候选，港股子集为577条
候选、564组。自动策略预览确认4,364组，76组进入人工签名队列。

港股最后12家缺口已扩展扫描至2020—2026年，并按财年结束年度归一化。10家补齐2025年报；
`00702.HK`与`01101.HK`最新正式年报停在2023，继续作为真实缺失。目标年度统一索引现为794份，
612/614家有年报、164家有独立ESG报告。强制`--report-year 2025`并完成严格规则扩展后，
自动确认预览4,364组，76组需人工签名；冻结审计保持`valid=true`、`freeze_ready=false`。
