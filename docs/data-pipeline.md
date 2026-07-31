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

历史港股与当前发行人身份使用独立连续性审计：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli audit-hkex-issuer-continuity \
  data/reference/2024_energy_company_registry.csv \
  --profiles data/reference/hkex_issuer_profiles_2026-07-29.csv \
  --drafts data/review/hkex_universe_evidence_draft_2026-07-29.csv \
  --code-map data/reference/historical_stock_code_resolutions.csv \
  --output output/audit/hkex_issuer_continuity_review_2026-07-29.csv \
  --summary output/audit/hkex_issuer_continuity_summary_2026-07-29.json
```

审计仅进行组织形式和H股后缀清理后的字符级比较，不执行简繁转换或相似度归并。当前15家公司
全称一致、8家公司简称一致、1家公司由官方签名代码解析确认，另68家公司需要名称连续性证据；
9条名称带H股线索进入A/H复核。名称差异不等同发行人变化，必须结合公告或年报判断。

发行人连续性和A/H关系由审核人按`data/templates/hkex_issuer_continuity_decisions.csv`签名后应用：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli apply-hkex-continuity-decisions \
  data/universe/energy_historical_candidates_2026.csv signed-continuity.csv \
  --continuity-audit output/audit/hkex_issuer_continuity_review_2026-07-29.csv \
  --output data/universe/energy_after_hkex_continuity_2026.csv \
  --audit output/audit/hkex_continuity_applied.csv \
  --summary output/audit/hkex_continuity_applied.json
```

`outcome`只接受`same_issuer`、`new_issuer`和`ah_same_entity`。`new_issuer`会排除仅依赖历史样本
沿用的当前证券；若当前发行人仍应按能源范围纳入，必须作为新候选重新提供行业证据。
`ah_same_entity`必须提供当前已纳入的沪深北证券代码和独立主体标识，系统固定保留A股并排除H股。
未覆盖的复核项保留在摘要中，只有全部必审项签名后`complete`才为true。

在签名决定前，可从连续性审计生成官方证据采集任务队列：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli plan-hkex-continuity-evidence \
  output/audit/hkex_issuer_continuity_review_2026-07-29.csv \
  --output output/audit/hkex_continuity_evidence_tasks_2026-07-29.csv \
  --summary output/audit/hkex_continuity_evidence_task_summary_2026-07-29.json
```

任务生成器跳过已完成字符级核验的证券，拒绝未知操作和重复代码，并按身份/行业复核、名称连续性、
A/H关系顺序保留审计优先级。当前92条审计生成70项待采集任务：4项身份与行业联合复核、64项名称
连续性核验、2项A/H关系核验；每项明确所需官方文件、历史与当前名称检索词及已有港交所资料URL。
任务始终保持`pending`，不会把检索建议冒充证据或审核结论。

高优先任务可从HKEXnews公开标题检索发现官方文件：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli discover-hkex-continuity-documents \
  output/audit/hkex_continuity_evidence_tasks_2026-07-29.csv \
  --from-date 2025-01-01 --to-date 2026-07-29 --limit 4 \
  --output data/manifests/hkex_continuity_priority_2026-07-29.csv \
  --raw-output data/snapshots/raw/hkex_continuity_priority_2026-07-29.json
```

适配器先按证券代码精确解析HKEXnews `stockId`，再查询公告标题；逐行校验返回证券代码，并核对
页面总记录数。单次结果超过页面上限时自动二分日期区间，直到每段完整，再按官方文件URL去重。
只保留年报、ESG报告、上市文件及更名公告；年报发布通知函不会误作年报。首批4个高优先案例
已发现12份候选文件并保存原始响应，其中00600.HK包含2025年报和新发行人的上市文件。

发现结果先收敛为不会覆盖的下载清单，再使用通用断点下载器：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli prepare-hkex-continuity-downloads \
  data/manifests/hkex_continuity_priority_2026-07-29.csv \
  --output data/manifests/hkex_continuity_priority_downloads_2026-07-29.csv \
  --summary output/audit/hkex_continuity_priority_download_summary_2026-07-29.json

PYTHONPATH=src python3 -m aegis_esg.cli extract-hkex-continuity-evidence \
  data/raw/hkex_continuity_document_index.csv --text-root data/text \
  --output data/review/hkex_continuity_priority_evidence_candidates_2026-07-29.csv \
  --summary output/audit/hkex_continuity_priority_evidence_summary_2026-07-29.json
```

收敛器按公司和文件类型选择最新文件，正式上市文件优先于形式通知，并拒绝目标路径冲突。
首批选择7份文件（4份年报、2份ESG报告、1份上市文件），全部下载成功且保存SHA-256。
1,655页文本生成40条待复核证据：发行人沿革2条、主营业务26条、A/H身份线索12条；主营业务
覆盖4/4，明确A/H术语覆盖2/4家公司。候选均保留文件、URL、页码和片段，`applicable=false`，
不能替代审核签名。A/H规则区分大写证券术语，避免把英文冠词`a share`误作A股。

候选证据使用稳定`candidate_id`汇总为未签名人工复核包：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli prepare-hkex-continuity-review \
  output/audit/hkex_continuity_evidence_tasks_2026-07-29.csv \
  data/review/hkex_continuity_priority_evidence_candidates_2026-07-29.csv \
  --output data/review/hkex_continuity_priority_review_packet_2026-07-29.csv \
  --summary output/audit/hkex_continuity_priority_review_packet_summary_2026-07-29.json
```

每家公司一行，分别列出发行人沿革、主营业务和A/H身份候选ID及页码。`outcome`、关联A股代码、
主体标识、证据URL、审核人和审核时间均为空，`review_status=unsigned`；审核人必须选择候选ID并
补齐签名信息后，才能转换为连续性决定。当前生成4个高优先复核包，其余66项仍在采集队列。
签名决定模板已移除示例数据，只保留表头，避免示例被误当真实审核决定。

审核人填完复核包后，必须先通过严格转换器：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli finalize-hkex-continuity-review \
  signed-review-packet.csv \
  data/review/hkex_continuity_priority_evidence_candidates_2026-07-29.csv \
  --output signed-continuity-decisions.csv \
  --audit output/audit/hkex_continuity_finalized_audit.csv \
  --summary output/audit/hkex_continuity_finalized_summary.json
```

转换器要求`review_status=signed`，并校验决定ID、结论、审核人、理由、ISO证据日期和带时区审核时间。
`selected_candidate_ids`必须全部属于同一证券，`evidence_url`必须来自所选候选；A/H同主体结论还
必须选择A/H身份候选并填写A股代码和独立主体标识。非A/H结论禁止携带主体映射字段。输出格式
可直接交给`apply-hkex-continuity-decisions`，同时生成候选选择审计。当前真实复核包仍未签名，
转换命令会在第一个未签名行立即拒绝，不产生可应用决定。

全量连续性文件发现支持逐证券检查点和失败恢复：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli discover-hkex-continuity-documents \
  output/audit/hkex_continuity_evidence_tasks_2026-07-29.csv \
  --from-date 2025-01-01 --to-date 2026-07-29 --delay 0.2 --resume \
  --output data/manifests/hkex_continuity_all_2026-07-29.csv \
  --raw-output data/snapshots/raw/hkex_continuity_all_2026-07-29.json.gz \
  --failures output/audit/hkex_continuity_all_failures_2026-07-29.csv
```

命令在每个证券完成后写入发现清单、原始响应和失败表；`--resume`按原始检查点跳过成功证券，
只重试失败或未处理项。`.json.gz`检查点可直接读写，避免原始HTML膨胀仓库。70项任务已全部完成，
失败0，共发现252份相关文件，68家公司有候选、2家公司在该时间窗内无匹配文件。无冲突收敛后
得到118份下载目标：68份年报、45份ESG报告、3份上市文件和2份更名公告。

下载清单支持断点续传、PDF签名校验、SHA-256索引和独立失败表：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli collect \
  data/manifests/hkex_continuity_all_downloads_2026-07-29.csv \
  --output-root data/raw \
  --index data/raw/hkex_continuity_all_document_index.csv \
  --failures data/raw/hkex_continuity_all_collection_failures.csv \
  --delay 0.2 --resume
```

北交所使用官网公告分类字典中的年度报告父类`9504-0100`和子类`9503-1001`查询，严格排除摘要、
更正、问询及回复。真实批次26/26家均发现并下载正式2025年报，失败0：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli discover-bse \
  data/universe/energy_historical_candidates_2026.csv --report-year 2025 \
  --output data/manifests/bse_candidates_2025.csv \
  --failures output/audit/bse_discovery_failures_2025.csv
```

四市场合并索引现有495份文件、400家公司，采集矩阵中388家公司已有年报。

上交所全量批次完成239/239家公司，发现239份正式年报和96份独立ESG报告，下载及哈希校验失败0。
四市场统一索引扩大到789份文件并覆盖全部614家公司；602家已有年报、164家已有独立ESG报告。
Swift批处理默认跳过已有文本，本轮增量文本化847份、跳过317份、失败0。港股当前年度人民币
表格、跨行/双语英文财务主表及折叠利润表规则扩展后，全量重抽得到4,902条候选；A股中文环境
绩效表严格解析（当前年优先/靠后/单年三种显式年份表头、行尾年份变体、人民币收入分母、
拒绝产值/发电量口径）新增27条至4,929条，对应4,440个候选任务，剩余18,278项缺失，其中
5,130项为关键指标缺口；4,364组可按策略自动确认，76组需人工
签名，37项定量指标均已有真实候选。90家已有目标年度年报的港股公司实现公司级候选全覆盖，
对应577条候选和564个港股公司指标任务。

港股剩余12家使用2020—2026扩展窗口重新发现，并将`2024/25`等非自然财年归属于结束年度；无年份
年报按发布日期前一年归属。`--report-year 2025 --annual-only`只选择目标年报，避免最新2026财年
或连续性文件混入评价索引。10家补齐，`00702.HK`和`01101.HK`最新年报仍为2023，明确保留缺失。
同URL元数据更正只在公司、文档类型、SHA-256和大小完全一致时允许。最终索引794份，612家有年报、
164家有独立ESG；年度过滤和规则扩展后的当前结果以上述全量重抽审计为准。

本批118份文件已全部下载且失败0。PDFKit文本化后，以下载索引生成带页码证据候选和审阅包：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli extract-hkex-continuity-evidence \
  data/raw/hkex_continuity_all_document_index.csv --text-root data/text \
  --max-per-category 5 \
  --output data/review/hkex_continuity_all_evidence_candidates_2026-07-29.csv \
  --summary output/audit/hkex_continuity_all_evidence_summary_2026-07-29.json

PYTHONPATH=src python3 -m aegis_esg.cli prepare-hkex-continuity-review \
  output/audit/hkex_continuity_evidence_tasks_2026-07-29.csv \
  data/review/hkex_continuity_all_evidence_candidates_2026-07-29.csv \
  --output data/review/hkex_continuity_all_review_packet_2026-07-29.csv \
  --summary output/audit/hkex_continuity_all_review_packet_summary_2026-07-29.json
```

结果为431条候选：主营业务348条、A/H身份72条、发行人历史11条；68家公司形成未签名审阅包，
`00702.HK`和`01101.HK`在时间窗内无文件候选。候选只用于人工审核，不能直接应用到公司池。

为避免审核人反复在复核包与候选表之间查找，可生成只读Markdown审阅手册：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli render-hkex-continuity-review \
  data/review/hkex_continuity_all_review_packet_2026-07-29.csv \
  data/review/hkex_continuity_all_evidence_candidates_2026-07-29.csv \
  --output data/review/hkex_continuity_all_review_guide_2026-07-29.md \
  --summary output/audit/hkex_continuity_all_review_guide_summary_2026-07-29.json
```

手册按优先级和证券代码排列，逐候选展示官方文件、报告期、页码、置信度及证据原文。它不会填写
`outcome`、选择候选或生成签名；审核结果仍必须回填CSV复核包并通过严格转换器校验。

审阅可以按最高优先级切分为独立批次，避免一次编辑全部68行：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli select-hkex-continuity-review-batch \
  data/review/hkex_continuity_all_review_packet_2026-07-29.csv \
  data/review/hkex_continuity_all_evidence_candidates_2026-07-29.csv \
  --max-priority 0 \
  --output-packets data/review/hkex_continuity_p0_review_packet_2026-07-29.csv \
  --output-candidates data/review/hkex_continuity_p0_evidence_candidates_2026-07-29.csv \
  --summary output/audit/hkex_continuity_p0_review_batch_summary_2026-07-29.json
```

P0批次包含`00042.HK`、`00600.HK`、`00607.HK`和`00650.HK`共4个复核包、40条候选。
切分器保留原始字段和未签名状态；审核完成后，可将该批次直接传给`finalize-hkex-continuity-review`。

原2025—2026时间窗无候选的`00702.HK`和`01101.HK`，扩展到2020—2026年后发现15份官方文件，
无冲突选择并下载2份2023年年报和1份ESG报告。多个断点下载索引通过严格合并命令统一：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli merge-document-indexes \
  data/raw/hkex_continuity_all_document_index.csv \
  data/raw/hkex_continuity_missing_document_index.csv \
  --output data/raw/hkex_continuity_complete_document_index.csv \
  --summary output/audit/hkex_continuity_complete_document_index_summary_2026-07-29.json
```

合并器按官方URL去除完全一致的重复项，并拒绝URL元数据冲突或本地路径冲突。统一索引包含121份
文件和70家公司；重新抽取后形成440条候选及70个审阅包，`codes_without_candidates=[]`。

评价报告采集另将沪市试点与港股正式报告索引合并为`data/raw/all_markets_document_index.csv`，
共199份文件、117家公司且冲突为0。重建614家公司计划后，105家已有年报、71家已有ESG报告。
深市257家候选可使用`discover-szse`批量生成官方报告清单，摘要不会进入下载队列。
真实运行已完成257/257家年报，并通过通用公告分页通道发现73份独立ESG报告。13份新增ESG正文
已下载校验，60份因官方静态站限速进入可重试失败队列；沪港深索引扩大到469份文件、374家公司。
上一轮456份文件批量文本生成833条候选。全市场矩阵按`included=true`的614家公司展开，排除
25条迁移否决项。

深交所静态站限速或验证页解除后，可直接把失败CSV作为增量清单重试；`--preserve-index`保证只更新
成功重试项，不会覆盖主索引中已有的270份文档，PDF超时分片则按URL哈希从系统临时目录续传：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli collect \
  output/audit/szse_collection_failures_2025.csv \
  --output-root data/raw --index data/raw/szse_document_index.csv \
  --failures output/audit/szse_collection_failures_2025.csv \
  --resume --preserve-index --workers 1 --delay 1
```

全部92家港股候选可直接使用发行人资料表执行同一官方发现适配器。2025-01-01至2026-07-29
时间窗共发现332份文件，收敛为155份目标并全部下载；原始PDF保存在隔离目录
`data/raw/hkex_reports/`，避免覆盖连续性审计所引用的文件。采集器只有在来源URL、本地路径、
SHA-256和文件大小均与断点索引一致时才复用文件，禁止把旧路径静默绑定到新URL。

合并扩展时间窗的3份文件后，使用覆盖审计命令生成逐公司状态：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli audit-document-coverage \
  data/reference/hkex_issuer_profiles_2026-07-29.csv \
  data/raw/hkex_reports_complete_document_index.csv \
  --output output/audit/hkex_reports_complete_coverage_2026-07-29.csv \
  --summary output/audit/hkex_reports_complete_coverage_summary_2026-07-29.json
```

当前年报覆盖92/92，独立ESG报告覆盖59/92；其余33家公司标记为`scan_annual_for_esg`，必须扫描
年报相关章节并明确记录独立报告缺失，不能把“无独立ESG报告”误记为“无ESG披露”。

PDF按页文本化后，可只扫描覆盖审计标记的33家公司：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli scan-annual-esg-disclosure \
  output/audit/hkex_reports_complete_coverage_2026-07-29.csv \
  data/raw/hkex_reports_complete_document_index.csv \
  --text-root data/text --max-per-company 5 \
  --output data/review/hkex_annual_esg_disclosure_candidates_2026-07-29.csv \
  --summary output/audit/hkex_annual_esg_disclosure_summary_2026-07-29.json
```

当前生成165条带页码候选，33/33家公司有命中且文本缺失0。命中只用于定位年报中的ESG相关
章节，状态固定为`pending`、`applicable=false`；不得据此自动认定披露完整或直接产生指标得分。

港股文本使用现有中文定量规则的基线结果为0。英文规则首批仅支持合并资产负债表资产负债率：
必须在`Consolidated Statement of Financial Position`或`Consolidated Balance Sheet`页面范围内同时
找到`Total assets`和`Total liabilities`，按负债/资产派生；`gearing ratio`等不同口径不得替代。

```bash
PYTHONPATH=src python3 -m aegis_esg.cli extract-batch-text \
  data/raw/hkex_reports_complete_document_index.csv data/text \
  --output data/review/hkex_indicator_candidates_2026-07-29.csv \
  --coverage output/audit/hkex_indicator_candidates_coverage_2026-07-29.json \
  --review-summary data/review/hkex_indicator_candidates_review_2026-07-29.csv
```

英文合并损益表还支持以`Revenue`两期值派生营业收入增长率，以明确的`Operating profit`或
`Profit from operations`派生营业利润率及增长率；与资产负债表两期值组合派生总资产周转率、
流动资产周转率和资本积累率。报表项目必须恰好得到两期数值，或“1个小整数附注号+2期数值”；
单期缺失、污染多列和疑似附注号加单值均拒绝。同一报告存在多个同名报表区间时，选择可派生指标
最完整的区间。英文环境强度规则还支持“标准煤/人民币营收”和“水量/人民币营收”的明确口径，
统一换算为方法论的千克/万元；温室气体强度另支持人民币万元、百万元及亿元分母。人均、面积、
发电量、美元营收和目标值口径不采纳。NOx和一般固体废物强度也仅接受明确人民币营收分母，
其中NOx统一换算为克/万元。研发费用占比支持明确英文直接披露，以及同一合并损益表内研发费用/
营业收入派生。现金分红仅接受人民币全年每股股息，拒绝港元及仅中期、末期或建议派息口径。
安全生产投入占比另支持明确英文“占营业收入比例”表格。英文合并资产负债表还严格派生应收账款
周转率、两金占比和速动比率，分别覆盖14、6、19家公司；混合口径`Trade and other receivables`
不作为应收账款。英文合并现金流量表以经营活动现金流量净额/流动负债派生经营现金流负债比，
覆盖14家公司；销售现金实现率只接受直接法主表的客户现金收入，当前无合规命中。英文全年利润
与两期总权益另派生净资产收益率，覆盖32家公司；税前利润与融资成本派生利息保障倍数，并在
具备两期总资产时派生总资产报酬率，分别覆盖42、12家公司。EBITDA利润率要求净利润、所得税、
融资成本、合并折旧摊销和营收五项主表要素完整，分拆且无法证明完整的折旧/摊销行不自动相加，
覆盖4家公司。英文温室气体减排率仅接受页面明确按本期、上期排列且口径一致的总量行，覆盖7家。
SO₂、颗粒物、废水和危废强度另统一要求人民币营收分母，拒绝产量、晶圆和原油桶口径；真实新增
废水1家、危废4家、SO₂ 1家及颗粒物2家。替代水资源利用率仅接受0%—100%的明确再生水
占比，拒绝循环水利用率，`03337.HK`两页一致披露8.53%。清洁能源强度仅接受标准煤/人民币营收；
`02688.HK`以同页当前年度可再生能源、综合能源及收入强度闭环派生0.218081042751千克标准煤/万元，
不使用生产量或港币分母。环保投入占比命中`01250.HK`的0.18%和`01798.HK`的0.56%。公益捐赠占比仅接受明确营收比例，
命中`03337.HK`的0.03%；单独捐赠金额和公式说明不采纳。员工薪酬仅从同页同集团的本期员工数
和人民币员工成本派生，拒绝港币及跨期拼接，覆盖3家公司。成本费用率只使用同一合并损益表的
完整费用合计，不以销售成本替代，命中`01811.HK`的71.60%。员工福利及教育经费仅在集团人数、
人民币附注和“本期增加额”表头闭环时派生，命中`01713.HK`。中文口径下员工薪酬、福利社保
公积金及工会教育经费的人均派生仅读取合并财务报表项目注释内的应付职工薪酬-短期薪酬列示：
列头与数据行同页（表头恰在页尾时仅绑定紧接下一页，带状分列布局拒绝跨块拼接），每行按
“期末=期初+增加-减少”会计恒等式定位“本期增加”列，三值/两值行须以同页游离年末余额列
精确佐证；员工数取报告期末在职合计（母公司+子公司交叉校验）或北交所员工总计期末人数，
双栏PDF水平三列表仅以母公司+子公司=合计恒等三元组加专业构成合计佐证采信，单位以表内
“单位：元/万元”或附注起首声明为准，人均值超出合理区间即拒绝。安全生产投入占比另兼容带脚注号的
`Safety Production Investment`倒装标签，新增`01250.HK`的1.77%。英文中国会计准则主表支持
`I. (Total) Operating revenue`及直接法客户销售收款，首次覆盖销售现金实现率，并补齐两家公司
的周转类指标；罗马序号及`Total operating cost`变体进一步补齐收入增长、营业利润率/增长率、
研发及成本费用率。当前生成435条候选，覆盖17项治理、11项环境和8项社会指标；`00600.HK`附录PDF列顺序、
`00196.HK`研发投入/费用口径及`01205.HK`两页温室气体总量微差产生三组冲突候选，必须人工复核；其余观测也保持
`pending`，确认后才可进入评分数据，负净资产案例不自动截断。

候选抽取后生成完整的公司×定量指标覆盖矩阵，避免只按已有候选观察进度：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli plan-candidate-coverage \
  data/reference/hkex_issuer_profiles_2026-07-29.csv \
  data/review/hkex_indicator_candidates_2026-07-29.csv \
  --output output/audit/hkex_quantitative_candidate_tasks_2026-07-29.csv \
  --summary output/audit/hkex_quantitative_candidate_tasks_summary_2026-07-29.json
```

历史港股专项矩阵曾为92×37=3,404项、422项有候选；当前生产进度统一以614家公司全市场矩阵为准：
4,440项已有待审候选，18,278项仍需扩展抽取规则，其中5,130项为关键
指标缺口。任务按“缺失关键指标、已有关键候选、缺失普通指标、已有普通候选”排序；矩阵
`applicable=false`，不会把候选误作确认数据。零覆盖指标已降至0。

候选审核前先生成只读分层，避免将“可按既定策略自动确认”和“必须签名”混在同一队列：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli plan-review-tiers \
  data/review/hkex_indicator_candidates_2026-07-29.csv \
  --output output/audit/hkex_candidate_review_tiers_2026-07-29.csv \
  --summary output/audit/hkex_candidate_review_tiers_summary_2026-07-29.json
```

`public-disclosure-v4`对新增指标同时校验指标代码、官方报告类型、稳定证据前缀和置信度。当前422组
候选分为415组可自动确认、3组冲突强制人工签名、1组一致多候选抽查和3组单候选抽查。该计划
`applicable=false`，只描述下一动作。`resolve-pending`预览生成415条确认、12条未决候选和422条
决策审计，文件名明确包含`preview`，不覆盖原始候选或正式评分数据。
`audit-resolution-preview`会按公司、报告期和指标逐组闭合候选、确认、未决及决策日志，并检查
策略版本、候选计数、原始选值和自动确认标记。当前真实批次422组/435条候选校验有效，415组
自动确认、7组人工审核，故`valid=true`但`freeze_ready=false`。看板和`/api/v1/review-tiers`
同步展示审核分层摘要及7组人工项；`/api/v1/resolution-freeze-audit`提供同源发布门禁状态。
`select-manual-review`严格要求分层与全部候选组一一对应，并核验每组候选计数；真实队列筛出
12条候选、7个审核组，再由`review-template`生成空白签名模板，避免对415个自动策略组重复审核。

冲突候选可从本地看板下载未签名模板。审核人只能选择候选中已有值执行`confirm`，或用`reject`
关闭全部不适用口径；两种动作都必须填写审核人、理由及带时区ISO-8601时间。使用
`apply-conflict-review`后分别输出确认观测、未处理候选和不可变审计CSV，不直接覆盖原候选文件。

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

全量年报的证据定位可通过以下命令生成。该命令覆盖方法论中的全部43项定性指标，保存原始文件、
URL、页码、匹配词和上下文，但所有记录保持`pending`，并在汇总中明确
`scoring_authorized=false`：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli collect-annual-qualitative-evidence \
  output/audit/all_markets_document_coverage_2025.csv \
  data/raw/all_markets_document_index.csv --report-year 2025 \
  --text-root data/text --max-per-indicator 3 \
  --output data/review/all_markets_annual_qualitative_evidence_candidates_2025.csv \
  --summary output/audit/all_markets_annual_qualitative_evidence_summary_2025.json
```

PDF文本中的NUL字符在证据写入前清除，确保CSV可被标准解析器读取。关键词命中仅说明存在待复核
证据，不等于满足任何评分档位，也不能直接写入正式观测表。

候选去重、四类上下文特征和缺口队列通过以下命令生成：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli plan-qualitative-review \
  data/review/all_markets_annual_qualitative_evidence_candidates_2025.csv \
  output/audit/all_markets_document_coverage_2025.csv --report-year 2025 \
  --packets data/review/all_markets_qualitative_review_packets_2025.csv \
  --gaps output/audit/all_markets_qualitative_evidence_gaps_2025.csv \
  --summary output/audit/all_markets_qualitative_review_plan_summary_2025.json
```

建议档位最高为80分；100分必须由复核员依据完整性、效果和行业领先证据主动判定。建议档位、
质量等级及优先级都不改变`pending`状态，汇总中的自动确认数必须保持0。

定性复核必须通过签名模板闭环，不允许直接编辑正式观测表。以下命令生成优先级1的首批500组
空白模板；它不会预填动作、最终分值、审核人或时间：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli qualitative-review-template \
  data/review/all_markets_qualitative_review_packets_2025.csv \
  --priority 1 --limit 500 \
  --output data/review/all_markets_qualitative_review_batch01_2025.csv
```

审核完成后使用`apply-qualitative-review`校验并应用决定：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli apply-qualitative-review \
  data/review/all_markets_qualitative_review_packets_2025.csv signed-decisions.csv \
  --confirmed data/confirmed/qualitative_reviewed_2025.csv \
  --unresolved data/review/qualitative_unresolved_2025.csv \
  --audit output/audit/qualitative_review_audit_2025.csv
```

`confirm`只接受0/20/50/80/100，`reject`禁止填写分值；所有决定必须填写审核人、理由和带时区
ISO-8601时间。100分的备注还必须明确行业领先或标杆证据。确认观测继承官方URL、原文件和页码，
并写入审核签名；原始证据候选和复核包均不覆盖。

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
