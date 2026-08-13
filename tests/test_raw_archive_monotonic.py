import hashlib
import importlib
import json
import os
import threading
import time
from pathlib import Path

import src.raw_archive_monotonic as raw_archive_monotonic
from src.raw_archive_monotonic import (
    append_jsonl_records,
    append_source_file,
    generation_descriptor_path,
    load_generation_descriptor,
    select_archive_segment_metadata_only,
)


def test_source_truncation_never_shrinks_primary_raw(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one"}\n{"id":"two"}\n'
    source.write_bytes(original)

    first = append_source_file(source, archive)
    source.write_bytes(b'{"id":"one"}\n')
    second = append_source_file(source, archive)

    assert first["write_performed"] is True
    assert second["status"] == "source_regression_raw_retained"
    assert second["source_regression"] is True
    assert second["write_performed"] is False
    assert second["raw_shrink_performed"] is False
    assert archive.read_bytes() == original


def test_source_growth_appends_only_the_new_tail(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first_payload = b'{"id":"one"}\n'
    final_payload = first_payload + b'{"id":"two"}\n'
    source.write_bytes(first_payload)
    append_source_file(source, archive)
    source.write_bytes(final_payload)

    result = append_source_file(source, archive)

    assert result["status"] == "appended"
    assert result["bytes_appended"] == len(final_payload) - len(first_payload)
    assert archive.read_bytes() == final_payload


def test_source_prefix_rewrite_is_reported_without_archive_mutation(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one","text":"original"}\n'
    source.write_bytes(original)
    append_source_file(source, archive)
    source.write_bytes(b'{"id":"one","text":"rewritten"}\n')

    result = append_source_file(source, archive)

    assert result["status"] == "source_divergence_raw_retained"
    assert result["source_divergence"] is True
    assert result["write_performed"] is False
    assert archive.read_bytes() == original


def test_metadata_only_segment_cache_indexes_each_directory_without_crossing_archives(
    tmp_path,
    monkeypatch,
):
    archive_dir = tmp_path / "memory" / "project"
    archive_dir.mkdir(parents=True)
    first = archive_dir / "first.jsonl"
    first_segment = archive_dir / "first.seg1.jsonl"
    second = archive_dir / "second.jsonl"
    second_segment = archive_dir / "second.seg1.jsonl"
    for path in (first, first_segment, second, second_segment):
        path.write_bytes(b'{}\n')
    (archive_dir / "first.seg1.jsonl.canonical_dialogue.jsonl").write_bytes(b'{}\n')
    (archive_dir / "first.seg1.jsonl.forensic_runtime.jsonl").write_bytes(b'{}\n')

    original_iterdir = Path.iterdir
    directory_scans = 0

    def count_directory_scans(path):
        nonlocal directory_scans
        if path == archive_dir:
            directory_scans += 1
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", count_directory_scans)
    cache = {}
    first_selection = select_archive_segment_metadata_only(
        first,
        None,
        directory_cache=cache,
    )
    second_selection = select_archive_segment_metadata_only(
        second,
        None,
        directory_cache=cache,
    )

    assert directory_scans == 1
    assert first_selection["candidate_count"] == 2
    assert Path(first_selection["retained_archive_path"]) == first_segment
    assert second_selection["candidate_count"] == 2
    assert Path(second_selection["retained_archive_path"]) == second_segment


def test_metadata_only_segment_discovery_rejects_derived_jsonl_sidecars(tmp_path):
    archive = tmp_path / "session.jsonl"
    segment = tmp_path / "session.seg1.jsonl"
    derived = tmp_path / "session.seg1.jsonl.canonical_dialogue.jsonl"
    for path in (archive, segment, derived):
        path.write_bytes(b'{}\n')
    Path(str(derived) + ".meta.json").write_text(
        json.dumps({"source_inode": 42}),
        encoding="utf-8",
    )

    selection = select_archive_segment_metadata_only(archive, 42)

    assert selection["candidate_count"] == 2
    assert Path(selection["archive_path"]) != derived
    assert Path(selection["retained_archive_path"]) == segment


def test_metadata_only_segment_selection_uses_latest_verified_inode_segment(tmp_path):
    archive = tmp_path / "session.jsonl"
    requested = tmp_path / "session.seg2.jsonl"
    for path in (archive, requested):
        path.write_bytes(b'{}\n')
        Path(str(path) + ".meta.json").write_text(
            json.dumps({"source_inode": 42}),
            encoding="utf-8",
        )

    selection = select_archive_segment_metadata_only(archive, 42)

    assert selection["selection_status"] == "source_inode_sidecar"
    assert Path(selection["archive_path"]) == requested
    assert selection["selection_proven_by_metadata"] is True


def test_unchanged_files_reuse_verified_prefix_without_full_scan(tmp_path, monkeypatch):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    payload = (b'{"id":"one"}\n' * 4096)
    source.write_bytes(payload)
    raw_archive_monotonic._MATCHED_PREFIX_CACHE.clear()
    first = append_source_file(source, archive, compute_sha256=False)

    def full_scan_must_not_repeat(*_args, **_kwargs):
        raise AssertionError("unchanged files performed another full prefix scan")

    monkeypatch.setattr(raw_archive_monotonic, "_prefix_matches", full_scan_must_not_repeat)
    second = append_source_file(source, archive, compute_sha256=False)

    assert first["status"] == "created"
    assert second["status"] == "up_to_date"
    assert "source_sha256" not in second
    assert "archive_sha256" not in second
    assert archive.read_bytes() == payload


def test_matched_prefix_cache_invalidates_on_source_rewrite(tmp_path, monkeypatch):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one","text":"original"}\n'
    rewritten = b'{"id":"one","text":"changed!"}\n'
    assert len(original) == len(rewritten)
    source.write_bytes(original)
    raw_archive_monotonic._MATCHED_PREFIX_CACHE.clear()
    append_source_file(source, archive, compute_sha256=False)
    before = source.stat()
    source.write_bytes(rewritten)
    if source.stat().st_mtime_ns == before.st_mtime_ns:
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1))

    calls = {"count": 0}
    original_prefix_matches = raw_archive_monotonic._prefix_matches

    def counted_prefix_match(*args, **kwargs):
        calls["count"] += 1
        return original_prefix_matches(*args, **kwargs)

    monkeypatch.setattr(raw_archive_monotonic, "_prefix_matches", counted_prefix_match)
    result = append_source_file(source, archive, compute_sha256=False)

    assert calls["count"] == 1
    assert result["status"] == "source_divergence_raw_retained"
    assert result["write_performed"] is False
    assert archive.read_bytes() == original
    assert not raw_archive_monotonic._MATCHED_PREFIX_CACHE


def test_source_growth_uses_bounded_prefix_proof_then_caches_appended_result(tmp_path, monkeypatch):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first_payload = b'{"id":"one"}\n' * (3 * 1024 * 1024 // 13)
    final_payload = first_payload + b'{"id":"two"}\n'
    source.write_bytes(first_payload)
    raw_archive_monotonic._MATCHED_PREFIX_CACHE.clear()
    append_source_file(source, archive, compute_sha256=False)
    source.write_bytes(final_payload)

    calls = {"count": 0}
    original_prefix_matches = raw_archive_monotonic._prefix_matches

    def counted_prefix_match(*args, **kwargs):
        calls["count"] += 1
        return original_prefix_matches(*args, **kwargs)

    monkeypatch.setattr(raw_archive_monotonic, "_prefix_matches", counted_prefix_match)
    appended = append_source_file(source, archive, compute_sha256=False)
    unchanged = append_source_file(source, archive, compute_sha256=False)

    assert appended["status"] == "appended"
    assert appended["prefix_verification"] == "bounded_checkpoint"
    assert unchanged["status"] == "up_to_date"
    assert calls["count"] == 0
    assert archive.read_bytes() == final_payload


def test_io_diagnostics_attribute_growth_scan_and_cache_hit_without_private_data(tmp_path):
    source = tmp_path / "private-session-name.jsonl"
    archive = tmp_path / "memory" / "private-archive-name.jsonl"
    first_payload = b'{"private":"first"}\n' * 4096
    final_payload = first_payload + b'{"private":"second"}\n'
    source.write_bytes(first_payload)
    raw_archive_monotonic._MATCHED_PREFIX_CACHE.clear()
    before = raw_archive_monotonic.raw_archive_diagnostics_snapshot()

    append_source_file(source, archive, compute_sha256=False)
    source.write_bytes(final_payload)
    append_source_file(source, archive, compute_sha256=False)
    append_source_file(source, archive, compute_sha256=False)
    after = raw_archive_monotonic.raw_archive_diagnostics_snapshot()

    assert after["checkpoint_prefix_hit_count"] - before["checkpoint_prefix_hit_count"] == 1
    assert after["checkpoint_prefix_miss_count"] - before["checkpoint_prefix_miss_count"] == 0
    assert 0 < after["checkpoint_prefix_source_bytes"] - before["checkpoint_prefix_source_bytes"] <= 2 * raw_archive_monotonic.CHUNK_SIZE
    assert after["verified_prefix_rehash_hit_count"] - before["verified_prefix_rehash_hit_count"] == 0
    assert after["verified_prefix_rehash_miss_count"] - before["verified_prefix_rehash_miss_count"] == 0
    assert after["verified_prefix_rehash_source_bytes"] - before["verified_prefix_rehash_source_bytes"] == 0
    assert after["full_prefix_scan_count"] - before["full_prefix_scan_count"] == 0
    assert after["full_prefix_source_bytes"] - before["full_prefix_source_bytes"] == 0
    assert after["full_prefix_archive_bytes"] - before["full_prefix_archive_bytes"] == 0
    assert after["full_prefix_total_bytes"] - before["full_prefix_total_bytes"] == 0
    assert after["matched_prefix_cache_hit_count"] - before["matched_prefix_cache_hit_count"] == 1
    serialized = json.dumps(after, sort_keys=True)
    assert "private-session-name" not in serialized
    assert "private-archive-name" not in serialized
    assert "private" not in serialized


def test_default_proof_mode_still_returns_full_source_and_archive_sha(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    payload = b'{"id":"proof"}\n'
    source.write_bytes(payload)

    result = append_source_file(source, archive)
    expected = hashlib.sha256(payload).hexdigest()

    assert result["source_sha256"] == expected
    assert result["archive_sha256"] == expected


def test_growth_prefix_rehash_detects_earlier_rewrite_without_appending(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one","text":"original"}\n'
    source.write_bytes(original)
    append_source_file(source, archive, compute_sha256=False)
    rewritten = b'{"id":"one","text":"rewritten"}\n'
    source.write_bytes(rewritten + b'{"id":"two"}\n')

    before = raw_archive_monotonic.raw_archive_diagnostics_snapshot()
    result = append_source_file(source, archive, compute_sha256=False)
    after = raw_archive_monotonic.raw_archive_diagnostics_snapshot()

    assert result["status"] == "source_divergence_raw_retained"
    assert result["write_performed"] is False
    assert archive.read_bytes() == original
    assert after["verified_prefix_rehash_miss_count"] - before["verified_prefix_rehash_miss_count"] == 1
    assert after["full_prefix_scan_count"] - before["full_prefix_scan_count"] == 1


def test_same_size_rewrite_never_uses_bounded_prefix_proof(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = (b"a" * (2 * 1024 * 1024)) + b"\n"
    source.write_bytes(original)
    append_source_file(source, archive, compute_sha256=False)
    source.write_bytes(b"b" + original[1:])

    result = append_source_file(source, archive, compute_sha256=False)

    assert result["status"] == "source_divergence_raw_retained"
    assert result["prefix_verification"] == "full_fail_closed"
    assert result["write_performed"] is False
    assert archive.read_bytes() == original


def test_expired_prefix_proof_detects_unchecked_historical_rewrite(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = (b"a" * raw_archive_monotonic.CHUNK_SIZE) + (b"b" * raw_archive_monotonic.CHUNK_SIZE)
    source.write_bytes(original)
    append_source_file(source, archive, compute_sha256=False)
    proof_path = Path(str(archive) + raw_archive_monotonic.PREFIX_PROOF_SUFFIX)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["last_full_verified_at_ns"] = time.time_ns() - (
        raw_archive_monotonic.PREFIX_FULL_REVERIFY_SECONDS + 1
    ) * 1_000_000_000
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    source.write_bytes(b"z" + original[1:] + b"tail\n")

    result = append_source_file(source, archive, compute_sha256=False)

    assert result["status"] == "source_divergence_raw_retained"
    assert result["prefix_verification"] == "full_fail_closed"
    assert result["write_performed"] is False
    assert archive.read_bytes() == original


def test_corrupt_prefix_proof_fails_closed_before_unchecked_block_rewrite(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b"".join(
        marker * raw_archive_monotonic.CHUNK_SIZE
        for marker in (b"a", b"b", b"c")
    )
    source.write_bytes(original)
    append_source_file(source, archive, compute_sha256=False)
    proof_path = Path(str(archive) + raw_archive_monotonic.PREFIX_PROOF_SUFFIX)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["blocks"][1]["sha256"] = "0" * 64
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    source.write_bytes(
        original[: raw_archive_monotonic.CHUNK_SIZE]
        + (b"z" * raw_archive_monotonic.CHUNK_SIZE)
        + original[2 * raw_archive_monotonic.CHUNK_SIZE :]
        + b"tail\n"
    )

    result = append_source_file(source, archive, compute_sha256=False)

    assert result["status"] == "source_divergence_raw_retained"
    assert result["prefix_verification"] == "full_fail_closed"
    assert result["write_performed"] is False
    assert archive.read_bytes() == original


def test_malformed_prefix_proof_fails_closed_without_crashing_watcher(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b"a" * (2 * raw_archive_monotonic.CHUNK_SIZE)
    source.write_bytes(original)
    append_source_file(source, archive, compute_sha256=False)
    proof_path = Path(str(archive) + raw_archive_monotonic.PREFIX_PROOF_SUFFIX)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["archive_size"] = {"not": "an integer"}
    proof["blocks"][0]["offset"] = ["bad"]
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    source.write_bytes(b"z" + original[1:] + b"tail\n")

    result = append_source_file(source, archive, compute_sha256=False)

    assert result["status"] == "source_divergence_raw_retained"
    assert result["prefix_verification"] == "full_fail_closed"
    assert result["write_performed"] is False
    assert archive.read_bytes() == original


def test_future_dated_valid_prefix_proof_fails_closed(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b"".join(
        marker * raw_archive_monotonic.CHUNK_SIZE
        for marker in (b"a", b"b", b"c")
    )
    source.write_bytes(original)
    append_source_file(source, archive, compute_sha256=False)
    proof_path = Path(str(archive) + raw_archive_monotonic.PREFIX_PROOF_SUFFIX)
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["last_full_verified_at_ns"] = time.time_ns() + 60 * 1_000_000_000
    proof_path.write_text(
        json.dumps(raw_archive_monotonic._seal_prefix_proof(proof)),
        encoding="utf-8",
    )
    source.write_bytes(
        original[: raw_archive_monotonic.CHUNK_SIZE]
        + (b"z" * raw_archive_monotonic.CHUNK_SIZE)
        + original[2 * raw_archive_monotonic.CHUNK_SIZE :]
        + b"tail\n"
    )

    result = append_source_file(source, archive, compute_sha256=False)

    assert result["status"] == "source_divergence_raw_retained"
    assert result["prefix_verification"] == "full_fail_closed"
    assert result["write_performed"] is False
    assert archive.read_bytes() == original


def test_inode_change_with_continuous_prefix_reuses_existing_segment(tmp_path):
    source = tmp_path / "source.jsonl"
    replacement = tmp_path / "replacement.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one"}\n'
    source.write_bytes(original)
    first_inode = source.stat().st_ino
    append_source_file(source, archive, source_inode=first_inode, compute_sha256=False)
    Path(str(archive) + ".meta.json").write_text(
        json.dumps({"source_inode": first_inode}), encoding="utf-8"
    )
    replacement.write_bytes(original + b'{"id":"two"}\n')
    os.replace(replacement, source)
    second_inode = source.stat().st_ino
    assert second_inode != first_inode

    result = append_source_file(source, archive, source_inode=second_inode, compute_sha256=False)

    assert result["status"] == "appended"
    assert result["source_identity_rebound"] is True
    assert result["archive_path"] == str(archive)
    assert archive.read_bytes() == source.read_bytes()
    assert not list(archive.parent.glob("session.seg*.jsonl"))


def test_watcher_connectors_explicitly_skip_full_sha(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "src"))
    for module_name in ("codex_local_connector", "claude_code_local_connector"):
        connector = importlib.import_module(module_name)
        source = tmp_path / f"{module_name}.jsonl"
        archive = tmp_path / "raw" / f"{module_name}.jsonl"
        source.write_bytes(b'{"id":"watch"}\n')
        calls = []

        def fake_append(*_args, **kwargs):
            calls.append(kwargs)
            return {
                "archive_path": str(archive),
                "status": "source_divergence_raw_retained",
                "source_divergence": True,
                "source_size": source.stat().st_size,
                "archive_size_before": source.stat().st_size,
            }

        with monkeypatch.context() as scoped:
            scoped.setattr(connector, "_raw_dest_for_artifact", lambda _artifact: archive)
            scoped.setattr(connector, "load_checkpoint", lambda: {})
            scoped.setattr(connector, "append_source_file", fake_append)
            _dest, status = connector.archive_session_incremental(
                str(source),
                artifact={"session_id": module_name},
            )

        assert status.startswith("source_divergence_raw_retained")
        expected = {
            "dry_run": False,
            "source_inode": source.stat().st_ino,
            "compute_sha256": False,
        }
        expected["continue_on_divergence"] = True
        assert calls == [expected]


def test_known_divergence_reuses_bounded_witness(tmp_path, monkeypatch):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = (b"a" * (2 * 1024 * 1024)) + b'\n'
    source.write_bytes(original)
    append_source_file(source, archive)
    source.write_bytes(original[:-2] + b"b\n")

    raw_archive_monotonic._DIVERGENCE_WITNESS_CACHE.clear()
    first = append_source_file(source, archive)
    assert first["status"] == "source_divergence_raw_retained"
    assert len(raw_archive_monotonic._DIVERGENCE_WITNESS_CACHE) == 1
    diagnostics_before = raw_archive_monotonic.raw_archive_diagnostics_snapshot()
    source.write_bytes(source.read_bytes() + b'{"id":"new-tail"}\n')

    def full_scan_must_not_repeat(*_args, **_kwargs):
        raise AssertionError("known divergence performed another full prefix scan")

    monkeypatch.setattr(raw_archive_monotonic, "_remember_divergence_witness", full_scan_must_not_repeat)
    second = append_source_file(source, archive)
    diagnostics_after = raw_archive_monotonic.raw_archive_diagnostics_snapshot()

    assert second["status"] == "source_divergence_raw_retained"
    assert second["write_performed"] is False
    assert archive.read_bytes() == original
    assert (
        diagnostics_after["divergence_witness_hit_count"]
        - diagnostics_before["divergence_witness_hit_count"]
    ) == 1
    assert (
        diagnostics_after["full_prefix_scan_count"]
        - diagnostics_before["full_prefix_scan_count"]
    ) == 0


def test_known_divergence_reuses_witness_after_append_only_archive_growth(tmp_path, monkeypatch):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = (b"a" * (2 * 1024 * 1024)) + b"\n"
    source.write_bytes(original)
    append_source_file(source, archive)
    divergent_prefix = original[:-2] + b"b\n"
    source.write_bytes(divergent_prefix)

    raw_archive_monotonic._DIVERGENCE_WITNESS_CACHE.clear()
    first = append_source_file(source, archive)
    assert first["status"] == "source_divergence_raw_retained"
    assert len(raw_archive_monotonic._DIVERGENCE_WITNESS_CACHE) == 1

    source_tail = b'{"id":"new-tail"}\n'
    source.write_bytes(divergent_prefix + source_tail)
    with archive.open("ab") as handle:
        handle.write(source_tail)

    def full_scan_must_not_repeat(*_args, **_kwargs):
        raise AssertionError("append-only archive growth re-recorded the mismatch witness")

    monkeypatch.setattr(raw_archive_monotonic, "_remember_divergence_witness", full_scan_must_not_repeat)
    second = append_source_file(source, archive)

    assert second["status"] == "source_divergence_raw_retained"
    assert second["write_performed"] is False
    assert archive.read_bytes() == original + source_tail


def test_divergence_witness_invalidates_when_source_prefix_recovers(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one","text":"original"}\n'
    source.write_bytes(original)
    append_source_file(source, archive)
    source.write_bytes(b'{"id":"one","text":"rewritten"}\n')

    raw_archive_monotonic._DIVERGENCE_WITNESS_CACHE.clear()
    divergent = append_source_file(source, archive)
    assert divergent["status"] == "source_divergence_raw_retained"

    recovered = original + b'{"id":"two"}\n'
    source.write_bytes(recovered)
    result = append_source_file(source, archive)

    assert result["status"] == "appended"
    assert archive.read_bytes() == recovered
    assert not raw_archive_monotonic._DIVERGENCE_WITNESS_CACHE


def test_source_deletion_keeps_archive_and_records_regression(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one"}\n{"id":"two"}\n'
    source.write_bytes(original)
    append_source_file(source, archive)

    source.unlink()
    result = append_source_file(source, archive)

    assert result["status"] == "source_regression_raw_retained"
    assert result["source_missing"] is True
    assert result["source_regression"] is True
    assert result["write_performed"] is False
    assert result["raw_shrink_performed"] is False
    assert result["retained_bytes"] == len(original)
    assert archive.read_bytes() == original


def test_inode_rotation_keeps_old_segment_and_starts_new_segment(tmp_path):
    source = tmp_path / "source.jsonl"
    replacement = tmp_path / "replacement.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one"}\n'
    rotated = b'{"id":"rotated"}\n'
    source.write_bytes(original)
    first_inode = source.stat().st_ino
    first = append_source_file(source, archive, source_inode=first_inode)
    Path(str(archive) + ".meta.json").write_text(
        json.dumps({"source_inode": first_inode}), encoding="utf-8"
    )

    replacement.write_bytes(rotated)
    os.replace(replacement, source)
    second_inode = source.stat().st_ino
    assert second_inode != first_inode

    second = append_source_file(source, archive, source_inode=second_inode)
    segment = Path(second["archive_path"])

    assert first["archive_path"] == str(archive)
    assert second["status"] == "created"
    assert segment.name == "session.seg1.jsonl"
    assert archive.read_bytes() == original
    assert segment.read_bytes() == rotated
    assert Path(str(archive) + ".meta.json").read_text(encoding="utf-8")


def test_same_inode_divergence_can_continue_in_proven_generation(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original_lines = [
        {"id": "one", "text": "original"},
        {"id": "two", "text": "stable"},
    ]
    original = b"".join(
        (json.dumps(item, separators=(",", ":")) + "\n").encode()
        for item in original_lines
    )
    source.write_bytes(original)
    append_source_file(source, archive, source_inode=source.stat().st_ino)
    rewritten_lines = [
        {"id": "one", "text": "rewritten"},
        {"id": "two", "text": "stable"},
        {"id": "three", "text": "new tail"},
    ]
    rewritten = b"".join(
        (json.dumps(item, separators=(",", ":")) + "\n").encode()
        for item in rewritten_lines
    )
    source.write_bytes(rewritten)

    result = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    generation = Path(result["archive_path"])
    descriptor = load_generation_descriptor(generation)

    assert result["status"] == "source_divergence_generation_started"
    assert result["generation_started"] is True
    assert archive.read_bytes() == original
    assert generation.name == "session.seg1.jsonl"
    assert generation.read_bytes() == rewritten
    assert descriptor["predecessor"] == str(archive)
    assert descriptor["source_base_offset"] == 0
    assert descriptor["divergence_witness"]["status"] == "proven"
    assert descriptor["reason"] == "source_divergence"


def test_generation_append_uses_absolute_source_offset_without_duplication(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first = b'{"id":"one","text":"stable"}\n'
    second_old = b'{"id":"two","text":"old"}\n'
    source.write_bytes(first + second_old)
    append_source_file(source, archive, source_inode=source.stat().st_ino)
    second_new = b'{"id":"two","text":"new value"}\n'
    third = b'{"id":"three","text":"tail"}\n'
    source.write_bytes(first + second_new + third)
    started = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    generation = Path(started["archive_path"])
    before = generation.read_bytes()
    fourth = b'{"id":"four","text":"later"}\n'
    source.write_bytes(source.read_bytes() + fourth)

    appended = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )

    assert started["source_base_offset"] == len(first)
    assert before == second_new + third
    assert appended["status"] == "appended_generation"
    assert appended["bytes_appended"] == len(fourth)
    assert generation.read_bytes() == before + fourth
    assert generation.read_bytes().count(third) == 1
    descriptor = load_generation_descriptor(generation)
    assert descriptor["source_covered_bytes"] == source.stat().st_size


def test_generation_mutations_are_serialized_per_logical_archive(tmp_path, monkeypatch):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    source.write_text('{}\n', encoding="utf-8")
    start = threading.Barrier(3)
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def observed_unlocked(*_args, **_kwargs):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.08)
        with state_lock:
            active -= 1
        return {"ok": True, "status": "up_to_date", "write_performed": False}

    monkeypatch.setattr(raw_archive_monotonic, "_append_source_file_unlocked", observed_unlocked)
    results = []

    def worker():
        start.wait(timeout=2)
        results.append(
            raw_archive_monotonic.append_source_file(
                source,
                archive,
                continue_on_divergence=True,
            )
        )

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 2
    assert maximum_active == 1


def test_second_divergence_starts_another_generation(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first = b'{"id":"one","text":"stable"}\n'
    source.write_bytes(first + b'{"id":"two","text":"v1"}\n')
    append_source_file(source, archive, source_inode=source.stat().st_ino)
    source.write_bytes(first + b'{"id":"two","text":"v2"}\n')
    generation_one = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    first_generation_path = Path(generation_one["archive_path"])
    first_generation_bytes = first_generation_path.read_bytes()
    source.write_bytes(first + b'{"id":"two","text":"v3"}\n')

    generation_two = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    second_generation_path = Path(generation_two["archive_path"])
    descriptor = load_generation_descriptor(second_generation_path)

    assert generation_two["status"] == "source_divergence_generation_started"
    assert second_generation_path.name == "session.seg2.jsonl"
    assert first_generation_path.read_bytes() == first_generation_bytes
    assert descriptor["generation"] == 2
    assert descriptor["predecessor"] == str(first_generation_path)
    assert descriptor["predecessor_generation"] == 1


def test_generation_prefix_divergence_starts_full_successor_generation(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first_v1 = b'{"id":"one","text":"v1"}\n'
    first_v2 = b'{"id":"one","text":"v2"}\n'
    second_v1 = b'{"id":"two","text":"old"}\n'
    second_v2 = b'{"id":"two","text":"new"}\n'
    source.write_bytes(first_v1 + second_v1)
    append_source_file(source, archive, source_inode=source.stat().st_ino)
    source.write_bytes(first_v1 + second_v2)
    generation_one = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    generation_one_path = Path(generation_one["archive_path"])
    generation_one_bytes = generation_one_path.read_bytes()
    third = b'{"id":"three","text":"tail"}\n'
    source.write_bytes(first_v2 + second_v2 + third)

    generation_two = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    generation_two_path = Path(generation_two["archive_path"])
    descriptor = load_generation_descriptor(generation_two_path)

    assert generation_two["status"] == "source_divergence_generation_started"
    assert generation_two["source_base_offset"] == 0
    assert generation_two_path.read_bytes() == source.read_bytes()
    assert generation_one_path.read_bytes() == generation_one_bytes
    assert descriptor["generation"] == 2
    assert descriptor["predecessor"] == str(generation_one_path)
    assert descriptor["reason"] == "source_prefix_divergence_after_generation"
    assert descriptor["divergence_witness"]["status"] == "proven_generation_prefix_divergence"


def test_source_inode_rotation_after_generation_starts_linked_full_successor(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first = b'{"id":"one","text":"stable"}\n'
    source.write_bytes(first + b'{"id":"two","text":"v1"}\n')
    append_source_file(source, archive, source_inode=source.stat().st_ino)
    source.write_bytes(first + b'{"id":"two","text":"v2"}\n')
    started = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    generation = Path(started["archive_path"])
    generation_bytes = generation.read_bytes()

    replacement = tmp_path / "replacement.jsonl"
    replacement_bytes = b'{"id":"three","text":"rotated source"}\n'
    replacement.write_bytes(replacement_bytes)
    os.replace(replacement, source)
    successor = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    successor_path = Path(successor["archive_path"])
    descriptor = load_generation_descriptor(successor_path)

    assert successor["status"] == "source_divergence_generation_started"
    assert successor["source_identity_rotated"] is True
    assert successor_path != generation
    assert generation.read_bytes() == generation_bytes
    assert successor_path.read_bytes() == replacement_bytes
    assert descriptor["source_base_offset"] == 0
    assert descriptor["predecessor"] == str(generation)
    assert descriptor["reason"] == "source_inode_rotation_after_generation"
    assert descriptor["divergence_witness"]["status"] == "proven_source_inode_rotation_after_generation"


def test_generation_fails_closed_without_complete_jsonl_boundary(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    original = b'{"id":"one","text":"alpha"}'
    source.write_bytes(original)
    append_source_file(source, archive, source_inode=source.stat().st_ino)
    source.write_bytes(b'{"id":"one","text":"omega"}')

    result = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )

    assert result["status"] == "source_divergence_generation_fail_closed"
    assert result["generation_failure"] == "line_boundary_not_proven"
    assert archive.read_bytes() == original
    assert not list(archive.parent.glob("session.seg*.jsonl"))


def test_generation_prefix_change_before_active_base_starts_successor(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first = b'{"id":"one","text":"stable"}\n'
    source.write_bytes(first + b'{"id":"two","text":"v1"}\n')
    append_source_file(source, archive, source_inode=source.stat().st_ino)
    source.write_bytes(first + b'{"id":"two","text":"v2"}\n')
    started = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    generation = Path(started["archive_path"])
    generation_bytes = generation.read_bytes()
    source.write_bytes(b'{"id":"one","text":"changed"}\n' + b'{"id":"two","text":"v2"}\n')

    result = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    successor = Path(result["archive_path"])
    descriptor = load_generation_descriptor(successor)

    assert result["status"] == "source_divergence_generation_started"
    assert successor != generation
    assert generation.read_bytes() == generation_bytes
    assert successor.read_bytes() == source.read_bytes()
    assert descriptor["predecessor"] == str(generation)
    assert descriptor["source_base_offset"] == 0


def test_pending_generation_descriptor_recovers_committed_segment(tmp_path):
    segment = tmp_path / "session.seg1.jsonl"
    payload = b'{"id":"one"}\n'
    segment.write_bytes(payload)
    prefix_sha = hashlib.sha256(b"").hexdigest()
    pending = {
        "contract": raw_archive_monotonic.GENERATION_CONTRACT,
        "state": "prepared",
        "generation": 1,
        "predecessor": str(tmp_path / "session.jsonl"),
        "predecessor_generation": 0,
        "reason": "source_divergence",
        "source_base_offset": 0,
        "source_prefix_sha256": prefix_sha,
        "segment_path": str(segment),
        "segment_size": len(payload),
        "segment_sha256": hashlib.sha256(payload).hexdigest(),
    }
    Path(str(segment) + raw_archive_monotonic.GENERATION_PENDING_SUFFIX).write_text(
        json.dumps(pending), encoding="utf-8"
    )

    recovered = load_generation_descriptor(segment, recover_pending=True)

    assert recovered["state"] == "committed"
    assert recovered["recovered_from_pending"] is True
    assert generation_descriptor_path(segment).exists()
    assert not Path(str(segment) + raw_archive_monotonic.GENERATION_PENDING_SUFFIX).exists()


def test_pending_generation_descriptor_rejects_wrong_segment_binding(tmp_path):
    segment = tmp_path / "session.seg1.jsonl"
    payload = b'{"id":"new"}\n'
    segment.write_bytes(payload)
    pending_path = Path(str(segment) + raw_archive_monotonic.GENERATION_PENDING_SUFFIX)
    pending_path.write_text(
        json.dumps({
            "contract": raw_archive_monotonic.GENERATION_CONTRACT,
            "state": "prepared",
            "generation": 1,
            "predecessor": str(tmp_path / "session.jsonl"),
            "predecessor_generation": 0,
            "reason": "source_divergence",
            "source_base_offset": 0,
            "source_prefix_sha256": hashlib.sha256(b"").hexdigest(),
            "segment_path": str(tmp_path / "wrong.seg1.jsonl"),
            "segment_size": len(payload),
            "segment_sha256": hashlib.sha256(payload).hexdigest(),
        }),
        encoding="utf-8",
    )

    recovered = load_generation_descriptor(segment, recover_pending=True)

    assert recovered == {}
    assert pending_path.exists()
    assert not generation_descriptor_path(segment).exists()


def test_generation_append_recovers_after_descriptor_commit_interruption(tmp_path, monkeypatch):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first = b'{"id":"one","text":"stable"}\n'
    source.write_bytes(first + b'{"id":"two","text":"v1"}\n')
    append_source_file(source, archive, source_inode=source.stat().st_ino)
    source.write_bytes(first + b'{"id":"two","text":"v2"}\n')
    started = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    generation = Path(started["archive_path"])
    before = generation.read_bytes()
    tail = b'{"id":"three","text":"tail"}\n'
    source.write_bytes(source.read_bytes() + tail)
    real_atomic_write = raw_archive_monotonic._atomic_json_write

    def interrupt_descriptor_commit(path, payload):
        if path == generation_descriptor_path(generation) and int(payload.get("segment_size", 0) or 0) > len(before):
            raise OSError("simulated descriptor commit interruption")
        return real_atomic_write(path, payload)

    monkeypatch.setattr(raw_archive_monotonic, "_atomic_json_write", interrupt_descriptor_commit)
    interrupted = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )

    assert interrupted["status"] == "source_divergence_generation_fail_closed"
    assert interrupted["generation_failure"].startswith("generation_descriptor_commit_interrupted")
    assert generation.read_bytes() == before + tail
    assert load_generation_descriptor(generation) == {}
    pending_path = Path(str(generation) + raw_archive_monotonic.GENERATION_PENDING_SUFFIX)
    assert pending_path.exists()

    monkeypatch.setattr(raw_archive_monotonic, "_atomic_json_write", real_atomic_write)
    recovered = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    descriptor = load_generation_descriptor(generation)

    assert recovered["status"] == "up_to_date"
    assert recovered["archive_path"] == str(generation)
    assert generation.read_bytes() == before + tail
    assert generation.read_bytes().count(tail) == 1
    assert descriptor["segment_size"] == len(before + tail)
    assert descriptor["recovered_from_pending"] is True
    assert descriptor["recovered_operation"] == "append_generation"
    assert not pending_path.exists()


def test_generation_append_recovers_partial_bytes_without_duplicate_tail(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first = b'{"id":"one","text":"stable"}\n'
    source.write_bytes(first + b'{"id":"two","text":"v1"}\n')
    append_source_file(source, archive, source_inode=source.stat().st_ino)
    source.write_bytes(first + b'{"id":"two","text":"v2"}\n')
    started = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    generation = Path(started["archive_path"])
    descriptor = load_generation_descriptor(generation)
    before = generation.read_bytes()
    tail = b'{"id":"three","text":"tail after partial crash"}\n'
    source.write_bytes(source.read_bytes() + tail)
    partial = tail[:11]
    previous_sha = hashlib.sha256(
        json.dumps(
            descriptor,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    pending = {
        "contract": raw_archive_monotonic.GENERATION_CONTRACT,
        "state": "prepared",
        "operation": "append_generation",
        "generation": descriptor["generation"],
        "segment_path": str(generation),
        "segment_size_before": len(before),
        "segment_size": len(before + tail),
        "source_path": str(source),
        "source_base_offset": descriptor["source_base_offset"],
        "source_snapshot_size": source.stat().st_size,
        "source_snapshot_mtime_ns": source.stat().st_mtime_ns,
        "append_sha256": hashlib.sha256(tail).hexdigest(),
        "previous_descriptor": descriptor,
        "previous_descriptor_sha256": previous_sha,
    }
    Path(str(generation) + raw_archive_monotonic.GENERATION_PENDING_SUFFIX).write_text(
        json.dumps(pending), encoding="utf-8"
    )
    with generation.open("ab") as handle:
        handle.write(partial)
        handle.flush()
        os.fsync(handle.fileno())
    in_flight = b'{"id":"four","text":"still in flight"'
    with source.open("ab") as handle:
        handle.write(in_flight)

    recovered = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    final_descriptor = load_generation_descriptor(generation)

    assert recovered["status"] == "appended_generation"
    assert generation.read_bytes() == before + tail
    assert generation.read_bytes().count(tail) == 1
    assert final_descriptor["segment_size"] == len(before + tail)
    assert final_descriptor["recovered_from_pending"] is True
    assert final_descriptor["recovered_partial_append"] is True
    assert recovered["incomplete_jsonl_tail_waiting"] is True


def test_partial_generation_recovery_fails_closed_if_unwritten_tail_changed(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first = b'{"id":"one","text":"stable"}\n'
    source.write_bytes(first + b'{"id":"two","text":"v1"}\n')
    append_source_file(source, archive, source_inode=source.stat().st_ino)
    source.write_bytes(first + b'{"id":"two","text":"v2"}\n')
    started = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    generation = Path(started["archive_path"])
    descriptor = load_generation_descriptor(generation)
    before = generation.read_bytes()
    original_tail = b'{"id":"three","text":"original tail"}\n'
    source.write_bytes(source.read_bytes() + original_tail)
    partial = original_tail[:12]
    previous_sha = hashlib.sha256(
        json.dumps(
            descriptor,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    pending = {
        "contract": raw_archive_monotonic.GENERATION_CONTRACT,
        "state": "prepared",
        "operation": "append_generation",
        "generation": descriptor["generation"],
        "segment_path": str(generation),
        "segment_size_before": len(before),
        "segment_size": len(before + original_tail),
        "source_path": str(source),
        "source_base_offset": descriptor["source_base_offset"],
        "source_snapshot_size": source.stat().st_size,
        "source_snapshot_mtime_ns": source.stat().st_mtime_ns,
        "append_sha256": hashlib.sha256(original_tail).hexdigest(),
        "previous_descriptor": descriptor,
        "previous_descriptor_sha256": previous_sha,
    }
    pending_path = Path(str(generation) + raw_archive_monotonic.GENERATION_PENDING_SUFFIX)
    pending_path.write_text(json.dumps(pending), encoding="utf-8")
    with generation.open("ab") as handle:
        handle.write(partial)
        handle.flush()
        os.fsync(handle.fileno())
    changed_tail = bytearray(original_tail)
    changed_tail[len(partial) + 2] = ord("X")
    source.write_bytes(source.read_bytes()[:-len(original_tail)] + bytes(changed_tail))

    recovered = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )

    assert recovered["status"] == "source_divergence_generation_fail_closed"
    assert recovered["generation_failure"] == "pending_generation_recovery_incomplete"
    assert generation.read_bytes() == before + partial
    assert load_generation_descriptor(generation) == {}
    assert pending_path.exists()


def test_generation_append_recovery_rejects_mismatched_previous_descriptor(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first = b'{"id":"one","text":"stable"}\n'
    source.write_bytes(first + b'{"id":"two","text":"v1"}\n')
    append_source_file(source, archive, source_inode=source.stat().st_ino)
    source.write_bytes(first + b'{"id":"two","text":"v2"}\n')
    started = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    generation = Path(started["archive_path"])
    descriptor = load_generation_descriptor(generation)
    before = generation.read_bytes()
    tail = b'{"id":"three","text":"tail"}\n'
    source.write_bytes(source.read_bytes() + tail)
    forged_previous = {**descriptor, "reason": "wrong-previous-descriptor"}
    forged_sha = hashlib.sha256(
        json.dumps(
            forged_previous,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    pending_path = Path(str(generation) + raw_archive_monotonic.GENERATION_PENDING_SUFFIX)
    pending_path.write_text(
        json.dumps({
            "contract": raw_archive_monotonic.GENERATION_CONTRACT,
            "state": "prepared",
            "operation": "append_generation",
            "generation": forged_previous["generation"],
            "segment_path": str(generation),
            "segment_size_before": len(before),
            "segment_size": len(before + tail),
            "source_path": str(source),
            "source_base_offset": forged_previous["source_base_offset"],
            "source_snapshot_size": source.stat().st_size,
            "source_snapshot_mtime_ns": source.stat().st_mtime_ns,
            "append_sha256": hashlib.sha256(tail).hexdigest(),
            "previous_descriptor": forged_previous,
            "previous_descriptor_sha256": forged_sha,
        }),
        encoding="utf-8",
    )
    partial = tail[:9]
    with generation.open("ab") as handle:
        handle.write(partial)
        handle.flush()
        os.fsync(handle.fileno())

    recovered = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )

    assert recovered["status"] == "source_divergence_generation_fail_closed"
    assert recovered["generation_failure"] == "pending_generation_recovery_incomplete"
    assert generation.read_bytes() == before + partial
    assert load_generation_descriptor(generation) == {}
    assert pending_path.exists()


def test_generation_waits_for_complete_jsonl_tail_before_advancing(tmp_path):
    source = tmp_path / "source.jsonl"
    archive = tmp_path / "memory" / "session.jsonl"
    first = b'{"id":"one","text":"stable"}\n'
    second_old = b'{"id":"two","text":"v1"}\n'
    second_new = b'{"id":"two","text":"v2"}\n'
    partial = b'{"id":"three","text":"in flight"'
    source.write_bytes(first + second_old)
    append_source_file(source, archive, source_inode=source.stat().st_ino)
    source.write_bytes(first + second_new + partial)

    started = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    generation = Path(started["archive_path"])

    assert started["status"] == "source_divergence_generation_started"
    assert generation.read_bytes() == second_new
    assert started["source_covered_bytes"] == len(first + second_new)

    waiting = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )
    assert waiting["status"] == "waiting_for_complete_jsonl_line"
    assert waiting["write_performed"] is False
    assert generation.read_bytes() == second_new

    completed_tail = partial + b'}\n'
    source.write_bytes(first + second_new + completed_tail)
    appended = append_source_file(
        source,
        archive,
        source_inode=source.stat().st_ino,
        continue_on_divergence=True,
    )

    assert appended["status"] == "appended_generation"
    assert generation.read_bytes() == second_new + completed_tail
    assert generation.read_bytes().endswith(b"\n")


def test_local_files_ingest_keeps_raw_history_after_source_delete_and_replacement(tmp_path, monkeypatch):
    connector = importlib.import_module("src.connectors.local_files_connector")
    input_dir = tmp_path / "input"
    raw_dir = tmp_path / "raw"
    index_file = raw_dir / ".source_index.jsonl"
    checkpoint_file = raw_dir / ".checkpoint.json"
    source = input_dir / "notes.txt"
    monkeypatch.setattr(connector, "INPUT_DIR", input_dir)
    monkeypatch.setattr(connector, "RAW_DIR", raw_dir)
    monkeypatch.setattr(connector, "INDEX_FILE", index_file)
    monkeypatch.setattr(connector, "CHECKPOINT_FILE", checkpoint_file)

    source.parent.mkdir(parents=True)
    source.write_text("first source version\n", encoding="utf-8")
    first = connector.ingest(dry_run=False)
    raw_file = raw_dir / f"{hashlib.md5(str(source).encode()).hexdigest()}.jsonl"
    before = raw_file.read_bytes()
    assert first["total_ingested"] == 1

    source.write_text("replacement source version\n", encoding="utf-8")
    second = connector.ingest(dry_run=False)
    after_replacement = raw_file.read_bytes()
    assert second["total_updated"] == 1
    assert len(after_replacement) > len(before)

    source.unlink()
    third = connector.ingest(dry_run=False)
    assert third["total_discovered"] == 0
    assert raw_file.read_bytes() == after_replacement


def test_jsonl_record_source_regression_keeps_existing_records(tmp_path):
    archive = tmp_path / "memory" / "session.jsonl"
    full = [{"id": "one", "text": "first"}, {"id": "two", "text": "second"}]
    first = append_jsonl_records(archive, full)
    before = archive.read_bytes()

    second = append_jsonl_records(archive, full[:1])

    assert first["appended_record_count"] == 2
    assert second["status"] == "source_regression_raw_retained"
    assert second["source_missing_record_count"] == 1
    assert second["write_performed"] is False
    assert archive.read_bytes() == before
    assert [json.loads(line)["id"] for line in archive.read_text().splitlines()] == ["one", "two"]
