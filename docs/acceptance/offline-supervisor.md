# Offline reservation supervisor, lane C

Implemented: scripts/attended_journal.py and scripts/attended_supervisor.py.
This is a real independent-process watchdog for ONE fixed harmless Python sleep
child. It is not a native capture watchdog, provider firewall or device runner.
No native profile exists; there is no command/plugin/profile override and no
readiness flag capable of enabling capture. All receipts say native_admission=false.

## Durable resource ownership

Coordinator initializes ONE private local journal once with Journal.initialize(path,
programme_sha256). Initialization is exclusive, file and parent directory fsynced.
Admission never initializes a missing journal. Keep the same programme/path across
all devices and attempts. Local flock is not distributed locking: simultaneous
remote-device admission is forbidden; coordinator must serialize the single ledger.
Never copy/reset/truncate/reinitialize it to recover allowance. Tests use disposable
journals, not the actual programme's remaining allowance.

Journal holds nonblocking exclusive POSIX inode lock for the whole child lifetime.
Reserve record is appended and fsynced BEFORE spawn; all reservations are fully
charged against 600000 ms, including failures, no refund. Sequence/hash chain,
programme identity, durations and shapes are verified on reopen. Partial writes,
missing files, replacement inode, malformed rows and uncertain fsync block admission.
A failed write poisons that open journal handle. A crash after reserve leaves an
unclosed reservation, so restart refuses another reservation. There is no CLI repair
or automatic close of an unknown physical resource. Reconcile actual closure and
independent ledger anchor before designing an explicit recovery operation.

Lock assumes private coordinator-owned parent directory on a local filesystem and
cooperating sole owner. Deletion/replacement by an adversary, rollback to an older
valid prefix, alternate journal paths or cross-host locks are NOT prevented. A hash
chain detects corruption, not authentic history. Independent anchored tail/custody
is mandatory for any future physical profile. Journal is bounded at 2 MB and fails
closed if exhausted; no compaction or cap reset is automatic.

## Process boundary and proof binding

CLI requires existing journal/programme, candidate SHA, proof file and exact SHA256.
Proof bytes must hash correctly and exactly declare schema=1, candidate, profile=
offline-fixed-child-v1, native_admission=false, provider_calls=0. This binds bytes
and declared candidate, not Git checkout authenticity or independent approval.
Coordinator must separately verify source HEAD/clean tree and review proof provenance.
Passing a different candidate cannot match that proof. No physical qualification
certificate is accepted by this offline schema.

Launch python3 -m scripts.attended_supervisor in a SEPARATE process. Controller
owns its stdin pipe: any byte is emergency Stop, EOF is controller death/disconnect.
Keep no duplicate writer handles. Supervisor uses its own monotonic deadline,
maximum 1000 ms offline reservation, and checks the pipe at most every 20 ms.
It kills only its own Popen child and waits up to one second for terminal status.
A failed/unknown wait leaves the reservation active. Spawn failure closes as error
but retains full charge. Deadline is measured before child launch.

The only child command is fixed stdlib sleep under Python -I -S, empty environment,
closed inherited FDs, no stdio output, no app/SDK/device imports or descendant spawn.
It ends itself after two seconds if supervisor is killed. That fallback is NOT the
reserved deadline guarantee. OS scheduling, uninterruptible kernel state, supervisor
SIGKILL and power loss cannot be proved safe by this userspace implementation.
A Popen terminal receipt proves this child exited, not a native stream closure.
No arbitrary PID/group kill or command can be supplied. Stop through pipe is the
supported bounded route, not termination of the watchdog itself.

Provider-deny boundary is currently construction: fixed no-provider/no-network child,
no credentials or dotenv, no adapters. It is not general-purpose network isolation.
Future B adapter integration must be a reviewed fixed profile, not a plugin command.
Reuse SoftwareNetworkGuard for Python API denial tests and reject provider SDK
construction before app import, but separately establish browser/native/OS egress
denial. Socket monkeypatches do not constitute a physical firewall.

## Smallest remaining qualification, NOT authorized by this document

After meeting end/readiness and independent profile review, one bounded synthetic
native-input attempt on the actual target platform must prove sole stream ownership,
OS/native close on Stop and controller death, output muted/fail-closed, egress denied,
no retained PCM, and actual stream closure under independent watchdog failure.
Calibrate timing including opening/teardown overhead against reserved duration.
Fault checks may need multiple attempts: reserve ALL in the same 600000-ms programme.
A pure software process death cannot substitute for this native lifetime proof.
Windows needs an independently reviewed native process-handle/job lifetime profile;
this POSIX flock/selectors implementation does not claim Windows support.

B handoff: keep ephemeral onset/capture adapter in B ownership. Do not call it here
until a fixed qualified profile supplies independently enforced resource lifetime,
provider-denied transport and cleanup evidence. No shared player/speed file changed.

## Offline checks

    python3 -m unittest discover -s tests/unit -p 'test_attended*.py' -v

Tests cover no refund/cap/reopen, exclusive admission including another process,
crash with durable unclosed reservation, partial journal, fsync-before-spawn failure,
proof hash/candidate mismatch, real harmless-child deadline/Stop/controller EOF,
separate supervisor process, spawn error and unknown child cleanup (fake handle).
They do not establish acoustic, browser, hardware, human or native firewall evidence.
