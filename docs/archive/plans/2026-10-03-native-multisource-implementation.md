# Unified native source routing implementation

Status: Archived Plan

Do not use this document as evidence of current implementation behavior.

归档日期：2026-10-04。正文保留编写时的设计、结果和未完成事项；归档不表示全部目标已验收。当前行为与仍待推进的计划见[文档索引](../../README.md)。

Approved scope: [source admission design](../designs/2026-10-03-native-multisource-design.md).

1. Probe public identity, statement metadata, dated factors and official calendar
   with 002130; keep responses outside the checkout. Establish exact normalized
   units and dates before implementing admission.
2. Add pure source qualifiers and a finite source-family registry. Add a native
   collector using distinct durable capability keys and BudgetedSession.
   Retain qualified tables independently and preserve each provider's family.
3. Route new native runs through the collector; version the workflow and retain
   original v1 recovery. Preserve typed safe errors across cached replay.
4. Exercise primary/fallback selection, exact code/date/unit rejection,
   calendar/factor gaps, cancellation/budget propagation and old/new recovery.
   Exercise the new families through all three native modes and C1.
5. Run one current-cutoff 002130 native trial after source qualification. Verify
   saved Reader/API output and navigation with browser-harness and Jev. Record
   real coverage, limitations and exact model dispatches.
6. Synchronize operational/architecture docs and run scoped tests, Ruff, agent
   docs and diff checks. No remote publication or profile-default migration.
