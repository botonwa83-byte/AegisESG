# ESG核心指标优化进展 - 2026-08-07

## 优化目标
针对6个核心指标（SO2、NOx、固废、能源、水资源、GHG强度）提升数据覆盖率，解决企业数据采集不足的问题。

## 当前状态（优化前）
| 指标 | 覆盖率 | 记录数 |
|-----|--------|--------|
| Q_E_GHG_INTENSITY | 17.7% | 173条 |
| Q_E_ENERGY_INTENSITY | 14.0% | 137条 |
| Q_E_SO2_INTENSITY | 2.5% | 25条 |
| Q_E_NOX_INTENSITY | 4.1% | 40条 |
| Q_E_WATER_INTENSITY | 12.4% | 121条 |
| Q_E_SOLID_WASTE_INTENSITY | 5.2% | 51条 |

## 已完成的优化措施

### 1. 数据缺口根因分析 ✓
**发现**：
- 绝对排放量数据充足（GHG 254条、ENERGY 215条、NOX 58条）
- 强度数据不足（差距177条）
- 根本原因：企业只披露绝对量，不披露强度

### 2. 强度自动计算功能 ✓
**实现**：
- 创建计算脚本：`scripts/calculate_intensity_from_absolute.py`
- 从营收增长率证据中提取营业收入
- 计算强度 = 绝对量 × 单位转换系数 / 营收(万元)

**成果**：
- 成功计算62条新强度记录
- GHG: +26条, ENERGY: +16条, NOX: +7条
- SO2: +3条, 固废: +5条, 水资源: +5条

**限制**：
- 营收提取率只有39.5%（633家中的250家）
- 需要直接提取营业收入绝对值

### 3. 新增提取规则 ✓
**在 `src/aegis_esg/extraction.py` 中添加了4条新规则**：

#### 3.1 营业收入提取规则
```python
DirectRule("Q_G_REVENUE", ...)
```
- 匹配：营业收入（元） + 数值
- 目标：提取率从39.5% → 80%+

#### 3.2 SO2绝对排放量规则
```python
DirectRule("Q_E_SO2_EMISSION", ...)
```
- 匹配：二氧化硫/SO2排放量 + 数值
- 目标：提取量从25条 → 100+条

#### 3.3 NOx绝对排放量规则
```python
DirectRule("Q_E_NOX_EMISSION", ...)
```
- 匹配：氮氧化物/NOx排放量 + 数值
- 目标：提取量从58条 → 150+条

#### 3.4 固废绝对产生量规则
```python
DirectRule("Q_E_SOLID_WASTE_GENERATION", ...)
```
- 匹配：固体废物产生量 + 数值
- 目标：提取量从25条 → 80+条

**验证**：
- DirectRule总数：73条 → 77条 ✓
- 新规则已加载：Q_G_REVENUE(1条), SO2_EMISSION(2条), NOX_EMISSION(2条), SOLID_WASTE_GENERATION(2条) ✓

## 待执行任务

### 任务1: 重新运行数据提取 🔄
```bash
PYTHONPATH=src python3 scripts/extract_ci_incremental_candidates.py
```
- 预计耗时：10-20分钟
- 使用新增的4条规则重新提取所有企业数据

### 任务2: 重新计算强度指标 ⏳
```bash
python3 scripts/calculate_intensity_from_absolute.py
```
- 基于新提取的营业收入数据
- 预期计算出150+条强度记录（vs 当前62条）

### 任务3: 验证优化效果 ⏳
```bash
python3 scripts/analyze_extraction_simple.py
```
- 对比优化前后覆盖率
- 生成效果报告

## 预期效果

### 保守估计
| 指标 | 优化前 | 预期优化后 | 提升 |
|-----|--------|-----------|------|
| Q_E_GHG_INTENSITY | 173条 (17.7%) | 230+条 (23.6%) | +33% |
| Q_E_ENERGY_INTENSITY | 137条 (14.0%) | 180+条 (18.5%) | +31% |
| Q_E_SO2_INTENSITY | 25条 (2.5%) | 70+条 (7.2%) | +180% |
| Q_E_NOX_INTENSITY | 40条 (4.1%) | 100+条 (10.3%) | +150% |
| Q_E_WATER_INTENSITY | 121条 (12.4%) | 150+条 (15.4%) | +24% |
| Q_E_SOLID_WASTE_INTENSITY | 51条 (5.2%) | 90+条 (9.2%) | +76% |

### 提升逻辑
1. **直接提取提升**：新规则提取更多绝对排放量
2. **计算补充提升**：营收数据增加 → 可计算强度增加
3. **规则优化提升**：昨晚已优化的强度直接提取规则生效

## 技术亮点

1. **双路径策略**：直接提取强度 + 从绝对量计算强度
2. **根因驱动**：分析企业实际披露习惯，而非盲目增加规则
3. **增量优化**：不重写全部代码，只针对性添加4条关键规则
4. **可验证性**：每步都有明确的数据支撑和预期效果

## 文件清单

### 核心代码
- `src/aegis_esg/extraction.py` - 新增4条DirectRule
- `scripts/calculate_intensity_from_absolute.py` - 强度计算脚本

### 分析脚本
- `scripts/analyze_extraction_simple.py` - 提取结果分析
- `scripts/test_new_rules.py` - 新规则测试

### 输出文件
- `output/audit/ci_incremental_candidates_v1_2025.csv` - 提取结果（待更新）
- `output/audit/ci_calculated_intensities_v1_2025.csv` - 计算强度（62条）

## 下一步行动

✅ 已完成：
1. 数据缺口分析
2. 强度计算功能实现
3. 新提取规则添加

🔄 进行中：
4. 重新运行数据提取

⏳ 待执行：
5. 重新计算强度
6. 验证优化效果
7. 生成对比报告

---
**更新时间**：2026-08-07 上午
**优化阶段**：实施中
**预计完成**：今天下午
