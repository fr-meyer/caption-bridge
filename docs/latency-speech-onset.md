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
