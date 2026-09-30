# Translation model selection

Caption Bridge uses Voxtral for live speech transcription and Mistral's chat API for text translation. The translation selector affects only text translation. Spoken readback remains on its separate TTS path.

Mistral Medium (mistral-medium-latest) is the starting translation choice for new sessions in this draft while GLM live reliability remains unproved (issue #68). The selector also offers Mistral Small (mistral-small-latest) and Mistral-hosted Z.ai GLM 5.3 (zai-glm-5-3), labeled experimental preview. Selecting GLM shows a concise warning that captions may be missed or delayed. The selected model remains visible while listening, including after refresh. An operator-configured default, if different, is also listed. Availability depends on the account and Mistral's current model catalog. A model being listed does not establish better caption quality or low enough latency for live use.

Choose a translation thinking level before Start, or change it in Settings. **Provider default** leaves the API reasoning setting unspecified. Small and Medium use a 200-output-token limit and 10-second request deadline; GLM uses a 4096-token limit and configurable 20-second request deadline after repeated thinking-only and timeout failures. **High reasoning (experimental)** sends Mistral's `reasoning_effort="high"`; it uses 1024 tokens for Small and Medium and 4096 for GLM. It can change cost, latency, and wording. A response with no answer text fails that caption without an automatic retry. A response ending with `finish_reason=length` and some answer text also fails without retry or spoken readback (`provider_output_limit`): fluent text can still be cut off before a qualification or negation. A token-limited quality repair cannot replace the original flagged caption. High is offered only for the three listed models; an unrecognized configured default uses Provider default.

Mistral Vibe labels its highest control “Max” but maps it to `reasoning_effort="high"` on the Mistral backend. We label the API request value here, rather than claiming Mistral-hosted GLM has a separately verified native Max setting. See [Mistral Vibe's request mapping](https://github.com/mistralai/mistral-vibe/blob/7c19608af06f6c61d63f8f7a5c3430da73fba2ab/vibe/core/llm/backend/mistral.py#L257-L262). Two public-text High requests to Mistral-hosted GLM returned captions, but this does not establish that High improves translation quality or live-audio readability.

Choose a model before Start, or change it in Settings during a session. A live change applies to the next finalized source segment. Translations already running, including their retries and quality-repair request, keep the model and thinking level selected when their segment was created. A provider response with no answer text marks that caption as failed without an automatic retry. Other failed provider requests follow the existing caption failure path; the selector does not fall back to a different model without a user choice.

The private JSON transcript records each segment's source text, translated text, target language, selected translation model ID, thinking level, output-token limit, revision, prompt version, creation/completion timestamps, and quality result. It also records model or thinking-level changes with a timestamp and first affected segment number. When Mistral returns them, the transcript records its response model ID, last finish reason, and the sum of reported prompt and completion tokens from translation and repair responses. These fields may be absent for failed requests, legacy sessions, or providers that do not report them. The configured default in config.translate_model is not a substitute for each segment's model field.

The -latest IDs are aliases and can point to a newer release later. A response model ID may itself still be an alias, so these records do not guarantee a pinned model build. For a controlled quality comparison, keep the source text, target language, glossary, prompt version, and model IDs alongside the observed latency and human quality judgment. The app does not currently run an automatic quality benchmark when switching models.

No model or thinking choice is saved in browser storage. A fresh session starts from the server's configured default. The journal persists the session's model changes and per-segment metadata for interrupted-session recovery; old journals retain unknown model metadata rather than guessing.

References: [Mistral model lifecycle](https://docs.mistral.ai/inference/model-lifecycle), [GLM 5.3 model](https://docs.mistral.ai/models/zai-glm-5-3), [Mistral chat API](https://docs.mistral.ai/api).

## Bounded public-text comparison

Run python -m scripts.compare_translation_models on GCP for an offline plan. It prepares one fixed Korean-English public caption with the production translation prompt for all three listed models and makes no provider calls by default.

The one-case runner requires --live, --key-stdin or a process environment key, --ledger, --prior-cost-upper-usd, and a budget allowance. Its --project-ceiling-usd defaults to $1 and must be set explicitly when a different total has been approved; --max-spend-usd defaults to $0.04. It sends at most three sequential Chat Completions requests with the same Provider-default output limits as the app: 200 tokens for Small and Medium, 4096 for GLM. The current plan's conservative upper bound is about $0.0498, so the default $0.04 added allowance fails closed; a live run requires a separately approved ceiling and explicit `--max-spend-usd 0.05`. There is no retry. It durably reserves a conservative upper bound before each request and will not replay an existing ledger. The private ledger contains the public source/output text, model IDs, reported token usage, latency, and automated quality signals. Keep it outside the repository with owner-only permissions. The CLI prints only counts, bounds, and static failure codes.

The reservation uses twice the standard token rates listed by [Mistral pricing](https://docs.mistral.ai/inference/pricing), checked again on 2026-09-29. It bounds this run's usage equivalent; it is not an invoice. The single public sentence can establish API availability and a directional latency/quality observation, not comparative superiority. Human review on a broader representative corpus is required before changing the default.

### First bounded GCP observation (2026-09-28)

On the single fixed public sentence, Small and Medium both returned the same faithful English caption, with observed response times of 570 ms and 499 ms. The GLM 5.3 request returned HTTP 200, but its response did not pass the comparator's text/usage validation; the run stopped without a retry. That first run did not isolate whether answer text or usage metadata caused the failure. The follow-up below identified the model-specific output limit issue. Small was the default at the time. The private owner-only ledger retains the two public responses and reported token counts. These individual timings do not predict typical latency.

### Follow-up GCP evidence (2026-09-29)

A bounded GLM probe returned valid answer and usage data with both thinking and text chunks. A second public caption then exposed the actual failure: with Provider default and a 200-token limit, GLM used all 200 completion tokens for thinking, returned no answer, and ended with `finish_reason=length`. Sending `reasoning_effort="none"` to this hosted model returned HTTP 400. Raising the output limit to 1024 returned a faithful caption, with 372 completion tokens including thinking. At that checkpoint, the selector gave GLM 1024 tokens at Provider default, while Small and Medium keep 200.

In a later six-case public Korean-to-English comparison, GLM with 1024 tokens and Small with 200 both produced a caption for every case, with no automatic quality flags. GLM preserved the trailing "but" on one paused clause that Small closed as a sentence. Other outputs showed no clear quality advantage; a technical-term rendering was less faithful to "synthetic model." Median API latency was 1,052 ms for GLM versus 658 ms for Small, and completion usage was 1,155 versus 48 tokens across these six cases. These small samples are directional, not a performance guarantee. Two GLM High requests also returned captions, with differing response structures.

At this checkpoint, the owner preferred GLM 5.3 as an eventual default if representative quality, latency, reliability, and real-audio acceptance supported it. These public-text checks did not meet that release gate, so Mistral Small was still the default. The private GCP ledgers contain only public final answers and structural metadata, not thinking text. The cumulative conservative usage-equivalent upper after these checks was $1.1480764 under the owner's revised $1.15 maximum; it is not a bill.


### Public recorded-audio check (2026-09-29)

Two Korean [FLEURS](https://huggingface.co/datasets/google/fleurs) test clips (12.48 and 12.36 seconds, CC BY 4.0) were streamed on GCP through Caption Bridge's Voxtral Realtime transcription adapter. Each resulting transcript was translated once with Small and once with Mistral-hosted GLM 5.3 using the production prompt, Provider default thinking, and the model-specific output limits. All six provider requests completed without retry; both models returned usable English captions.

| Clip | First ASR text | Small translation | GLM 5.3 translation |
| --- | ---: | ---: | ---: |
| Bridge clearance | 4.2 s | 741 ms, 35 completion tokens | 2,742 ms, 793 completion tokens |
| Dark matter | 5.5 s | 684 ms, 20 completion tokens | 955 ms, 243 completion tokens |

The first ASR transcript fused a Korean phrase meaning “under the bridge” into a different word. Both translators recovered the bridge-clearance sense; GLM phrased it more naturally. On the second clip, their translations were equivalent. GLM took longer and used more output tokens on both clips. Combined with the six mixed public-text cases above, this does not establish enough quality benefit to change the translation default from Small. High reasoning was not used in this audio check.

This tested recorded public audio, the real ASR adapter, and the production translation prompt. It did not exercise microphone hardware, browser rendering, spoken output, live model switching, or human readability. The added conservative usage-equivalent reservation was $0.0615488, bringing the cumulative upper to $1.2096252 under the owner's $1.25 ceiling. It is not an invoice.

### Targeted public-text follow-up (2026-09-29)

Two new synthetic Korean academic captions tested “synthetic data” with negation and an estimate falling from 0.15 to 0.08 while its confidence interval still included zero. On GCP, the production translation prompt with Provider-default thinking produced four answer texts without retries, truncation, or automated quality flags. Small and GLM both preserved the negation and numbers. GLM exactly matched the prepared reference on the synthetic-data sentence; Small conveyed the meaning but changed the singular model to plural. Their numerical captions were equivalent.

In these two cases, Small took 698 and 592 ms with 38 completion tokens total; GLM took 686 and 835 ms with 336 completion tokens, including thinking. Across the eight public text cases now tested, median API latency was 658 ms for Small and 1,012.5 ms for GLM, with 86 versus 1,491 completion tokens. These small, selected samples do not measure live readability or establish a reliable quality advantage. GLM's earlier mistranslation of “synthetic model” remains relevant. Small was still the default at this checkpoint; the later owner decision below changes the draft default.

The follow-up sent only these public synthetic sentences from GCP. It used no microphone, TTS, or personal caption content.

<!-- two-case-quality-check-20260929 -->


### Owner-selected draft default (2026-09-29)

The owner directed the draft to start new sessions with Mistral-hosted GLM 5.3, using Provider default thinking. The draft cap at this checkpoint was 2048 tokens after the later live preflight below. Small and Medium 3.5 remain selectable before Start and during a session. This is an explicit product preference, not a finding that GLM consistently translates live captions better: eight selected public-text pairs and two public recorded-audio clips showed mixed wording, higher median latency, and much higher reported completion-token use. The draft still needs real-session readability and spoken-output judgment, representative quality and usage review, and release approval.

An existing `MISTRAL_TRANSLATE_MODEL` setting in an operator's `.env` continues to override the code default. The new example configuration selects GLM; rollout must check any existing environment override rather than silently replacing a deliberate model choice. The selected and provider-reported model IDs, thinking level, output cap, and usage remain in each private caption record for later analysis. This default change used no additional provider calls.

Mistral's [Vibe model configuration](https://docs.mistral.ai/vibe/code/cli/configuration) currently recommends Medium 3.5 for that separate product and lists GLM 5.3 as another model. Mistral describes [GLM 5.3](https://docs.mistral.ai/models/zai-glm-5-3) as a third-party public preview. Caption Bridge's choice does not assert that GLM is Mistral's official default.


### Isolated Mac preflight and output-cap adjustment (2026-09-29)

An attended Chrome session on the physical Mac ran the draft GLM default with a 90-second automatic stop. The microphone picked up unrelated background audio while public Korean clips were played, so this was **not** a valid Korean caption or human spoken-output acceptance run. The session was stopped, its unexported isolated test journal was removed locally, and no caption or response text was copied to GCP or the repository.

Content-free evidence from that session: seven finalized segments; six GLM translations completed; one returned no answer text after consuming its full 1024 completion-token allowance. The failed segment did not retry. No translation retry error or quality-repair attempt was logged. The app did synthesize and play speech, but the human readability/playback gate remains open. The bounded usage-equivalent increment was $0.0728372, bringing the project upper bound to $1.3116381 under the approved $1.50 ceiling; this is not a bill.

At this checkpoint, the draft allowed up to 2048 output tokens for GLM, including Provider default and High, while Small/Medium limits remain unchanged. This is a mitigation for the observed thinking-only truncation, **not** proof that GLM always returns an answer or meets live latency/cost expectations. Any GLM response without answer text still fails that caption without an automatic retry. Re-run bounded public-audio and human acceptance on the new exact candidate before promotion, with unrelated Mac audio stopped.
<!-- glm-live-preflight-20260929 -->

### Public API check of the 2048-token cap (2026-09-29)

The GCP one-case comparator ran at code head f2f41b8 with its production prompt and then-current output limits: 200 for Small/Medium and 2048 for GLM. Three sequential public Korean-to-English requests completed with answer text, valid reported usage, and no automated quality flags. Small took 585 ms and 11 completion tokens; Medium took 568 ms and 11; GLM took 711 ms and 81. This short example did not approach 1024 tokens, so it verifies that the Mistral API accepts the new request setting but does not establish that the earlier thinking-only failure is fixed for difficult live fragments.

The owner-only GCP ledger reserved $0.0317117 at twice published rates, bringing the conservative project usage-equivalent upper to $1.3433498 under the approved $1.50 ceiling. This is not an invoice. No microphone, personal caption text, or TTS was used in this follow-up. Live Korean and human readback acceptance remain open.
<!-- glm-2048-public-api-check-20260929 -->


### GLM reliability preparation after a private Mac session (2026-09-29)

The owner used the isolated Mac preview and exported a private session. Content-free review found 16 GLM translation attempts: 13 completed, two reached the existing 10-second translation deadline, and one returned no answer after exactly using its 2048-token output allowance. Medium 3.5 is working in the owner's separate current session. No private source or translation text from the export is copied into this repository.

This GCP-only draft raises the GLM output allowance to 4096 tokens and gives GLM a configurable 20-second request deadline. Small and Medium retain the 200-token Provider-default allowance and 10-second deadline; their High allowance remains 1024. The cap and deadline are independent: a larger cap alone would not help a request still cut off at 10 seconds. The draft also records the provider's content-free finish reason in each segment's private export and recovery journal, alongside the existing selected model, requested output cap, and token usage. A future no-answer result can be distinguished as output-limit truncation when the provider reports `finish_reason=length`. It does not expose thinking text.

These changes are mitigations inferred from one private session, not a measured GLM reliability fix. A higher cap increases possible token use, and a longer deadline may delay ordered captions. The app still does not retry a thinking-only answer automatically or switch the requested model silently. Provider-free tests cover model-specific budgets, timeouts, and preserved diagnostic metadata. The candidate needs a bounded live GLM run and a human quality/latency review before any Mac rollout.
<!-- glm-private-session-preparation-20260929 -->

### GCP public-text check of the 4096-token candidate (2026-09-29)

With the owner's added test allowance, a private GCP ledger reserved a conservative $0.1234840 for three no-retry GLM 5.3 requests at the draft's 4096-token output cap and Provider-default thinking. For extra caution, the budget guard treated the full previous $1.50 ceiling as spent, so the accounted upper became $1.6234840 under the newly approved $1.65 ceiling. This is a usage-equivalent bound based on twice Mistral's published standard rates, not a bill. Only public synthetic Korean and French academic text was sent; no Mac session text, microphone audio, or TTS was used.

All three requests returned HTTP 200, answer text, and `finish_reason=stop`. They took 812–1326 ms, used 124–218 completion tokens, and had no automated quality flags. Manual inspection found the three captions faithful to their source text. The cases were much shorter and easier than the private Mac request that consumed all 2048 tokens without an answer, so this confirms API compatibility and basic quality but does not establish that the intermittent no-answer or 10-second timeout is fixed. The GCP-only draft remains unpromoted; a later isolated live-session check is needed before Mac rollout.
<!-- glm-4096-public-text-check-20260929 -->


### Reliable startup decision and acceptance boundary (2026-09-30)

Issue #68 makes Medium the draft startup choice until a representative exact-candidate GLM run passes the physical acceptance gate. The previous GLM preference was conditional on working well; the 13/16 private-session completion result and easy public follow-up do not meet that condition. The Medium 629/629 result supports a reliability choice in those observed sessions, not a controlled accuracy ranking. GLM remains selectable, including live, with its 4096-token cap and 20-second deadline; no automatic model fallback is added.

An explicit `MISTRAL_TRANSLATE_MODEL` environment value still wins. In particular, the previously observed Mac Small override will keep selecting Small until the operator deliberately changes it during an approved rollout. Merely upgrading code must not erase that choice. Browser storage does not save a model preference: refresh restores the server session selection; New Session restores the server-configured default and Provider default thinking. Requested/resolved model, thinking level, cap, profile and reported usage stay in private export/recovery records.

The GCP truncation regressions first reproduced two failures: nonempty token-limited answers were accepted as done, and a fluent truncated repair replaced the original flagged answer. The draft now rejects the first without retry/TTS and rejects the replacement in the second. It retains content-free finish reason and reported usage; ordered delivery proceeds to the next segment. This addresses an acceptance gap without claiming that GLM's intermittent provider failure is cured.

No live provider, microphone, TTS service, physical browser or production run was made for this update. The exact remaining human/device record is in [Mac acceptance](mac-acceptance.md#draft-integration-64-and-startup-choice-68). Issue #68 remains open for physical judgment and reviewed release/rollout; PR #64 remains draft.

GCP verification for this update: 291 Python tests passed (one existing skip), 28 Chromium browser contracts passed, Ruff/JavaScript/diff checks passed, and quality/segmentation/1,000-segment resilience/full-pipeline benchmarks passed with synthetic providers. The additional WebKit run could not launch because the existing GCP host lacks required shared libraries; its 28 setup errors are environment failures, not passed browser checks. No host packages were installed. Earlier WebKit/native Safari evidence applies to earlier runtime code and does not validate this changed UI.
