"""Failure-only observations, never closure acceptance or raw process logging."""
from __future__ import annotations

from native.caption_helper.qualify_assembly import validate_startup

_TERMINAL_KEYS = {'schema', 'capture_exit', 'capture', 'terminal', 'pids',
                  'wait_status', 'cleanup_killed'}
_FAILURE_KEYS = {'stage', 'role', 'errno_class', 'reader_events', 'cleanup_errors', 'events', 'wait_status',
                 'timing_valid', 'elapsed_ns', 'window_ns', 'deadline_reached'}
_FAILURE_STAGES = frozenset('''SIGNAL_POLICY STOP_FLAGS TIMEBASE BUDGET STARTUP_DEADLINE
PIPE_SETUP PIPE_FLAGS PATH_BOUNDS PRELAUNCH_STOP PARENT_CHANGED STATE_SETUP SPAWN_SETUP GROUP_CUSTODY
IDENTITY_VERIFY CAPABILITY READINESS_DEADLINE READINESS_EOF READINESS_ID READINESS_IO
FD_CLOSE SPAWN_ACTION_DESTROY SPAWN_ATTR_DESTROY STARTUP_OUTPUT OBSERVE_OWNED CHILD_STATUS
ACTIVE_DEADLINE STOP_POLL STOP_READER WALL_EXPIRED LOOP_SLEEP OBSERVATION_INCOMPLETE
GROUP_OBSERVE GROUP_SIGNAL REAP_WAIT REAP_SIGNAL REAP_TIMEOUT IDENTITY_VISIBLE
IDENTITY_QUERY DIAGNOSTIC_INVALID
GROUP_PGID PIN_ARGUMENT PIN_WAIT PIN_TERMINAL PIN_METADATA_QUERY PIN_METADATA_SIZE PIN_METADATA_PID PIN_ZOMBIE PIN_PARENT PIN_GROUP PIN_RUID PIN_EUID PIN_BIRTH_SEC PIN_BIRTH_USEC PIN_WAIT_EVENT PIN_WAIT_STATE'''.split())
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


def failure_shape_valid(value):
    """Fixed-enum causal observation only; never a closure or timing proof."""
    if type(value) is not dict or set(value) not in (_FAILURE_KEYS, _FAILURE_KEYS | {'wait_event'}):
        return False
    event = value.get('wait_event')
    if event is not None:
        if type(event) is not dict or set(event) != {'signo', 'code', 'status', 'pid_relation'}:
            return False
        if any(type(event[key]) is not int or not -(2 ** 31) <= event[key] < 2 ** 31
               for key in ('signo', 'code', 'status')):
            return False
        if type(event['pid_relation']) is not int or event['pid_relation'] not in (0, 1, 2):
            return False
    if (type(value['stage']) is str
            and value['stage'] in {'PIN_WAIT_EVENT', 'PIN_WAIT_STATE'} and event is None):
        return False
    if type(value['stage']) is not str or value['stage'] not in _FAILURE_STAGES:
        return False
    if (type(value['errno_class']) is not str or value['errno_class'] not in
            {'NONE', 'EINTR', 'EBADF', 'ECHILD', 'EPERM', 'ESRCH', 'EINVAL', 'OTHER'}):
        return False
    for key, upper in (('role', 3), ('reader_events', 15), ('cleanup_errors', 31)):
        if type(value[key]) is not int or not 0 <= value[key] <= upper:
            return False
    events = value['events']
    if (type(events) is not list or len(events) > 16
            or any(type(event) is not int or not 1 <= event <= 14 for event in events)
            or len(set(events)) != len(events)):
        return False
    statuses = value['wait_status']
    if (type(statuses) is not list or len(statuses) != 3
            or any(type(status) is not int or not -1 <= status <= 65535 for status in statuses)):
        return False
    if type(value['timing_valid']) is not bool:
        return False
    elapsed, window, reached = (value[k] for k in ('elapsed_ns', 'window_ns', 'deadline_reached'))
    if type(elapsed) is not int or type(window) is not int:
        return False
    if value['timing_valid']:
        if (not 0 <= elapsed <= 10_000_000_000 or not 1 <= window <= 2_000_000_000
                or type(reached) is not bool
                or (reached and elapsed < window) or (not reached and elapsed > window)):
            return False
    elif elapsed != 0 or window != 0 or (reached is not None and type(reached) is not bool):
        return False
    return True


def terminal_shape_error(value):
    """Fixed field labels only; never echo malformed keys or values."""
    if type(value) is not dict:
        return 'type'
    if type(value.get('schema')) is not int or value['schema'] not in (1, 2):
        return 'schema'
    keys = _TERMINAL_KEYS | ({'failure'} if value['schema'] == 2 else set())
    if set(value) != keys:
        return 'fields'
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
    if value['schema'] == 2 and (value['capture_exit'] != 70
                                 or not failure_shape_valid(value['failure'])):
        return 'failure'
    return None


def validated_terminal(value):
    """Validate shape ONLY, allowing actual failure/unknown status observations.

    This is NOT the strict launch success validator: -1 unknown statuses and
    cleanup kills remain diagnostic FAIL/HOLD, never accepted closure.
    """
    if terminal_shape_error(value) is not None:
        return None
    # Reconstruct only allowlisted primitive fields; never return input aliases.
    terminal = dict(schema=value['schema'], capture_exit=value['capture_exit'], capture=value['capture'],
                    terminal='HOLD', pids=list(value['pids']), wait_status=list(value['wait_status']),
                    cleanup_killed=list(value['cleanup_killed']))
    if value['schema'] == 2:
        terminal['failure'] = {key: (list(item) if type(item) is list else
                                           dict(item) if type(item) is dict else item)
                               for key, item in value['failure'].items()}
    return terminal


class CaptureDiagnostics:
    """Owned by the no-input CLI; collection does not alter any launch decisions."""
    def __init__(self):
        self.stage = 'preflight'
        self.returncode = None
        self.startup = None
        self.terminal = None
        self.cleanup = dict.fromkeys(_CLEANUP, False)

    def observe_native_failure(self, packet):
        # Early C failure may replace challenge/startup, but can NEVER replace
        # their validators or admit a launch. Retain only the validated diagnostic.
        terminal = validated_terminal(packet)
        if terminal is not None and terminal['schema'] == 2:
            self.terminal = terminal

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
