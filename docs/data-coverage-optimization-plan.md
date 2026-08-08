# 数据覆盖优化详细计划

**制定时间**: 2026-08-08  
**项目阶段**: 设计定型后的数据优化阶段  
**核心约束**: 不修改企业排名表设计和算法的大架构

---

## 一、当前状况分析

根据代码审查和排名文件分析，当前系统状况：

### 1.1 已实现的基础设施
- ✅ 80项指标体系（37项定量 + 43项定性）和权重已定型
- ✅ 评分算法已实现（样本正态分布 + 治理优秀值峰打分）
- ✅ 632家能源公司宇宙池已建立
- ✅ 数据采集管道（交易所、cninfo、公司网站）
- ✅ PDF解析和候选值抽取
- ✅ 审核流程和证据链追溯

### 1.2 数据覆盖问题（来自 ranking_disclosure_gap_report）
根据 `output/audit/ranking_disclosure_gap_report_v1_2025.csv`：

**严重缺失指标（披露率<10%）**：
- Q_E_ALTERNATIVE_WATER_RATE（再生水占比）: 3.42%
- Q_E_CLEAN_ENERGY_INTENSITY（清洁能源强度）: 3.75%
- Q_E_SO2_INTENSITY（二氧化硫排放强度）: 4.07%
- Q_E_HAZ_WASTE_INTENSITY（危险废物强度）: 4.72%
- Q_E_SOLID_WASTE_INTENSITY（固体废物强度）: 5.37%
- Q_E_PM_INTENSITY（颗粒物强度）: 5.54%
- Q_E_NOX_INTENSITY（氮氧化物强度）: 6.03%
- Q_S_SAFETY_INVEST_RATE（安全投入占比）: 7.0%
- Q_E_ENERGY_INTENSITY（能源消耗强度）: 9.45%
- Q_E_WATER_INTENSITY（水资源强度）: 9.77%

**中等缺失指标（10%-40%）**：
- Q_E_GHG_INTENSITY（温室气体强度）: 11.89%
- Q_S_BENEFIT_PER_EMPLOYEE（员工福利）: 13.52%
- Q_S_PAY_PER_EMPLOYEE（员工薪酬）: 20.36%

**覆盖较好指标（>50%）**：
- Q_G_ROE（净资产收益率）: 93.81%
- Q_G_REVENUE_GROWTH（营业增长率）: 90.39%
- Q_G_DEBT_ASSET_RATE（资产负债率）: 85.67%

### 1.3 当前系统缺口
- ❌ 缺失值处理策略单一（仅 legacy_zero_v1、indicator_neutral_v1、disclosed_weight_v1）
- ❌ 无公式派生机制扩展已有数据
- ❌ 无历史数据时间序列预测
- ❌ 无行业平均值填充机制
- ❌ 数据源仍未充分利用（公司官网ESG报告）

---

## 二、优化策略详解

### 策略1：公式计算扩展（Formula Derivation）

**目标**: 从已有数据通过财务公式推导缺失指标

#### 1.1 可派生指标映射表

| 目标指标 | 公式 | 依赖数据 | 优先级 |
|---------|------|---------|-------|
| Q_E_ENERGY_INTENSITY | 综合能耗 / 营业收入 | 能耗总量 + 收入 | 高 |
| Q_E_WATER_INTENSITY | 用水量 / 营业收入 | 用水总量 + 收入 | 高 |
| Q_E_GHG_INTENSITY | 温室气体排放量 / 营业收入 | GHG总量 + 收入 | 高 |
| Q_E_SO2_INTENSITY | SO2排放量 / 营业收入 | SO2总量 + 收入 | 高 |
| Q_E_NOX_INTENSITY | NOx排放量 / 营业收入 | NOx总量 + 收入 | 高 |
| Q_S_PAY_PER_EMPLOYEE | 薪酬总额 / 员工人数 | 应付职工薪酬 + 员工数 | 高 |
| Q_S_BENEFIT_PER_EMPLOYEE | 福利总额 / 员工人数 | 社保公积金 + 员工数 | 高 |
| Q_G_OPERATING_MARGIN | 营业利润 / 营业收入 | 利润表 | 中 |
| Q_G_ROA | 净利润 / 总资产 | 资产负债表 + 利润表 | 中 |

**实施要点**：
- 派生值必须标注来源为"formula_derived"
- 保存派生公式和源观测ID用于审计
- 置信度设置为源数据最低置信度 × 0.9
- 仅在源数据status=CONFIRMED时派生
- 派生值不参与行业基准计算（避免循环依赖）

#### 1.2 实施文件
```python
# 新建: src/aegis_esg/formula_derivation.py
# 修改: scripts/run_incremental_indicator_extraction.py（加入派生阶段）
```

---

### 策略2：扩大数据下载渠道（Data Source Expansion）

**目标**: 从更多合规来源获取原始披露

#### 2.1 新增数据源清单

| 数据源 | 覆盖内容 | 优先级 | 实施难度 |
|--------|---------|-------|---------|
| 公司官网ESG专栏 | 环境指标详细披露 | 高 | 中 |
| 国家能源局公开数据 | 能源强度行业数据 | 高 | 低 |
| 生态环境部公开平台 | 排污许可证、监测数据 | 高 | 中 |
| 应急管理部 | 安全生产投入统计 | 中 | 中 |
| 中国证券业协会 | 上市公司社会责任指引 | 低 | 低 |

**当前已有但未充分利用**：
- `scripts/run_cooperative_issuer_website_pipeline.py` - 公司官网渠道
- `scripts/run_verified_domain_download_campaign.py` - 域名验证下载

#### 2.2 实施步骤
1. **Phase 1 (Week 1-2)**: 激活公司官网ESG报告自动发现
   - 扩展 `scripts/run_cooperative_issuer_website_pipeline.py`
   - 针对披露率<10%的环境指标优先爬取
   - 建立官网ESG报告索引表

2. **Phase 2 (Week 3)**: 集成政府公开数据
   - 生态环境部排污数据API对接
   - 国家能源局统计数据下载
   - 建立外部数据源映射表

3. **Phase 3 (Week 4)**: 数据质量校验
   - 多源数据冲突检测
   - 置信度分级（官方披露 > 公司网站 > 政府统计）

---

### 策略3：历史数据预测（Time Series Prediction）

**目标**: 利用2022-2024历史趋势预测2025缺失值

#### 3.1 预测适用条件
- 公司至少有2年历史数据
- 历史数据CV（变异系数）< 0.5（相对稳定）
- 仅用于研究排名，不用于正式排名
- 必须标注为"predicted"状态

#### 3.2 预测方法
```
方法1：线性趋势外推（适用于单调变化指标）
  - 排放强度类（通常下降趋势）
  - 投入占比类（相对稳定）

方法2：移动平均法（适用于波动指标）
  - 三年移动平均
  - 加权最近年份

方法3：同比增长率法（适用于规模指标）
  - 计算历史平均同比增长率
  - 外推至当前年度
```

#### 3.3 预测指标优先级
**高优先级**（历史稳定性高）：
- Q_G_DEBT_ASSET_RATE（资产负债率）
- Q_S_RD_RATE（研发占比）
- Q_E_ENERGY_INTENSITY（能源强度 - 通常逐年下降）

**中优先级**：
- Q_E_GHG_INTENSITY（温室气体强度）
- Q_S_SAFETY_INVEST_RATE（安全投入）

**不适用预测**：
- 事故类负向指标（离散事件）
- 首次披露的新指标

#### 3.4 实施文件
```python
# 新建: src/aegis_esg/time_series_predictor.py
# 新建: scripts/run_historical_prediction.py
```

---

### 策略4：行业平均值填充（Industry Mean Imputation）

**目标**: 对无法获取的数据使用细分行业均值

#### 4.1 行业分层策略
当前系统已有行业分类（煤炭/油气/电力/新能源），需细化：

```
一级分类      二级分类               公司数估计
----------------------------------------------------------------
煤炭         煤炭开采                ~80
             煤化工                  ~30
油气         石油开采                ~40
             天然气                  ~25
             油气炼化                ~35
电力         火电                    ~150
             水电                    ~60
             核电                    ~10
新能源       风电                    ~80
             光伏                    ~70
             其他新能源              ~52
```

#### 4.2 填充规则
```python
# 伪代码逻辑
if 披露率 < 30%:
    使用一级行业均值（样本量更大，更稳定）
elif 披露率 >= 30% and 二级行业样本量 >= 15:
    使用二级行业均值（更精确）
else:
    使用一级行业均值
```

#### 4.3 填充指标白名单
**允许行业均值填充**（行业特征明显）：
- Q_E_ENERGY_INTENSITY（能源强度 - 行业差异大）
- Q_E_WATER_INTENSITY（水强度 - 火电/煤炭高）
- Q_S_SAFETY_INVEST_RATE（安全投入 - 采矿业高）
- Q_S_RD_RATE（研发占比 - 新能源高）

**禁止行业均值填充**（公司个体差异大）：
- 所有治理指标（公司治理结构个性化）
- Q_S_DIVIDEND_PER_SHARE（分红 - 取决于公司决策）
- 负向指标（事故、处罚）

#### 4.4 透明度要求
- 填充值必须标注"industry_mean_imputed"
- 记录行业样本量和标准差
- 仅用于研究排名，正式排名使用disclosed_weight策略
- 生成专项审计报告列出所有填充项

#### 4.5 实施文件
```python
# 新建: src/aegis_esg/industry_imputation.py
# 修改: src/aegis_esg/scoring.py（增加industry_mean_v1策略）
# 新建: scripts/build_industry_benchmark_baseline.py
```

---

## 三、技术实施优先级

### Phase 1: 快速增量（Week 1-2）
**目标**: 将覆盖率从当前水平提升5-10个百分点

1. **公式派生引擎**（2天）
   - 实现强度类指标派生（收入在财务数据库中覆盖率>90%）
   - 预期覆盖提升：能源强度 9.45% → 25%，水强度 9.77% → 20%

2. **官网ESG报告采集**（5天）
   - 针对前200排名边界企业优先
   - 重点采集环境指标详细披露
   - 预期覆盖提升：SO2强度 4.07% → 12%，NOx强度 6.03% → 15%

3. **数据缺口审计刷新**（1天）
   - 运行 `build_comprehensive_coverage_report.py`
   - 更新 `ranking_disclosure_gap_report`

### Phase 2: 预测模型（Week 3）
**目标**: 对稳定指标提供历史趋势预测

1. **历史数据库构建**（2天）
   - 从2022-2024年报中提取历史序列
   - 建立 `data/historical/indicator_time_series.csv`

2. **预测引擎实现**（3天）
   - 实现线性趋势、移动平均、同比增长三种方法
   - 自动选择最佳预测方法（基于历史拟合度）

3. **预测结果审核**（2天）
   - 生成预测置信区间
   - 人工抽查异常预测值

### Phase 3: 行业基准填充（Week 4）
**目标**: 为研究排名提供完整数据集

1. **行业分类细化**（1天）
   - 建立二级行业映射表
   - 审核分类准确性

2. **行业基准计算**（2天）
   - 计算各指标的行业均值/中位数/标准差
   - 建立 `output/audit/industry_benchmarks_2025.csv`

3. **填充策略实现**（2天）
   - 修改ScoringEngine支持industry_mean_v1策略
   - 生成填充审计报告

4. **全流程验证**（2天）
   - 对比三种缺失策略的排名稳定性
   - 生成敏感性分析报告

---

## 四、数据质量控制

### 4.1 派生数据质量门禁
```python
# 派生值质量检查
def validate_derived_value(original, derived, formula_type):
    # 1. 合理性检查
    if formula_type == "intensity":
        assert 0 <= derived <= original * 10  # 强度不应远超总量
    
    # 2. 同比变化检查
    if has_historical_data:
        yoy_change = abs(derived - last_year) / last_year
        if yoy_change > 0.5:  # 同比变化>50%需人工复核
            flag_for_review()
    
    # 3. 行业离群检查
    industry_z_score = (derived - industry_mean) / industry_std
    if abs(industry_z_score) > 3:  # 3倍标准差外需复核
        flag_for_review()
```

### 4.2 预测值质量门禁
```python
# 预测值置信度评级
def predict_with_confidence(historical_values):
    # 1. 数据点数量
    if len(historical_values) < 2:
        return None, 0.0
    
    # 2. 历史稳定性（CV < 0.5）
    cv = stdev(historical_values) / mean(historical_values)
    if cv > 0.5:
        confidence = 0.3  # 低置信度
    elif cv > 0.3:
        confidence = 0.6  # 中置信度
    else:
        confidence = 0.8  # 高置信度
    
    # 3. 趋势一致性
    if all(v2 > v1 for v1, v2 in zip(historical_values, historical_values[1:])):
        confidence *= 1.1  # 单调趋势，提升10%置信度
    
    return predicted_value, min(confidence, 0.9)
```

### 4.3 填充值透明度要求
所有非原始披露数据必须在输出中明确标注：

```csv
company_code,indicator_code,value,status,source_type,confidence,note
600001,Q_E_ENERGY_INTENSITY,0.85,derived,formula_derived,0.85,"从能耗总量/营业收入派生"
600002,Q_E_GHG_INTENSITY,1.20,predicted,time_series,0.65,"基于2022-2024线性趋势预测"
600003,Q_S_SAFETY_INVEST_RATE,0.03,imputed,industry_mean,0.50,"使用煤炭开采行业均值"
```

---

## 五、预期效果评估

### 5.1 覆盖率提升目标

| 指标类别 | 当前平均覆盖率 | Phase 1 目标 | Phase 2 目标 | Phase 3 目标 |
|---------|--------------|-------------|-------------|-------------|
| 环境强度类（E） | 6.5% | 18% | 25% | 60%* |
| 社会投入类（S） | 13% | 20% | 28% | 55%* |
| 治理财务类（G） | 65% | 70% | 70% | 70% |

*Phase 3包含行业均值填充，仅用于研究排名

### 5.2 排名稳定性评估
运行三种缺失策略对比：
- `legacy_zero_v1`: 当前基线
- `disclosed_weight_v1`: 当前正式排名
- `enriched_research_v1`: 公式+预测+行业均值（新增）

评估指标：
- 前50名重叠率 >= 90%
- 前200名重叠率 >= 85%
- 边界企业（180-220名）稳定性分析

### 5.3 审计追溯能力
每个填充/派生值都能追溯到：
1. 原始数据来源（PDF页码/URL）
2. 派生/预测/填充规则版本
3. 置信度评级
4. 人工复核状态（如需）

---

## 六、风险控制

### 6.1 设计变更隔离
✅ **严格遵守**: 所有优化在现有架构内进行
- 不修改 `Methodology` 权重结构
- 不修改 `ScoringEngine` 核心算法
- 不修改 `GradeFlags` 级别映射
- 新增策略作为 `MissingStrategy` 枚举扩展

### 6.2 数据审计要求
- 所有新增数据源记录在 `data/sources/source_registry.json`
- 所有派生规则版本化在 `src/aegis_esg/formula_derivation.py`
- 所有预测模型参数保存在 `output/audit/prediction_models_v1.json`

### 6.3 回滚机制
每个Phase完成后生成独立快照：
```bash
output/research/2025/phase1_formula_derived/
output/research/2025/phase2_with_prediction/
output/research/2025/phase3_industry_imputed/
```

如发现问题可回退到前一Phase的稳定快照。

---

## 七、实施检查清单

### Week 1-2 (Phase 1)
- [ ] 实现 `src/aegis_esg/formula_derivation.py`
- [ ] 定义17个可派生指标映射
- [ ] 扩展官网采集脚本
- [ ] 运行派生+官网补充
- [ ] 生成Phase 1覆盖率报告
- [ ] 人工抽查100条派生值

### Week 3 (Phase 2)
- [ ] 构建2022-2024历史数据库
- [ ] 实现 `src/aegis_esg/time_series_predictor.py`
- [ ] 计算预测置信度
- [ ] 生成预测审计报告
- [ ] 对比预测vs实际披露（已有数据子集）

### Week 4 (Phase 3)
- [ ] 细化行业二级分类
- [ ] 计算行业基准参数
- [ ] 实现 `src/aegis_esg/industry_imputation.py`
- [ ] 修改 `ScoringEngine` 增加 `industry_mean_v1` 策略
- [ ] 生成三策略对比排名
- [ ] 计算排名稳定性指标

### 交付物
- [ ] 数据覆盖优化技术报告
- [ ] 新增数据源审计日志
- [ ] 派生/预测/填充规则文档
- [ ] Phase 1-3 排名快照
- [ ] 敏感性分析报告

---

## 八、后续维护计划

### 8.1 季度更新
- 每季度刷新行业基准参数
- 验证预测模型准确性
- 更新官网采集URL清单

### 8.2 年度审计
- 对比预测值vs实际披露偏差
- 淘汰准确率<60%的预测指标
- 更新派生公式（如会计准则变化）

### 8.3 正式排名隔离
⚠️ **重要提醒**: 
- 预测值和行业填充值**禁止**进入正式排名
- 正式排名仍使用 `disclosed_weight_v1` 策略
- 派生值可进入正式排名，但需额外人工复核

---

**计划批准**: 待与项目负责人确认后实施  
**预计完成时间**: 4周（2026-08-08 至 2026-09-05）  
**预期成果**: 研究排名数据覆盖率从当前40%提升至60%（包含填充值）
