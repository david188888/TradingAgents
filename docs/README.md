# Documentation Index

This directory holds focused references. Keep current behavior in code and configuration; use this index to find the prose that explains ownership, boundaries, and operational context.

## Current State

These pages describe the supported product and architecture. They must be checked against the implementation when behavior changes.

- [Product context](context.md): users, goals, constraints, and explicit non-goals.
- [Research Reader architecture](architecture/research-reader.md): current typed research publication and read-only projections.
- [Repository architecture](../ARCHITECTURE.md): system-wide dependency flow and module ownership.
- [Agent rules](../AGENTS.md): scoped working instructions for contributors and Coding Agents.

## Contracts

- [Contract index](contracts/README.md): canonical Python, runtime, web, and frontend sources, plus change propagation rules.
- [Legacy composite](learning-research-reader.md): a compatibility and migration reference. Its body contains historical and mixed-status material and is not the ownership source for new work.

Schemas are not copied into Markdown. When a field, enum, event, artifact, or endpoint changes, update the machine-owned definition and its consumers first, then update the relevant focused explanation.

## Operational References

- [A-share data capabilities](a-share-data-capabilities.md)
- [Observability and replay](observability-replay.md)
- [Workbench presets](workbench-presets.md)
- [Wind A-share integration plan](wind-a-share-data-integration-plan.md): active integration planning; inspect its current branch status before treating it as an operational contract.

## Plans And Design

The tracked plan/design references are:

- [Research data integrity design](superpowers/specs/2026-08-13-research-data-integrity-design.md)
- [Research data integrity implementation plan](superpowers/plans/2026-08-13-research-data-integrity-plan.md)

Plans and approved designs describe work, constraints, or intended changes. They are not evidence that the described behavior is deployed. The local `docs/plans/` directory is intentionally not linked here because it is not present in a clean tracked checkout; it remains outside the current documentation truth map.

## Reviews And Decisions

- [First-principles review](reviews/2026-08-13-tradingagents-first-principles-review.md): historical review evidence, not a current-state contract.
- [Architecture decisions](decisions/README.md): ADR lifecycle and future decision records. No historical ADRs are invented here.

## Reading Rule

For a change, read the current-state page and contract index first, inspect the canonical code, then classify any plan or review evidence separately. When the prose and implementation disagree, the implementation and its passing tests are the immediate fact source; fix the affected documentation in the same change when practical.
