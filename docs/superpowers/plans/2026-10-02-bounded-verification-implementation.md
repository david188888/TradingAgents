# C1：有界验证实施

Status: Archived Plan

Do not use this document as evidence of current implementation behavior.

依据[接口细化](../specs/2026-10-02-bounded-verification-design.md)及已认可的[总体计划](2026-09-30-evidence-driven-research-implementation.md)。

1. canonical 计划模型与 verification 可选范围/绑定字段，保持历史读取兼容；更新 TypeScript mirror。
2. allowlist 财务/指标条件的纯工具，先以确定性反例确认谓词语义和 cutoff，禁止扩大为全文或自由计算。
3. 同一 durable ledger 的预留/dispatch/保存/settle，身份、round、task cache 与取消；不创建新预算。
4. V1 派生证据与执行结果、未执行 outcome、保存后的重新校验与恢复；旧 case 不改结论。
5. schema、工具、真实 journal/RunStore、旧投影、前端 typecheck/test/build、Ruff/docs/diff 检查；以整合提交 8fc9d63 的12项基线失败为参考，新增失败需解决。
6. 更新 current-state 契约和验收；本批之后 C2 专项/挑战/综合接线仍待实施，不提前修改默认入口。

上述 C1 模块及限定验证已实施，见[验收记录](2026-10-02-bounded-verification-acceptance.md)。C2／完整 D／E 不在本批完成范围。
