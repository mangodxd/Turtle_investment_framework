# Changelog — 龟龟投资策略 v2

> 本文件记录 v1.1 → v2 的所有变更。当前版本：**v2_beta**

---

## v2_beta (2026-04-05)

### PDF-first 架构升级

business-analysis 从 WebSearch-first 升级到 PDF-first 数据流：

- 年报 PDF 作为主数据源，直接载入 1M context，Tushare 仅作历史序列补充
- 单 Agent 模式取代 v2_alpha 的多 Agent 并行拆分（Agent A/B/C + Summary）。实测单 Agent 在交叉验证上更优，所有维度共享同一 context 消除信息孤岛
- 新增 PDF 本地缓存检查：下载前先 glob `output/{code}_{company}/` 中已有 PDF，避免重复下载
- 新增 `coordinator_v2.md` + `qualitative_assessment_v2.md`

### Turtle 策略 Pre-flight 合并

将独立的 `phase3_preflight.md`（数据校验+口径锚定）合并进 `phase3_quantitative.md` 的 Step 0：

- Pipeline 从 3 个串行 Agent（Pre-flight → Agent B → Agent C）缩减为 2 个（Agent B 含 Step 0 → Agent C）
- 每次分析预计节省 2-3 分钟（消除 1 次 Agent 启动 + 9 次文件读取 + 1 次文件写入）
- `phase3_valuation.md` 不再依赖独立的 `phase3_preflight.md`，从 Agent B 输出读取基础信息
- `phase3_preflight.md` 保留为文档参考，不再被 pipeline 调用

### 新增独立估值模块

- `/valuation` slash command：独立于龟龟策略的通用估值分析
- `scripts/valuation_engine.py`：DCF / DDM / 可比估值 / Graham 四种方法
- `strategies/valuation/`：coordinator + phase2_valuation + 参考文件（方法论/分类规则/模板/示例）

### Tushare 模块增强

- `assembly.py`：新增 §17 衍生指标预计算（Factor 2/3/4 加速）
- `--refresh-market` 模式：仅刷新 §1/§2/§11/§14（增量更新，<5秒）
- `financials.py` / `infrastructure.py`：minor fixes
- `report_to_html.py`：支持 `--standalone` 内嵌 CSS 模式
- `tests/test_refresh_market.py`：新增 refresh-market 测试覆盖

### 测试

- 新增 `test_refresh_market.py`：refresh-market 模式测试覆盖
- 总测试数：792（v2_alpha 时为 769）

### 实战验证

完成两只标的的端到端全流程（business-analysis + turtle-analysis）：

| 标的 | 结论 | 关键发现 |
|------|------|---------|
| 美的集团 (000333) | Observe 30% | Gross R 5.69% > 门槛，GG 3.53% < 门槛（SGA proxy 驱动的保守偏差），KUKA 商誉 34.3B 为潜在风险 |
| 海尔智家 (600690) | Observe 50% | 股价低于地板价 7.4%，零价值陷阱信号，但毛利率连降 5ppt + AR 增速远超营收需警惕 |

---

## v2_alpha (2026-03-31)

### 架构重构：模块化拆分

**从 `prompts_v2/` 到 `shared/` + `strategies/`**

v1.x 所有内容（数据采集、preflight、定性、定量、估值）耦合在 `prompts_v2/` 中。v2 将定性分析独立为通用模块：

- `shared/qualitative/` — 通用定性分析模块（6维度商业质量评估）
  - 可独立运行（`/business-analysis` 命令）
  - 可被龟龟策略调用（替代原 phase3_qualitative.md）
  - 可被烟蒂策略、未来其他投资框架调用
- `strategies/turtle/` — 龟龟策略专属模块
  - 数据采集（phase1/phase2）
  - Preflight 数据校验
  - 穿透回报率计算（phase3_quantitative.md）
  - 估值与报告组装（phase3_valuation.md）
- `prompts_v2/` 已删除，文件迁移至上述两个目录
- `prompts/` 保留为 v1 只读遗留

**新增文件**：
| 文件 | 用途 |
|------|------|
| `shared/qualitative/coordinator.md` | 独立定性分析入口 |
| `shared/qualitative/qualitative_assessment.md` | 6维度分析 prompt |
| `shared/qualitative/data_collection.md` | 轻量级 WebSearch 指令 |
| `shared/qualitative/references/output_schema.md` | 结构化参数输出 schema (v1.1) |
| `shared/qualitative/references/framework_guide.md` | 框架说明固定附录 |
| `.claude/commands/business-analysis.md` | `/business-analysis` 命令 |

**变更文件**：
| 文件 | 变更 |
|------|------|
| `strategies/turtle/coordinator.md` | 路径引用从 `{prompts_v2_dir}` 改为 `{shared_dir}` + `{strategy_dir}` |
| `strategies/turtle/references/factor_interface.md` | 新增 shared output_schema 引用和 moat_rating 映射说明 |
| `.claude/commands/turtle-analysis.md` | 入口从 prompts/coordinator.md 改为 strategies/turtle/ |
| `CLAUDE.md` | 反映新目录结构 |

---

### 护城河分析框架升级

**维度二（D2）重大扩展**，灵感来源：太阳纸业护城河深度分析 + Greenwald 竞争优势理论

v1 的 D2 仅有定性的非技术/技术双层护城河评估。v2 扩展为6步结构化分析：

| 步骤 | 新增内容 | 来源灵感 |
|------|---------|---------|
| 2.1 行业地图 | 先定义竞争战场：细分市场、进入壁垒表（5类）、CR4 | Greenwald |
| 2.2 量化验证 | ROE vs 门槛（8/15/25%）、份额稳定性、低谷韧性 | Greenwald |
| 2.3 双框架分析 | 框架A（非技术+技术双层）+ 框架B（供给侧/需求侧/规模经济） | 新增 Greenwald 三维 |
| 2.4 虚假优势辨析 | 品牌≠护城河、运营效率≠结构壁垒等 | 太阳纸业案例 |
| 2.5 竞争对手对比 | vs 前2-3名对手逐维度对比表 + 差距可持续性 | 太阳纸业案例 |
| 2.6 可持续性与监控 | 护城河监控锚点（3个KPI，含当前值和警戒线） | 太阳纸业案例 |

**新增结构化参数**：14个（market_cr4, entry_barrier, roe_5y_avg, moat_existence, moat_framework_primary, supply/demand/scale_ratings, false_advantages, competitor_ranking, advantage_gap_sustainability, moat_sustainability, moat_monitor_kpis）

**judgment_examples.md 拆分**：
- 通用锚点（护城河、MD&A、管理层 + Greenwald 三维示例 + 虚假优势辨析）→ `shared/qualitative/references/`
- 龟龟专属锚点（G系数、分配意愿、λ可靠性）→ `strategies/turtle/references/`

---

### 报告可读性与输出格式

**可读性改进**：
- 新增 **执行摘要**（报告开头半页，结论先行 + 关键指标表）
- 新增 **深度总结与投资启示**（报告末尾2-3页：商业模式本质、优劣势归因表、竞争定位、投资者启示、监控锚点展开、催化剂与风险事件、一句话最终结论）
- 写作风格指令：结论先行、重点加粗、通俗表达、去重、逻辑过渡
- 每个维度开头用加粗一句话结论引导

**HTML 仪表盘报告**：
- `scripts/report_to_html.py`：MD → HTML 转换（Markdown + Jinja2）
- `shared/qualitative/templates/dashboard.html`：IBM Plex 字体、暖色调浅底 + 自动暗色模式、语义色彩标签（绿/琥珀/红）、KPI 卡片、Verdict 横幅、折叠式附录
- 双输出：MD（策略消费）+ HTML（人类阅读 / 打印 PDF）

**固定附录**：
- `shared/qualitative/references/framework_guide.md`：Greenwald 框架说明、飞轮护城河概念、评级标准定义表、量化验证门槛

---

### Agent Team 并行架构

将单 Agent 串行改为多 Agent 并行，提升效率并降低 context 压力：

```
Step 3.0: split_data_pack.py → 按维度切割数据子集 + D6 触发检查
Step 3.1: 并行执行
  Agent A: D1(商业模式) + D2(护城河)  ← 最重的维度，合并消除依赖
  Agent B: D3(外部环境) + D4(管理层) + D5(MD&A)  ← 天然独立
  Agent C: D6(控股结构)  ← 条件触发，大概率跳过
Step 3.2: Summary Agent → 执行摘要 + 深度总结 + 报告组装
Step 4: report_to_html.py → HTML 仪表盘
```

**新增文件**：
| 文件 | 用途 |
|------|------|
| `scripts/split_data_pack.py` | 确定性数据预分发 + D6 触发检查 |
| `shared/qualitative/agents/agent_a_d1d2.md` | Agent A prompt（D1+D2） |
| `shared/qualitative/agents/agent_b_d3d4d5.md` | Agent B prompt（D3+D4+D5） |
| `shared/qualitative/agents/agent_summary.md` | Summary Agent prompt |
| `shared/qualitative/agents/writing_style.md` | 共享写作风格前置指令 |

---

## 待完成（v2_rc 路线图）

### 定性模块
- [x] ~~Agent Team 端到端测试与调优~~ → 改为单 Agent 模式（v2_beta）
- [ ] D2 护城河分析的边界案例处理（如 platform 型企业的框架选择）
- [ ] HTML 模板增加 bar chart（利润率趋势可视化）和 signal dots（风险信号矩阵）

### 龟龟策略（strategies/turtle/）
- [x] coordinator.md 调度改为引用 shared 定性模块（v2_beta 已完成）
- [x] phase3_preflight 合并进 phase3_quantitative Step 0（v2_beta）
- [x] 端到端 `/turtle-analysis` 测试 — 美的集团 + 海尔智家（v2_beta）
- [ ] W2 员工支出 SGA proxy 偏差优化（当前驱动 HH 偏差过大）
- [ ] Agent B + Agent C 进一步合并可行性评估

### 估值模块（strategies/valuation/）
- [x] 新增独立 `/valuation` 命令 + valuation_engine.py（v2_beta）
- [ ] 端到端测试与调优

### 烟蒂策略（strategies/cigarbutt/）
- [ ] 创建 cigarbutt coordinator + 策略专属 prompt
- [ ] 接入 shared 定性模块
- [ ] 端到端 `/cigarbutt-analysis` 测试

---

## 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v1.0 | — | 初始版本：6-phase pipeline, 4 factors |
| v1.1 | — | 17 improvements across 9 files, shared_tables, HK/US support |
| v2.0-alpha | 2026-03-31 | 模块化拆分 + Greenwald 护城河框架 + HTML 仪表盘 + Agent Team |
| v2.0-beta | 2026-04-05 | PDF-first + 单Agent + Pre-flight合并 + 估值模块 + 实战验证 |
