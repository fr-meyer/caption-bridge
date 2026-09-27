# Gemini Live Translate: GCP synthetic spike

Status: research only, 2026-09-24. Related: [issue #13](https://github.com/fr-meyer/caption-bridge/issues/13). The production translation path and its Mistral default are unchanged.

## Decision

The preview model accepted streamed Korean audio and returned translated audio plus input and output transcript events in four short GCP trials. That establishes the transport shape, but does not establish caption quality. The first clearer sample missed a time-detail check; a later clean numbers sample passed all three checks, while the same sample with synthetic noise missed its subject check. **No-go for integration in the current cycle:** leave the model disabled and the Mistral path unchanged. These small keyword checks are diagnostic only, not a general accuracy verdict.

This model is audio-in/audio-out. It cannot implement the existing text-in/text-out `TranslationProvider` contract. A future experiment would need a separate source-audio tap and would use the output transcript for captions. It must remain off by default, with the current segmented text translation and TTS path intact.

## Method and bounded evidence

The run used GCP only, the existing gateway environment credential, and a user-approved US$1 maximum. No private microphone audio was used. Both fixtures contained the same short Korean sentence about a meeting starting at 3 p.m. Trial A used offline synthetic speech. Trial B used a short, clearer synthetic TTS sample. Audio was converted to 16 kHz mono, 16-bit little-endian PCM and sent in approximately 100 ms chunks. Output audio was measured at 24 kHz mono PCM. One connection was made per fixture, with input-byte, output-byte, and wall-time caps; there was no retry loop.

| Check | Trial A: offline voice | Trial B: clearer synthetic voice |
| --- | ---: | ---: |
| Input audio | 5.68 s | 3.84 s |
| Translated audio received | 10.25 s | 8.00 s |
| First output from connection start | 3.82 s | 4.13 s |
| Input and output transcript events | Both | Both |
| Automated meeting concept check | Missed | Passed |
| Automated time concept check | Missed | Missed |
| Estimated Live Translate paid audio charge | US$0.00588 | US$0.00454 |

The clearer TTS sample adds roughly US$0.0006 at the published paid audio rate. The first two Live Translate streams have an **audio-only** estimate of US$0.01042. Google also documents a text-token surcharge when input or output transcription is enabled, so these audio calculations do not represent a total charge. Actual billing and account tier were not available to this evaluation. Connection setup is included in first-output timing; there was no direct timing run against the current Caption Bridge pipeline. The checks were simple English keyword checks over ephemeral output transcript text; they are not a human translation-quality review. No audio, transcripts, provider bodies, or credentials were retained in the repository, issue, Workboard, or logs. Only content-free counts and pass/fail results were recorded.

## Follow-up clean/noise comparison

A subsequent GCP run synthesized one short Korean sentence about a train leaving tomorrow at 9 a.m. The clean and noisy conditions used the **same generated audio**; the noisy copy added seeded, low-amplitude stationary noise. Each had a separate Live Translate session. At the end of each stream, the client sent `audioStreamEnd` and waited for remaining output. The fixture audio was held in memory only.

| Check | Clean speech | Same speech with noise |
| --- | ---: | ---: |
| Input audio | 3.48 s | 3.48 s |
| Translated audio received | 12.75 s | 12.75 s |
| First output transcript from connection start | 4.05 s | 3.95 s |
| Input/output transcript events | 2 / 2 | 2 / 2 |
| Automated train / tomorrow / nine checks | 3 of 3 | 2 of 3; train missed |
| Input number recognized by source-transcript check | Yes | Yes |
| Estimated Live Translate **audio-only** charge | US$0.00700 | US$0.00700 |

The four completed Live Translate streams therefore have a combined audio-only estimate of US$0.02442, excluding synthetic speech generation, transcription text tokens, and any billing adjustments. This remains far below the US$1 spending ceiling by the published rates and the short input/output limits, but it is **not an invoice**. The pause and two-voice fixtures were not tested: the synthetic speech generator stalled after these two completed sessions and the whole evaluation process ended at its 170-second limit. No client-level retry loop was made. The stall is a fixture-generation limitation, not a Live Translate failure.

For the current Caption Bridge path, the GCP deterministic quality gate passed 26/26 synthetic classification cases and the segmentation gate passed 10/10 cases. These validate local checks and boundary behavior only. A live Mistral comparison on the same audio was not available in the isolated GCP harness, so no provider-to-provider quality, latency, or cost claim is made.

## Remaining evaluation

1. Compare the current segmented text-translation/TTS path and an isolated Live Translate harness on the same small, consent-safe Korean fixtures. Measure first useful caption, audio start, final transcript stability, and meaning preservation, including dates and numbers.
2. Test pauses, two speakers, and accent variation with a bounded fixture generator; repeat background-noise conditions at more than one level. Record aggregate outcomes only and inspect any raw speech/transcript only in a private, temporary evaluation session.
3. Check reconnect, timeout, quota, spend limit, and fail-closed behavior. Keep a per-session input/output budget and make the feature opt-in if implementation is later justified.
4. Decide on privacy and data-use terms for the actual account tier. Google's pricing table distinguishes free-tier product-improvement use from paid-tier use. Do not assume the tier from the presence of a key.
5. Revisit the current no-go only after the comparison and failure gates are measured. If evidence supports a later opt-in mode, open a narrow implementation issue for a separate audio-mode interface and synthetic smoke tests. Do not change the production default as part of the research spike.

Official references: [Live Translate protocol](https://ai.google.dev/gemini-api/docs/live-api/live-translate), [pricing](https://ai.google.dev/gemini-api/docs/pricing), [synthetic speech generation](https://ai.google.dev/gemini-api/docs/speech-generation), [Live API billing guidance](https://ai.google.dev/gemini-api/docs/live-api/best-practices).
