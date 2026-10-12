# Microphone input and spoken output

Before Start, choose **Microphone input** in the idle panel. **System default
microphone** resolves the native default when Start is pressed. An explicit
choice opens that native input with the existing 16 kHz mono int16 capture path.
Input stays fixed during listening and reconnect; use New Session to choose
another microphone. Listing devices does not capture audio. macOS idle readiness
reads existing authorization without opening input; actual device access is
checked when Start opens the stream. Other platforms defer the permission/open
check to Start. This does not add physical Windows support.

**Spoken readback output** belongs to the browser's shared Web Audio context.
Choose an exposed output in the idle panel or Settings. A successful sink change
applies to both live speech and replay. **Choose speech output**, when offered,
opens the browser's output chooser only after a deliberate click. No browser
microphone stream is opened to reveal device labels or grant speaker access.

Output APIs and device exposure vary by browser and permission state. When
selection is unsupported, speech uses system/browser default output and the
control is disabled with guidance. Only permitted outputs are listed; use
system/browser audio settings when an intended device is missing. Rejected
changes leave the current route selected and show a notice. If a selected output
disappears from the exposed inventory, speech is muted; choose a usable output
and unmute deliberately. Captions remain available for replay.

**Refresh devices** reloads native input metadata and exposed browser outputs.
Browser device-change notifications refresh outputs when available. A removed,
replaced or reindexed explicit native choice blocks Start instead of silently
using a different microphone. Reconnect revalidates the input frozen at Start.
Native device identity is limited to the current PortAudio index and reported
metadata; identical device instances cannot be distinguished beyond that API.

Native choices survive a browser replacement in the active server session.
Browser output choices reset to system/browser default after page replacement,
and speech still requires the replacement document's Enable audio gesture.
New Session resets both transient choices to defaults. No choice, device label
or identifier is saved to browser storage, transcript exports, recovery journals,
or aggregate diagnostics. Device lists are displayed only in the local loopback
UI. Physical routing and intelligibility require separate attended acceptance.

## Integration with the combined PCM player

This focused draft is based on published v0.4.0, rather than publishing the
unreleased combined candidate. Apply its native input helper, capture `device`
argument, Start validation, runtime-only snapshot/reset and UI inventory events
additively when integrating with the combined profile/model/terminology source.
Keep that candidate's existing Start validation and canonical caption metadata.

For the combined buffered/progressive PCM player, keep one shared `audioContext`.
Use the same `getAudioContext()` for `CaptionPcmPlayer`'s `context` callback,
Enable audio and the output selector. `setSinkId()` must target that context;
changing a separate HTML audio element does not route PCM. Preserve clip IDs,
epochs, cancellation, Catch up and relock behavior. The output-unavailable hook
must mute through existing dispatcher controls and cancel the existing PCM player,
without deleting captions. Add `/audio-devices.js` to the static no-store asset
set and the synthetic browser harness. Keep progressive playback off and normal
speech speed unchanged. The combined adaptation needs its own focused interaction
review; this v0.4.0 draft does not claim that integration has been performed.

API references: [native sounddevice metadata/format checks](https://python-sounddevice.readthedocs.io/en/0.5.5/api/checking-hardware.html),
[browser device exposure](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/enumerateDevices),
[AudioContext output routing](https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/setSinkId),
[explicit output chooser](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/selectAudioOutput).
