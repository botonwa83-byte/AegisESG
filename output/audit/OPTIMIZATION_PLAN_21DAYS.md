# ESG指标提取系统优化计划 - 目标95%+数据覆盖

执行时间：2026-08-06 21:40 开始  
目标：3周内将数据覆盖率从40%提升到95%

---

## 🎯 优化目标

### 核心KPI
```
当前状态: 40% 数据覆盖率
目标状态: 95% 数据覆盖率
提升幅度: +137.5%
时间期限: 21天 (3周)
```

### 分阶段目标
- **第1周末**: 60%覆盖率（+20%）
- **第2周末**: 80%覆盖率（+20%）
- **第3周末**: 95%覆盖率（+15%）

---

## 📋 三阶段实施计划

### 第1周：快速突破（Day 1-7）

#### Day 1-2：高频指标规则补充 ⚡
**目标**: 新增10个高频指标规则

**待补充指标**:
1. `Q_S_PAY_PER_EMPLOYEE` - 员工薪酬（披露率20%→目标40%）
2. `Q_S_BENEFIT_PER_EMPLOYEE` - 员工福利（披露率13%→目标30%）
3. `Q_S_ENV_INVEST_RATE` - 环保投入占比（新增→目标20%）
4. `Q_E_PM_INTENSITY` - PM排放强度（披露率5%→目标15%）
5. `Q_E_HAZ_WASTE_INTENSITY` - 危废排放强度（披露率4%→目标12%）
6. `Q_E_WASTEWATER_INTENSITY` - 废水排放强度（披露率6%→目标18%）
7. `Q_S_FEMALE_EMPLOYEE_RATE` - 女性员工占比（新增→目标25%）
8. `Q_S_EDU_PER_EMPLOYEE` - 职工教育经费（披露率15%→目标35%）
9. `Q_E_GHG_REDUCTION_RATE` - GHG减排率（披露率6%→目标20%）
10. `Q_E_CLEAN_ENERGY_INTENSITY` - 清洁能源强度（披露率3%→目标15%）

**实施步骤**:
```python
# 1. 员工薪酬（中文）
_rule("Q_S_PAY_PER_EMPLOYEE",
      r"(?:员工|职工)(?:平均)?(?:薪酬|工资|报酬)",
      r"(?:万|千)?元(?:/人)?",
      {"元": 1, "千元": 1000, "万元": 10000})

# 2. 环保投入占比
_rule("Q_S_ENV_INVEST_RATE",
      r"环(?:境)?(?:保护|保)(?:投入|支出|费用)(?:占比|比例)",
      r"%|％",
      {"%": 1.0})

# 3. PM排放强度
_rule("Q_E_PM_INTENSITY",
      r"(?:颗粒物|PM|粉尘)(?:排放)?强度",
      r"(?:千克|kg|吨|t)/万元",
      {"千克/万元": 1, "吨/万元": 1000})

# ... 继续添加其他7个
```

**验证**: 立即测试新规则提取效果

#### Day 3-4：放宽现有规则 📈
**目标**: 优化20个现有规则，提升20%匹配率

**优化策略**:
```python
# 优化前（过严）
r"千克标准煤/万元(?:营收|营业收入)"

# 优化后（灵活）
r"(?:千克|kg|公斤)(?:标准煤|标煤|tce)?[/／](?:万|百万)?元(?:营收|营业收入|收入|产值)?"

# 关键改进:
1. 支持同义词: 营收|营业收入|收入|产值
2. 支持单位变体: kg|千克|公斤
3. 支持符号变体: /|／
4. 可选标注: tce?, 产值?
5. 支持数量级: 万|百万
```

**需要优化的规则**:
1. Q_E_GHG_INTENSITY - 温室气体排放强度
2. Q_E_ENERGY_INTENSITY - 能源消耗强度
3. Q_E_WATER_INTENSITY - 水资源强度
4. Q_E_NOX_INTENSITY - NOx排放强度
5. Q_E_SO2_INTENSITY - SO2排放强度
6. Q_E_SOLID_WASTE_INTENSITY - 固废排放强度
7. Q_S_SAFETY_INVEST_RATE - 安全投入占比
8. Q_S_RD_RATE - 研发投入占比
9. Q_G_DEBT_ASSET_RATE - 资产负债率
10. Q_S_DONATION_RATE - 公益捐赠（英文规则）
... 继续优化其他10个

#### Day 5-7：简易表格识别 📊
**目标**: 实现基础表格数据提取

**实现方案**:
```python
def detect_simple_table(text: str) -> list[TableRow]:
    """检测简单的列对齐表格"""
    lines = text.split('\n')
    table_lines = []
    
    # 1. 检测多列对齐（3个以上连续空格）
    for line in lines:
        if re.search(r'\s{3,}.*\s{3,}', line):
            table_lines.append(line)
    
    # 2. 解析表头（查找年份和单位）
    header = table_lines[0] if table_lines else ""
    years = re.findall(r'20\d{2}', header)
    unit = extract_unit(header)
    
    # 3. 提取数据行
    rows = []
    for line in table_lines[1:]:
        label = extract_row_label(line)
        values = extract_row_values(line)
        if label and values:
            rows.append(TableRow(label, values, unit))
    
    return rows

def extract_from_tables(pages: list[PageText]) -> list[Observation]:
    """从表格中提取指标"""
    observations = []
    
    for page in pages:
        tables = detect_simple_table(page.text)
        for row in tables:
            # 匹配指标代码
            indicator_code = match_indicator_label(row.label)
            if indicator_code:
                # 提取当前年份的值
                value = get_value_for_year(row.values, current_year)
                # 应用单位换算
                normalized = normalize_value(value, row.unit)
                
                observations.append(Observation(
                    indicator_code=indicator_code,
                    value=normalized,
                    confidence=0.85,  # 表格数据置信度
                    ...
                ))
    
    return observations
```

**集成到提取流程**:
```python
# 在 extract_indicator_candidates 中添加
def extract_indicator_candidates(...):
    candidates = []
    
    # 原有的文本行提取
    candidates.extend(extract_from_text_rules(pages, ...))
    
    # 新增的表格提取
    candidates.extend(extract_from_tables(pages, ...))
    
    return deduplicate(candidates)
```

**预期效果**: 
- 表格数据提取率: 0% → 40%
- 整体提取率: 40% → 60%

---

### 第2周：深度优化（Day 8-14）

#### Day 8-10：补充剩余7个指标规则 🔧
**目标**: 达到90%规则覆盖（33/37）

**待补充指标**:
1. `Q_G_OPERATING_PROFIT_GROWTH` - 营业利润增长率
2. `Q_G_CASH_CURRENT_LIABILITY` - 现金流动负债比率
3. `Q_S_FEMALE_MANAGER_RATE` - 女性管理者占比
4. `Q_S_EMPLOYEE_TRAINING_HOUR` - 人均培训时长
5. `Q_S_SOCIAL_INSURANCE_RATE` - 社保缴纳比例
6. `Q_S_ACCIDENT_RATE` - 安全事故率
7. `Q_E_WATER_CONSUMPTION` - 水资源消耗总量

**实施步骤**:
```python
# 1. 营业利润增长率
_rule("Q_G_OPERATING_PROFIT_GROWTH",
      r"营业利润(?:增长|增幅)(?:率)?",
      r"[+-]?\d+(?:\.\d+)?%",
      {"%": 1.0})

# 2. 现金流动负债比率
DirectRule("Q_G_CASH_CURRENT_LIABILITY",
          re.compile(r"经营活动(?:产生的)?现金流量净额?[^\d]{0,30}流动负债" + NUMBER),
          1.0, 0.90)

# 3. 女性管理者占比
_rule("Q_S_FEMALE_MANAGER_RATE",
      r"女性(?:管理|高管|领导)(?:人员|者)?(?:占比|比例)",
      r"\d+(?:\.\d+)?%",
      {"%": 1.0})

# ... 继续添加其他4个
```

#### Day 11-12：增强表格提取 📊
**目标**: 支持复杂表格格式

**增强功能**:
```python
def detect_complex_table(text: str) -> list[Table]:
    """支持更复杂的表格格式"""
    
    # 1. 支持多级表头
    def parse_multi_header(lines):
        """解析二级表头（如：年份下分季度）"""
        pass
    
    # 2. 支持单位在表头
    def extract_unit_from_header(header):
        """从表头提取单位（如：单位：吨CO2e/万元）"""
        patterns = [
            r"单位[：:]\s*([^\s\n]+)",
            r"\(([^)]+)\)$",
            r"Unit:\s*([^\s\n]+)"
        ]
        for pattern in patterns:
            match = re.search(pattern, header)
            if match:
                return match.group(1)
        return None
    
    # 3. 支持合并单元格
    def handle_merged_cells(rows):
        """处理跨行/跨列合并单元格"""
        pass
    
    # 4. 支持表格内注释
    def strip_table_notes(text):
        """去除表格内的注释（如：*1、注：等）"""
        return re.sub(r'[*†‡]?\d+|注[：:].*', '', text)
    
    return tables
```

**支持的表格格式**:
```
格式1: 标准表格
┌────────────┬──────┬──────┐
│ 指标       │ 2024 │ 2025 │
├────────────┼──────┼──────┤
│ GHG强度    │ 1.23 │ 1.15 │
└────────────┴──────┴──────┘

格式2: 单位在表头
指标统计表（单位：吨CO2e/万元）
GHG排放强度    1.23    1.15
能源消耗强度    0.45    0.42

格式3: 紧凑格式
GHG排放强度：1.15吨CO2e/万元（2025年）

格式4: 列表格式
• 温室气体排放强度：1.15
• 能源消耗强度：0.42
```

#### Day 13-14：财务数据增强 💰
**目标**: 提升财务指标提取准确率

**增强策略**:
```python
# 1. 支持中文财务报表
def extract_cn_financial_statements(pages):
    """提取中文格式的资产负债表和利润表"""
    patterns = {
        "资产负债表": r"(?:合并)?资产负债表",
        "利润表": r"(?:合并)?利润表",
        "现金流量表": r"(?:合并)?现金流量表"
    }
    # 识别报表起始页
    # 提取关键项目
    # 计算衍生指标
    pass

# 2. 区分合并vs母公司
def identify_statement_type(page_text):
    """识别是合并报表还是母公司报表"""
    if re.search(r"合并.*(?:资产负债表|利润表)", page_text):
        return "consolidated"
    elif re.search(r"母公司.*(?:资产负债表|利润表)", page_text):
        return "parent"
    return "unknown"

# 3. 提取利润表数据
def extract_profit_growth(pages):
    """提取营业利润增长率"""
    # 查找利润表
    # 提取本年和上年营业利润
    # 计算增长率
    pass
```

---

### 第3周：精细优化（Day 15-21）

#### Day 15-17：规则微调和单位完善 🔧
**目标**: 完善单位换算，支持所有变体

**单位换算矩阵**:
```python
UNIT_CONVERSIONS = {
    # 能源强度
    "千克标准煤/万元": 1.0,
    "kg标煤/万元": 1.0,
    "吨标煤/万元": 1000.0,
    "t标煤/万元": 1000.0,
    "千克tce/万元": 1.0,
    "吨标煤/百万元": 10.0,  # 新增
    "kg标煤/千元": 0.1,  # 新增
    
    # GHG强度
    "千克CO2e/万元": 1.0,
    "kg CO2/万元": 1.0,
    "吨CO2e/万元": 1000.0,
    "t CO2/万元": 1000.0,
    "吨CO2/百万元": 10.0,  # 新增
    "g CO2/万元": 0.001,  # 新增
    
    # 水资源
    "立方米/万元": 1.0,
    "吨/万元": 1.0,  # 水：1立方米≈1吨
    "m³/万元": 1.0,
    "升/万元": 0.001,  # 新增
    
    # 电能转标煤
    "万千瓦时/万元": 1.229,  # 1万kWh = 1.229吨标煤
    "度/万元": 0.0001229,  # 新增
}
```

**支持范围值**:
```python
def parse_range_value(text):
    """解析范围值，取平均"""
    # "1.2-1.5" → 1.35
    # "1.2~1.5" → 1.35
    # "1.2至1.5" → 1.35
    match = re.search(r'(\d+(?:\.\d+)?)\s*[-~至]\s*(\d+(?:\.\d+)?)', text)
    if match:
        return (float(match.group(1)) + float(match.group(2))) / 2
    return None
```

#### Day 18-19：全量重新提取 🔄
**目标**: 使用优化后的规则重新提取所有数据

**执行步骤**:
```bash
# 1. 备份当前结果
cp output/audit/ci_incremental_candidates_v1_2025.csv \
   output/audit/ci_incremental_candidates_v1_2025_backup.csv

# 2. 清空候选缓存
rm -f output/audit/ci_incremental_candidates_v1_2025.csv

# 3. 重新提取（使用新规则）
PYTHONPATH=src python3 scripts/run_incremental_indicator_extraction.py

# 4. 生成对比报告
python3 scripts/compare_extraction_results.py \
  --old output/audit/ci_incremental_candidates_v1_2025_backup.csv \
  --new output/audit/ci_incremental_candidates_v1_2025.csv \
  --output output/audit/extraction_improvement_report.csv
```

**评估提取效果**:
```python
def evaluate_extraction_quality():
    """评估提取质量"""
    metrics = {
        "total_observations": 0,
        "by_indicator": {},
        "by_confidence": {},
        "coverage_by_company": {}
    }
    
    # 统计每个指标的提取数量
    # 统计每个公司的指标覆盖数
    # 计算平均置信度
    # 识别提取异常值
    
    return metrics
```

#### Day 20-21：验证和调优 ✅
**目标**: 达到95%数据覆盖目标

**验证清单**:
```markdown
□ 规则覆盖率: ≥95% (35/37指标)
□ 公司覆盖率: 每家公司平均提取≥30个指标
□ 高披露指标: ≥25个指标披露率>50%
□ 中披露指标: ≥10个指标披露率20-50%
□ 低披露指标: ≤2个指标披露率<20%
□ 提取准确率: 抽样100条，准确率≥90%
□ 置信度分布: >80%的记录置信度≥0.85
```

**问题修复**:
```python
# 1. 识别过度提取（误报）
def find_false_positives():
    """查找可能的误报"""
    # 异常值检测
    # 同一指标多个候选值
    # 置信度过低的记录
    pass

# 2. 识别遗漏提取（漏报）
def find_false_negatives():
    """查找可能的漏报"""
    # 随机抽样文档
    # 人工标注应该提取的指标
    # 对比系统提取结果
    pass

# 3. 规则微调
def tune_extraction_rules():
    """根据误报/漏报调整规则"""
    # 降低误报规则的置信度
    # 放宽漏报规则的匹配条件
    pass
```

---

## 📊 进度跟踪

### 每日KPI
```python
daily_metrics = {
    "新增规则数": 0,
    "优化规则数": 0,
    "提取记录数": 0,
    "数据覆盖率": 0.0,
    "问题修复数": 0
}
```

### 周度里程碑
```
Week 1:
- [ ] Day 2: 新增10个规则，覆盖率→50%
- [ ] Day 4: 优化20个规则，覆盖率→55%
- [ ] Day 7: 表格提取就绪，覆盖率→60%

Week 2:
- [ ] Day 10: 新增7个规则，规则覆盖90%
- [ ] Day 12: 复杂表格支持，覆盖率→75%
- [ ] Day 14: 财务增强完成，覆盖率→80%

Week 3:
- [ ] Day 17: 单位完善，覆盖率→85%
- [ ] Day 19: 全量重提取，覆盖率→90%
- [ ] Day 21: 验证调优完成，覆盖率→95% ✅
```

---

## 🔧 立即开始：Day 1 任务

### 任务1: 添加员工薪酬规则（30分钟）
```python
# 添加到 src/aegis_esg/extraction.py 的 RULES 列表

# 中文规则
_rule("Q_S_PAY_PER_EMPLOYEE",
      r"(?:员工|职工)(?:平均)?(?:薪酬|工资|报酬|年薪)",
      r"(?:万|千)?元(?:/人|人均)?",
      {"元": 1, "千元": 1000, "万元": 10000},
      confidence=0.88)

# 英文规则
DirectRule("Q_S_PAY_PER_EMPLOYEE",
          re.compile(r"(?:average|per capita)\s+(?:employee\s+)?(?:salary|compensation|remuneration)\s+" + 
                    r"(?:of\s+)?(?:RMB|CNY)?\s*" + NUMBER + r"\s*(?:thousand|万)?", re.I),
          1000.0,  # 假设是千元
          0.85)
```

### 任务2: 添加环保投入规则（20分钟）
```python
_rule("Q_S_ENV_INVEST_RATE",
      r"环(?:境)?(?:保护|保)(?:投入|支出|投资|费用)(?:占比|比例|占营业收入)",
      r"\d+(?:\.\d+)?%",
      {"%": 1.0},
      confidence=0.90)

# 英文规则
DirectRule("Q_S_ENV_INVEST_RATE",
          re.compile(r"environmental\s+(?:protection\s+)?(?:investment|spending|expenditure)\s+" +
                    r"(?:as\s+a\s+)?(?:percentage|proportion)\s+(?:of\s+revenue)?\s*" + NUMBER + r"\s*%", re.I),
          1.0,
          0.88)
```

### 任务3: 测试新规则（10分钟）
```bash
# 重新运行提取
PYTHONPATH=src python3 scripts/run_incremental_indicator_extraction.py

# 检查新增的观测数
grep "Q_S_PAY_PER_EMPLOYEE\|Q_S_ENV_INVEST_RATE" \
  output/audit/ci_incremental_candidates_v1_2025.csv | wc -l
```

---

## 💡 成功因素

### 关键成功要素
1. **快速迭代**: 每天测试，及时调整
2. **数据驱动**: 基于实际提取效果优化规则
3. **优先级清晰**: 先高频指标，后长尾指标
4. **质量把控**: 准确率>覆盖率

### 风险缓解
| 风险 | 缓解措施 |
|------|----------|
| 规则过度匹配 | 抽样验证，置信度评估 |
| 表格识别失败 | 先简单后复杂，逐步迭代 |
| 单位换算错误 | 建立完整换算矩阵，单元测试 |
| 时间超期 | 每日进度跟踪，及时调整优先级 |

---

## 📈 预期成果

### 量化目标
```
规则覆盖: 54% → 95% (+41%)
数据覆盖: 40% → 95% (+55%)
高披露指标: 8个 → 25个 (+17个)
可用公司: 300家 → 580家 (+280家)

系统价值: 提升2.5倍
投资回报: 极高
```

### 业务价值
- ✅ 达到正式发布标准
- ✅ 排名数据可信度显著提升
- ✅ 系统从"研究级"升级到"生产级"
- ✅ 为后续持续优化奠定基础

---

**计划制定时间**: 2026-08-06 21:40  
**计划执行**: 立即开始  
**预期完成**: 2026-08-27  
**负责人**: 开发团队

**下一步**: 立即开始 Day 1 任务 →
