# 🚀 紧急修复进行中

## 问题根源确认

**致命缺陷**：
- `_rule`函数：标签 + 数值 + 单位
- 实际格式：标签 + 单位 + 数值
- **顺序完全相反！**

这就是为什么：
- 新增23个规则几乎都不起作用
- 环境指标仅5-16%
- 社会指标仅5-25%

## 正在修复

### 已添加DirectRule（正确模式）
1. ✅ Q_E_GHG_INTENSITY - 温室气体
2. ✅ Q_E_ENERGY_INTENSITY - 能源强度
3. ✅ Q_E_WATER_INTENSITY - 水资源
4. ✅ Q_E_NOX_INTENSITY - NOx
5. ✅ Q_E_SO2_INTENSITY - SO2
6. ✅ Q_S_PAY_PER_EMPLOYEE - 员工薪酬
7. ✅ Q_S_ENV_INVEST_RATE - 环保投入

### 继续添加中...

需要为所有环境和社会指标添加DirectRule，
预计提取率将大幅提升！
