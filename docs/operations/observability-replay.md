# V9 observability and replay

Status: Current

Run stores save append-only `events.jsonl`, secret-free `run.json`, content-addressed artifacts and a durable research journal. Web uses `~/.tradingagents/web/runs/`; CLI uses `~/.tradingagents/cli/runs/`. Each launcher holds its own exclusive writer lock. Do not delete user run directories for development or recovery.

The journal freezes the V9 request/configuration and tracks reservations, dispatches and results. Resume requires intact matching V9 identity, reuses valid saved results and keeps unknown dispatched outcomes spent. A resumed run never adopts new prompts, source policy or changed model configuration. Unsupported old workflow records remain on disk but cannot execute or enter the current Reader.

Persisted diagnostics distinguish source gaps, provider/model failures, cancellation, timeout and publication failure. Provider error text and credential-bearing URLs must not become public diagnostics. Use the Web research audit and saved per-agent results to inspect qualified facts, source passages, numeric lineage and model usage. Counts describe observed events and authorized attempts, not guaranteed provider billing or semantic research quality.

A valid public report requires a frozen candidate, committed authorization barrier and matching report identity. Stage output may be readable before final publication and must remain visibly provisional. Reader/audit GETs never trigger provider calls. Web schedules an independent explanation job after completion; explicit retry remains separate from baseline execution.

Use [the current contract](../contracts/research-record.md) for evidence and publication guarantees, [CLI operations](cli-research.md) for terminal resume, and [Web operations](evidence-research.md) for interactive recovery. Historical benchmark, hypothesis and envelope tools belonged to retired workflows and are no longer maintained entrypoints.

<a id="retry-and-accounting"></a>
<a id="原生模型有限网络重试"></a>
