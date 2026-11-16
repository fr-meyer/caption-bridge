# Provider design verdicts, checked 2026-11-16

Research only for #90/#13. No audio, private captions, credentials, paid probe,
new provider client or default switch. Medium/Mistral translation, existing ASR,
normal buffered speech and explicit fallback policy remain unchanged.

## Voxtral Realtime Transcribe 3 (#90)

Official sources fetched 2026-11-16:

- [Model card](https://docs.mistral.ai/models/voxtral-mini-transcribe-realtime-3-0),
  dated October 20, 2026, **public preview v3.0**. It advertises configurable
  80-2,400 ms latency, turn detection, context biasing and speaker diarization.
  Listed price $0.008/minute, not proof of included account entitlement.
- [Realtime protocol](https://docs.mistral.ai/studio/audio/speech-to-text/transcribe-in-realtime).
  Extraction was partial, but lifecycle/settings/events below were retrieved.
  Older capabilities/audio_transcription URL returned 404; use the current URL.

This is audio-to-text streaming ASR over authenticated WebSocket, NOT text
translation, TTS, or a drop-in speech-to-speech pipeline. The lifecycle is
session.created, settings update/ack, input_audio.append chunks,
transcription.text.delta, input_audio.end, transcription.done, then close.
The guide says PCM signed 16-bit little-endian mono, default 16 kHz; explicit
format must describe actual input. Defaults/ack must be checked before sending
audio because settings become immutable after the first chunk. Delay accepts
80-1,200 ms or 2,400 ms (recommended start 480 ms). Advertised delay is model
transcription delay, not end-to-end caption/audio latency.

Deltas are append-only with their own whitespace; done is the transcript of
record. Diarization changes the event shape to transcription.segment and is
incompatible with turn_detection in one session. Speaker references need
additional audio and diarization, neither is authorized or needed now. Existing
segmentation/final-only/duplicate/reconnect behavior must not assume every new
provider event has the old shape. No new speakers/language expansion by default.

Verdict: **no switch in this candidate; design-compatible as a future explicit
ASR adapter, evaluation unresolved**. Preview lifecycle/settings differences
justify a separate typed adapter and tests, not a silent model-name replacement.
Before any implementation/default decision:

1. Verify exact rolling alias and account access/quotas/included billing. Do not
   guess a dated model ID or enable PAYG. Record requested/resolved provenance.
2. Check locked mistralai 2.x SDK schema and update_session support against the
   selected model. Public examples do not prove our lock supports every field.
3. Test settings echo, format validation, append/done ordering, silence/turn
   boundaries, failures, finite retries, cancellation and drain/close offline.
4. Separately approve bounded public-fixture live comparison; assess Korean and
   target languages, precision/numbers, latency, quotas and current terms for
   the actual account. Current retention/data residency and entitlement are
   unverified, not implied by API-key possession.
5. Keep current adapter/configuration recoverable. A rejected model/access check
   must fail visibly, never switch provider or start a second capture pipeline.

Missing live evidence is not a technical quality no-go. Research/design is
complete for this document's scope; #90 live compatibility acceptance remains
open unless the owner explicitly accepts a research-only disposition.

## Gemini Live Translate (#13)

Official URLs checked 2026-11-16:

- [Live Translation guide](https://ai.google.dev/gemini-api/docs/live-api/live-translate)
- [Preview model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-live-translate-preview)
- [Pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-live-translate)

Direct retrieval of all three hit a redirect limit. A same-day search restricted
to Google's documentation returned these official URLs and describes
speech-to-speech, 16 kHz input/24 kHz output PCM, optional input/output transcript
configuration and no text input. This is secondary discovery of official pages,
not a complete successful current-document/privacy/billing audit. Exact current
model availability, price/terms and account entitlement remain UNVERIFIED here.
Do not rely on a search summary to authorize spend or select a new default.

The retained [September 24 spike](gemini-live-spike.md) is historical evidence:
four short public synthetic streams, mixed keyword checks, no same-input Mistral
comparison, missing pause/two-voice cases, no general quality/latency conclusion.
It established audio transport/transcript shape, not meeting suitability.

Verdict: **retain the historical no-go for current-cycle integration, no new
quality verdict**. Audio-in/audio-out cannot implement the existing text-in/
text-out TranslationProvider contract. Replacing segmented translation/TTS would
require an independently approved source-audio tap, bounded session/spend policy,
transcript reconciliation and separate audio-mode interface. It would enlarge
privacy, coupling and failure scope immediately before the meeting. A text
Gemini model would be a separate text-translation evaluation, not this Live
Translate experiment and not an automatic fallback.

Revisit only with retrievable current official model/protocol/SDK/pricing and
account-tier data-use/retention terms, explicit audio-upload/spend approval,
same-input baseline, human meaning/numbers/listening evidence, quota/exhaustion/
reconnect/cancel cleanup, and a tested return to the existing Mistral path.
No new key, probe or provider calls were made. Historical estimates are not an
invoice or current-price guarantee. #13 comparative/live acceptance remains open.

## Deferred, not hidden scope

GLM/Large quality comparisons, speaker/language expansion, extra voices, offline
ASR, packaging/signing/notarization and automatic startup are separate later
decisions. Provider marketing latency/language counts do not qualify the app's
supported platform, output audibility, privacy or meeting readiness.
