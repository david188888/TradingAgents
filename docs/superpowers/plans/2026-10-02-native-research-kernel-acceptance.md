# C2 共享研究内核：本地阶段验收

Status: Historical

Do not use this document as evidence of current implementation behavior.

日期：2026-10-03（接续 10 月 2 日实施）。承接[整合验收](2026-10-02-research-data-integration-acceptance.md)、[C1](2026-10-02-bounded-verification-acceptance.md)及[接线清单](2026-10-02-native-research-wiring-implementation.md)。当前契约请查[共享记录](../../contracts/research-record.md)。

## 已实施的范围

本批在 `codex/research-data-integration-20261002` 接续 `e0bb17b`，实现可直接程序调用的三模式共享内核：

- 来源字段 → native V0：证券身份、来源 context 摘要、披露日期、历史时点、字段和源家族由代码校验。保存各财务表最多八期允许字段，复用 C1 数值解析。部分覆盖保留真实已取得字段，不推出“没有事件”。标题仅证明列表披露；用户原论点是声明；行情与风险统计不推导价值区间。
- 经营、事件、市场专项分别读取窄事实视图，固定顺序预留与合并、并发至多二。原生假设引用事实、保留必要/失效条件与替代解释；一次匿名挑战可以为零条，不要求强制多空。
- 条件 ID 绑定完整结构、假设与 V0；挑战只能选择已有条件。至多三项 C1 核查先于一次综合。条件结果不自动关闭经济挑战，关键挑战优先显示。
- 可选 assessment 绑定最终 snapshot、模式维度、最多三条依据、主要疑点与下一核查。缺估值资料或原持仓假设只约束对应维度；不足维度使用代码说明，不保留无依据的模型价值区间。旧记录不增加 null assessment，保留旧字节/摘要。
- SDK adapter 关闭隐性重试，使用真实截止时间与一个全局模型槽，每阶段最多一次 repair、全局至多两次。共用原 durable ledger；未知调用保持已消费且不重派。已保存 adapter/repair 响应可在取消/过期/MAIN UNKNOWN 后纯读取恢复。
- 原生 publication 强制要求 candidate、生命周期授权和已提交 checkpoint；失败抛错，不能回落为可选投影。Reader 与 Markdown 使用同一已保存 record，不另跑模型。Reader 首层保留判断、关键依据、主要风险、下一核查与量化，未增加选择项。

## 审阅与验证

独立审阅发现并修复：已缓存 adapter 响应被 unknown guard 丢弃、checkpoint 冲突被当普通降级、手工不合格 fact seed 进入综合、缺估值资料仍展示模型区间，以及 minor 主疑点遮蔽 critical。对应回归与最新树复查已完成。后续真实持久化串联测试发现 RFC8785 把原始统计 `2.0` 规范为 `2`，使旧 source-family JSON 摘要重建失败；现改为模型 dispatch 前保存精确 V0、恢复直接 `load_native_seed`，保留来源字段字符串与 typed metric 的准确身份。三模式发布／Reader／Markdown／真实 store reopen 的串联均通过，恢复没有新取数或模型调用。最后负责该串联的 subagent 因使用额度停止，根代理完成了修复与验收；新 V0 恢复修正不冒称已有独立复审。

最终针对性组合 **239 passed**，其中新增原生内核、事实、SDK adapter、发布／报告及三模式串联测试 **108 项**。所有测试关闭 dotenv、排除 smoke 与未标记 live DeepSeek 类。验证是程序接口、实际临时 RunStore、Python／组件测试；不声称原生浏览器 E2E、供应商重新认证或研究准确率改善。

最终全量离线：**12 failed / 2864 passed / 5 deselected / 73 subtests**。与 C1 `e0bb17b` 的 **12 failed / 2756 passed** 对比，失败集合完全相同，没有新增失败；保留 graph prefetch 3项、fundamentals 日期文本1项、runtime v2契约/恢复3项、methodology metadata2项与Web CLI日志权限3项。**全量未全绿。** 最终日志 `/tmp/tradingagents-c2-final-offline-20261003.log`，对照日志 `/tmp/tradingagents-c1-reviewed-offline-20261002.log`。Ruff、文档检查（67页）与 diff check通过。

前端 43 文件／314 项通过；npm ci、typecheck、build 通过并包含生成 static。仍有原有 16 项依赖审计告警和主 chunk 507.82 kB 的构建提示，未扩展到依赖升级。

## 尚未实施的边界

**C2 公开生产接线尚未完成。** 新 `evidence_v1` 独立入口或扩展 `catalyst_v1` 的兼容选择已向用户提问，尚未收到答案。本批没有更改 public request/profile/mode、RunManager factory/resume/retry、Web 创建入口或角色事件注册；强制 publisher 的组件测试不能证明生产 manager 的 completed 闭环已接通。

默认 classic、research-only 与预算上限保留。完整 D Reader、E 同证据质量/成本对照、真实来源/模型评估与默认迁移仍为后续工作。本批只做本地整合，不 push、不合并 main。
