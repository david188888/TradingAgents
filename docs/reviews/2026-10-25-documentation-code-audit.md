# 文档与代码审查及精简结果（2026-10-25）

Status: Historical

Do not use this document as evidence of current implementation behavior.

基线：`main` / `de7f324f2b41082fd92e95dc676a694613b6ed0d`，版本 `3.7.0`。
当前行为从[现役索引](../README.md)进入。用户已确认保留归档、精简现役文档；已落实文档收敛，并按下表问题完成代码整改；验证结果见文末。

## 文档应服务的两个目的

让读者快速开始使用；让开发者快速理解当前目标、架构、流程和修改边界。
只有帮助读者操作、定位实现、理解关键取舍或避免重大错误的内容，才值得长期维护。
字段、枚举、完整状态机由代码与测试拥有；单次测试计数、会话过程和旧方案不进入必读正文。

已采用以下四类核心页面，实际内容优先于机械行数指标：

| 页面 | 必须回答的问题 | 收敛后行数 |
| --- | --- | --- |
| [README](../../README.md)，中英文对齐 | 做什么、适合谁、怎样启动、主要限制、下一步读哪里 | 89 行/语言 |
| [ARCHITECTURE](../../ARCHITECTURE.md) | 当前目标、主流程、模块职责、关键约束、扩展入口、少量未完成目标 | 141 行 |
| [Web 操作](../operations/evidence-research.md) | 如何创建、读懂结果、配置模型、处理失败及恢复 | 146 行 |
| [CONTRIBUTING](../../CONTRIBUTING.md) | 开发环境、修改路由、必要验证、生成资产和发布边界 | 81 行 |

[docs/README](../README.md)仅作短导航；AGENTS 保留必要机器协作规则。
研究合同、数据源、账户、诊断和兼容说明作为按需参考。18 份重复专题改为短指针，旧章节锚点保留。
127 篇原有历史正文逐字节保持不变；不改写其中的当时观测或授权。核心阅读从 1201 行降至 457 行（约 62%）。

## 审查发现与文档处理

- **版本漂移已对齐**：当前新建统一解释为 V8/V2，历史身份仍按保存版本读取/恢复。
- **创建教程已修正**：只指导当前公司研究；holding/catalyst 的旧创建示例不再混入新建操作。
- **配置边界已说明**：统一官方日历优先链；明确独立搜索关闭的服务端环境变量，未虚构 Web UI 开关。
- **职责已收敛**：架构 429→141 行、Web 操作 611→146 行；重复专题合并到负责该语义的参考页。
- **历史材料不宜成为必读**：127 篇历史正文已审读；部分有计数矛盾、上界推论越界或将派发写成确认计费。保留时应标注适用时点，不能沿用为当前结论。

## 代码审查的关键结果

P1 优先处理持久状态正确性；P2 表示有具体触发条件的功能或操作问题。

| 优先级 | 已核实的问题（均已修复并补回归） | 主要位置 |
| --- | --- | --- |
| P1 | 完成事件已落盘但快照写入失败，重开只补序号，运行状态和完成信息仍旧 | [runtime/store.py](../../tradingagents/runtime/store.py) |
| P2 | 同 ID 恢复被 React 合并更新，界面不重新订阅 | [WorkbenchLayout](../../frontend/src/components/layout/WorkbenchLayout.tsx) |
| P2 | 删除排队批次成员返回 204，留下悬空引用，随后取消批次返回 404 | [api.py](../../tradingagents/web/api.py) |
| P2 | SSE 重连首次快照 GET 失败即停止后续退避 | [useRunStream](../../frontend/src/hooks/useRunStream.ts) |
| P2 | queued 被历史过滤；界面只取默认 20 条，忽略后续游标 | [projections](../../tradingagents/web/projections.py)、[useRunHistory](../../frontend/src/hooks/useRunHistory.ts) |
| P2 | classic 延迟摘要响应可把选中的 B 公司视图覆盖为 A | [useRunView](../../frontend/src/hooks/useRunView.ts) |
| P2 | 多缺口搜索把所有命中按第一条需求处理，财务 PDF 恢复依赖排列顺序 | [search_coordinator](../../tradingagents/execution/search_coordinator.py) |
| P2 | 兼容研究包把相邻季度发布为同比：Q1=100、Q2=120 得到 revenue_yoy=20% | [research_package](../../tradingagents/research/research_package.py) |
| P2 | Google/Azure 丢弃共享配置中的输出 token 上限 | [provider_kwargs](../../tradingagents/llm_clients/provider_kwargs.py)、对应 provider client |
| P2 | benchmark 只找 V1 产物，将已发布 V8/V2 计为没有报告/综合失败 | [eval_benchmark](../../scripts/eval_benchmark.py) |
| P2 | wheel 缺少方法论 Markdown；主要影响 built distribution 的 classic 方法论 | [pyproject.toml](../../pyproject.toml)，package-data |

同时补齐全应用 Host/Origin 边界、启动时跨进程单写入者锁、真实模型测试显式 opt-in，以及新研究的独立搜索环境变量开关。
本地无 Origin 的 API 客户端保留；锁只保障受支持的 Web 启动入口，不提供多写入者 store。浏览器攻击链与真实模型质量仍未做联网验收。
当前 native 的财务比较与 classic 指标链不同，不能把兼容链缺陷扩大为所有新研究错误。

## 架构与过时代码的判断

证据冻结、角色隔离、确定性计算、版本 codec、阶段/最终产物区分和发布屏障值得保留。
剩余维护问题是分散的版本/状态组合、graph/execution 相互调用私有接口；batch 模型已归入 runtime，Web 保留兼容导出。
应围绕明确职责收敛，不按文件大小机械拆分，也不为减少代码删除信任边界校验。
classic、catalyst、facade 与部分旧字段仍有历史恢复或公开调用职责；尚无依据直接批量删除。

## 验证与边界

审查覆盖 176 份跟踪 Markdown（23,623 行），含 127 篇历史记录和 11 份方法论；另查本地旧计划与支持材料。
三位 subagent 并行审查，整改后两轮独立复核未发现新的可行动问题；不代表逐行证明全部实现正确。

- Python 全量禁外网 socket 运行：4058 passed、74 subtests passed、1 live skipped、2 failed。错误码类型遗漏与旧 ASGI 测试 Host 已修正，失败项重跑 2 passed；未重复执行整套。
- 搜索/指标/计量定向集合 121 passed；运行状态、删除保护、来源边界和跨进程锁另有回归，集合重叠不相加。
- 前端 423 项测试、TypeScript、构建通过，生成 SPA 已重建；wheel 中 11 份方法论逐字节匹配，并通过隔离导入加载。
- Ruff、177 份 Markdown 链接/锚点检查、旧章节锚点及 127 篇历史哈希、diff 空白检查通过。
- 未做 Playwright、真实读者任务、真实模型质量或供应商覆盖验收；既有 npm 依赖告警保留，未借此升级依赖。

逐文件审读、红绿回归、完整测试和独立复核证据保留在本轮临时工作材料，不增加长期必读页面。
剩余架构债务是版本/状态策略与 graph/execution 私有接口的职责收敛；不借本轮删除历史恢复职责。
已修改产品、测试和现役文档；历史运行、凭据和服务未动，也未提交、推送或发布。
