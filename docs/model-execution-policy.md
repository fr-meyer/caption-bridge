# Translation lifecycle, privacy and alias execution policy

This is source policy, not account, live-provider or confidential-content
approval. Existing catalogue/cache/refresh/admission architecture is retained.
The configured Medium default and all request budgets/deadlines are unchanged.

## Vendor lifecycle is not privacy consent

The current-card verifier distinguishes literal `GA`, `Public Preview`, `Labs`,
`Deprecated` and `Retired` badges. Normalized states are respectively `active`,
`preview`, `labs`, `deprecated` and `retired`. Conflicting badges fail closed,
including GA plus Preview. Current-card identity binding, bounded parsing,
public/account freshness, cancellation and independent account capability
checks remain required. Preview/Labs stay refreshable, but never become eligible
merely because an account advertises `completion_chat`.

As retrieved on 2026-11-24, the [training policy][training] explicitly excludes
Labs/Public Preview from ordinary training opt-out, regardless of subscription;
the [ZDR policy][zdr] independently excludes them. The current [DeepSeek card][deepseek]
says **Public Preview**, not GA. Its reviewed output budget is not permission
to send private captions. Translation catalogue snapshots and choices retain
`vendor_status` and `privacy_status`; DeepSeek remains disabled with
`privacy_preview_excluded`. A stale generic-active cache cannot override the
newer reviewed Preview restriction. Any graduation needs a source-policy review.

The product has no reviewed public-only content route or applicable written
contract exception. It therefore blocks Preview/Labs translation entirely, not
only when an invented consent checkbox is unset. There is no privacy waiver,
plan-upgrade shortcut, user-consent toggle or automatic fallback. GA instead
reports `account_terms_unverified`: a GA badge does **not** establish the
account's retention, opt-out, region, contract or private-content approval.

## GLM names, targets and complete request parity

The complete [GLM 5.3 Markdown card][glm] declares exactly `zai-glm-5-3`,
`zai-glm-5` and `zai-glm-latest` as GA. The two aliases belong only to the
standard GLM variant. [GLM Flash][flash] is a separate GA variant; its card
does not declare a rolling alias. No Flash/DeepSeek `*-latest` name is invented.

Public name existence is not account resolution. Enable an alias only with
fresh account metadata resolving it to a known concrete, active target in the
same family **and variant**, with an identical reviewed execution contract.
An alias-to-alias chain is not a resolved version. Unknown/deprecated targets,
conflicting targets, missing capabilities and changed contracts remain disabled.
An echoed requested alias is not response-resolution evidence.

The registry records both documented GLM aliases with the dated standard GLM
execution contract (default/high effort, 4096 output-token ceiling). The shared
dispatcher routes these exact selectors through the same configured GLM deadline,
not the shorter ordinary-chat deadline. The requested selector is preserved;
there is no silent target substitution. Missing actual account resolution still
keeps aliases unavailable. No account call, real alias resolution, provider
quality or live acceptance is claimed by this offline source implementation.

Use the existing [provider evidence](provider-evidence-20261124.md) for captured
public declarations and the unresolved account/contract leaves. Previously saved
GA HTML fixtures remain historical parser evidence, not a current DeepSeek badge.

[training]: https://help.mistral.ai/en/articles/347617-do-you-use-my-user-data-to-train-your-artificial-intelligence-models
[zdr]: https://docs.mistral.ai/admin/monitor-comply/zero-data-retention
[deepseek]: https://docs.mistral.ai/models/deepseek-v4-flash-1017.md
[glm]: https://docs.mistral.ai/models/zai-glm-5-3.md
[flash]: https://docs.mistral.ai/models/zai-glm-5-3-flash.md
