import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _fast_scan(path: Path):
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "file_identity": {
            "device": stat.st_dev,
            "inode": stat.st_ino,
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        },
        "size_bytes": stat.st_size,
        "has_user_and_assistant": None,
        "fast_stat_only": True,
    }


def test_lost_source_triage_fails_closed_for_inconsistent_counts():
    from raw_record_recoverability import lost_source_triage

    assert lost_source_triage({
        "lost_source_count": 3,
        "lost_source_recoverable_count": 2,
        "lost_source_unrecoverable_count": 0,
        "lost_source_not_measured_count": 0,
    }) == (3, 0, 3, 0)


def test_raw_failure_status_is_not_overwritten_by_source_recoverability(tmp_path):
    from raw_record_recoverability import prepare_recoverability_evidence

    raw_path = tmp_path / "raw.jsonl"
    raw_path.write_text(
        json.dumps({"role": "user", "content": "u"}) + "\n"
        + json.dumps({"role": "assistant", "content": "a"}) + "\n",
        encoding="utf-8",
    )
    record = {
        "source_system": "future_xyz",
        "raw_path": str(raw_path),
        "source_scan": {"exists": False},
        "raw_scan": _fast_scan(raw_path),
        "guard_status": "source_divergence_raw_retained",
        "raw_current": False,
    }

    result = prepare_recoverability_evidence(
        [record],
        scan_mode="fast",
        authorized_desktop_formats=set(),
        record_id_fn=lambda _item: "record-1",
        records_db=tmp_path / "missing.db",
    )

    assert result["candidate_count"] == 0
    assert result["targeted_scan_count"] == 0
    assert record["guard_status"] == "source_divergence_raw_retained"
    assert record["recoverable_from_raw"] is None


def test_targeted_scan_missing_file_remains_not_measured(tmp_path):
    from raw_record_recoverability import _bounded_jsonl_recoverability_scan

    result = _bounded_jsonl_recoverability_scan(
        tmp_path / "gone.jsonl",
        source_system="future_xyz",
        max_bytes=1024,
    )

    assert result["exists"] is False
    assert result["has_user_and_assistant"] is None
    assert result["health_status"] == "missing_during_targeted_scan"


def test_recoverability_cache_has_a_hard_entry_limit():
    from raw_record_recoverability import _cache_put

    cache = {}
    for index in range(300):
        _cache_put(cache, (index,), {"recoverable_from_raw": True}, entry_limit=256)

    assert len(cache) == 256
    assert (0,) not in cache
    assert (299,) in cache


def test_persisted_recoverability_cache_opens_sqlite_read_only(tmp_path, monkeypatch):
    import raw_record_recoverability

    raw_path = tmp_path / "raw.jsonl"
    raw_path.write_text(
        json.dumps({"role": "user", "content": "u"}) + "\n"
        + json.dumps({"role": "assistant", "content": "a"}) + "\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "records.db"
    db_path.touch()
    captured = {}

    def reject_after_capture(database, **kwargs):
        captured.update(database=database, kwargs=kwargs)
        raise raw_record_recoverability.sqlite3.OperationalError("stop after capture")

    monkeypatch.setattr(raw_record_recoverability.sqlite3, "connect", reject_after_capture)
    record = {
        "source_system": "future_xyz",
        "raw_path": str(raw_path),
        "source_scan": {"exists": False},
        "raw_scan": _fast_scan(raw_path),
        "guard_status": "stat_incomplete",
        "raw_current": False,
    }

    result = raw_record_recoverability.prepare_recoverability_evidence(
        [record],
        scan_mode="fast",
        authorized_desktop_formats=set(),
        record_id_fn=lambda _item: "record-1",
        records_db=db_path,
        cache={},
    )

    assert captured["database"].endswith("?mode=ro")
    assert captured["kwargs"]["uri"] is True
    assert result["canonical_cache_status"] == "sqlite_open_failed:OperationalError"
