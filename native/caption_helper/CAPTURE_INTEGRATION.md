# Physical capture source and PCM integration (disabled by default)

This is source availability, **not native/physical admission or acceptance**.
NoAudioController/NoAudioHelper/GuardianA/GuardianB and their qualification entrypoint
remain unchanged. The opt-in CaptureController/CaptureHelper are separately signed
images with microphone-only helper entitlement; no network or audio-output route.

## Discard and PCM modes

The older explicit `--capture-budget` path retains discard-only input. Its
budget reply is CBCA0002; --capture-noinput-budget is CBNC0002 and calls no opener
or closer. The separate --capture-pcm-budget uses **CBPC0002**, private inherited
PCM/soft-stop pipes, and a nonzero 128-bit epoch. Cross-domain replies cannot debit
or arm another mode. No PCM goes through JSON stdout/stderr, files, sockets, the
ledger, metrics, or qualification artifacts. Role process/image identity and
parent lifelines remain the existing suspended-image native boundary.

CaptureHelper explicitly selects the granted HAL AudioDeviceID, never a PortAudio
index or the default device. It reads the native input format, rejects unsupported
formats/rates/channel counts, and sets only its AudioUnit client output format to
interleaved little-endian signed PCM16 at the existing native rate (mono/stereo).
It does not change hardware/default routes or nominal rates. Scratch and callback
frame limits remain fixed. Client format negotiation failures close without any
sounddevice/default-device or guessed-format fallback.

## PCM wire and bounded backpressure

One producer, one inherited nonblocking FIFO, one process-owned reader. Every write
is one atomic packet <=496 bytes, below the POSIX minimum PIPE_BUF of 512; descriptor
mode/type/atomic capacity are checked in both controller and capture role. A packet
is a 48-byte network-order header followed by at most 448 PCM bytes:

- 8 bytes: CBPCM001; 16 bytes: exact granted epoch;
- u64 sequence (starting at zero, no gaps/replays);
- u32 native sample rate (8000..192000), u16 channels (1 or 2), u16 flags;
- u32 frame count and u32 payload byte count (frames * channels * 2).

Flags zero means nonempty PCM. Flag 1 is an empty END packet, emitted only after
checked local stop/uninitialize/dispose and callback quiescence; it does NOT release
HOLD or independently prove physical closure. Pipe EOF without END, bytes after
END, changed format/epoch/sequence, oversized data or duration excess fail closed.
The decoder enforces frames <= native_rate * granted_ms / 1000.

The callback never waits/retries/drops audio on pipe pressure: EAGAIN, EINTR, short
writes and broken pipe fault capture and cause checked close. Python reads at most
four packets per loop callback, not unlimited call_soon_threadsafe handles. Its
ASR coalescer has <3200 pending bytes plus one converted packet (<896 bytes), and
its application queue is <=50 * 3200 bytes. Queue pressure is terminal emergency
stop, never silent loss/continued capture. Stop drops queued/pending references.
No secure-erasure claim is made for immutable Python/provider buffers.

## ASR and lifecycle integration

app/native_pcm.py validates framing and maintains per-epoch stereo downmix and
stateful conversion to exactly **16000 Hz, mono PCM16LE**, matching the existing ASR
request contract. Native-rate conversion does not mutate a device setting. Python
3.11/3.12 audioop is used only where conversion is necessary; unavailable conversion
(including 3.13 without audioop) fails closed. No install, guessed-rate passthrough,
or stateless per-packet resampling fallback exists. 100 ms ASR blocks preserve the
existing application chunk contract; a final partial block is drained once.

app/native_capture.py owns the reader, fixed queue and single stream consumer. A
one-use NativeCaptureFactory is bound to session ID, pipeline generation, epoch,
sample rate, programme, ledger tail, exact base runtime-grant digest (including HAL
device/duration/runtime proof), candidate, image pins, exact consumer, reviewed
provider-authorization reference (for app-asr), and narrowed grant expiry. It never
requests permission, opens output, starts a provider directly or renews a grant.
The independent coordinator keeps Custody/Journal and EmergencyStop ownership.

The optional app.main.configure_native_capture(factory) hook is idle-only. No
startup, config, UI flag, environment setting or persisted state calls it. Missing
proof/permit remains visibly fail-closed, with no legacy fallback. Native selection
installs an opaque granted-HAL catalog so browser Start preflight cannot query or
misinterpret a PortAudio integer. Existing Start readiness/language/profile checks
still run. The unchanged default remains the legacy route, not an implicit native
activation. Native Start requires muted TTS; unmute invalidates subsequent native
callbacks. Provider connection waits for this epoch's valid PCM in the owned
transcription task, not the websocket Start handler, so Stop is not blocked by a
native launch handshake. Existing ingress/ASR diagnostics callbacks are preserved.

Soft finish closes a distinct parent writer; the native input role cooperatively
stops/disposes, writes END, exits, and is reaped by its controller. Python drains
only bounded queued/pipe tail and requires clean EOF plus clean owned controller
terminal. Emergency Stop/generation replacement/overflow abort and discard instead.
Python owns/awaits its launcher worker; native code owns/reaps exact role children.
Every reservation is journal-fsynced before native budget delivery; all outcomes,
including successful transport END/terminal, retain debit and **HOLD**. No stop,
reconnect, reset, queue clear, process exit or adapter result releases the journal.
A consumed factory cannot reopen on reconnect or a second Start.

## Independent authority and remaining exact gates

scripts/attended_pcm_admission.py ADDS an authenticated PCM review and runtime grant
to the existing CaptureAdmission; discard-only authority cannot authorize audio
egress. Trusted digest pins must come from the independent owner/reviewer, never
from source, browser assertions, generated fixtures or the candidate itself. New
physical proof categories are framing/epoch, backpressure-close, stop/drain,
no-retention and consumer-boundary. PCM review pins the base exact-image review;
app-asr also pins a separately authorized provider reference. It does not mint a
provider budget or waive spending/privacy/output admission.

**Unavailable here:** an actual macOS build/signature/entitlement receipt for these
exact changed images; independent native/framing/backpressure/fault/physical
closure evidence; authenticated PCM review/proofs and exact programme/session
runtime grant; and an independently established consumer egress/privacy boundary.
The base runtime's kernel-egress-denied condition cannot simply be claimed to
permit an application ASR upload: its scope must be independently reconciled with
any separately authorized provider consumer, preserving helper network denial.
Offline synthetic tests prove software contracts only, not these facts.

The shared websocket output guard is now integrated: while native capture is
selected, unmuted Start/new-session, unmute, replay, audio unlock and catch-up
controls fail closed. Muted-before-Start and per-packet invalidation remain
defense-in-depth. These reviewed source boundaries are NOT independent runtime
consumer/egress or acoustic proof. All ordinary PCM transport/factory/lifecycle
source is implemented above; the remaining independent facts are not renamed
'human transport' work or treated as Phase-A/real full-cycle acceptance.

Rollback: do not install the optional factory; existing default/noaudio routes stay
unchanged. Remove an installed factory only while idle; live instances must Stop
and join owned cleanup first. Do not clear a debit/HOLD to retry.


## Safety follow-up: expiry, independent termination and supported startup

Capture budget v2 is exactly 72 bytes: the prior magic/challenge/duration/sequence
prefix plus an absolute continuous validity tick and authenticated Unix-ns expiry.
The native challenge publishes its fixed continuous anchor and timebase. Parent
admission first pins expiry to a sleep-inclusive local clock (mach_continuous_time
on macOS; CLOCK_BOOTTIME in Linux software tests). PCM permits also narrow that
bound. Mapping samples wall and continuous time AFTER the native anchor, rounds
down, and fixes the
validity tick BEFORE durable reservation. Native takes the minimum of the original
anchor-plus-debit deadline and this validity tick, and enforces Unix expiry too.
Immediate post-fsync revalidation rejects expired authority before delivery while
preserving debit/HOLD. Neither scheduling pauses, clock rollback, Stop nor drain
refreshes a full duration. Forward wall expiry is checked independently by both
native guardians and before helper open/render/start. Old capture v1 replies fail
closed; noaudio CBNA0001 remains the existing 56-byte protocol.

Only 1000..2000 ms capture/noinput qualification budgets are supported. Smaller
budgets are rejected before permit consumption or debit; native startup rejects
already-insufficient remaining time before any child can open HAL. Slow startup
still fails closed and retains any debit; source does not promise successful
startup under an arbitrarily delayed scheduler.

CaptureGuardianA and CaptureGuardianB are NEW separate signed images, not replacements
for the noaudio GuardianA/B. Both live guardians enforce continuous/wall deadlines,
emergency pipe and controller death by SIGKILL of their OWN isolated capture group.
This includes a SIGSTOP'ed helper even when CaptureController is dead or SIGSTOP'ed.
A is group leader; B and CaptureHelper join that exact group while suspended,
before pin verification/continuation. Controller remains OUTSIDE the group.

Controller retains its direct group-leader child unreaped (WNOWAIT observations),
including failed spawn/ready setup; group termination ALWAYS precedes leader reap.
ECHILD never permits a numeric group signal. Individual fallback signals are only
to retained unreaped direct children. Guardians do not kill borrowed reported PIDs:
the executing guardian's own group membership pins the identity it terminates.
SIGCHLD handling is reset for capture custody so auto-reap cannot invalidate it.

Separate private helper-to-guardian close pipes carry a fixed local-close token
only after checked close/disposal and PCM END/descriptor cleanup. Token+EOF allows
normal guardian exits and soft-finish/drain; missing/malformed/late token forces
termination. The token is NOT an independent physical proof or HOLD release.
No-input still calls neither HAL opener nor HAL closer and uses no real programme.

Regression evidence includes frozen-source fsync-expiry delivery and 500-ms policy
reproductions, and an isolated Linux POSIX process-group/subreaper mechanism model:
cooperative-only guardians reproduce the suspended-helper gap; forced-group models
close it with controller dead/stopped, emergency/deadline, either guardian stopped,
or both guardians stopped with live retained-parent enforcement. Every synthetic
process is owned and reaped. These are offline source/mechanism tests, NOT a macOS
build, native ABI result, HAL fault injection, or physical/kernel acceptance.
Exact new signed-image review and independent combined-fault proofs remain required.

## Failure-only no-input diagnostics

The no-input qualification CLI emits one bounded content-free FAIL/HOLD JSON
receipt on failure, rather than an exception traceback. It records the fixed
failure stage/class, observed controller return code, startup validity, a strictly
shape-validated native terminal (or null), PID agreement and actual parent cleanup
observations. Unknown statuses (-1), cleanup kills and failed native exits remain
failure observations, never closure acceptance. Malformed/unexpected terminal
fields are omitted entirely, not printed with repr or raw stdout/stderr. No raw
error text, paths, environment, argv, device data, PCM or transcripts are emitted.

The existing strict success validator and successful output schema are unchanged.
A syntactically valid diagnostic terminal is not a successful terminal, independent
closure evidence, physical qualification or permission to clear the journal HOLD.
The hosted no-input rejection that motivated these diagnostics did not preserve
its rejected terminal; its exact cause must not be inferred from the traceback.
The next actual hosted run must supply the bounded observation before a native
lifecycle repair can be justified. No guardian/deadline/closure guard is waived.
