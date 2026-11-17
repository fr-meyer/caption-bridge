# Voxtral 3: bounded compatibility and evaluation design

Research/design revision 1, 2026-11-17. Original issue #90 criteria, not a production adapter or live result. Baseline inspected: c98f5e10981be7cc25e9d8ea6263065e46d10de3, tree 5a6462c05c8cdedd765f50a3a112c5abd6963cab. No dependency, settings, provider, device or default changes. Current authorization: **$0 provider spend, no audio uploads**. All experiment numbers below are predeclared proposals, not measurements.

## Evidence register

Retrieved first-party sources on 2026-11-17, approximately 01:58–02:00 UTC:

- [R1 model card](https://docs.mistral.ai/models/voxtral-mini-transcribe-realtime-3-0): HTTP 200, public preview, October 20, 2026, $0.008/audio minute. Advertised latency is not measured application latency.
- [R2 protocol](https://docs.mistral.ai/studio/audio/speech-to-text/transcribe-in-realtime): HTTP 200, extracted lifecycle/settings/event table. Fetch warned incomplete HTML after 750000 bytes; examples not fully extracted. Only retrieved prose/table facts are used.
- [R3 turn detection](https://docs.mistral.ai/studio/audio/speech-to-text/turn-detection): HTTP 200, same HTML extraction warning; retrieved event ordering, text lag and defaults.
- [R4 announcement](https://mistral.ai/news/voxtral-3/): HTTP 200, EU-hosted API and self-deployment advertised. This is not a downloadable-weight license or hardware specification.
- [S1 SDK connection](https://raw.githubusercontent.com/mistralai/client-python/v2.9.3/src/mistralai/extra/realtime/connection.py), [S2 update payload](https://raw.githubusercontent.com/mistralai/client-python/v2.9.3/src/mistralai/client/models/realtimetranscriptionsessionupdatepayload.py), [S3 session](https://raw.githubusercontent.com/mistralai/client-python/v2.9.3/src/mistralai/client/models/realtimetranscriptionsession.py), [S4 segment](https://raw.githubusercontent.com/mistralai/client-python/v2.9.3/src/mistralai/client/models/transcriptionstreamsegmentdelta.py): HTTP 200, complete public tagged source inspected, not imported/executed. Repository uv.lock locks 2.9.3; wheel SHA256 e5c401caa6e862528ec41ceda4b551c9483081dd7bdb2a1ed73d8e9d0db3d6d0. Tagged source is schema evidence, not byte-verified installed-wheel equivalence or live compatibility proof.
- [P1 training](https://help.mistral.ai/en/articles/347617-do-you-use-my-user-data-to-train-your-artificial-intelligence-models), [P2 ZDR](https://help.mistral.ai/en/articles/347612-can-i-activate-zero-data-retention-zdr), [P3 retention](https://help.mistral.ai/en/articles/347628-how-long-do-you-store-my-data): HTTP 200. Extracted policy prose is described in criterion 6; omitted page tables are not inferred. Attempted legacy privacy documentation path returned 404, superseded by these help pages.

## Criterion 1: locked SDK and opt-in seam

The seam is app/transcribe.py, not the text-only app/providers.py. app/config.py remains February voxtral-mini-transcribe-realtime-2602, PCM s16le/16000 Hz, delay 1000 ms, mistral-medium-latest. The adapter waits for Updated before consuming audio. Model echo uses strict string equality; absent/null delay remains unverified, an explicit integer mismatch fails. Sender flushes then ends; final-only text has a separate callback and aggregate Done does not duplicate nonempty deltas. None of these facts proves v3 interoperability.

| Wire feature (R2/R3) | Exact 2.9.3 surface | Proposed disposition |
| --- | --- | --- |
| session.created / session.updated | S1 typed mapping; S3 requires request_id/model/audio_format, optional nullable delay | Require Created then matching Updated before any audio; no defaults inferred from absent echo |
| audio_format and target_streaming_delay_ms | S1 update_session accepts only these two arguments; S2 declares only these fields | Shared basic path is structurally plausible; explicitly validate mono s16le/16000 and integer delay 80–1200 or 2400 |
| language, context_bias | Not declared in S1 signature or S2 | Do not pass arbitrary kwargs or assume extra-field serialization; separate future typed wire adapter or reviewed SDK upgrade |
| diarize, speaker_references, turn_detection | Not declared in S1/S2 | Excluded from initial comparison; references and speaker UI out of scope; deny diarize+turn combination |
| transcription.text.delta | S1 typed mapping | Preserve whitespace exactly, append once |
| transcription.done | S1 typed mapping; existing app consumes text/usage | Keep final record separately, no concatenation of aggregate and deltas; discrepancy becomes explicit failure/count, not silent rewrite |
| transcription.segment | S1 maps S4; S4 requires text/start/end, optional nullable speaker_id | Existing app does not deliver this as caption delta. Missing timestamps cause parser fallback; do not claim diarization supported |
| turn.start/eager_end/resume/end | Absent S1 dispatch table, become UnknownRealtimeEvent | Not implementable as typed turns with this lock alone; keep disabled pending separate adapter |
| error, invalid JSON/schema, unknown type | Typed error or UnknownRealtimeEvent with raw content/error | Never log raw fallback content. Required unknown lifecycle/turn/text event fails experimental session, optional metadata is counted only |
| input_audio.append/end/flush | S1 send_audio/end_audio/flush_audio | R2 documents append/end, not flush in extracted lifecycle. Future adapter must verify flush support or omit it deliberately, not assume parity |
| cancellation | S1 events catches CancelledError, finally closes | Preserve existing app cancellation counter check and shielded late-connect disposal |

**Proposed configuration, not added:** separate experimental ASR selector default off; explicit requested model, reviewed alias-resolution allowlist, adapter revision and frozen options. Existing MISTRAL_TRANSCRIBE_MODEL alone is not sufficient to opt into a different protocol. Do not invent a rolling v3 alias: current exact family alias remains an open model-discovery leaf. A future requested rolling alias and returned resolved ID are distinct provenance fields. Admit an echo only when identical or a specifically reviewed alias-to-ID mapping valid at run start; never prefix-match or accept any provider echo. Revalidate Created/Updated/Done identity consistency. Null/missing requested option echo is a failed experimental readiness gate, not permission to send. No second capture or parallel ASR session.

Rollback is explicit Stop, bounded drain/close, verified tasks/socket gone, discard experimental state, then owner-selected unchanged baseline session. No automatic fallback on access rejection, quota, malformed ACK or transport failure. Preserve old config and adapter; no current code change is requested.

## Criterion 2: reproducible paired comparison

Freeze a manifest BEFORE any future run: fixture ID, public source/license/consent, SHA256 of PCM and reference text, duration/sample count, language/condition, speaker count, annotated speech/utterance boundaries, domain terms and critical numbers. No private meeting audio. Corpus procurement and manifests are still unexecuted; an empty corpus is not a successful experiment.

Use 16 fixtures of 15 seconds each: two independently sourced/consented public clips per stratum below, exactly 240 seconds unique audio. Normalize once to mono 16 kHz signed little-endian PCM, peak below clipping, retain conversion recipe and tool version. Reference annotations reviewed before provider outputs. Noise copies use seed 90, stationary noise at 10 dB SNR calculated over annotated speech; label synthetic perturbation. Pauses 0.3/1.5/3 seconds must fit each 15-second fixture. Mixed-language and multi-speaker clips must be naturally represented or transparently labeled constructed, never private recordings.

Replay identical 3200-byte chunks every 100 ms against a monotonic origin after verified ACK; last chunk may be shorter. Record actual send timestamps. If >100 ms behind, fail pacing rather than burst catch-up. Three repetitions of each fixture per arm, 96 sessions total, 24 audio minutes. Alternate AB/BA by fixture index, reverse order in repetition two, restore in three. One connection at a time, no retries in primary analysis, no selective reruns or dropped failures. Session hard wall cap 30 seconds including connect/drain; global wall cap 60 minutes. These are experiment limits, not current execution permission.

A = unchanged February adapter at 1000 ms. B = future approved v3 adapter at the SAME 1000 ms, language autodetect, bias empty, diarization and turns off. A separate 480 ms/turn-enabled experiment requires new registered comparison and budget, not post-hoc replacement of B. Freeze exact code/tree, SDK, options and requested/resolved model IDs. Alias drift during a study invalidates affected pairs.

Downstream BOTH arms: mistral-medium-latest, identical prompt/temperature/target English, context 5 segments, pause 1500 ms, fragment merge enabled, hold 3000 ms/minimum 15 chars/3 tokens; freeze all remaining config and glossary hash from the same baseline. Reset context between fixtures. Primary ASR comparison TTS off; separate optional readback arm uses the same approved baseline TTS/voice, buffered 1x, identical queue policy in both arms. No Gemini. Boundary differences induced by ASR are outcomes, not normalized away. Do not cache one arm's translations as the other's output. Downstream charges require a separate token/audio ceiling before approval.

## Criterion 3: corpus, metrics and predeclared decision

| Stratum (two fixtures each) | Required content |
| --- | --- |
| Korean clean | Native Korean, dates and numbers |
| English clean | Native English, dates and numbers |
| Accents | Korean-accented English and regional Korean |
| Noise | Matched clean-source clips with seeded 10 dB noise |
| Pauses | Clause-internal and sentence-end silence, trailing speech |
| Domain | Technical names/acronyms, negation and quantities |
| Mixed language | Korean/English code switching within utterances |
| Multiple speakers | Two alternating speakers; one controlled overlap interval, no identity labels |

Every timestamp uses monotonic elapsed milliseconds. Annotated source speech onset/end is mapped to the actual paced send clock, not connection-open time. Record connect-to-ACK separately. First caption = first nonempty rendered source text minus first speech onset. Stable caption = last change to the utterance's displayed source text minus annotated utterance end (can be negative); determine retrospectively, not by a guessed quiet period. Final caption = terminal committed source record minus fixture speech end; also report Done arrival separately. Translation latency = first rendered translated segment and final translated segment minus their corresponding annotated source utterance end. Readback latency = first **delivered output** sample for that segment minus source utterance end, separately from PCM-receipt/scheduling timestamps. Acoustic onset requires separately approved calibrated hardware; never infer it from SDK or browser scheduling. TTS-off readback fields are null/not_applicable, not zero.

Report per-arm/per-stratum n, failure counts, p50 and nearest-rank p95 (sorted index ceil(.95*n)-1), plus paired deltas. With six observations per stratum p95 is effectively maximum, explicitly low precision. Global estimates have 48 observations per arm, still exploratory. Failed/timed-out cases stay in denominators and cannot improve percentiles by omission; report successful-only percentiles alongside failure rate and worst-case timeout accounting. No interpolation or retrospective exclusion.

WER = (substitutions+deletions+insertions)/reference whitespace-token count after Unicode NFC, casefold English, removal of punctuation only. Korean WER is spacing-sensitive, so also report CER over NFC characters excluding whitespace and punctuation; never decompose Hangul selectively. Preserve digits and negation. Aggregate edit counts before division; also report per-fixture scores. Critical-number/name/negation exact-concept errors reviewed separately. Scoring ephemeral public-fixture outputs is allowed only in a later authorized run; repository report keeps numeric aggregates, not output text.

Two bilingual raters, blinded A/B and randomized presentation, independently score meaning fidelity, caption readability/segmentation and (optional) spoken clarity on 1–5: 1 unusable/wrong, 2 major corrections, 3 understandable with effort, 4 clear with minor flaws, 5 faithful and effortless. Record disagreement and both ratings, no AI substitute for human proof.

Proposed **go to opt-in implementation only if ALL**: zero privacy/duplicate/lost-tail/identity failures; no additional failed sessions versus A; global WER and CER each no worse than A by 1 absolute percentage point; no stratum worse by >3 points; zero additional critical-number/negation errors; first-caption p50 improves >=15%; stable/final/translation p95 each <= A+200 ms; optional readback p95 <= A+200 ms; median human fidelity/readability >=4 and not below A, no score 1. Missing human or readback evidence means unresolved for that branch. A threshold failure is a no-go for this configuration, not universal model inferiority. Freeze these thresholds before collecting data; revisions require a new version/study, retaining failures. No thresholds were measured here.

Result record (one per attempted session): schema_version, study_version, fixture_id/hash, stratum, pair_id, repetition, order, arm, code_tree, sdk_version, requested_model, resolved_model, options_hash, status/reason_enum, input_samples, sent_chunks, pacing_late_ms_max, connect_ack_ms, first_caption_ms, stable_caption_ms, final_caption_ms, done_ms, translation_first_ms/translation_final_ms, readback_delivered_ms, metric_null_reasons, word_edits/reference_words, character_edits/reference_characters, critical_errors, queue_peak, dropped_chunks, duplicate_count, tail_complete, socket_closed, task_leaks, billed_usage_known and cost_estimate. Human ratings join by blinded pair ID; no credentials, audio, transcript, raw event/error body or account identifiers.

## Criterion 4: mocked-test contract and retained regressions

These are **specified tests, not implemented v3 tests or passes**. Fake transport, fake monotonic clock, public synthetic strings only, network denied. Every case asserts zero raw-content diagnostics and exact terminal outcome.

| IDs | Stimulus and required oracle | Existing regression to retain |
| --- | --- | --- |
| V01–V04 | Good Created/Updated; missing ACK; wrong model/rate/format; absent/null/wrong delay. Zero bytes sent before verified ACK, timeout closes | tests/unit/test_asr_ack_final.py; test_asr_readiness.py |
| V05–V08 | Accepted reviewed alias; unlisted resolved ID; Created/Updated/Done drift; invalid option/delay/type (including bool). Fail closed without fallback | test_asr_ack_final.py; test_asr_diagnostics.py |
| V09–V12 | Empty/nonempty deltas with whitespace; final-only; delta+same Done; divergent Done. Exactly-once visible text, final-only callback once, divergence recorded | test_asr_ack_final.py |
| V13–V16 | Post-audio update forbidden; unknown required event; malformed JSON/schema; segment missing timestamps. No silent caption loss or raw fallback logging | test_asr_transport.py; test_asr_diagnostics.py |
| V17–V20 | turn eager_end/resume/end with late delta; invalid turn order; diarize+turn; references without diarize. No early translation, unsupported options rejected before connect | New isolated adapter tests required |
| V21–V24 | Provider error, connect/ACK/send/receive/drain timeout. Safe reason enum, finite deadline, primary error preserved, socket closes | test_asr_transport.py; test_asr_readiness.py |
| V25–V28 | Reconnect exhaustion/429; queue full; Stop during connect/send/receive; cancellation swallowed by SDK. Finite attempts and no replay duplication, bounded memory, actual cancellation | test_reconnect.py; test_queues.py; test_frontend_reconnect_pcm.py; test_asr_transport.py |
| V29–V32 | Graceful EOF with tail; Done before ready; EOF without Done; receiver-first sender failure. No false success; tail admitted once; all child tasks gathered and late socket disposed | test_asr_ack_final.py; test_asr_transport.py; test_full_pipeline_scenario.py |

Retain tests/unit/test_segmentation_benchmark.py, test_exporter.py, test_export_config_scope.py, test_analyze_exports.py and browser_tests/ alongside the deterministic full-pipeline suite. Parent runs actual relevant CI per .github/workflows/ci.yml on integrated head; this document does not reuse historical test counts as new proof. A future test harness must test the real adapter entrypoint, not only a parallel model of it.

## Criterion 5: native turn versus caption sentence

R3 says turn.start opens, eager_end may be canceled by resume, end closes; time_s is audio position, not wall time. Text deltas have no timestamps and may arrive AFTER turn.end. Defaults: start .5, eager .5, end .33, min silence 500 ms, timeout 3000 ms; required ordering start >= eager > end and timeout >= minimum. These are conversation-turn signals, not guaranteed sentence boundaries.

Decision now: retain semantic segmentation, no native-turn replacement. A later shadow-only adapter may record turn hints without emitting translations, flushing queues, triggering TTS or changing captions. At end wait the configured delay for late words (or next start as documented), but absent token timestamps attribution remains uncertain. Do not force a caption cut merely on next start if that would lose delayed text. Compare shadow hints against human-annotated boundaries: premature clause cuts, merged sentences, lost trailing words and boundary latency. Candidate boundary integration requires zero lost/duplicated words, no additional premature cuts, >=10% median boundary-latency improvement and p95 <= baseline+200 ms, with the criterion-3 readability gate. Eager events never commit work. Any ambiguous attribution remains no-go for boundary replacement. Overlap/speaker UI is a separate design, not silently enabled by this evaluation.

## Criterion 6: account, price, region and privacy

Public facts: R1 lists $0.008/minute. R4 advertises EU hosting, not a per-account routing guarantee. P1 says free Studio inputs/outputs may train models; PAYG customers can opt out, not an unconditional default exclusion. P2 restricts ZDR to approved PAYG stateless calls and distinguishes ZDR from training opt-out. Extracted endpoint table was absent: **realtime WebSocket ZDR eligibility is not established**. P3 does not establish a realtime-audio retention duration in retrieved prose. API-key presence proves none of these facts for the owner.

Open account leaves, evidence owner = owner/account administrator via redacted console/contract evidence or an explicitly authorized read-only route (no credential retrieval in this lane):

1. Exact v3 rolling alias/entitlement and February availability, dated model catalog or provider confirmation.
2. Organization tier, remaining audio/request quota, rate/concurrency/session-duration limits, billing rounding/minimums and included credits, dated console limits. No quota-increase request implied.
3. Approved endpoint/region, processing and storage residency, subprocessors and cross-border terms, contract/service configuration. EU marketing alone insufficient.
4. Audio/transcript/error retention duration, training opt-out actual state, ZDR approval AND realtime coverage, contract/admin evidence. Training opt-out is not deletion/ZDR.
5. February ASR, Medium token and optional TTS tariffs and usage ceilings, enough to price the whole experiment. No assumed free tier.

Budget proposal: 16*15s*3 = 12 minutes per arm. V3 ASR list-price component = $0.096. February component = 12*verified baseline price/minute. Total = ASR components + bounded Medium input/output tokens at verified tariffs + optional TTS charges + applicable minimums/taxes. No invented full-price quote. Primary retries = 0; concurrency = 1. Any separately approved retry consumes a reserved full-session allowance before connect; at most one per failed pair with both original failures retained, otherwise stop. Two simultaneous fast/accurate sessions are explicitly prohibited; they would double ASR minutes. Proposed approval ceiling at most $1 ONLY if the complete prospective calculation fits it, otherwise return a revised quote for approval. Current ceiling remains $0; nothing is reserved or spent.

Diagnostics: allowlisted event kind, safe reason, durations/counts, setting-match booleans, bounded model provenance and usage/cost-known status. Never dump S1 UnknownRealtimeEvent.content/error, SDK exceptions, audio/base64, transcript, headers, keys, websocket URLs/querystrings or account/request IDs. Retain ephemeral outputs only for authorized scoring, delete at run end; durable report uses aggregates and public-fixture hashes. Privacy/access failure aborts before upload, quota errors stop rather than hammer retries. Criterion 6 is **partially delivered, account-specific evidence unresolved**, not satisfied by listing unknowns and not a blocker to other design work.

## Criterion 7: hosted versus local feasibility and disposition

Hosted: basic PCM/delta path is plausibly design-compatible, but v3 options/turns exceed the typed 2.9.3 API and account/alias facts remain unknown. Verdict **no production switch; conditional evaluation unresolved**, not demonstrated quality failure.

Local/offline: R4 offers self-deployment but retrieved evidence does not supply v3 realtime downloadable weights, license rights, access procedure, checksum, supported runtime, quantization, GPU/CPU requirements, RAM/VRAM or measured real-time factor. February Apache weights do NOT confer v3 rights. Recorded-file “offline” transcription is not no-network local inference. Do not invent a parameter count or Mac memory estimate. Weight storage lower bound would be parameter_count*bits/8; total RAM additionally needs runtime, activations, caches and audio queues, all presently unknown. A local feasibility approval would require vendor-provided artifact/license/access and supported hardware matrix plus capacity/real-time-factor validation on an authorized isolated machine. No downloads, installs, sales contact, GPU purchase or device experiment now. **Local deployment no-go for this cycle on insufficient licensing/hardware evidence, not proof it is impossible.** Vendor evidence owner: provider documentation/support via owner-approved contact; machine evidence owner: later authorized device operator.

Conditional follow-up specifications (not issued or authorized here): F1 schema/alias adapter with V01–V32 and explicit rollback, no SDK change without review; F2 manifest/scoring runner with network-denied fixtures and schema checks; F3 priced public-audio paired evaluation only after account/privacy/alias gates and separate spend approval; F4 optional shadow turn study only after F1/F3 evidence. Parent exclusively owns issue publication. No viable-for-production verdict exists that would require immediate implementation.

### Original checklist disposition

1 compatibility design delivered with exact schema limits; 2 paired protocol delivered, corpus selection/run pending by design; 3 metrics/thresholds delivered, no measurements claimed; 4 test design/regression mapping delivered, future adapter tests not executed; 5 boundary assessment delivered, retain existing policy; 6 public review delivered, named account leaves remain unresolved; 7 distinct local/hosted verdict and conditional plan delivered with explicit unknowns. **Do not close #90 as fully complete until criterion 6's required account evidence is resolved or the owner explicitly changes that acceptance.** A paid run, microphone capture or production implementation is not an original mandatory closure criterion.
