# Documentation Index

- **Status: Current** — 本文档是 `docs/` 的唯一导航入口。其它页面若要声明“当前行为”，都必须通过本文档被找到。
- **即时事实源是代码与 passing tests**：Markdown 只解释边界、ownership 和语义。当 prose 与实现不一致时，以代码和测试为准，并在同一改动中修复对应文档。
- 历史计划、设计与评审**不是“已经实现”的证据**：只有标注 `Status: Current` 的页面才能作为当前实现事实使用。

## Reading Rule

For any question about current behavior:

1. Read this index, then the relevant current-state page and the [contract index](contracts/README.md).
2. Inspect the canonical code and passing tests.
3. Treat plans/reviews/designs separately: they describe work, constraints, or historical snapshots, never deployed behavior.

## Current State

`Status: Current` — 描述当前受支持的产品与架构；行为变化时必须对照实现校验。

- [Product context](context.md): users, goals, constraints, and explicit non-goals.
- [Research Reader architecture](architecture/research-reader.md): current typed research publication and read-only projections.
- [Repository architecture](../ARCHITECTURE.md): system-wide dependency flow and module ownership.
- [Agent rules](../AGENTS.md): scoped working instructions for contributors and Coding Agents.

## Architecture

- [Research Reader architecture](architecture/research-reader.md): the current learning-research path (see Current State).
- [Repository architecture](../ARCHITECTURE.md): module ownership and dependency flow (see Current State).

## Contracts

- [Contract index](contracts/README.md): canonical Python, runtime, web, and frontend sources, plus change propagation rules.
- [Valuation assessment](contracts/valuation-assessment.md): deterministic price-position and reference-range chain behind the reader's 估值定位 card (`valuation-assessment-v1`).
- [Local price statistics](contracts/local-price-statistics.md): deterministic return-risk/ATR methods and frozen price evidence, separate from valuation.
- [Shared research record](contracts/research-record.md): evidence/hypothesis/metric contract, native three-mode workflow and bounded verification, mandatory publication, read-only Reader and compatibility limits.

Schemas are not copied into Markdown. When a field, enum, event, artifact, or endpoint changes, update the machine-owned definition and its consumers first, then update the relevant focused explanation.

## Operations

`Status: Current` — 运行时与运维边界，行为变化时对照代码校验。

- [A-share data capabilities](operations/a-share-data-capabilities.md): A-share supplemental data sources, fallback, coverage, and unavailable semantics.
- [Observability and replay](operations/observability-replay.md): replay / audit / privacy boundaries.
- [Research package interoperability](operations/research-package-interoperability.md): external Agent consumption contract over the public research-package and reader fact layer.
- [Workbench presets](operations/workbench-presets.md): YAML analyst presets and the fixed downstream graph nodes.
- [Web batch analysis](operations/web-batch-analysis.md): 1-8 company batch research, global FIFO scheduler, concurrency, lifecycle, and notification limits.
- [Catalyst trial operations](operations/catalyst-research.md): explicit entry, qualification limits, budgets, recovery and read semantics.
- [Web evidence research](operations/evidence-research.md): default `evidence_v1` for single/batch company research, catalyst and holding scopes, bounded valuation and verification, saved-content Reader and legacy recovery.
- [Model reasoning configuration](operations/llm-reasoning.md): official DeepSeek model names, task effort overrides, inheritance and frozen-run recovery.

## Integrations

`Status: Current` — 第三方数据集成当前真实支持的范围。

- [Wind AIFin Market](integrations/wind.md): currently supported Wind capabilities, config, routing, and limits. Historical planning lives in `archive/plans/`.

## Decisions

- [Architecture decisions](decisions/README.md): ADR lifecycle and future decision records. No historical ADRs are reconstructed here.

## Current Delivery Reviews

- [v3.0.0 release notes](reviews/2026-10-05-v3-release-notes.md): Web product migration, changes since v2.10.0, verification and research-quality limits.
- [Web final acceptance — 600803](reviews/2026-10-04-web-final-acceptance.md): delivered native Web default and Reader, real fresh/frozen trial outcomes, HTML preview, validation and remaining human/research-quality checks.

## Proposed Engineering Designs

These are execution proposals, not descriptions of current runtime behavior.

- [Evidence-driven research and Reader design](superpowers/specs/2026-09-30-evidence-driven-research-and-reader-proposal.md) and [implementation plan](superpowers/plans/2026-09-30-evidence-driven-research-implementation.md): retained overall goals and remaining quality/readability evaluation and default-migration conditions. Current engineering behavior belongs in the operations and contract pages above.
- [Frozen evaluation criteria](superpowers/plans/eval-table-frozen.md) and [case inputs](superpowers/plans/eval-cases.json): retained classic/catalyst comparison protocol, not completed evaluation results or authorization for new paid calls.
- [Unified Reader prototype](superpowers/prototypes/2026-09-30-unified-research-reader.html), [sample metric generator](superpowers/prototypes/reader_sample_metrics.py), [sample metrics](superpowers/prototypes/reader_sample_metrics.json), and [catalyst layout prototype](superpowers/specs/2026-09-28-catalyst-research-layout.html): retained synthetic design material, not live research or runtime contracts.

## Historical / Archive

`Status: Historical | Frozen Design | Archived Plan` — **Do not use these documents as evidence of current implementation behavior.** They are kept for traceability and migration, not as current-state contracts.

- [Legacy learning-research composite](archive/legacy/learning-research-reader-2026-08-13.md): frozen historical reference for the learning research / Reader path and its implementation records.
- [Catalyst redesign](archive/designs/2026-09-28-catalyst-research-redesign.md), [task plan](archive/plans/2026-09-29-catalyst-research-task-plan.md), and [engineering handoff](archive/reviews/2026-09-29-engineering-handoff.md): original scope, task dependencies and writing-time blockers; archiving does not certify every original goal.
- [Capability probe design](archive/designs/2026-09-29-capability-probe-matrix.md), [probe results](archive/reviews/2026-09-29-data-capability-probe.md), [baseline manifest](archive/reviews/2026-09-29-baseline-manifest.md), [pytest baseline](archive/reviews/2026-09-29-baseline-pytest-failures.md), [readability baseline](archive/reviews/2026-09-29-baseline-readability.md), and [hidden model-call audit](archive/reviews/2026-09-29-hidden-llm-audit.md): dated pre-migration measurements and source limitations.
- [Catalyst wiring design](archive/designs/2026-09-30-catalyst-production-wiring-design.md), [plan](archive/plans/2026-09-30-catalyst-production-wiring-plan.md), and [acceptance](archive/reviews/2026-09-30-catalyst-wiring-acceptance.md): implementation history; current entry and qualification semantics are in catalyst operations.
- [Research foundation acceptance](archive/reviews/2026-09-30-research-foundation-acceptance.md) and [shared record acceptance](archive/reviews/2026-09-30-research-record-acceptance.md): initial A/B and limited Reader implementation history.
- [a-stock-data v3.10.0 branch handoff](archive/reviews/2026-09-30-a-stock-data-v310-sync.md) and [research/data integration acceptance](archive/reviews/2026-10-02-research-data-integration-acceptance.md): retained branch history, local merge, compatibility fixes, validation and remaining research migration work.
- [Bounded verification design](archive/designs/2026-10-02-bounded-verification-design.md), [implementation](archive/plans/2026-10-02-bounded-verification-implementation.md) and [acceptance](archive/reviews/2026-10-02-bounded-verification-acceptance.md): C1 execution, predicate semantics, durable recovery and validation history.
- [Native wiring design](archive/designs/2026-10-02-native-research-wiring-design.md), [implementation](archive/plans/2026-10-02-native-research-wiring-implementation.md), [kernel acceptance](archive/reviews/2026-10-02-native-research-kernel-acceptance.md), and [public wiring acceptance](archive/reviews/2026-10-03-native-research-public-wiring-acceptance.md): C2 shared-kernel and public entry implementation history; current behavior is in native API operations.
- [Native multi-source design](archive/designs/2026-10-03-native-multisource-design.md), [implementation](archive/plans/2026-10-03-native-multisource-implementation.md), [acceptance](archive/reviews/2026-10-03-native-multisource-acceptance.md), and [live smoke record](archive/reviews/2026-10-03-002130-live-smoke.md): bounded source routing and dated coverage evidence, not a general research-quality result.
- [Official body and operating-detail design](archive/designs/2026-10-03-disclosure-body-operating-detail-design.md), [implementation](archive/plans/2026-10-03-disclosure-body-operating-detail-implementation.md) and [acceptance](archive/reviews/2026-10-03-disclosure-body-operating-detail-acceptance.md): bounded PDF admission, deterministic operating tables and scoped coverage labels; current behavior is in the native API operations page.
- [Research data integrity design](archive/designs/2026-08-13-research-data-integrity-design.md): frozen design, implemented.
- [Research data integrity plan](archive/plans/2026-08-13-research-data-integrity-plan.md): archived implementation plan, completed.
- [Wind A-share integration plan](archive/plans/2026-08-12-wind-a-share-integration-plan.md): archived research and implementation plan for the Wind integration.
- [Upstream v0.5 correctness batch plan](archive/plans/2026-09-18-upstream-v0.5-correctness-batch.md): archived implementation plan, completed and released in v2.10.0.
- [Upstream v0.5 prompt/evidence batch plan](archive/plans/2026-09-19-upstream-v0.5-prompt-evidence-batch.md): archived implementation plan, completed and released in v2.10.0.
- [First-principles review](archive/reviews/2026-08-13-tradingagents-first-principles-review.md): historical audit snapshot, not a current-state contract.
- [Upstream v0.6.0 review](archive/reviews/2026-10-04-upstream-v060-review.md): historical A-share selective-adoption review; later DeepSeek implementation points to the current reasoning guide.
- [DeepSeek effort audit](archive/reviews/2026-10-04-deepseek-effort-audit.md): historical call-site assessment and trial candidates before task overrides; current behavior is in the reasoning configuration guide.
- [DeepSeek task effort design](archive/designs/2026-10-04-deepseek-task-effort-design.md): archived configuration design; defaults and recovery behavior are documented in the reasoning guide.
- [Task effort validation](archive/reviews/2026-10-04-deepseek-task-effort-validation.md): offline checks, live official-API wiring, browser acceptance and same-environment failure comparison.

Every archived document carries a `Status:` field and a pointer back to this index.

## Document Conventions

- Non-current documents must start with one of: `Status: Proposed`, `Status: Historical`, `Status: Frozen Design`, `Status: Archived Plan` — and must state: **Do not use this document as evidence of current implementation behavior.** Proposed designs belong under Proposed Engineering Designs until implemented or archived.
- Current documents are marked `Status: Current`.
- Current-state pages do not carry implementation-process noise (story points, sprints, task boards, uncommitted-worktree notes, one-off test counts, or “Next / To Do” markers). Those belong in issues, PRs, project management systems, or historical plans.
