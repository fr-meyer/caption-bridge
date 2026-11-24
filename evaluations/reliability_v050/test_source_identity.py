"""Software receipt provenance checks, not physical or provider acceptance."""

from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from evaluations.reliability_v050 import run_offline
from evaluations.reliability_v050.run_offline import software_source_identity


def identity_fixture(monkeypatch, tmp_path, names):
    def git(argv, **kwargs):
        assert argv[:3] == ["git", "-C", str(tmp_path)]
        assert kwargs == {"capture_output": True, "check": True}
        command = argv[3:]
        if command[:1] == ["ls-files"]:
            return SimpleNamespace(stdout=b"\0".join(names) + b"\0")
        if command == ["rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=b"a" * 40 + b"\n")
        assert command == ["status", "--porcelain=v1", "-z"]
        return SimpleNamespace(stdout=b" M app/example.py\0")

    monkeypatch.setattr(subprocess, "run", git)
    (tmp_path / "app").mkdir()
    return lambda: software_source_identity(tmp_path)


def test_source_identity_detects_same_head_dirty_byte_changes(monkeypatch, tmp_path):
    identity = identity_fixture(monkeypatch, tmp_path, [b"app/example.py"])
    source = tmp_path / "app/example.py"
    source.write_bytes(b"before")
    before = identity()
    assert before == identity()
    source.write_bytes(b"after")
    after = identity()
    assert before["source_head"] == after["source_head"] == "a" * 40
    assert before["source_dirty"] is after["source_dirty"] is True
    assert before["software_source_sha256"] != after["software_source_sha256"]
    assert before["software_source_files"] == 1
    assert not any(str(tmp_path) in str(value) for value in before.values())


def test_source_identity_detects_missing_and_untracked_inputs(monkeypatch, tmp_path):
    names = [b"app/example.py"]
    identity = identity_fixture(monkeypatch, tmp_path, names)
    missing = identity()
    (tmp_path / "app/example.py").write_bytes(b"")
    assert missing["software_source_sha256"] != identity()["software_source_sha256"]
    before = identity()
    (tmp_path / "app/new.py").write_bytes(b"untracked software")
    names.append(b"app/new.py")
    after = identity()
    assert before["software_source_sha256"] != after["software_source_sha256"]
    assert after["software_source_files"] == 2
    names.reverse()
    assert identity() == after


def test_source_identity_does_not_follow_external_symlinks(monkeypatch, tmp_path):
    identity = identity_fixture(monkeypatch, tmp_path, [b"app/example.py"])
    source = tmp_path / "app/example.py"
    try:
        source.symlink_to(tmp_path / "external-private-file")
    except OSError:
        pytest.skip("Source symlink creation unavailable; no privilege change requested")
    before = identity()
    (tmp_path / "external-private-file").write_bytes(b"not software input")
    assert identity() == before


def test_receipt_rejects_source_mutation_even_when_software_tests_pass(monkeypatch, tmp_path):
    snapshots = iter([
        {"source_head": "a" * 40, "software_source_sha256": "before"},
        {"source_head": "a" * 40, "software_source_sha256": "after"},
    ])
    monkeypatch.setattr(run_offline, "software_source_identity", lambda: next(snapshots))
    monkeypatch.setattr(run_offline, "resource", None)
    monkeypatch.setattr(run_offline, "install_guards", lambda: SimpleNamespace(fallback_pairs_created=0))
    # A reporting-only unit check, not a substituted real software-suite receipt.
    monkeypatch.setattr(pytest, "main", lambda *_args, **_kwargs: 0)
    monkeypatch.setenv("RELIABILITY_V050_RECEIPTS", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["run_offline.py", "--receipt-dir", str(tmp_path)])
    assert run_offline.main() == 1
    receipt = json.loads((tmp_path / "focused-receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["source_unchanged"] is False
    assert receipt["pytest_exit_code"] == 0
    assert receipt["passed"] == 0


def test_source_identity_fails_closed_without_git_identity(monkeypatch, tmp_path):
    def fail(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "git")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        software_source_identity(tmp_path)
