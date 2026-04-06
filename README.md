# 龟龟投资框架 (Turtle Investment Framework)

AI 辅助的 A 股/港股/美股基本面分析系统。混合架构：Python 脚本完成确定性数据采集，LLM 提示词驱动定性分析与多因子评估。

> **当前版本：v2.0-beta** — PDF-first 单 Agent 架构 + 独立估值模块 + Pre-flight 合并 + 实战验证。详见 [CHANGELOG_V2.md](CHANGELOG_V2.md)。

## 核心功能

| 模块 | 名称 | 实现方式 | 说明 |
|------|------|----------|------|
| 龟龟策略 | 穿透回报率 + 估值 | 共享定性 + 专属定量 | 完整四因子分析 → 买入/观察/规避 |
| 商业分析 | 6 维度定性评估 | PDF-first 单 Agent | 年报 PDF 作主数据源 + Greenwald 护城河 |
| 估值分析 | 多方法估值 | Python 引擎 + LLM | DCF/DDM/PE Band/PEG/PS 自动分类 |
| 数据采集 | Tushare + WebSearch | Python + Agent | A/港/美股，24+ API，5 年财务数据 |
| 年报解析 | PDF 章节提取 | Python / pdfplumber | 7 个目标章节 + 附注精提取 |
| 选股器 | 龟龟选股器 | Python / 两级筛选 | Tier 1 批量过滤 + Tier 2 深度分析 |
| 报告输出 | MD + HTML 双输出 | Jinja2 模板 | 暗色模式、KPI 卡片、语义色彩标签 |

## 系统架构 (v2.0)

v2.0 采用 **共享模块 + 策略专属模块** 的分层架构，定性分析可独立运行或被不同策略复用。

### 龟龟策略完整流程

```
用户输入 (股票代码 + 年报PDF)
         │
    ┌────▼────┐
    │ Phase 0 │  自动下载年报 (/download-report)
    └────┬────┘
         │
    ┌────▼────┬──────────────┐
    │Phase 1A │  Phase 2A    │  ← 并行运行
    │Tushare  │  PDF预处理    │
    │数据采集  │  (pdfplumber) │
    └────┬────┴──────┬───────┘
         │           │
    ┌────▼────┐      │
    │Phase 1B │      │
    │WebSearch│      │
    └────┬────┘      │
         │      ┌────▼────┐
         │      │Phase 2B │
         │      │精提取    │
         └──┬───┴────┬────┘
            │        │
       ┌────▼────────▼────┐
       │     Phase 3      │
       │  定性(共享) +     │
       │  定量 + 估值(龟龟) │
       └──────┬───────────┘
              │
     output/{code}_分析报告.md + .html
```

### 独立商业分析流程（PDF-first 单 Agent）

```
/business-analysis {code}
         │
    ┌────▼────────────────┐
    │ 年报 PDF 下载/缓存   │  glob 检查 → 按需下载
    └────┬────────────────┘
         │
    ┌────▼────────────────┐
    │ Tushare 数据采集     │  历史序列补充（§1–§17）
    └────┬────────────────┘
         │
    ┌────▼────────────────┐
    │ 单 Agent 定性分析    │  PDF 直接载入 1M context
    │ D1–D6 全维度        │  交叉验证优于多 Agent 拆分
    └────┬────────────────┘
         │
    report.md + report.html
```

### 各阶段角色

- **Phase 0** — 调用 `/download-report` 命令自动搜索并下载最新年报 PDF
- **Phase 1A** — `tushare_collector.py` 通过 Tushare Pro API 采集结构化数据，输出 `data_pack_market.md`（含 §1–§17 共 17 个数据段）
- **Phase 1B** — Agent 执行 WebSearch 补充治理/行业/子公司等非结构化信息
- **Phase 2A** — `pdf_preprocessor.py` 使用关键词匹配定位年报 7 个目标章节，输出 `pdf_sections.json`
- **Phase 2B** — Agent 从 PDF 章节中精确提取附注数据
- **Phase 3** — 定性分析（PDF-first 单 Agent）+ 定量分析（含 Pre-flight Step 0）+ 估值（龟龟专属），输出 MD + HTML 双格式报告

## 快速开始

### 环境要求

- Python >= 3.10
- [Tushare Pro](https://tushare.pro/) 账号及 API Token
- （可选）pdfplumber 用于 PDF 解析
- （内置）`/download-report` 命令用于自动下载年报

### 安装

**首次安装：**

```bash
git clone https://github.com/terancejiang/Turtle_investment_framework.git
cd Turtle_investment_framework

# 一键初始化（创建 venv、安装依赖、验证环境）
bash init.sh
```

**更新已有项目：**

```bash
cd Turtle_investment_framework
git pull

# 重新安装依赖（确保新增的包被安装）
bash init.sh --force-install
```

`init.sh` 会自动完成：
1. 查找系统中 Python >= 3.10，创建 `.venv`
2. 安装 `requirements.txt` 中的依赖
3. 检查 `TUSHARE_TOKEN` 环境变量
4. 运行测试验证环境

### 配置 Tushare Token

```bash
cp .env.sample .env
# 编辑 .env，填入你的 Token
# TUSHARE_TOKEN=your_token_here
```

或者直接设置环境变量：

```bash
export TUSHARE_TOKEN='your_token_here'
```

## 使用方法

### 单股分析

在 [Claude Code](https://claude.com/claude-code) 中使用 slash command：

```
/turtle-analysis 600887          # 完整龟龟策略（定性 + 定量 + 估值）
/business-analysis 600887        # 独立商业分析（PDF-first 6维度定性评估）
/valuation 600887                # 独立估值分析（自动分类 + 多方法估值）
```

`/turtle-analysis` 自动执行 Phase 0 → 1A → 1B → 2A → 2B → 3 完整流程。
`/business-analysis` PDF-first 单 Agent 定性分析（年报 PDF + Tushare 数据）。
`/valuation` 独立估值分析，需先运行 `/business-analysis`（依赖定性报告 + 市场数据）。

### 数据采集（仅 Phase 1A）

```bash
# 基本用法
.venv/bin/python scripts/tushare_collector.py --code 600887.SH

# 指定输出路径
.venv/bin/python scripts/tushare_collector.py --code 600887.SH --output output/data_pack_market.md

# 附加额外字段
.venv/bin/python scripts/tushare_collector.py --code 00700.HK --extra-fields balancesheet.defer_tax_assets

# 试运行（不调用 API）
.venv/bin/python scripts/tushare_collector.py --code 600887 --dry-run
```

输出 Markdown 包含以下数据段：

| 段号 | 内容 | 来源 |
|------|------|------|
| §1 | 基本信息 | stock_basic + daily_basic |
| §2 | 行情数据（52 周范围） | pro_bar weekly |
| §3 | 合并利润表（5 年） | income |
| §3P | 母公司利润表 | income (report_type=4) |
| §4 | 合并资产负债表（5 年） | balancesheet |
| §4P | 母公司资产负债表 | balancesheet (report_type=4) |
| §5 | 合并现金流量表 + FCF | cashflow |
| §6 | 分红历史 | dividend |
| §7–§10 | 占位符（WebSearch 补充） | Phase 1B |
| §11 | 周线数据（10 年） | weekly |
| §12 | 财务指标（ROE/毛利率等） | fina_indicator |
| §13 | 风险警告 | 自动检测 + Agent |
| §14 | 无风险利率 | yc_cb |
| §15 | 股份回购 | repurchase |
| §16 | 股权质押 | pledge_stat |
| §17 | 衍生指标预计算 | compute_derived_metrics |

### 年报解析（仅 Phase 2A）

```bash
# 基本用法
.venv/bin/python scripts/pdf_preprocessor.py --pdf 伊利股份_2024_年报.pdf

# 指定输出 + 详细日志
.venv/bin/python scripts/pdf_preprocessor.py --pdf report.pdf --output output/pdf_sections.json --verbose

# 使用 TOC hints 覆盖关键词匹配
.venv/bin/python scripts/pdf_preprocessor.py --pdf report.pdf --hints toc_hints.json
```

提取的 7 个目标章节：

| 缩写 | 章节 | 说明 |
|------|------|------|
| P2 | 公司治理 | 公司治理结构 |
| P3 | 会计政策 | 重要会计政策和会计估计 |
| P4 | 应收账款 | 应收账款/票据附注 |
| P6 | 合并报表 | 合并财务报表附注 |
| P13 | 风险 | 风险提示/重大事项 |
| MDA | 管理层讨论 | 经营情况讨论与分析 |
| SUB | 子公司 | 主要子公司/长期股权投资明细 |

### 批量选股（龟龟选股器）

```bash
# 完整流程（Tier 1 + Tier 2）
.venv/bin/python scripts/screener_core.py

# 仅 Tier 1 快速筛选
.venv/bin/python scripts/screener_core.py --tier1-only

# 限制 Tier 2 分析数量
.venv/bin/python scripts/screener_core.py --tier2-limit 50

# 自定义阈值
.venv/bin/python scripts/screener_core.py --min-roe 10 --max-pe 30 --min-gross-margin 20

# 导出结果
.venv/bin/python scripts/screener_core.py --csv output/screener.csv --html output/screener.html

# 刷新缓存
.venv/bin/python scripts/screener_core.py --cache-refresh          # 全部刷新
.venv/bin/python scripts/screener_core.py --cache-tier2-refresh    # 仅刷新 Tier 2
```

### Jupyter Notebook

```bash
cd notebooks
jupyter notebook screener.ipynb
```

Notebook 包含 7 个 Cell：初始化 → Tier 1 过滤 → 排名 → Tier 2 分析 → 评分 → 导出 → 个股详情，附 matplotlib 可视化图表。

## 项目结构

```
Turtle_investment_framework/
├── shared/                        # 共享模块（v2.0）
│   └── qualitative/               # 通用定性分析模块
│       ├── coordinator.md          #   v1 入口（Agent Team）
│       ├── coordinator_v2.md       #   v2 入口（PDF-first 单 Agent）
│       ├── qualitative_assessment.md #   v1 6维度分析 prompt
│       ├── qualitative_assessment_v2.md # v2 PDF-first prompt
│       ├── data_collection.md      #   轻量级 WebSearch 指令
│       ├── agents/                 #   Agent Team prompts（v1 保留）
│       │   ├── agent_a_d1d2.md     #     D1(商业模式)+D2(护城河)
│       │   ├── agent_b_d3d4d5.md   #     D3(外部)+D4(管理层)+D5(MD&A)
│       │   ├── agent_summary.md    #     总结 Agent
│       │   └── writing_style.md    #     共享写作风格
│       ├── references/             #   参考文档
│       │   ├── output_schema.md    #     结构化参数输出 schema
│       │   ├── judgment_examples.md #    护城河/MD&A/管理层锚点
│       │   ├── framework_guide.md  #     Greenwald 框架说明
│       │   └── market_rules_*.md   #     港/美股规则（条件加载）
│       └── templates/
│           └── dashboard.html      #   HTML 仪表盘模板
├── strategies/                    # 策略专属模块（v2.0）
│   ├── turtle/                    # 龟龟策略
│   │   ├── coordinator.md          #   入口（/turtle-analysis）
│   │   ├── phase1_数据采集.md       #   数据采集指令
│   │   ├── phase2_PDF解析.md        #   PDF 解析指令
│   │   ├── phase3_preflight.md     #   数据校验 + 会计锚定（已合并至 quantitative）
│   │   ├── phase3_quantitative.md  #   Pre-flight Step 0 + 穿透回报率（11步）
│   │   ├── phase3_valuation.md     #   估值 + 报告组装
│   │   └── references/             #   策略专属参考
│   │       ├── shared_tables.md    #     税表/阈值/分配公式
│   │       ├── factor_interface.md #     Agent 间参数传递 schema
│   │       └── judgment_examples_turtle.md # G系数/分配/λ锚点
│   └── valuation/                 # 独立估值模块
│       ├── coordinator.md          #   入口（/valuation）
│       ├── phase2_valuation.md     #   估值方法 + 报告组装
│       └── references/
│           ├── classification_rules.md #  公司类型分类阈值
│           ├── valuation_methods.md #    DCF/DDM/PE Band/PEG/PS 公式
│           ├── valuation_examples.md #   计算示例
│           └── report_template.md  #     报告模板
├── scripts/                       # Python 脚本
│   ├── config.py                  #   配置工具（Token、股票代码验证）
│   ├── format_utils.py            #   格式化工具（数字、表格、标题）
│   ├── tushare_collector.py       #   Tushare 数据采集门面
│   ├── tushare_modules/           #   Tushare 模块化实现
│   │   ├── constants.py           #     字段映射（VIP/HK/US）
│   │   ├── infrastructure.py      #     市场检测、格式化
│   │   ├── financials.py          #     财务报表 get_* 方法
│   │   ├── other_data.py          #     分部/持股/审计/质押
│   │   ├── derived_metrics.py     #     §17 衍生指标计算
│   │   ├── yfinance_integration.py #    yfinance 回退（港/美股）
│   │   └── assembly.py            #     数据包组装
│   ├── pdf_preprocessor.py        #   PDF 年报章节提取
│   ├── split_data_pack.py         #   Agent Team 数据预分发
│   ├── valuation_engine.py        #   估值引擎（DCF/DDM/PEG/PE Band/PS）
│   ├── report_to_html.py          #   MD → HTML 转换（支持 --standalone）
│   ├── screener_config.py         #   选股器配置
│   ├── screener_core.py           #   选股器核心（两级筛选）
│   └── download_report.py         #   年报PDF下载
├── prompts/                       # v1 提示词（只读遗留）
├── cigarbutt/                     # 烟蒂策略（独立模块）
├── notebooks/                     # Jupyter Notebooks
│   └── screener.ipynb             #   选股器交互式 Notebook
├── tests/                         # 测试套件（792 tests）
│   ├── conftest.py
│   ├── fixtures/mock_tushare_responses/
│   ├── test_config.py
│   ├── test_coordinator.py
│   ├── test_derived_metrics.py
│   ├── test_download_report.py
│   ├── test_format_utils.py
│   ├── test_integration.py
│   ├── test_output_format.py
│   ├── test_pdf_preprocessor.py
│   ├── test_phase1b_prompt.py
│   ├── test_phase2b_prompt.py
│   ├── test_phase3_prompt.py
│   ├── test_refresh_market.py
│   ├── test_screener.py
│   └── test_tushare_client.py
├── output/                        # 输出目录（gitignored）
├── init.sh                        # 环境初始化脚本
├── requirements.txt               # Python 依赖
├── CHANGELOG_V2.md                # v1→v2 变更日志
├── feature_list.json              # 功能清单
└── claude-progress.txt            # 开发进度日志
```

## 分析框架详解

### 定性分析（共享模块，6 维度）

v2.0-beta 的定性分析采用 **PDF-first 单 Agent** 架构：年报 PDF 直接载入 1M context 作为主数据源，Tushare 仅作历史序列补充。单 Agent 模式在交叉验证上优于多 Agent 拆分，所有维度共享同一 context 消除信息孤岛。

| 维度 | 内容 | 说明 |
|------|------|------|
| D1 商业模式 | 轻/重资产判别、利润结构、资产质量 | 核心维度 |
| D2 护城河 | Greenwald 三维框架（供给侧/需求侧/规模经济）+ 竞对对比 | 6步结构化分析 |
| D3 外部环境 | 行业周期、政策、竞争格局 | — |
| D4 管理层 | 治理结构、激励机制、历史诚信 | — |
| D5 MD&A | 管理层讨论分析、战略一致性 | — |
| D6 控股结构 | 母/子公司关系、关联交易 | 条件触发 |

**D2 护城河分析（v2.0 重大升级）**：6 步结构化分析 — 行业地图 → 量化验证（ROE 门槛 8/15/25%）→ 双框架分析（非技术+技术 × 供给/需求/规模）→ 虚假优势辨析 → 竞对对比表 → 可持续性监控锚点

### 四因子模型（龟龟策略专属）

在定性分析基础上，龟龟策略增加穿透回报率计算和估值：

**因子 2：穿透回报率粗算**
- 从 §17.2 读取 C/B/M/N/OE 等参数 + OE 纠偏
- 否决门（ROE < 8% 或负值 → 直接否决）
- 计算穿透回报率 R% = M × (1 − 分红税率) × OE
- 否决判定（R% < Rf → 否决）

**因子 3：穿透回报率精算**
- 真实现金收入（S/T/U、保守基础、收款比率）
- 经营性流出（W1–W4：供应商/员工/税/利息）
- 基础盈余、AA（含/不含资本化）、CV、λ 系数
- 分配意愿（M）、可预测性
- 输出：精算后 R% + 可靠性标签

**因子 4：估值与安全边际**
- 相对估值（PE/PB 分位数、历史对比）
- 绝对估值指标（EV/EBITDA、现金调整 PE、FCF 收益率等 11 项）
- 基准价（5 种方法取算术平均）+ 溢价分析
- 输出：买入/观察/规避 评级

### 龟龟选股器

两级筛选系统，从全 A 股 5000+ 只中筛选优质标的：

**Tier 1 — 批量过滤（仅市场数据，~5 秒）**

| 过滤条件 | 默认阈值 |
|----------|----------|
| 排除 ST/PT/退市整理 | — |
| 上市年限 | ≥ 3 年 |
| 市值 | ≥ 5 亿元 |
| 日换手率 | ≥ 0.1% |
| PB | 0 < PB ≤ 10 |
| 股息率 | > 0 |
| PE（主通道） | 0 < PE_TTM ≤ 50 |
| PE（观察通道） | PE_TTM < 0，按市值取前 50 |

排名公式：`Score = 0.4 × dv_ttm + 0.3 × (1/PE) + 0.3 × (1/PB)`

主通道取前 150 名 + 观察通道 50 名 → 共 200 只进入 Tier 2。

**Tier 2 — 深度分析（逐只调用 API）**

- 硬否决：质押比 > 70%、非标审计意见
- 财务质量：ROE ≥ 8%、毛利率 ≥ 15%、资产负债率 ≤ 70%
- 因子 2 指标：分配意愿 M、穿透率 R、Threshold II
- 因子 4 指标：EV/EBITDA、现金调整 PE、FCF 收益率、商誉占比
- 基准价：5 种方法（净流动资产/BVPS/10 年低点/股息隐含/悲观 FCF）取算术平均

**底价（Floor Price）— 5 种方法取算术平均**

底价是多维度安全边际锚点，综合物理资产、历史价格、分红能力和现金流生成能力：

| # | 方法 | 公式 | 说明 |
|---|------|------|------|
| 1 | 净流动资产/股 | (现金 + 交易资产 − 有息负债) / 总股数 | 清算视角的底线价值 |
| 2 | 每股净资产 (BVPS) | 归属股东权益(不含少数) / 总股数 | 账面价值锚点 |
| 3 | 10 年历史最低价 | 过去 10 年周收盘价最小值 | 历史极端情绪底部 |
| 4 | 分红折现价 | 近 3 年平均每股分红 / max(Rf, 3%) | 股息率等于折现率时的价格 |
| 5 | 悲观 FCF 资本化价 | 近 5 年最小 FCF / Rf% / 总股数 | 仅当 5 年 FCF 全为正时有效 |

复合基准取有效方法值的 **算术平均**。底价溢价率 = (当前价 / 基准价 − 1) × 100%。

| 溢价率 | 区间含义 |
|--------|----------|
| ≤ 0% | "买入就是胜利"区间 — 当前价低于底价 |
| 0–30% | 安全边际充足 |
| 30–80% | 合理溢价，需成长验证 |
| > 80% | 高溢价，需强成长预期支撑 |

**综合评分权重**

| 维度 | 权重 |
|------|------|
| ROE | 20% |
| FCF 收益率 | 20% |
| 穿透率 R | 25% |
| EV/EBITDA（逆序） | 15% |
| 基准价溢价（逆序） | 20% |

## 测试

```bash
# 运行全部测试（792 tests）
.venv/bin/python -m pytest tests/ -v

# 运行单个测试文件
.venv/bin/python -m pytest tests/test_screener.py -v

# 快速模式（遇到失败即停止）
.venv/bin/python -m pytest tests/ -x -q

# 查看覆盖率
.venv/bin/python -m pytest tests/ --cov=scripts --cov-report=term-missing
```

测试覆盖范围（14 个测试文件）：
- 配置与工具函数（`test_config.py`, `test_format_utils.py`）
- Tushare 数据采集 + 衍生指标（`test_tushare_client.py`, `test_derived_metrics.py`）
- PDF 预处理（`test_pdf_preprocessor.py`）
- LLM 提示词验证（`test_phase1b_prompt.py`, `test_phase2b_prompt.py`, `test_phase3_prompt.py`）
- 协调器与集成测试（`test_coordinator.py`, `test_integration.py`）
- 输出格式验证（`test_output_format.py`）
- 年报下载（`test_download_report.py`）
- 选股器全流程（`test_screener.py`）
- 增量刷新模式（`test_refresh_market.py`）

所有测试使用 Mock 数据，不需要 Tushare Token 即可运行。

## 技术细节

### 数据单位约定

所有金额统一为 **百万元（RMB）**。Tushare 返回的原始数据（元）在采集时自动除以 1,000,000，并使用千分位格式化显示。

### 缓存策略

选股器使用 Parquet 格式的分层缓存：

| 数据类型 | 缓存 TTL |
|----------|----------|
| stock_basic（全量股票列表） | 7 天 |
| daily_basic（每日行情） | 当日有效 |
| Tier 2 财务数据（年报类） | 168 小时（7 天） |
| Tier 2 行情数据（周线） | 24 小时 |
| 全局数据（无风险利率） | 24 小时 |

缓存目录：`output/.screener_cache/`

### 速率限制

Tushare API 调用自动限速：每次请求间隔 ≥ 0.3 秒，失败自动重试（指数退避）。

## 开发指南

### 功能开发流程

1. 查看 `feature_list.json` 中下一个待实现的 feature
2. 按 feature 的 `steps` 数组顺序实现
3. 同步编写测试（不允许跳过测试）
4. 完成后在 `feature_list.json` 中标记 `passes: true`
5. 按规范提交 commit

### 提交规范

```
feat(category): description [feature #N]
fix(category): description [feature #N]
test(category): description [feature #N]
```

Category 对应 `feature_list.json` 中的分类：`infrastructure`, `phase1a_tushare`, `phase1b_websearch`, `phase2a_pdf_preprocess`, `phase3_analysis`, `screener` 等。

### 里程碑

| 标签 | 范围 | 状态 |
|------|------|------|
| v1.0-alpha | 基础设施 (#1–#8) | 已完成 |
| v1.0-beta | 全部脚本 (#1–#47) | 已完成 |
| v1.0 | 完整 pipeline + 提示词 v1 | 已完成 |
| v1.1 | 17 improvements, HK/US support, shared_tables | 已完成 |
| v2.0-alpha | 模块化拆分 + Greenwald 护城河 + Agent Team + HTML 仪表盘 | 已完成 |
| **v2.0-beta** | **PDF-first 单 Agent + 估值模块 + Pre-flight 合并 + 实战验证** | **当前** |
| v2.0-rc | 烟蒂策略接入 shared 模块 + 端到端调优 | 计划中 |

## 依赖

```
tushare>=1.2.89       # A 股数据接口
pandas>=1.5.0         # 数据处理
pdfplumber>=0.9.0     # PDF 文本提取
requests>=2.28.0      # HTTP 请求
pytest>=7.0.0         # 测试框架
pyarrow>=10.0.0       # Parquet 缓存
matplotlib>=3.5.0     # 可视化（Notebook）
tqdm>=4.60.0          # 进度条
jupyter>=1.0.0        # Notebook 运行环境
jinja2>=3.0.0         # HTML 模板（报告 + 选股器导出）
yfinance>=0.2.0       # 港股/美股行情回退
```

## License

MIT
