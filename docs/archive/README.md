# Documentation Archive

- **Status: Historical** — 历史设计与交付记录，**不是当前实现行为的证据**。当前行为以代码、passing tests 和 [当前状态文档索引](../README.md) 为准。

`docs/` 下除 `contracts/`、`operations/`、`architecture/`、`integrations/`、
`decisions/` 外的其余目录都属于归档。本页是这些目录的完整清单；
当前状态的导航入口是 [docs/README.md](../README.md)。

## 归档约定

每个归档文档在开头声明 `Status: Historical`、`Status: Frozen Design`、
`Status: Archived Plan` 或 `Status: Verification record`，并指向当前状态文档。
归档不保证原始目标全部达成，也不因归档而获得认可。

## Reviews And Verification Records

- [v3.7.0 发布说明](../reviews/2026-10-24-v3.7.0-release-notes.md)：双路搜索、有界补证与 V2 证据版本。
- [双路搜索实施收尾](../reviews/2026-10-24-dual-search-closeout.md)：11 项任务、独立审查修复、验证范围和知识面状态。

`docs/reviews/` — 交付验收、发布说明与定点调查记录。

- [v3.6.0 release notes](../reviews/2026-10-23-v3.6.0-release-notes.md): 事实前提、假设导向核查、财务比较、分段综合及可逆元数据离线对照；生产压缩未启用。
- [Architecture and workflow review](../reviews/2026-10-20-architecture-workflow-review.md): 当前工作区多维审查，含日历负向复现、语义支撑缺口、真实记录计量及定向验证。
- [Remediation handoff validation](../reviews/2026-10-22-remediation-handoff-validation.md): F01–F07/P3 进度复核、获批的两项 F02 修复、最终 Agent 身份拒绝及下一阶段决策边界。
- [F04 read-only input measurement](../reviews/2026-10-22-f04-input-measurement.md): 哈希核对的旧策略输入与用量、新策略合成清单、负向保留反例及待确认的下一步。
- [F04 reversible metadata view](../plans/2026-10-22-f04-lossless-metadata-view.md): 复用既有元数据别名的已批准设计、离线收益探测与生产接入边界。
- [F04 metadata view validation](../reviews/2026-10-23-f04-metadata-view-validation.md): 纯 codec、完整 prompt 净收益、篡改/校验反例与历史/合成样本对照，生产未启用。
- [Remediation knowledge closeout](../reviews/2026-10-23-remediation-knowledge-closeout.md): F02／F04 现役入口对齐、规则与技能依赖核对、复验及保留现场，发布和清场未执行。
- [F03 implementation and offline validation](../reviews/2026-10-21-f03-implementation-validation.md): 独立命题、分类与任务去向、保存阶段/恢复及固定分母验收，含两类 F02 既有失败和历史日期缺口。
- [V8 Phase 0 live replay](../reviews/2026-10-19-v8-phase0-live-replay.md): 服务重启、宁德时代与江淮汽车真实 Luna 中途验收，含未完成分段、用量与解释失败边界。
- [V8 Phase 0 offline baseline](../reviews/2026-10-18-v8-phase0-baseline.md): 只读基线、计量口径与 8/8 综合输入哈希复现，尚未完成 Phase 0。
- [V8 Phase 0 synthesis capture](../reviews/2026-10-18-v8-phase0-synthesis-capture.md): 单次 Luna 采集、逐字段复现及引用入口修复的历史快照。
- [V8 Phase 0 sectioned synthesis](../reviews/2026-10-18-v8-phase0-sectioned-synthesis.md): 已确认的分段发布语义、离线原始响应重放与分层验收边界。
- [V8 Phase 0 structured financial checks](../reviews/2026-10-18-v8-phase0-structured-financial-checks.md): 有限财务子问题独立交付、完整现金流桥边界与历史兼容验证。
- [Upstream v0.7.0 selective review](../reviews/2026-10-17-upstream-v070-review.md): ChatGPT 参数与刷新韧性、发布包完整性及不引入的边界。
- [ChatGPT upstream adaptation validation](../reviews/2026-10-17-chatgpt-upstream-adaptation-validation.md): 用户排除安装包发布后的两项适配与离线回归记录。
- [v3.5.0 release notes](../reviews/2026-10-16-v3.5.0-release-notes.md)
- [v3.4.0 release notes](../reviews/2026-10-13-v3.4.0-release-notes.md)
- [v3.3.2 release notes](../reviews/2026-10-12-v3.3.2-release-notes.md)
- [v3.3.1 release notes](../reviews/2026-10-12-v3.3.1-release-notes.md)
- [v3.3.0 release notes](../reviews/2026-10-11-v3.3-release-notes.md)
- [v3.2.0 release notes](../reviews/2026-10-11-v3.2-release-notes.md)
- [v3.1.0 release notes](../reviews/2026-10-07-v3.1-release-notes.md)
- [v3.0.0 release notes](../reviews/2026-10-05-v3-release-notes.md)
- [Research flow UI acceptance](../reviews/2026-10-11-research-flow-ui-acceptance.md)
- [Subscription, retry and Reader closeout](../reviews/2026-10-11-subscription-retry-acceptance.md)
- [Independent research and focus-response acceptance](../reviews/2026-10-07-independent-research-focus-acceptance.md)
- [Question-first Reader implementation](../reviews/2026-10-06-question-first-reader-acceptance.md)
- [a-stock-data v3.10.1 acceptance](../reviews/2026-10-07-a-stock-data-v3101-acceptance.md)
- [Proma a-stock-data v3.10.1 upgrade acceptance](../reviews/2026-10-07-proma-a-stock-data-v3101-acceptance.md): 本机固定版本升级与回滚记录，非项目安装依赖。
- [Web final acceptance — 600803](../reviews/2026-10-04-web-final-acceptance.md)
- [600803 minimum-evidence acceptance](../reviews/2026-10-05-minimum-evidence-acceptance.md)
- [Reader process first-principles review](../reviews/2026-10-06-reader-process-first-principles-review.md): 研究过程与阅读体验的只读审查快照。
- [Company report delivery validation](../reviews/2026-10-13-company-report-delivery-validation.md)
- [Luna E2E and offline synthesis diagnosis](../reviews/2026-10-13-luna-e2e-offline-diagnosis.md)
- [600418 diagnosis and Luna validation](../reviews/2026-10-12-600418-luna-validation.md)
- [600418 00:47 timeout and audit readability](../reviews/2026-10-12-audit-and-600418-timeout.md)
- [600418 latest failure — hypothesis reference mismatch](../reviews/2026-10-11-600418-latest-failure.md)
- [600418 investigation and bounded recovery](../reviews/2026-10-11-600418-research-investigation.md)
- [External engineering diagnosis verification](../reviews/2026-10-14-external-engineering-diagnosis-verification.md)
- [a-stock-data v3.10.2 selective review](../reviews/2026-10-12-a-stock-data-v3102-review.md)
- [a-stock-data v3.10.1 review](../reviews/2026-10-07-a-stock-data-v3101-review.md)
- [Proma skill review](../reviews/2026-10-07-proma-a-stock-data-v3101-review.md)
- [Low-cost evidence investigation — 600803](../reviews/2026-10-05-low-cost-evidence-investigation.md)
- [External project evidence review](../reviews/2026-10-05-external-projects-evidence-review.md)

## Designs And Plans

`docs/superpowers/specs/` 与 `docs/superpowers/plans/` — 已交付或已冻结的设计与实施计划。
它们描述当时的范围与约束；当前行为属于对应的契约与运维页面。

- [架构审查整改状态与待办（2026-10-21）](../plans/2026-10-21-review-remediation-backlog.md)：F03–F05、F07 与批次模型迁移的状态快照、依赖、待办和验收条件，含 F02 剩余边界。
- [V8 evidence reasoning proposal](../plans/2026-10-17-evidence-reasoning-architecture-v8.md): 六阶段提案；预算、接口和额外调试运行仍有待确认项。
- [DeepSeek／Tavily 双路检索设计](../superpowers/specs/2026-10-23-dual-search-research-design.md) 与 [实施计划](../superpowers/plans/2026-10-23-dual-search-research.md): 设计与计划已于 2026-10-24 完成实现和离线验收；保留冻结基线，现役行为见双路搜索合同。
- [ChatGPT upstream adaptation design](../superpowers/specs/2026-10-17-chatgpt-upstream-adaptation-design.md) and [implementation plan](../superpowers/plans/2026-10-17-chatgpt-upstream-adaptation.md): 显式推理参数与令牌刷新韧性；用户明确排除安装包发布。

- [Plain-language report design](../superpowers/specs/2026-10-15-plain-language-report-design.md) and [stage output review design](../superpowers/specs/2026-10-15-stage-output-review-design.md): 白话解读补充与可独立阅读的阶段产出。
- [ChatGPT recovery and sidebar design](../superpowers/specs/2026-10-14-chatgpt-sidebar-recovery-design.md)
- [Numeric narrative design](../superpowers/specs/2026-10-14-numeric-narrative-design.md) and [implementation record](../superpowers/plans/2026-10-14-numeric-narrative-implementation.md)
- [Unified company research design](../superpowers/specs/2026-10-11-unified-company-research-design.md) and [implementation record](../superpowers/plans/2026-10-11-unified-company-research-implementation.md)
- [Research flow and adjacent detail design](../superpowers/specs/2026-10-11-research-flow-design.md) and [execution plan](../superpowers/plans/2026-10-11-research-flow-ui.md)
- [Audit readability design](../superpowers/specs/2026-10-12-audit-readability-design.md)
- [ChatGPT subscription design](../superpowers/specs/2026-10-10-chatgpt-subscription-design.md) and [implementation record](../superpowers/plans/2026-10-11-chatgpt-subscription-implementation.md)
- [Native retry and official PDF recovery design](../superpowers/specs/2026-10-11-native-model-retry-design.md)
- [Independent research and focus-response design](../superpowers/specs/2026-10-07-independent-research-and-focus-response-design.md) and [implementation plan](../superpowers/plans/2026-10-07-independent-research-and-focus-response-implementation.md)
- [Question-first dual-column Reader design](../superpowers/specs/2026-10-06-question-first-reader-design.md) and [completed implementation plan](../superpowers/plans/2026-10-06-question-first-reader-implementation.md)
- [Web unified evidence research design](../superpowers/specs/2026-10-04-web-final-design.md) and [implementation plan](../superpowers/plans/2026-10-04-web-final-implementation.md): Web-only 迁移，人工阅读与对比质量验收仍未完成。
- [Company report delivery design](../superpowers/specs/2026-10-13-company-report-delivery-design.md) and [implementation plan](../superpowers/plans/2026-10-13-company-report-delivery.md)
- [Specialist reference isolation design](../superpowers/specs/2026-10-13-specialist-reference-isolation-design.md) and [implementation plan](../superpowers/plans/2026-10-13-specialist-reference-isolation.md)
- [Luna company research E2E repair design](../superpowers/specs/2026-10-13-luna-e2e-research-design.md): 遗留的真实合成失败记录在上面的 E2E 调查。
- [Evidence-driven research and Reader design](../superpowers/specs/2026-09-30-evidence-driven-research-and-reader-proposal.md) and [implementation plan](../superpowers/plans/2026-09-30-evidence-driven-research-implementation.md)
- [Frozen evaluation criteria](../superpowers/plans/eval-table-frozen.md) and [case inputs](../superpowers/plans/eval-cases.json): 冻结的对比协议，非已完成的评估结果。
- [Catalyst research layout prototype](../superpowers/specs/2026-09-28-catalyst-research-layout.html)

## Prototypes

`docs/superpowers/prototypes/` — 合成设计材料，不是运行结果。

- [Unified Reader prototype](../superpowers/prototypes/2026-09-30-unified-research-reader.html)
- [Sample metric generator](../superpowers/prototypes/reader_sample_metrics.py) and [sample metrics](../superpowers/prototypes/reader_sample_metrics.json)
- [Question-first Reader prototype](../superpowers/prototypes/2026-10-06-question-first-reader.html) and [B2/B3/B4 designs](../superpowers/prototypes/2026-10-06-question-first-reader-b-v2.html), [B3 preview](../superpowers/prototypes/2026-10-06-question-first-reader-b-v3.html) and [B4 Agent review](../superpowers/prototypes/2026-10-06-question-first-reader-b-v4.html)
- [Research flow previews](../superpowers/prototypes/2026-10-11-research-flow-preview.html) and [preview v2](../superpowers/prototypes/2026-10-11-research-flow-preview-v2.html)

## Legacy Archive

`docs/archive/` — 2026-09 之前的原始设计与实施记录。

- [Low-cost evidence design](../archive/designs/2026-10-05-low-cost-evidence-design.md) and [implementation](../archive/plans/2026-10-05-low-cost-evidence-implementation.md)
- [Native multi-source design](../archive/designs/2026-10-03-native-multisource-design.md), [implementation](../archive/plans/2026-10-03-native-multisource-implementation.md), [acceptance](../archive/reviews/2026-10-03-native-multisource-acceptance.md) and [live smoke record](../archive/reviews/2026-10-03-002130-live-smoke.md)
- [Official body and operating-detail design](../archive/designs/2026-10-03-disclosure-body-operating-detail-design.md), [implementation](../archive/plans/2026-10-03-disclosure-body-operating-detail-implementation.md) and [acceptance](../archive/reviews/2026-10-03-disclosure-body-operating-detail-acceptance.md)
- [Native wiring design](../archive/designs/2026-10-02-native-research-wiring-design.md), [implementation](../archive/plans/2026-10-02-native-research-wiring-implementation.md), [kernel acceptance](../archive/reviews/2026-10-02-native-research-kernel-acceptance.md) and [public wiring acceptance](../archive/reviews/2026-10-03-native-research-public-wiring-acceptance.md)
- [Bounded verification design](../archive/designs/2026-10-02-bounded-verification-design.md), [implementation](../archive/plans/2026-10-02-bounded-verification-implementation.md) and [acceptance](../archive/reviews/2026-10-02-bounded-verification-acceptance.md)
- [Research data integration acceptance](../archive/reviews/2026-10-02-research-data-integration-acceptance.md)
- [Catalyst wiring design](../archive/designs/2026-09-30-catalyst-production-wiring-design.md), [plan](../archive/plans/2026-09-30-catalyst-production-wiring-plan.md) and [acceptance](../archive/reviews/2026-09-30-catalyst-wiring-acceptance.md)
- [Catalyst redesign](../archive/designs/2026-09-28-catalyst-research-redesign.md), [task plan](../archive/plans/2026-09-29-catalyst-research-task-plan.md) and [engineering handoff](../archive/reviews/2026-09-29-engineering-handoff.md)
- [Capability probe design](../archive/designs/2026-09-29-capability-probe-matrix.md), [probe results](../archive/reviews/2026-09-29-data-capability-probe.md), [baseline manifest](../archive/reviews/2026-09-29-baseline-manifest.md), [pytest baseline](../archive/reviews/2026-09-29-baseline-pytest-failures.md) and [hidden model-call audit](../archive/reviews/2026-09-29-hidden-llm-audit.md)
- [Research foundation acceptance](../archive/reviews/2026-09-30-research-foundation-acceptance.md) and [shared record acceptance](../archive/reviews/2026-09-30-research-record-acceptance.md)
- [Data capability probe](../archive/reviews/2026-09-29-baseline-readability.md), [a-stock-data v3.10.0 branch handoff](../archive/reviews/2026-09-30-a-stock-data-v310-sync.md) and [first-principles review](../archive/reviews/2026-08-13-tradingagents-first-principles-review.md)
- [Research data integrity design](../archive/designs/2026-08-13-research-data-integrity-design.md) and [plan](../archive/plans/2026-08-13-research-data-integrity-plan.md)
- [Legacy learning-research composite](../archive/legacy/learning-research-reader-2026-08-13.md)
- [Wind A-share integration plan](../archive/plans/2026-08-12-wind-a-share-integration-plan.md)
- [Upstream v0.5 correctness batch](../archive/plans/2026-09-18-upstream-v0.5-correctness-batch.md) and [prompt/evidence batch](../archive/plans/2026-09-19-upstream-v0.5-prompt-evidence-batch.md)
- [Upstream v0.6.0 review](../archive/reviews/2026-10-04-upstream-v060-review.md)
- [DeepSeek effort audit](../archive/reviews/2026-10-04-deepseek-effort-audit.md), [task effort validation](../archive/reviews/2026-10-04-deepseek-task-effort-validation.md) and [task effort design](../archive/designs/2026-10-04-deepseek-task-effort-design.md)

- [F02 实施与离线验收（2026-10-21）](../reviews/2026-10-21-f02-implementation-validation.md)：结构化观察绑定及其语义保证边界。
