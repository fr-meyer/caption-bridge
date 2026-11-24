"""Hosted macOS no-input qualification only; never physical admission or acceptance.

Run from repository root: python3 -m native.caption_helper.qualify_capture_noinput BIN
Caller reviews exact built controller first. Temporary ledger deliberately retains
its HOLD; this harness cannot accept an attended programme ledger or device id.
"""
import json
import sys
import tempfile
from pathlib import Path

from native.caption_helper.capture_diagnostics import CaptureDiagnostics
from scripts.attended_helper_budget import Custody
from scripts.attended_journal import Journal
from scripts.attended_native_launch import qualify_noinput


def main():
    if sys.platform != 'darwin' or len(sys.argv) != 2:
        return 64
    diagnostics = CaptureDiagnostics()
    journal = None
    try:
        with tempfile.TemporaryDirectory(prefix='caption-noinput-') as scratch:
            path = Path(scratch) / 'qualification-ledger'
            Journal.initialize(path, '0' * 64)
            journal = Journal(path, '0' * 64)
            try:
                result = qualify_noinput(sys.argv[1], Custody(journal), '0' * 40,
                                         _diagnostics=diagnostics)
                if journal.active is None:
                    raise RuntimeError('noinput_hold_lost')
                print(json.dumps(result, sort_keys=True))
            finally:
                journal.close()
    except Exception as error:
        # No traceback/exception text/native stdout/stderr: only bounded primitives.
        hold = journal.active is not None if journal is not None else None
        print(json.dumps(diagnostics.receipt(error, journal_hold=hold), sort_keys=True))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
