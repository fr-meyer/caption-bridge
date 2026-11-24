# Provider evidence and disposition, 24 November 2026

Completed public research for #90 criterion 6 and #96, not an account audit or
live qualification. Only unauthenticated first-party public pages were retrieved.
No account login, credentials, inference, audio, billing change or default change.
This note supersedes older public-discovery gaps where explicitly corrected
below. It does not complete unknown account criteria or reopen delivered
catalogue implementation milestones.

## Material corrections

1. **The v3 rolling alias is now documented.** The complete official [v3 card
   Markdown][v3] names `voxtral-mini-transcribe-realtime-latest`, alongside
   `voxtral-mini-transcribe-realtime-3-0` and
   `voxtral-mini-transcribe-realtime-3`. The earlier [migration table][migration]
   omits the rolling alias; omission is not evidence that it does not exist.
   Public alias existence is resolved, but account availability, alias target
   and realtime ACK compatibility remain separate. No selector is changed.
2. **Preview privacy exclusions are explicit, not a missing toggle.** The
   [training policy][training] says opt-out does not apply to Labs or Public
   Preview models, regardless of subscription plan. The [ZDR guide][zdr]
   independently excludes those models. The v3 card is still Public Preview.
   Paying more or enabling ordinary opt-out/ZDR cannot establish coverage.
3. **DeepSeek V4.1 Flash 1017 is Public Preview, not GA.** Both the complete
   [card][deepseek] and [model index][index] say so. The older catalogue table
   was wrong on this distinction. GLM 5.3 and GLM 5.3 Flash remain GA, but are
   different variants. A product's experimental qualification label is not a
   vendor lifecycle badge.
4. **1000 ms is not a documented v3 trained delay.** The [protocol][protocol]
   and [troubleshooting][troubleshooting] require multiples of 80 from 80 to
   1200, or 2400. The existing legacy 1000 ms setting is not authority to send
   it to v3. The revised [evaluation design](voxtral3-evaluation-plan.md)
   distinguishes a proposed 960 ms v3 arm from the unchanged legacy arm.
5. **Global inference is not region-pinned.** The [hosting policy][region]
   says EEA hosting by default, but [regional inference][regional] explicitly
   makes no specific inference-location commitment for `api.mistral.ai`.
   Storage location, inference location and control-plane processing are
   different claims. The regional table describes its EU geography as EU and
   EFTA countries; do not infer an EU-only guarantee from its label. Dedicated EU/US endpoints are separate routes with
   availability checks and a documented token-price surcharge.

## #90 criterion 6: evidence versus remaining prerequisite

| Dimension | Public evidence as retrieved | Exact remaining fact / disposition |
| --- | --- | --- |
| Access | [v3][v3] is Public Preview; [legacy realtime][legacy] is deprecated 2026-10-31, scheduled retirement 2027-04-30 | Existing intended account/workspace must actually advertise the exact requested alias and target; neither a card nor older model metadata proves present transport access |
| Audio quotas | [Admin limits][limits] identifies audio seconds/minute and seconds/month | Numeric effective limits, used/reserved amount, reset and remaining headroom for the intended account/workspace |
| Scope | [Workspace][workspace] and [audio limits][audio-limits] say workspace/shared keys; [Help][help-limits] says organization/across workspaces | Reconcile effective organization AND workspace constraints. Do not pick one exclusive scope from conflicting documentation |
| Concurrency/session length | Workspace page calls RPS maximum concurrent API requests; audio guide supplies no numeric realtime session ceiling | Provider/account-specific simultaneous WebSocket ceiling and maximum session length. Generic RPS is not a documented numerical realtime-session allowance |
| API/billing access | Admin limits says API requires billing activation/PAYG; Help still describes Free-mode evaluation limits | Existing actual state only. No free-credit assumption, subscription upgrade, key creation or billing activation for research |
| Full price | Current model-card prices and billing semantics below | Account currency/tax, actual entitlement/credits, rounding/minimums, failed/disconnected/replayed-session charges, and applicable region/model coverage |
| Retries | Realtime guide requires corrected settings/new sessions for configuration changes; no general free-retry or deduplication promise | Freeze exact application AND SDK wire-attempt limits, reserve every attempted wire before dispatch, retain unknown charges. No inferred refund after timeout/cancellation |
| Retention | [ZDR][zdr] lists stateless audio transcription/speech endpoints, excludes preview; [retention policy][retention] provides no retrieved realtime-content TTL | Exact audio/transcript/error-content retention/deletion and WebSocket coverage for the selected model/contract. Generic endpoint coverage is not explicit realtime coverage |
| Training | Ordinary Studio/PAYG opt-out exists, but [preview exclusion][training] overrides it | Actual eligible-model account control/contract; v3 has an evidenced ordinary-policy no-go for confidential use requiring training exclusion |
| Region/privacy | EEA hosting default and dedicated regional-inference distinctions are documented | Actual approved endpoint, selected model's regional availability, processing/storage/subprocessor terms and applicable agreement. No route changes in this research |

The audio-limits page's three-attempt policy is for **voice-agent webhook
delivery**, not a retry entitlement for realtime ASR. Never use it to justify
replaying audio or to bound hidden SDK retries. Application retries, reconnects,
quality repairs and SDK transport retries are separate cost multipliers.

### Price: newly resolved components, not a complete authorized quote

Complete current first-party Markdown cards supply prices omitted by the earlier
HTML extraction:

| Selected role | Standard USD list price | Source / limit |
| --- | --- | --- |
| Legacy February realtime | $0.006/audio minute | [Legacy card][legacy], deprecated, not proof of current account access |
| V3 realtime | $0.008/audio minute | [V3 card][v3], Public Preview |
| Medium 3.5 text translation | $1.50/M input tokens, $7.50/M output tokens | [Medium card][medium], deprecated, including documented `mistral-medium-latest` name, not a live resolution receipt |
| Large 4 text translation | $0.70/M input, $0.07/M cached input, $2.10/M output tokens | [Large card][large], GA; not a replacement for the frozen Medium arm |

For the unexecuted 12-minute-per-arm, TTS-off design, standard ASR components
are **$0.072 + $0.096 = $0.168**. With Medium, the remaining arithmetic is
`$0.168 + input_tokens * 1.50 / 1_000_000 + output_tokens * 7.50 / 1_000_000`.
This is not a full ceiling until input/output and all attempt limits are frozen
and the missing charging/tax terms are evidenced or conservatively bounded.
No optional TTS is included, no cached discount is assumed, and no inference is
authorized by these calculations. A different translation arm needs a separate
predeclared comparison, never a silent family substitution.

[Billing][billing] says credits are deducted **including tax**, spending limits
apply **before tax**, processing delay can create a negative credit balance,
and credits do not remove spending limits. A console monthly cap is therefore
not an exact experiment watchdog. Do not buy credits or enable auto-recharge
to resolve an evidence gap. [Regional inference][regional] specifies **1.1x**
standard token pricing for input/output/cached reads/cache writes. Its excerpt
does not establish an audio-minute regional tariff or realtime regional
availability; those remain unknown. The API [pricing table][pricing] differs
from the marketing page's generic Large example, so use the precise card and
verify the intended endpoint/model tariff, not the generic example.

### Research verdict and one consolidated handoff

**No-go for v3 confidential seminar content under the retrieved ordinary
preview terms.** Opt-out/ZDR exclusion is positive evidence, not merely absence
of a screenshot. A purchase is not a remedy. Safest disposition is defer v3,
retain the recoverable existing path, and do not upload private material.
This is not a model-quality verdict, proof the legacy path meets every privacy
requirement, or permission to bypass lifecycle checks. A contract-specific
exception could be considered only with explicit applicable written evidence;
no exception or blanket waiver is inferred or solicited here.

If no v3 use is needed, no upgrade or paid comparison is needed to finish this
research artifact. If the project still requires criterion 6 in full, keep #90
open for the exact account/contract leaves in the table, or have the maintainer
explicitly accept a research-only/deferred disposition. Public/synthetic-fixture
evaluation is also a separate budget/content decision, not automatically safe
or authorized by this no-go. Use the existing account administrator's read-only
evidence, not new credentials, support contact or account actions.

## #96: official names, families and eligibility are different claims

The following is a public declaration inventory, not an account catalogue.
Every row was retrieved from the complete first-party `.md` card on 2026-11-24.
No alias was invented from a prefix. Source output budgets remain application
policies, not the vendor's context or maximum-output capability.

| Family/variant | Literal official API names | Vendor lifecycle | Contract distinction |
| --- | --- | --- | --- |
| Large 4 | `mistral-large-4`, `mistral-large-4-0`, `mistral-large-latest` | GA | [Text/image in, reasoning/text out][large]; a rolling alias does not pin a build |
| Small 4 | `mistral-small-2603`, `mistral-small-latest` | GA | [Hybrid reasoning/text][small]; High needs account capability AND explicit policy |
| Medium 3.5 | `mistral-medium-3-5`, `mistral-medium-3`, `mistral-medium-latest` | Deprecated | [Retires 2027-04-30][medium]; replacement recommendation is not default-change authority |
| GLM 5.3 | `zai-glm-5-3`, `zai-glm-5`, `zai-glm-latest` | GA | [Text-in reasoning/text-out][glm]; aliases are not Flash names |
| GLM 5.3 Flash | `zai-glm-5-3-flash` | GA | [Separate multimodal Flash variant][glm-flash]; no `*-latest` declared in this card |
| DeepSeek V4.1 Flash 1017 | `deepseek-v4-1-flash-1017` | Public Preview | [Reasoning/text output][deepseek]; privacy exclusions apply, no `*-latest` declared |
| Codestral | `codestral-2508`, `codestral-latest` | GA | [Chat AND FIM][codestral]; FIM support alone would not prove translation compatibility |
| Ministral 3 3B | `ministral-3b-2512`, `ministral-3b-latest` | GA | [3B family][mini3]; not interchangeable with 8B/14B or separate reasoning weights |
| Ministral 3 8B | `ministral-8b-2512`, `ministral-8b-latest` | GA | [8B family][mini8]; separate explicit execution contract |
| Ministral 3 14B | `ministral-14b-2512`, `ministral-14b-latest` | GA | [14B family][mini14]; separate explicit execution contract |
| Voxtral Small | `voxtral-small-2507`, `voxtral-small-latest` | GA | [Chat-capable audio/text input, text output][voxtral-small]; not realtime-ASR or TTS and not Small Transcribe 3 |

Required eligibility remains conjunctive: fresh account `completion_chat`,
current literal-name/lifecycle evidence, same-family AND same-variant alias
target corroboration, identical reviewed execution policy, permitted content
privacy, and supported effort. A GA badge supplies none of account access,
translation quality, low latency or actual retention configuration. Unknown
families/aliases remain visible but disabled until their own evidence exists;
deprecated/retired entries stay unavailable. Never revive Medium through its
replacement card or infer Flash compatibility from GLM non-Flash success.

The existing source's general `active` lifecycle includes Public Preview.
**Active is not GA or privacy approval.** The current registry also lacks the
newly documented GLM rolling aliases. These are coordinator/backend handoffs,
not competing code changes in this research lane. Add an alias only after its
exact target and execution contract are corroborated; do not enable previews
merely because the account lists them. Existing catalogue milestones stand,
but these narrower gaps and per-family account/live acceptance remain open.

### Latest preference versus reproducible campaigns

Normal new requests should use an officially documented rolling `*-latest`
selector when that route is verified, recording requested alias separately
from a genuinely resolved model identifier. An echoed alias is not resolution
proof. A controlled campaign's exact dated IDs remain immutable provenance and
evidence for **those IDs only**; do not rewrite them as alias trials, silently
change a running campaign, or alter the product default to match a campaign.
For variants without a documented latest name, leave selection unresolved
unless a narrow explicit exception is actually authorized. Neither prior
account metadata nor one successful family route qualifies every family.

## Source register and confidence

All sources below returned HTTP 200 on 2026-11-24. Complete model-card Markdown
was used for literal names, lifecycle, prices and retirement dates. Confidence
is **high for the quoted public declarations**, not account applicability or
runtime compatibility. Account/retention/concurrency unknowns are deliberately
not assigned confidence as though measured. No private artifacts or account
data are included here.

- Model Markdown retrievals: Large/Voxtral Small 11:42:03-04 UTC; v3, legacy,
  Medium, Small, GLM, Flash, DeepSeek, Codestral, Ministral 3B/8B/14B
  11:42:29-31 UTC. Model index: 11:44:09 UTC.
- Training, opt-out, ZDR Help, retention, hosting and Admin limits:
  11:40:19-20 UTC. Admin ZDR table: 11:43:55 UTC.
- Workspace/audio/Help limits and migration: 11:40:28-29 UTC.
- API pricing Markdown: 11:43:19 UTC; billing: 11:43:35 UTC; realtime protocol:
  11:43:36 UTC; troubleshooting: 11:44:10 UTC; regional inference: 11:44:18 UTC.
- HTML migration, realtime protocol, some HTML cards, troubleshooting and regional inference
  reported incomplete bodies after 750000 bytes. Only retrieved affirmative
  text is used. Omitted aliases were resolved by complete card Markdown, not
  guessed. Help extraction omits some lists even when marked complete; the
  complete retrieved Admin ZDR table supplies endpoint evidence, but does not
  add a realtime WebSocket guarantee. Search summaries were discovery only.
- Some guide `.md` links and a legacy troubleshooting URL returned 404. Working
  HTML guides above were used instead; no claim depends on a failed fetch.

[v3]: https://docs.mistral.ai/models/voxtral-mini-transcribe-realtime-3-0.md
[legacy]: https://docs.mistral.ai/models/voxtral-mini-transcribe-realtime-26-02.md
[medium]: https://docs.mistral.ai/models/mistral-medium-3-5-26-04.md
[large]: https://docs.mistral.ai/models/mistral-large-4-0.md
[small]: https://docs.mistral.ai/models/mistral-small-4-0-26-03.md
[glm]: https://docs.mistral.ai/models/zai-glm-5-3.md
[glm-flash]: https://docs.mistral.ai/models/zai-glm-5-3-flash.md
[deepseek]: https://docs.mistral.ai/models/deepseek-v4-flash-1017.md
[codestral]: https://docs.mistral.ai/models/codestral-25-08.md
[mini3]: https://docs.mistral.ai/models/ministral-3-3b-25-12.md
[mini8]: https://docs.mistral.ai/models/ministral-3-8b-25-12.md
[mini14]: https://docs.mistral.ai/models/ministral-3-14b-25-12.md
[voxtral-small]: https://docs.mistral.ai/models/voxtral-small-25-07.md
[index]: https://docs.mistral.ai/models.md
[migration]: https://docs.mistral.ai/studio/audio/migrate-from-voxtral-2
[protocol]: https://docs.mistral.ai/studio/audio/speech-to-text/transcribe-in-realtime
[troubleshooting]: https://docs.mistral.ai/studio/audio/speech-to-text/troubleshooting
[training]: https://help.mistral.ai/en/articles/347617-do-you-use-my-user-data-to-train-your-artificial-intelligence-models
[zdr]: https://docs.mistral.ai/admin/monitor-comply/zero-data-retention
[retention]: https://help.mistral.ai/en/articles/347628-how-long-do-you-store-my-data
[region]: https://help.mistral.ai/en/articles/347629-where-do-you-store-my-data-or-my-organization-s-data
[regional]: https://docs.mistral.ai/inference/regional-inference
[limits]: https://docs.mistral.ai/admin/billing-usage/usage-limits
[workspace]: https://docs.mistral.ai/admin/workspaces/usage-limits
[audio-limits]: https://docs.mistral.ai/studio/audio/specs-and-limits/limits
[help-limits]: https://help.mistral.ai/en/articles/698531-why-am-i-hitting-api-rate-limits-and-how-do-i-increase-them
[pricing]: https://docs.mistral.ai/inference/pricing.md
[billing]: https://docs.mistral.ai/admin/billing-usage/billing
