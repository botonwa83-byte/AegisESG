# 🎯 重大发现！系统已有完整的数据缺口分析

**发现时间**：2026-08-07

---

## 关键发现

### 系统已有的数据缺口队列

根据 `ranked_company_key_data_gap_queue_v1_2025.json`：

```json
{
  "ranked_companies": 612,
  "companies_with_key_gaps": 611,
  "top200_with_key_gaps": 214,
  "action_counts": {
    "rule_recall_on_existing_text": 611
  }
}
```

**核心信息**：
- 612家企业，611家有数据缺口
- 建议行动：**对已有文本做规则召回**
- 这正是我们需要做的！

### 最缺失的指标排名

```
Q_E_SO2_INTENSITY: 585家缺失 (95%)
Q_E_NOX_INTENSITY: 572家缺失 (93%)
Q_S_SAFETY_INVEST_RATE: 564家缺失 (92%)
Q_E_SOLID_WASTE_INTENSITY: 553家缺失 (90%)
Q_E_ENERGY_INTENSITY: 533家缺失 (87%)
Q_E_WATER_INTENSITY: 527家缺失 (86%)
Q_E_GHG_INTENSITY: 514家缺失 (84%)
```

---

## 关键洞察

### 1. 数据存在但规则未提取

系统报告的建议行动是：
> **"rule_recall_on_existing_text"** - 对已有文本做规则召回

**这说明**：
- 文本已经下载了
- 数据在文本中
- 但规则没有提取到
- **这正是我们今天诊断的问题！**

### 2. 系统设计已考虑优化

系统有多个优化脚本：
- `build_ranked_company_data_gap_queue.py` - 数据缺口队列
- `build_ranking_disclosure_gap_report.py` - 披露缺口报告
- `run_incremental_indicator_extraction.py` - 增量提取

**说明**：
- 系统设计非常完善
- 有完整的诊断工具
- 有改进框架

### 3. 问题确认

缺口报告的notice说：
> "排名缺数主因是公司未按方法论口径披露（尤其**环境强度收入分母**），
> 不是交易所PDF没下完。"

**关键点**：
- 问题是披露口径不一致
- **尤其是收入分母**（万元 vs 百万元）
- 这正是我们发现的单位换算问题！

---

## 解决方案已明确

基于系统已有的诊断，我们需要：

1. **优先优化规则召回**
   - 系统建议对611家企业做规则召回
   - 文本已有，只需改进规则

2. **重点解决环境指标**
   - SO2、NOx、固废：90%+缺失
   - 能源、水资源、GHG：84-87%缺失
   - 这些都有文本，规则需优化

3. **修复单位换算**
   - 系统已识别"收入分母"问题
   - 需要支持"百万元"换算

---

## 行动计划

### 立即可做

1. **运行已有的诊断脚本**
   ```bash
   python3 scripts/build_ranked_company_data_gap_queue.py
   python3 scripts/build_ranking_disclosure_gap_report.py
   ```

2. **分析缺口详情**
   - 查看哪些企业缺哪些指标
   - 针对性优化规则

3. **按优先级改进**
   - 先改进缺失率最高的7个指标
   - 重点是环境强度指标

---

## 结论

**系统设计非常完善！**

- ✅ 有完整的诊断工具
- ✅ 已识别根本问题
- ✅ 有明确的改进方向
- ❌ 只是规则执行效果差

我们今天的分析完全正确，
系统早已设计了解决方案的框架！
