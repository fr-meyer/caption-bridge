"""Offline source/policy regressions. Never native/HAL/physical acceptance."""
import io
import hashlib
import json
import re
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

import test_caption_native_capture as baseline
from scripts.attended_native_admission import MIN_CAPTURE_MS
from scripts.attended_native_launch import EmergencyStop, _run, capture_valid_until, qualify_noinput

ROOT = Path(__file__).resolve().parents[1]
FROZEN = "a1f60ea1abe81b4b7968c22d51a87969d213d77c"
SNAPSHOTS = ROOT / "tests/fixtures/native_safety_a1f60ea1"


def frozen_source(path):
    name = Path(path).name + ".snapshot"
    manifest = json.loads((SNAPSHOTS / "MANIFEST.json").read_text())[name]
    data = (SNAPSHOTS / name).read_bytes()
    assert manifest["source"] == path and manifest["commit"] == FROZEN
    assert hashlib.sha256(data).hexdigest() == manifest["sha256"]
    return data.decode()



@pytest.fixture
def case():
    c = baseline.AdmissionTests("runTest")
    c.setUp()
    try:
        yield c
    finally:
        c.doCleanups()


def challenge(event="capture_budget_ready"):
    return dict(event=event, challenge="d" * 64, ceiling_ms=2000,
                anchor_continuous_ticks=10_000_000_000, timebase_numer=1, timebase_denom=1)


class Child:
    writes = []
    def __init__(self, *_args, **_kwargs):
        self.stdout = io.BytesIO()
        self.stdin = self
    def write(self, wire):
        self.writes.append(wire)
        return len(wire)
    def close(self):
        pass
    def poll(self):
        return 0
    def wait(self, **_kwargs):
        return 0


class Reader:
    def __init__(self, *_args):
        self.first = True
    def line(self):
        if self.first:
            self.first = False
            return challenge()
        raise RuntimeError("unit_only_after_delivery")


def test_expiry_crossing_actual_durable_debit_never_delivers_budget(case):
    clock, expiry = [17_000_000_000], 20_000_000_000
    original = case.c.prepare_capture_budget
    Child.writes = []
    def slow_debit(*args, **kwargs):
        reservation, wire = original(*args, **kwargs)
        assert case.j.active is not None  # Real temp-journal debit/fsync, no mocks.
        assert len(wire) == 72 and wire[:8] == b"CBCA0002"
        assert int.from_bytes(wire[56:64], "big") == 13_000_000_000
        assert int.from_bytes(wire[64:72], "big") == expiry
        clock[0] = expiry + 1
        return reservation, wire
    emergency = EmergencyStop()
    try:
        with patch("scripts.attended_native_launch.sys.platform", "darwin"), \
             patch("scripts.attended_native_launch.subprocess.Popen", Child), \
             patch("scripts.attended_native_launch.BoundedLines", Reader), \
             patch("scripts.attended_native_launch.time.time_ns", side_effect=lambda: clock[0]), \
             patch("scripts.attended_native_launch.continuous_ns", return_value=17_000_000_000), \
             patch.object(case.c, "prepare_capture_budget", side_effect=slow_debit):
            with pytest.raises(RuntimeError, match="expired_after_debit"):
                _run(case.root, case.c, case.authority.candidate, 2000, emergency,
                     no_input=False, device_id=17, expires_unix_ns=expiry, expected_tail=case.j.tail,
                     valid_until_continuous_ns=20_000_000_001)
        assert Child.writes == []
        assert case.j.charged == 2000 and case.j.active is not None
    finally:
        emergency.close()


def test_fixed_native_validity_never_refreshes_full_duration_after_fsync():
    event = dict(challenge(), timebase_numer=3, timebase_denom=125)
    with patch("scripts.attended_native_launch.time.time_ns", return_value=17_000_000_000), \
         patch("scripts.attended_native_launch.continuous_ns", return_value=17_000_000_000):
        fixed = capture_valid_until(event, 20_000_000_000, 2000, 20_000_000_001)
    assert fixed == 10_000_000_000 + 3_000_000_000 * 125 // 3
    # Clock jumps/scheduling after mapping cannot mutate the integer handed to
    # the native min(debit_deadline, authenticated_validity_deadline) parser.
    with patch("scripts.attended_native_launch.time.time_ns", return_value=1):
        assert fixed == 135_000_000_000
    with patch("scripts.attended_native_launch.time.time_ns", return_value=19_900_000_000), \
         patch("scripts.attended_native_launch.continuous_ns", return_value=17_000_000_000):
        with pytest.raises(RuntimeError, match="validity_too_short"):
            capture_valid_until(challenge(), 20_000_000_000, 2000, 20_000_000_001)


def test_frozen_source_reproduces_post_expiry_v1_delivery(case):
    # Exact prior commit source, isolated module namespace; no source checkout or
    # resumption of an old worker and no real native subprocess/provider calls.
    def frozen(path, name):
        value = frozen_source(path)
        module = types.ModuleType(name)
        sys.modules[name] = module
        exec(compile(value, path + "@" + FROZEN, "exec"), module.__dict__)
        return module
    budget = frozen("scripts/attended_helper_budget.py", "_old_capture_budget_unit")
    launch = frozen("scripts/attended_native_launch.py", "_old_capture_launch_unit")
    custody = budget.Custody(case.j)
    clock, expiry = [19_900_000_000], 20_000_000_000
    original = custody.prepare_capture_budget
    def slow_debit(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] = expiry + 1
        return result
    class OldReader(Reader):
        def line(self):
            value = super().line()
            return {k: value[k] for k in ("event", "challenge", "ceiling_ms")}
    def check():
        if clock[0] >= expiry:
            raise RuntimeError("expired")
    emergency = launch.EmergencyStop()
    Child.writes = []
    try:
        with patch.object(launch.sys, "platform", "darwin"), \
             patch.object(launch.subprocess, "Popen", Child), \
             patch.object(launch, "BoundedLines", OldReader), \
             patch.object(launch.time, "time_ns", side_effect=lambda: clock[0]), \
             patch.object(custody, "prepare_capture_budget", side_effect=slow_debit):
            with pytest.raises(RuntimeError, match="unit_only_after_delivery"):
                launch._run(case.root, custody, case.authority.candidate, 2000, emergency,
                            no_input=False, device_id=17, check_grant=check)
        assert clock[0] > expiry and len(Child.writes) == 1
        assert Child.writes[0][:8] == b"CBCA0001" and len(Child.writes[0]) == 56
        assert case.j.active is not None
    finally:
        emergency.close()
        sys.modules.pop("_old_capture_budget_unit", None)
        sys.modules.pop("_old_capture_launch_unit", None)


@pytest.mark.parametrize("milliseconds", [1, 100, 500, 999])
def test_unsupported_startup_window_rejects_before_consumption_or_debit(case, milliseconds):
    assert MIN_CAPTURE_MS == 1000
    with pytest.raises(RuntimeError, match="runtime_grant"):
        case.issue(milliseconds=milliseconds)
    assert not case.authority._permits and not case.authority._seen_grants
    assert case.j.charged == 0 and case.j.active is None
    with patch("scripts.attended_native_launch.sys.platform", "darwin"), \
         patch.object(case.c, "session") as session, \
         patch("scripts.attended_native_launch.subprocess.Popen") as spawn:
        with pytest.raises(ValueError, match="duration"):
            qualify_noinput(case.root, case.c, case.authority.candidate, milliseconds=milliseconds)
        session.assert_not_called()
        spawn.assert_not_called()


def test_source_custody_deadline_and_noinput_guards_are_explicit():
    assembly = (ROOT / "native/caption_helper/assembly.c").read_text()
    guardian = (ROOT / "native/caption_helper/capture_guardian.c").read_text()
    role = (ROOT / "native/caption_helper/capture_role.c").read_text()
    budget = (ROOT / "native/caption_helper/budget.h").read_text()
    builder = (ROOT / "native/caption_helper/build_capture.sh").read_text()
    assert "POSIX_SPAWN_SETPGROUP" in assembly and "WNOWAIT" in assembly
    group_kill = assembly[assembly.index("static int kill_capture_group"):assembly.index("int main(")]
    assert group_kill.index("observe_owned(capture_group") < group_kill.index("kill(-capture_group")
    assert "retained[0]!=capture_group" in group_kill
    assert assembly.index("!kill_capture_group()") < assembly.index("reap_owned(retained[i]", assembly.index("cleanup:"))
    assert "kill(0,SIGKILL)" in guardian and "kill(cap.parent" not in guardian
    assert "cb_capture_wall_valid(cap.expires_unix_ns)" in guardian
    assert "CB_CAPTURE_CLOSED" in guardian and "return 72" in guardian
    assert "CB_CAPTURE_CLOSED" in role and "write(12" in role and "write(13" in role
    assert "if(validity<*deadline)*deadline=validity" in budget
    assert "wire+64" in budget and "cb_capture_wall_valid(cb_capture_expires_unix_ns)" in budget
    assert '#define CB_BUDGET_BYTES 56' in budget and '"CBNA0001"' in budget
    assert "CaptureGuardian" in builder
    # Frozen noaudio-only sources/entrypoints are byte-identical to prior commit.
    for path in ("native/caption_helper/role.c", "scripts/build_caption_helper.sh",
                 "native/caption_helper/qualify_assembly.py", "native/caption_helper/entitlements.plist"):
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == {'native/caption_helper/role.c': 'e23729398816494c0ee1289fd2662edbab66a112674b2b6b1adb41972457c417', 'scripts/build_caption_helper.sh': '551feab980e6ee20b3b2cc638f31d1804924fdd39a4f3d359dfb58791fa81855', 'native/caption_helper/qualify_assembly.py': 'b2876729634dca2159a9d00a1ff752abdb9fb71f76a3f2d4e0a87f13ae03a679', 'native/caption_helper/entitlements.plist': 'baa050bc06d89900bed3bb4954acdf2f17c4f47e259b1870f889d4a301fbcaf4'}[path]
    assert 'if(options.flags==CB_CAPTURE_ARMED || options.flags==CB_CAPTURE_PCM)' in role


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux subreaper mechanism model, not native qualification")
@pytest.mark.parametrize("scenario", ["deadline", "emergency", "controller_death",
                                     "guardian_a_stopped", "guardian_b_stopped",
                                     "controller_owns_stopped_group"])
def test_real_posix_group_model_closes_suspended_helper_without_controller(scenario):
    result = subprocess.run([sys.executable, str(ROOT / 'tests/native_capture_group_model.py'), scenario],
                            capture_output=True, text=True, timeout=5, check=True)
    evidence = json.loads(result.stdout)
    assert evidence['synthetic_only'] is True
    assert all(state in ('Z', 'gone') for state in evidence['closed_states'])


def test_frozen_admission_policy_accepted_guaranteed_unstartable_500ms(case):
    source = frozen_source("scripts/attended_native_admission.py")
    module = types.ModuleType("_old_small_budget_unit")
    exec(compile(source, "frozen-admission-unit", "exec"), module.__dict__)
    # Reuse authenticated SOFTWARE fixture state, not a claimed native image.
    old = module.CaptureAdmission.__new__(module.CaptureAdmission)
    old.__dict__ = dict(case.authority.__dict__)
    grant, runtime = case.grant(milliseconds=500)
    permit = old.issue(grant, baseline.digest(grant), runtime, case.c)
    assert old.consume(permit, case.c)["milliseconds"] == 500
    assert case.j.charged == 0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux model only, not native qualification")
def test_frozen_cooperative_only_guardian_model_leaves_suspended_helper(case):
    old = frozen_source("native/caption_helper/role.c")
    assert "SIGKILL" not in old and "return 72" in old
    result = subprocess.run([sys.executable, str(ROOT / "tests/native_capture_group_model.py"), "legacy_gap"],
                            capture_output=True, text=True, timeout=5, check=True)
    evidence = json.loads(result.stdout)
    assert evidence["legacy_gap_survives"] is True and evidence["closed_states"][2] == "T"


def noaudio_projection(source):
    """Resolve ONLY capture conditionals; preserve all other source directives."""
    output, stack, active = [], [], True
    for line in source.splitlines():
        value = line.strip()
        if value.startswith(("#ifdef ", "#ifndef ", "#if ")):
            known = value in ("#ifdef CB_CAPTURE_CONTROLLER", "#ifndef CB_CAPTURE_CONTROLLER")
            stack.append((active, known))
            if known:
                active = active and value.startswith("#ifndef")
            elif active:
                output.append(line)
        elif value == "#else":
            parent, known = stack[-1]
            if known:
                active = parent and not active
            elif active:
                output.append(line)
        elif value == "#endif":
            parent, known = stack.pop()
            if not known and active:
                output.append(line)
            active = parent
        elif active:
            output.append(line)
    assert not stack
    return re.sub(r"\s+", "", "\n".join(output))


def test_noaudio_controller_and_budget_token_paths_are_identical():
    for path in ("native/caption_helper/assembly.c", "native/caption_helper/budget.h"):
        assert hashlib.sha256(noaudio_projection((ROOT / path).read_text()).encode()).hexdigest() == {'native/caption_helper/assembly.c': '278144dfed1369b2c27ff80e9708ac51482122d10ec341b73fd83b1f8c05275c', 'native/caption_helper/budget.h': '8a2b63720f3dc400fd338e56c78c007b5d8830b1b6fa491672d5ba58b52fe306'}[path]


def test_wall_rollback_cannot_revive_expired_continuous_admission(case):
    import time
    now = time.time_ns()
    grant, runtime = case.grant(expires_unix_ns=now + 5_000_000_000)
    grant_data, runtime_data = json.loads(grant), json.loads(runtime)
    runtime_data["expires_unix_ns"] = grant_data["expires_unix_ns"]
    runtime = baseline.raw(runtime_data)
    grant_data["runtime_sha256"] = baseline.digest(runtime)
    grant = baseline.raw(grant_data)
    with patch("scripts.attended_native_admission.continuous_ns", return_value=100_000_000_000):
        permit = case.authority.issue(grant, baseline.digest(grant), runtime, case.c)
    # Simulated system sleep/expiry while wall time has rolled back inside the still-valid original wall window.
    with patch("scripts.attended_native_admission.continuous_ns", return_value=106_000_000_000), \
         patch("scripts.attended_native_admission.time.time_ns", return_value=now+1_000_000_000):
        with pytest.raises(RuntimeError, match="expired_or_ledger_changed"):
            case.authority.consume(permit, case.c)
    assert case.j.charged == 0


def test_mapping_cannot_refresh_validity_when_wall_rolls_back():
    with patch("scripts.attended_native_launch.time.time_ns", return_value=1), \
         patch("scripts.attended_native_launch.continuous_ns", return_value=19_900_000_000):
        with pytest.raises(RuntimeError, match="validity_too_short"):
            capture_valid_until(challenge(), 20_000_000_000, 2000, 20_000_000_001)


def test_real_linux_sleep_inclusive_clock_is_not_platform_mocked():
    from scripts.attended_native_clock import continuous_ns
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux clock software path only")
    before = continuous_ns()
    with patch("sys.platform", "darwin"):
        after = continuous_ns()  # Must NOT load libSystem on this real Linux host.
    assert 0 < before <= after
