# Translation model selection

Caption Bridge uses Voxtral for live speech transcription and Mistral's chat API for text translation. The translation selector affects only text translation. Spoken readback remains on its separate TTS path.

Mistral Small (mistral-small-latest) remains the default. The selector also offers Mistral Medium (mistral-medium-latest) and Z.ai GLM 5.3 (zai-glm-5-3, public preview) through Mistral's chat API. An operator-configured default, if different, is also listed. Availability depends on the account and Mistral's current model catalog. A model being listed does not establish better caption quality or low enough latency for live use.

Choose a translation thinking level before Start, or change it in Settings. **Provider default** keeps the existing request behavior and 200-output-token limit. **High reasoning (experimental)** sends Mistral's `reasoning_effort="high"` and raises the output limit to 1024 tokens so thinking has room for an answer. It can increase cost and latency, and the existing 10-second translation timeout still applies. A provider response with no answer text fails that caption without an automatic retry. High is offered only for the three listed models; an unrecognized configured default uses Provider default.

Mistral Vibe labels its highest control “Max” but maps it to `reasoning_effort="high"` on the Mistral backend. We label the API request value here, rather than claiming Mistral-hosted GLM has a separately verified native Max setting. See [Mistral Vibe's request mapping](https://github.com/mistralai/mistral-vibe/blob/7c19608af06f6c61d63f8f7a5c3430da73fba2ab/vibe/core/llm/backend/mistral.py#L257-L262). The high setting has not yet passed live GLM caption acceptance under the current $1 test limit.

Choose a model before Start, or change it in Settings during a session. A live change applies to the next finalized source segment. Translations already running, including their retries and quality-repair request, keep the model and thinking level selected when their segment was created. A provider response with no answer text marks that caption as failed without an automatic retry. Other failed provider requests follow the existing caption failure path; the selector does not fall back to a different model without a user choice.

The private JSON transcript records each segment's source text, translated text, target language, selected translation model ID, thinking level, output-token limit, revision, prompt version, creation/completion timestamps, and quality result. It also records model or thinking-level changes with a timestamp and first affected segment number. When Mistral returns them, the transcript records its response model ID and the sum of reported prompt and completion tokens from successful translation and repair responses. These fields may be absent for failed requests, legacy sessions, or providers that do not report them. The configured default in config.translate_model is not a substitute for each segment's model field.

The -latest IDs are aliases and can point to a newer release later. A response model ID may itself still be an alias, so these records do not guarantee a pinned model build. For a controlled quality comparison, keep the source text, target language, glossary, prompt version, and model IDs alongside the observed latency and human quality judgment. The app does not currently run an automatic quality benchmark when switching models.

No model or thinking choice is saved in browser storage. A fresh session starts from the server's configured default. The journal persists the session's model changes and per-segment metadata for interrupted-session recovery; old journals retain unknown model metadata rather than guessing.

References: [Mistral model lifecycle](https://docs.mistral.ai/inference/model-lifecycle), [GLM 5.3 model](https://docs.mistral.ai/models/zai-glm-5-3), [Mistral chat API](https://docs.mistral.ai/api).

## Bounded public-text comparison

Run python -m scripts.compare_translation_models on GCP for an offline plan. It prepares one fixed Korean-English public caption with the production translation prompt for all three listed models and makes no provider calls by default.

Live mode requires --live, --key-stdin or a process environment key, --ledger, --prior-cost-upper-usd, and an allowance that fits the unchanged $1 project ceiling. It sends at most three sequential Chat Completions requests, each capped at 200 output tokens, with no retry. It durably reserves a conservative upper bound before each request and will not replay an existing ledger. The private ledger contains the public source/output text, model IDs, reported token usage, latency, and automated quality signals. Keep it outside the repository with owner-only permissions. The CLI prints only counts, bounds, and static failure codes.

The reservation uses twice the standard token rates listed by [Mistral pricing](https://docs.mistral.ai/inference/pricing) on 2026-09-28. It bounds this run's usage equivalent; it is not an invoice. The single public sentence can establish API availability and a directional latency/quality observation, not comparative superiority. Human review on a broader representative corpus is required before changing the default.

### First bounded GCP observation (2026-09-28)

On the single fixed public sentence, Small and Medium both returned the same faithful English caption, with observed response times of 570 ms and 499 ms. The GLM 5.3 request returned HTTP 200, but its response did not pass the comparator's text/usage validation; the run stopped without a retry. This does not isolate whether answer text or usage metadata caused the failure. GLM is therefore unvalidated for Caption Bridge's live caption path, and Small remains the default. The private owner-only ledger retains the two public responses and reported token counts. These individual timings do not predict typical latency.
