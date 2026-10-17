# Installation and physical-check plan — October 17, 2026

Ordinary installed Medium needs no update or repeated acceptance test for this
timing work. The installed checkout, recorded development application and local
timing helper have identical `app` tree
`bc00dc015d58374ec579b9ce6063df8635567197`. Their repository heads differ:

| Source | Exact head | State |
| --- | --- | --- |
| Mac installation | `a746f9aff65ee40ff3943d1137127378e744fae2` | Installed; October 13 verification recorded Medium and buffered speech |
| Development branch | `c3548e0172b679b4062d323a72a5beec36e7c17c` | October 15 PR85/86 merge and exact-head CI record |
| Browser timing attachment | `51c56bb1b0658bdea321d340bde3e82fca0d3aa4` | Local, reviewed, offline-only |
| Published v0.5.0 | `39ecd3e7e6eafd367877eff3b0a0ef878a17b127` | Retained published release identity; distinct from the installed candidate |

The Mac Git HEAD was read on October 17. Merge/release identities above reference
retained records; they are not a live deployment or controller readback.

The installation receipt recorded `mistral-medium-latest`, buffered speech,
loopback `127.0.0.1:8765`, 50 unchanged dependencies and a stopped controller.
These are historical verification results, not a claim about a currently running
process. Application-tree equality transfers application source identity only;
it does not transfer whole-repository, environment or physical acceptance.

## Use installed Medium

From the existing Mac checkout, the supported on-demand commands remain:

```sh
make ctl-start
make ctl-status
```

Open `http://127.0.0.1:8765`, confirm Medium and English, choose the intended
microphone and speech output, and press Start yourself. Wait for transcription
ready before supplying speech. Enable audio with its separate button when needed.
Use normal product Start/Stop; no spending cap, acceptance wrapper or automatic
session cutoff is added. At the end, Stop and, when finished with the service:

```sh
make ctl-stop
make ctl-status
```

This document does not execute those commands or initiate a microphone/provider
session. The earlier successful Medium and public-quartet listening results keep
their recorded scope; the operator has confirmed Close Trial for the local check.

## Optional installation change

There is no application-byte benefit to advancing the installed SHA to the
current development head just for this timing work. If a later installation is
requested, use the [Mac CLI runbook](../../docs/mac-cli.md) and this checklist:

1. Name the exact approved candidate, compare its application and dependency
   changes, and check reviews and CI for that exact revision.
2. Preserve any dirty canonical work, Mac-local configuration, saved results and
   environment. Record the actual installed SHA and owner-only settings without
   printing secrets. The October 13 immediate rollback is
   `78c25a49b7635e2e887322bc39764b993295d657`; verify it still matches the intended
   rollback rather than treating the published tag as the immediate predecessor.
3. Stop through the supported controller and confirm stopped. Use a clean tree;
   never overwrite dirty work. Follow the runbook's frozen dependency sync only
   when executing the approved upgrade, then verify identity and software
   preflight. Do not install a service or change permissions.
4. Confirm effective Medium, buffered speech and loopback binding. Start only for
   the separately requested use or physical check. Record final identity and
   controller state; preserve the rollback until the result is accepted.

## Optional per-chunk physical comparison

This is research for a later progressive-playback/default decision. It does not
block installed Medium. `ActorTimingBridge` currently rejects attended actors;
there is no supported attended launch command for this new collector yet.

Before proposing that session, implement an explicitly attended attachment that
preserves the qualified actor's device ownership and cleanup, review it, freeze
its source/helper/fixture hashes and run only the affected silent checks. Keep
the original helper and `51c56bb` evidence intact. A full public-fixture silent
Chrome run remains unperformed; the retained native-browser check used tiny
silence and fake audio, and must not be described as full-fixture qualification.

The concrete future session scope is:

- Allow about five minutes of operator time after explicit readiness. Use the
  existing Mac/Chrome, operator-selected output and public Google FLEURS Korean
  `ko_kr` test-offset-100 fixture (CC BY 4.0): 296,640 samples at 24 kHz, 12.36
  seconds, 124 chunks including the 60 ms tail. Use the retained verified copy;
  do not download or substitute a different recording during the session.
- Play the same fixture four times in buffered/progressive/progressive/buffered
  order, one clip at a time: 49.44 seconds of source speech. This is local fake-SDK
  fixture delivery with **zero ASR, translation or TTS provider requests** and no
  provider cost. It does not test Medium or provider cadence. Keep ordinary
  Medium and buffered defaults unchanged.
- The operator wears the chosen output, selects routes, presses Start and Enable
  audio as the approved helper requires, and confirms clarity, gaps, overlap and
  mode preference. If native input is part of that helper's check, disclose its
  intended local measurement duration and immediate-disposal policy before
  readiness; capture itself begins only on the operator's manual Start. Otherwise
  keep native capture absent. No ambient audio is sent to a provider.
- Keep numeric source-yield, receive and scheduling rows separate from hearing
  judgments. ACKs and schedule timestamps are not acoustic onset. Stop on missing
  audio, overlap, device loss, capture not closing or an unexpected provider path;
  do not start an automatic retry or repeated listening loop.
- Finish once, keep saved results available for review, and verify capture off,
  scheduled sources/timers cancelled, pending speech zero, WebSockets closed and
  owned server/browser processes exited. Close Trial retires the helper; retain
  only the agreed compact metadata, not captured microphone audio.

Native Safari, physical Windows, long-session endurance, faster-speech design and
comparative terminology usability retain their separate scopes. None is a new
prerequisite for current Medium use. Enabling progressive speech by default or
publishing/installing a new candidate requires its own requested action.

## Evidence reused

- PR85 exact-head CI `38744021054` and development push CI `38744585477`: all
  three jobs passed on each run. The Python matrix passed 505 tests with two
  explicit skips per version; Chromium passed 60 tests. The supplemental native
  Windows lifecycle expected failure remains open.
- `51c56bb`: eight focused contracts passed in 0.91 seconds; independent source
  review clear. The affected muted Chrome check passed in 14.46 seconds with four
  complete reports, observer retirement and owned cleanup; independent retained
  result review clear. These checks used no physical devices or providers.
- The attended public quartet was reported clear with no overlap, and Close Trial
  was confirmed. Its older aggregate gap counters do not establish per-chunk
  timing or prove a cause. Do not repeat that listening test merely to obtain a
  duplicate result.
