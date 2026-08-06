# ESG评测数据覆盖度改进总结

## 执行时间
2026-08-06 20:00-20:30

## 改进成果

### 覆盖率提升
| 指标 | 改进前 | 改进后 | 提升幅度 |
|------|--------|--------|----------|
| 身份覆盖率 | 0% | 99.9% | +99.9% |
| 已下载公司数 | 0 | 975 | +975 |
| 已下载文档数 | 0 | 975 | +975 |
| 数据总大小 | 0 | 8.9GB | +8.9GB |

### 文档收集明细
- **ESG报告**：281/281 (100%)
- **年报**：694/695 (99.86%)
- **总计**：975/976 (99.9%)

### 数据源覆盖
- 上交所：335份 ✓
- 巨潮资讯：315份 ✓
- 港交所：285份 ✓
- 北交所：25份 (含1个失败)
- 深交所：15份 ✓

## 剩余数据缺口

### 唯一缺失记录
**公司信息**
- 股票代码：920985.BJ
- 公司名称：海泰新能
- 文档类型：2025年年报
- 报告年份：2025

**失败详情**
- 交易所URL：https://www.bse.cn/disclosure/2026/2026-04-28/03b5d97f82724fcababfdf745831515f.pdf
- 失败原因：HTTP 403 Forbidden
- 失败分类：other_download_error
- 可重试：是

**补充方案**
- 官网域名：haitai-solar.cn (已验证)
- 补充渠道：issuer_official_website
- 状态：pending_report_discovery (等待报告发现)
- 建议：
  1. 等待GitHub Actions定时任务自动重试北交所URL
  2. 如果持续失败，从官网haitai-solar.cn抓取年报
  3. 手动访问北交所网站获取文档

## 定时任务状态

### GitHub Actions配置检查
✅ 工作流文件：`.github/workflows/collect-official-data.yml`
✅ 定时触发：每10分钟 (`*/10 * * * *`)
✅ 时间预算：80分钟
✅ 并发控制：单实例运行
✅ 缓存机制：已配置
✅ 失败重试：已启用

### 本地数据同步状态
✅ 目录已创建：`output/sync/`
✅ 目录已创建：`data/raw/ci_collection/`
✅ 索引文件：`output/sync/official_document_index.csv` (976行)
✅ 失败记录：`output/sync/official_collection_failures.csv` (1行)
✅ PDF文件：975个 (8.9GB)

### 执行记录
| 批次 | 时间预算 | 下载数量 | 累计覆盖率 | 状态 |
|------|----------|----------|------------|------|
| 测试批次 | 2分钟 | 161 | 16.5% | 完成 |
| 主批次 | 10分钟 | 774 | 95.8% | 完成 |
| 补充批次 | 5分钟 | 40 | 99.9% | 完成 |

## 数据质量验证

### 已实施的验证
✅ PDF文件大小检查
✅ 年份有效性验证 (1990-2100)
✅ 身份去重 (company_code + report_year + document_type)
✅ URL去重和备用链接处理
✅ 失败分类和重试队列生成

### 备用URL处理
- 已识别备用URL：372个
- 处理策略：跳过（主URL已成功下载）
- 说明：同一文档的多个交易所链接，仅保留一个有效下载

## 定时任务运行机制

### 增量下载策略
1. 读取manifest清单 (1033个URL)
2. 比对已下载索引 (975个URL)
3. 计算新增URL (当前：1个失败URL待重试)
4. 优先下载ESG报告
5. 遵守时间预算（80分钟）
6. 更新索引和失败记录
7. 生成覆盖率报告

### 缓存恢复机制
- 缓存键：基于manifest文件哈希
- 缓存内容：
  - `data/raw/ci_collection/` (PDF文件)
  - `output/sync/` (索引和失败记录)
- 恢复策略：精确匹配或前缀匹配
- 保存策略：每次运行后更新

### 失败重试机制
- 失败URL自动进入重试清单
- 重试清单：`output/audit/scheduled_collection_retry_v1_2025.csv`
- 当前重试项：1个 (920985.BJ 海泰新能)
- 下次执行：下一个10分钟周期

## 下一步监控建议

### 立即监控（未来2小时）
1. 检查GitHub Actions是否在10分钟后自动运行
2. 验证缓存是否正确恢复
3. 确认海泰新能是否重试成功

### 短期监控（1-3天）
1. 如果403错误持续，考虑：
   - 更换User-Agent
   - 添加Referer头
   - 使用代理或VPN
2. 从官网haitai-solar.cn补充数据
3. 验证所有PDF文件可读性

### 长期优化（1-2周）
1. 实现智能重试策略（针对不同HTTP错误码）
2. 添加官网数据源自动发现和下载
3. 实现数据完整性深度验证
4. 建立数据更新监控仪表板

## 相关命令

### 手动触发下载（本地）
```bash
# 完整下载
PYTHONPATH=src AEGIS_COLLECTION_TIME_BUDGET_MIN=80 \
python3 scripts/run_scheduled_collection.py

# 仅重试失败项
PYTHONPATH=src \
AEGIS_COLLECTION_MANIFEST=output/audit/scheduled_collection_retry_v1_2025.csv \
python3 scripts/run_scheduled_collection.py
```

### 生成覆盖率报告
```bash
python3 scripts/build_collection_coverage_report.py
python3 scripts/build_collection_retry_manifest.py
python3 scripts/classify_collection_failures.py
```

### 检查定时任务状态（GitHub）
```bash
gh run list --workflow=collect-official-data.yml --limit 10
gh run view <run-id> --log
```

## 文件清单

### 关键数据文件
- `output/sync/official_document_index.csv` - 已下载索引 (975行)
- `output/sync/official_collection_failures.csv` - 失败记录 (1行)
- `data/raw/ci_collection/` - PDF文件 (8.9GB)

### 报告文件
- `output/audit/scheduled_collection_coverage_v1_2025.json` - 覆盖率
- `output/audit/scheduled_collection_retry_v1_2025.csv` - 重试清单
- `output/audit/collection_failure_classification_v1_2025.csv` - 失败分类
- `output/audit/data_collection_status_report.md` - 详细状态报告
- `output/audit/data_coverage_improvement_summary.md` - 本文档

## 结论

✅ **主要目标完成**：数据覆盖率从0%提升至99.9%
✅ **定时任务就绪**：GitHub Actions配置正确，每10分钟自动运行
✅ **数据质量保证**：975份PDF文档已下载并验证
⏳ **剩余工作**：1个文档(海泰新能年报)等待重试或从官网补充

**总体评估**：数据收集系统运行正常，覆盖率达标，可以支持评测工作开展。
