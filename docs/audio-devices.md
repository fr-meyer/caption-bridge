# Microphone input and spoken output

Before Start, choose **Microphone input** in the idle panel. **System default
microphone** resolves the native default when Start is pressed. An explicit
choice opens that native input with the existing configured mono int16 capture
path (16 kHz by default). Format validation uses the same configured sample rate
as capture, including before reconnect.
Input stays fixed during listening and reconnect; use New Session to choose
another microphone. Listing devices does not capture audio. macOS idle readiness
reads existing authorization without opening input. Mac Start requires microphone
permission already granted for the launcher; an undetermined, denied, restricted
or unverifiable authorization blocks Start. This feature does not initiate a first
grant or change device permissions. First-grant setup is separate; an unlisted
launcher cannot be granted access merely by toggling a missing Settings entry.
For an authorized launcher, actual device access is checked when Start opens the
stream. Other platforms defer the permission/open
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
Metadata refresh and Start/reconnect validation are serialized so an older device
list cannot replace the inventory used to choose the input.
Native device identity is limited to the current PortAudio index and reported
metadata; identical device instances cannot be distinguished beyond that API.

Native choices survive a browser replacement in the active server session.
Browser output choices reset to system/browser default after page replacement,
and speech still requires the replacement document's Enable audio gesture.
New Session resets both transient choices to defaults. No choice, device label
or identifier is saved to browser storage, transcript exports, recovery journals,
or aggregate diagnostics. Device lists are displayed only in the local loopback
UI. Physical routing and intelligibility require separate attended acceptance.

Output transitions retain the last successfully applied route even if a later
reset fails. Device lists from before a chooser or sink change are discarded;
the app refreshes output exposure after the transition so a removed output is
still detected without falsely muting a newly granted one.

## Integration with v0.5.0's PCM player

This candidate adapts the reviewed PR #81 native input and browser output controls
to released v0.5.0. `CaptionPcmPlayer`, Enable audio and the output selector use
one shared `getAudioContext()`. Both buffered and optional progressive playback
therefore use the chosen sink for live speech and Replay. Output removal invokes
the existing mute cancellation, clears the speaking highlight, updates Replay
controls and sends the ordinary dispatcher mute command. Choosing a usable
output never unmutes speech automatically.

Clip IDs, epochs, cancellation, Catch up, relock and input-tail handling retain
their v0.5.0 behavior. Model/thinking/profile selection and frozen terminology
metadata remain independent of device selection. `/audio-devices.js` shares the
browser assets' no-store policy. Progressive playback remains opt-in and speech
speed remains normal.

Silent synthetic browser checks exercise shared-context routing, active/queued
source cancellation on output removal, Catch up, stale-epoch rejection and Replay
in buffered and progressive modes. They also check native selection through
Start, page replacement and New Session. These checks do not certify physical
routing, browser permission prompts, native Safari or Windows hardware. An
attended routing and intelligibility check remains before deploying this feature.

API references: [native sounddevice metadata/format checks](https://python-sounddevice.readthedocs.io/en/0.5.5/api/checking-hardware.html),
[browser device exposure](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/enumerateDevices),
[AudioContext output routing](https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/setSinkId),
[explicit output chooser](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/selectAudioOutput).
