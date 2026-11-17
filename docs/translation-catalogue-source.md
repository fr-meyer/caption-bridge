# Translation catalogue source checkpoint (#96)

This is an **incomplete integration candidate**, not E1–E4 acceptance or a deployment recommendation. No account metadata request, inference, credential loading, capture, playback or device operation was performed. Additional provider spend: US$0.

## Implemented path

The existing provider boundary now exposes explicit metadata-only enumeration. An explicit idle/drawer refresh command fetches it with a five-second timeout, single in-flight task and five-minute success/failure cooldown. Disconnect cancels the owned refresh; refresh does not replace the session snapshot or disturb playback. Catalogue entries preserve disabled reasons, requested identities and historical session revisions. Stale metadata cannot authorize new selections or future dispatches. Configured models do not bypass eligibility. Existing ASR/TTS/startup-family settings remain unchanged.

Reconciliation enumerates all returned account models, including unknown hosted families. It checks text-chat capability, independent lifecycle evidence and execution policy, deduplicates declared families and prefers verified official aliases (including aliases listed on account cards). Without an alias it selects the newest verified release. Unknown/conflicting lifecycle and unknown execution contracts remain visible but disabled. Alias target metadata is separate from provider-resolved provenance. An echoed requested ID is not retained as a resolved-version claim.

Large has a bounded 4096-token/20-second source policy, independent of the GLM timeout. Medium/Small ordinary requests remain 200 tokens, high 1024; GLM retains 4096. These are bounded source policies, **not demonstrated live quality/latency fixes**. Length-capped empty and partial responses fail as output-limit errors before ordinary empty classification. Refusal, observable reasoning-only, unsupported/unavailable errors have distinct fixed reasons. Reasoning content is never extracted or retained. Future dispatches fail closed after catalogue expiry/retirement, without fallback. In-flight work keeps its dispatch identity.

## Public evidence and material conflict

Read unauthenticated official documentation on 2026-11-17:

- https://docs.mistral.ai/api/endpoint/models: account availability enumeration, not lifecycle proof.
- https://docs.mistral.ai/models: current featured Large 4, Small 4 and GLM 5.3; explicit deprecated/retired section.
- https://docs.mistral.ai/models/mistral-large-4-0: GA, chat completions.
- https://docs.mistral.ai/models/zai-glm-5-3: GA third-party hosted model, chat completions.
- https://docs.mistral.ai/inference/conversations/function-calling: explicit official Large/Small aliases. Its Medium alias still points at Medium 3.5, while the overview lists Medium 3.5 under deprecated/retired models.

**Medium is intentionally preserved as startup identity but marked lifecycle-conflicting.** Neither silently changing the family nor treating its current alias target as verified would respect the task. The coordinator must reconcile authoritative current alias-target/lifecycle evidence before enabling it. This does not change an accepted installation.

Public pages were partly truncated and are not an exhaustive lifecycle inventory. Consequently new account families can be enumerated but remain disabled with a concrete reason until their lifecycle and execution policy are verified. The checked public evidence expires 2026-11-24 UTC. There is no invented catalogue-wide active fallback.

## Verification actually executed

- Stdlib unittest catalogue suite: **9 tests passed**, including parameterized subcases for capability/lifecycle/policy states, alias/no-alias, duplicate/conflicting metadata, new hosted families, stale/failure refresh, retirement, timeout and cancellation.
- Node DOM-control unit suite: **5 tests passed**, covering disabled reasons, restored retired identity and metadata-driven thinking capabilities. These are JS unit tests, not native browser evidence.
- Python compileall for changed application/new tests: passed.
- node --check app/static/app.js: passed.
- git diff --check: passed.

Initial catalogue test had an incorrectly constructed capability fixture; corrected fixture and rerun passed. Initial Node test string escaping failed before execution; repaired and rerun passed. No failed run is claimed as passed.

## Remaining gates / do not call #96 complete

1. The available Python runtime lacks pytest and application dependencies; installs were prohibited for this lane. The added 20-case provider execution matrix and four Playwright cases are **written but not run**. Full existing provider/translation/session/browser regressions still need execution in the coordinator's authorized dependency-backed/CI environment.
2. Existing tests assume the historical hard-coded four-model catalogue and fabricated echoed-alias resolution. They need explicit synthetic current account/lifecycle fixtures and updated assertions. This branch is not claimed compatible with those old test assumptions or ready to merge.
3. Complete the verified public lifecycle/execution-policy inventory, especially newly hosted families (GLM Flash/DeepSeek and other compatible account results). Unknown contracts are surfaced rather than guessed or falsely qualified. This is a real remaining E1 acceptance item, not merely live E6 qualification.
4. Verify actual account catalogue/SDK behavior separately, without inference, only under the coordinator's separately recorded metadata authorization. No account entitlement is claimed here.
5. Independent review, exact-head dependency-backed regressions/CI, and parent integration/publication remain outstanding. No GitHub write or release was attempted.
