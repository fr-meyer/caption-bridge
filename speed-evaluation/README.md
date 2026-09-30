# Spoken-readback speed evaluation (#67)

Keep production at normal speed. This candidate adds an independent evaluation
harness and evidence, with no production imports, control, provider request, or
audible output. It complements the progressive PCM playback work in #65.

## Measured result

The exact harness completed in the existing GCP validation image with networking
disabled, source/runtime mounts read-only, one CPU, 768 MiB memory, 160 processes,
and a 90-second ceiling. **11 checks passed and 3 explicitly skipped.** All six
offline resampling checks passed in Chromium and Linux WebKit. Chromium also
completed the three muted-media duration checks. The three skips are Linux
WebKit's inability to decode the local silent PCM WAV in this image; its
pitch-control property checks passed independently.

A one-second, 440 Hz synthetic signal was rendered only into an in-memory
`OfflineAudioContext` buffer. Neither browser routed this signal to a device.
Both browsers produced these results, rounded for readability:

| Web Audio playback rate | Rendered duration | Measured frequency | Pitch shift | Duration saved |
| --- | ---: | ---: | ---: | ---: |
| 1.0 | 1.00000 s | 440.000 Hz | 0.000 semitones | 0% |
| 1.15 | 0.86958 s | 506.000 Hz | +2.420 semitones | 13.04% |
| 1.3 | 0.76925 s | 572.000 Hz | +4.542 semitones | 23.08% |

The pitch shift is a material consequence of simple resampling. The Web Audio
specification defines `playbackRate` and `detune` as one combined rate that
advances through the buffer. Changing `detune` to cancel the frequency change
also cancels the speed change; it does not provide independent time stretching.
[Web Audio specification](https://www.w3.org/TR/webaudio/#AudioBufferSourceNode).

## Pitch-preserving alternative

Both tested engines expose standard `HTMLMediaElement.preservesPitch`, initially
true, and accepted changes to false and back to true. The HTML standard requires
pitch preservation when this property is true and playback rate differs from
normal. This makes a media element a candidate for a separately evaluated
complete-clip player. [HTML media specification](https://html.spec.whatwg.org/multipage/media.html#dom-media-preservespitch).

Chromium played a locally generated, one-second, zero-valued PCM WAV at all three
rates with `muted=true` and `volume=0`. Playing-to-ended wall times were 1.0402 s,
0.9003 s, and 0.8002 s. Scheduling and media-end overhead account for the
difference from ideal durations; these observations are not latency guarantees.
Media time advanced monotonically and ended at exactly one second of content.

Linux WebKit returned media error code 4 for that WAV. This limits the container
measurement and does not establish native Safari's codec behavior. We did not
install a decoder or change host configuration. The harness records unsupported
decoding explicitly; it never counts those media checks as passes.

Silence has no frequency, so these media tests establish API support and muted
timeline behavior, not measured pitch preservation or speech intelligibility.
The normative pitch requirement is distinct from the measurements.

Both tested engines report `MediaSource.isTypeSupported("audio/wav") == false`,
while reporting support for tested Opus/WebM and AAC/MP4 types. This is a feature
probe, not a decoding/integration test. Caption Bridge currently receives raw
PCM; wrapping a completed clip as WAV restores the wait for completion. A media
alternative cannot be dropped into #65's progressive raw-PCM queue unchanged.
No containerization, transcoder, time-stretching dependency, or provider-specific
speed parameter was added by this evaluation.

## Go/no-go prerequisite

An attended listening comparison on actual Safari and Chromium must precede a
faster production setting. Use an approved public or locally generated synthetic
speech sample containing pauses, punctuation, numbers, acronyms, and technical
terms in the supported target languages. Compare normal, 1.15, and 1.3 in the
chosen playback mechanism; include a short interruption/replay example. Do not
capture microphone audio or retain sample audio/transcript in diagnostics.

A go decision requires the listener to accept voice/pitch quality and understand
the terms and numbers at the proposed rate. A failure in either browser or a
supported target-language sample keeps normal speed. Human judgment cannot be
substituted by zero-crossing accuracy or the existence of `preservesPitch`.
That listening comparison and the playback-mechanism decision remain open;
this candidate does not launch them or ask for new provider work.

Any later speed control must preserve #65/#66's clip IDs, epochs, one start and
one terminal acknowledgment per clip, Catch up/mute cancellation of every source,
reconnect rebasing, replay, and audio-unlock behavior. Apply a selected rate at
clip start unless a reviewed design handles in-flight source scheduling. Keep
normal as the default and record only numeric speed/outcome diagnostics.

## Reproduce and incorporate

The files are isolated under `speed-evaluation/`. `run-offline.sh` reproduces the
bounded test using the existing GCP image and cached Python runtime; its current
path is an environment-specific development runtime, not a production dependency.
The Playwright tests can also run with an already installed pytest-playwright
runtime and Chromium/WebKit. They do not download dependencies or browsers.

`evidence/final-measurements.json` contains all 14 aggregate measurements, exact
harness hashes, test exit status, and execution constraints. The original failing
run is retained as `evidence/initial-measurements.json` and
`evidence/bounded-validation.log`; the corrected run is
`evidence/final-validation.log`. Raw synthetic signal samples are not exported.

The accompanying `speed-evaluation.patch` adds the harness, checks, this decision
record, and the final numeric receipt. It has no hunk in `app/` or the streaming
branch. No GitHub publication or production change was performed.
