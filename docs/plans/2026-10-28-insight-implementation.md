# Insight 研究实施计划

> **For agentic workers:** Use executing-plans to implement task-by-task. 保留当前未提交修改；没有 Git 发布授权。

**Goal:** 新研究以简化 Insight 完成专项、质疑回应和可追溯综合，兼容旧记录。
**Architecture:** 独立版本的提交、保存和发布契约；复用来源、数值目录、模型请求及持久化执行基础设施。新协议不转换回旧模型 envelope。
**Tech Stack:** Python/Pydantic、现有 durable journal、React/TypeScript。
**Spec:** [已确认的具体协议](2026-10-28-insight-protocol-design.md)。

Status: One authorized live run delivered a traceable report; follow-up context compaction and reply diagnostics verified offline。Current contracts remain owned by code and indexed contract documents.

## Global Constraints

- 四项 Insight；数字与引用由程序管理；局部失败保留合格条目。
- 综合 Agent 判断证据充分性；程序不得因缺少指定估值锚点自动否决有利评级。
- 不修改旧记录、冻结请求及提示词；新模型调用、服务生命周期与 Git 发布不自动授权。
- 现有调用预算不扩大，修复每阶段最多一次；白话解释覆盖率不参与研究验收。
- 使用现有 Conda 环境；按 CONTRIBUTING 选择检查，前端变更须构建。

## Review Focus

- 一条坏引用/结构错误导致合格兄弟条目消失：任务 1/2 验证。
- 数字相同但单位、期间或主体不同，以及普通年份被误拒：任务 1 验证。
- 恢复后引用编号变化、未知响应被重新发送：任务 2 验证。
- 撤回/修订后的旧版本继续支持总体判断：任务 3 验证。
- 只有新模型类，生产入口/发布/Reader 实际仍走旧规则：任务 4/5 验证。

## Task 1: 提交模型、证据目录和逐条接纳

Files: 新增 `agents/schemas/_insight.py`、`research/insights.py`、`tests/test_insight_protocol.py`（均在现有目录下）。
Interfaces: `InsightProposal` 为四项内容；`InsightCatalog` 保存短引用到来源/指标的映射；`compile_insights(payload, *, catalog, role, revision=1)` 返回 `InsightBatch`，包含可采纳/待验证条目和安全结构拒绝。

- [x] 先写并运行回归：七个引用、长观点、重复引用、无证据、未知引用、坏兄弟、裸数字、年份代码、指标依赖缺失。
- [x] 实现最小模型与编译器；复用 `render_numeric_anchor`，不调用旧 `_compile` 或前提绑定。
- [x] 运行 `pytest -q tests/test_insight_protocol.py`，预期全部通过；Ruff 检查改变文件。

## Task 2: 持久化的专项调用与单专项闭环

Files: 新增 `execution/insight_model.py`、`graph/insight_research.py`；修改 `execution/native_runner.py` 版本分流；新增对应测试。
Interfaces: 复用 `invoke_model_request` 和 durable ledger；阶段上下文冻结 `InsightCatalog`，缓存已编译条目；输出独立 Insight record。

- [x] 先写失败测试：请求使用固定 schema、局部修复、恢复不重复发送、预算及取消传播。
- [x] 接入一个专项，完成保存和投影，再将统一协议用于其余专项；不让生产入口绕开新模块。
- [x] 针对新 caller/graph/runner 和旧恢复路径运行检查。

## Task 3: 一轮质疑回应与综合

Files: 新协议 dialogue/synthesis 模型、`graph/insight_research.py` 及对应测试。
Interfaces: 质疑和回应引用已保存 Insight；修订产生新版本；综合引用有效版本并保留缺口。

- [x] 先写失败测试：无反证、未审阅、失败、维持/修订/撤回、综合坏引用、无估值锚点但有效立场。
- [x] 实现一轮质疑和回应；综合原子输出的依据失效则不评级，独立 Insight 仍交付。
- [x] 运行图与发布边界回归，确保不执行旧评级裁决规则。

## Task 4: 发布、报告、Reader 与版本兼容

Files: `execution/native_publication.py`、`execution/output_publisher.py`、`runtime/reports.py`、`web/research_record_projection.py`、`web/manager.py`、前端契约与 Insight Reader。
Interfaces: 独立公开记录版本，复用持久化发布授权及校验；Reader 明确按版本选择，不伪装旧 record。

- [x] 先写失败测试：提交屏障、只读重放、跨 run 拒绝、Markdown/Reader 一致、旧报告读取。
- [x] 接入真实运行入口、完成状态和前端，缺口及未解决质疑保底显示。
- [x] 后端 scoped tests、前端相关 tests、一次 build，预期全部通过。

## Task 5: 对照验证、文档与审阅

- [x] 用已保存真实输入离线运行新完整链路及故障样例，明确合成响应不能替代真实模型验收。
- [x] 同步当前架构和契约文档，检查 diff；进行独立代码审阅并修复实质问题。
- [x] 准备可审阅的真实验收次数/预算，在获单独授权后执行。没有真实运行结果时不得宣布本次问题完全解决。

2026-10-29 离线验收：使用既有真实记录 `run_20261028T062613775477Z_419b76bb` 的 306 条记录、163 项来源构建专项目录；固定模型响应分别运行正常与坏引用样例。两者均完成发布及只读重放；故障样例保留 3 条合格观点、3 条待验证观点，综合无效时不输出总体评级。此检查验证数据规模与执行链路，不验证真实模型研究质量。相关后端迁移回归 246 项、前端相关回归 31 项、两条浏览器端到端路径通过；前端构建通过。独立审阅发现的引用重编号、目标映射、数量单位与综合重放问题已完成失败复现及修复。

已获授权并执行的真实验收范围：独立临时本地服务、浏览器 UI、`002130.SZ`、既有 SIWC 登录与 `gpt-6.1-terra`，只运行一次完整研究，不自动重跑。沿用上限：研究模型尝试 29 次，DeepSeek/Tavily 搜索各 50 次，补搜最多 3 轮；可选白话解释另最多 2 次调用。研究主动执行上限 900 秒；解释上限 120 秒。记录专项有效产物、质疑回应、综合及评级、引用追溯、局部失败交付和资料缺口；白话解释覆盖率不作为通过标准。

实施细节在任务边界内由执行者确定；遇到改变已确认语义或预算的事项暂停确认，不在任务间重复询问是否继续。


### 真实验收与后续修复记录

2026-10-29 从浏览器 UI 提交 `run_20261029T123016229207Z_b3e6dbdf`，两类模型均为 `gpt-6.1-terra`。约 7 分 18 秒发布 `insight-research-v1`：经营 5 条、事件 6 条、市场 3 条有效观点；14 条均完成审阅，其中 8 条被质疑、6 条无有效反证；7 条回应中 6 条修订、1 条维持，另有 1 条未形成有效回应。综合 Agent 给出中性判断并引用 11 条有效观点；发布屏障、引用重放、浏览器跳转及来源展开均通过。21 条旧版本保留但不进入有效综合依据。

研究调用 10 次，结构修复 0 次；DeepSeek/Tavily 搜索分别 16/15 次，使用 3 轮补搜。研究输入累计 1,244,965 tokens，输出 8,563 tokens。白话解释独立调用 1 次，完成本次选取目标中的 7/32 段，非研究验收指标。资料和流程缺口已显示；不能称所有质疑均已解决，也不能把单次成功推广成稳定性保证。

2026-10-30 离线后续：补齐回应拒绝的安全类别诊断；旧运行未保存该类别，因此未回应条目的精确原因仍未知。新任务冻结紧凑上下文策略，专项/质疑保留全部事实，综合仅携带有效观点及审阅/回应已经引用的依据。基于上述保存输入，综合证据目录 JSON 从 431,847 字符降至 70,334 字符（约 84%），完整审阅目录从 431,847 降至 383,947 字符。此为离线字符量测量，不是新模型 token 用量。88 项相关后端回归通过；新压缩策略尚未真实复验，原已发布报告未改写。
