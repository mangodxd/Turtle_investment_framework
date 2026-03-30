# 龟龟投资策略 — 变更日志（Changelog）

> 本文件记录各版本的变更摘要。独立存档，不随 coordinator.md 加载进 context。

---

## v1.1（2026-03-30）

**主题：Prompt 质量优化 — 17 项改进（一致性、完整性、报告质量）**

- **新增 shared_tables.md**：支付率计算、股息税率表、门槛公式、跨币种处理规则集中管理，消除因子2/3间重复
- **新增否决门总览**：Phase 3 执行器前置展示全部 9 个否决门（Rejection Map）
- **新增分析置信度**：报告执行摘要增加数据完整性+外推可信度+Warnings影响三维评级
- **新增关键假设汇总**：报告模板增加影响结论的 6 项核心假设及其敏感性
- **新增数据约定**：金额单位转换表统一管理，Phase 1/2 交叉引用
- **新增 Phase 0 重试规则**：3次指数退避重试，失败后明确进入无 PDF 模式
- **新增阶段超时规则**：各 Phase 最大执行时间和超时行为
- **新增 Phase 3 数据澄清回流**：Phase 3 可触发最多1次补充 WebSearch
- **新增 WebSearch 批量策略**：Phase 1B 按依赖关系分4批执行，减少搜索次数
- **新增季节性行业清单**：Phase 3 年化估算时高季节性行业显式警告
- **新增商誉减值分级**：>30% 降仓50%，20-30% 标注+交叉验证
- **新增控股折价异常处理**：折价 >60% 或溢价时的明确行动规则
- **新增 Factor 2 分配能力独立性说明**：明确与因子1B模块六的独立关系
- **新增 Growth Capex 方法论对比说明**：因子2 G系数 vs 因子3全额扣除的设计意图
- **新增 MD&A 来源验证**：因子1B模块八根据来源（PDF/WebSearch/缺失）设置可信度基线
- **新增美股数据覆盖表**：明确约 60% 覆盖率和各字段降级方案

**修改文件**：coordinator.md, phase1, phase2, phase3, factor1-4, CLAUDE.md + 新建 shared_tables.md
**测试**：766 passed, 1 test updated (tax table → shared_tables cross-ref)

---

## v1.0（2026-03-07）

**主题：v0.16_alpha → v1.0 架构重构**

- **新增 Phase 0**：内置 `/download-report` 命令，自动搜索并下载年报 PDF
- **Phase 1 拆分两步**：Step A = `tushare_collector.py`（Python 脚本采集结构化数据）+ Step B = Agent WebSearch（非结构化信息）
- **Phase 2 拆分两步**：Step A = `pdf_preprocessor.py`（Python 关键词定位 7 章节：P2-P13 + MDA + SUB）+ Step B = Agent 精提取（5+1 项 footnote 数据，SUB 条件触发）
- **Pipeline 重排**：Phase 1A + Phase 2A 并行运行；Phase 1B 在 Phase 1A 完成后立即启动（§10 到达时检查 pdf_sections.json）
- **单位统一**：所有金额单位为 **百万元**（Tushare 原始单位元 ÷ 1e6）
- **新增母公司报表**：§3P/§4P 母公司损益表和资产负债表（Tushare `report_type=4`）
- **yfinance 保留为 fallback**：Tushare 失败时降级使用
- **AskUserQuestion 交互**：结构化收集持股渠道、PDF 处理方式、Tushare Token 等
- **渐进式披露**：Phase 3 精简执行器 + references/ 按需加载
