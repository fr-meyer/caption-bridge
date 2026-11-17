"""Offline PCM correlation and summaries. No device, network or persistence APIs."""
import math
import statistics
from collections import Counter


def finite(x):
    return type(x) in (int, float) and math.isfinite(x)


def marker():
    """Deterministic public calibration signal, NOT a speech fixture."""
    state, result = 7, []
    for _ in range(127):
        state = (1103515245 * state + 12345) & 0x7fffffff
        result.append(0.25 if state & 0x10000 else -0.25)
    return result


def correlate(reference, captured, threshold=0.9):
    """Normalized DC-removed polarity-invariant match in bounded offline arrays."""
    if type(reference) not in (list, tuple) or type(captured) not in (list, tuple):
        raise ValueError("PCM sequences required")
    if not 32 <= len(reference) <= 512 or not len(reference) <= len(captured) <= 24000:
        raise ValueError("invalid correlation bounds")
    if not finite(threshold) or not 0.5 <= threshold <= 1:
        raise ValueError("invalid threshold")
    if any(not finite(x) or abs(x) > 1 for x in [*reference, *captured]):
        raise ValueError("invalid PCM")
    n = len(reference)
    mean = statistics.mean(reference)
    ref = [x - mean for x in reference]
    energy = sum(x*x for x in ref)
    if energy < 1e-12:
        raise ValueError("silent reference")
    matches = []
    for offset in range(len(captured) - n + 1):
        window = captured[offset:offset+n]
        mean = sum(window)/n
        power = sum((x-mean)**2 for x in window)
        score = abs(sum(a*(b-mean) for a, b in zip(ref, window)))
        score = score / math.sqrt(energy*power) if power > 1e-12 else 0
        if score >= threshold:
            matches.append((offset, score))
    if not matches:
        return dict(valid=False, reason="marker_missing")
    offset, score = max(matches, key=lambda item: item[1])
    # One adjacent sample may belong to the same correlation lobe. Equal
    # competing peaks, even adjacent, and any remote match are ambiguous.
    if any(pos != offset and (abs(pos-offset) > 1 or abs(value-score) < 1e-9)
           for pos, value in matches):
        return dict(valid=False, reason="ambiguous_marker")
    return dict(valid=True, offset_samples=offset, correlation=score)


def onset(reference, captured, *, sample_rate, capture_start_ms, request_ms,
          clock_uncertainty_ms, scope):
    if scope not in {"digital_loopback", "acoustic"}:
        raise ValueError("output scope required")
    if type(sample_rate) is not int or not 8000 <= sample_rate <= 192000:
        raise ValueError("invalid sample rate")
    if any(not finite(x) or x < 0 for x in
           (capture_start_ms, request_ms, clock_uncertainty_ms)):
        raise ValueError("calibrated clock required")
    result = correlate(reference, captured)
    result.update(scope=scope, clock_uncertainty_ms=clock_uncertainty_ms)
    if result["valid"]:
        latency = capture_start_ms + result["offset_samples"]*1000/sample_rate - request_ms
        if latency < 0:
            return dict(valid=False, reason="onset_before_request", scope=scope)
        result["request_to_output_ms"] = latency
    return result


def distribution(values):
    if not values:
        return dict(n=0, p50_ms=None, p95_ms=None)
    return dict(n=len(values), p50_ms=statistics.median(values),
                p95_ms=sorted(values)[math.ceil(.95*len(values))-1])


def summarize(rows):
    """One browser/scope/fixture, invalid attempts retained; no acceptance inference."""
    fields = {"pair_id", "mode", "browser", "scope", "fixture_id", "valid",
              "reason", "latency_ms", "gap_ms", "overlap_ms", "underruns"}
    reasons = {"ok", "marker_missing", "ambiguous_marker", "clock_invalid",
               "cancelled", "timeout", "capture_failed", "onset_before_request"}
    if type(rows) is not list or not 1 <= len(rows) <= 10000:
        raise ValueError("empty observations")
    identities, seen, groups = set(), set(), {"buffered": [], "progressive": []}
    for row in rows:
        if type(row) is not dict or set(row) != fields:
            raise ValueError("invalid observation schema")
        if type(row["mode"]) is not str or row["mode"] not in groups:
            raise ValueError("invalid observation schema")
        if type(row["scope"]) is not str or row["scope"] not in {"scheduling", "digital_loopback", "acoustic"}:
            raise ValueError("invalid scope")
        if any(not isinstance(row[k], str) or not row[k] or len(row[k]) > 128
               for k in ("pair_id", "browser", "fixture_id")):
            raise ValueError("invalid identity")
        key = (row["pair_id"], row["mode"])
        if key in seen:
            raise ValueError("duplicate attempt")
        seen.add(key)
        identities.add((row["browser"], row["scope"], row["fixture_id"]))
        if (type(row["valid"]) is not bool or type(row["reason"]) is not str
                or row["reason"] not in reasons):
            raise ValueError("invalid status")
        if row["valid"] != (row["reason"] == "ok"):
            raise ValueError("inconsistent status")
        if row["valid"]:
            if not finite(row["latency_ms"]) or row["latency_ms"] < 0:
                raise ValueError("invalid latency")
        elif row["latency_ms"] is not None:
            raise ValueError("invalid samples must not carry latency")
        for field in ("gap_ms", "overlap_ms", "underruns"):
            if row[field] is None and not row["valid"]:
                continue
            if not finite(row[field]) or row[field] < 0:
                raise ValueError("invalid continuity metric")
        if row["underruns"] is not None and type(row["underruns"]) is not int:
            raise ValueError("invalid underrun count")
        groups[row["mode"]].append(row)
    if len(identities) != 1:
        raise ValueError("do not pool browsers, scopes or fixtures")
    output = {}
    for mode, samples in groups.items():
        valid = [r for r in samples if r["valid"]]
        output[mode] = dict(attempts=len(samples), valid=len(valid),
                            invalid=len(samples)-len(valid),
                            reasons=dict(Counter(r["reason"] for r in samples)),
                            latency=distribution([r["latency_ms"] for r in valid]),
                            **{k: (None if any(r[k] is None for r in samples)
                                   else sum(r[k] for r in samples))
                               for k in ("gap_ms", "overlap_ms", "underruns")},
                            continuity_unknown_counts={
                                k: sum(r[k] is None for r in samples)
                                for k in ("gap_ms", "overlap_ms", "underruns")},
                            continuity_known_sums={
                                k: sum(r[k] for r in samples if r[k] is not None)
                                for k in ("gap_ms", "overlap_ms", "underruns")})
    baseline = {r["pair_id"]: r for r in groups["buffered"]}
    candidate = {r["pair_id"]: r for r in groups["progressive"]}
    paired = [key for key in baseline.keys() & candidate.keys()
              if baseline[key]["valid"] and candidate[key]["valid"]]
    output.update(scope=next(iter(identities))[1], paired_valid=len(paired),
                  unpaired_attempts=len(baseline.keys() ^ candidate.keys()),
                  minimum_met=len(paired) >= 30,
                  paired_delta_ms=distribution([candidate[k]["latency_ms"] -
                                                baseline[k]["latency_ms"] for k in paired]),
                  human_quality="pending", acceptance="not_evaluated")
    return output
