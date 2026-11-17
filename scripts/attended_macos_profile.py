"""Source-only fixed macOS profile. No launch/native admission implementation."""
from __future__ import annotations

import hashlib
import plistlib
from dataclasses import dataclass
from pathlib import Path

from scripts.attended_acceptance import hex_id

# Exact allowlist, NOT a claim that this unsigned plist activates App Sandbox.
ENTITLEMENTS = {'com.apple.security.app-sandbox': True,
                'com.apple.security.device.microphone': True}
ROLES = ('capture', 'guardian_a', 'guardian_b')
CHECKS = ('signature_entitlements', 'kernel_egress_denied', 'single_stream',
          'deadline_close', 'controller_death_close', 'guardian_death_close',
          'mute_before_route_change', 'native_cleanup')


@dataclass(frozen=True)
class Preflight:
    source_bound: bool
    missing: tuple[str, ...]
    native_admission: bool = False


def preflight(candidate, binaries, entitlements, receipts):
    """Inspect supplied bytes only. No subprocess, device or host inspection.

    Signed-binary/receipt authenticity is deliberately not inferred from hashes.
    No receipt or flag can turn this source-only profile into launch authority.
    """
    missing = []
    if not hex_id(candidate, 40):
        missing.append('candidate')
    if not isinstance(binaries, dict) or set(binaries) != set(ROLES):
        missing.append('fixed_roles')
    else:
        for role in ROLES:
            item = binaries[role]
            if (not isinstance(item, dict) or set(item) != {'bytes', 'sha256'}
                    or not isinstance(item['bytes'], bytes) or not item['bytes']
                    or hashlib.sha256(item['bytes']).hexdigest() != item['sha256']):
                missing.append(role + '_hash')
    try:
        parsed = plistlib.loads(entitlements)
        if (parsed != ENTITLEMENTS
                or any(type(value) is not bool for value in parsed.values())):
            missing.append('entitlement_allowlist')
    except (ValueError, TypeError, plistlib.InvalidFileException):
        missing.append('entitlement_format')
    # No accepted attestation trust root/platform implementation exists yet.
    if receipts:
        missing.append('untrusted_attestation')
    missing.extend(CHECKS)
    missing.append('native_launcher_not_qualified')
    return Preflight(not any(x in missing for x in ('candidate', 'fixed_roles',
                     'capture_hash', 'guardian_a_hash', 'guardian_b_hash',
                     'entitlement_allowlist', 'entitlement_format')), tuple(missing))


def native_launch(*_args, **_kwargs):
    raise RuntimeError('macos_native_profile_disabled')


class LifetimeModel:
    """Executable protocol model for fake backend tests, NOT a process guardian.

    The only route transition first emits mute. Dead guardian/controller or expired
    lease produces terminal close; renewed heartbeats cannot revive it. Real native
    binding must implement these actions independently of the application event loop.
    """
    def __init__(self, deadline_ns):
        if type(deadline_ns) is not int or deadline_ns <= 0:
            raise ValueError('deadline')
        self.deadline = deadline_ns
        self.state = 'armed'
        self.muted = True
        self.last_ns = 0

    def step(self, event, now_ns):
        if self.state == 'closed':
            return ()
        if type(now_ns) is not int or now_ns < self.last_ns:
            event = 'clock_failure'
        else:
            self.last_ns = now_ns
        if (event in ('stop', 'controller_eof', 'guardian_a_eof', 'guardian_b_eof',
                      'backend_error', 'clock_failure') or self.last_ns >= self.deadline):
            self.state = 'closed'
            self.muted = True
            return ('mute', 'close_input', 'verify_closed')
        if event == 'open' and self.state == 'armed':
            self.state = 'capturing'
            return ('open_single_input',)
        if event == 'route_change':
            self.muted = True
            return ('mute', 'invalidate_route')
        # No output-unmute event: B owns output validation and human readiness.
        if event not in ('tick',):
            self.state = 'closed'
            self.muted = True
            return ('mute', 'close_input', 'verify_closed')
        return ()


def write_entitlements(path):
    """Exclusive local source artifact only, not codesigning or installation."""
    with Path(path).open('xb') as output:
        plistlib.dump(ENTITLEMENTS, output, sort_keys=True)
