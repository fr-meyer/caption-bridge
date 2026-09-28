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

The terms apply to the selected target language and are frozen at Start.
Changing the target language during a session suspends those terms until you
return to their original language. They do not rewrite earlier captions.
Edit terms before starting a new session. Unsaved drafts remain in this page
through New Session and are lost on reload.

**Remember terms on this browser** is off by default. When selected, only the
current language's glossary is saved in this browser's local storage. Switching
languages shows that language's draft; it does not automatically send the old
language's terms. Unchecking the box removes this glossary's saved browser copy.
**Clear terms** removes the current draft and its saved copy. Other local
session transcripts and journals are unaffected.

At Start, terms whose source appears in the current caption segment are sent
to the existing translation provider along with that segment, including any
already-bounded repair request. Terms appearing only in earlier context or
elsewhere in the glossary are withheld. Sent terms add prompt tokens and can
increase cost. They are preferences, not a guarantee of correct translation.
No additional request or retry is introduced by the glossary.

The session glossary is included in its private journal and TXT/JSON export,
including recovery exports. Diagnostics, reliability summaries and support
bundles do not contain terms. Existing export/journal retention is unchanged.

Rollback: return to immutable `v0.3.0` and clear the optional browser glossary
copy if desired. Older versions ignore the additional journal record and keep
recovering caption text; they do not preserve glossary metadata in old exports.
