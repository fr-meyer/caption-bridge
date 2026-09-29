# Translation model selection

Caption Bridge uses Voxtral for live speech transcription and Mistral's chat API for text translation. The translation selector affects only text translation. Spoken readback remains on its separate TTS path.

Mistral Small (mistral-small-latest) remains the default. The selector also offers Mistral Medium (mistral-medium-latest) and Z.ai GLM 5.3 (zai-glm-5-3, public preview) through Mistral's chat API. An operator-configured default, if different, is also listed. Availability depends on the account and Mistral's current model catalog. A model being listed does not establish better caption quality or low enough latency for live use.

Choose a translation thinking level before Start, or change it in Settings. **Provider default** leaves the API reasoning setting unspecified. Small and Medium use a 200-output-token limit; GLM uses 1024 because a live public-text request spent all 200 tokens on thinking and returned no answer. **High reasoning (experimental)** sends Mistral's `reasoning_effort="high"` and uses a 1024-token limit for the listed models. It can change cost, latency, and wording; the existing 10-second translation timeout still applies. A response with no answer text fails that caption without an automatic retry. High is offered only for the three listed models; an unrecognized configured default uses Provider default.

Mistral Vibe labels its highest control “Max” but maps it to `reasoning_effort="high"` on the Mistral backend. We label the API request value here, rather than claiming Mistral-hosted GLM has a separately verified native Max setting. See [Mistral Vibe's request mapping](https://github.com/mistralai/mistral-vibe/blob/7c19608af06f6c61d63f8f7a5c3430da73fba2ab/vibe/core/llm/backend/mistral.py#L257-L262). Two public-text High requests to Mistral-hosted GLM returned captions, but this does not establish that High improves translation quality or live-audio readability.

Choose a model before Start, or change it in Settings during a session. A live change applies to the next finalized source segment. Translations already running, including their retries and quality-repair request, keep the model and thinking level selected when their segment was created. A provider response with no answer text marks that caption as failed without an automatic retry. Other failed provider requests follow the existing caption failure path; the selector does not fall back to a different model without a user choice.

The private JSON transcript records each segment's source text, translated text, target language, selected translation model ID, thinking level, output-token limit, revision, prompt version, creation/completion timestamps, and quality result. It also records model or thinking-level changes with a timestamp and first affected segment number. When Mistral returns them, the transcript records its response model ID and the sum of reported prompt and completion tokens from successful translation and repair responses. These fields may be absent for failed requests, legacy sessions, or providers that do not report them. The configured default in config.translate_model is not a substitute for each segment's model field.

The -latest IDs are aliases and can point to a newer release later. A response model ID may itself still be an alias, so these records do not guarantee a pinned model build. For a controlled quality comparison, keep the source text, target language, glossary, prompt version, and model IDs alongside the observed latency and human quality judgment. The app does not currently run an automatic quality benchmark when switching models.

No model or thinking choice is saved in browser storage. A fresh session starts from the server's configured default. The journal persists the session's model changes and per-segment metadata for interrupted-session recovery; old journals retain unknown model metadata rather than guessing.

References: [Mistral model lifecycle](https://docs.mistral.ai/inference/model-lifecycle), [GLM 5.3 model](https://docs.mistral.ai/models/zai-glm-5-3), [Mistral chat API](https://docs.mistral.ai/api).

## Bounded public-text comparison

Run python -m scripts.compare_translation_models on GCP for an offline plan. It prepares one fixed Korean-English public caption with the production translation prompt for all three listed models and makes no provider calls by default.

The one-case runner requires --live, --key-stdin or a process environment key, --ledger, --prior-cost-upper-usd, and a budget allowance. Its --project-ceiling-usd defaults to $1 and must be set explicitly when a different total has been approved; --max-spend-usd defaults to $0.03. It sends at most three sequential Chat Completions requests with the same Provider-default output limits as the app: 200 tokens for Small and Medium, 1024 for GLM. There is no retry. It durably reserves a conservative upper bound before each request and will not replay an existing ledger. The private ledger contains the public source/output text, model IDs, reported token usage, latency, and automated quality signals. Keep it outside the repository with owner-only permissions. The CLI prints only counts, bounds, and static failure codes.

The reservation uses twice the standard token rates listed by [Mistral pricing](https://docs.mistral.ai/inference/pricing), checked again on 2026-09-29. It bounds this run's usage equivalent; it is not an invoice. The single public sentence can establish API availability and a directional latency/quality observation, not comparative superiority. Human review on a broader representative corpus is required before changing the default.

### First bounded GCP observation (2026-09-28)

On the single fixed public sentence, Small and Medium both returned the same faithful English caption, with observed response times of 570 ms and 499 ms. The GLM 5.3 request returned HTTP 200, but its response did not pass the comparator's text/usage validation; the run stopped without a retry. That first run did not isolate whether answer text or usage metadata caused the failure. The follow-up below identified the model-specific output limit issue. Small remains the default. The private owner-only ledger retains the two public responses and reported token counts. These individual timings do not predict typical latency.

### Follow-up GCP evidence (2026-09-29)

A bounded GLM probe returned valid answer and usage data with both thinking and text chunks. A second public caption then exposed the actual failure: with Provider default and a 200-token limit, GLM used all 200 completion tokens for thinking, returned no answer, and ended with `finish_reason=length`. Sending `reasoning_effort="none"` to this hosted model returned HTTP 400. Raising the output limit to 1024 returned a faithful caption, with 372 completion tokens including thinking. The selector now gives GLM 1024 tokens at Provider default, while Small and Medium keep 200.

In a later six-case public Korean-to-English comparison, GLM with 1024 tokens and Small with 200 both produced a caption for every case, with no automatic quality flags. GLM preserved the trailing "but" on one paused clause that Small closed as a sentence. Other outputs showed no clear quality advantage; a technical-term rendering was less faithful to "synthetic model." Median API latency was 1,052 ms for GLM versus 658 ms for Small, and completion usage was 1,155 versus 48 tokens across these six cases. These small samples are directional, not a performance guarantee. Two GLM High requests also returned captions, with differing response structures.

The owner prefers GLM 5.3 as the eventual default if representative quality, latency, reliability, and real-audio acceptance support it. These public-text checks do not meet that release gate, so Mistral Small remains the default. The private GCP ledgers contain only public final answers and structural metadata, not thinking text. The cumulative conservative usage-equivalent upper after these checks was $1.1480764 under the owner's revised $1.15 maximum; it is not a bill.


### Public recorded-audio check (2026-09-29)

Two Korean [FLEURS](https://huggingface.co/datasets/google/fleurs) test clips (12.48 and 12.36 seconds, CC BY 4.0) were streamed on GCP through Caption Bridge's Voxtral Realtime transcription adapter. Each resulting transcript was translated once with Small and once with Mistral-hosted GLM 5.3 using the production prompt, Provider default thinking, and the model-specific output limits. All six provider requests completed without retry; both models returned usable English captions.

| Clip | First ASR text | Small translation | GLM 5.3 translation |
| --- | ---: | ---: | ---: |
| Bridge clearance | 4.2 s | 741 ms, 35 completion tokens | 2,742 ms, 793 completion tokens |
| Dark matter | 5.5 s | 684 ms, 20 completion tokens | 955 ms, 243 completion tokens |

The first ASR transcript fused a Korean phrase meaning “under the bridge” into a different word. Both translators recovered the bridge-clearance sense; GLM phrased it more naturally. On the second clip, their translations were equivalent. GLM took longer and used more output tokens on both clips. Combined with the six mixed public-text cases above, this does not establish enough quality benefit to change the translation default from Small. High reasoning was not used in this audio check.

This tested recorded public audio, the real ASR adapter, and the production translation prompt. It did not exercise microphone hardware, browser rendering, spoken output, live model switching, or human readability. The added conservative usage-equivalent reservation was $0.0615488, bringing the cumulative upper to $1.2096252 under the owner's $1.25 ceiling. It is not an invoice.
