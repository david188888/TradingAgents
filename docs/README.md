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

Schemas are not copied into Markdown. When a field, enum, event, artifact, or endpoint changes, update the machine-owned definition and its consumers first, then update the relevant focused explanation.

## Operations

`Status: Current` — 运行时与运维边界，行为变化时对照代码校验。

- [A-share data capabilities](operations/a-share-data-capabilities.md): A-share supplemental data sources, fallback, coverage, and unavailable semantics.
- [Observability and replay](operations/observability-replay.md): replay / audit / privacy boundaries.
- [Research package interoperability](operations/research-package-interoperability.md): external Agent consumption contract over the public research-package and reader fact layer.
- [Workbench presets](operations/workbench-presets.md): YAML analyst presets and the fixed downstream graph nodes.

## Integrations

`Status: Current` — 第三方数据集成当前真实支持的范围。

- [Wind AIFin Market](integrations/wind.md): currently supported Wind capabilities, config, routing, and limits. Historical planning lives in `archive/plans/`.

## Decisions

- [Architecture decisions](decisions/README.md): ADR lifecycle and future decision records. No historical ADRs are reconstructed here.

## Historical / Archive

`Status: Historical | Frozen Design | Archived Plan` — **Do not use these documents as evidence of current implementation behavior.** They are kept for traceability and migration, not as current-state contracts.

- [Legacy learning-research composite](archive/legacy/learning-research-reader-2026-08-13.md): frozen historical reference for the learning research / Reader path and its implementation records.
- [Research data integrity design](archive/designs/2026-08-13-research-data-integrity-design.md): frozen design, implemented.
- [Research data integrity plan](archive/plans/2026-08-13-research-data-integrity-plan.md): archived implementation plan, completed.
- [Wind A-share integration plan](archive/plans/2026-08-12-wind-a-share-integration-plan.md): archived research and implementation plan for the Wind integration.
- [First-principles review](archive/reviews/2026-08-13-tradingagents-first-principles-review.md): historical audit snapshot, not a current-state contract.

Every archived document carries a `Status:` field and a pointer back to this index.

## Document Conventions

- Non-current documents must start with one of: `Status: Historical`, `Status: Frozen Design`, `Status: Archived Plan` — and must state: **Do not use this document as evidence of current implementation behavior.**
- Current documents are marked `Status: Current`.
- Current-state pages do not carry implementation-process noise (story points, sprints, task boards, uncommitted-worktree notes, one-off test counts, or “Next / To Do” markers). Those belong in issues, PRs, project management systems, or historical plans.
