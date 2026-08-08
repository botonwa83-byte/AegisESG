# 排名分级系统使用指南

**创建时间**: 2026-08-08  
**用途**: 区分基础排名（免费）和高级排名（会员专享）

---

## 📋 系统概述

### 三个排名等级

| 等级 | 名称 | 价格 | 数据来源 | 覆盖率 |
|------|------|------|---------|--------|
| **BASIC** | 基础排名 | 免费 | 仅已披露数据 | ~40% |
| **PREMIUM** | 高级排名 | 会员 | 已披露+预测+填充 | ~85% |
| **PROFESSIONAL** | 专业排名 | 企业版 | 全部+API访问 | ~85% |

### 核心区别

#### 基础排名（免费）
- ✅ 仅使用企业已公开披露的数据
- ✅ 按disclosed_weight策略计算
- ✅ 透明、可审计
- ⚠️ 数据覆盖率较低（~40%）
- ⚠️ 部分企业因披露不足无法评级

#### 高级排名（会员）
- ✅ 使用增强数据（历史预测+行业填充）
- ✅ 数据覆盖率提升至~85%
- ✅ 排名更全面、更稳定
- ✅ 包含数据来源透明标注
- ✅ 提供排名对比分析
- ⚠️ 需要会员权限访问

---

## 🚀 快速使用

### 生成分级排名

```bash
# 步骤1: 确保已有基础观测和增强观测
# 基础观测: data/review/all_markets_indicator_confirmed_v22_2025.csv
# 增强观测: output/research/2025/enhanced_observations_v3_industry_filled.csv

# 步骤2: 运行分级排名生成
PYTHONPATH=src python3 scripts/generate_tiered_rankings.py \
    data/review/all_markets_indicator_confirmed_v22_2025.csv \
    output/research/2025/enhanced_observations_v3_industry_filled.csv \
    --methodology data/methodologies/energy_esg_2025.json \
    --output-dir output/research/2025/tiered_rankings \
    --top-n 200
```

### 输出文件

```
output/research/2025/tiered_rankings/
├── basic_ranking.json          # 基础排名（免费）
├── premium_ranking.json        # 高级排名（会员）
├── ranking_comparison.json     # 排名对比分析
└── access_control.json         # 访问控制说明
```

---

## 📊 数据结构

### 基础排名输出

```json
{
  "summary": {
    "tier": "basic",
    "tier_name": "基础排名",
    "company_count": 612,
    "total_observations": 7988,
    "observation_by_status": {
      "confirmed": 7988
    },
    "average_coverage_rate": 0.40,
    "features": [
      "企业已披露数据",
      "行标权重评分",
      "E/S/G分项得分"
    ],
    "price_info": "免费"
  },
  "ranking": {
    "tier": "基础排名",
    "companies": [
      {
        "rank": 1,
        "company_code": "600900.SH",
        "company_name": "长江电力",
        "total_score": 85.32,
        "grade": "AA",
        "dimension_scores": {"E": 38.5, "S": 16.8, "G": 30.02},
        "disclosure_rate": 65.4
      }
    ]
  }
}
```

### 高级排名输出

```json
{
  "summary": {
    "tier": "premium",
    "tier_name": "高级排名",
    "company_count": 612,
    "total_observations": 14190,
    "observation_by_status": {
      "confirmed": 7988,
      "imputed": 6202
    },
    "enhanced_observations": 6202,
    "enhanced_ratio": 0.437,
    "average_coverage_rate": 0.85,
    "features": [
      "✓ 基础排名所有功能",
      "✓ 时间序列预测数据",
      "✓ 行业均值填充",
      "✓ 数据覆盖率提升80%+"
    ],
    "price_info": "会员专享"
  },
  "ranking": {
    "tier": "高级排名",
    "companies": [
      {
        "rank": 1,
        "company_code": "600900.SH",
        "company_name": "长江电力",
        "total_score": 86.15,
        "grade": "AA",
        "dimension_scores": {"E": 39.2, "S": 17.5, "G": 29.45},
        "disclosure_rate": 89.3,
        "indicator_details": [...],  // 详细指标（会员专享）
        "data_sources": {            // 数据来源（会员专享）
          "Q_E_GHG_INTENSITY": {
            "status": "imputed",
            "source_type": "industry_mean_imputed",
            "confidence": 0.65
          }
        }
      }
    ]
  }
}
```

### 排名对比输出

```json
{
  "comparison_summary": {
    "total_companies": 612,
    "rank_up": 287,              // 排名上升的企业
    "rank_down": 285,            // 排名下降的企业
    "rank_same": 40,             // 排名不变的企业
    "top_200_overlap": 175,      // 前200名重叠企业数
    "top_200_overlap_rate": 87.5 // 前200名重叠率
  },
  "comparisons": [
    {
      "company_code": "600900.SH",
      "company_name": "长江电力",
      "basic_rank": 2,
      "premium_rank": 1,
      "rank_change": 1,           // 上升1位
      "basic_score": 85.32,
      "premium_score": 86.15,
      "score_change": 0.83,
      "basic_coverage": 0.654,
      "premium_coverage": 0.893,
      "coverage_improvement": 0.239
    }
  ]
}
```

---

## 🔐 访问控制

### 在代码中使用

```python
from aegis_esg.ranking_tier import RankingTier, RankingTierManager

# 创建管理器
tier_manager = RankingTierManager()

# 检查用户权限
user_tier = RankingTier.BASIC  # 用户当前等级
requested_tier = RankingTier.PREMIUM  # 请求的排名等级

has_access, reason = tier_manager.check_access_permission(user_tier, requested_tier)

if not has_access:
    print(f"访问被拒绝: {reason}")
    # 输出: 访问被拒绝: 访问高级排名需要升级会员等级（会员专享）
else:
    # 允许访问高级排名
    pass
```

### 过滤观测数据

```python
from aegis_esg.ranking_tier import RankingTier, RankingTierManager
from aegis_esg.io import load_observations_from_csv

# 加载全部观测（含增强数据）
all_observations = load_observations_from_csv("enhanced_observations.csv")

tier_manager = RankingTierManager()

# 基础用户：只保留已披露数据
basic_obs = tier_manager.filter_observations_by_tier(
    all_observations,
    RankingTier.BASIC,
)
# 结果：只包含status=CONFIRMED的观测

# 高级用户：保留全部增强数据
premium_obs = tier_manager.filter_observations_by_tier(
    all_observations,
    RankingTier.PREMIUM,
)
# 结果：包含CONFIRMED + PREDICTED + IMPUTED + DERIVED
```

---

## 📈 排名对比分析

### 关键指标

1. **排名稳定性**
   - 前200名重叠率：衡量两种排名的一致性
   - 目标：≥85%（说明排名相对稳定）

2. **排名变化**
   - 上升企业：数据增强后排名提升
   - 下降企业：其他企业数据补全后相对排名下降
   - 不变企业：排名位置保持稳定

3. **得分变化**
   - 得分提升：数据覆盖率提高带来的得分增加
   - 覆盖率改善：从~40%提升至~85%

### 使用场景

- **用户升级转化**：展示高级排名的价值
- **数据质量验证**：检查增强数据的合理性
- **排名透明度**：说明两种排名的区别

---

## ⚠️ 重要说明

### 评分算法一致性 ✅
- ✅ **基础排名和高级排名使用相同的评分算法**
- ✅ **权重体系完全一致**
- ✅ **唯一区别是输入数据的完整性**
- ✅ **不修改总分计算公式**

### 数据透明度 ✅
- ✅ 所有增强数据标注来源（predicted/imputed/derived）
- ✅ 记录置信度（0.3-0.9）
- ✅ 生成详细审计报告
- ✅ 用户可查看数据来源

### 使用限制 ⚠️
- ⚠️ 高级排名仅用于研究和会员服务
- ⚠️ 正式评级报告仍使用基础排名（已披露数据）
- ⚠️ 增强数据不能替代企业实际披露

---

## 🔄 更新和维护

### 定期更新
1. **季度更新**：刷新行业基准参数
2. **年度更新**：重新计算历史预测模型
3. **数据源扩展**：增加新的数据采集渠道

### 版本管理
- 每次方法论变更需要升级版本号
- 保留历史排名用于对比分析
- 记录数据增强策略的变更

---

## 📞 技术支持

**模块位置**: `src/aegis_esg/ranking_tier.py`  
**示例脚本**: `scripts/generate_tiered_rankings.py`  
**文档**: `docs/ranking-tier-guide.md`

---

**创建者**: Claude  
**最后更新**: 2026-08-08
