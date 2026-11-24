"""Failure-only observations, never closure acceptance or raw process logging."""
from __future__ import annotations

from native.caption_helper.qualify_assembly import validate_startup

_TERMINAL_KEYS = {'schema', 'capture_exit', 'capture', 'terminal', 'pids',
                  'wait_status', 'cleanup_killed'}
_STAGES = {'preflight', 'spawn', 'challenge', 'debit', 'budget_delivery', 'startup',
           'terminal_read', 'controller_wait', 'eof', 'terminal_validate', 'complete'}
_ERRORS = {'RuntimeError', 'ValueError', 'OSError', 'TimeoutError', 'JSONDecodeError',
           'BrokenPipeError', 'FileNotFoundError', 'PermissionError', 'TimeoutExpired'}
_REASONS = {'capture_terminal_unknown_hold', 'capture_termination_unknown_hold',
            'capture_startup_unknown_hold', 'capture_budget_short_write_hold',
            'capture_terminal_timeout_hold', 'capture_eof_timeout_hold',
            'capture_trailing_output_hold'}
_CLEANUP = ('emergency_closed', 'wait_completed', 'kill_sent', 'streams_closed',
            'peer_closed', 'custody_revoked')


def terminal_shape_error(value):
    """Fixed field labels only; never echo malformed keys or values."""
    if type(value) is not dict:
        return 'type'
    if set(value) != _TERMINAL_KEYS:
        return 'fields'
    if type(value['schema']) is not int or value['schema'] != 1:
        return 'schema'
    if type(value['capture']) is not bool:
        return 'capture'
    if type(value['capture_exit']) is not int or not 0 <= value['capture_exit'] <= 255:
        return 'capture_exit'
    if value['terminal'] != 'HOLD':
        return 'terminal'
    for key in ('pids', 'wait_status', 'cleanup_killed'):
        if (type(value[key]) is not list or len(value[key]) != 3
                or any(type(item) is not int for item in value[key])):
            return key
    if (any(pid != -1 and not 1 < pid < 2**31 for pid in value['pids'])
            or len(set(pid for pid in value['pids'] if pid != -1))
            != sum(pid != -1 for pid in value['pids'])):
        return 'pids'
    if any(not -1 <= status <= 65535 for status in value['wait_status']):
        return 'wait_status'
    if any(killed not in (0, 1) for killed in value['cleanup_killed']):
        return 'cleanup_killed'
    return None


def validated_terminal(value):
    """Validate shape ONLY, allowing actual failure/unknown status observations.

    This is NOT the strict launch success validator: -1 unknown statuses and
    cleanup kills remain diagnostic FAIL/HOLD, never accepted closure.
    """
    if terminal_shape_error(value) is not None:
        return None
    # Reconstruct only allowlisted primitive fields; never return input aliases.
    return dict(schema=1, capture_exit=value['capture_exit'], capture=value['capture'],
                terminal='HOLD', pids=list(value['pids']), wait_status=list(value['wait_status']),
                cleanup_killed=list(value['cleanup_killed']))


class CaptureDiagnostics:
    """Owned by the no-input CLI; collection does not alter any launch decisions."""
    def __init__(self):
        self.stage = 'preflight'
        self.returncode = None
        self.startup = None
        self.terminal = None
        self.cleanup = dict.fromkeys(_CLEANUP, False)

    def receipt(self, error, *, journal_hold=None):
        terminal = validated_terminal(self.terminal)
        startup = validate_startup(self.startup)
        error_class = type(error).__name__
        reason = error.args[0] if error.args and type(error.args[0]) is str else None
        return dict(
            schema=1, qualification='NATIVE_CAPTURE_NOINPUT_DIAGNOSTIC', result='FAIL',
            native_admission=False, physical_acceptance=False, independent_closure_verified=False,
            terminal='HOLD', stage=self.stage if self.stage in _STAGES else 'unknown',
            error_class=error_class if error_class in _ERRORS else 'ERROR',
            reason=reason if reason in _REASONS else 'capture_failure',
            controller_returncode=(self.returncode if type(self.returncode) is int
                                   and -128 <= self.returncode <= 255 else None),
            startup_valid=startup is not None, terminal_shape_valid=terminal is not None,
            native_terminal=terminal, terminal_shape_error=terminal_shape_error(self.terminal),
            pids_match_startup=(terminal['pids'] == startup['pids']
                                if terminal is not None and startup is not None else None),
            journal_hold=journal_hold if type(journal_hold) is bool else None,
            parent_cleanup={key: self.cleanup.get(key) is True for key in _CLEANUP})
