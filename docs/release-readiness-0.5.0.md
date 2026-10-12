# Proposed v0.5.0 release readiness

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
- P1.4 is closed by issue #35. Two-hour endurance, physical Windows, VoiceOver
  and second-operator onboarding are separate follow-ups for the owner Mac CLI scope.

This preparation changes only the package version in `pyproject.toml`, the
virtual project entry in `uv.lock`, `PACKAGE_VERSION` in `app/identity.py` and
release documentation. Identity display changes; capture, provider, translation,
speech and session behavior do not. The prior acceptance keeps its original
runtime identity; source comparisons establish which unchanged behavior carries.

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

## Concrete remaining attended cases

The [Mac checklist](mac-acceptance.md) applies before `dev` → `main` reliability
promotion. Its broad physical checks remain unperformed for this candidate:

1. Ordinary supported controller startup/readiness and loopback ownership;
   pre-Start default/explicit override behavior and New Session reset.
2. Public Korean connective pause/continuation, a clear polite ending,
   negation/numbers and representative terminology. Judge source response,
   readable target and latency separately. The already-passed dark-matter
   sentence and English hearing verdict do not need another demonstration.
3. Settings changes during listening, future-caption provenance and private
   export metadata; browser refresh with one capture pipeline and audio relock.
   Optional preview models must stay experimental rather than forcing a new
   provider comparison to validate Medium.
4. Mute/unmute and Replay while live captions continue, followed by Stop/Export,
   New Session and the repeated supported controller start/status/stop cycle.
   Earlier playback-only success does not establish this live interaction.
5. Console/log privacy checks. Controlled network interruption can be deferred
   with its reason recorded; do not disrupt Mac-wide networking by default.

Native microphone/output judgment and any required provider-backed physical
cases need the operator's attended Mac. Model/profile/provenance/epoch mechanics
already have deterministic coverage; do not repeat that coverage as an audio test.

## Later approval and publication sequence

No piecemeal device or provider approval is requested by this preparation.
When the owner chooses to finish release acceptance, present one concrete
session covering only the uncovered public-fixture/lifecycle cases, its ambient
microphone transmission, existing devices and cleanup. Resolve device readiness
once at the start and keep main promotion/activation explicit in the selected scope.

After the preparation is reviewed and its applicable checks pass, publish its
feature PR into `dev` under the repository workflow, then prepare a separate
`dev` → `main` release PR. Main merge/tag/release and installed Medium activation
remain pending. Preserve v0.4.0 as rollback; keep PR #81 device selectors and
PR #72 speed evaluation separate. Source branches and older PRs remain intact.
