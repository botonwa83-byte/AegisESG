# ESG评测数据收集状况报告

生成时间：2026-08-06

## 一、数据覆盖率总结

### 核心指标
- **目标公司数量**：976家
- **已收集公司数量**：975家
- **覆盖率**：**99.9%**
- **下载文档总数**：975份
- **数据总大小**：8.9GB

### 文档类型分布
- ESG报告：281份（目标）→ 281份（已收集）✓
- 年报：695份（目标）→ 694份（已收集，缺1份）

### 数据源分布
| 数据源 | 下载数量 |
|--------|----------|
| 上交所 (www.sse.com.cn) | 335 |
| 巨潮资讯 (static.cninfo.com.cn) | 315 |
| 港交所 (www1.hkexnews.hk) | 285 |
| 北交所 (www.bse.cn) | 25 |
| 深交所 (disc.static.szse.cn) | 15 |

## 二、数据缺口分析

### 唯一缺失的数据
- **公司**：920985.BJ 海泰新能
- **文档类型**：2025年年报
- **URL**：https://www.bse.cn/disclosure/2026/2026-04-28/03b5d97f82724fcababfdf745831515f.pdf
- **失败原因**：HTTP 403 Forbidden（北交所服务器拒绝访问）
- **失败分类**：other_download_error
- **可重试**：是
- **建议行动**：retry_later（等待服务器恢复或使用其他下载策略）

### 备用URL缺口
- **备用URL数量**：372个
- **说明**：这些是同一文档的备用链接，实际身份已通过主URL收集完成，不影响覆盖率

## 三、定时任务状态

### GitHub Actions配置
- **工作流名称**：Collect reviewed disclosure ESG data
- **触发方式**：
  - 定时：每10分钟执行一次（`*/10 * * * *`）
  - 手动：workflow_dispatch
- **运行环境**：ubuntu-latest
- **超时时间**：90分钟
- **Python版本**：3.11
- **并发控制**：单实例运行（official-data-collection组）

### 任务执行流程
1. 准备交易所manifest（`build_scheduled_collection_manifest.py`）
2. 准备官网manifest（`build_official_website_source_queue.py`等）
3. 恢复缓存（data/raw/ci_collection + output/sync）
4. 执行下载（`run_scheduled_collection.py`）
   - 时间预算：80分钟
   - 文档优先级：ESG优先
   - SZSE超时：1200秒
   - HTTP超时：300秒
5. 生成覆盖率和重试报告
6. 上传数据artifacts（保留30天）

### 缓存策略
- **缓存路径**：data/raw/ci_collection、output/sync
- **缓存键**：基于manifest文件哈希
- **恢复策略**：前缀匹配（aegis-ci-data-）

## 四、本次改进措施

### 已完成
1. ✅ 创建output/sync目录
2. ✅ 创建data/raw/ci_collection目录
3. ✅ 执行初始数据收集（2分钟测试）：下载161份文档，覆盖率16.5%
4. ✅ 执行主要数据收集（10分钟）：下载935份文档，覆盖率95.8%
5. ✅ 补充剩余缺口（5分钟）：下载975份文档，覆盖率99.9%
6. ✅ 分类失败原因并生成重试manifest

### 待处理
1. ⏳ 重试海泰新能年报下载（403错误，建议等待服务器恢复）
2. ⏳ 监控GitHub Actions定时任务是否正常运行
3. ⏳ 验证缓存机制是否正常工作

## 五、数据质量保障

### 验证机制
- ✅ PDF文件大小检查（过滤过小文件）
- ✅ 年份有效性验证（1990-2100）
- ✅ 身份去重（company_code + report_year + document_type）
- ✅ URL去重和备用链接处理

### 失败分类体系
- timeout_partial_resume：超时但有部分数据
- timeout_empty：超时且无数据
- ssl_eof：SSL连接错误
- connection_reset：连接重置
- connection_closed：连接关闭
- exchange_antibot_html：反爬虫HTML
- other_download_error：其他下载错误
- invalid_report_year：无效年份
- non_pdf_payload：非PDF内容
- pdf_too_small：PDF文件过小

## 六、下一步建议

### 短期（1-3天）
1. 监控GitHub Actions是否自动重试海泰新能的下载
2. 验证定时任务是否每10分钟正常运行
3. 检查artifact上传是否成功

### 中期（1-2周）
1. 手动访问北交所网站获取海泰新能年报
2. 分析403错误是否需要调整User-Agent或添加Referer
3. 考虑为北交所实现特殊的下载策略

### 长期优化
1. 实现智能重试机制（针对不同失败类型采用不同策略）
2. 增加数据完整性检测（PDF可读性验证）
3. 实现下载进度实时监控仪表板
4. 添加数据更新通知机制

## 七、相关文件清单

### 主要脚本
- `scripts/run_scheduled_collection.py` - 定时下载主脚本
- `scripts/build_collection_coverage_report.py` - 覆盖率报告
- `scripts/build_collection_retry_manifest.py` - 重试清单生成
- `scripts/classify_collection_failures.py` - 失败分类

### 数据文件
- `output/audit/scheduled_collection_manifest_v1_2025.csv` - 下载清单（1033行）
- `output/sync/official_document_index.csv` - 已下载索引（975行）
- `output/sync/official_collection_failures.csv` - 失败记录（1行）
- `output/audit/scheduled_collection_retry_v1_2025.csv` - 重试清单（1行）
- `data/raw/ci_collection/` - 原始PDF文件（8.9GB，975个文件）

### 状态报告
- `output/audit/scheduled_collection_coverage_v1_2025.json` - 覆盖率JSON
- `output/audit/scheduled_collection_retry_v1_2025_summary.json` - 重试摘要
- `output/audit/collection_failure_classification_v1_2025.csv` - 失败分类详情
