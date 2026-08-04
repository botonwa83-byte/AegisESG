# aegisESP 专利工程证据索引

更新时间：2026-08-03

本索引证明技术方案、失败—修复过程和可测技术效果已经形成工程材料；不证明发明人资格、申请权
归属、专利性或法律结论。相关结论须由真实贡献人、申请主体和专利代理师确认。

| 特征编号 | 技术特征 | 主要实现 | 实验/审计证据 | 当前证据状态 |
|---|---|---|---|---|
| F01 | 异构披露证据约束图 | `src/aegis_esg/evidence_graph.py` | 约束图、E1冻结样本、真实错年/错单位反例 | 工程完成，真实E1标注待签 |
| F02 | 年份、单位、主体和口径联合闭合 | `extraction.py`、`env_intensity.py` | v7至v22全量增删审计、范围三变化排斥、SOx反例 | 工程完成，抽样待签 |
| F03 | 排名敏感性反向传播 | `ranking_analysis.py`、`review_priority.py` | 三缺失策略、Top-N边界、名次跨度与混合实验 | 工程完成 |
| F04 | 风险驱动审核调度 | `quantitative_gap_priority.py`、`gap_priority.py` | 全缺口1,822项、薄样本均衡批次、假阳性收敛 | 工程完成 |
| F05 | 依赖图局部增量重算 | `incremental.py` | 静态及动态E3基准、逐字段Hash等价 | 工程完成，真实签名变更实验待补 |
| F06 | 自动预排名与固定正式算法隔离 | `scoring.py`、`ranking_analysis.py` | `auto_prerank_v1`/`formal_rank_fixed_v1`攻击测试 | 工程完成 |
| F07 | 多级Hash冻结与发布双签 | `release_guard.py`、`quantitative_validation.py` | 输入/方法论/策略Hash、跨版本和机器身份拒绝 | 工程完成，真实双签待补 |
| F08 | 抽样完整性与规则扩展联动 | `quantitative_validation.py` | v5抽样176条/66层/37项，稳定候选ID全集 | 工程完成，真实标注待补 |
| F09 | 方法论变更防越权 | `methodology_review.py` | 三项裁决包、双输入Hash、清单及代签篡改测试 | 工程完成，真实裁决待补 |

## 核心冻结产物

- 方法论：`data/methodologies/energy_esg_2025.json`。
- v22候选、确认、未决及裁决日志：`data/review/all_markets_indicator_*_v22_2025.csv`、
  `output/audit/all_markets_indicator_resolution_*_v22_2025.*`。
- 定量抽样：`data/review/all_markets_quantitative_validation_sample_v5_2025.csv`及其summary。
- 薄样本全诊断与方法论裁决：`output/audit/thin_population_gap_batch_05_*`、
  `data/review/all_markets_thin_methodology_review_v1_2025.csv`及manifest。
- 最新研究反馈：`output/research/2025/full_auto_v19`及34,304条合并观测。
- 完成门：`output/audit/project_completion_v16_2025.json`。
- 发布授权空白模板：`data/review/release_authorization_template_2025.json`。

## 仍需真实输入的专利证据

1. E1和定量抽样的真实标注准确率；
2. 真实审核值变化后的E3非模拟实验；
3. 技术特征逐项实际贡献人及贡献时间；
4. 申请权/职务发明/委托开发关系证明；
5. 首次公开、演示、投标、论文、代码托管或客户交付日期；
6. 现有技术检索、单一性、充分公开和权利要求范围的代理师意见。

以上缺口不得用Git作者、机器执行记录或文档编写者身份自动推定。
