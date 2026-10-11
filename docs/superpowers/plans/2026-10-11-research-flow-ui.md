# 研究流程 UI 执行计划

- **Status: Archived Plan** — Do not use this document as evidence of current implementation behavior.

依据：已确认的 `../specs/2026-10-11-research-flow-design.md`。

视觉：浅色研究画布、明确依赖连线、紧邻输入/产物详情。内容：运行结果 → 依赖流程 → 所选环节 → 操作。交互：运行脉冲/连接流动、节点选择高亮、详情定位；终止和减少动态效果偏好下静止。

## Story 1：看清依赖与停止位置（5 points，Must）

用户在运行/失败/已发布记录中能看到共同输入、专项分工、汇合和后续环节。依赖：现有版本化角色集合与 Reader DTO。

- [x] 实现共用 ResearchFlow，仅读取 props，支持未知版本列表回退、代码职责的两个展示位置和一份统计。
- [x] 接入 NativeResearchPage 与 NativeReader 过程视图，保持现有 hooks 和回调边界。
- [x] 检查执行状态与公开产物状态分离，不制造计数、失败节点或百分比。

验收：V6 含 focus、V7 无目标回应、未知版本、真实失败、未发布及已发布场景准确；代码角色不获得虚构进度。

## Story 2：就近阅读产物并准确表达可用性（3 points，Must）

用户选择节点后立即看到对应详情，可以关闭、返回和重试。依赖：Story 1、useReaderAgent。

- [x] 相邻详情与窄屏纵向定位，重复点击、关闭返回焦点、跨运行重置。
- [x] 修正 terminal/pending_publication 文案；确认没有已发布记录后才提示无报告，loading/error 单独处理。
- [x] 为 Agent 详情补齐独立使用时的 tokens、按钮和正文层次。

验收：鼠标/键盘选择、重复点击、角色切换、关闭、失败重试、跨运行；未发布不称最终报告可读。

## Story 3：画布视觉与可验证交付（3 points，Must）

依赖：Story 1、2。

- [x] 浅点阵、节点/连线、容器断点、运行限定动画和 reduced motion。
- [x] 更新 Vitest/Playwright 场景与当前 Reader 文档。
- [x] agent-doc check、Ruff、npm ci/typecheck/build/Vitest/适用 E2E、diff check；生成 SPA 一起交付。
- [x] 用浏览器核对真实失败、已发布过程、390px/桌面及动画停止，保存截图。

验收：无横向溢出，动作不依赖悬停；静止状态没有运行流动；保留用户数据与无关脏状态。核心模型绑定、错误分类修复和新付费运行不属于本计划。

交付记录：[2026-10-11 UI 验收](../../reviews/2026-10-11-research-flow-ui-acceptance.md)。V7 补充回应读取兼容在回归中补齐，沿用原 API 的身份保护。
