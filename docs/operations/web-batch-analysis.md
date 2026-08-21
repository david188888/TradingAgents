# Web Batch Analysis

The localhost Web workbench supports single-company and batch company research. CLI batch creation is out of scope.

## Limits and scheduling

- A batch accepts 1-8 company inputs.
- Inputs are validated together before any child run is created. Codes and company names are accepted; names must resolve to exactly one instrument. A-share resolution is the default, while explicit exchange-qualified symbols can target other markets.
- Every company remains an independent durable run with its own SSE stream, Reader, report, audit history, and cancellation state.
- Single runs and batch children share one FIFO scheduler. The default global concurrency is 3 and can be set to 1, 2, or 3. Lowering concurrency never interrupts already-running work; it affects future scheduling.
- A batch record stores ordered child run references and aggregate counts. Deleting a terminal batch removes only the batch record and preserves child runs and reports.

## Lifecycle

Queued children survive browser reloads and remain recoverable after a service restart. A child that was already running when the service stopped follows the existing `interrupted` recovery contract; queued children remain queued and are scheduled after startup recovery.

Failures are isolated and are not automatically retried. Cancelling a batch cancels active children cooperatively and marks queued children cancelled. Cancelling one child does not affect other children.

## Notifications

Completion notifications use the browser Notification API and therefore appear in macOS Notification Center when the browser remains available. The preference is enabled by default and permission is requested on the first explicit analysis start. A denied permission does not block analysis and suppresses notifications.

- Single runs notify once on completion or failure, but not on user cancellation.
- Batches notify once after every child reaches a terminal state and include completed, failed, and cancelled counts.
- Notification clicks focus the workbench; run-level clicks select the child run, while batch-level clicks return to the batch status surface.
