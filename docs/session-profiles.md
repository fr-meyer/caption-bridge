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
requests/cost. A longer pause can delay captions. The bounded public-text
comparison below is directional; real-audio and human-readability comparisons
remain pending. The presets remain an unpublished draft.

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
before Start is the per-session rollback. The published v0.4.0 glossary release
remains unchanged and is the software rollback for this unpublished draft.

## Bounded public-text comparison

On GCP, a replay fed two public Korean examples through the production
boundary detector under each timing choice. One example had a 1.1-second pause
between complete clauses; the other was a single unpunctuated sentence.
Shorter pauses finalized the first clause at about 0.8 seconds and made two
translation requests. Current settings and Longer pauses waited for the second
clause at about 1.1 seconds and made one request each. The standalone sentence
finalized at about 0.8 / 1.5 / 2.2 seconds, respectively.

Seven bounded Mistral Small translation requests completed. All seven passed
the existing automated output-quality checks. Shorter used three requests
across the examples; Current and Longer used two each. The conservative
seven-call usage reservation was below $0.01; this is a pricing-based upper
bound, not a provider invoice. The event replay had no microphone, human
readability judgment, speech playback or full end-to-end latency measurement.
The results show the expected latency/request-count tradeoff for these two
public examples, not a general quality claim.

## Remaining acceptance

GCP tests cover validation before Start side effects, frozen/reconnect timing,
new-session reset, export/recovery, explicit storage and active-session refresh
precedence. Chromium/WebKit and prior native Safari controls were synthetic;
they do not establish microphone, human readability, VoiceOver or invoiced
provider evidence. The
glossary predecessor is published. Promotion still requires real-audio and
human-readability review, any final native Safari acceptance needed by the
rollout, and a version/release decision.
