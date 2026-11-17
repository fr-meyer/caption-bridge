# Hosted noaudio budget qualification suite

Source-only delivery after 2b26d93. No native process was run while authoring this
suite. Offline fixtures mock subprocesses, signals, native replies and waits.

## Exact hosted invocation

From the reviewed repository root, AFTER the parent-owned job has built and
verified the exact signed controller and fixed role images:

    python3 -m native.caption_helper.newqualifysuite "$SIGNED_MACOS_DIRECTORY" > "$RECEIPT_FILE"

SIGNED_MACOS_DIRECTORY is the directory containing NoAudioController and the
three fixed signed roles (the existing app's Contents/MacOS). Caller must verify
source identity, signatures and exact image identities immediately before running.
This suite adds no identity trust root and never changes signing, entitlements or
pins. Keep the old six-mode qualify_assembly invocation unchanged.

The suite refuses native execution unless sys.platform is darwin AND
GITHUB_ACTIONS=true AND RUNNER_ENVIRONMENT=github-hosted. Those environment guards
are accident prevention, not attestation or operational capture authority. Parent
CI owns genuine ephemeral-hosted-runner provenance and exact image review.
No journal/programme/path supplied by a caller is accepted. Each scenario creates
its own private, fresh DISPOSABLE qualification ledger, reserves 2000 ms, and
retains the debit/active HOLD. After controller reap it reopens the actual ledger
and checks persisted debit plus fresh-Custody rejection. Qualification ledgers
are removed after resources close; no actual physical-capture programme is opened,
reset, refunded or erased. These scenarios cost zero provider spend.

## Scenarios, fixed order

- valid: exact durable debit, reply/EOF, expected natural native terminal statuses.
- wrong_challenge: flip one challenge bit, require pre-role exit 70.
- replayed_challenge: use prior valid launch's challenge in a fresh launch; exit 70.
- truncated: 55-byte reply/EOF; exit 70.
- trailing: 57-byte reply/EOF; exit 70.
- missing_eof: full reply but retain sole writer until native timeout; exit 70.
- writer_death: close sole pipe writer without a reply; exit 70. This injects the
  EOF consequence of writer death, NOT a process-death-mechanism qualification.
- nonpipe: inherit /dev/null instead of the budget pipe; no challenge, exit 70.
- late_response: wait 2.2 seconds after challenge then attempt response; exit 70.
  BrokenPipe is expected if native has already retired; other early EPIPE fails.
- suspend_expiry: SIGSTOP direct owned controller, observe WIFSTOPPED, write reply
  and EOF, wait 2.2 seconds, SIGCONT; native must reject expiration with exit 70.
  This is process suspension, NOT proof of physical system-sleep behavior.

All negative scenarios reject unexpected stdout/started/terminal rows; exit 70
alone cannot mask an unexpected startup. All output is bounded to 4096 bytes and
the absolute attempt read/wait window is 7 seconds, plus at most 2 seconds owned
controller cleanup. Stop observation is bounded to 0.5 seconds. Small pipe writes
are below PIPE_BUF. No retry or fresh ledger is used to rescue the same attempt.
Only a direct owned controller is signalled/reaped. No reported role PID is killed.
On unknown terminal state the suite neither asserts descendant/physical closure nor
calls Journal.finish. Other scenarios remain isolated and finite after a failure.

## Exact public receipt contract

One compact JSON line on stdout. Exit 0 only for all ten PASS; exit 1 otherwise.
Top-level keys are exactly:

    schema, qualification, capture, terminal, result, passed, failed, rows

schema=1, qualification=NO_AUDIO_BUDGET_SUITE_ONLY, capture=false, terminal=HOLD.
result is PASS or FAIL; passed+failed=10. rows contains exactly ten entries in the
fixed order above. Each row has exactly:

    scenario, result, stage, capture, terminal, charged_ms

capture=false and terminal=HOLD on EVERY row including failures before debit.
This HOLD is the non-operational receipt disposition, not a claim about physical
resource lifecycle. charged_ms is 0 or 2000 only. PASS requires stage=COMPLETE and
charged_ms=2000. FAIL must have a non-COMPLETE stage from:

    PLATFORM SETUP SPAWN CHALLENGE DEBIT INJECT WAIT OUTPUT TERMINAL HOLD CLEANUP

No raw stdout/stderr, exception message, native challenge, PID, path, argv,
environment, journal contents or account information is projected. Assertions
about controller terminal consistency do not release holds and confer no capture
permission, independent physical closure or unique parent-monitor attribution.

For the parent CI receipt-consumer step:

    from native.caption_helper.newqualifysuite import parse_receipt
    value = parse_receipt(receipt_bytes)
    # Require value is not None and value['result'] == 'PASS'.

parse_receipt accepts at most 4096 bytes, rejects duplicate keys and unknown fields,
checks types (including rejecting boolean counts), exact scenario order, bounded
counts and PASS/FAIL consistency, and returns a fresh content-free projection.
Do not promote fixture data or noaudio suite PASS to operational authority.

## Offline verification

    python3 -m unittest discover -s tests -p 'test_caption_native_qualification_suite.py' -v

17 deterministic tests cover ten injection fixtures, strict projection/decoder
negatives, output/EOF bounds, fixed ordering and replay correlation, platform gate,
CLI result codes/privacy, malformed native challenges, unexpected output/exit and
cleanup-failure override. All native launches/signals/waits are mocked. Parent
owns independent review and the first real hosted execution/receipt validation.
