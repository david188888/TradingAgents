# Product Context

- **Status: Current**（current-state 文档；行为变化时对照代码与测试校验）

TradingAgents is a local-first, LangGraph-based multi-agent financial research
framework. This fork prioritizes China A-share research with a maintained A-share Web product and retained compatibility code for older instruments. It is a research tool,
not an execution or account-management product.

## Users

- Individual researchers and engineers running the local Web workbench.
- Developers extending data providers, graph roles, evidence contracts, and
  local observability.
- Readers reviewing a company-research or holding-review artifact with its
  reported evidence, uncertainty, and data-source degradation.

## Goals

- Combine market, social, news, and fundamentals lenses in an auditable
  research workflow.
- Make evidence provenance, coverage limitations, and persisted artifacts
  available to local readers rather than hiding provider failures.
- Support Web company, catalyst and holding research, plus batch company research.
  Holding review requires explicit user-provided facts.
- Keep domain execution independent of the Web adapter and retained compatibility consumers.

## Entry Surfaces

`tradingagents web --port 8765 --open` starts the maintained local workbench.
New single and batch runs use `evidence_v1`; old profiles are read/resume only.
CLI analysis is outside continued maintenance. The FastAPI/SSE adapter serves
its bundled frontend on loopback only. The native kernel freezes evidence,
creates isolated hypotheses, challenges and bounded conditions, then synthesizes
one saved research record consumed by both Reader and Markdown.

## Non-Goals

The project does not provide brokerage connectivity, account management,
custody, order generation, order routing, trade execution, target-position
recommendations, or investment advice. A research artifact or model output is
not a trading instruction.

## Core Concepts

- **Analysis request:** typed ticker, date, analyst selection, horizon, and
  research mode passed into the shared execution boundary.
- **Evidence and capability result:** provider output with source and
  availability semantics. Missing, degraded, and unavailable sources are not
  evidence that an event did not occur.
- **Research case:** a public, evidence-bound artifact assembled from a
  validated research draft; partial and fail-stop outputs are explicit.
- **Reader and audit projection:** read-only Web views of persisted artifacts
  and events, including compatibility/degradation states for incomplete or
  older runs.
- **Checkpoint:** local durable LangGraph state used for resumable runs when
  configured and compatible with the current runtime.

## A-Share-First Constraints

A-share instruments require exchange-aware symbol normalization, local-market
data source routing, and careful distinction between official disclosures,
public fallbacks, and unavailable coverage. Market sessions, disclosures, and
timestamps must be interpreted with the relevant market and declared time
semantics rather than the machine's locale. See
[operations/a-share-data-capabilities.md](operations/a-share-data-capabilities.md) for focused
provider behavior.

## Evidence And Time Boundaries

Research should distinguish observed facts from inference, preserve source
identity where an artifact exposes a claim, and report unavailable or partial
coverage honestly. Analysis is evaluated relative to its requested analysis
date and the runtime's resolved cutoff; later data must not silently appear as
point-in-time evidence. Persisted artifacts and projections should remain
read-only representations of what a run captured, not live provider refreshes.

## Product Stage

The workbench is a local, loopback-only application that persists its run
history under the user's home directory. Its purpose is research, inspection,
and iterative development of the framework, not a hosted multi-tenant service
or a financial-account portal.
