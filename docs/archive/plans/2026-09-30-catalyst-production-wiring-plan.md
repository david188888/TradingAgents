# 催化研究真实接线实施计划

Status: Archived Plan

Do not use this document as evidence of current implementation behavior.

归档日期：2026-10-04。正文保留编写时的设计、结果和未完成事项；归档不表示全部目标已验收。当前行为与仍待推进的计划见[文档索引](../../README.md)。

- 基线：main `168326c`，2026-09-30。
- 设计：[已批准设计](../designs/2026-09-30-catalyst-production-wiring-design.md)。显式接线已实施，验证边界见[验收记录](../reviews/2026-09-30-catalyst-wiring-acceptance.md)。
- 范围：显式试用完整路径，classic 默认不变，不执行批量评估/默认切换/推送。
- 估量是任务复杂度点数，不是耗时或费用承诺；各项均为 Must。

| 步骤 | 用户价值 / 复杂度 | 主要边界 | 前置 | 验收 |
| --- | --- | --- | --- | --- |
| W1 请求和身份（3） | 关注问题不会丢失 | execution/models、web/schema/api/manager、TS contract | 无 | 400码点/emoji边界；profile/问题/policy创建重载重试保留；classic指纹不变 |
| W2 数据/模型适配（8） | 新流程消费真实证据和配置 | dataflows、research、execution | W1 | cutoff/覆盖/单位保守资格；实际请求前扣账；SDK重试关闭；引用可解析；并发config隔离 |
| W3 durable执行（8） | 中断后继承预算与已得结果 | execution、runtime、observability、workflow | W2 | 许可先持久化；未知attempt计费；stage恢复；冲突拒绝；超时/取消无迟到发布 |
| W4 Web生命周期（5） | profile实际分流且报告可读 | manager、resume、reports、projections | W3 | HTTP创建到/catalyst与Markdown链路；取消/发布两种顺序；读取/重连零调用 |
| W5 表单和读路径（5） | 可显式发起并阅读新研究 | controls、useConfig/useCatalyst、state、styles | W4 | 固定84天展望；无隐藏字段泄漏；classic入口保持；阶段/终态更新；static重建 |
| W6 工程验收（5） | 有真实边界与浏览器证据 | focused tests、Playwright、临时run store | W5 | 模型/provider mock与live分开；指定viewport/200%/键盘；有限smoke记录实际调用和产物 |
| W7 回归与文档（3） | 支持范围和限制可复查 | README双语、ARCHITECTURE、CHANGELOG、handoff | W6 | 门禁通过或记录基线失败；diff无越界；当前态只写已落地行为 |

实现按边界串行；不因模块测试通过而跳过HTTP/持久化/浏览器。新增测试验证故障和适配边界，不复制实现内部细节。

## 验证命令

Python 使用 `/Users/david/miniconda3/envs/tradingagents/bin/python`；命令按 RTK.md 加 `rtk` 前缀。

1. 各步骤对应focused pytest/Vitest。
2. `python scripts/check_agent_docs.py`、`ruff check tradingagents cli scripts/check_agent_docs.py`。
3. `npm --prefix frontend ci`、typecheck、test -- --run、build。
4. 全量 `python -m pytest -q -p no:randomly --color=no`，同名失败集合比较。
5. 浏览器隔离临时run store与日志，不清理或覆盖用户数据。
6. git diff --check、status、逐文件diff审阅。

## 基线

设计阶段原始输出 `/private/tmp/catalyst-wiring-baseline-20260930.txt`：15 failed / 2319 passed / 73 subtests。12项既有失败，额外3项为 sandbox 拒绝Web launcher写用户server.log。后续环境差异与回归分开；不能修改测试迎合失败实现。

## 完成记录

以下只在实现及验证完成后标记：

- [x] W1 请求、问题与身份。
- [x] W2 有界适配及保守资格；默认行情无 qualified 路径，真实财务未合格，均明确降级。
- [x] W3 durable 执行、预算、四阶段退出恢复及迟到结果拒绝。
- [x] W4 HTTP 创建/重试、发布仲裁、报告、只读投影。
- [x] W5 真实表单/事件/读路径，static 已重建。
- [ ] W6 原生 200% 缩放待人工验证；6 项真实浏览器、等价尺寸和一次有限 live smoke 已完成。不能把 partial live 记为研究质量通过。
- [x] W7 回归、同环境基线归因、双语与当前态文档同步；本仓库无 CHANGELOG。
