# Native sandbox qualification helper

Qualification-only macOS APPL bundle with no capture implementation, microphone entitlement,
provider client, playback or admission switch. Every unknown invocation including --capture exits 64.
Build using existing tools: sh scripts/build_caption_helper.sh /absolute/new/output
Ad-hoc signing is local development evidence, not Developer ID distribution/notarization.

Supported mechanism: Apple's App Sandbox entitlement in a signed APPL bundle, not custom SBPL.
Official references consulted 2026-11-17:
- https://developer.apple.com/documentation/security/app-sandbox
- https://developer.apple.com/documentation/xcode/embedding-a-helper-tool-in-a-sandboxed-app
- https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.app-sandbox

This executable is the sandboxed app itself, not a helper inheriting an unsandboxed parent's sandbox.
No com.apple.security.inherit entitlement is used.

## Qualification API v1

--probe-loopback PORT: 127.0.0.1 only, JSON result/errno, exit 0 only for EPERM/EACCES.
Host first proves an owned listener accepts its control connection, then checks sandbox connection
was not accepted. No external network probe.

--probe-file PATH: O_RDONLY|O_NOFOLLOW open only, never reads content. Only use owned harmless
scratch canary outside app container. Exit 0 only for EPERM/EACCES.

--probe-lifecycle SECONDS: 1..5 second alarm. FD0 controller, FD1 guardian A, FD2 guardian B
must be independent pipe read ends. Any EOF/data/error exits 71; alarm exits 72.
No stdout/stderr output in this mode. Caller must close duplicate endpoints and reap children.

Budget lane contract: qualification facts only, never admission. Bind host/node, image SHA256,
source SHA256, extracted signed entitlements and CodeDirectory hash, probe arguments, actual
return/errno/timing, PID-reap checks, and listener closure. Naked booleans or receipt hashes
are not capture readiness. There is no spending interface.

## Residual gates

App Sandbox supplies standard OS/container allowances, not an exact per-file allowlist.
One denied canary does not prove all filesystem paths denied. EOF tests establish closure
mechanics, not death of independently identified controllers/guardians with descriptor custody.
Alarm is a process timer, not an external monotonic absolute-deadline guardian or suspend proof.
Production capture/audio closure, trusted guardians, fixed-role image/receipt trust, independent
review and later human readiness/capture authority remain unimplemented gates. Existing attended
preflight is deliberately untouched. No receipt from this helper grants launch authority.

## Followup supervision proof (no audio)

Build identity inspector separately with existing tools:
clang -Wall -Wextra -Werror native/caption_helper/identity.c -framework Security -framework CoreFoundation -o identity
Run the two native/ qualification Python scripts from a NEW directory holding build/ and identity.

--probe-supervised ABSOLUTE_TICKS uses mach_continuous_time (includes system sleep), checks
before each 10ms poll, and exits 72 once deadline is reached. A SIGSTOPed helper cannot run;
on resume it checks the already-expired deadline before other work. This is not a guarantee
of physical resource closure while OS-suspended, nor a real-time scheduling bound.

Parent-side Security.framework checks live SecCode by direct owned child PID, strict signature
validity, actual executable URL and CodeDirectory unique hash. sysctl KERN_PROC_PID records birth
and parent PID before/after interrogation. Direct child stays unreaped, preventing PID reuse.
These observations are not an atomic exec lock or an audit-token attestation. No inherited
socketpair peer identity is used. Role guardians currently remain forked bounded harness children,
not independently signed role executables: guardian code identity remains a real gate.

Descriptor custody: all three pipe pairs start noninheritable; each forked guardian closes all
readers and every writer except its single assigned role. Spawn closes all descriptors except
mapped read ends 0/1/2. Parent closes guardian writer copies immediately. Controller-death test
uses a dedicated sole writer process while the outer harness retains child reap ownership.
It tests controller-role death, not death of helper's direct spawning parent. No lifeline writer
is inherited by the helper. Guardian death A/B, controller-role death, deadline and suspended
helper deadline were exercised successfully. The five-case matrix and controller-death harness
are qualification tools, not a production controller or trusted launcher.

Remaining: independently signed guardian roles, authenticated parent-death monitor, atomic
postspawn exec/event binding, exact role birth/image pins and trustworthy receipt consumption.
Current identity inspector emits observed code hash/path comparison; it does NOT authorize any
operation and the Python harness must compare expected CodeDirectory hash. Existing native
admission remains false. No audio code, microphone entitlement or capture path has been added.

## Fixed native assembly, source-only revision

Build now emits distinct signed GuardianA, GuardianB, SyntheticHelper and NoAudioController
images inside APPL packaging. Controller accepts only --noaudio and an image directory.
Each child starts POSIX_SPAWN_START_SUSPENDED with CLOEXEC_DEFAULT; Security.framework compares
strictly validated disk/live CDHash and identifier before SIGCONT. Capability struct travels
through a private inherited pipe, not argv or files. FD sources are duplicated above destination
range before spawn to avoid dup2 aliasing; all intermediate descriptors close in parent.

Native roles monitor actual spawning parent with EVFILT_PROC NOTE_EXIT|NOTE_EXEC and getppid,
plus continuous deadline. Guardian sole writer death is visible on synthetic helper read ends.
Helper has no lifeline writer. Controller owns and reaps all direct children. NoAudioController
is an unsandboxed qualification orchestrator; role images carry App Sandbox entitlements.
Platform compile and behavior of this NEW assembly have NOT been run. Earlier native results
apply only to their pinned earlier images, not this revision. CI must verify suspended SecCode
inspection and process-filter permission under App Sandbox and treat any refusal as failed
qualification, never fall back to an unsandboxed role.

input_state.h implements reserved-before-one-synthetic-input, mute-before-route and bounded
stop/drain/dispose transition rules. A real input opener is deliberately absent. Unknown stop,
drain or disposal produces irreversible HOLD, never a terminal refund. Budget adapter must
reserve before input and retain reservation until independently verified terminal closure;
child exit alone, JSON HOLD, or source state is not terminal proof. Capture admission returns
false unconditionally and no runtime option overrides it.

Latest source hardening: build-generated exact CodeDirectory pins and fixed expected identifiers
are compiled into controller; disk/live equality alone is no longer accepted. Build seals bundle
after every image, including StateMatrix. StateMatrix exhausts 16 stop/drain/dispose/deadline
combinations, rejects second input and terminal retry, and verifies mute before route. Five-case
CI harness adds deadline, guardian A/B kill, helper kill and suspended-helper scenarios.
These NEW cases remain unexecuted until hosted macOS CI. Their current receipt is HOLD-only.
Known incomplete robustness: several spawn setup/destroy and close return values still need
full checked cleanup; failure receipts do not yet prove expected child exit cause or list all
reaped role PIDs; controller-death injection remains absent. Do not label this matrix qualified
until those deficiencies are repaired and hosted native checks actually pass.

Checked assembly revision: spawn allocation/setup/destroy, descriptor mappings, capability writes,
close, CF allocation and wait failures now converge through owned cleanup and HOLD. Natural
wait statuses are retained; cleanup SIGKILL cannot manufacture a successful case. Start receipt
contains only three owned role PIDs. CI independently decodes per-role wait statuses. Direct
controller death kills only Python-owned controller, then observes ESRCH after OS reaping of
grandchildren, never claims Python waited them. Role parent monitoring now uses getppid plus
capability EOF, not foreign-process kqueue filters. Deadline helper may exit71 on guardian EOF
or72 on its own deadline because those events race; injected guardian failure requires71.
All these are NEW SOURCE checks awaiting native CI, not native runtime acceptance.

READY protocol: role writes fixed {int32 pid,uint32 role} to inherited FD8 after capability
validation. Parent polls against continuous deadline and requires exact owned PID and role.
Startup event is emitted only after all three acknowledgments with >=500ms remaining in the
2-second deadline. Ownership table records PID immediately after successful spawn, before
identity inspection; failed bounded reap never clears retained ownership. Early failure emits
schema5 terminal receipt with partial PID list (-1 for never spawned), preserving HOLD.
Schema5 controller terminal fields: schema,noaudio_exit,terminal,pids,wait_status. Startup
fields: event="started",pids. Harness aggregate fields: schema,qualification,images,rows.
Readiness is not admission. Unknown closure and missing READY fail qualification.

## Parent-death injection evidence classification (authoritative clarification)

Mode parent_death names the injected controller kill only. Observation enum is
ESRCH_AFTER_OS_REAPER_PARENT_OR_DEADLINE. This proves eventual bounded aggregate closure
after controller death, not unique qualification of the parent-monitor mechanism: a role
ignoring parent changes and exiting only at its two-second deadline can satisfy this test.
Parent-monitor-specific native qualification remains unproven and admission remains unavailable.
New fixed-role implementation checks getppid and continuous deadline. FD3 capability pipe is
closed after initialization; it is NOT an ongoing EOF monitor. Historical README references
to process exec monitoring or ongoing capability EOF do not describe this fixed-role revision.
No unique parent-death attribution or physical capture acceptance is conferred by schema5.

Qualifier diagnostics: success schema5 unchanged. Failure is exactly
{schema:5,qualification:"NO_AUDIO_ONLY",failure:{mode,stage,error_class,controller_wait,
startup,terminal},images,rows}. Mode is one of six existing modes or null; stage is signature,
state_matrix,capture_reject,startup,communicate,wait_status,retirement. error_class is bounded
to AssertionError,TimeoutExpired,JSONDecodeError,RuntimeError,CalledProcessError,OSError,Other.
startup/terminal are strictly whitelisted existing receipts or null. No exception text, raw
streams, paths, argv or environment is emitted. Failure exits1 and emits one JSON object.

Native terminal schema6 replaces schema5 only for terminal records. Mandatory added keys:
failure_stage (NONE/SPAWN_SETUP/IDENTITY_VERIFY/CAPABILITY/READY_ACK/OWNED_REAP),
failure_role (0..3), failure_code (signed32), cleanup_killed (three integer 0/1 flags).
Success is NONE/0/0 and [0,0,0]. Aggregate envelope remains schema5, startup unchanged.
Security API failure_code preserves OSStatus; internal codes: -10001 identity/pin mismatch,
-10002 allocation, -10003 READY deadline, -10004 READY identity mismatch, -10005 generic
setup/I/O without errno, -10006 retirement, -10007 READY EOF. Other I/O failures retain errno.
wait_status now preserves actual failed-start child reap status; cleanup_killed distinguishes
cleanup-sent SIGKILL from a status already available before cleanup. These are diagnostics,
not qualification or capture authority. Native compile/runtime remains hosted-CI-only.
