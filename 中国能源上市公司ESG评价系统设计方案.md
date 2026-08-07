# 中国能源上市公司可持续发展ESG评价系统 —— 设计与部署方案

版本：v2.3（2026-08-07更新：客户方法论对齐验证 + 数据缺口分析）  
适用场景：投研 / 合规 / 评级业务对接  
部署环境：2台物理服务器 + 1台见证节点，Linux Rocky 10

> **方法论真相源**：现行实现以电力行业标准 **DL/T 2971—2025** 附录 A（37项定量）/
> 附录 B（43项定性）及第6.4节权重（定量80%/定性20%，E/S/G=45%/20%/35%）为准，落盘于
> `data/methodologies/energy_esg_2025.json`（兼容版）及待冻结的 `DLT2971-2025-v1`。
> 下文 2.2–2.3 中早期”约31项 + AHP/熵权”设想仅作历史对照，**不得作为现行评分依据**。

> **⚠️ 重要发现（2026-08-07）**：
> 1. **评分引擎已完美实现客户方法** - `src/aegis_esg/scoring.py` 中的正态分布算法完全符合客户2025年报告要求，无需重写
> 2. **方法论配置正确** - `data/methodologies/energy_esg_2025.json` 包含正确的37+43指标和E:S:G权重
> 3. **核心问题是数据缺失** - 15个定量指标无数据（32.83%权重），43个定性指标未实现（20分）
> 4. **不要重新造轮子** - 开发前务必先读懂现有代码，避免重复实现已有功能
> 5. **优先补数据而非改算法** - 当前得分偏低是数据覆盖问题，不是算法问题

---

## 零、系统当前状态与开发指南（2026-08-07更新）

### 0.1 核心架构已完成 ✅

**评分引擎** (`src/aegis_esg/scoring.py`)：
- ✅ 正态分布评分算法完全实现（正向/负向/双向）
- ✅ 1%/99%缩尾处理
- ✅ 定性指标0/20/50/80/100档评分
- ✅ E/S/G维度分解
- ✅ 定量80%+定性20%合成
- **结论：评分算法无需修改，完全符合客户要求**

**方法论配置** (`data/methodologies/energy_esg_2025.json`)：
- ✅ 37个定量指标（含权重、方向、benchmark）
- ✅ 43个定性指标（代码前缀X_）
- ✅ 维度权重 E:S:G = 45:20:35
- ✅ 定量/定性 = 80:20
- **结论：配置正确，直接使用此文件评分**

### 0.2 数据缺口分析 ⚠️

**定量指标覆盖率**：22/37（59.5%）

**缺失的15个定量指标**（总权重32.83%）：

**公司治理（9个，15.70%权重）**：
```
Q_G_DIVIDEND_PER_SHARE       现金分红              2.80%  需从利润分配表提取
Q_G_DEBT_RATIO               资产负债率            2.80%  需从资产负债表计算
Q_G_ROTA                     总资产收益率          2.80%  需从利润表+资产负债表计算
Q_G_TWO_FUNDS_RATIO          两金占流动资产比      2.10%  需从资产负债表计算
Q_G_EBITDA_INTEREST_COVER    EBITDA利息倍数       2.80%  需从利润表+现金流量表计算
Q_G_OPERATING_CASH_RATE      营业收现率            1.40%  ✅已计算（248家）
Q_G_COST_REVENUE_RATIO       成本费用占比          1.40%  ✅已计算（248家）
```

**社会责任（6个，9.31%权重）**：
```
Q_S_EMPLOYEE_SALARY          员工薪酬              2.80%  需从应付职工薪酬/员工人数
Q_S_CHARITY_RATE             公益投入占比          3.00%  需从ESG报告提取
Q_S_UNIONIZATION_RATE        工会覆盖率            0.75%  需从ESG报告提取
Q_S_TRAINING_COVERAGE        培训覆盖率            0.90%  需从ESG报告提取
Q_S_TRAINING_HOURS           培训时长              0.90%  需从ESG报告提取
Q_S_EMPLOYEE_SATISFACTION    员工满意度            0.90%  需从ESG报告提取
```

**环境（2个，6.28%权重）**：
```
Q_E_RECYCLED_WATER_RATE         再生水使用比例     2.46%  需从环境报告提取
Q_E_HAZARDOUS_WASTE_INTENSITY   危废排放强度       3.82%  需从环境报告提取
```

**定性指标覆盖率**：0/43（0%）
- 占总分20%
- 需要文本评估框架（规则引擎或LLM）
- 评分标准：0/20/50/80/100五档

### 0.3 当前排名质量

**使用客户方法论评分结果**：
- 企业数：612家
- Top 1：帝尔激光 52.70分（定量49.42 + 定性65.83）
- 客户2024年Top 1：阳光电源 71.98分
- **差距：-19.28分（-26.8%）**

**差距原因**：
1. 15个定量指标缺失（影响-12~-15分）
2. 43个定性指标未正确实现（影响-5~-7分）

### 0.4 开发优先级与实施路径 🎯

**阶段1：补充定量指标（2周）**

优先级排序（按权重和难度）：
1. **财务基础指标**（高权重+易获取）：
   - 现金分红（2.80%）- 从利润分配表
   - 资产负债率（2.80%）- 简单计算
   - 总资产收益率（2.80%）- 简单计算
   
2. **财务衍生指标**（中等权重+需计算）：
   - EBITDA利息倍数（2.80%）
   - 两金占流动资产比（2.10%）

3. **社会责任指标**（低权重+需提取）：
   - 员工薪酬（2.80%）- 从财报附注
   - 公益投入（3.00%）- 从ESG报告
   - 其他4个（各0.75-0.90%）

4. **环境指标**（中等权重+需提取）：
   - 危废排放强度（3.82%）
   - 再生水使用比例（2.46%）

**阶段2：定性指标实现（3-4周）**

方案选择：
- **方案A（快速）**：关键词规则引擎 → 0/20/50三档
- **方案B（准确）**：LLM文本评估 → 20/50/80/100四档
- **方案C（推荐）**：混合方案（规则初筛+LLM优化）

实施步骤：
1. 建立43个指标的评分标准库
2. 实现规则引擎（披露完整性评分）
3. 集成LLM API（Claude/GPT-4）
4. 人工抽查验证（Top 100企业）

**阶段3：验证与优化（1周）**
1. 与客户2024年Top 200逐一对比
2. 调整评分参数（benchmark值）
3. 生成最终排名报告

### 0.5 开发规范 ⚠️

**务必遵守的原则**：

1. **先读懂现有代码，不要重复造轮子**
   - 评分引擎已完美实现 → 不要重写
   - 方法论配置已正确 → 直接使用
   - 数据IO工具已完善 → 直接调用

2. **使用正确的方法论文件**
   ```bash
   # ✅ 正确
   --methodology data/methodologies/energy_esg_2025.json
   
   # ❌ 错误（这是80指标研究版）
   --methodology data/methodologies/energy_esg_2025_research_sasac.json
   ```

3. **数据文件命名规范**
   ```
   ci_merged_all_sources_v1_2025.csv          # 原始合并数据
   ci_merged_with_calculated_v1_2025.csv      # 加入计算指标
   ci_merged_with_extracted_v2_2025.csv       # 加入提取指标
   ci_merged_complete_v3_2025.csv             # 完整数据集
   ```

4. **评分输出目录规范**
   ```
   output/audit/client_method_ranking_2025/        # v1：22个指标
   output/audit/client_method_ranking_v2_2025/     # v2：24个指标
   output/audit/client_method_ranking_final_2025/  # 最终版：37+43指标
   ```

5. **不要猜测缺失指标的代码名**
   - 所有指标代码必须在方法论JSON中定义
   - 不能自创指标代码（如Q_G_REVENUE）
   - 计算新指标前先检查方法论定义

### 0.6 快速验证命令

**生成排名（使用客户方法论）**：
```bash
PYTHONPATH=./src python3 -m aegis_esg.cli \
  --methodology data/methodologies/energy_esg_2025.json \
  score output/audit/ci_merged_all_sources_v1_2025.csv \
  --mode research \
  --missing-strategy legacy_zero_v1 \
  --output-dir output/audit/test_ranking \
  --title "测试排名" \
  --limit 10
```

**检查方法论指标**：
```bash
python3 -c "
import json
with open('data/methodologies/energy_esg_2025.json') as f:
    m = json.load(f)
    quant = [i for i in m['indicators'] if i.get('kind') != 'qualitative']
    print(f'定量指标: {len(quant)}')
    for i in quant[:5]:
        print(f'  {i[\"code\"]}: {i[\"name\"]} ({i[\"weight\"]}%)')
"
```

**验证数据覆盖**：
```bash
python3 -c "
import csv, json
with open('data/methodologies/energy_esg_2025.json') as f:
    defined = {i['code'] for i in json.load(f)['indicators'] if i.get('kind') != 'qualitative'}
with open('output/audit/ci_merged_all_sources_v1_2025.csv') as f:
    existing = {row['indicator_code'] for row in csv.DictReader(f)}
print(f'定量指标定义: {len(defined)}')
print(f'有数据指标: {len(existing & defined)}')
print(f'缺失指标: {len(defined - existing)}')
"
```

### 0.7 重要文档索引

- **评分引擎源码**：`src/aegis_esg/scoring.py`（第393-414行：核心评分算法）
- **客户方法论**：`data/methodologies/energy_esg_2025.json`
- **对齐分析报告**：`output/audit/CLIENT_SCORING_ALIGNMENT_2026_08_07.md`
- **最终状态报告**：`output/audit/FINAL_STATUS_REPORT_2026_08_07.md`
- **工作总结**：`output/audit/WORK_SUMMARY_2026_08_07_CLIENT_ALIGNMENT.md`

---

## 一、总体设计思路

系统分三层交付：

1. **方法论层**：可对外披露、可复现、可审计的ESG指标体系与评分模型 —— 业务对接（投研/合规/评级）的核心，评级结果必须能向监管、客户、被评价公司解释清楚"为什么打这个分"。
2. **系统实现层**：数据采集 → 清洗入库 → 指标计算 → 评分与排名 → 可视化/API输出。
3. **集群部署层**：基于K3s + TiDB的两节点+见证节点高可用架构，部署在Rocky 10上。

业务约束（因为要对接实际业务，而非仅做研究展示）：

- **可解释性优先**：不用黑箱机器学习模型做最终评分；正式算法采用行标固定权重 + 正态/优秀值峰打分，任何一次评分都能拆解到具体指标和原始数据来源。
- **可审计留痕**：原始数据（PDF年报、公告链接、采集时间戳）与计算过程全部落库，评分结果可追溯到源文件的具体页码/字段。
- **可复现**：同一批数据、同一版本方法论，任何时候重算结果一致；方法论版本化管理，指标体系调整不覆盖历史评分。
- **真正的高可用**：数据库和K8s控制面的故障切换必须是自动的，不依赖人工介入——这要求在架构层面解决"两台物理机无法形成quorum多数"的问题（见第四章）。

### 1.1 双轨算法与三级输出（v2.1调整）

系统共享同一套原始文档、结构化事实和证据链，但评分算法物理隔离：

1. **自动预排名算法**：系统自有、可解释、版本化，无需人工参与；允许使用机器定性判断和明确的
   缺失值策略，输出覆盖率、可信等级及多情景敏感性，不作为正式评级；
2. **客户正式算法**：严格执行客户确认的公司池、指标、权重、缺失规则和定性档位；高风险项目经
   单审、双审或仲裁后冻结，不为迎合预期名次修改规则；对齐 DL/T 2971 时额外要求治理优秀值齐全、
   表1级别输出、一年有效期与评价组长签名；
3. **审核候选排名**：作为两者之间的增量结果，用来识别哪些未审任务仍可能改变名次或前200边界。

模型风险控制重点不是让人工审核所有格子，而是对主体身份、实质冲突、定性80/100、高权重弱证据
和排名敏感项强制审核，对低风险严格派生执行分层抽样。任何自动决定都必须保存证据、规则版本、
置信度和适用的排名模式。

---

## 二、ESG评价方法论

### 2.1 指标体系设计原则

- **行业针对性**：以能源企业为适用范围（煤炭、油气、电力、新能源等），指标口径对齐 DL/T 2971。
- **数据可得性**：三级指标必须能从公开渠道（年报、社会责任报告、ESG专项报告、环保部门处罚公告、交易所公告）获取。
- **正逆/双向区分**：环境与社会按正向/负向样本正态打分；治理参考国资委工业优秀值（正/负向单侧衰减，双向以优秀值为峰）。
- **参照标准**：规范性依据为 DL/T 2971—2025；并兼容交易所可持续披露指引、GRI、IFRS S1/S2 等作为披露对照，而非替代行标权重。

### 2.2 三级指标体系（现行：80项）

**一级：环境保护(E) / 社会责任(S) / 公司治理(G)**  
在定量、定性各自满分100内，E/S/G 权重分别为 **45% / 20% / 35%**；总分  
`S = S_定量 × 80% + S_定性 × 20%`。

定量 12 个二级、37 个三级；定性 17 个二级、43 个三级。完整编码与权重见  
`data/methodologies/energy_esg_2025.json`，与行标附录 A/B 一一对应。

级别符号按表1：AAA[90,100] … C[20,30)、NA（分值&lt;20，或披露率&lt;50%，或重大事故/瞒报等显式flag）。

### 2.3 权重与打分（现行，非 AHP）

1. **权重**：采用行标附录固定权重，不做 AHP/熵权重标定；方法论变更必须升版本并重算。
2. **环境/社会定量**：披露样本正态 + Z 分数方向化（兼容版在优秀值缺失时对治理亦用样本中心，须标注）。
3. **治理定量**：配置 `benchmark`（国资委工业优秀值）后，按优秀值峰单/双侧衰减；注入命令见 README。
4. **定性**：达成率 100/80/50/20（工程扩展允许 0 表示未披露），乘以指标权重。
5. **正式发布**：`score --mode release --require-dlt-process` 校验一年有效期、evaluation_lead 与治理优秀值齐全。

> 历史设想（约31项三级指标、AHP+熵权组合赋权、min-max 标准化）已废弃，仅保留在版本历史中供对照。

### 2.4 级别与有效期

- 级别：`grade.py` 按表1映射；NA 优先于分值档。
- 有效期：正式结果一年；`prepare-release-authorization --seal-validity` 写入窗口。
- 评价形式：默认第三方主动评价（公开资料）；委托评价的现场尽调不在自动流水线内强制。

---

## 三、数据采集方案

### 3.1 数据来源

| 数据类型 | 来源 | 获取方式 |
|---|---|---|
| 定期报告（年报/半年报） | 巨潮资讯网 cninfo.com.cn | 公开API/页面抓取，PDF下载 |
| ESG/社会责任报告 | 巨潮资讯网、公司官网投资者关系页 | PDF下载 |
| 临时公告（处罚、事故、关联交易） | 上交所/深交所/北交所官网、巨潮资讯网 | 页面抓取 |
| 监管处罚信息 | 证监会官网、交易所纪律处分公告 | 页面抓取 |
| 环保处罚信息 | 生态环境部"环境行政处罚决定书"公开平台、各省市生态环境厅 | 页面抓取 |
| 安全生产事故信息 | 应急管理部/国家矿山安全监察局公告 | 页面抓取 |
| 行业统计数据 | 国家能源局、国家统计局 | 公开数据下载 |
| 股权与治理结构 | 交易所公开的公司治理专栏 | 页面抓取 |
| 商业数据库（如有采购） | Wind、同花顺iFinD | 官方API（合规付费接口，优先使用，减少自建爬虫维护成本） |

> 核心结构化数据（财务、股权、处罚记录）优先走Wind/iFinD等合规商业API，自建爬虫主要覆盖ESG报告全文、临时公告这类非结构化/长尾数据，降低反爬和合规风险。

### 3.2 采集技术方案

- **抓取框架**：Python + Scrapy（结构化列表页）+ requests/httpx（详情页与文件下载），PDF解析用 `pdfplumber` / `PyMuPDF`，扫描件走OCR（`PaddleOCR`）。
- **反爬与稳定性**：请求限速、随机User-Agent、代理池（如有需要）、断点续传，所有抓取任务记录采集日志（URL、时间戳、HTTP状态、文件hash）便于审计。
- **调度**：Celery Beat定期报告采集按财报季（4月/8月/10月）加密度调度，公告类每日增量抓取。
- **文件存储**：原始PDF/HTML落地对象存储或本地文件系统（`/data/raw/公司代码/年度/文件类型/`），数据库只存结构化字段+文件路径引用。

### 3.3 数据清洗与ETL

1. **抽取**：从PDF年报/ESG报告中按关键词+表格识别抽取指标数值。
2. **校验**：单位统一、量纲检查、同比异常波动预警（触发人工复核队列，不自动入库覆盖历史数据）。
3. **归集**：按公司代码+报告期+指标编码写入标准化事实表。
4. **人工复核环节**：定性指标和抽取置信度低的字段进入复核队列，业务人员在系统内确认后才计入正式计算。

---

## 四、系统架构设计（K3s + TiDB 两节点+见证节点高可用架构）

### 4.1 为什么不是普通K8s + 主从MySQL

只有2台物理服务器时，任何依赖多数派（quorum）机制的系统——K8s的etcd、MySQL Group Replication、TiDB的PD/Raft——都无法实现真正的自动故障切换：2票里丢1票就跌破"多数"门槛。这不是配置问题，是分布式一致性协议的数学约束。

解决方案是**加一台低配见证节点**（2核4G即可，云VM或闲置小机器都行），凑够3个quorum投票者，同时做架构收敛：

**关键点：K3s支持把控制面状态存到外部MySQL协议数据库（`datastore-endpoint`参数），而TiDB是MySQL协议兼容的分布式数据库。** 因此K3s不需要自己再跑一套etcd Raft——直接把K3s server指向TiDB集群，只用TiDB一套Raft同时支撑"业务数据"和"K8s控制面状态"两件事，避免维护两套独立的quorum系统。

### 4.2 技术栈选型

| 层 | 选型 | 说明 |
|---|---|---|
| 操作系统 | Rocky Linux 10 | RHEL兼容，SELinux默认开启 |
| 分布式数据库 | TiDB（PD + TiKV + TiDB SQL层） | MySQL协议兼容，Raft原生高可用，同时承担业务数据和K3s控制面存储 |
| K8s发行版 | K3s（external datastore模式，指向TiDB） | 轻量，不需要单独维护etcd |
| 缓存/队列 | Redis（单实例，暂不上Sentinel） | 见4.3节权衡说明 |
| 后端服务 | Python 3.12 + FastAPI | 计算引擎+对外API |
| 任务调度 | Celery | 采集任务、指标计算批处理 |
| 爬虫层 | Scrapy + Playwright（动态页面兜底） | |
| 前端/可视化 | Vue3 + ECharts，或Metabase | 业务对接场景优先复用成熟BI工具 |
| 反向代理 | Nginx | TLS终结、静态资源、API网关 |
| 容器化 | Podman/containerd（K3s自带） | Rocky系官方推荐 |

### 4.3 节点角色分配

| 组件 | 服务器A | 服务器B | 见证节点(2C4G) |
|---|---|---|---|
| TiDB PD | ✓ | ✓ | ✓（投票用） |
| TiKV | ✓（正常规格） | ✓（正常规格） | ✓（小规格，配置evict-leader-scheduler，避免扛读写压力） |
| TiDB SQL层 | ✓ | ✓ | 不需要 |
| K3s server（datastore指向TiDB） | ✓ | ✓ | 不跑 |
| 业务Pod（FastAPI/Celery/Scrapy/Nginx） | ✓ | ✓ | 不跑 |
| Redis | ✓（单实例，pod affinity固定） | 备用 | 不跑 |

**Redis权衡说明**：Redis Sentinel/Cluster又是一套独立quorum系统，在两节点+见证的架构里投入产出比不划算。Celery队列丢失in-flight任务的风险，对ESG评分这种非实时业务可接受（重跑一次采集/计算任务成本很低）。如果后续更看重这块可靠性，建议把关键任务队列改造成基于TiDB表的轻量队列，复用已有的HA能力，而不是再引入一套Redis HA。

### 4.4 模块架构

```
┌─────────────────────────────────────────────────────────┐
│                     展示/业务对接层                        │
│   BI看板(Metabase/自建Vue) │ 对外评级API │ 报告导出(docx/pdf) │
└───────────────────────────┬───────────────────────────────┘
                             │
┌───────────────────────────▼───────────────────────────────┐
│                       计算引擎层 (FastAPI，K3s Pod)          │
│  指标计算服务 │ 权重管理与版本控制 │ 评分/排名/趋势分析服务      │
└───────────────────────────┬───────────────────────────────┘
                             │
┌───────────────────────────▼───────────────────────────────┐
│                   数据清洗/复核层 (Celery Worker，K3s Pod)    │
│   PDF解析/NLP抽取 │ 数据校验与异常预警 │ 人工复核队列(Web表单)  │
└───────────────────────────┬───────────────────────────────┘
                             │
┌───────────────────────────▼───────────────────────────────┐
│                       数据采集层 (Scrapy，K3s Pod)            │
│  定期报告采集 │ 公告采集 │ 处罚/事故公开数据采集 │ 商业API对接    │
└───────────────────────────┬───────────────────────────────┘
                             │
┌───────────────────────────▼───────────────────────────────┐
│   TiDB集群（PD×3 + TiKV×3，跨A/B/见证节点）                   │
│   —— 同时承载业务数据 与 K3s控制面状态(kine/datastore) ——     │
└─────────────────────────────────────────────────────────┘
```

### 4.5 数据库核心表设计（TiDB / MySQL协议语法）

```sql
-- 公司主表
CREATE TABLE dim_company (
    company_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    stock_code      VARCHAR(10) UNIQUE NOT NULL,
    company_name    VARCHAR(100) NOT NULL,
    sub_industry    VARCHAR(50),          -- 煤炭/石油石化/电力/新能源
    listing_board   VARCHAR(20),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 指标定义表（方法论版本化）
CREATE TABLE dim_indicator (
    indicator_id    BIGINT AUTO_INCREMENT PRIMARY KEY,
    indicator_code  VARCHAR(30) UNIQUE NOT NULL,
    dimension       ENUM('E','S','G') NOT NULL,
    level2_name     VARCHAR(100),
    level3_name     VARCHAR(100),
    direction       ENUM('POS','NEG') NOT NULL,
    data_source     VARCHAR(100),
    methodology_version VARCHAR(20)
);

-- 权重表（按方法论版本+指标存权重，支持历史回溯）
CREATE TABLE fact_weight (
    weight_id       BIGINT AUTO_INCREMENT PRIMARY KEY,
    indicator_id    BIGINT NOT NULL REFERENCES dim_indicator(indicator_id),
    methodology_version VARCHAR(20),
    weight_ahp      DECIMAL(6,4),
    weight_entropy  DECIMAL(6,4),
    weight_final    DECIMAL(6,4),
    effective_date  DATE
);

-- 原始采集数据表（含审计字段）
CREATE TABLE fact_raw_data (
    raw_id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    company_id      BIGINT NOT NULL REFERENCES dim_company(company_id),
    indicator_id    BIGINT NOT NULL REFERENCES dim_indicator(indicator_id),
    report_period   VARCHAR(10),   -- e.g. 2025FY
    raw_value       DECIMAL(18,4),
    raw_text        TEXT,          -- 定性指标原文
    source_file_path VARCHAR(500),
    source_page     INT,
    extract_method  ENUM('rule','nlp','manual'),
    confidence      DECIMAL(3,2),
    review_status   ENUM('pending','confirmed','rejected') DEFAULT 'pending',
    collected_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 标准化与得分表
CREATE TABLE fact_indicator_score (
    company_id      BIGINT NOT NULL,
    indicator_id    BIGINT NOT NULL,
    report_period   VARCHAR(10) NOT NULL,
    normalized_score DECIMAL(6,2),
    methodology_version VARCHAR(20) NOT NULL,
    PRIMARY KEY (company_id, indicator_id, report_period, methodology_version)
);

-- 综合评分表
CREATE TABLE fact_esg_score (
    company_id      BIGINT NOT NULL,
    report_period   VARCHAR(10) NOT NULL,
    methodology_version VARCHAR(20) NOT NULL,
    score_e         DECIMAL(6,2),
    score_s         DECIMAL(6,2),
    score_g         DECIMAL(6,2),
    score_total     DECIMAL(6,2),
    rating_grade    VARCHAR(5),   -- AAA/AA/A/BBB...
    industry_rank   INT,
    calculated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, report_period, methodology_version)
);
```

### 4.6 后端服务要点

- **API设计**：`/api/v1/companies/{code}/score`、`/api/v1/companies/{code}/score/detail`（下钻到三级指标与原始数据来源）、`/api/v1/rankings?industry=&period=`。
- **异步计算**：批量重算全市场评分走Celery后台任务；单公司即时查询走Redis缓存（TTL到下次数据更新）。
- **鉴权**：API Key + 调用配额管理（FastAPI中间件），区分内部投研用户与外部客户权限。

---

## 五、集群部署方案（Rocky 10）

### 5.1 硬件与端口规划

| 节点 | 角色 | 关键端口 |
|---|---|---|
| 服务器A | TiDB PD/TiKV/TiDB + K3s server + 业务Pod | PD 2379/2380，TiKV 20160，TiDB 4000/10080，K3s 6443/10250 |
| 服务器B | TiDB PD/TiKV/TiDB + K3s server + 业务Pod | 同上 |
| 见证节点 | TiDB PD/TiKV（低leader-weight，仅投票） | PD 2379/2380，TiKV 20160 |

### 5.2 第一步：三台机器部署TiDB集群（TiUP）

```bash
# 三台机器都需要的基础准备
sudo dnf install -y numactl
curl --proto '=https' --tlsv1.2 -sSf https://tiup-mirrors.pingcap.com/install.sh | sh
source ~/.bashrc
```

在服务器A（作为部署控制机）编写 `topology.yaml`：

```yaml
pd_servers:
  - host: <服务器A_IP>
  - host: <服务器B_IP>
  - host: <见证节点_IP>

tikv_servers:
  - host: <服务器A_IP>
  - host: <服务器B_IP>
  - host: <见证节点_IP>
    config:
      raftstore.capacity: "50GB"   # 见证节点小规格，容量按需调低

tidb_servers:
  - host: <服务器A_IP>
  - host: <服务器B_IP>
```

```bash
tiup cluster deploy esg-tidb v8.5.0 ./topology.yaml --user root
tiup cluster start esg-tidb
tiup cluster display esg-tidb   # 确认全部节点Up
```

部署完成后，给见证节点的TiKV配置低leader权重，避免它成为读写热点，只保留quorum投票作用：

```bash
tiup ctl:v8.5.0 pd -u http://<服务器A_IP>:2379 store   # 查出见证节点store_id
tiup ctl:v8.5.0 pd -u http://<服务器A_IP>:2379 scheduler add evict-leader-scheduler <witness_store_id>
```

### 5.3 第二步：服务器A、B部署K3s，datastore指向TiDB

先在TiDB里为K3s单独建库：

```sql
CREATE DATABASE k3s;
CREATE USER 'k3s_user'@'%' IDENTIFIED BY '<强密码>';
GRANT ALL PRIVILEGES ON k3s.* TO 'k3s_user'@'%';
```

服务器A：

```bash
curl -sfL https://get.k3s.io | sh -s - server \
  --datastore-endpoint="mysql://k3s_user:<强密码>@tcp(<TiDB_VIP或负载均衡地址>:4000)/k3s" \
  --tls-san=<服务器A_IP> \
  --node-name=node-a
cat /var/lib/rancher/k3s/server/node-token   # 记录token，B节点要用
```

服务器B（用同一个datastore-endpoint和A节点生成的token）：

```bash
curl -sfL https://get.k3s.io | sh -s - server \
  --datastore-endpoint="mysql://k3s_user:<强密码>@tcp(<TiDB_VIP或负载均衡地址>:4000)/k3s" \
  --tls-san=<服务器B_IP> \
  --node-name=node-b \
  --token=<从服务器A获取的token>
```

> TiDB是分布式的，建议前面挂一个VIP（keepalived）或简单的TCP负载均衡（如HAProxy），而不是让K3s直连某一台TiDB SQL层实例，避免那台实例故障时K3s连接不上。

验证：

```bash
sudo k3s kubectl get nodes -o wide   # 两台都应显示 Ready，角色 control-plane,master
```

### 5.4 第三步：Rocky 10特有的坑

**SELinux**（默认enforcing，不建议直接 `setenforce 0`）：

```bash
# TiDB数据目录、K3s目录按需放行上下文
sudo semanage fcontext -a -t container_file_t "/var/lib/rancher/k3s(/.*)?"
sudo restorecon -Rv /var/lib/rancher/k3s
sudo semanage port -a -t http_port_t -p tcp 4000   # TiDB SQL端口示例，按需放行K3s/TiDB其余端口
```

**firewalld**：

```bash
# 三台TiDB节点
sudo firewall-cmd --permanent --add-port={2379,2380,20160,4000,10080}/tcp
# 服务器A、B额外放行K3s
sudo firewall-cmd --permanent --add-port={6443,10250}/tcp
sudo firewall-cmd --permanent --add-port=8472/udp    # Flannel VXLAN(K3s默认CNI)
sudo firewall-cmd --reload
```

**离线环境**：Rocky 10默认dnf仓库没有TiDB包，TiUP是在线安装最省心的方式；如果机器不能连外网，需要提前用 `tiup mirror clone` 在有网环境打包离线镜像，再导入部署。

### 5.5 业务容器部署

FastAPI/Celery/Scrapy打成镜像后，用标准K8s Deployment + Service部署在A/B两个节点上，数据库连接串直接指向TiDB（走VIP或HAProxy）。建议：

- 用`nodeAffinity`让核心API Pod在A/B均有副本，Scrapy这类可以偏向单节点跑（避免IP被同时封锁两台机器）。
- Ingress用K3s自带的Traefik或换成Nginx Ingress，视你已有的运维习惯而定。
- 应用配置里数据库地址、Redis地址统一走ConfigMap/Secret管理，不要硬编码。

### 5.6 备份与运维

- TiDB定期备份：`tiup cluster backup` 或 BR (Backup & Restore) 工具，输出到独立存储，满足审计留痕要求。
- 原始采集文件目录做增量rsync备份。
- 监控：TiDB自带Prometheus+Grafana监控栈（TiUP部署时可选装），K3s可复用同一套Grafana加K8s面板，运维只维护一套监控体系。
- 日志：K3s容器日志走`journalctl`/K3s自带日志收集，业务日志建议统一发到TiDB或轻量ELK，方便和评分审计记录关联查询。

---

## 六、实施路线图

| 阶段 | 周期 | 交付物 |
|---|---|---|
| 1. 方法论定稿 | 1–2周 | 指标体系文档、权重专家打分收集、评分细则手册 |
| 2. 见证节点申请与三节点TiDB搭建 | 1周 | 见证节点到位、TiDB集群跑通、K3s接入验证 |
| 3. 数据采集与首批验证 | 2–3周 | 首批10–20家龙头能源企业数据采集验证 |
| 4. 清洗/复核流程 | 1–2周 | PDF抽取规则、人工复核Web界面 |
| 5. 计算引擎 | 1–2周 | 标准化、权重计算、综合评分API |
| 6. 可视化与业务对接 | 1–2周 | BI看板、对外API文档、首份评级报告输出（docx模板自动生成） |
| 7. 试运行与校准 | 1–2周 | 与Wind/MSCI等第三方评级结果交叉验证，调整α系数与异常值处理规则；模拟服务器/见证节点故障演练自动failover |

当前实现阶段的优先顺序调整为：先完成三种排名模式和缺失策略敏感性，生成全自动预排名；再用排名
影响驱动人工审核；随后冻结632家公司与正式方法论，最终发布正式审计版。详细验收口径以
`docs/development-plan.md`为准。

核心研发同时按发明专利技术交底要求留痕，优先保护多源证据约束图、排名敏感性反向传播、审核任务
调度、依赖图增量重算及双算法隔离冻结。具体申请组合、实验指标和商业秘密边界以
`docs/patent-strategy.md`为准。

---

## 七、业务对接与合规注意事项

- **方法论公开披露**：作为评级/投研业务使用，建议对外公开评分方法论（指标体系+权重逻辑），这是评级公信力的基础。
- **利益冲突隔离**：若评级对象与业务存在关联，需要在系统里做流程隔离（评分人员与业务人员权限分离）。
- **数据合规**：抓取公开数据总体合规风险低，但需保留robots.txt遵守记录、避免高频抓取；涉及非公开数据一律不采集。
- **模型风险管理**：每年至少一次方法论复审，权重和指标体系变更需版本化记录，不得静默修改影响历史可比性。
- **架构风险管理**：见证节点是全系统quorum完整性的关键依赖，需要和主节点同等级别的可用性保障（哪怕它不跑业务负载）；建议定期演练"见证节点失联""服务器A/B单点故障"两类场景下的自动恢复。

---

如果需要，下一步我可以：
1. 把 `topology.yaml`、K3s安装脚本、firewalld/SELinux配置整理成可以直接执行的Shell脚本；
2. 写具体的K8s Deployment/Service YAML（FastAPI、Celery、Scrapy、Nginx Ingress）；
3. 写PD故障演练脚本，验证"停掉服务器A的TiKV"场景下系统是否真的自动恢复。
