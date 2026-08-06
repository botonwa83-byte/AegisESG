# ESG数据补充和Demo生成计划

## 当前状态

### 正在进行
- ✅ 文本提取：Swift进程正在运行，处理975个PDF → 提取文本
- ⏳ 预计完成时间：10-20分钟（取决于PDF大小和复杂度）

### 已完成
- ✅ PDF收集：975份官方文档 + 12份cninfo补充
- ✅ 数据索引：official_document_index.csv
- ✅ 排名基础：universe_baseline_ranking_v1_2025.json (612家公司)
- ✅ 缺口分析：ranking_disclosure_gap_report_v1_2025.csv

---

## 需要补充的数据

### 1. 缺失的年报（高优先级）
根据`universe_collection_gaps_v1_2025.csv`：

**港股年报缺失（2家）**
- 01101.HK HUARONG ENERGY
- 00702.HK SINO OIL & GAS

**补充方案**：
1. 从港交所官网直接下载
2. 使用`scripts/run_verified_domain_download_campaign.py`
3. 手动从公司官网获取

### 2. 披露率低的指标（中优先级）
根据`ranking_disclosure_gap_report_v1_2025.csv`，披露率<10%的关键指标：

| 指标 | 披露率 | 缺口 |
|------|--------|------|
| 再生水占比 | 3.42% | 593家 |
| 清洁能源强度 | 3.75% | 591家 |
| SO2排放强度 | 4.07% | 589家 |
| 危废排放强度 | 4.72% | 585家 |
| 固废排放强度 | 5.37% | 581家 |
| PM排放强度 | 5.54% | 580家 |
| NOx排放强度 | 6.03% | 577家 |
| GHG减排率 | 6.19% | 576家 |
| 废水排放强度 | 6.35% | 575家 |
| 安全投入占比 | 7.0% | 571家 |

**补充方案**：
1. 官网ESG报告补充抓取
2. 年报附注和社会责任章节深度提取
3. 交易所ESG专项披露查询
4. 行业报告和第三方数据源

### 3. 主体缺口（18家）
- 目标：632家公司
- 当前：614家公司
- 缺口：18家

**补充方案**：需要外部提供完整名单

---

## Demo生成流程

### 前置条件检查
```bash
# 1. 文本提取完成检查
find data/text/ci_collection -name "*.txt" | wc -l
# 预期：~975个文本文件

# 2. 观测数据生成
python3 scripts/run_incremental_indicator_extraction.py
# 输出：output/research/2025/full_auto_observations_v*.csv
```

### Demo生成步骤

#### 步骤1：生成观测数据（如果文本提取完成）
```bash
# 增量指标提取
PYTHONPATH=src python3 scripts/run_incremental_indicator_extraction.py

# 预期输出：
# - output/research/2025/full_auto_observations_v*.csv
# - 9,000+ 观测记录
```

#### 步骤2：刷新研究排名
```bash
# 刷新排名（使用最新观测数据）
PYTHONPATH=src python3 scripts/run_research_ranking_refresh.py

# 预期输出：
# - output/research/2025/full_auto_v*_exchange_zero/ranking.html
# - output/research/2025/full_auto_v*_exchange_zero/ranking.json
```

#### 步骤3：生成Demo HTML
```bash
# 生成GitHub Pages兼容的静态demo
PYTHONPATH=src python3 scripts/build_github_demo.py

# 预期输出：
# - public-demo/index.html (系统演示主页)
# - public-demo/ranking/index.html (排名中心)
# - public-demo/data-readiness/index.html (数据就绪度)
# - public-demo/company/[公司代码]/index.html (公司详情页)
```

#### 步骤4：启动Demo服务器
```bash
bash scripts/run_real_system_demo.sh

# 访问：http://127.0.0.1:8000/demo
```

---

## 数据补充优先级策略

### P0：关键年报（必须）
- **2家港股年报**
- 影响：无年报则无法评分
- 时间：立即处理

### P1：关键环境指标（重要）
- **温室气体排放强度** (11.89% → 目标50%)
- **能源消耗强度** (9.45% → 目标50%)
- **水资源强度** (9.77% → 目标50%)
- **SO2/NOx/PM** (4-6% → 目标30%)
- 影响：E维度评分准确性
- 时间：1周内

### P2：社会责任指标（重要）
- **安全投入占比** (7.0% → 目标40%)
- **员工薪酬** (20.36% → 目标60%)
- **员工福利** (13.52% → 目标50%)
- 影响：S维度评分准确性
- 时间：2周内

### P3：其他指标（可选）
- **再生水占比** (3.42% → 目标20%)
- **清洁能源强度** (3.75% → 目标30%)
- 影响：细分指标准确性
- 时间：持续优化

---

## 多渠道数据补充方案

### 渠道1：官网ESG报告深度提取
```bash
# 运行官网数据发现和下载
python3 scripts/run_issuer_website_research_harvest.py --year 2025 --limit 100

# 目标：
# - 发现和下载公司官网ESG报告
# - 补充交易所未披露的指标
```

### 渠道2：年报附注深度挖掘
- 社会责任专章
- 环境保护投入明细
- 安全生产费用
- 员工薪酬和福利表

### 渠道3：交易所专项披露
- ESG专项报告
- 社会责任报告
- 环境信息披露
- 碳排放报告

### 渠道4：第三方数据源
- 行业协会报告
- 政府环保公示
- 能源统计年鉴
- ESG评级机构数据

### 渠道5：手动补充（最后手段）
- 电话咨询投资者关系部
- 邮件请求披露
- 实地调研
- 行业平均值推算（标注）

---

## 监控命令

### 检查文本提取进度
```bash
# 查看进程
ps aux | grep swift | grep extract

# 查看提取数量
find data/text/ci_collection -name "*.txt" | wc -l

# 查看日志
tail -f /private/tmp/claude-501/.../bclzu50am.output
```

### 检查观测数据
```bash
# 查看最新观测文件
ls -lt output/research/2025/full_auto_observations_*.csv | head -1

# 统计观测数量
wc -l output/research/2025/full_auto_observations_v*.csv
```

### 检查排名输出
```bash
# 查看排名目录
ls -la output/research/2025/full_auto_v*/

# 查看排名文件
ls -la output/research/2025/full_auto_v*/ranking.*
```

---

## 当前可以做的工作

### 立即可执行（不依赖文本提取）

1. **补充港股年报**
```bash
# 下载01101.HK和00702.HK年报
# 从港交所官网手动下载或使用API
```

2. **查看现有排名数据**
```bash
# 检查现有排名（基于旧数据）
cat output/audit/universe_baseline_ranking_v1_2025.json
```

3. **分析披露缺口**
```bash
# 查看详细缺口报告
cat output/audit/ranking_disclosure_gap_report_v1_2025.csv
```

4. **准备补充数据脚本**
```bash
# 官网数据发现
python3 scripts/build_official_website_source_queue.py
```

### 等待文本提取完成后

1. **生成观测数据**
2. **刷新排名**
3. **生成Demo**
4. **启动演示服务器**

---

## 预期时间线

| 阶段 | 预计时间 | 状态 |
|------|----------|------|
| 文本提取 | 10-20分钟 | 🔄 进行中 |
| 指标提取 | 5-10分钟 | ⏳ 等待文本 |
| 排名生成 | 2-3分钟 | ⏳ 等待观测数据 |
| Demo生成 | 1-2分钟 | ⏳ 等待排名 |
| 补充港股年报 | 10分钟 | 💡 可以并行开始 |
| 深度指标补充 | 1-2周 | 💡 持续进行 |

---

## 下一步建议

1. **等待文本提取完成**（10-20分钟）
2. **同时准备补充数据源**
3. **文本提取完成后立即生成demo**
4. **启动demo展示当前评测结果**
5. **根据缺口报告制定详细补充计划**

---

*生成时间：2026-08-06 21:00*  
*状态：文本提取进行中，demo生成准备就绪*
