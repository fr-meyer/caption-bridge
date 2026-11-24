"""Synthetic failure packet/source contracts, NEVER native/physical acceptance."""
import ast
import copy
import io
import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from native.caption_helper.capture_diagnostics import (
    _FAILURE_STAGES,
    CaptureDiagnostics,
    validated_terminal,
)
from scripts.attended_helper_budget import Custody
from scripts.attended_journal import Journal
from scripts.attended_native_launch import _terminal, qualify_noinput

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = "PRIVATE_PATH_ENV_ARGV_DEVICE_AUDIO_TRANSCRIPT_SECRET"
STARTUP = dict(event="started", pids=[10, 11, 12])


def old_terminal(code=0):
    return dict(schema=1, capture_exit=code, capture=False, terminal="HOLD",
                pids=[10, 11, 12], wait_status=[72 << 8] * 3, cleanup_killed=[0] * 3)


def packet(stage="ACTIVE_DEADLINE"):
    return dict(old_terminal(70), schema=2, failure=dict(
        stage=stage, role=0, errno_class="NONE", reader_events=0, cleanup_errors=0,
        events=[1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14],
        wait_status=[72 << 8, 72 << 8, -1], timing_valid=True,
        elapsed_ns=2_000_000_000, window_ns=2_000_000_000, deadline_reached=True))


def receipt(value):
    diagnostics = CaptureDiagnostics()
    diagnostics.startup, diagnostics.terminal, diagnostics.returncode = STARTUP, value, 70
    result = diagnostics.receipt(RuntimeError(PRIVATE), journal_hold=True)
    encoded = json.dumps(result)
    assert PRIVATE not in encoded and len(encoded) < 2048
    assert result["result"] == "FAIL" and result["terminal"] == "HOLD"
    assert not any(result[key] for key in
                   ("native_admission", "physical_acceptance", "independent_closure_verified"))
    return result


@pytest.mark.parametrize("stage", sorted(_FAILURE_STAGES))
def test_known_branch_is_observation_only_and_never_accepted(stage):
    value = packet(stage)
    assert receipt(value)["native_terminal"] == value
    for code in (0, 70):
        with pytest.raises(RuntimeError):
            _terminal(STARTUP, value, code, no_input=True)


def test_old_success_unchanged_and_old_exit70_not_reinterpreted():
    old = old_terminal()
    assert _terminal(STARTUP, old, 0, no_input=True) == old
    failed = old_terminal(70)
    assert receipt(failed)["native_terminal"] == failed
    assert "failure" not in failed  # Never invent the absent hosted reason.
    with pytest.raises(RuntimeError):
        _terminal(STARTUP, failed, 70, no_input=True)


def test_failure_snapshot_and_final_status_remain_distinct_and_unaliased():
    value = packet()
    result = receipt(value)
    assert result["native_terminal"]["wait_status"] == [72 << 8] * 3
    assert result["native_terminal"]["failure"]["wait_status"][-1] == -1
    value["failure"]["events"].append(7)
    value["failure"]["wait_status"][0] = 9
    assert result["native_terminal"]["failure"]["events"][-1] == 14
    assert result["native_terminal"]["failure"]["wait_status"][0] == 72 << 8


@pytest.mark.parametrize("key,value", [
    ("stage", PRIVATE), ("stage", [PRIVATE]), ("stage", 0),
    ("errno_class", PRIVATE), ("errno_class", [PRIVATE]), ("errno_class", 0),
    ("role", True), ("role", -1), ("role", 4),
    ("reader_events", True), ("reader_events", -1), ("reader_events", 16),
    ("cleanup_errors", False), ("cleanup_errors", -1), ("cleanup_errors", 32),
    ("events", PRIVATE), ("events", [PRIVATE]), ("events", [1, 1]),
    ("events", [True]), ("events", [15]), ("events", [0]), ("events", list(range(17))),
    ("wait_status", [PRIVATE, 0, 0]), ("wait_status", [False, 0, 0]),
    ("wait_status", [-2, 0, 0]), ("wait_status", [65536, 0, 0]), ("wait_status", [0, 0]),
    ("timing_valid", "true"), ("timing_valid", 1),
    ("elapsed_ns", -1), ("elapsed_ns", 10_000_000_001), ("elapsed_ns", True),
    ("elapsed_ns", 1.5), ("window_ns", 0), ("window_ns", 2_000_000_001),
    ("window_ns", True), ("window_ns", PRIVATE),
    ("deadline_reached", False), ("deadline_reached", PRIVATE), ("deadline_reached", 1),
    ("extra", PRIVATE)])
def test_malformed_or_private_failure_fields_are_dropped_whole(key, value):
    candidate = packet()
    candidate["failure"][key] = value
    # A false deadline observation is valid at exact rounded equality; use >.
    if key == "deadline_reached" and value is False:
        candidate["failure"]["elapsed_ns"] += 1
    result = receipt(candidate)
    assert result["native_terminal"] is None and not result["terminal_shape_valid"]
    assert result["terminal_shape_error"] == "failure"


@pytest.mark.parametrize("changes", [dict(capture_exit=0), dict(capture_exit=1),
    dict(schema=3), dict(schema=True), dict(failure=PRIVATE), dict(failure={}),
    dict(extra=PRIVATE)])
def test_new_schema_is_failure_only_and_has_no_extra_projection(changes):
    candidate = dict(packet(), **changes)
    assert receipt(candidate)["native_terminal"] is None


def test_early_failure_survives_without_becoming_challenge_or_startup():
    value = packet("BUDGET")
    value["pids"] = [-1] * 3
    value["wait_status"] = [-1] * 3
    value["failure"].update(events=[], wait_status=[-1] * 3, timing_valid=False,
                            elapsed_ns=0, window_ns=0, deadline_reached=None)
    diagnostics = CaptureDiagnostics()
    diagnostics.observe_native_failure(value)
    result = diagnostics.receipt(RuntimeError("capture_startup_unknown_hold"))
    assert result["native_terminal"] == value and not result["startup_valid"]
    assert result["result"] == "FAIL" and result["journal_hold"] is None
    invalid = copy.deepcopy(value)
    invalid["failure"]["stage"] = PRIVATE
    other = CaptureDiagnostics()
    other.observe_native_failure(invalid)
    assert other.terminal is None


def test_source_emitter_is_one_bounded_json_line_and_matches_strict_parser():
    # Interprets only actual C format literals, NOT C/HAL execution or acceptance.
    source = (ROOT / "native/caption_helper/assembly.c").read_text()
    prefix = next(line for line in source.splitlines() if r'\"schema\":2' in line)
    suffix = next(line for line in source.splitlines() if r'\"deadline_reached\"' in line)
    def literal(line):
        return ast.literal_eval(re.search(r'printf\(("(?:\\.|[^"\\])*")', line).group(1))
    value = packet()
    first = literal(prefix) % ("false", 10, 11, 12, *([72 << 8] * 3), 0, 0, 0,
                               "ACTIVE_DEADLINE", 0, "NONE", 0, 0)
    last = literal(suffix).replace("%llu", "%d") % (72 << 8, 72 << 8, -1, "true",
                                                         2_000_000_000, 2_000_000_000, "true")
    text = first + ",".join(map(str, value["failure"]["events"])) + last
    assert text.endswith("\n") and text.count("\n") == 1 and len(text.encode()) < 4096
    assert json.loads(text) == value and validated_terminal(json.loads(text)) == value


def test_fixed_c_stage_registry_matches_parser_and_critical_branches_are_recorded():
    header = (ROOT / "native/caption_helper/capture_diagnostic.h").read_text()
    native = set(re.findall(r'X\(([A-Z_]+)\)', header.split("enum cb_capture_failure_stage")[0]))
    assert native == _FAILURE_STAGES
    source = (ROOT / "native/caption_helper/assembly.c").read_text()
    reasons = set(re.findall(r'CAPTURE_(?:FAILURE|SYSTEM_FAILURE|REJECT|PIN_FAILURE)\(([A-Z_]+),', source))
    assert reasons <= native
    assert {"ACTIVE_DEADLINE", "STOP_READER", "OBSERVE_OWNED", "CHILD_STATUS",
            "READINESS_DEADLINE", "GROUP_SIGNAL", "REAP_WAIT", "IDENTITY_QUERY",
            "GROUP_PGID", "PIN_WAIT", "PIN_METADATA_QUERY", "PIN_METADATA_SIZE",
            "PIN_METADATA_PID", "PIN_PARENT", "PIN_GROUP", "PIN_RUID", "PIN_EUID",
            "PIN_BIRTH_SEC", "PIN_BIRTH_USEC", "PIN_TERMINAL", "PIN_ZOMBIE",
            "PIN_ARGUMENT", "PIN_WAIT_EVENT", "PIN_WAIT_STATE"} <= reasons
    active = source.split("while(mach_continuous_time()<reap_end){", 1)[1].split("#else", 1)[0]
    assert all("CAPTURE_FAILURE(" in line or "CAPTURE_SYSTEM_FAILURE(" in line
               for line in active.splitlines() if "result=70" in line)
    assert "if(mach_continuous_time()>=end){CAPTURE_FAILURE(ACTIVE_DEADLINE" in active
    assert "if(d->stage!=CB_CAPTURE_FAIL_NONE)return" in header
    assert "end+2000000000ULL*tb.denom/tb.numer" in source
    assert "end+=" not in source and "deadline+=" not in source



def test_postreap_identity_checks_are_own_custody_not_global_pid_absence():
    source = (ROOT / "native/caption_helper/assembly.c").read_text()
    start = source.index("/* Successful waitpid readback")
    branch = source[start:source.index("CAPTURE_EVENT(IDENTITIES_CHECKED)", start)]
    assert "waitid(P_PID,(id_t)identities[i],&gone,WEXITED|WNOHANG|WNOWAIT)" in branch
    for guard in ("retained[i]>0", "saved_status[i]<0", "observed==0", "errno!=ECHILD"):
        assert guard in branch
    assert "CAPTURE_SYSTEM_FAILURE(IDENTITY_QUERY,i+1)" in branch
    assert "CAPTURE_CLEANUP(IDENTITY);result=70" in branch
    assert "kill(" not in branch and "getpgid(" not in branch
    # Keep historical failures readable without demanding global PID absence.
    assert "IDENTITY_VISIBLE" in _FAILURE_STAGES


def test_owned_pin_reasons_preserve_guards_and_suspended_probe_order():
    header = (ROOT / "native/caption_helper/owned_group_closure.h").read_text()
    assembly = (ROOT / "native/caption_helper/assembly.c").read_text()
    probe = (ROOT / "native/caption_helper/probe_group_signal.c").read_text()
    start = header.index("cb_owned_group_pin_detail(")
    pin = header[start:header.index("static inline int cb_owned_group_pin(", start)]
    assert "memset(&info,0,sizeof(info))" in pin
    assert "WEXITED|WSTOPPED|WNOHANG|WNOWAIT" in pin
    for guard in ("event==CB_WAIT_INVALID", "event==CB_WAIT_TERMINAL",
                  "event==CB_WAIT_STOPPED && row.kp_proc.p_stat!=SSTOP", "p_stat==SZOMB", "e_ppid!=getpid()",
                  "e_pgid!=group", "p_ruid!=getuid()", "cr_uid!=geteuid()",
                  "tv_sec<=0", "tv_usec<0", "tv_usec>=1000000"):
        assert guard in pin
    for reason in ("ARGUMENT", "WAIT", "TERMINAL", "METADATA_QUERY", "METADATA_SIZE",
                   "METADATA_PID", "ZOMBIE", "PARENT", "GROUP", "RUID", "EUID",
                   "BIRTH_SEC", "BIRTH_USEC", "WAIT_EVENT", "WAIT_STATE"):
        assert "CB_PIN_" + reason in header
        assert ("case CB_PIN_" + reason + ":CAPTURE_PIN_FAILURE(PIN_" + reason
                + ",role,system_errno);break;") in assembly
    assert "*system_errno=errno" in header
    assert pin.count("return CB_PIN_OK;") == 1
    assert pin.index("pin->birth=") < pin.index("pin->enrolled=1;return CB_PIN_OK")
    spawn = assembly[assembly.index("static pid_t spawn_role("):assembly.index("static int observe_owned(")]
    for flag in ("POSIX_SPAWN_CLOEXEC_DEFAULT", "POSIX_SPAWN_START_SUSPENDED", "POSIX_SPAWN_SETPGROUP"):
        assert flag in spawn and flag in probe
    assert "posix_spawnattr_setpgroup(&attr," in spawn and "posix_spawnattr_setpgroup(&attr," in probe
    assert 'char *env[]={NULL}' in probe and '"--owned-member"' in probe
    assert "posix_spawn(&pid,executable,&actions,&attr,argv,env)" in probe
    assert "stopped.kp_proc.p_stat!=SSTOP" in probe
    verify = probe.index("!verify_member(pid)")
    enrolled = probe.index("cb_owned_group_pin_detail(pin,pid,*group,&pin_errno,NULL)")
    continued = probe.index("kill(pid,SIGCONT)")
    ready = probe.index("wait_ready(ready_pipe[0],&r,end)", continued)
    assert verify < enrolled < continued < ready
    assert "fork()" not in probe
    assert "pin_result!=CB_PIN_OK" in assembly
    assert "capture_pin_failure(pin_result,role,pin_errno,pid,&pin_readback);goto done" in assembly


def test_shared_wait_event_classifier_never_equates_pid_with_exit():
    header = (ROOT / "native/caption_helper/owned_group_closure.h").read_text()
    classifier = header[header.index("cb_owned_wait_classify("):header.index("/* Fixed diagnostic reasons")]
    for guard in ("info->si_pid==0", "!info->si_signo && !info->si_code && !info->si_status",
                  "info->si_pid!=pid || info->si_signo!=SIGCHLD", "default:return CB_WAIT_INVALID"):
        assert guard in classifier
    for code in ("CLD_EXITED", "CLD_KILLED", "CLD_DUMPED", "CLD_STOPPED"):
        assert "case " + code + ":" in classifier
    assert "info->si_status>=0 && info->si_status<NSIG?CB_WAIT_STOPPED:CB_WAIT_INVALID" in classifier
    assert "CLD_TRAPPED" not in classifier and "CLD_CONTINUED" not in classifier
    assembly = (ROOT / "native/caption_helper/assembly.c").read_text()
    probe = (ROOT / "native/caption_helper/probe_group_signal.c").read_text()
    assert "cb_owned_wait_classify(pid,&info)" in assembly
    assert "cb_owned_wait_classify(pid,info)" in probe
    assert "if(event!=CB_WAIT_TERMINAL)return 0" in assembly
    assert "return event==CB_WAIT_TERMINAL?1:0" in probe
    assert "info.si_status<0 || info.si_status>255" in assembly


def test_probe_cleanup_requires_fresh_waitpid_custody_before_kill():
    probe = (ROOT / "native/caption_helper/probe_group_signal.c").read_text()
    start = probe.index("static int cleanup_reap(")
    cleanup = probe[start:probe.index("static int run_case(", start)]
    assert "int status=-1;pid_t done=waitpid(pid,&status,WNOHANG)" in cleanup
    assert "if(done==pid){*saved=status;*held=0;return 1;}" in cleanup
    assert "if(done==0)return 0" in cleanup
    assert "if(done<0 && errno==EINTR)return 2" in cleanup
    assert "observe(" not in cleanup and "waitid(" not in cleanup
    assert "until_ms(2000),grace=until_ms(1000)" in cleanup
    assert "held[i] && !untrusted[i] && before(end)" in cleanup
    assert "if(r<0){ok=0;untrusted[i]=1;break;}" in cleanup
    assert "if(r==0){\n   if(kill(pids[i],SIGKILL)" in cleanup
    assert "cleanup_reap(pids[i],&held[i],&statuses[i])" in cleanup
    assert "for(int i=0;i<OWNED_CAP;i++)if(held[i])ok=0" in cleanup
    assert probe.count("static const char *maybe_bool(") == 1


def test_raw_pin_wait_readback_is_first_cause_bounded_and_legacy_compatible():
    assembly = (ROOT / "native/caption_helper/assembly.c").read_text()
    diagnostic = (ROOT / "native/caption_helper/capture_diagnostic.h").read_text()
    parser = (ROOT / "native/caption_helper/capture_diagnostics.py").read_text()
    assert "if(first && readback && (reason==CB_PIN_TERMINAL" in assembly
    for key in ("signo", "code", "status"):
        assert "capture_diagnostic.wait_event_" + key + "=readback->si_" + key in assembly
    assert "!readback->si_pid?0:(readback->si_pid==pid?1:2)" in assembly
    assert "case 0:return 0;case EINTR:" in diagnostic
    assert "set(value) not in (_FAILURE_KEYS, _FAILURE_KEYS | {'wait_event'})" in parser
    assert "set(event) != {'signo', 'code', 'status', 'pid_relation'}" in parser
    assert "not -(2 ** 31) <= event[key] < 2 ** 31" in parser
    assert "event['pid_relation'] not in (0, 1, 2)" in parser
    assert "dict(item) if type(item) is dict else item" in parser
    assert "if (type(value['stage']) is str" in parser

def test_state_setup_rejection_precedes_cleanup_without_changing_noaudio_projection():
    source = (ROOT / "native/caption_helper/assembly.c").read_text()
    condition = "if(!cb_reserve(&state,end) || !cb_synthetic_input(&state) || !cb_route_change(&state))"
    branch = (
        "#ifdef CB_CAPTURE_CONTROLLER\n " + condition + "CAPTURE_REJECT(STATE_SETUP,0);\n"
        "#else\n " + condition + "goto cleanup;\n#endif"
    )
    assert branch in source
    assert source.index(branch) < source.index("CAPTURE_EVENT(PIPES);")
    value = packet("STATE_SETUP")
    value["pids"] = [-1] * 3
    value["wait_status"] = [-1] * 3
    value["failure"].update(
        wait_status=[-1] * 3, events=[1, 8, 10, 14], cleanup_errors=1,
        elapsed_ns=50, deadline_reached=False,
    )
    observed = receipt(value)
    assert observed["native_terminal"]["failure"]["stage"] == "STATE_SETUP"
    assert observed["native_terminal"]["failure"]["cleanup_errors"] == 1
    with pytest.raises(RuntimeError):
        _terminal(STARTUP, value, 70, no_input=True)


@pytest.mark.parametrize("where", ["challenge", "startup"])
def test_early_packet_in_private_driver_never_passes_challenge_or_startup(tmp_path, where):
    path = tmp_path / "ledger"
    Journal.initialize(path, "a" * 64)
    journal = Journal(path, "a" * 64)
    diagnostics, children = CaptureDiagnostics(), []
    value = packet("BUDGET" if where == "challenge" else "READINESS_DEADLINE")
    value.update(pids=[-1] * 3, wait_status=[-1] * 3)
    value["failure"].update(events=[], wait_status=[-1] * 3, timing_valid=False,
                            elapsed_ns=0, window_ns=0, deadline_reached=None)
    class Child:
        def __init__(self, _arguments, **_kwargs):
            self.stdin = io.BytesIO()
            r, w = os.pipe()
            self.stdout = os.fdopen(r, "rb", buffering=0)
            lines = []
            if where == "startup":
                lines.append(dict(event="capture_noinput_budget_ready", challenge="d" * 64,
                                  ceiling_ms=2000, anchor_continuous_ticks=1_000_000_000,
                                  timebase_numer=1, timebase_denom=1))
            lines.append(value)
            os.write(w, b"".join(json.dumps(line).encode() + b"\n" for line in lines))
            os.close(w)
            children.append(self)
        def poll(self):
            return 70
        def wait(self, **_kwargs):
            return 70
    try:
        with patch("scripts.attended_native_launch.sys.platform", "darwin"), \
             patch("scripts.attended_native_launch.subprocess.Popen", Child):
            with pytest.raises((RuntimeError, ValueError)):
                qualify_noinput(tmp_path, Custody(journal), "b" * 40, _diagnostics=diagnostics)
        result = diagnostics.receipt(RuntimeError(PRIVATE), journal_hold=journal.active is not None)
        assert result["native_terminal"] == value and result["result"] == "FAIL"
        assert not result["startup_valid"] and not result["native_admission"]
        assert result["journal_hold"] is (where == "startup")
        assert journal.charged == (2000 if where == "startup" else 0)
        assert result["controller_returncode"] == 70
        assert children[0].stdout.closed and children[0].stdin.closed
        assert PRIVATE not in json.dumps(result)
    finally:
        journal.close()


def test_c_observation_macros_do_not_substitute_structure_member_names():
    source = (ROOT / "native/caption_helper/assembly.c").read_text()
    for name, parameters, body in re.findall(r"#define (CAPTURE_\w+)\(([^)]*)\)([^\n]*)", source):
        members = set(re.findall(r"capture_diagnostic\.(\w+)", body))
        assert not set(parameters.split(",")) & members, name
