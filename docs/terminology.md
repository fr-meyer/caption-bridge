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
