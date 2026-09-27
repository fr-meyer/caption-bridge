# Captions-only mode

Choose **Captions only** before pressing **Start**, or open **Settings** during a
session and turn it on there.

Source and translated captions continue. Spoken readback stops, queued speech
is suppressed, and Replay is disabled while the choice is on. Transcription and
translation still use the configured provider; captions-only mode does not make
those services free.

## Keep the choice between sessions

The choice survives **New Session**, browser refresh and connection recovery.
It is stored for this browser and this site. A different browser or site address
has its own choice.

Browser storage contains only a true/false preference. It stores no caption
text, transcript, glossary, audio, credential or provider response for this
setting. If browser storage is unavailable, the choice works in the current page
but may not survive refresh.

## Turn spoken readback on again

Uncheck **Captions only** in Settings, or use the speaker button labelled
**Turn on spoken readback**. Both actions clear the persistent captions-only
choice.

If the browser shows **Enable Audio**, press it to allow playback. Refreshing the
page locks audio again until a new user gesture. Normal temporary mute remains
available after captions-only mode is off.

## Export and rollback

Stopping and exporting a session works normally. Captions-only does not change
the retention policy or automatically save or delete transcripts.

Turn the choice off to return to the normal speech controls. Software rollback
uses the immutable previous release tag as described in [Mac CLI
operations](mac-cli.md); start remains on demand.
