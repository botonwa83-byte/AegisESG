# 中国能源上市公司可持续发展ESG评价系统 —— 设计与部署方案

版本：v2.0（整合方法论 + 系统设计 + 集群部署）　适用场景：投研 / 合规 / 评级业务对接
部署环境：2台物理服务器 + 1台见证节点，Linux Rocky 10

---

## 一、总体设计思路

系统分三层交付：

1. **方法论层**：可对外披露、可复现、可审计的ESG指标体系与评分模型 —— 业务对接（投研/合规/评级）的核心，评级结果必须能向监管、客户、被评价公司解释清楚"为什么打这个分"。
2. **系统实现层**：数据采集 → 清洗入库 → 指标计算 → 评分与排名 → 可视化/API输出。
3. **集群部署层**：基于K3s + TiDB的两节点+见证节点高可用架构，部署在Rocky 10上。

业务约束（因为要对接实际业务，而非仅做研究展示）：

- **可解释性优先**：不用黑箱机器学习模型做最终评分，AHP/熵权组合赋权 + 线性加权，任何一次评分都能拆解到具体指标和原始数据来源。
- **可审计留痕**：原始数据（PDF年报、公告链接、采集时间戳）与计算过程全部落库，评分结果可追溯到源文件的具体页码/字段。
- **可复现**：同一批数据、同一版本方法论，任何时候重算结果一致；方法论版本化管理，指标体系调整不覆盖历史评分。
- **真正的高可用**：数据库和K8s控制面的故障切换必须是自动的，不依赖人工介入——这要求在架构层面解决"两台物理机无法形成quorum多数"的问题（见第四章）。

### 1.1 双轨算法与三级输出（v2.1调整）

系统共享同一套原始文档、结构化事实和证据链，但评分算法物理隔离：

1. **自动预排名算法**：系统自有、可解释、版本化，无需人工参与；允许使用机器定性判断和明确的
   缺失值策略，输出覆盖率、可信等级及多情景敏感性，不作为正式评级；
2. **客户正式算法**：严格执行客户确认的公司池、指标、权重、缺失规则和定性档位；高风险项目经
   单审、双审或仲裁后冻结，不为迎合预期名次修改规则；
3. **审核候选排名**：作为两者之间的增量结果，用来识别哪些未审任务仍可能改变名次或前200边界。

模型风险控制重点不是让人工审核所有格子，而是对主体身份、实质冲突、定性80/100、高权重弱证据
和排名敏感项强制审核，对低风险严格派生执行分层抽样。任何自动决定都必须保存证据、规则版本、
置信度和适用的排名模式。

---

## 二、ESG评价方法论

### 2.1 指标体系设计原则

- **行业针对性**：能源行业（煤炭、石油石化、电力、新能源）区别于通用ESG体系的关键点是碳排放强度、能源结构转型、安全生产事故率、职业健康。通用SASB/MSCI框架需要结合中国能源行业特点做本地化调整。
- **数据可得性**：三级指标必须能从公开渠道（年报、社会责任报告、ESG专项报告、环保部门处罚公告、交易所公告）获取，避免设计出无法采集的指标。
- **正逆指标区分**：明确标注每个三级指标是正向（越高越好，如可再生能源占比）还是逆向（越低越好，如碳排放强度、环保处罚次数）。
- **参照标准**：对齐证监会《上市公司自律监管指引第17号——可持续发展报告编制》、香港交易所ESG指引、GRI标准、MSCI/Wind ESG评级方法论，便于结果与主流评级交叉验证。

### 2.2 三级指标体系

**一级指标：环境(E) / 社会(S) / 治理(G)，各占一级权重待2.3节确定**

#### E 环境维度

| 二级指标 | 三级指标 | 正/逆 | 数据来源 |
|---|---|---|---|
| 碳排放管理 | 碳排放强度（吨CO2/万元营收） | 逆 | ESG报告、碳排放核查报告 |
| | 温室气体排放总量同比变化率 | 逆 | ESG报告 |
| | 是否设定碳中和/达峰目标及路径清晰度 | 正 | ESG报告文本 |
| 能源结构 | 清洁能源装机占比（发电类企业） | 正 | 年报、公司公告 |
| | 单位产值综合能耗 | 逆 | 年报、社会责任报告 |
| 污染物排放 | 主要污染物（SO2/NOx/COD）排放达标率 | 正 | 环保部门公开数据 |
| | 环保行政处罚次数及金额 | 逆 | 证监会/生态环境部处罚公告 |
| 环境管理体系 | 是否通过ISO14001等环境管理认证 | 正 | 公司公告 |
| | 环保投入占营收比 | 正 | 年报 |
| 资源利用 | 水资源循环利用率 | 正 | ESG报告 |
| | 固废综合利用率 | 正 | ESG报告 |

#### S 社会维度

| 二级指标 | 三级指标 | 正/逆 | 数据来源 |
|---|---|---|---|
| 安全生产 | 百万工时死亡率/重伤率 | 逆 | 安全生产报告、应急管理部公告 |
| | 安全生产事故次数 | 逆 | 公司公告、监管处罚 |
| 员工权益 | 员工社保覆盖率 | 正 | 年报、ESG报告 |
| | 员工培训投入/人均培训时长 | 正 | ESG报告 |
| | 员工流失率 | 逆 | ESG报告 |
| 供应链管理 | 供应商ESG审核覆盖率 | 正 | ESG报告 |
| | 本地采购占比 | 正 | ESG报告 |
| 产品责任 | 产品质量/安全投诉处理率 | 正 | 年报、投诉公开数据 |
| 社区与公益 | 公益捐赠占净利润比 | 正 | 年报 |
| 信息安全 | 是否发生数据安全/网络安全重大事件 | 逆 | 公司公告 |

#### G 治理维度

| 二级指标 | 三级指标 | 正/逆 | 数据来源 |
|---|---|---|---|
| 股权与董事会结构 | 独立董事占比 | 正 | 年报 |
| | 董事长与总经理是否两职分离 | 正 | 年报 |
| | 女性董事占比 | 正 | 年报 |
| 信息披露质量 | 是否单独发布ESG/社会责任报告 | 正 | 公司公告 |
| | ESG报告第三方鉴证情况 | 正 | ESG报告 |
| | 信息披露违规次数 | 逆 | 证监会/交易所处罚公告 |
| 股东权益 | 中小股东权益保护机制完善度 | 正 | 年报、公司治理报告 |
| | 关联交易占比 | 逆 | 年报 |
| 高管激励与合规 | 高管薪酬与ESG绩效挂钩情况 | 正 | 年报 |
| | 商业道德/反腐败制度建设 | 正 | ESG报告 |
| 风险管理 | 是否设立ESG委员会/专门治理机构 | 正 | 公司公告 |

> 三级指标共约31个，具体项目落地时按数据可得性可裁剪至25–35个，避免为凑数纳入不可获取字段。

### 2.3 权重确定方法：AHP + 熵权组合赋权

1. **AHP主观权重**：邀请3–5位能源行业/ESG领域专家对一级、二级指标两两比较打分，构造判断矩阵，计算特征向量得到主观权重 `w_AHP`，需做一致性检验（CR < 0.1）。
2. **熵权法客观权重**：基于历史采集到的实际数据分布，计算各指标的信息熵，熵越小说明指标区分度越大、权重越高，得到 `w_entropy`。
3. **组合权重**：`w_final = α × w_AHP + (1-α) × w_entropy`，α建议取0.5–0.6（业务解释场景下主观权重占比略高，避免权重被个别年份数据波动带偏）。
4. **权重版本化**：每次重新标定权重生成新版本号，历史评分固定使用当年生效的权重版本，不做回溯调整。

### 2.4 数据标准化与打分

- **正向指标**：`score = (x - min) / (max - min) × 100`
- **逆向指标**：`score = (max - x) / (max - min) × 100`
- **定性指标**（如"是否设立ESG委员会"）：转换为0/1或分档评分（0/50/100），需在评分细则文档中明确判定标准，避免人工打分不一致。
- **极值处理**：采用行业内分位数缩尾（Winsorize，1%/99%分位）处理异常值，避免个别公司极端数据拉偏全行业标准化区间。
- **分组标准化**：能源行业内部按细分行业（煤炭/石油石化/电力/新能源）分别做min-max，避免不同商业模式的公司直接比较失真。

### 2.5 综合评价模型

- **主模型**：线性加权综合得分 `ESG_score = Σ(三级指标标准化分 × 组合权重)`，逐层加总到二级、一级、总分，满分100，附E/S/G三个分项分。
- **稳健性验证**：用TOPSIS法或灰色关联法做二次排名，与线性加权排名做Spearman相关性检验，差异过大触发人工复核。
- **评级映射**：总分映射为等级（AAA/AA/A/BBB/BB/B/CCC），便于业务侧直接使用等级而非具体分数沟通。
- **同比与趋势**：保留历史评分，输出年度环比变化、行业排名变化趋势。

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
