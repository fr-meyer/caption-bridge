# Language and caption timing profile

Before Start, choose a supported target language. Open **Session profile
(optional)** to choose caption timing. Source speech continues to use the existing
auto-detection; this feature does not add languages or claim new language quality.

| Timing choice | Pause timeout | Fragment hold limit |
| --- | --- | --- |
| Current settings (default) | Existing operator setting | Existing operator setting |
| Shorter pauses | 800 ms | 2,000 ms |
| Longer pauses | 2,200 ms | 5,000 ms |

These values control the existing caption boundary detector. They are not
end-to-end latency promises. Punctuation, semantic boundaries, fragment rules,
transcription/provider response time, translation and spoken playback still
affect delivery. A shorter pause can split phrases and increase translation
requests/cost. A longer pause can delay captions. Live readability/quality and
cost comparisons are pending; the presets remain an unpublished draft.

The selected timing is fixed at Start and retained across reconnect. **New
Session** permits a new choice. The active target language can still be changed
through the existing drawer; changing it does not change timing or the saved
profile for future sessions.

## Remember only when requested

**Remember language and timing on this browser** is off by default. Enabling it
stores one target-language code and timing-choice ID, with a schema version, in
this browser's local storage. No transcript, glossary term, source audio, API key,
provider setting or custom name is stored as part of the profile.

Without opt-in, the selection remains in page memory and resets on refresh/New
Session. Unchecking removes the saved profile while keeping the current page's
selection. **Forget saved profile** removes that browser entry and restores the
current server default language/timing. Other saved preferences and private
session data are unaffected.

An active session snapshot takes precedence over browser storage on refresh.
Invalid/unsupported saved choices are ignored. If browser storage is unavailable,
the app can still start using the current selection and reports that it could
not remember the profile.

## Session/export transparency and rollback

The session snapshot, private JSON/TXT export and recovery journal include the
resolved timing choice and numeric values. A current-settings session freezes
the operator's values for that session; reconnect does not silently adopt later
configuration changes. Older journals without profile metadata recover with
unknown timing, rather than inventing an original setting. Invalid profile
metadata is ignored with a static, content-free warning; captions still recover.

The existing content-free reliability counters and latency report keep their
current schema. For future profile comparisons, join the private export's
session ID/profile metadata with its aggregate reliability record; never copy
caption text into a report. These counters are not a provider invoice.

No provider/model, microphone format, streaming delay, concurrency, retry limit,
audio default, automatic startup or retention behavior changes. Default Start
uses the existing configured detector values. Returning to **Current settings**
before Start is the per-session rollback. The published v0.3.0 and glossary
release candidate #60 remain separate and unchanged.

## Remaining acceptance

GCP tests must prove validation before Start side effects, frozen/reconnect
timing, new-session reset, export/recovery, explicit storage and active-session
refresh precedence. Chromium/WebKit tests are synthetic, not native Safari,
microphone, human readability, VoiceOver or billed provider evidence. Promotion
requires the glossary release decision and bounded live timing/quality/cost
evidence within the remaining approved budget.
