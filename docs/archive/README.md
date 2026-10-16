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

`docs/reviews/` — 交付验收、发布说明与定点调查记录。

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
