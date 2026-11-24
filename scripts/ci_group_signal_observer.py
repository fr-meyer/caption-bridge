"""Retain only fixed, bounded data from the real hosted Darwin noinput probe.

Never launches the probe, native capture, or a provider. Raw probe files stay private.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci_capture_noinput_provenance import (  # noqa: E402
    HEX40,
    HEX64,
    Parser,
    canonical,
    digest,
    image_hashes,
    integer,
    regular_bytes,
    require,
    strict_json,
    tool,
)

PUBLIC_FILE = 'group-signal-observation.json'
MAX_PUBLIC = 32768
SOURCES = ('.github/workflows/ci.yml', 'scripts/ci_group_signal_observer.py',
           'native/caption_helper/probe_group_signal.c',
           'native/caption_helper/probe_group_signal.sh')
IMAGES = ('CaptureController', 'CaptureGuardianA', 'CaptureGuardianB', 'CaptureHelper')
CASES = (0, 1, 3)
OBS_KEYS = frozenset('''schema kind natural_exits observation_complete mechanism_complete group
uid euid private_session pids census_complete states waitid_exits signal_zero signal_kill
reaped_status cleanup_forced remaining_owned darwin_unix03 capture native_admission'''.split())
KERNEL = re.compile(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z')
BUILD = re.compile(r'[0-9]{1,3}[A-Z][0-9]{1,6}[a-z]?\Z')
BINDINGS = {'COMPLETE', 'PARTIAL', 'MISSING', 'REJECTED', 'UNKNOWN'}


def checked_observation(value, index):
    require(type(value) is dict and set(value) == OBS_KEYS)
    require(type(value['schema']) is int and value['schema'] == 1
            and value['kind'] == 'DARWIN_OWNED_GROUP_SIGNAL_OBSERVATION'
            and type(value['natural_exits']) is int and value['natural_exits'] == CASES[index])
    require(value['capture'] is False and value['native_admission'] is False)
    for key in ('observation_complete', 'mechanism_complete', 'census_complete'):
        require(type(value[key]) is bool)
    for key in ('uid', 'euid'):
        require(integer(value[key], 0, 2**32 - 1))
    require(integer(value['group'], 0, 2**31 - 1)
            and integer(value['private_session'], -1, 2**31 - 1)
            and integer(value['darwin_unix03'], 0, 1))
    for key, low, high in (('pids', 0, 2**31 - 1), ('states', 0, 255),
                           ('waitid_exits', 0, 255), ('reaped_status', -1, 65535),
                           ('cleanup_forced', 0, 1), ('remaining_owned', 0, 1)):
        require(type(value[key]) is list and len(value[key]) == 3
                and all(integer(item, low, high) for item in value[key]))
    for key in ('signal_zero', 'signal_kill'):
        require(type(value[key]) is dict and set(value[key]) == {'rc', 'errno'}
                and integer(value[key]['rc'], -2, 0)
                and integer(value[key]['errno'], 0, 4095))
    # No predicted errno/result is supplied, and no row means no observation.
    return value


def observations(directory):
    rows = []
    try:
        path = directory / 'observations.jsonl'
        if not path.exists():
            return dict(status='NONE', cases=[])
        raw = regular_bytes(path, 16384)
        lines = raw.splitlines(keepends=True)
        require(len(lines) <= 3)
        for index, line in enumerate(lines):
            require(line.endswith(b'\n') and 0 < len(line) <= 4096)
            rows.append(checked_observation(strict_json(line), index))
        return dict(status='COMPLETE' if len(rows) == 3 else 'PARTIAL' if rows else 'NONE',
                    cases=rows)
    except Exception:
        return dict(status='REJECTED', cases=rows)


def runtime(directory):
    try:
        path = directory / 'runtime.txt'
        if not path.exists():
            return dict(status='MISSING', kernel_release=None, build_version=None)
        raw = regular_bytes(path, 65536)
        releases = re.findall(rb'^kern\.osrelease: ([0-9.]+)\r?$', raw, re.M)
        builds = re.findall(rb'^kern\.osversion: ([0-9A-Za-z]+)\r?$', raw, re.M)
        sw_builds = re.findall(rb'^BuildVersion:[ \t]+([0-9A-Za-z]+)\r?$', raw, re.M)
        require(len(releases) == len(builds) == 1 and sw_builds == builds)
        release, build = releases[0].decode('ascii'), builds[0].decode('ascii')
        require(KERNEL.fullmatch(release) and BUILD.fullmatch(build))
        return dict(status='KNOWN', kernel_release=release, build_version=build)
    except Exception:
        return dict(status='REJECTED', kernel_release=None, build_version=None)


def result_status(directory):
    try:
        path = directory / 'result.txt'
        if not path.exists():
            return dict(status='MISSING', returncode=None)
        raw = regular_bytes(path, 256)
        match = re.fullmatch(rb'probe_exit=([0-9]{1,3})\ndiagnostic_only=true\n'
                             rb'capture=false\nnative_admission=false\n', raw)
        require(match is not None and integer(int(match[1]), 0, 255))
        return dict(status='KNOWN', returncode=int(match[1]))
    except Exception:
        return dict(status='REJECTED', returncode=None)


def source_binding(checkout):
    require(type(checkout) is str and HEX40.fullmatch(checkout))
    actual = tool(['git', 'rev-parse', 'HEAD'])[0].decode().strip()
    tree = tool(['git', 'rev-parse', 'HEAD^{tree}'])[0].decode().strip()
    require(actual == checkout and HEX40.fullmatch(tree))
    tool(['git', 'diff', '--quiet', 'HEAD', '--'])
    hashes = {}
    for name in SOURCES:
        raw = regular_bytes(ROOT / name, 262144)
        require(raw == tool(['git', 'show', 'HEAD:' + name])[0])
        hashes[name] = digest(raw)
    return dict(checkout_commit=actual, checkout_tree=tree, files_sha256=hashes)


def hash_record(path, expected):
    """Compare private shasum lines exactly, without publishing their paths."""
    try:
        if not path.exists():
            return 'MISSING', 0
        lines = regular_bytes(path, 16384).splitlines()
        require(len(lines) <= len(expected))
        for line, (name, sha256) in zip(lines, expected):
            require(line == sha256.encode('ascii') + b'  ' + os.fsencode(name))
        return ('COMPLETE' if len(lines) == len(expected) else 'PARTIAL'), len(lines)
    except Exception:
        return 'REJECTED', 0


def binary(directory, source):
    value = dict(status='MISSING', sha256=None, hash_binding='UNKNOWN', recorded_hashes=0)
    try:
        path = directory / 'GroupSignalProbe'
        if not path.exists():
            return value
        value['sha256'] = digest(regular_bytes(path, 32 * 1024 * 1024))
        value['status'] = 'UNVERIFIED'
        if source is not None:
            expected = [(ROOT / name, source['files_sha256'][name]) for name in SOURCES[2:]]
            expected.append((path, value['sha256']))
            value['hash_binding'], value['recorded_hashes'] = hash_record(
                directory / 'source-binary.sha256', expected)
        tool(['/usr/bin/codesign', '--verify', '--strict', str(path)])
        require(digest(regular_bytes(path, 32 * 1024 * 1024)) == value['sha256'])
        value['status'] = 'VERIFIED'
    except Exception:
        value['status'] = 'UNVERIFIED' if value['sha256'] is not None else 'REJECTED'
    return value


def candidate(directory, build):
    value = dict(sha256=None, hash_binding='UNKNOWN', recorded_hashes=0)
    try:
        hashes = image_hashes(build)
        value['sha256'] = hashes
        paths = build / 'CaptionHelper.app/Contents/MacOS'
        value['hash_binding'], value['recorded_hashes'] = hash_record(
            directory / 'candidate-binaries.sha256', [(paths / name, hashes[name]) for name in IMAGES])
    except Exception:
        value['hash_binding'] = 'MISSING' if not build.exists() else 'REJECTED'
    return value


def validate(value):
    require(type(value) is dict and set(value) == {
        'schema', 'kind', 'diagnostic_only', 'capture', 'native_admission', 'physical_acceptance',
        'source', 'source_status', 'probe_step_outcome', 'observations', 'runtime', 'result',
        'probe_binary', 'candidate'})
    require(type(value['schema']) is int and value['schema'] == 1
            and value['kind'] == 'DARWIN_GROUP_SIGNAL_SAFE_RETENTION'
            and value['diagnostic_only'] is True and value['capture'] is False
            and value['native_admission'] is False and value['physical_acceptance'] is False)
    require(value['source_status'] in {'KNOWN', 'REJECTED'})
    source = value['source']
    if source is not None:
        require(value['source_status'] == 'KNOWN' and type(source) is dict
                and set(source) == {'checkout_commit', 'checkout_tree', 'files_sha256'})
        require(all(type(source[key]) is str and HEX40.fullmatch(source[key])
                    for key in ('checkout_commit', 'checkout_tree')))
        require(type(source['files_sha256']) is dict and set(source['files_sha256']) == set(SOURCES)
                and all(type(item) is str and HEX64.fullmatch(item)
                        for item in source['files_sha256'].values()))
    else:
        require(value['source_status'] == 'REJECTED')
    require(value['probe_step_outcome'] in {'unknown', 'success', 'failure', 'cancelled', 'skipped'})
    obs = value['observations']
    require(type(obs) is dict and set(obs) == {'status', 'cases'}
            and obs['status'] in {'NONE', 'PARTIAL', 'COMPLETE', 'REJECTED'}
            and type(obs['cases']) is list and len(obs['cases']) <= 3)
    for index, row in enumerate(obs['cases']):
        checked_observation(row, index)
    require(obs['status'] != 'COMPLETE' or len(obs['cases']) == 3)
    require(obs['status'] != 'PARTIAL' or 0 < len(obs['cases']) < 3)
    require(obs['status'] != 'NONE' or not obs['cases'])
    run = value['runtime']
    require(type(run) is dict and set(run) == {'status', 'kernel_release', 'build_version'}
            and run['status'] in {'KNOWN', 'MISSING', 'REJECTED'})
    if run['status'] == 'KNOWN':
        require(type(run['kernel_release']) is str and KERNEL.fullmatch(run['kernel_release'])
                and type(run['build_version']) is str and BUILD.fullmatch(run['build_version']))
    else:
        require(run['kernel_release'] is None and run['build_version'] is None)
    result = value['result']
    require(type(result) is dict and set(result) == {'status', 'returncode'}
            and result['status'] in {'KNOWN', 'MISSING', 'REJECTED'})
    require(integer(result['returncode'], 0, 255) if result['status'] == 'KNOWN'
            else result['returncode'] is None)
    probe = value['probe_binary']
    require(type(probe) is dict and set(probe) == {'status', 'sha256', 'hash_binding', 'recorded_hashes'}
            and probe['status'] in {'MISSING', 'REJECTED', 'UNVERIFIED', 'VERIFIED'})
    require(probe['sha256'] is None if probe['status'] in {'MISSING', 'REJECTED'}
            else type(probe['sha256']) is str and HEX64.fullmatch(probe['sha256']))
    candidate = value['candidate']
    require(type(candidate) is dict and set(candidate) == {'sha256', 'hash_binding', 'recorded_hashes'})
    if candidate['sha256'] is not None:
        require(type(candidate['sha256']) is dict and set(candidate['sha256']) == set(IMAGES)
                and all(type(item) is str and HEX64.fullmatch(item)
                        for item in candidate['sha256'].values()))
    for record, count in ((probe, 3), (candidate, 4)):
        require(record['hash_binding'] in BINDINGS and integer(record['recorded_hashes'], 0, count))
        require(record['hash_binding'] != 'COMPLETE' or record['recorded_hashes'] == count)
        require(record['hash_binding'] != 'PARTIAL' or record['recorded_hashes'] < count)
        if record['hash_binding'] == 'COMPLETE':
            require(record['sha256'] is not None)
    return value


def verify(directory):
    require(directory.is_dir() and not directory.is_symlink()
            and {path.name for path in directory.iterdir()} == {PUBLIC_FILE})
    raw = regular_bytes(directory / PUBLIC_FILE, MAX_PUBLIC)
    value = validate(strict_json(raw))
    require(raw == canonical(value))
    return value


def collect(args):
    source = None
    try:
        source = source_binding(args.checkout)
    except Exception:
        pass
    require(not args.private_dir.is_symlink()
            and (not args.private_dir.exists() or args.private_dir.is_dir()))
    value = dict(schema=1, kind='DARWIN_GROUP_SIGNAL_SAFE_RETENTION', diagnostic_only=True,
                 capture=False, native_admission=False, physical_acceptance=False,
                 source=source, source_status='KNOWN' if source is not None else 'REJECTED',
                 probe_step_outcome=args.probe_outcome, observations=observations(args.private_dir),
                 runtime=runtime(args.private_dir), result=result_status(args.private_dir),
                 probe_binary=binary(args.private_dir, source),
                 candidate=candidate(args.private_dir, args.build_root))
    validate(value)
    staging = args.public_dir.with_name(args.public_dir.name + '.validated-staging')
    staging.mkdir(mode=0o700)
    with (staging / PUBLIC_FILE).open('xb') as stream:
        stream.write(canonical(value))
    os.chmod(staging / PUBLIC_FILE, 0o600)
    verify(staging)
    require(not args.public_dir.exists() and not args.public_dir.is_symlink())
    staging.rename(args.public_dir)
    verify(args.public_dir)
    with args.github_output.open('a', encoding='utf-8') as stream:
        stream.write('safe_probe_artifact=true\n')
    print('GROUP_SIGNAL_OBSERVER_RETAINED')
    complete = (source is not None and value['observations']['status'] == 'COMPLETE'
                and all(row['mechanism_complete'] for row in value['observations']['cases'])
                and value['runtime']['status'] == 'KNOWN'
                and value['result'] == {'status': 'KNOWN', 'returncode': 0}
                and value['probe_binary']['status'] == 'VERIFIED'
                and value['probe_binary']['hash_binding'] == 'COMPLETE'
                and value['candidate']['hash_binding'] == 'COMPLETE')
    # An actual failed/cancelled probe remains failed upstream. Safe partial data
    # is retained, never filled in. A claimed successful probe must have evidence.
    return 1 if source is None or args.probe_outcome == 'success' and not complete else 0


def main():
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('collect')
    for name in ('private-dir', 'build-root', 'public-dir', 'github-output'):
        run.add_argument('--' + name, type=Path, required=True)
    run.add_argument('--checkout', required=True)
    run.add_argument('--probe-outcome', default='unknown', choices=(
        'unknown', 'success', 'failure', 'cancelled', 'skipped'))
    check = commands.add_parser('verify')
    check.add_argument('directory', type=Path)
    try:
        args = parser.parse_args()
        if args.command == 'collect':
            return collect(args)
        verify(args.directory)
        print('GROUP_SIGNAL_OBSERVER_VALIDATED')
        return 0
    except Exception:
        print('GROUP_SIGNAL_OBSERVER_REJECTED')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
