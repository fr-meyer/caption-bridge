# Unified completion and release acceptance

Status: active source preparation, not a release or hardware certification.

## Baseline

Published release v0.5.0 is `39ecd3e7e6eafd367877eff3b0a0ef878a17b127`.
The current development baseline for this project is
`8d98a0b8d5a81ddfb78ad0ab30ee05de33efa7e9`, including merged PRs #85,
#86, #87 and #89. Reuse that work instead of merging obsolete drafts again.
The installed version must be inspected independently before any rollout;
a published tag is not proof of the installed build or its immediate rollback.

## Unified issue map

| Work | Current implementation | Required closeout |
| --- | --- | --- |
| #88 ASR reliability | Correlated diagnostics and authoritative recovery snapshots in development | Inspect complete acceptance coverage; fix actual gaps; exact-candidate tests |
| #80 / #81 audio routes | Native input and shared-context output routing in development | Reconcile old draft, verify privacy/failure/reconnect behavior and truthful capability reporting |
| #67 / #72 speech speed | Isolated pitch-preserving evaluation tools, normal app speed unchanged | Evidence-backed evaluation decision; do not claim physical listening or promote an unvalidated faster default |
| #65 progressive playback | Opt-in playback and timing/evaluation tooling | Repeatable bounded software evidence, with native audible latency and quality distinguished |
| #69 terminology | Editing/Undo/provenance and keyboard-focus regressions | Software regression acceptance; comparative human usability remains separate |
| #23 roadmap/platform | Ubuntu current-source and separately qualified Windows fixture evidence | Exact-final-head checks, support/docs/dependency identity, reviewed release and rollback |
| #90 Voxtral 3 | Research/evaluation issue | Current-source compatibility/privacy/cost and explicit go/no-go or remaining-evidence note; no silent default switch |
| #13 Gemini | Research-only, current-cycle integration no-go | Preserve justified decision and actual unperformed comparisons; no production integration implied |

## Completion gate

- [ ] Freshly verify repository/base/head and preserve previous releases.
- [ ] Inspect existing implementations against issue acceptance; implement only real gaps.
- [ ] All mandatory software CI successful for the exact final candidate.
- [ ] Independent review, with no unresolved release-blocking findings.
- [ ] Record actual version, runtime and lock identity plus dependency-audit result.
- [ ] Verify install/start/stop/export instructions and recoverable rollback.
- [ ] Record source release, exact tag/commit and every issue/draft disposition.

Physical devices, audible pitch/clarity, native latency, VoiceOver, comparative
human usability and physical Windows acceptance are not inferred from hosted CI.
Keep unmet issue criteria open. A software soak is neither live-provider
endurance nor an offline ASR product. Source publication and installed activation
are distinct operations. Preserve the existing supported setup until the
replacement passes its own required acceptance.
