"""Offline plan check only. Does not open devices or authorize capture."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CAP_MS = 600_000
PROOFS = ('network_deny', 'hard_watchdog', 'emergency_stop', 'single_capture',
          'output_fail_closed', 'owned_cleanup')


def integer(value):
    return type(value) is int and value >= 0


def hex_id(value, length):
    return (isinstance(value, str) and len(value) == length
            and all(c in '0123456789abcdef' for c in value))


def validate(packet):
    """Content-free failures. Coordinator owns the complete programme ledger."""
    errors = []
    fields = {'schema', 'candidate_sha', 'meeting_ended', 'participant_ready',
              'private_quiet', 'proofs', 'ledger', 'requested_ms'}
    if not isinstance(packet, dict) or set(packet) != fields:
        return ['packet_shape']
    if packet['schema'] != 'caption-attended-v1':
        errors.append('schema')
    sha = packet['candidate_sha']
    if not hex_id(sha, 40):
        errors.append('candidate_sha')
    for flag in ('meeting_ended', 'participant_ready', 'private_quiet'):
        if packet[flag] is not True:
            errors.append(flag)
    proofs = packet['proofs']
    if not isinstance(proofs, dict) or set(proofs) != set(PROOFS):
        errors.append('proofs_shape')
    else:
        for key in PROOFS:
            proof = proofs[key]
            if (not isinstance(proof, dict) or set(proof) != {'sha256', 'candidate_sha'}
                    or proof['candidate_sha'] != sha or not hex_id(proof['sha256'], 64)):
                errors.append('proof_' + key)
    ledger = packet['ledger']
    charged = 0
    if not isinstance(ledger, list):
        errors.append('ledger_shape')
    else:
        for index, row in enumerate(ledger, 1):
            if (not isinstance(row, dict)
                    or set(row) != {'sequence', 'reserved_ms', 'elapsed_ms', 'closed'}):
                errors.append('ledger_row')
                continue
            seq, reserved, elapsed = row['sequence'], row['reserved_ms'], row['elapsed_ms']
            if not integer(seq) or seq != index:
                errors.append('ledger_sequence')
            if not integer(reserved) or reserved == 0 or not integer(elapsed):
                errors.append('ledger_duration')
                continue
            # No refund: failed/interrupted attempts retain their entire reservation.
            charged += max(reserved, elapsed)
            if row['closed'] is not True:
                errors.append('unclosed_capture')
            if elapsed > reserved:
                errors.append('watchdog_overrun')
    requested = packet['requested_ms']
    if not integer(requested) or requested == 0:
        errors.append('requested_ms')
    elif charged + requested > CAP_MS:
        errors.append('programme_cap')
    return sorted(set(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packet', type=Path)
    args = parser.parse_args()
    try:
        errors = validate(json.loads(args.packet.read_text(encoding='utf-8')))
    except (OSError, ValueError):
        errors = ['packet_unreadable']
    print(json.dumps({'plan_valid': not errors, 'capture_authorized': False,
                      'hardware_verified': False, 'errors': errors}))
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
