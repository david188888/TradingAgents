# C1：三模式共享的有界验证执行器

Status: Frozen Design

Do not use this document as evidence of current implementation behavior.

这是已认可的[统一研究方案](2026-09-30-evidence-driven-research-and-reader-proposal.md) C 阶段的接口细化，不改变 research-only、classic 默认或额度。本批交付可直接调用并通过真实 durable journal 恢复的验证模块；不宣称完成整个 C 阶段或三模式生产图迁移。

## 目标与接口

`agents/schemas/_verification_plan.py` 定义 strict/frozen 的 `VerificationPlanV1`、任务与数值条件；`research/verification_tools.py` 执行 allowlist 条件；`execution/verification_executor.py` 协调现有 durable ledger、恢复、取消、V1 和 `ResearchRecordV1`。输入为已校验、construction=native 且仅有 V0 的研究记录，以及至多三个任务。三种 record.mode 使用同一执行器，不解释用户未提供的原持仓假设。

任务明确绑定 task/challenge/hypothesis/V0；条件文本必须是该 native hypothesis 已保存的 assumption 或 invalidation condition；挑战只能针对这个 hypothesis 对应的单条 inference。适配推断没有明确可反驳条件，拒绝把它转成自动验证。计划摘要包含完整输入 record hash、计划版本与所有任务参数，恢复时任何改变在 dispatch 前拒绝。

## 首批 allowlist 与结果范围

- 财务条件：从已保存且未截断的 `tushare.financial_statements` source_fields 按精确报告期读取收入、归母/净利润、经营现金流、总资产/负债。表名/字段组合代码维护；行的披露日期、报告期、来源 available/usable_as_of 必须满足 cutoff。相同字段、相同月日的报告期之间可算差值或正基期增长率；不支持跨口径比较、模糊字段或自由表达式。
- 指标条件：读取已有 available metric 的值、单位和输入引用，检查窗口与来源资格。只是对已保存代码指标作阈值比较，明确不宣称重新计算原始行情。
- 不获取新的正文/供应商数据，不运行模型，不接受任意 URL、脚本、SQL 或 Python。未来报告期、saved_summary、公告标题、缺失/重复行、单位/期间不一致、非有限值和无资格数据都未解决。

所有结果是 `predicate_only`：必要条件满足可以支持这个条件，不足以证明整条假设；失效条件满足是该条件的反证，未触发失效条件只能 inconclusive。执行记录增加可选 hypothesis/plan/condition/scope 字段，与旧记录兼容；完整计划和操作结果保存在 durable checkpoint。关键挑战不因计算成功而自动关闭，不调整源 case 判断。

## 预算与恢复

复用当前 run 的 durable ledger（已具备 journal、cached_result 与 record_result），不创建第二本额度。一次 SUPPLEMENT_ROUNDS，至多三次 SUPPLEMENT_CAPABILITIES，实际工具执行同时计 DATA_CAPABILITY_CALLS；纯本地检查无 HTTP 或模型次数。按 critical/material/minor、task ID 稳定串行执行。预留、dispatch、结果保存、settle 使用现有持久化许可；许可持久化失败禁止调用工具。

输入身份先保存。原有 round dispatch 是恢复的已授权证明，不重新收费。任务曾 dispatch 而没有已保存结果时保守记为 unknown，禁止自动重做；未 dispatch 的 reservation 可以由原有 reconcile 回收。已有结果经 hash/身份校验后复用。额度拒绝与取消写操作 outcome，不伪造 executed_at 或已执行验证；工具实际执行但无法验证数据则可记录 unavailable。工具异常只保存固定原因，不保存异常全文。

## V0/V1 与失败

V0、原 claims/hypotheses/challenges/metrics 不改写。实际成功执行数值条件后，把输入引用、运算、条件结果保存为 derived source_fields（非独立来源），追加 V1 和绑定验证记录。不可用执行可无新增 evidence；V1 仍由真实执行记录证明。零挑战/零执行不造 V1。结果必须重新通过 canonical model 校验；输出在 checkpoint 保存完整 record 与内容 hash，重读不调用工具。取消中止后续 dispatch，保留已核查材料，恢复不返还消耗。

## 集成边界与验证

这是 C1 可运行模块，不把 classic/catalyst 的兼容推断冒充新假设；现有生产路径仍发布空 executed verification。C2 再让专项生成 native 假设和结构化条件，由挑战阶段选择核查，并在最终综合前调用 C1。此模块复用持久化接口，不触碰 classic 指纹、已有 catalyst stages/roles 或用户 store。

测试包括三模式、真/假必要条件、触发/未触发失效条件、差值/增长率、负/零基期、精确日期与单位、截断/summary/缺行/双行、未来与不可用输入、NaN/inf、参数/来源污染、条件绑定、V0 不变、V1 哈希/派生血缘、预算拒绝无 dispatch、取消、工具故障无私密诊断、保存失败、真实 RunStore/journal 恢复幂等、不明调用不重做、已改计划/输入在恢复前拒绝。原兼容记录/只读投影和前端一起回归；显式排除 live DeepSeek。不得宣称准确率提高。
