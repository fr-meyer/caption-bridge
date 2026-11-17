# Translation catalogue source evidence (#96)

Source implementation completed in the exclusive E worktree. Not a deployment or live qualification claim. No authenticated account request, inference, capture, device operation or provider spend occurred. Only unauthenticated official public model cards were read.

## Catalogue and lifecycle

Account enumeration is metadata-only and separate from inference. Reconciliation checks completion_chat, lifecycle, account deprecation timestamps, duplicate/conflicting cards, verified aliases and explicit execution policies. Unknown compatible families remain visible and disabled with a concrete reason. Embedding/OCR/transcription/TTS-only endpoints are excluded from translation choices. Account metadata cannot independently prove lifecycle or live quality.

Verified official cards (https://docs.mistral.ai/models/):

| Card suffix | Literal model names / alias | Current status | Source output cap |
| --- | --- | --- | --- |
| mistral-large-4-0 | mistral-large-4, mistral-large-4-0, mistral-large-latest | GA | 4096 |
| mistral-small-4-0-26-03 | mistral-small-2603, mistral-small-latest | GA | 200/default, 1024/high |
| mistral-medium-3-5-26-04 | mistral-medium-3-5, mistral-medium-latest | Deprecated | unavailable |
| zai-glm-5-3 | zai-glm-5-3 | GA | 4096/default or high |
| zai-glm-5-3-flash | zai-glm-5-3-flash | GA | 4096/default |
| deepseek-v4-flash-1017 | deepseek-v4-1-flash-1017 | GA | 4096/default |
| codestral-25-08 | codestral-2508, codestral-latest | GA | 200/default |
| ministral-3-3b-25-12 | ministral-3b-2512, ministral-3b-latest | GA | 200/default |
| ministral-3-8b-25-12 | ministral-8b-2512, ministral-8b-latest | GA | 200/default |
| ministral-3-14b-25-12 | ministral-14b-2512, ministral-14b-latest | GA | 200/default |
| voxtral-small-25-07 | voxtral-small-2507, voxtral-small-latest | GA | 200/default |

Public refresh of all 11 cards passed on 2026-11-17. Medium's precise current model-card Deprecated badge supersedes older capability guides mentioning its alias. Startup remains Medium, visibly unavailable; no silent family switch. Historical Large 3 and GLM 5.2 remain deprecated, not revived through replacement cards. Magistral Small 1.2 card was also checked and is deprecated. Other returned account chat families without verified evidence remain explicitly unknown/unavailable, not silently eligible. The catalogue does not claim these 11 cards exhaust future account inventories.

Explicit refresh runs bounded public and account metadata in parallel with sibling cancellation: public requests have four-second per-request limits, three concurrent requests, 3MB response ceiling, eight-second aggregate deadline; complete refresh ten seconds. Success/failure cooldown is five minutes. Disconnect cancels ownership. Public evidence has a seven-day freshness ceiling (initial packet expires 2026-11-24); successful public refresh renews it. Refresh emits a catalogue-only event, not a player-resetting session snapshot.

Execution policies are application budgets, not provider capacity or verified live latency/cost. Large uses a bounded 20-second source timeout; existing other timeout policies remain. No undocumented high effort is sent for newly included families. Account reasoning capability is required for offered high settings. Observable reasoning-only/refusal, empty capped output, partial truncated output, ordinary empty output, timeout and provider errors have distinct fixed reasons. Internal reasoning is never extracted or retained. Echoed requested aliases are not claimed as resolved versions. Future dispatch rechecks eligibility without fallback; already dispatched work preserves its identity.

## Executed verification

- Full provider-free Python source/regression run: **715 passed, 3 skipped, 22 subtests passed**; two warnings (existing malformed-export fixture and Starlette/httpx deprecation).
- Expanded original 20-case backend matrix now covers 11 models × 5 response states: **55 passed** (included above).
- All Node suites: **20 passed**, including six catalogue/UI control regressions.
- Ruff over app, tests and browser_tests; JS syntax; git diff whitespace checks: passed.
- Browser suite attempted: **67 setup errors**, no browser assertions executed. Both ambient/default and explicit channel attempts select unavailable system Chrome. The owned downloaded Chromium also lacks host runtime libraries (glib, NSS, X11, Cairo, Pango, ALSA and others). No prohibited system installation was performed. Four new catalogue Playwright cases are collected but not claimed passed.

## Remaining external evidence

1. Dependency-backed browser execution on the existing hosted runner, with its supported browser runtime. Exact command after the existing locked dependency/browser setup:       uv run pytest browser_tests --browser chromium -q --tb=short

   Focused new coverage: uv run pytest browser_tests/test_translation_catalogue.py -q --tb=short
2. Independent review and exact integrated-head existing CI, owned by coordinator. No CI edits or GitHub publication in E.
3. Separately authorized actual account metadata/SDK qualification and bounded live acceptance. Source fixtures do not establish account entitlement, prices, model answer quality or low-latency suitability.

Disposable .venv-e and .tools-e are untracked and excluded from source commits. Lockfiles and CI workflows are unchanged.
