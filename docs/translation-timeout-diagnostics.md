# Translation deadlines and first-failure diagnostics

## Deadline policy

The product retains its bounded defaults: ordinary requests 10 seconds, Large
requests 20 seconds, GLM-family requests 20 seconds, and Stop/drain 30 seconds.
The existing environment settings are `TRANSLATION_TIMEOUT_MS`,
`TRANSLATION_LARGE_TIMEOUT_MS`, `TRANSLATION_GLM_TIMEOUT_MS`, and
`TRANSLATION_DRAIN_TIMEOUT_MS`. Request settings remain bounded to 100–120,000ms;
drain remains bounded to 1,000–300,000ms. No family, model, default, retry count,
output limit, concurrency limit or SDK transport setting is changed here.

A longer attended-run override is not sufficient evidence for a universal
latency/default increase: changing request, drain and SDK settings together does
not isolate which change was necessary. Successful aggregate outcomes do not
prove zero failures, continuous endurance, or acceptable human-perceived delay.
Qualify any proposed new deadline on the exact candidate and selected model,
including failures and actual latency, before choosing a new default.

Application startup logs the effective request/drain policy and warns when drain
is shorter than a configured request deadline. This is a warning, not an
automatic extension or refusal: a deliberately shorter Stop deadline is valid.
The Mistral SDK transport timeout is separate and is not asserted to equal the
application timeout. This patch does not adopt any attended harness transport
setting or disable/replace that harness’s independent spending safeguards.

Each application request timeout starts after admission to the provider semaphore.
Retries, retry backoff, semaphore waiting and the separate bounded quality repair
can add to end-to-end elapsed time. Drain is a separate shared deadline for all
currently in-flight work, followed by the existing bounded two-second cancellation
join. These are not total caption-latency targets. Existing elapsed-time and
latency accounting are unchanged; a recovered retry is not reported as a clean
first-attempt success by the diagnostic counter.

## Content-free diagnostics

`TranslationDispatcher.diagnostics_snapshot()` exposes only effective budgets,
in-flight count, an opaque per-session diagnostic run ID, failure/cancellation
counters and the first observed failure. It is runtime observation, not a change
to the WebSocket, journal, export or reliability persistence schema.

Structured WARNING logs include the current failure and immutable first failure:
segment sequence, allowlisted stage/reason/error category, bounded HTTP status
and the applicable request budget. Repair failures report the actual repair
budget rather than the model’s ordinary request budget. Stages distinguish
admission, request, retry, repair, drain and internal task failure. There is no
caption text, provider body/message, arbitrary exception class name, credential,
account identifier, session identifier or local path in the structured record.
A status is retained only if it is an integer from 100 through 599 (not a bool).

The first observed failure can be a recovered error; final segment outcome is
still authoritative for completion. A later retry timeout, output limit or Stop
does not overwrite that cause. Normal cancellation is counted separately and
never invents a first failure. A replaced session gets a fresh diagnostic run;
stale callbacks cannot contaminate it. Counts are observations, not billable
request counts or a spending ledger.

When drain expires, its cause is recorded before cancellation. Tasks resisting
cancellation remain owned in the in-flight set until their actual done callback;
a bounded cancellation join is not falsely represented as completed cleanup.
No synthetic completion is emitted for those tasks.

## Validation boundaries

`tests/test_translation_diagnostics.py` uses real configuration and diagnostic
classes with the exact dispatcher AST and narrow injected synthetic seams. It
checks privacy/allowlists, first-cause retention, stale sessions, deadline
selection, recovered retries, output limits, repair and task custody. It does
not validate the SDK or ASGI dependency graph.

`tests/unit/test_translation_diagnostics_integration.py` uses normal application
imports and an explicitly injected synthetic provider. Run it in the project’s
locked test environment alongside the existing translation and WebSocket suites.
Neither suite constitutes provider, hardware, acoustic or human acceptance.
