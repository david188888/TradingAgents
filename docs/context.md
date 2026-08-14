# Product Context

TradingAgents is a local-first, LangGraph-based multi-agent financial research
framework. This fork prioritizes China A-share research while retaining support
for other instruments through its configured providers. It is a research tool,
not an execution or account-management product.

## Users

- Individual researchers and engineers running local CLI or workbench analysis.
- Developers extending data providers, graph roles, evidence contracts, and
  local observability.
- Readers reviewing a company-research or holding-review artifact with its
  reported evidence, uncertainty, and data-source degradation.

## Goals

- Combine market, social, news, and fundamentals lenses in an auditable
  research workflow.
- Make evidence provenance, coverage limitations, and persisted artifacts
  available to local readers rather than hiding provider failures.
- Support company research through the local CLI and workbench, and
  learning-oriented holding review through an explicit Web/API holding context.
- Keep shared execution independent of its CLI and Web consumers.

## Entry Surfaces

`tradingagents` and `tradingagents analyze` currently construct a
`company_research` request. A `holding_review` requires an explicit holding
context and is created through the Web/API request boundary; the CLI does not
collect that context. The local workbench is a FastAPI/SSE adapter that serves
its bundled frontend on loopback only.

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
[a-share-data-capabilities.md](a-share-data-capabilities.md) for focused
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
