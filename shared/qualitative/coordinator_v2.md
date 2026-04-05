# 定性分析模块 — 协调器 v2

> **角色**：你是项目经理。职责：(1) 验证输入；(2) 加载数据；(3) 启动定性分析；(4) 交付完整报告。
>
> **架构变更 (v2)**：PDF-first 数据流。年报 PDF 直接载入 context，不经过中间格式化步骤。
> Tushare 数据仅作为历史序列补充。

---

## 输入解析

| 输入项 | 示例 | 必需？ |
|--------|------|--------|
| 股票代码或名称 | `600690` / `海尔智家` / `0001.HK` / `AAPL` | 必需 |
| 年报 PDF | 本地文件路径 或 URL | 可选（有则跳过 WebSearch） |

**解析规则**：
1. 从用户消息中提取股票代码/名称
2. 若用户提供了 PDF 链接/路径 → 下载到 `{output_dir}/annual_report.pdf`
3. 代码格式化：A股 → `XXXXXX.SH/SZ`；港股 → `XXXXX.HK`；美股 → `AAPL.US`

---

## 执行流程

```
┌──────────────────────────────────────────────┐
│  Step 1：数据采集（并行）                       │
│                                                │
│  ┌──────────────────┐  ┌──────────────────┐   │
│  │ 1A Tushare数据    │  │ 1B PDF 加载      │   │
│  │ → data_pack.md    │  │ → context 直接读取│   │
│  └──────────────────┘  └──────────────────┘   │
└──────────┬─────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│  Step 2 + Step 1C（可并行）                    │
│                                                │
│  ┌──────────────────┐  ┌──────────────────┐   │
│  │ Step 2:           │  │ Step 1C:          │   │
│  │ 6维度定性分析      │  │ PDF附注提取       │   │
│  │ → qualitative_    │  │ → data_pack_      │   │
│  │   report.md       │  │   report.md       │   │
│  └──────────────────┘  └──────────────────┘   │
└──────────┬─────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│  Step 3：HTML 仪表盘报告（可选）               │
│  report_to_html.py → qualitative_report.html  │
└──────────────────────────────────────────────┘
```

---

## Step 1 详细指令

### 1A：Tushare 数据采集

```bash
mkdir -p {output_dir}
python3 scripts/tushare_collector.py --code {ts_code} --output {output_dir}/data_pack_market.md
```

### 1B：PDF 获取与加载

**PDF 获取优先级**：
1. 用户已提供 PDF 路径/URL → 直接使用
2. 用户未提供 PDF → 使用 `/download-report {stock_code}` 搜索并下载最新年报（或中报）
   - 下载目标目录：`{output_dir}/`
   - 下载失败（重试后仍失败）→ fallback 到 WebSearch（Step 1C-fallback）

**PDF 读取策略**：

1. **先读目录**（通常前 3-5 页）→ 确认 PDF 类型和章节页码
2. **判断 PDF 类型**：
   - 纯文本 PDF → 直接 Read 关键章节
   - 扫描/图片 PDF → fallback 到 `python3 scripts/pdf_preprocessor.py`
3. **按需读取关键章节**（优先级排序）：

| 优先级 | 章节 | 典型页码范围 | 分析用途 |
|--------|------|-----------|--------|
| P0 | 致股东信 | 前 5-8 页 | 战略概览、管理层风格 |
| P0 | 管理层讨论与分析 | 16-60 | D1收入质量、D3行业、D5 MD&A |
| P0 | 公司治理 | 61-85 | D4 管理层 |
| P1 | 公司简介和主要财务指标 | 10-15 | D1 基础数据 |
| P1 | 股东情况 | 101-108 | D4 股权结构 |
| P2 | 财务报告附注 | 115+ | D6 控股结构、关联交易 |

每次 Read 最多 20 页，按优先级分批读取。

**1C-fallback：WebSearch 降级（仅当 PDF 下载失败时）**：
- 使用 WebSearch 补充 §7（管理层）、§8（行业）、§10（MD&A）
- 搜索时优先获取最近完整财年数据，WebSearch 关键词中加入"年报""全年"以避免返回半年报/季报结果
- 在报告中标注数据来源为 WebSearch，可信度相应降低

### 1C：PDF 附注提取（仅当有 PDF 时，可与 Step 2 并行）

> 此步骤为下游策略（龟龟、烟蒂等）提供结构化附注数据，不影响定性分析。
> 定性分析 Agent 和附注提取 Agent 读取 PDF 的不同区域，可并行执行。

```
Agent(
  subagent_type = "general-purpose",
  prompt = """
  请阅读 {workspace}/strategies/turtle/phase2_PDF解析.md 中的提取清单和输出格式。

  年报 PDF 文件：{output_dir}/{pdf_filename}

  步骤：
  1. 使用 Read 工具读取 PDF 前 3-5 页，获取目录页，定位附注各章节的页码。
  2. 判断 PDF 类型（纯文本 or 扫描件）：
     - 若 Read 返回清晰的中文文字和表格 → 纯文本 PDF，继续步骤 3
     - 若 Read 返回乱码或极少文字 → 扫描件，输出标记 `PDF_TYPE=SCANNED` 后停止
  3. 按优先级从 PDF 中直接 Read 对应章节（每次最多 20 页）：
     P0: 非经常性损益明细(P13)、受限现金明细(P2)
     P1: 应收账款账龄(P3)、关联交易(P4)、或有负债与承诺(P6)
     P2: 主要控股参股公司(SUB，条件触发：仅控股公司结构)
  4. 按 phase2_PDF解析.md 的格式提取结构化数据。

  将提取结果写入：{output_dir}/data_pack_report.md
  """,
  description = "PDF附注提取(供下游策略)"
)

# 扫描件 fallback（仅当上述 Agent 返回 PDF_TYPE=SCANNED 时执行）
Bash(
  command = "python3 scripts/pdf_preprocessor.py --pdf {output_dir}/{pdf_filename} --output {output_dir}/pdf_sections.json",
  description = "PDF预处理-扫描件fallback"
)
Agent(
  prompt = """
  请阅读 {workspace}/strategies/turtle/phase2_PDF解析.md 中的完整指令。
  pdf_sections.json 文件路径：{output_dir}/pdf_sections.json
  公司名称：{company_name}
  将解析结果写入：{output_dir}/data_pack_report.md
  """,
  description = "PDF精提取-扫描件fallback"
)
```

**无 PDF 时**：跳过此步骤。下游策略在无 `data_pack_report.md` 时使用降级方案。

---

## Step 2 详细指令

### 模式 A：单 Agent 全量分析（推荐）

```
Agent(
  subagent_type = "general-purpose",
  prompt = """
  请阅读 {shared_dir}/qualitative/qualitative_assessment_v2.md 中的完整分析框架。

  同时加载以下参考文件：
    - {shared_dir}/qualitative/references/judgment_examples.md（判断锚点）
    - {shared_dir}/qualitative/references/framework_guide.md（框架定义）
    - {shared_dir}/qualitative/agents/writing_style.md（写作风格）
    - {shared_dir}/qualitative/references/output_schema.md（参数输出规范）
    [港股] + {shared_dir}/qualitative/references/market_rules_hk.md
    [美股] + {shared_dir}/qualitative/references/market_rules_us.md

  目标公司：{stock_code}（{company_name}）

  数据文件：
    - Tushare 数据：{output_dir}/data_pack_market.md
    - 年报 PDF：已在 context 中加载（如有）

  按照 qualitative_assessment_v2.md 的 6 维度框架进行完整分析。
  特别注意"收入质量分解"和"交叉验证"部分。

  将最终报告写入：{output_dir}/qualitative_report.md
  """,
  description = "6维度定性分析"
)
```

### 模式 B：多 Agent 并行（加速）

与 v1 的 agent_a / agent_b / agent_summary 流程类似，但：
- 每个 Agent 均接收完整 data_pack_market.md + 年报 PDF 相关章节
- 不再使用 split_data_pack.py 预分发
- Summary Agent 增加交叉验证职责

---

## Step 3：HTML 仪表盘（可选 — 仅用户明确要求时执行）

**默认跳过此步骤。** 仅当用户明确要求 HTML 输出时执行（如参数含 `--html`，或提到"HTML"/"网页"/"仪表盘"）。

```bash
# 本地预览（内嵌 CSS）
python3 scripts/report_to_html.py \
  --input {output_dir}/qualitative_report.md \
  --output {output_dir}/qualitative_report.html \
  --standalone

# 网站部署（引用外部 CSS）
python3 scripts/report_to_html.py \
  --input {output_dir}/qualitative_report.md \
  --output ~/Projects/Teracnejiang.com/zh/stock/{slug}.html
```

---

## 异常处理

| 异常情况 | 处理方式 |
|---------|---------|
| PDF 下载失败 | 提示用户重新提供链接；fallback 到 WebSearch |
| PDF 为扫描件 | 定性分析：使用 pdf_preprocessor.py 处理；附注提取：fallback 到 pdf_preprocessor.py + Agent |
| PDF 附注提取失败 | 不影响定性分析；下游策略使用降级方案（无 data_pack_report.md） |
| Tushare Token 缺失 | 降级使用 yfinance，标注数据源 |
| PDF + Tushare 数据冲突 | 以 PDF 为准，标注差异 |

---

## 文件路径约定

```
{workspace}/
├── shared/qualitative/
│   ├── coordinator_v2.md              ← 本文件
│   ├── qualitative_assessment_v2.md   ← 分析框架 v2
│   ├── agents/writing_style.md        ← 写作风格（复用）
│   └── references/                    ← 参考文件（复用）
├── scripts/
│   ├── tushare_collector.py           ← Tushare 采集
│   └── report_to_html.py             ← MD→HTML
├── strategies/turtle/
│   └── phase2_PDF解析.md              ← 附注提取格式规范（Step 1C 引用）
└── output/{code}_{company}/
    ├── annual_report.pdf              ← 年报 PDF
    ├── data_pack_market.md            ← Tushare 结构化数据
    ├── data_pack_report.md            ← PDF 附注结构化数据（Step 1C 输出，供下游策略）
    ├── qualitative_report.md          ← 分析报告
    └── qualitative_report.html        ← HTML 仪表盘（可选）
```

---

*定性分析模块 v2.0 | PDF-first 协调器*
