"""Content-free retention around the existing hosted noinput commands, never admission.

This script never launches the native build or qualifier. Their original Bash
commands and process ancestry remain unchanged; raw child output stays private.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from native.caption_helper.capture_diagnostics import (  # noqa: E402
    _CLEANUP,
    _ERRORS,
    _REASONS,
    _STAGES,
    terminal_shape_error,
)

IMAGES = ('CaptureController', 'CaptureGuardianA', 'CaptureGuardianB', 'CaptureHelper')
ROLES = IMAGES[1:]
IDENTIFIERS = dict(zip(IMAGES, ('local.captionbridge.capture.controller',) + tuple(
    'local.captionbridge.' + name for name in ROLES), strict=True))
SOURCE_FILES = (
    '.github/workflows/ci.yml', 'scripts/ci_capture_noinput_provenance.py',
    'scripts/build_caption_helper.sh', 'scripts/attended_native_launch.py',
    'scripts/attended_helper_budget.py', 'scripts/attended_journal.py',
    'scripts/attended_native_admission.py', 'scripts/attended_native_clock.py',
    'native/caption_helper/build_capture.sh', 'native/caption_helper/main.c',
    'native/caption_helper/supervised.c', 'native/caption_helper/role.c',
    'native/caption_helper/assembly.c', 'native/caption_helper/identity.c',
    'native/caption_helper/state_matrix.c', 'native/caption_helper/budget.h',
    'native/caption_helper/input_state.h', 'native/caption_helper/pcm_transport.h',
    'native/caption_helper/entitlements.plist', 'native/caption_helper/generate_pins.py',
    'native/caption_helper/capture_controller.c', 'native/caption_helper/capture_guardian.c',
    'native/caption_helper/capture_role.c', 'native/caption_helper/capture_input.c',
    'native/caption_helper/capture_input.h', 'native/caption_helper/capture_protocol.h',
    'native/caption_helper/capture_diagnostic.h', 'native/caption_helper/capture_entitlements.plist',
    'native/caption_helper/generate_capture_pins.py',
    'native/caption_helper/qualify_capture_noinput.py',
    'native/caption_helper/capture_diagnostics.py', 'native/caption_helper/qualify_assembly.py',
    'native/caption_helper/qualify_budget.py',
)
FAILURE_KEYS = frozenset('''schema qualification result native_admission physical_acceptance
independent_closure_verified terminal stage error_class reason controller_returncode startup_valid
terminal_shape_valid native_terminal terminal_shape_error pids_match_startup journal_hold
parent_cleanup'''.split())
SUCCESS_KEYS = frozenset('''qualification physical_acceptance native_admission terminal
sequence reserved_ms'''.split())
SHAPE_ERRORS = frozenset('''type schema fields capture capture_exit terminal pids wait_status
cleanup_killed failure'''.split())
ERRORS = frozenset('''SOURCE_BINDING FILE_SHAPE CODE_SIGNATURE GENERATED_PINS BUILD_STATUS_UNAVAILABLE
QUALIFIER_STATUS_UNAVAILABLE RECEIPT_SCHEMA SOURCE_DRIFT IMAGE_DRIFT ARTIFACT_SCHEMA INTERNAL'''.split())
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
CDHASH = re.compile(r'[0-9a-f]{40,64}\Z')
MAX_JSON = 32768
MANIFEST = 'capture-noinput-provenance.json'
RECEIPT = 'capture-noinput-qualifier.json'


class Rejected(Exception):
    def __init__(self, code):
        self.code = code


def require(condition, code='ARTIFACT_SCHEMA'):
    if not condition:
        raise Rejected(code)


def regular_bytes(path, limit):
    """Never follow a leaf symlink or publish its name/contents on error."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and 0 <= info.st_size <= limit, 'FILE_SHAPE')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            value = stream.read(limit + 1)
        require(len(value) == info.st_size and len(value) <= limit, 'FILE_SHAPE')
        return value
    finally:
        os.close(fd)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def strict_json(value):
    require(len(value) <= MAX_JSON, 'RECEIPT_SCHEMA')

    def pairs(items):
        out = {}
        for key, item in items:
            require(key not in out, 'RECEIPT_SCHEMA')
            out[key] = item
        return out

    try:
        return json.loads(value, object_pairs_hook=pairs,
                          parse_constant=lambda _: require(False, 'RECEIPT_SCHEMA'))
    except (ValueError, RecursionError, UnicodeError):
        raise Rejected('RECEIPT_SCHEMA') from None


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def checked_receipt(value, returncode):
    """Exact fixed schemas only. Failure observations never become acceptance."""
    require(type(value) is dict, 'RECEIPT_SCHEMA')
    require(value.get('physical_acceptance') is False
            and value.get('native_admission') is False, 'RECEIPT_SCHEMA')
    if value.get('qualification') == 'NATIVE_CAPTURE_NOINPUT_DIAGNOSTIC':
        require(set(value) == FAILURE_KEYS and returncode != 0, 'RECEIPT_SCHEMA')
        require(type(value['schema']) is int and value['schema'] == 1
                and value['result'] == 'FAIL' and value['terminal'] == 'HOLD'
                and value['independent_closure_verified'] is False, 'RECEIPT_SCHEMA')
        require(value['stage'] in _STAGES | {'unknown'}
                and value['error_class'] in _ERRORS | {'ERROR'}
                and value['reason'] in _REASONS | {'capture_failure'}, 'RECEIPT_SCHEMA')
        require(value['controller_returncode'] is None
                or integer(value['controller_returncode'], -128, 255), 'RECEIPT_SCHEMA')
        for key in ('startup_valid', 'terminal_shape_valid'):
            require(type(value[key]) is bool, 'RECEIPT_SCHEMA')
        for key in ('pids_match_startup', 'journal_hold'):
            require(value[key] is None or type(value[key]) is bool, 'RECEIPT_SCHEMA')
        cleanup = value['parent_cleanup']
        require(type(cleanup) is dict and set(cleanup) == set(_CLEANUP)
                and all(type(item) is bool for item in cleanup.values()), 'RECEIPT_SCHEMA')
        terminal = value['native_terminal']
        if terminal is None:
            require(value['terminal_shape_valid'] is False
                    and value['terminal_shape_error'] in SHAPE_ERRORS, 'RECEIPT_SCHEMA')
        else:
            require(terminal_shape_error(terminal) is None
                    and terminal['capture'] is False and value['terminal_shape_valid'] is True
                    and value['terminal_shape_error'] is None, 'RECEIPT_SCHEMA')
        return value
    require(set(value) == SUCCESS_KEYS and returncode == 0
            and value.get('qualification') == 'NATIVE_CAPTURE_NOINPUT_ONLY', 'RECEIPT_SCHEMA')
    terminal = value['terminal']
    require(terminal_shape_error(terminal) is None and terminal['schema'] == 1
            and terminal['capture'] is False and terminal['capture_exit'] == 0
            and terminal['cleanup_killed'] == [0, 0, 0], 'RECEIPT_SCHEMA')
    for index, status in enumerate(terminal['wait_status']):
        require(status >= 0 and os.WIFEXITED(status)
                and os.WEXITSTATUS(status) in ((71, 72) if index == 2 else (72,)), 'RECEIPT_SCHEMA')
    require(all(pid > 1 for pid in terminal['pids'])
            and integer(value['sequence'], 1, 2**63 - 1)
            and integer(value['reserved_ms'], 1, 2000), 'RECEIPT_SCHEMA')
    return value


def tool(arguments):
    result = subprocess.run(arguments, cwd=ROOT, capture_output=True, timeout=5, check=False)
    require(result.returncode == 0 and len(result.stdout) + len(result.stderr) <= 262144,
            'SOURCE_BINDING' if arguments[0] == 'git' else 'CODE_SIGNATURE')
    return result.stdout, result.stderr


def source_binding(checkout, head):
    require(HEX40.fullmatch(checkout) and HEX40.fullmatch(head), 'SOURCE_BINDING')
    actual = tool(['git', 'rev-parse', 'HEAD'])[0].decode().strip()
    tree = tool(['git', 'rev-parse', 'HEAD^{tree}'])[0].decode().strip()
    require(actual == checkout and HEX40.fullmatch(tree), 'SOURCE_BINDING')
    tool(['git', 'diff', '--quiet', 'HEAD', '--'])
    hashes = {}
    for name in SOURCE_FILES:
        value = regular_bytes(ROOT / name, 262144)
        require(value == tool(['git', 'show', 'HEAD:' + name])[0], 'SOURCE_BINDING')
        hashes[name] = digest(value)
    return dict(checkout_commit=actual, checkout_tree=tree, event_head_commit=head,
                files_sha256=hashes)


def image_hashes(build):
    directory = build / 'CaptionHelper.app/Contents/MacOS'
    for path in (build, build / 'CaptionHelper.app', build / 'CaptionHelper.app/Contents', directory):
        require(path.is_dir() and not path.is_symlink(), 'FILE_SHAPE')
    return {name: digest(regular_bytes(directory / name, 32 * 1024 * 1024)) for name in IMAGES}


def signed_snapshot(build):
    hashes = image_hashes(build)
    directory = build / 'CaptionHelper.app/Contents/MacOS'
    images = {}
    for name in IMAGES:
        tool(['/usr/bin/codesign', '--verify', '--strict', str(directory / name)])
        out, err = tool(['/usr/bin/codesign', '-dv', '--verbose=4', str(directory / name)])
        text = (out + err).decode('utf-8', 'strict')
        identifiers = re.findall(r'^Identifier=(.+)$', text, re.M)
        cdhashes = re.findall(r'^CDHash=([0-9a-f]{40,64})$', text, re.M)
        require(identifiers == [IDENTIFIERS[name]] and len(cdhashes) == 1, 'CODE_SIGNATURE')
        images[name] = dict(sha256=hashes[name], identifier=identifiers[0], cdhash=cdhashes[0])
    pin_bytes = regular_bytes(build / 'capture_pins.h', 8192)
    identifiers = ','.join('"' + IDENTIFIERS[name] + '"' for name in ROLES)
    cdhashes = ','.join('"' + images[name]['cdhash'] + '"' for name in ROLES)
    expected = ('static const char *cb_role_identifiers[]={' + identifiers + '};\n'
                'static const char *cb_role_hashes[]={' + cdhashes + '};\n').encode()
    require(pin_bytes == expected, 'GENERATED_PINS')
    require(image_hashes(build) == hashes, 'IMAGE_DRIFT')
    return images, digest(pin_bytes)


def new_manifest():
    return dict(schema=1, qualification='CAPTURE_NOINPUT_PROVENANCE_ONLY', source=None,
                build_status='UNKNOWN', build_returncode=None, build_step_outcome='unknown',
                qualifier_step_outcome='unknown', images_before=None,
                generated_pins_before_sha256=None, qualifier_status='UNKNOWN',
                qualifier_returncode=None, qualifier_receipt_sha256=None, images_after=None,
                generated_pins_after_sha256=None, source_unchanged=None,
                images_unchanged=None, generated_pins_unchanged=None, provenance_error=None,
                native_admission=False, physical_acceptance=False)


def validate_manifest(value, receipt_bytes, *, final=True):
    """Independent disk readback shape check; no arbitrary keys/strings or paths."""
    require(type(value) is dict and set(value) == set(new_manifest()))
    require(type(value['schema']) is int and value['schema'] == 1
            and value['qualification'] == 'CAPTURE_NOINPUT_PROVENANCE_ONLY'
            and value['native_admission'] is False and value['physical_acceptance'] is False)
    require(value['build_status'] in {'UNKNOWN', 'NOT_RUN', 'PASSED', 'FAILED'})
    for key in ('build_step_outcome', 'qualifier_step_outcome'):
        require(value[key] in {'unknown', 'success', 'failure', 'cancelled', 'skipped'})
    require(value['qualifier_status'] in {'UNKNOWN', 'NOT_RUN', 'PASSED_LIMITED', 'FAILED_DIAGNOSTIC',
                                         'REJECTED'})
    require(value['provenance_error'] is None or value['provenance_error'] in ERRORS)
    for key in ('build_returncode', 'qualifier_returncode'):
        require(value[key] is None or integer(value[key], -128, 255))
    for key in ('source_unchanged', 'images_unchanged', 'generated_pins_unchanged'):
        require(value[key] is None or type(value[key]) is bool)
    source = value['source']
    if source is not None:
        require(type(source) is dict and set(source) == {
            'checkout_commit', 'checkout_tree', 'event_head_commit', 'files_sha256'})
        require(all(type(source[key]) is str and HEX40.fullmatch(source[key]) for key in (
            'checkout_commit', 'checkout_tree', 'event_head_commit')))
        require(type(source['files_sha256']) is dict
                and set(source['files_sha256']) == set(SOURCE_FILES)
                and all(type(item) is str and HEX64.fullmatch(item)
                        for item in source['files_sha256'].values()))
    before = value['images_before']
    if before is not None:
        require(type(before) is dict and set(before) == set(IMAGES))
        for name, image in before.items():
            require(type(image) is dict and set(image) == {'sha256', 'identifier', 'cdhash'}
                    and image['identifier'] == IDENTIFIERS[name]
                    and type(image['sha256']) is str and HEX64.fullmatch(image['sha256'])
                    and type(image['cdhash']) is str and CDHASH.fullmatch(image['cdhash']))
        require(value['build_status'] == 'PASSED' and value['build_returncode'] == 0)
    after = value['images_after']
    if after is not None:
        require(type(after) is dict and set(after) == set(IMAGES)
                and all(type(item) is str and HEX64.fullmatch(item) for item in after.values()))
    for key in ('generated_pins_before_sha256', 'generated_pins_after_sha256',
                'qualifier_receipt_sha256'):
        require(value[key] is None or type(value[key]) is str and HEX64.fullmatch(value[key]))
    require((before is None) == (value['generated_pins_before_sha256'] is None))
    require((after is None) == (value['generated_pins_after_sha256'] is None))
    if receipt_bytes is None:
        require(value['qualifier_receipt_sha256'] is None
                and value['qualifier_status'] not in {'PASSED_LIMITED', 'FAILED_DIAGNOSTIC'})
    else:
        require(value['qualifier_receipt_sha256'] == digest(receipt_bytes)
                and value['qualifier_status'] in {'PASSED_LIMITED', 'FAILED_DIAGNOSTIC'})
        require(type(value['qualifier_returncode']) is int)
        checked_receipt(strict_json(receipt_bytes), value['qualifier_returncode'])
        require(value['qualifier_status'] == (
            'PASSED_LIMITED' if value['qualifier_returncode'] == 0 else 'FAILED_DIAGNOSTIC'))
    if value['build_status'] == 'FAILED':
        require(value['build_returncode'] is not None and value['build_returncode'] != 0
                and before is None and after is None and value['qualifier_status'] == 'NOT_RUN')
    if value['build_status'] in {'UNKNOWN', 'NOT_RUN'}:
        require(value['build_returncode'] is None and before is None and after is None)
    if value['qualifier_status'] in {'UNKNOWN', 'NOT_RUN'}:
        require(value['qualifier_returncode'] is None and receipt_bytes is None)
    if before is None:
        require(after is None and value['images_unchanged'] is None
                and value['generated_pins_unchanged'] is None)
    if after is None:
        require(value['images_unchanged'] is None and value['generated_pins_unchanged'] is None)
    if before is not None and after is not None:
        require(value['images_unchanged'] is (after == {
            name: item['sha256'] for name, item in before.items()}))
        require(value['generated_pins_unchanged'] is (
            value['generated_pins_before_sha256'] == value['generated_pins_after_sha256']))
    if final and value['provenance_error'] is None:
        require(source is not None and value['build_status'] in {'PASSED', 'FAILED'})
        if value['build_status'] == 'PASSED':
            require(before is not None and after is not None
                    and value['source_unchanged'] is True and value['images_unchanged'] is True
                    and value['generated_pins_unchanged'] is True
                    and value['qualifier_status'] in {'PASSED_LIMITED', 'FAILED_DIAGNOSTIC'})


def verify_public(directory):
    require(directory.is_dir() and not directory.is_symlink())
    names = {path.name for path in directory.iterdir()}
    require(names in ({MANIFEST}, {MANIFEST, RECEIPT}))
    manifest_bytes = regular_bytes(directory / MANIFEST, MAX_JSON)
    receipt_bytes = regular_bytes(directory / RECEIPT, MAX_JSON) if RECEIPT in names else None
    value = strict_json(manifest_bytes)
    validate_manifest(value, receipt_bytes)
    require(manifest_bytes == canonical(value))
    if receipt_bytes is not None:
        require(receipt_bytes == canonical(strict_json(receipt_bytes)))
    require(len(manifest_bytes) + len(receipt_bytes or b'') <= 2 * MAX_JSON)
    return value


def publish(directory, manifest, receipt):
    receipt_bytes = canonical(receipt) if receipt is not None else None
    manifest['qualifier_receipt_sha256'] = digest(receipt_bytes) if receipt_bytes else None
    validate_manifest(manifest, receipt_bytes)
    staging = directory.with_name(directory.name + '.validated-staging')
    staging.mkdir(mode=0o700)
    for name, value in ((MANIFEST, canonical(manifest)), (RECEIPT, receipt_bytes)):
        if value is not None:
            require(len(value) <= MAX_JSON)
            with (staging / name).open('xb') as stream:
                stream.write(value)
            os.chmod(staging / name, 0o600)
    verify_public(staging)
    require(not directory.exists() and not directory.is_symlink())
    staging.rename(directory)
    verify_public(directory)


def save_checkpoint(directory, manifest):
    value = canonical(manifest)
    require(len(value) <= MAX_JSON)
    temporary = directory / 'checkpoint-next.json'
    with temporary.open('xb') as stream:
        stream.write(value)
    os.chmod(temporary, 0o600)
    temporary.replace(directory / 'checkpoint.json')


def load_checkpoint(directory):
    require(directory.is_dir() and not directory.is_symlink())
    value = strict_json(regular_bytes(directory / 'checkpoint.json', MAX_JSON))
    receipt_path = directory / 'validated-qualifier.json'
    receipt_bytes = regular_bytes(receipt_path, MAX_JSON) if receipt_path.exists() else None
    validate_manifest(value, receipt_bytes, final=False)
    return value, strict_json(receipt_bytes) if receipt_bytes is not None else None


def phase(args):
    """Observe only. Original sh/uv commands remain directly in their Bash steps."""
    manifest = new_manifest()
    try:
        if args.command == 'prepare':
            manifest['build_status'] = 'NOT_RUN'
            manifest['qualifier_status'] = 'NOT_RUN'
            args.private_dir.mkdir(mode=0o700)
            require(sys.platform == 'darwin', 'SOURCE_BINDING')
            manifest['source'] = source_binding(args.checkout, args.event_head)
        else:
            manifest, _ = load_checkpoint(args.private_dir)
            require(integer(args.returncode, 0, 255))
            if args.command == 'snapshot':
                manifest['build_returncode'] = args.returncode
                manifest['build_status'] = 'PASSED' if args.returncode == 0 else 'FAILED'
                if args.returncode == 0:
                    images, pins = signed_snapshot(args.build_root)
                    manifest['images_before'] = images
                    manifest['generated_pins_before_sha256'] = pins
            else:
                manifest['qualifier_returncode'] = args.returncode
                manifest['qualifier_status'] = 'REJECTED'
                require(source_binding(args.checkout, args.event_head) == manifest['source'],
                        'SOURCE_DRIFT')
                receipt = checked_receipt(strict_json(regular_bytes(
                    args.private_dir / 'qualifier.stdout', MAX_JSON)), args.returncode)
                receipt_bytes = canonical(receipt)
                with (args.private_dir / 'validated-qualifier.json').open('xb') as stream:
                    stream.write(receipt_bytes)
                os.chmod(args.private_dir / 'validated-qualifier.json', 0o600)
                manifest['qualifier_receipt_sha256'] = digest(receipt_bytes)
                manifest['qualifier_status'] = (
                    'PASSED_LIMITED' if args.returncode == 0 else 'FAILED_DIAGNOSTIC')
    except Rejected as error:
        manifest['provenance_error'] = error.code
    except Exception:
        manifest['provenance_error'] = 'INTERNAL'
    try:
        save_checkpoint(args.private_dir, manifest)
    except Exception:
        print('CAPTURE_PROVENANCE_CHECKPOINT_REJECTED')
        return 1
    print('CAPTURE_PROVENANCE_PHASE_RECORDED')
    return 1 if manifest['provenance_error'] is not None else 0


def finalize(args):
    manifest, receipt = new_manifest(), None
    try:
        manifest, receipt = load_checkpoint(args.private_dir)
    except Exception:
        manifest['provenance_error'] = 'ARTIFACT_SCHEMA'
    manifest['build_step_outcome'] = args.build_outcome
    manifest['qualifier_step_outcome'] = args.qualifier_outcome
    if manifest['images_before'] is not None:
        try:
            manifest['source_unchanged'] = source_binding(
                args.checkout, args.event_head) == manifest['source']
            after_images = image_hashes(args.build_root)
            after_pins = digest(regular_bytes(args.build_root / 'capture_pins.h', 8192))
            manifest['images_after'] = after_images
            manifest['generated_pins_after_sha256'] = after_pins
            manifest['images_unchanged'] = after_images == {
                name: image['sha256'] for name, image in manifest['images_before'].items()}
            manifest['generated_pins_unchanged'] = (
                manifest['generated_pins_before_sha256'] == after_pins)
            require(manifest['source_unchanged'], 'SOURCE_DRIFT')
            require(manifest['images_unchanged'] and manifest['generated_pins_unchanged'],
                    'IMAGE_DRIFT')
        except Rejected as error:
            manifest['provenance_error'] = manifest['provenance_error'] or error.code
        except Exception:
            manifest['provenance_error'] = manifest['provenance_error'] or 'INTERNAL'
    if manifest['provenance_error'] is None:
        if manifest['build_status'] in {'UNKNOWN', 'NOT_RUN'}:
            manifest['build_status'] = 'UNKNOWN'
            manifest['provenance_error'] = 'BUILD_STATUS_UNAVAILABLE'
        elif manifest['build_status'] == 'PASSED' and manifest['qualifier_status'] in {
                'UNKNOWN', 'NOT_RUN'}:
            if args.qualifier_outcome != 'skipped':
                manifest['qualifier_status'] = 'UNKNOWN'
            manifest['provenance_error'] = 'QUALIFIER_STATUS_UNAVAILABLE'
    try:
        publish(args.public_dir, manifest, receipt)
        # Only this fixed marker enters GHA outputs, after disk readback.
        with args.github_output.open('a', encoding='utf-8') as stream:
            stream.write('safe_artifact=true\n')
    except Exception:
        print('CAPTURE_PROVENANCE_ARTIFACT_REJECTED')
        return 1
    print('CAPTURE_PROVENANCE_RETAINED')
    return 1 if manifest['provenance_error'] is not None else 0


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Rejected('ARTIFACT_SCHEMA')


def main():
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('prepare', 'snapshot', 'record', 'finalize'):
        execute = commands.add_parser(command)
        execute.add_argument('--private-dir', type=Path, required=True)
        if command in ('prepare', 'record', 'finalize'):
            execute.add_argument('--checkout', required=True)
            execute.add_argument('--event-head', required=True)
        if command in ('snapshot', 'finalize'):
            execute.add_argument('--build-root', type=Path, required=True)
        if command in ('snapshot', 'record'):
            execute.add_argument('--returncode', type=int, required=True)
        if command == 'finalize':
            execute.add_argument('--public-dir', type=Path, required=True)
            execute.add_argument('--github-output', type=Path, required=True)
            for name in ('build-outcome', 'qualifier-outcome'):
                execute.add_argument('--' + name, default='unknown', choices=(
                    'unknown', 'success', 'failure', 'cancelled', 'skipped'))
    verify = commands.add_parser('verify')
    verify.add_argument('directory', type=Path)
    check = commands.add_parser('check-receipt')
    check.add_argument('receipt', type=Path)
    check.add_argument('--returncode', type=int, required=True)
    check.add_argument('--validated-copy', type=Path, required=True)
    try:
        args = parser.parse_args()
        if args.command in ('prepare', 'snapshot', 'record'):
            return phase(args)
        if args.command == 'finalize':
            return finalize(args)
        if args.command == 'verify':
            verify_public(args.directory)
        else:
            require(integer(args.returncode, -128, 255), 'RECEIPT_SCHEMA')
            value = checked_receipt(strict_json(regular_bytes(args.receipt, MAX_JSON)),
                                    args.returncode)
            with args.validated_copy.open('xb') as stream:
                stream.write(canonical(value))
            require(checked_receipt(strict_json(regular_bytes(
                args.validated_copy, MAX_JSON)), args.returncode) == value, 'RECEIPT_SCHEMA')
        print('CAPTURE_PROVENANCE_VALIDATED')
        return 0
    except Exception:
        print('CAPTURE_PROVENANCE_REJECTED')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
