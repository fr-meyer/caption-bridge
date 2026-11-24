# Speech-onset detector

Bounded local energy detector for Caption Bridge latency dimension 1–2.

## Signal

- Input: int16 mono PCM from the existing capture callback (~100 ms blocks).
- Metric: RMS normalized to `[0, 1]`.
- Floor: exponential moving average of quiet blocks, with a minimum floor.
- Onset: two consecutive blocks above `max(min_floor, floor * 3.5)`.
- End of utterance: three consecutive quiet blocks.

The detector emits only a boolean onset. It never retains PCM, captions, or paths.

## Error modes

False positives

- Keyboard taps, coughs, door slams, and other short bursts can cross the adaptive floor.
- A loud noise during silence opens an utterance that no caption will follow.

False negatives

- Very quiet or far-field speech may stay under the adaptive floor.
- Speech that starts while an utterance is already open is not a new onset.
- Onset during an existing open utterance is ignored by design.

False-start resets increment when an onset is followed by silence before any non-empty partial, or when a source caption is finalized with no partial after onset.

These counts are diagnostic only. They are not release thresholds.

## Distinct playback timing dimensions

This capture RMS detector is not the playback onset analyzer. A capture callback
onset is not request dispatch, first generated PCM, readiness, schedule submission
or sound reaching a listener. The software observer in
[evaluations/speech_timing](../evaluations/speech_timing/README.md) records receive
and scheduling work without changing this detector. Its modeled sink uses real
wall-clock execution but measures no delivered digital output. A real
OfflineAudioContext can verify rendered sample offsets without opening a device;
its render start and fixed sample clock cannot establish realtime output latency.
Only a verified digital loopback measures that digital route. Acoustic onset
requires an attended calibrated physical reference with uncertainty and guarded
capture. Keep these scopes distinct in every report; unknown continuity and
human quality remain unknown.
