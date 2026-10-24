# Documentation Index

Current new-study contract: [Dual-search company research (V8)](contracts/dual-search-research.md), extending [unified company research (V7 baseline)](contracts/unified-company-research.md).

- **Status: Current** — 本文档是 `docs/` 的唯一导航入口。其它页面若要声明“当前行为”，都必须通过本文档被找到。
- **即时事实源是代码与 passing tests**：Markdown 只解释边界、ownership 和语义。当 prose 与实现不一致时，以代码和测试为准，并在同一改动中修复对应文档。
- 历史计划、设计与评审**不是“已经实现”的证据**：只有标注 `Status: Current` 的页面才能作为当前实现事实使用。

## Reading Rule

For any question about current behavior:

1. Read this index, then the relevant current-state page and the [contract index](contracts/README.md).
2. Inspect the canonical code and passing tests.
3. Treat plans/reviews/designs separately: they describe work, constraints, or historical snapshots, never deployed behavior.

For initial orientation, read the concise [Chinese README](../README.md) or
[English README](../README.en.md). Coding Agents start with [AGENTS.md](../AGENTS.md),
then the scoped guide, architecture and owning contract. Keep detailed execution
rules here in focused documents rather than duplicating them in the README.

## Current State

`Status: Current` — 描述当前受支持的产品与架构；行为变化时必须对照实现校验。

- [ChatGPT subscription configuration](operations/chatgpt-subscription.md): official OAuth, dynamic account catalogs, usage limits and local credential ownership.
- [Product context](context.md): users, goals, constraints, and explicit non-goals.
- [Research Reader architecture](architecture/research-reader.md): current typed research publication and read-only projections.
- [Repository architecture](../ARCHITECTURE.md): system-wide dependency flow and module ownership.
- [Agent rules](../AGENTS.md): scoped working instructions for contributors and Coding Agents.

## Architecture

- [Research Reader architecture](architecture/research-reader.md): native saved-record reading and legacy compatibility paths (see Current State).
- [Repository architecture](../ARCHITECTURE.md): module ownership and dependency flow (see Current State).

## Contracts

- [Contract index](contracts/README.md): canonical Python, runtime, web, and frontend sources, plus change propagation rules.
- [Plain-language report reading](contracts/report-explanation.md): indicator definitions, numeric formatting and bounded new-study model explanations beside unchanged professional research.
- [Valuation assessment](contracts/valuation-assessment.md): deterministic price-position and reference-range chain behind the reader's 估值定位 card (`valuation-assessment-v1`).
- [Local price statistics](contracts/local-price-statistics.md): deterministic return-risk/ATR methods and frozen price evidence, separate from valuation.
- [Frozen numeric narrative](contracts/numeric-narrative.md): fresh V7 host-owned numeric fragments, scoped templates, structural bindings, cache/publication replay, focus isolation and historical compatibility.
- [Structured financial checks](contracts/structured-financial-checks.md): independent statement coverage and profit/CFO comparison, exact scopes, five-check versioning and saved-history compatibility.
- [Hypothesis-directed challenge checks](contracts/hypothesis-directed-checks.md): typed verifiability, independent propositions, task outcomes, bounded isolation and frozen-denominator measurement.
- [Saved evidence benchmark](contracts/evidence-benchmark.md): read-only Phase 0 measurements, token-accounting limits and versioned manual hypothesis rubric.
- [Native input measurement](contracts/native-input-measurement.md): hash-verified stage prompt sizes, unknown usage, conservative inventories and offline reversible metadata comparison without runtime changes.
- [Shared research record](contracts/research-record.md): evidence/hypothesis/metric contract, versioned native company workflow and bounded verification, mandatory publication, read-only Reader and compatibility limits.

Schemas are not copied into Markdown. When a field, enum, event, artifact, or endpoint changes, update the machine-owned definition and its consumers first, then update the relevant focused explanation.

## Operations

`Status: Current` — 运行时与运维边界，行为变化时对照代码校验。

- [A-share data capabilities](operations/a-share-data-capabilities.md): A-share supplemental data sources, fallback, coverage, and unavailable semantics.
- [Observability and replay](operations/observability-replay.md): replay / audit / privacy boundaries.
- [Research package interoperability](operations/research-package-interoperability.md): external Agent consumption contract over the public research-package and reader fact layer.
- [Legacy analyst presets](operations/workbench-presets.md): retained CLI/inspection YAML contracts and compatibility metadata; new Web native roles are fixed.
- [Web batch analysis](operations/web-batch-analysis.md): 1-8 company batch research, global FIFO scheduler, concurrency, lifecycle, and notification limits.
- [Legacy catalyst recovery](operations/catalyst-research.md): retained qualification limits, budgets, recovery and read semantics; historical setup does not enable new creation.
- [Web evidence research](operations/evidence-research.md): default `evidence_v1` for single/batch company research, catalyst and holding scopes, bounded valuation and verification, saved-content Reader and legacy recovery.
- [Model reasoning configuration](operations/llm-reasoning.md): official DeepSeek model names, task effort overrides, inheritance and frozen-run recovery.

## Integrations

`Status: Current` — 第三方数据集成当前真实支持的范围。

- [Wind AIFin Market](integrations/wind.md): currently supported Wind capabilities, config, routing, and limits. Historical planning lives in `archive/plans/`.

## Decisions

- [Architecture decisions](decisions/README.md): ADR lifecycle and future decision records. No historical ADRs are reconstructed here.

## Archive

- [Documentation archive](archive/README.md): 历史设计、实施计划、验收与定点调查记录的完整清单。

本索引只描述当前受支持的行为。归档文档保留其写作时的事实，不因归档而获得认可，
也不得作为当前实现证据；需要追溯某个历史决策时，从归档索引进入。

## Document Conventions

- Non-current documents must start with one of: `Status: Proposed`, `Status: Historical`, `Status: Frozen Design`, `Status: Archived Plan` — and must state: **Do not use this document as evidence of current implementation behavior.** Proposed designs stay in the archive index until implemented or archived.
- Current documents are marked `Status: Current`.
- Current-state pages do not carry implementation-process noise (story points, sprints, task boards, uncommitted-worktree notes, one-off test counts, or “Next / To Do” markers). Those belong in issues, PRs, project management systems, or historical plans.
