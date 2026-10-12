"""Repeated exports must not inflate a private seminar's quality totals."""

import json

from scripts.analyze_exports import collect_transcripts, main


def transcript(session_id="session-one"):
    return {
        "session_id": session_id,
        "quality_summary": {"total_segments": 1, "done": 1},
        "segments": [{"seq": 1, "translation_status": "done",
                      "source_text": "PRIVATE_SOURCE_秘密", "translated_text": "PRIVATE_TRANSLATION"}],
    }


def write_export(root, name, data, *, indent=None):
    path = root / name / "transcript.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=indent), encoding="utf-8")
    return path


def test_repeated_formatted_exports_and_overlapping_roots_count_once(tmp_path):
    first = write_export(tmp_path, "exports/first", transcript())
    second = write_export(tmp_path, "recovered/copy", transcript(), indent=2)
    write_export(tmp_path, "recovered/other-session", transcript("session-two"))
    before = {path: path.read_bytes() for path in tmp_path.rglob("transcript.json")}
    loaded, duplicates = collect_transcripts([tmp_path, first, second.parent])
    assert len(loaded) == 2
    assert duplicates == 1
    assert {path: path.read_bytes() for path in before} == before


def test_different_snapshots_remain_available_for_analysis(tmp_path):
    write_export(tmp_path, "first", transcript())
    updated = transcript()
    updated["segments"][0]["translation_status"] = "failed"
    updated["quality_summary"] = {"total_segments": 1, "done": 0, "failed": 1}
    write_export(tmp_path, "later", updated)
    loaded, duplicates = collect_transcripts([tmp_path])
    assert len(loaded) == 2
    assert duplicates == 0


def test_summary_is_deduplicated_and_does_not_print_private_text(tmp_path, capsys):
    write_export(tmp_path, "first", transcript())
    write_export(tmp_path, "copy", transcript())
    main([str(tmp_path), "--summary-only"])
    captured = capsys.readouterr()
    aggregate = captured.out.split("=== Aggregate totals ===")[1]
    assert "unique_exports: 1" in aggregate
    assert "duplicate_exports_skipped: 1" in aggregate
    assert "total_segments: 1" in aggregate
    assert "PRIVATE" not in captured.out + captured.err


def test_malformed_file_does_not_hide_valid_export(tmp_path):
    write_export(tmp_path, "valid", transcript())
    write_export(tmp_path, "invalid", [])
    loaded, duplicates = collect_transcripts([tmp_path])
    assert len(loaded) == 1
    assert duplicates == 0
