# aegisESP 不可替代外部输入登记

更新时间：2026-08-04

本登记只列系统不能真实替代的人类决定或外部事实。研究预排名可继续自动运行；以下项目未闭合前，
任何结果均不得提升为正式排名。

## 1. 正式632家公司主体表

- 当前证据：候选614家，均已绑定交易所快照；目标报告只公开前200，未公开完整632家底表。
- 缺口：18家目标主体及其纳入理由；614家中的行业分类、中文全称、A/H主体映射仍需真实证据审核。
- 禁止动作：从前200反推完整底表、按证券数量凑足632、由证券代码自动声称A/H同一主体。
- 验收：版本化主体表恰好632个唯一`entity_id`，四市场齐全，来源URL、日期、行业证据和纳入/排除
  决策完整，`universe-audit --expected-companies 632`通过。

## 2. 两家目标年度年报事实

- `00702.HK`（SINO OIL & GAS）和`01101.HK`（HUARONG ENERGY）官方最新年报停在2023，当前无
  2025年报；这不是下载失败。
- 需要：正式名录确认两家公司是否仍属于2025评价主体；若保留，需要由数据审核人签署“目标年度
  未披露”终态；若移除，须有主体表纳入/排除证据。
- 禁止动作：把2023年报改标2025、用新闻或第三方摘要替代正式年报。

## 3. 定量自动决定抽样

- 模板：`data/review/all_markets_quantitative_validation_sample_v5_2025.csv`。
- 清单：`output/audit/all_markets_quantitative_validation_sample_summary_v5_2025.json`。
- 当前状态：176条、66层、覆盖37项，真实签名0，绑定确认输入SHA-256。
- 需要：逐条true/false真值、有效真值数值、真实审核人、带时区时间和原页理由；准确率阈值98%。
- 验收：`evaluate-quantitative-validation --manifest ...`通过，随后使用同一confirmed文件执行
  `apply-quantitative-validation`；任何行增删或跨版本绑定均拒绝。

## 4. 三项薄样本方法论决定

- 模板：`data/review/all_markets_thin_methodology_review_v1_2025.csv`。
- 清单：`output/audit/all_markets_thin_methodology_review_manifest_v1_2025.json`。
- 指标：清洁能源强度（1/20）、SO2强度（13/20）、替代水占比（7/20）。
- 可选决定：保留阈值并警示、委托补采数据、修订指标定义、修订最低人口。
- 当前状态：3行签名0；输入人口摘要和1,822项诊断文件均已绑定Hash。
- 验收：真实方法论负责人填写决定、带时区时间、充分理由；修订类决定必须填写拟议变更。评估通过
  仍不直接改写方法论或授权评分，后续必须生成新方法论版本并重新执行全链路验证。

## 5. 定量冲突与定性正式审核

- 定量：137个公司指标组、285条观测仍需真实冲突审核。
- 定性：27,176个公司指标组尚无正式确认；应按风险分层、抽样阈值、双审和仲裁流程推进，不以全量
  人工逐格作为唯一自动化目标。
- 禁止动作：机器填写审核人、时间或理由；把研究域20/50/80估计提升为正式观测。
- 验收：高风险开放项及仲裁项清零，分类阈值和抽样准确率由真实标注验证，所有签名清单Hash闭合。

## 6. 专利权属与发明人确认

- 需要：申请主体、发明人名单、各技术特征实际贡献、职务发明关系、首次公开日期、申请国家/地区及
  代理机构意见。
- 工程证据：`docs/patent-strategy.md`、测试、冻结输入Hash、失败—修复样例和实验产物。
- 索引与模板：`docs/patent-evidence-index.md`、`docs/patent-contribution-ownership-template.md`。
- 禁止动作：系统根据代码提交者自动认定发明人或权利人。

## 7. 正式发布双签授权

- 正式算法：`formal_rank_fixed_v1`；研究算法：`auto_prerank_v1`，两域不可互相提升。
- 需要：不同真实人员担任方法论负责人和数据审核人，签署绑定观测、方法论、缺失策略和算法版本的
  发布清单；若启用`--require-dlt-process`，另需`evaluation_lead`第三人签名及一年有效期。
- 验收：六道完成门全部通过，授权清单验证成功，并执行
  `score --mode release --expected-companies 632 --release-manifest ...`。

## 8. 国资委工业领域优秀值（DL/T 2971 治理定量）

- 标准依据：DL/T 2971—2025 附录 A 要求公司治理定量参考《企业绩效评价标准值》工业领域优秀值。
- 模板：`data/methodologies/governance_benchmarks_template_2025.csv`（17项，含国资委表头别名）。
- 录入工作包：`prepare-governance-benchmark-packet` 生成 CSV/HTML；其中 4 项存在口径映射风险
  （EBITDA利润率、营业收现率、成本费用占收比、两金占比），不得擅自用近似项顶替。
- 当前状态：`audit-governance-benchmarks` 显示 filled=0/17，`formal_ready=false`；评价报告与行标 PDF
  均未随文公开具体优秀值数值。
- 需要：采购或内部提供经核验的当年《企业绩效评价标准值》工业（或约定细分行业）优秀值，填入 CSV
  后执行`apply-governance-benchmarks`冻结`DLT2971-2025-v1`。
- 禁止动作：用网络 OCR/二手摘录未核验数值直接冻结正式方法论；用样本均值冒充优秀值并宣称行标正式打分。
- 验收：`audit-dlt-alignment` 显示`aligned=true`，方法论版本为`DLT2971-2025-v1`，17项`benchmark`非空。

## 9. 公司官网域名归属核验

- 候选：`output/audit/official_domain_candidates_from_documents_v1_2025.csv`（455条/361家，已过滤
  巨潮/路演/排污披露平台/截断OCR域名）。
- P0工作包：`data/review/official_domain_review_batch01_2025.csv`（50家，优先缺独立ESG且HTTPS候选）。
- 只读页面：`/demo/official-domain-review`；应用审计：`output/audit/official_domain_review_application_v1_2025.json`。
- 同域发现：`/demo/official-report-discovery`，仅在域名核验后扫描同域HTTPS PDF，当前`await_verified_domains`。
- 当前状态：签名0/50，`blocked_external_review`；核验通过只登记域名，不授权下载或评分。
- 需要：人工确认域名归属发行方后填写`verify/reject/defer`、审核人、带时区时间和理由，再执行
  `apply-official-domain-review`；随后另发现同域HTTPS年报/ESG PDF链接。
- 禁止动作：把交易所/巨潮/搜索镜像登记为官网；未签名自动把候选写入下载清单；核验域名后直接评分。
- 验收：队列中对应公司`domain_verification=verified`且`download_authorized=false`，直至同域报告URL通过验证。

## 自动工程终态判断

只有当剩余未完成项均能在本登记中找到对应外部责任人、空白模板、输入Hash和机器可验证验收条件，
且代码测试、编译、差异检查和研究链路均通过时，才可认定“工程侧已完成、等待不可替代输入”。
该状态不等于项目正式完成，也不等于榜单可发布。

## 机器审计

可用以下命令检查登记项是否已有真实输入：

```bash
PYTHONPATH=src python3 -m aegis_esg.cli audit-external-readiness \
  --completion-report output/audit/project_completion_v16_2025.json \
  --quantitative-manifest output/audit/all_markets_quantitative_validation_sample_summary_v5_2025.json \
  --thin-methodology-manifest output/audit/all_markets_thin_methodology_review_manifest_v1_2025.json \
  --release-manifest data/review/release_authorization_template_2025.json \
  --patent-template docs/patent-contribution-ownership-template.md \
  --e1-summary output/audit/e1_evidence_validation_sample_summary_2025.json \
  --e2-summary output/audit/all_markets_rank_impact_review_summary_2025.json \
  --output output/audit/external_readiness_2025.json
```

该命令只读取并报告状态，不代替审核、不写入签名；当前结果为`blocked_external`。
E1约束图真实标注和E2审核调度结果也纳入可选审计项；缺少它们不会被误判为专利技术效果已验证。
E2签名模板为`data/review/all_markets_e2_validation_v1_2025.csv`，摘要为
`output/audit/all_markets_e2_validation_summary_v1_2025.json`；当前275项任务、111项跨前200边界，
签名0。

推荐使用`auto-stage`作为自动续接入口；它同时刷新`stage_assessment`和本登记审计，当前产物为
`output/audit/auto_stage_2025.json`，`next_stage=M3`且`continue_automatically=false`。
