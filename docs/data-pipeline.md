# 公开数据采集、复核与年度评分流程

## 年份口径

榜单年份与数据报告期不是同一年。2025评价报告使用2024年1月1日至12月31日
的公开数据。因此系统执行规则为：

```text
评价年份 = 报告期年份 + 1
```

生成2026榜单时，应采集2025年年报、2025年可持续发展/ESG/社会责任报告及
报告期内处罚、事故等公开信息。

## 来源优先级

1. 交易所法定披露文件；
2. 巨潮资讯正式公告；
3. 公司投资者关系网站；
4. 政府处罚、事故和信用公开平台；
5. 经授权的结构化财务数据接口；
6. 新闻只作线索，不直接作为确认值。

不要依赖未公开接口或绕过验证码。下载器接受审核后的
`data/templates/document_manifest.csv`，每个文件保留公告原始URL、实际取件URL和
SHA-256。上交所主站返回验证页时，仅回退到其官方`big5.sse.com.cn`镜像；响应
必须通过PDF文件头和最小尺寸校验，HTML验证页不会进入原始文档库。

## 全市场公司池

四个交易所的原始名单先转换为标准快照字段：`stock_code`、`company_name`、
`exchange`、`industry`、`entity_id`、`st_status`、`listing_status`、
`energy_eligible`、`source_url`和`as_of_date`。模板位于
`data/templates/exchange_universe_snapshot.csv`。

交易所下载文件允许CSV、TSV或XLSX格式，中文/英文字段名由`normalize-snapshot`统一映射，
并自动补齐`.SH`、`.SZ`、`.BJ`或`.HK`后缀。XLSX支持需要安装`universe`可选依赖。

```bash
PYTHONPATH=src python3 -m aegis_esg.cli normalize-snapshot raw/bse.xlsx \
  --exchange BSE --source-url https://www.bse.cn/nq/listedcompany.html \
  --as-of-date 2026-07-28 --output data/snapshots/bse.csv \
  --quality output/audit/bse_snapshot_quality.json
```

标准化时同步输出质量报告；只要数据为空，或者存在缺失/非法来源URL、非ISO快照日期、
主体标识缺失、未知交易所或重复证券代码，快照即判定无效并返回非零退出码。

对于提供公开分页JSON接口的交易所，可使用`discover-listings`直接采集。URL模板必须包含
`{page}`；采集器校验JSON结构、返回页码、总页数、总记录数和代码唯一性。分页期间总数变化、
漏页、重复记录或HTML验证页都会使整次任务失败。

```bash
PYTHONPATH=src python3 -m aegis_esg.cli discover-listings \
  --exchange SZSE --endpoint-template 'https://official.example/api?page={page}' \
  --referer https://www.szse.cn/market/stock/company/ --as-of-date 2026-07-28 \
  --output data/snapshots/szse.csv --quality output/audit/szse_snapshot_quality.json
```

接口URL只有在交易所页面实际请求验证通过后才能写入生产任务，不得使用第三方行情接口替代
官方公司范围底表。

若运行环境限制Python网络访问，可先用`curl`保存官方单页完整JSON，再使用
`import-listing-json`离线标准化。该路径会保留原始响应，适合正式审计归档。

`energy_eligible`是经过行业映射复核后的显式结论。为空时仅接受已配置的能源细分行业；
未分类或非能源行业进入排除审计，不凭公司名称猜测。系统依次执行上市状态检查、
ST/*ST排除、行业映射和同主体多地上市去重。A/H重复时固定优先保留A股，结果不受输入顺序影响。

```bash
PYTHONPATH=src python3 -m aegis_esg.cli build-universe \
  data/snapshots/sse.csv data/snapshots/szse.csv \
  data/snapshots/bse.csv data/snapshots/hkex.csv \
  --output data/universe/energy_full_2026.csv \
  --audit output/audit/energy_full_2026_decisions.csv
```

正式底表的每一行必须保留交易所来源URL和快照日期，行业人工调整通过更新标准快照中的
`energy_eligible`完成，不能直接修改最终公司池而绕过审计。
`universe-audit`还会阻止以下情况进入正式发布：纳入行缺失`entity_id`、来源URL或快照日期，
同一主体被重复纳入，排除行没有理由，以及纳入行仍带有排除理由。上述问题均在审计JSON中
输出独立计数，不能仅靠主体总数达到632而绕过证据质量门槛。

历史迁移候选通过证券代码精确绑定四交易所官方快照，不允许名称模糊匹配：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli bind-universe-provenance \
  data/universe/energy_historical_candidates_2026.csv \
  --snapshot data/snapshots/all_exchanges_2026-07-29.csv \
  --output data/universe/energy_historical_candidates_2026.csv \
  --audit output/audit/historical_candidate_provenance_binding.csv \
  --summary output/audit/historical_candidate_provenance_binding.json
```

命令只填补空来源、日期和主体字段，已有纳入证据不会被覆盖；名称差异、主体冲突和未匹配项
均保留逐证券记录。已排除的退市证券允许保持未匹配，但任何纳入证券未匹配都会返回非零状态。

行业纳入证据和A/H主体关系使用独立任务队列推进：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli plan-universe-evidence \
  data/universe/energy_historical_candidates_2026.csv \
  --snapshot data/snapshots/all_exchanges_2026-07-29.csv \
  --output output/audit/historical_candidate_universe_evidence_tasks.csv \
  --summary output/audit/historical_candidate_universe_evidence_summary.json
```

任何包含“待分类”或“待…复核”的细分行业均计入`unclassified_count`并阻止发布。任务队列优先
处理港股中文全称及行业证据，再处理内地能源细分行业，已明确行业的证券继续核验主体关系。

复核人员按`data/templates/universe_evidence_decisions.csv`填写签名决定后应用：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli apply-universe-evidence \
  data/universe/energy_historical_candidates_2026.csv signed-decisions.csv \
  --output data/universe/energy_reviewed_2026.csv \
  --audit output/audit/energy_reviewed_decisions.csv \
  --summary output/audit/energy_reviewed_summary.json
```

纳入决定必须提供非占位细分行业、证据URL或仓库证据路径、证据日期、审核人、带时区审核时间
和理由。主体映射只有在同一A/H组合的全部证券同时签名时才生效，并固定优先保留A股；非A/H
重复主体、只审核组合中的一只证券或任何字段缺失都会使整批失败，不产生部分写入。

多人或多轮审核使用`data/templates/universe_evidence_batch.csv`形成不可变批次，再生成当前有效决定：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli merge-universe-evidence batch-01.csv batch-02.csv \
  --active-output output/review/universe_evidence_active.csv \
  --ledger-output output/audit/universe_evidence_ledger.csv \
  --summary output/audit/universe_evidence_ledger.json
```

每个决定和批次必须有唯一ID。首次决定使用`operation=upsert`且`supersedes`为空；更正决定必须
准确指向同证券当前决定；撤销使用`operation=revoke`并指向当前决定。版本分叉、重复批次、跨证券
替换和撤销旧版本都会整批失败。账本保留`active/superseded/revoked`状态，活动投影可直接交给
`apply-universe-evidence`。港股首批任务已生成在`output/audit/hkex_universe_evidence_tasks.csv`。

港股中文名称、公司简介和行业候选证据来自港交所股票报价页自身调用的官方JSONP接口：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli discover-hkex-profiles \
  data/universe/energy_historical_candidates_2026.csv \
  --output data/reference/hkex_issuer_profiles_2026-07-29.csv \
  --raw-output data/snapshots/raw/hkex_issuer_profiles_2026-07-29.json
```

适配器从官方报价页提取动态访问令牌，逐证券校验返回代码，并保存中文全称、简介、恒生行业/
子行业、上市类别、资料更新时间及原始响应。网络客户端遇到港交所对Python请求的403时使用无shell
参数的`curl`回退。上述92条资料全部完整，但仍只是审核候选，不会自动生成审核人签名或修改公司池。

使用版本化精确行业映射生成未签名审核草案：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli prepare-hkex-evidence-review \
  data/reference/hkex_issuer_profiles_2026-07-29.csv \
  --universe data/universe/energy_historical_candidates_2026.csv \
  --evidence-date 2026-07-29 \
  --output data/review/hkex_universe_evidence_draft_2026-07-29.csv \
  --summary output/audit/hkex_universe_evidence_draft_summary_2026-07-29.json
```

映射由`data/methodologies/hkex_energy_industry_mapping_2026.json`版本控制，只接受恒生子行业完全
一致匹配。当前88家生成行业建议，4家进入人工复核；草案故意保留审核人和审核时间为空，不能
直接进入证据账本。人工复核项包括东北电气H股，以及当前行业为半导体、环保工程或半导体设备
的3家公司；证券代码可能跨年度对应不同发行人，因此不得仅凭历史代码沿用纳入结论。

## 外部企业名录对账

业务方或用户提供的企业名录使用`reconcile-registry`与交易所标准快照核对。输入至少包含
证券代码或公司名称，推荐同时提供两者；模板为`data/templates/company_registry.csv`。

```bash
PYTHONPATH=src python3 -m aegis_esg.cli reconcile-registry incoming/companies.csv \
  --snapshot data/snapshots/mainland_sse_szse_2026-07-28.csv \
  --source-name 用户提供名录 --source-url https://example/source \
  --as-of-date 2026-07-28 --output output/audit/company_registry_reconciliation.csv
```

对账状态包括：`matched`为代码精确或规范名称唯一匹配；`review`为代码与名称冲突；
`ambiguous`为规范名称对应多个证券；`unmatched`为交易所底表未找到。只要存在后三种状态，
命令返回非零退出码，任何记录都不会自动写入正式632家公司池。公司名称规范化仅处理空格、
全半角括号以及“集团/股份有限公司”等组织形式后缀，不做模糊相似度猜测。

## 抽取状态机

```text
采集 → 自动抽取(pending) → 单位/公式校验 → 人工复核
                                      ├─ confirmed
                                      └─ rejected/重新抽取
```

零值、缺失和不适用必须分开：

- `confirmed + 0`：报告明确披露数值为零；
- `missing`：应披露但没有可确认数据；
- `not_applicable`：经复核确认该指标不适用于公司；
- `pending`：已抽取但尚未确认。

当前兼容方法论对没有确认值的指标计0分，既体现表现也体现披露质量。若业务方
决定对“不适用”重新归一权重，必须发布新方法论版本，不能修改历史批次。

## 单位归一

数据库保留原值、原单位和换算值。计算前统一为指标配置中的单位：

- 温室气体：千克CO2e；
- 标准煤：千克；
- NOx/SO2/颗粒物：克；
- 水和固废：千克；
- 财务金额：万元；
- 比率：百分数值，例如`5.2`表示5.2%，而不是`0.052`。

分母为零、负数或口径无法确认时不得自动生成强度值，应进入复核队列。

## 正态评分与复现

每个定量指标使用当年全部`confirmed`值形成样本：

1. 样本数不少于20时做1%/99%缩尾；
2. 记录样本数量、均值和总体标准差；
3. 正向指标使用`100 × Φ(z)`；
4. 负向指标使用`100 × (1-Φ(z))`；
5. 标准差为零时统一记50分；
6. 指标得分乘该指标权重形成贡献分值。

治理指标在获得当年国资委工业领域优秀值后，应配置`benchmark`。达到优秀值的
单向指标取满分，未达到部分按标准差距离衰减；双向指标以优秀值为峰值向两侧
衰减。没有优秀值时，当前版本使用当年样本中心，输出必须标注为独立估计。

## 定性指标

自动文本匹配只产生建议档位，不能直接确认。复核员依据报告标准选择：

- 100：描述完整、制度目标合理、措施有效、年度目标完成、行业领先；
- 80：描述具体、制度目标清晰、基本完成、行业优秀；
- 50：披露一般、措施和完成效果一般；
- 20：描述差、目标模糊或未完成；
- 0：没有有效证据。

每个定性结果必须保存证据原文、页码、复核人和复核时间。

## 发布门槛

- 公司范围和报告期已冻结；
- 所有输入有来源或明确缺失状态；
- 高权重指标低置信度记录已清零；
- 权重分别满足定量100、定性100；
- 总分等于`0.8×定量+0.2×定性`；
- 同分采用密集排名，结果类似`19,19,20`；
- 随机抽取至少10家公司完成从榜单到PDF页码的反向核验；
- MySQL备份和OSS对象版本已冻结。
