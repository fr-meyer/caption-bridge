"""Pure capture-consumer seam. Does not open streams or authorize capture."""
from scripts.playback_measurement import finite, onset


def calibrate(anchors, sample_rate):
    """Anchors: (capture sample index, monotonic ms, uncertainty ms).

    Require three bracketing anchors; nominal rate slope with bounded residual.
    Offsets are midpoint of feasible intervals, not an unbounded extrapolation.
    """
    if type(sample_rate) is not int or not 8000 <= sample_rate <= 192000:
        raise ValueError("invalid rate")
    if type(anchors) is not list or not 3 <= len(anchors) <= 32:
        raise ValueError("three clock anchors required")
    lower, upper, previous = [], [], -1
    for anchor in anchors:
        if type(anchor) not in (list, tuple) or len(anchor) != 3:
            raise ValueError("invalid clock anchor")
        sample, stamp, uncertainty = anchor
        if type(sample) is not int or sample <= previous or sample < 0:
            raise ValueError("unordered clock anchors")
        if not finite(stamp) or stamp < 0 or not finite(uncertainty) or uncertainty < 0:
            raise ValueError("invalid clock anchor")
        offset = stamp - sample*1000/sample_rate
        lower.append(offset-uncertainty)
        upper.append(offset+uncertainty)
        previous = sample
    low, high = max(lower), min(upper)
    if low > high:
        raise ValueError("clock drift exceeds uncertainty")
    return dict(offset_ms=(low+high)/2, uncertainty_ms=(high-low)/2,
                first_sample=anchors[0][0], last_sample=anchors[-1][0],
                sample_rate=sample_rate)


def continuity(blocks, sample_rate):
    """Capture transport continuity, NOT audible speech gap detection.

    Each block describes actual delivered capture samples, with backend overrun
    count. Unknown status is rejected. Speech silence is not an underrun.
    """
    if type(sample_rate) is not int or not 8000 <= sample_rate <= 192000:
        raise ValueError("invalid rate")
    if type(blocks) is not list or not 1 <= len(blocks) <= 10000:
        raise ValueError("missing capture continuity")
    frontier, previous, gaps, overlaps, underruns = None, -1, 0, 0, 0
    for block in blocks:
        if type(block) is not dict or set(block) != {"start_sample", "samples", "underruns"}:
            raise ValueError("invalid block schema")
        start, count, lost = (block[k] for k in ("start_sample", "samples", "underruns"))
        if any(type(x) is not int for x in (start, count, lost)):
            raise ValueError("unknown capture continuity")
        if start < 0 or count <= 0 or lost < 0 or start < previous:
            raise ValueError("invalid capture continuity")
        end = start+count
        if frontier is not None:
            gaps += max(0, start-frontier)
            overlaps += max(0, min(end, frontier)-start)
        frontier = end if frontier is None else max(frontier, end)
        previous = start
        underruns += lost
    return dict(gap_ms=gaps*1000/sample_rate, overlap_ms=overlaps*1000/sample_rate,
                underruns=underruns, continuity_scope="capture_transport_only")


def analyze_window(reference, pcm, *, window_start_sample, request_ms, clock,
                   blocks, scope):
    """Consume an owned mutable PCM list and zero it on success/error.

    Caller must prevent aliases/copies and release device buffers itself. Python
    zeroing is not a guarantee of physical-memory erasure or backend cleanup.
    """
    if type(pcm) is not list:
        raise ValueError("owned mutable PCM list required")
    try:
        fields = {"offset_ms", "uncertainty_ms", "first_sample", "last_sample", "sample_rate"}
        if type(clock) is not dict or set(clock) != fields:
            raise ValueError("calibration required")
        if (any(not finite(clock[k]) for k in ("offset_ms", "uncertainty_ms"))
                or clock["uncertainty_ms"] < 0
                or any(type(clock[k]) is not int for k in
                       ("first_sample", "last_sample", "sample_rate"))
                or not 0 <= clock["first_sample"] < clock["last_sample"]):
            raise ValueError("invalid calibration")
        if type(window_start_sample) is not int or window_start_sample < 0:
            raise ValueError("invalid window start")
        if (window_start_sample < clock["first_sample"] or
                window_start_sample+len(pcm) > clock["last_sample"]):
            raise ValueError("window outside clock calibration")
        transport = continuity(blocks, clock["sample_rate"])
        if blocks[0]["start_sample"] != window_start_sample:
            raise ValueError("continuity window mismatch")
        if max(b["start_sample"]+b["samples"] for b in blocks) != window_start_sample+len(pcm):
            raise ValueError("continuity window mismatch")
        result = onset(reference, pcm, sample_rate=clock["sample_rate"],
                       capture_start_ms=clock["offset_ms"]+window_start_sample*1000/clock["sample_rate"],
                       request_ms=request_ms, clock_uncertainty_ms=clock["uncertainty_ms"],
                       scope=scope)
        result.update(transport)
        # Loss/overlap invalidates timing rather than trusting reconstructed data.
        if any(transport[k] for k in ("gap_ms", "overlap_ms", "underruns")):
            result = dict(valid=False, reason="capture_failed", scope=scope, **transport)
        return result
    finally:
        for i in range(len(pcm)):
            pcm[i] = 0.0


def capture_budget(*, remaining_seconds, window_seconds, calibration_seconds,
                   other_lanes_seconds, retry_seconds):
    """Two fixtures, 30 pairs, two modes, two native browsers. No authority."""
    values = (remaining_seconds, window_seconds, calibration_seconds,
              other_lanes_seconds, retry_seconds)
    if any(not finite(x) or x < 0 for x in values) or window_seconds <= 0:
        raise ValueError("invalid budget")
    if remaining_seconds > 600:
        raise ValueError("programme ceiling exceeded")
    observations = 2*30*2*2
    total = observations*window_seconds+calibration_seconds+other_lanes_seconds+retry_seconds
    return dict(observations=observations, planned_seconds=total,
                remaining_seconds=remaining_seconds, fits=total <= remaining_seconds,
                slack_seconds=remaining_seconds-total, capture_authorized=False)
