# Terminology preferences

Before Start, open **Terminology (optional)** and enter one pair per line:

```text
통계적 유의성 => statistical significance
신뢰 구간 => confidence interval
```

Use up to 20 unique source terms. Each source and preferred rendering can have
1–80 characters. The source cannot contain the `=>` separator in this editor.
Controls and invisible formatting characters are rejected. An empty editor
keeps the existing translation behavior.

The terms apply to the selected target language. Start saves an initial version.
Changing the target language during a session suspends those terms until you
return to their original language. They do not rewrite earlier captions.
Unsaved pre-session drafts remain in this page
through New Session and are lost on reload.

While listening, choose **Correct term** on a caption. Select a short source
term (or type it), then choose **Preferred translation** or **Misheard source
term**. Enter the preferred rendering or correct source spelling and choose
**Save for future captions** to confirm. Closing the editor saves nothing.
Source corrections replace matching text only in future translation inputs;
the original ASR text remains available. Replacements are applied once, with
the longest match first, and never cascade into another replacement.

Use **Settings → Session terminology** to inspect the list, edit a term, remove
it, or **Undo last change**. Undo restores the previous list as a new version.
Listening and spoken readback continue while the editor is open. Every caption
shows the terminology version captured when its translation was dispatched;
requests already in flight keep that version. No action here re-translates or
rewrites an existing caption.

The same 20-pair and 80-character limits apply during a session. A session is
limited to 100 saved changes, including undo. At that limit the list remains
inspectable; a new session is required for further changes. Saving terms for a
different target language replaces the paused list, and Undo can restore it.
Refresh restores the server's current version and undo state. Stale saves,
language changes and edits from an earlier session are rejected before mutation.
Changing the translation model does not change the terminology version.

**Remember terms on this browser** is off by default. When selected, only the
current language's glossary is saved in this browser's local storage. Switching
languages shows that language's draft; it does not automatically send the old
language's terms. Unchecking the box removes this glossary's saved browser copy.
**Clear terms** removes the current draft and its saved copy. Other local
session transcripts and journals are unaffected.

Preferred translations whose source appears in the effective caption segment are sent
to the existing translation provider along with that segment, including any
already-bounded repair request. Terms appearing only in earlier context or
elsewhere in the glossary are withheld. Sent terms add prompt tokens and can
increase cost. They are preferences, not a guarantee of correct translation.
No additional request or retry is introduced by the glossary.

The current glossary is included in the private TXT/JSON export. The JSON
export and journal also preserve original ASR and translation, effective
translation input, per-caption terminology snapshot/version/status, and the
revision history with caption origin and undo provenance, including recovery
exports. Live edits stay on the server and do not activate browser persistence.
Diagnostics, reliability summaries and support
bundles do not contain terms. Existing export/journal retention is unchanged.

Before Mac rollout, an attended usability review must compare this caption
action with the pre-session editor: create a correction from a synthetic
caption, save it, inspect/edit/remove/undo it, refresh, and confirm that the
original caption and listening state remain intact. Offline browser tests
cover these actions; they do not replace that human review.

Rollback: return to immutable `v0.3.0` and clear the optional browser glossary
copy if desired. Older versions ignore the additional journal record and keep
recovering caption text; they do not preserve glossary metadata in old exports.

## Prepared human comparison and accessibility programme

Preparation is not participant/VoiceOver/onboarding acceptance. Reuse the editor
and caption action above; no alternative UI or production speed feature is added.
Automated browser checks cover labels, keyboard activation, modal Tab/Shift+Tab
containment, Escape/return focus, unchanged captions and continued listening.
When Save/Undo becomes disabled while awaiting a reply, focus moves to Close
before native disabling can blur the keyboard position to the page body. These
contracts cannot certify spoken screen-reader announcements or discoverability.

### Counterbalanced terminology task card

Use anonymous slots and an offline public-text caption scenario, not a live
meeting/provider session. Freeze the candidate and reset session/glossary/browser
persistence between task cards. Prepare matching X/Y cards: X asks for
“protocol → procedure”, Y for “interval → range”. The two captions contain only
their own source term. Rotate four assignments before recruitment:

1. Pre-session X, then caption-action Y.
2. Caption-action X, then pre-session Y.
3. Pre-session Y, then caption-action X.
4. Caption-action Y, then pre-session X.

Neutral instruction: “Make future translations use the preferred wording on
this card, without changing the caption already shown. Tell us when you believe
it is saved.” Do not name the control or demonstrate the successful path. The
pre-session condition necessarily saves at Start; the caption condition saves
during listening. Compare only the shared preference-entry outcome, not total
session startup or unmatched inspect/undo functionality. The observer records
first action, elapsed time, wrong turns, requests for help, save confirmation,
original-caption preservation and reported confidence. Preserve failed attempts.
The observer may stop unsafe behavior but logs that intervention as assistance.

After the comparison, separately ask the participant to inspect, edit, remove,
undo, cancel an unsaved edit, refresh and explain whether earlier captions
changed. Also cover a misheard-source correction, target-language suspension,
local persistence off by default, opt-in and clearing. These are additional
functional tasks, not retroactively scored into the paired comparison. Check
listening status, original captions and terminology versions independently.

### Human VoiceOver sheet (actual Mac window required)

Before starting, record browser/version, screen-reader/version, keyboard
navigation setting and whether the participant already knows the product. Do
not change system accessibility/TCC/audio settings during autonomous preparation.
Use only the agreed provider-free fixture, with capture absent.

Ask the participant to navigate headings/controls, discover the caption action,
open the dialog, identify its title/help, correction type, both inputs, current
version, errors and Save/Undo/Close. Traverse forward/backward, attempt invalid
input, save, inspect/remove/undo, then Escape. Ask where focus landed and what
was announced after each operation, without suggesting the expected wording.
Repeat entry from Settings, a pending mutation, a read-only 100-change limit and
a hidden/disconnected opener. The observer checks no focus escape, meaningful
labels/status/error announcement, predictable fallback and unchanged listening.
Record actual announcements, confusion, assistance and PASS/FAIL/NOT ASSESSED
per task. Chromium accessibility-tree/keyboard tests are not VoiceOver evidence.

### Uncoached second-operator card (participant-facing)

“Using the supplied offline demonstration only, prepare English captions with
spoken readback off. Add the term preference on your card. Decide whether the
application is ready, start the demonstration when appropriate, make one future
term correction, stop it, find the private export and leave the application
idle. Do not grant unexpected device/account permissions or change system audio.
If something is unclear, say what you expect before taking action. You may stop.”

Do not give the participant these observer answers in advance: readiness must
come from public status/checklist, not an assumed caption or internal JS state;
Captions only should remain explicit; the original caption must survive a future
correction; Stop must leave no pending speech; export must be readable privately;
final status must be idle with no capture. The observer records independent
completion, elapsed time, each instruction requested, every intervention and
privacy/safety confusion. One coached rescue is not uncoached success. No external
participant is contacted by this preparation; owner-approved participants and
attended readiness remain prerequisites.

### Shortcut observer phase boundary

The browser shortcut regression keeps both full WebSocket histories. Before any
keyboard action it requires the actual live-caption `seq=1` renderer ACK on the
browser and receiving fixture and verifies this exact ordered initial exchange:
`refresh_input_devices`, `tts_mute(muted=false)`, `render_ack(seq=1)`. This binds
the baseline to authoritative snapshot/renderer processing, not a sleep or a
message-type allowlist. It does not clear either observer. Each baseline index
is fixed once before the modal/guarded-key phase.

After the keys, a condition-based receive-count checkpoint drains all observed
browser sends into the server recorder, including controls ignored by dispatch.
The original startup prefix/ACK must remain intact; this single-caption fixture
expects **no** additional frame from either observer. A late startup-typed frame
is not exempt. Existing dynamic Tab order, Escape focus return and active
Listening checks remain unchanged.

Source-driven Node/Python model probes reproduce the former whole-history false
failure and remove the actual modal keyboard guard in memory: the resulting
post-baseline Stop is detected independently by both observer assertions. These
are **model probes, not actual Chromium/native focus/VoiceOver or browser-audio
proof**. A fresh hosted browser run at the published repair head is still needed;
no browser installation, timeout increase, forged ACK or skip is used here.
