# ASR recovery reconciliation, November 16

Baseline: origin/dev 8d98a0b, not published v0.5.0/main 39ecd3e. Current dev
already includes #88 diagnostics, recovery and browser state separation.
No additional frontend changes are required by this patch. Do not add a second
diagnostics sink or recovery state machine.

## Frontend interface

Existing asr_state carries capture.active separately from asr.state/reason.
Microphone failures use microphone_error. Provider interruption is not browser
WebSocket loss; browser connection notices remain independent.
provider_temporarily_unavailable carries retrying/exhausted/permanent outcome,
retry ceiling and recovery-cycle downtime. reconnect_attempt carries progress;
recovered supplies attempts/downtime; reconnect_cancelled clears the notice.
Silence and pending segmentation do not initiate an outage.

Correlation stays in app.asr_diagnostics JSON logs: opaque run ID, application
attempt number, UTC timestamp, fixed reason/category, bounded protocol codes and
monotonic recovery duration. Browser messages must not equate caption gaps with
downtime or assert unknown provider causes. Existing bounded retries,
one-failure-per-attempt suppression, fragment preservation, ordering, stale
callback rejection and cancellation remain unchanged.

This patch removes dynamic exception-class reflection from deferred connection
cleanup logging. A custom exception class name may itself contain sensitive
content. No exception messages, audio, transcripts, provider bodies or device
identifiers are added to logs, exports or journals.

## Validation

Executed locally: python3 tests/test_asr_recovery_contract.py (2 passing);
Python compileall for changed Python files; git diff --check. The stdlib runner
extracts actual diagnostic definitions by AST without initializing provider,
device or application modules. It supplements, not replaces, integration tests.

Parent CI commands:

    uv run pytest -q tests/test_asr_recovery_contract.py tests/unit/test_asr_diagnostics.py tests/unit/test_reconnect.py tests/unit/test_asr_readiness.py tests/unit/test_asr_transport.py tests/unit/test_asr_ack_final.py
    uv run pytest -q browser_tests/test_asr_readiness.py
    uv run ruff check app/transcribe.py tests/test_asr_recovery_contract.py

Existing dev tests cover transient/repeated failures, exhaustion, silence,
preserved ordering, stale callbacks and cleanup. Those were inspected but not run
here: this isolated host lacks pytest, Pydantic and the SDK. No dependencies were
installed. Real provider/device behavior and historical cause remain unproved.
