# Gemini Live Translate: GCP synthetic spike

Status: research only, 2026-09-24. Related: [issue #13](https://github.com/fr-meyer/caption-bridge/issues/13). The production translation path and its Mistral default are unchanged.

## Decision

The preview model accepted streamed Korean audio and returned translated audio plus input and output transcript events in two short GCP trials. That establishes the transport shape, but does not establish caption quality. A clearer synthetic sample passed an automated check for the meeting concept and missed the time concept. Do not integrate or enable it in Caption Bridge yet. Continue with a small, consent-safe comparison before deciding on an optional audio path.

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

The clearer TTS sample adds roughly US$0.0006 at the published paid rate. The total modeled cost is about US$0.011, far below the approved ceiling. This is a duration-based estimate, not a billing statement. Connection setup is included in first-output timing; there was no direct timing run against the current Caption Bridge pipeline. The checks were simple English keyword checks over ephemeral output transcript text; they are not a human translation-quality review. No audio, transcripts, provider bodies, or credentials were retained in the repository, issue, Workboard, or logs. Only content-free counts and pass/fail results were recorded.

## Remaining evaluation

1. Compare the current segmented text-translation/TTS path and an isolated Live Translate harness on the same small, consent-safe Korean fixtures. Measure first useful caption, audio start, final transcript stability, and meaning preservation, including dates and numbers.
2. Test pauses, two speakers, accent variation, and background noise. Record aggregate outcomes only and inspect any raw speech/transcript only in a private, temporary evaluation session.
3. Check reconnect, timeout, quota, spend limit, and fail-closed behavior. Keep a per-session input/output budget and make the feature opt-in if implementation is later justified.
4. Decide on privacy and data-use terms for the actual account tier. Google's pricing table distinguishes free-tier product-improvement use from paid-tier use. Do not assume the tier from the presence of a key.
5. Write a go/no-go decision. If it is viable, open a narrow implementation issue for a separate audio-mode interface and synthetic smoke tests. Do not change the production default as part of the research spike.

Official references: [Live Translate protocol](https://ai.google.dev/gemini-api/docs/live-api/live-translate), [pricing](https://ai.google.dev/gemini-api/docs/pricing), [synthetic speech generation](https://ai.google.dev/gemini-api/docs/speech-generation).
