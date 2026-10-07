# 独立基础研究与后置关注点回应实施计划

Status: Archived Plan

Do not use this document as evidence of current implementation behavior.

依据：[用户已确认规格](../specs/2026-10-07-independent-research-and-focus-response-design.md)。2026-10-07 用户确认进入实施，使用 task-planning。全部故事为 Must Have；仅本地实施与离线/合成链路验收。

| 故事 | 价值与验收标准 | 点数 | 依赖 | 状态 |
| --- | --- | --- | --- | --- |
| S1 契约与版本预算 | 作为研究者，我需要关注点与基础记录分离。新闭合 schema 可验证引用；V6 独立调用桶最多 1 且总上限 12，旧版本为 0。 | 5 | 无 | Done |
| S2 独立核心与后置执行 | 作为研究者，我需要基础判断不受提问影响。同一 V0 下各核心上下文/摘要相同；基础先 durable 保存，普通补充失败不改变它，未知派发不重发。 | 8 | S1 | Done |
| S3 发布与恢复 | 作为用户，我需要结果可恢复且可核对。必需基础先发布，补充绑定摘要与授权；取消竞态、局部失败与稳定发布状态通过测试。 | 5 | S1、S2 | Done |
| S4 读契约与角色诊断 | 作为读者，我需要独立读取补充回应。API 不调用模型/取数；旧角色保持、新角色及预算/SDK 计数准确、损坏补充不影响基础读取。 | 5 | S3 | Done |
| S5 Reader 与导出 | 作为读者，我先读整体研究再看关注点。控件标签、基础优先顺序、补充引用/状态、Agent 产物和 Markdown 同源；切换运行无残留。 | 5 | S4 | Done |
| S6 回归与文档 | 作为维护者，我需要可验证交付。适用 pytest/Vitest/桌面 Playwright、docs/Ruff/typecheck/build 通过；static 同步，历史兼容验证与当前文档同步。 | 5 | S1–S5 | Done |

各故事细分为 canonical schema → 生产适配器 → focused 行为测试，完成后进入下一依赖项。不使用模型文字相似度替代上下文隔离测试；固定模拟 caller 证明基础摘要不变。需要真实付费对照时另行确认冻结输入与请求上限。

完成定义：用户规格不变量成立；普通补充失败、恢复与取消边界测试通过；受影响客户端/报告/角色/计数可核对；文档与生成资源同步；工作区无无关变更。远端发布与旧研究数据改写不属于本计划。
2026-10-07：S1–S6 已完成本地实现，当前规则见 Web operations / research-record contract。
验证结果与边界见 [同日验收记录](../../reviews/2026-10-07-independent-research-focus-acceptance.md)。
Git 远端发布、服务重启及新增付费模型对照不计入本地交付；历史研究文件保持原样。
