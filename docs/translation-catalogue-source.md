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

## Independent review repair (after 1ef547)

All four ordinary findings addressed: connection-owned renewal starts only after an explicit successful metadata refresh, runs before TTL at 75%, and has a 30-second minimum retry interval (shorter proportional intervals only for synthetic TTL tests). It emits catalogue-only UI freshness/failure state, cancels on ownership loss, and never starts capture/inference. Cancelled unpublished refresh restores its previous attempt marker so a replacement owner is not locked out. Completed failures retain cooldown. Strict alias eligibility now requires account-corroborated target, same family/variant and identical explicit target execution contract; a direct alias without target evidence is disabled. Future dispatch validates both model and saved effort; capability revocation fails with model_effort_unavailable, never silently downgrading.

Account listing now uses a fixed HTTPS metadata GET, four-second request timeout inside the catalogue aggregate deadline, zero application retries/redirects, trust_env=False and a 2MB streamed ceiling before JSON deserialization; 2000-row cap remains. Public renewal checks literal model/alias names in the official card's serialized names declarations as well as the lifecycle badge. Changed identity/alias declarations fail closed. Historical deprecated entries (including Medium) remain disabled and are never reactivated by a current replacement card; precise Medium deprecation provenance is retained. The registry remains intentionally non-exhaustive; unknown account chat families remain visible/disabled.

Repair tests cover cross-family/missing-target/missing-or-changed execution contracts, revoked effort, immediate retry after cancellation, successful renewal beyond TTL, failure UI events and no refresh after disconnect, changed public identity, redirect/no-retry/byte ceiling. Full source pytest: 726 passed, 3 skipped, 22 subtests; Node: 20 passed. Browser execution remains the previously documented hosted-runner gate, not rerun locally.

Initial repair reruns exposed obsolete mocks and fixture issues; fixed and rerun. One obsolete empty-key SDK mock reached the new HTTP adapter and failed locally while encoding an empty Bearer header; no authenticated request or inference occurred. Missing keys are now rejected before transport construction, and all adapter regressions use mock transports.

## Current-card provenance repair (after 82faf63)

Replaced the global backslash stripping/names union with JSON decoding of the actual Next Flight script envelope and records. Verification binds the requested official URL to the canonical root path and dynamic slug, follows only the canonical children outlet to its __PAGE__ component, and inspects the unique current-card header. The names declaration must occupy the actual title-row sibling identity slot; all required snapshot/alias names must appear together in that one declaration. Lifecycle must be the unique status on the same header. Scoped lazy render references are decoded with cycle/depth protection; unrelated records are never searched for substitute identities. Missing, ambiguous, changed or unsupported schema fails closed.

Three reduced fixtures were extracted offline from previously saved official HTML, retaining actual route/page/header records and escaped Flight framing: Large current, DeepSeek lazy-name current, and Magistral deprecated. Fixture README records source URLs, original SHA256 and reduction method. Negatives cover incidental navigation/history/other-card identities, header navigation, split declarations, wrong canonical path/slug, conflicting cards/statuses, missing/unscoped headers, missing lazy identity records and malformed escaped JSON. Positive fixtures exercise current, deprecated and newly declared same-card identity pairs. No new public or account network requests were made for this repair.

All eight locally saved active model cards were also checked offline against the new decoder and matched their existing registry identities; this is retained-fixture evidence, not a new current inventory/qualification claim. Renewal/transport/alias execution/effort/cancellation fixes are unchanged. Hosted browser and separately authorized account/live qualification remain external gates.

Final repair gates: focused lifecycle **32 passed**; full provider-free Python **747 passed, 3 skipped, 22 subtests passed** (two existing warnings); Node **20 passed**; Ruff, JS syntax and diff whitespace passed. Browser gate unchanged.

## Synchronous verification work budget (after 6b5722c)

Every verify_current_card attempt now shares one 4096-unit synchronous budget across Flight record scanning, canonical route/outlet traversal, both page/header render traversals, identity-reference resolution and final declaration checks. Each render occurrence/edge spends before expansion, including repeated references; class-string tokenization is length-charged before splitting. The existing reference cycle/depth bound remains, with an additional inline nesting ceiling and direct verifier input-length guard. Overflow raises a fixed ValueError and cannot renew lifecycle metadata. This CPU bound does not depend on an asyncio timeout or memoization. Duplicate placements are still visited and remain ambiguous, not silently deduplicated.

Deterministic regression: the review's compact 16-record branching DAG is passed through the actual verifier and rejects within at most 4097 budget-spend calls; no exponential enumeration or giant graph is run. Tests additionally check shared budget identity across both traversals, late aggregate exhaustion, reference cycle/depth, accepted harmless repeated references and rejected repeated header placements. All original 32 lifecycle tests remain; focused suite now **37 passed**. Full locked owned-environment provider-free pytest: **752 passed, 3 skipped, 22 subtests passed**, two existing warnings. Node: **20 passed**. Ruff, JS syntax and diff whitespace passed. Eight previously saved official active pages still pass offline under the budget. No network/provider/capture/device/system/CI/GitHub operations occurred; other prior repairs and external evidence gates are unchanged.

## PR98 hosted failure repair (after 69a9636)

Hosted evidence identified evaluation preconditions, not a reason to weaken production gates: standalone fake-only entrypoints lacked the eligible catalogue that pytest's old autouse fixture supplied. Both offline runners now enter an explicit synthetic catalogue scope and explicitly select Small in their local AppConfig. The scope reconciles synthetic active public evidence, alias+snapshot account metadata and existing real execution policy; marks its source synthetic-offline-fixture; uses a frozen fixture clock; and restores the original process catalogue even on exceptions. Full-pipeline fake websocket snapshots share that scoped cache and restore their prior cache separately. No real account enumeration, lifecycle promotion, production default/effort change or validation bypass is involved. Evaluation runs are serialized, as documented by the helper.

Browser baseline now explicitly declares its synthetic fresh metadata rather than accidentally displaying stale guidance. Fresh guidance is legitimately visible: it states cached verification and cautions that source tests are not live qualification. The two startup/new-session cases assert that text instead of hiding it; all existing model-selection, live acknowledgement, reconnect and new-session identity assertions remain. Two added stale/failed-metadata cases assert that accurate refresh-required/failure guidance and disabled choices remain visible, without starting capture/inference. The historical Medium-enabled browser baseline is explicitly synthetic, not production lifecycle evidence.

Executed with MISTRAL_API_KEY unset, using the existing owned locked environment:
- python -m scripts.resilience_soak --segments 1000 --json: passed=true; 1000 delivered, 970 done, 20 injected timeouts, 10 injected exhausted failures; 1120/1120 fake calls, ordered, zero pending/remaining tasks.
- python -m scripts.full_pipeline_scenario --json: passed=true; six segments, four done, one injected timeout, one injected failure; seven fake translation and five fake TTS calls; export statuses preserved; zero remaining tasks/jobs.
- Translation benchmark with hosted thresholds (FPR<=0.05, recall>=1, exact reasons): 26 cases, FPR=0, recall=1, zero reason mismatches.
- Segmentation benchmark with hosted thresholds (zero unexpected/delayed boundaries, <=4500ms): passed=true; zero boundary mismatches.
- Full provider-free Python: 757 passed, 3 skipped, 22 subtests passed; two existing warnings. Node: 20 passed. Whole-repository Ruff, JS syntax and diff whitespace passed.
- Browser: 69 cases collected. Assertions were not locally rerun because the already-owned Chromium still lacks host glib/NSS and other runtime libraries (read-only ldd confirmation); no install attempted. Actual hosted browser execution remains required.

Five dedicated unit cases prove entrypoints succeed with an initially empty cache, restore it without creating a real provider, retain unchanged deprecated Medium default/lifecycle and fail-closed external validation, restore scope on exceptions, and declare consistent synthetic browser startup/new-session freshness. No network/provider/audio/device/system/GitHub/CI/native mutations occurred in this repair. Parent owns integrated-head review/publication/hosted rerun; old/new native helper qualification remains unclaimed.

## Interrupted evaluation teardown repair (after 0d5b7aed)

Full-pipeline scenario teardown now puts every synchronous global restoration in an unconditional nested finally. The original body/first cleanup exception (including CancelledError) is retained and re-raised, while other teardown stages are still attempted. Dispatcher drain and TTS stop have seven-second stage ceilings; interrupted owned translation/TTS workers are explicitly cancelled and given at most two seconds to settle. Manager timer cancellation is attempted independently. This neither scans/cancels unrelated event-loop tasks nor converts a failed cleanup into a passing report.

Four deterministic actual-scenario regressions inject cancellation or an exact RuntimeError instance at final dispatcher drain or TTS stop. Each adds an owned sleeping worker, then proves it is cancelled/settled, every preexisting model/WS/reconnect binding is restored by identity, no new scheduled tasks remain, the original cancellation/exception propagates, and no real provider can be constructed. Existing synthetic helper scope and production app files are unchanged.

Final exact evidence: focused pipeline suite 8 passed; full provider-free Python 761 passed, 3 skipped, 22 subtests passed (two existing warnings); Node 20 passed; whole-repository Ruff, JS syntax and whitespace checks passed. Actual fake-only CLI pipeline passed with 7 translation/5 TTS calls and zero remaining workers; 1000-segment soak passed with 1120/1120 fake calls and zero remaining tasks. No network/provider/audio/device/system/browser/native/CI/GitHub operations occurred. Hosted browser and prior external qualification gates remain unchanged.
