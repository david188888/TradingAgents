# 独立基础研究与补充关注点：本地验收

Status: Historical

Do not use this document as evidence of current implementation behavior.

2026-10-07。依据用户确认的 [方案 A 规格](../superpowers/specs/2026-10-07-independent-research-and-focus-response-design.md)，实现新运行 V6。当前行为以 [Web 操作](../operations/evidence-research.md)、[记录契约](../contracts/research-record.md)与代码为准。

## 已实现与核对

- 基础任务由模式拥有。collector 移除用户关注点；专项、挑战、验证选择、综合及其身份不消费关注点。固定同一 V0、run_id 与核查时间，比较留空、AI、现金流、无关主题、指令注入五种输入，三个模式的全部核心上下文、模型 prompt、基础身份和记录摘要相等。
- `native.output` 持久化后才允许 `native.focus_response`。独立闭合 schema 绑定基础摘要、最终输入 snapshot、原始关注点及合格引用；额外基础字段、未知 claim、无保存内容、不可用或未来来源被拒绝。基础综合 fallback 跳过补充。
- V6 专用 focus bucket 最多 1 次，仍计入总 12 次；quick SDK 无修复、重试或工具。普通模型/结构/引用错误、额度耗尽和剩余时间不足保存明确 unavailable；显式取消与全局持久化失败继续失败。测试验证基础先保存与补充超时后仍可发布基础。
- 基础公开记录先发布，补充有单独候选、授权摘要、发布 barrier 与 durable disposition。局部补充发布失败不影响基础报告；未知 dispatch 不重复、SDK cache 可恢复、commit 与 disposition 间崩溃可恢复。保存 unavailable 后不再隐式重试提升。
- `/reader/focus` 在选定序列读取 committed bytes，验证请求、输入、基础与授权绑定；不读取候选为公开回答，不补写或调用模型。损坏补充独立降级，基础仍可读；未来读取边界返回 409。SSE/reducer、Reader/Audit 角色与主/补充/修复计数同步。补充引用不进入 claim authorship。
- 控件改为“补充关注点（可选）”；V6 先显示研究范围和综合判断，补充放在全部基础章节之后。Reader、Agent 产物和 Markdown 使用相同的已发布回应/稳定缺失状态。跨运行与事件边界的迟到响应被拒绝。V1–V5 保留旧研究问题语义、版本读取政策、恢复与报告渲染。

## 验证

| 检查 | 结果 |
| --- | --- |
| Python 全量 pytest | 3248 passed；修正客户端边界错误码与固定 V5 旧验收版本后重跑通过 |
| Python unit 标记 | 990 passed |
| 补充隔离/恢复/发布/引用测试 | 31 passed |
| 原失败点、公开 wiring、process、补充回归 | 85 passed |
| 额外批量入口回归 | 1 passed，单独执行；将可选关注点从 batch API 传入独立运行，并核对基础上下文不可见该文本 |
| Vitest | 46 files / 330 tests passed |
| Playwright | question-reader + catalyst-wiring，共 8 passed；最终生成 SPA、本地合成 FastAPI/SSE/store，包含桌面证据/角色/关注点及三模式回归 |
| 公共检查 | npm ci、typecheck、build、docs checker、Ruff、git diff --check 通过；tracked static 同步 |

Playwright 初次受 macOS MachPort 沙箱限制未启动；按相同测试命令在允许浏览器启动的本地环境重跑后通过。浏览器检查与截图确认综合判断在前，关注点回应为最后一个报告章节，引用仍能打开保存依据。

## 原样本与边界

只读核对原 002130.SZ 运行 `run_20261006T080541489282Z_c275dbb3`，Reader 仍为 ready。原公开研究记录 SHA256 为 `88f852ad9f8d2768dd76d9c9c4362ce8afe122be527ca1c2d75bc1ebabd7ba0b`；Markdown SHA256 为 `c04eb6365a6b500636cb7fc4dfcfa493c0c63836aa7b44725907f6cea26a8bd6`。当前文件均与原发布事件摘要一致；未重写旧数据。

验证证明输入隔离、预算与保存/展示接线，未评估真实模型研究质量。本次未新增付费运行、未把旧问题主导的推断当作新独立分析，也未执行 Git push、PR、merge 或在用服务重启。已有 Web 服务需要重新加载代码后，新建运行才采用 V6；历史运行保持原版本。

## 发布前知识收尾（2026-10-07）

用户随后授权 GitHub 分支推送、PR 合并与文档收尾。本段记录发布前审计；GitHub 的 PR 状态、检查与 merge commit 是远端集成凭证，不由本地验收推导。

| 事实面 | 状态 | 核对与处置 |
| --- | --- | --- |
| 代码 | changed-and-verified | V6 的输入隔离、补充契约、发布/恢复和读端已通过上表门禁；批量入口额外通过。 |
| 运行态 | pending | 在用本地服务仍未加载 `/reader/focus`，返回 404；旧样本 `/reader/record` 仍可读。服务重启和新真实模型运行未纳入本次授权。合成浏览器验收已通过。 |
| 文档 | changed-and-verified | README 双语、架构、记录契约、Reader、Web 操作、批量与推理配置已对齐。替换了操作页前半段仍把用户问题注入核心分析的旧说明；设计/实施保留历史标记和索引。 |
| 规则 | verified-current | 根 AGENTS 为共享真身，CLAUDE 导入它；包/前端规则与 schema、适配器、static 同提交约定一致，未发现本次影响的死引用。 |
| 记忆 | out-of-scope | Codex 生成记忆只读；未请求长期记忆修改。Hindsight 本倡议页仍在生成，未将旧页面当作 V6 当前合同。 |
| 工作区 | verified-current | 本次改动范围核对；保留当前分支、浏览器报告和截图。另有八个既有 worktree，不属于本次清场范围。 |

GitHub 仓库没有 Actions workflow；检查是否存在及合并资格仍以 PR 的实时状态为准。分支/报告清场未执行，复核现场保留。
