# C2：原生研究接线实施

Status: Historical

Implementation note: shared kernel and independent evidence_v1 public routing implemented.
See [public wiring acceptance](2026-10-03-native-research-public-wiring-acceptance.md).

Do not use this document as evidence of current implementation behavior.

依据[设计](../specs/2026-10-02-native-research-wiring-design.md)与既有 A–E 计划。用户已确认独立 evidence_v1；classic 默认及 catalyst_v1 旧执行/恢复保留。

1. canonical 原生综合与阶段输出模型；校验模式维度、声明类型、snapshot／引用／条件来源。原 Record 缺省兼容。
2. 纯 source→native V0/fact/metric、模式政策和窄事实/字段视图；financial 同期字段保留、声明与事实区别、缺持仓原假设／估值降级。
3. 角色 partition、稳定预算预留／汇合，一次匿名挑战、C1 plan／执行、一次带验证结果的综合、分维度代码门槛。
4. durable 模型 caller、版本身份、源缓存、阶段及候选保存、取消/超时、mandatory publication、同源 Markdown。
5. 用户已确认的 profile/mode request、manager factory／metadata／resume／retry／roles 和 Web API 边界；native Reader/TypeScript 最小消费，不加用户选择项、不迁移默认。
6. 离线全链回归及独立审阅，前端生成资源与 current-state 文档，历史验收与下一 D/E 边界；本地提交。

## 文件与验收边界

| 步骤 | 代码归属 | 针对性验收 |
| --- | --- | --- |
| 1 | `agents/schemas/_native_stage.py`、`_research_assessment.py`、`_research_record.py` | 旧记录不增加 null 字段，snapshot/引用/三模式维度与条件合法性 |
| 2 | `research/native_record.py`、`native_policy.py` | `test_native_record.py`：身份、原始摘要、PIT、8期字段、声明/标题与事实边界 |
| 3 | `graph/native_research.py` | `test_native_research.py`：隔离、一次挑战、C1先于综合、重放、未知调用、取消与局部降级 |
| 4 | `execution/native_model.py`、`native_publication.py`、`runtime/reports.py` | `test_native_model.py`、`test_native_publication.py`、`test_native_report.py`：期限/repair、发布屏障/冲突、Markdown同源 |
| 有限 D | `frontend/.../ResearchRecordSection.tsx`、API DTO及生成静态资源 | component/Vitest、typecheck、build；不等同浏览器E2E |
| 5 | `execution/native_runner.py`、native policy/request、API/manager/roles/DTO/native Reader | `test_native_production_wiring.py`、`test_evidence_api.py`、native projection 与前端测试；完整 D/E 仍待完成 |

本阶段公开接线已完成离线验收；没有进行付费模型/供应商评估，不迁移默认 classic，不把局部研究标为成功。
