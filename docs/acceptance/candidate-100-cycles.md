# Candidate 100-cycle software check

Run `python -m scripts.candidate_endurance --cycles 100 --output acceptance/endurance.json`.
The default is exactly 100 cycles, not a duration soak. Smaller positive integer
counts (1 through 100) are for diagnostics only. There is no timed two-hour mode.

Each cycle retains the full pipeline assertions, synthetic fault injection,
teardown/leaked-task checks and offline IO guard. Only the artificial 250 ms
inter-cycle pause is removed; genuine scenario timing and fault checks remain.
A failed result, exception, denied IO or timeout fails the check. The async
per-cycle limit is 45 seconds and the aggregate limit is 240 seconds. Async
cancellation is cooperative; the hosted job's 10-minute limit is the outer hard
budget, including dependencies and tests, not a guaranteed run duration.

The aggregate JSON records the checked-out commit, expected/requested/completed
cycles, elapsed wall time, maximum cycle duration and denied IO count. Completed
cycles are cycles that returned a result (including a false result); interrupted
cycles are not counted. `cycles` remains an alias for completed cycles.
Exception messages are not retained. `physical_acceptance` is always false.

The stable `candidate-100-cycles` job runs automatically on PRs targeting main
(exact PR head, not GitHub's synthetic merge commit), and on pushes to main
(the actual merged commit). Reusable workflow callers supply a full `sha`;
manual dispatch also requires a full SHA for recovery. Explicit inputs take
precedence over inherited PR event context. Checkout SHA equality is verified.
The normal CI workflow is unchanged.

## Release boundary

These triggers and the reusable workflow provide validation, not publishing
or enforcement. A PR-head result is not evidence for a different merge SHA.
Before publishing, the release controller must require successful evidence for
the exact release SHA. The parent audit found an empty release-required-check
list and no CI-check gate in the current broker release path. This source change
does not change that broker, branch protection or publisher policy, and does not
claim release enforcement. Physical/hardware and real-provider acceptance remain
separate and unqualified by this software-only check.
