# Historical v0.5.0 release-readiness preparation

Status correction, 2026-11-16: v0.5.0 was published through PR #84, main
merge `39ecd3e7e6eafd367877eff3b0a0ef878a17b127`. The dated preparation
record below is historical, not the current release gate or a pending
v0.5 publication request. Next-candidate rollback is v0.5.0. Use
[candidate validation](candidate-validation-20261116.md) for current gates.

This local preparation starts from merged `dev`
`a5e81b6bcc8a3eecec88d38283c3099a38c79257`. It proposes a minor version for
the combined caption controls and reliability repairs. It is not a published
release, installed-app update or authorization to start microphones/providers.

## Existing evidence to reuse

- PR #82 head `27c8b447a5462e94b31680260a06211a374239fd` and its dev merge
  have identical trees. Exact-head CI and the reviewed deterministic gates pass.
- Independent combined-source, ASR, connection-ownership, capture-tail and
  final CI-repair reviews have no remaining concrete source findings. Repository
  policy asks for exact-head review; it does not specify a separate human reviewer.
- The [October 12 Medium record](acceptance/medium-mac-2026-10-12.md) belongs
  to application tree `9bb804d1655d26df1bd6f11903ee7df94f5dc4fa`, which is
  exactly the merged application tree. It already proves the public Korean
  microphone/ASR/Medium/English buffered-speech path and the human hearing verdict.
- The October 7 prerecorded playback result proves clear playback, Catch up
  stopping and Replay restarting in its narrower scope. `app/tts.py` and
  `app/static/pcm-player.js` remain byte-identical to that candidate.
- The [October 13 owner Mac record](acceptance/mac-release-2026-10-13.md)
  completes the planned listening/lifecycle cases on exact source `080ee7aa`;
  this documentation successor preserves its application tree unchanged.
- P1.4 is closed by issue #35. Two-hour endurance, physical Windows, VoiceOver
  and second-operator onboarding are separate follow-ups for the owner Mac CLI scope.

The version preparation changed the package version in `pyproject.toml`, the
virtual project entry in `uv.lock`, `PACKAGE_VERSION` in `app/identity.py` and
release documentation. The subsequent isolated repair updates the dev-only
`pytest-base-url` → `requests` → `urllib3` dependency from 2.7.0 to 2.8.0.
The fresh audit found three distinct issues represented by six alias records;
the repaired Apple Silicon/Python 3.11 catalog reports no known findings.
Full validation and the remaining audit selectors are recorded separately.
Identity display changes; capture, provider, translation, speech and session
behavior do not. The prior acceptance keeps its original runtime identity;
source comparisons establish which unchanged behavior carries.

## Work that does not need another audio session

- Check package/runtime/virtual-lock version agreement, identity endpoints,
  third-party lock equality, pinned workflow revisions and whitespace/lint.
- Review the small preparation delta; reuse existing runtime and browser tests.
  Run exact-head hosted CI when this candidate is later published.
- Before release, run the documented networked frozen dependency audit on GCP,
  including the actual deployment target. A static lock inventory is not a fresh
  advisory audit. The observed owner target is Apple Silicon macOS/Python 3.11;
  do not infer physical Windows support from generic audit selectors.
- Use the existing CLI upgrade/rollback procedure. A saved
  `MISTRAL_TRANSLATE_MODEL` overrides the Medium code default. Record any
  prior value privately and change it only under the later activation scope.
  Never copy API keys or environment contents into this record.

## Completed attended cases and retained scope

The [October 13 owner Mac record](acceptance/mac-release-2026-10-13.md)
consolidates two separately approved windows: ordinary controller startup,
connective/ending/negation/number/terminology cases, Medium default and High,
actual Settings, browser replacement/audio relock, mid-clip mute/unmute/Replay,
Small → Medium future-caption provenance, Stop/export, New Session defaults
and retained results. The initial helper timeout remains in its historical
record; the narrow follow-up completes its missing caption/speech cases.
No uninterrupted live run or endurance result is inferred by adding windows.

Controlled network interruption is deferred because Mac-wide disruption and
extra retries were outside the agreed public-fixture session. Windows,
VoiceOver/second operator, endurance and preview-model comparisons remain
separate follow-ups for the supported owner Mac CLI scope. Buffered playback
and normal speech speed were used; opt-in progressive playback has automated
coverage without a new physical claim.

Application bytes and the locked package catalog remain identical to the
accepted `080ee7aa31ad5bb4ade26e1a695c4d9286983bb1` candidate. Reuse its live,
source-review, 459-test GCP and ten-selector dependency-audit evidence. Hosted
CI at merged dev `a5e81b6` passed all three jobs, including 51 Chromium cases;
it supports unchanged behavior and is not hosted CI for this successor.
After publication require exact-head Python 3.11/3.13 and browser CI, plus
review of this sanitized documentation delta. No extra audio session is needed.

## Later approval and publication sequence

The planned listening checks are complete and the operator is released from
attendance. Publication, main promotion and installed activation need their
own scope. Keep private transcripts, screenshots, test harnesses and detailed
run evidence local; publish only this content-free acceptance summary.

After the preparation is reviewed and its applicable checks pass, publish its
feature PR into `dev` under the repository workflow, then prepare a separate
`dev` → `main` release PR. Main merge/tag/release and installed Medium activation
remain pending. Preserve v0.4.0 as rollback; keep PR #81 device selectors and
PR #72 speed evaluation separate. Source branches and older PRs remain intact.
