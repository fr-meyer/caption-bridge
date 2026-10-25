# ASR interruption diagnostics

Issue #88 reported a gap between finalized captions and two pairs of uncorrelated
error lines in a prior session. Silence or segmentation delay can also produce
caption gaps. This change improves observation and recovery state; it does not
identify the cause or duration of that historical incident or claim a provider
reliability fix from offline tests.

The ASR pipeline owner emits one `stream_failure` JSON record per run/attempt.
`transcribe` delegates logging to its error callback; a standalone invocation
without a callback emits its own record. The logger never formats exception text,
exception class names, provider bodies or provider request identifiers.

Every record has schema version 1, UTC event timestamp, fixed event/reason/category,
an application-generated opaque run ID, numeric attempt ID/number, monotonic
elapsed downtime, and optional bounded WebSocket/HTTP codes. Cause-chain inspection
is bounded and copies only classified protocol values. Unknown values remain
unknown; no outage cause is inferred from a generic SDK wrapper. Correlation IDs
live only in diagnostics, not captions, exports, recovery journals or device state.
Only the latest failed attempt is retained for deduplication; there is no growing
in-memory event history.

Events distinguish stream connection/readiness/failure, reconnect start, each
attempt/result, and recovered/exhausted/permanent/cancelled outcomes. Initial
startup failure remains separate from reconnect after a verified stream. Downtime
starts when the interruption is admitted for reconnect and ends at the existing
recovery decision, including its health check; it is not the time between captions
or an acoustic measurement. Outage/recovery records use WARNING so normal CLI
logging retains the complete correlation even when application INFO logs are
disabled. Routine connecting/ready observations use INFO.

The existing browser protocol shows automatic reconnect and then verification
after a new verified handshake. It preserves captions, reports current microphone
activity separately, and offers manual restart after retry exhaustion. Browser
socket loss retains its distinct connection notice. No watchdog based on silence
or final-caption cadence is introduced. Model selection, provider requests,
reconnect ceilings, manual session lifetime and export schemas are unchanged.

Provider-free checks use existing in-memory SDK/socket and pipeline seams. They
cover correlated retries and exhaustion, wrapped close/status classification,
duplicate suppression, stale callback rejection, preserved caption order and
cleanup, plus silence/pending-fragment cases. The UI check uses synthetic socket
events with capture and AudioContext construction denied. No microphone, audio
playback, permission change or provider request is needed. A Mac execution of
these cases is not a native Windows/Linux or hardware qualification. The user's
physical listening/device checks are post-release and nonblocking.
