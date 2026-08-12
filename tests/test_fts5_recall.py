import importlib
import json
import os
import sqlite3
import sys
import time
import plistlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _reload_p3(tmp_path, monkeypatch, *, fts5_enabled=False):
    memcore = tmp_path / "memcore"
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("MEMCORE_ZHIYI_ROOT_OVERRIDE", str(memcore / "zhiyi"))
    monkeypatch.setenv("MEMCORE_PROJECT_STATUS_ROOT_OVERRIDE", str(memcore))
    monkeypatch.setenv("MEMCORE_XINGCE_ROOT_OVERRIDE", str(memcore))
    monkeypatch.setenv("MEMCORE_FTS5_RECALL_INDEX_PATH", str(memcore / "runtime" / "fts5" / "p3.sqlite3"))
    monkeypatch.setenv("MEMCORE_FTS5_REFRESH_DEBOUNCE_SECONDS", "0")
    if fts5_enabled:
        monkeypatch.setenv("MEMCORE_FTS5_RECALL", "1")
    else:
        monkeypatch.delenv("MEMCORE_FTS5_RECALL", raising=False)
    for name in [
        "config_loader",
        "src.config_loader",
        "src.fts5_recall_index",
        "src.p3_recall",
    ]:
        sys.modules.pop(name, None)
    p3 = importlib.import_module("src.p3_recall")
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    return p3


def _write_memory(tmp_path, *, exp_id, summary, detail, source_system="codex"):
    memcore = tmp_path / "memcore"
    raw_path = memcore / "memory" / source_system / "local" / "project-a" / f"{exp_id}.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps({"text": detail}, ensure_ascii=False), encoding="utf-8")
    zhiyi_path = memcore / "zhiyi" / "case_memory" / "case_memory.jsonl"
    zhiyi_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "exp_id": exp_id,
        "type": "case_memory",
        "summary": summary,
        "detail": detail,
        "score": 0.8,
        "scope": "window/project-a",
        "source_refs": {
            "source_system": source_system,
            "source_path": str(raw_path),
            "msg_ids": [exp_id],
        },
    }
    with open(zhiyi_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def test_structure_analysis_surfaces_transparency_failure(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch)

    class ModelConfig:
        model = "fixture-model"
        provider = "fixture-provider"
        api_key_env = "FIXTURE_API_KEY"
        api_key_present = True
        base_url = "https://example.invalid/v1"

    monkeypatch.setattr(p3, "default_model_config", lambda **_kwargs: ModelConfig())
    monkeypatch.setattr(
        p3,
        "plan_evidence_bound_answer_model_use",
        lambda *_args, **_kwargs: {"should_call_model": True, "reason": "fixture"},
    )
    monkeypatch.setattr(
        p3,
        "run_evidence_bound_answer",
        lambda *_args, **_kwargs: {
            "model_call_performed": True,
            "answer": "fixture",
            "verdict": "answered",
            "confidence": 1.0,
            "supporting_refs": ["exp-1"],
            "transparency_recorded": False,
            "transparency_error": "OSError: ledger lock timeout",
            "transparency_warning": "model_call_succeeded_but_transparency_ledger_write_failed",
        },
    )

    analysis, _matched = p3._run_structure_analysis(
        "query",
        [{"exp_id": "exp-1", "summary": "fixture evidence"}],
        {"enable_structure_analysis": True},
    )

    assert analysis["transparency_recorded"] is False
    assert analysis["transparency_error"] == "OSError: ledger lock timeout"
    assert analysis["transparency_warning"] == "model_call_succeeded_but_transparency_ledger_write_failed"


def test_substring_mode_does_not_load_an_empty_vector_contract(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch)
    config_path = tmp_path / "model_config.json"
    config_path.write_text(json.dumps({"recall": {"mode": "substring"}}), encoding="utf-8")
    p3._CONFIG_PATH = str(config_path)
    p3._lancedb_v2_cache.update({
        "tok": None,
        "model": None,
        "tbl": None,
        "row_count": None,
        "status": {},
    })

    def fail_if_loaded():
        raise AssertionError("substring mode must not load a vector contract")

    monkeypatch.setattr(p3, "_v2_model_contract", fail_if_loaded)

    engine = p3._get_v2_engine()
    status = p3.vector_runtime_status(load_model=False)

    assert engine["model"] is None
    assert engine["tbl"] is None
    assert status["status"] == "off"
    assert status["expected"] is False
    assert status["issues"] == []


def test_health_warmup_loads_model_and_runs_encoding_probe(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch)
    load_calls = []

    def vector_status(load_model=False):
        load_calls.append(load_model)
        return {
            "ok": True,
            "expected": True,
            "model_loaded": True,
            "table_loaded": True,
        }

    monkeypatch.setattr(p3, "vector_runtime_status", vector_status)
    monkeypatch.setattr(p3, "_warmup_vector_engine", lambda: {
        "enabled": True, "ok": True, "seconds": 1.25,
    })
    monkeypatch.setattr(p3, "get_memories", lambda: [{"exp_id": "one"}])

    payload = p3._health_payload("warmup")

    assert load_calls == [True, False]
    assert payload["memory_count"] == 1
    assert payload["vector_recall"]["model_loaded"] is True
    assert payload["vector_warmup"]["ok"] is True


def test_fts5_index_builds_and_searches_trigram(tmp_path):
    from src.fts5_recall_index import build_index, capability_probe, search_index

    probe = capability_probe()
    assert probe["ok"] is True
    memories = [
        {
            "exp_id": "exp-remote-desktop",
            "_type": "case_memory",
            "scope": "window/project-a",
            "summary": "远程桌面不要直暴露3389",
            "detail": "先用跳板或 VPN，再开放远程桌面。",
            "source_refs": {"source_path": str(tmp_path / "source.jsonl")},
        }
    ]
    index_path = tmp_path / "fts5.sqlite3"
    built = build_index(memories, str(index_path))
    assert built["ok"] is True
    assert built["doc_count"] == 1

    found = search_index(query="远程桌面 3389", index_path=str(index_path), expected_signature=built["corpus_signature"])
    assert found["ok"] is True
    assert found["status"]["applied"] is True
    assert found["rows"][0]["exp_id"] == "exp-remote-desktop"


def test_fts5_search_reports_concurrent_build_as_not_ready(tmp_path):
    from src.fts5_recall_index import search_index

    index_path = tmp_path / "fts5-building.sqlite3"
    con = sqlite3.connect(index_path)
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute(
        "CREATE TABLE docs("
        "doc_id TEXT PRIMARY KEY, exp_id TEXT, memory_type TEXT, scope TEXT, "
        "summary TEXT, detail TEXT, source_refs TEXT, content_sha256 TEXT NOT NULL)"
    )
    con.execute(
        "CREATE VIRTUAL TABLE docs_fts "
        "USING fts5(doc_id UNINDEXED, summary, detail, tokenize='trigram')"
    )
    con.commit()
    con.close()

    result = search_index(
        query="开局注入防截断",
        index_path=str(index_path),
        expected_signature="pending-build-signature",
    )

    assert result["ok"] is False
    assert result["rows"] == []
    assert result["status"]["error"] == "index_not_ready"
    assert result["status"]["build_in_progress"] is True


def test_fts5_match_query_avoids_short_broad_ascii_terms():
    from src.fts5_recall_index import _match_query

    match_query, terms = _match_query("Time Library 2026.7.25 release readiness")

    assert "Time" not in terms
    assert len(terms) <= 4
    assert "readiness" in terms
    assert '"readiness"' in match_query


def test_fts5_search_timeout_falls_back_instead_of_occupying_request(tmp_path, monkeypatch):
    from src import fts5_recall_index
    from src.fts5_recall_index import build_index, search_index

    index_path = tmp_path / "fts5-timeout.sqlite3"
    memories = [
        {
            "exp_id": f"doc-{index}",
            "summary": "common searchable marker",
            "detail": f"common searchable detail {index}",
        }
        for index in range(2000)
    ]
    assert build_index(memories, str(index_path))["ok"] is True
    monkeypatch.setattr(fts5_recall_index, "_query_timeout_seconds", lambda: 0.000001)

    result = search_index(query="common searchable marker", index_path=str(index_path), limit=20)

    assert result["ok"] is False
    assert result["rows"] == []
    assert result["status"]["error"] == "query_timeout"
    assert result["status"]["fallback_required"] is True


def test_fts5_stale_index_falls_back_before_match_query(tmp_path):
    from src.fts5_recall_index import build_index, search_index

    index_path = tmp_path / "fts5-stale.sqlite3"
    assert build_index(
        [{"exp_id": "old", "summary": "old searchable marker", "detail": "old detail"}],
        str(index_path),
        source_signature="old-source-snapshot",
    )["ok"] is True

    result = search_index(
        query="old searchable marker",
        index_path=str(index_path),
        expected_source_signature="new-source-snapshot",
    )

    assert result["ok"] is False
    assert result["rows"] == []
    assert result["status"]["stale"] is True
    assert result["status"]["error"] == "stale_index"
    assert result["status"]["fallback_required"] is True
    assert result["status"]["stale_index_skipped"] is True


def test_fts5_atomic_build_publishes_only_complete_candidate(tmp_path, monkeypatch):
    from src import fts5_recall_index
    from src.fts5_recall_index import build_index, build_index_atomically, search_index

    index_path = tmp_path / "fts5-atomic.sqlite3"
    old = {"exp_id": "old", "summary": "old searchable marker", "detail": "old detail"}
    new = {"exp_id": "new", "summary": "new searchable marker", "detail": "new detail"}
    assert build_index([old], str(index_path))["ok"] is True

    rejected = build_index_atomically(
        [new],
        str(index_path),
        expected_signature="not-the-new-signature",
    )
    assert rejected["ok"] is False
    assert rejected["write_performed"] is False
    assert search_index(query="old searchable", index_path=str(index_path))["rows"][0]["exp_id"] == "old"

    original_replace = fts5_recall_index._replace_with_retry
    monkeypatch.setattr(
        fts5_recall_index,
        "_replace_with_retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("fixture publish refusal")),
    )
    publish_failed = build_index_atomically([new], str(index_path))
    assert publish_failed["ok"] is False
    assert publish_failed["write_performed"] is False
    assert search_index(query="old searchable", index_path=str(index_path))["rows"][0]["exp_id"] == "old"

    source_changed = build_index_atomically(
        [new],
        str(index_path),
        source_signature="snapshot-before-build",
        source_signature_probe=lambda: "snapshot-after-build",
    )
    assert source_changed["ok"] is False
    assert source_changed["write_performed"] is False
    assert "source_snapshot_changed_during_build" in source_changed["error"]
    assert search_index(query="old searchable", index_path=str(index_path))["rows"][0]["exp_id"] == "old"

    monkeypatch.setattr(fts5_recall_index, "_replace_with_retry", original_replace)
    published = build_index_atomically([new], str(index_path))
    assert published["ok"] is True
    assert published["atomic_publish"] is True
    assert search_index(query="new searchable", index_path=str(index_path))["rows"][0]["exp_id"] == "new"
    assert not list(tmp_path.glob(".fts5-atomic.sqlite3.build-*"))


def test_fts5_candidate_fsync_uses_writable_descriptor_for_windows_crt(tmp_path, monkeypatch):
    from src import fts5_recall_index

    candidate = tmp_path / "fts5-candidate.sqlite3"
    candidate.write_bytes(b"candidate")
    opened_modes = []
    original_open = Path.open

    def tracked_open(path, mode="r", *args, **kwargs):
        if path == candidate:
            opened_modes.append(mode)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_open)
    monkeypatch.setattr(fts5_recall_index.os, "fsync", lambda _descriptor: None)

    fts5_recall_index._fsync_file(candidate)

    assert opened_modes == ["r+b"]


def test_p3_substring_uses_fts5_only_when_explicitly_enabled(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    _write_memory(
        tmp_path,
        exp_id="exp-slow-meta",
        summary="普通状态流水",
        detail="这条只是普通流水，包含远程和桌面两个词，但没有 3389。",
    )
    _write_memory(
        tmp_path,
        exp_id="exp-3389",
        summary="远程桌面不要直暴露3389",
        detail="远程桌面端口 3389 不要直接暴露在公网。",
    )

    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    default_result = p3.handle_recall({"query": "远程桌面 3389", "recall_mode": "substring", "top_k": 2})
    assert "fts5_applied" not in default_result

    from src.fts5_recall_index import build_index

    index_path = tmp_path / "memcore" / "runtime" / "fts5" / "p3.sqlite3"
    indexed_memories = p3.get_memories()
    built = build_index(
        indexed_memories,
        str(index_path),
        source_signature=p3._fts5_expected_source_signature(indexed_memories),
    )
    assert built["ok"] is True

    enabled_result = p3.handle_recall({
        "query": "远程桌面 3389",
        "recall_mode": "substring",
        "top_k": 2,
        "fts5_recall": True,
    })
    assert enabled_result["fts5_applied"] is True
    assert enabled_result["fts5_status"]["error"] is None
    assert enabled_result["fts5_status"]["stale"] is False
    assert enabled_result["default_vector_freshness_covered"] is False
    assert enabled_result["primary_recall_backend"] == "keyword+fts5"
    assert enabled_result["ranking_owner"] in ("keyword", "keyword+fts5")
    assert enabled_result["matched_memories"][0]["exp_id"] == "exp-3389"
    assert enabled_result["matched_memories"][0]["matched_by"] == "fts5_bm25"
    assert enabled_result["matched_memories"][0]["rank_reason"] == "sqlite_fts5_trigram_bm25"
    assert "_fts5" not in enabled_result["matched_memories"][0]["archive_card"]


def test_p3_default_recall_uses_bounded_recent_delta_without_fts5(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    _write_memory(
        tmp_path,
        exp_id="exp-old-vector-hit",
        summary="旧向量命中",
        detail="这条旧记忆会模拟 vector 先命中，但不包含新 token。",
    )
    p3.get_memories()

    def fake_vector_search(_query, top_k=5, scope_filter=None, type_filter=None):
        raise AssertionError("bounded recent_delta hit must return before vector search")

    monkeypatch.setattr(p3, "vector_search_v2", fake_vector_search)
    monkeypatch.setattr(p3, "vector_runtime_status", lambda load_model=False: {"ok": True, "expected": True})

    token = "fresh-default-recall-token-0704"
    _write_memory(
        tmp_path,
        exp_id="exp-fresh-default-recall",
        summary=f"刚写入的新记忆 {token}",
        detail=f"默认召回必须立刻看见这条新记忆，nonce={token}。",
    )

    result = p3.handle_recall({"query": token, "top_k": 3})
    ids = [item.get("exp_id") for item in result["matched_memories"]]

    assert result["mode"] == "vector_with_bounded_recent_delta"
    assert "fts5_applied" not in result
    assert result["recent_delta_applied"] is True
    assert result["freshness_fast_path"] == "bounded_recent_delta"
    assert result["freshness_boundary"] == "bounded_recent_delta"
    assert result["default_recall_freshness_covered"] is True
    assert result["default_vector_freshness_covered"] is False
    assert result["vector_search_deferred_for_recent_delta"] is True
    assert ids[0] == "exp-fresh-default-recall"
    assert result["matched_memories"][0]["matched_by"] == "recent_delta"


def test_p3_default_recall_uses_bounded_recent_tail_on_cold_cache(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    token = "fresh-default-cold-tail-token-0704"
    _write_memory(
        tmp_path,
        exp_id="exp-fresh-cold-tail",
        summary=f"冷启动刚写入的新记忆 {token}",
        detail=f"默认召回在无 cache baseline 时也必须先看 bounded recent tail，nonce={token}。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    p3._MEMORY_LAST_SERVED_SIGNATURE = None

    def fake_vector_search(_query, top_k=5, scope_filter=None, type_filter=None):
        raise AssertionError("cold bounded recent tail hit must return before vector search")

    monkeypatch.setattr(p3, "vector_search_v2", fake_vector_search)
    monkeypatch.setattr(p3, "vector_runtime_status", lambda load_model=False: {"ok": True, "expected": True})

    result = p3.handle_recall({"query": token, "top_k": 3})

    assert result["mode"] == "vector_with_bounded_recent_delta"
    assert result["recent_delta_applied"] is True
    assert result["recent_delta_status"]["reason"] == "bounded_recent_tail_default_recall_hit"
    assert result["recent_delta_status"]["cold_start_tail"] is True
    assert result["freshness_fast_path"] == "bounded_recent_delta"
    assert result["default_recall_freshness_covered"] is True
    assert result["default_vector_freshness_covered"] is False
    assert result["vector_search_deferred_for_recent_delta"] is True
    assert result["structure_analysis"]["reason"] == "skipped_recent_delta_fast_path"
    assert result["matched_memories"][0]["exp_id"] == "exp-fresh-cold-tail"
    assert result["matched_memories"][0]["matched_by"] == "recent_delta"


def test_p3_keyword_filter_parses_query_once_and_skips_unused_source_refs(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    memories = [
        {
            "_type": "case_memory",
            "exp_id": f"exp-{index}",
            "summary": "release readiness marker",
            "detail": "bounded keyword filtering",
            "source_refs": "{}",
        }
        for index in range(100)
    ]
    original_query_terms = p3._query_terms
    calls = 0

    def counted_query_terms(query):
        nonlocal calls
        calls += 1
        return original_query_terms(query)

    monkeypatch.setattr(p3, "_query_terms", counted_query_terms)
    monkeypatch.setattr(
        p3,
        "_source_refs_for_filter",
        lambda *_args: (_ for _ in ()).throw(AssertionError("source refs should stay lazy")),
    )

    result = p3.filter_memories(memories, query="release readiness")

    assert len(result) == len(memories)
    assert calls == 1


def test_p3_explicit_fts5_request_schedules_missing_index_refresh_off_request_path(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-no-index",
        summary="开局注入防截断",
        detail="开局注入只留阅读区 lanes，避免客户端截断。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    def fail_if_built_in_p3(*_args, **_kwargs):
        raise AssertionError("FTS5 refresh must not build inside the P3 process")

    monkeypatch.setattr(p3, "_fts5_build_index", fail_if_built_in_p3)
    started = time.monotonic()
    first = p3.handle_recall({"query": "开局注入防截断", "recall_mode": "substring", "top_k": 1})
    foreground_seconds = time.monotonic() - started
    assert first["fts5_applied"] is False
    assert first["fts5_status"]["error"] in {"index_missing", "index_not_ready"}
    assert first["fts5_status"]["auto_refresh_attempted"] is True
    assert first["fts5_status"]["auto_refresh_pending"] is True
    assert first["fts5_status"]["auto_refresh_trigger"] == first["fts5_status"]["error"]
    assert first["default_recall_freshness_covered"] is False
    assert foreground_seconds < 1.0
    worker_pid = (
        p3._FTS5_REFRESH_PROCESS.pid
        if p3._FTS5_REFRESH_PROCESS is not None
        else p3._FTS5_REFRESH_STATUS.get("worker_pid")
    )
    assert worker_pid != os.getpid()

    if p3._FTS5_REFRESH_THREAD is not None:
        p3._FTS5_REFRESH_THREAD.join(timeout=5)
    assert p3._FTS5_REFRESH_STATUS["atomic_publish"] is True
    assert p3._FTS5_REFRESH_STATUS["worker_pid"] != os.getpid()
    second = p3.handle_recall({"query": "开局注入防截断", "recall_mode": "substring", "top_k": 1})
    assert second["fts5_applied"] is True
    assert second["fts5_status"]["error"] is None
    assert second["fts5_status"]["stale"] is False
    assert second["fts5_status"]["auto_refresh_completed"] is True
    assert second["default_recall_freshness_covered"] is True
    assert second["matched_memories"][0]["exp_id"] == "exp-no-index"


def test_p3_explicit_fts5_request_schedules_stale_index_refresh_off_request_path(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-before-refresh",
        summary="旧索引内容",
        detail="这条先进入 FTS5 索引。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    from src.fts5_recall_index import build_index

    index_path = tmp_path / "memcore" / "runtime" / "fts5" / "p3.sqlite3"
    indexed_memories = p3.get_memories()
    assert build_index(
        indexed_memories,
        str(index_path),
        source_signature=p3._fts5_expected_source_signature(indexed_memories),
    )["ok"] is True
    _write_memory(
        tmp_path,
        exp_id="exp-after-refresh",
        summary="自动刷新唯一标记 durability-refresh-0710",
        detail="显式 FTS5 请求必须发现 corpus signature 变化并自动追平。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    first = p3.handle_recall({
        "query": "durability-refresh-0710",
        "recall_mode": "substring",
        "top_k": 2,
    })

    assert first["fts5_status"]["stale"] is True
    assert first["fts5_status"]["error"] == "stale_index"
    assert first["fts5_status"]["stale_index_skipped"] is True
    assert first["fts5_applied"] is False
    assert first["fts5_status"]["auto_refresh_attempted"] is True
    assert first["fts5_status"]["auto_refresh_pending"] is True
    assert first["fts5_status"]["auto_refresh_trigger"] == "source_signature_mismatch"
    assert first["default_recall_freshness_covered"] is False

    p3._FTS5_REFRESH_THREAD.join(timeout=5)
    second = p3.handle_recall({
        "query": "durability-refresh-0710",
        "recall_mode": "substring",
        "top_k": 2,
    })
    assert second["fts5_status"]["stale"] is False
    assert second["fts5_status"]["auto_refresh_completed"] is True
    assert second["default_recall_freshness_covered"] is True
    assert second["matched_memories"][0]["exp_id"] == "exp-after-refresh"


def test_p3_fts5_source_signature_is_bound_per_memory_snapshot(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-signature-cache",
        summary="signature cache marker",
        detail="Repeated recalls must not rehash an unchanged memory snapshot.",
    )
    memories = p3.get_memories()
    monkeypatch.setattr(
        p3,
        "_fts5_corpus_signature",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("foreground corpus hash forbidden")),
    )
    first = p3._fts5_expected_source_signature(memories)
    second = p3._fts5_expected_source_signature(memories)

    assert first == second
    assert len(first) == 64

    replacement = list(memories)
    assert p3._fts5_expected_source_signature(replacement) == ""


def test_p3_fts5_query_compares_against_current_source_snapshot(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-before-source-change",
        summary="before source change",
        detail="initial memory snapshot",
    )
    memories = p3.get_memories()
    bound_before = p3._fts5_expected_source_signature(memories)
    _write_memory(
        tmp_path,
        exp_id="exp-after-source-change",
        summary="after source change",
        detail="current source snapshot",
    )
    captured = {}

    def fake_search_index(**kwargs):
        captured.update(kwargs)
        return {
            "rows": [],
            "status": {
                "enabled": True,
                "applied": False,
                "error": "stale_index",
                "stale": True,
                "stale_reason": "source_signature_mismatch",
            },
        }

    monkeypatch.setattr(p3, "_fts5_search_index", fake_search_index)
    monkeypatch.setattr(p3, "_schedule_fts5_refresh", lambda *_args, **_kwargs: "deferred_source_change")
    monkeypatch.setattr(
        p3,
        "_fts5_memory_doc_id",
        lambda *_args: (_ for _ in ()).throw(AssertionError("zero FTS5 rows must not build a doc map")),
    )
    p3._fts5_ordered_memories(memories, "source change", 2)

    assert captured["expected_source_signature"] == p3._fts5_current_source_signature()
    assert captured["expected_source_signature"] != bound_before


def test_p3_source_signature_tracks_xingce_candidates_and_actions(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    before = p3._memories_source_signature()
    root = tmp_path / "memcore" / "output" / "xingce_work_experience"
    candidate_path = root / "candidates" / "xingce-fixture-candidate.json"
    action_path = root / "actions" / "fixture.jsonl"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    action_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text("{}", encoding="utf-8")
    after_candidate = p3._memories_source_signature()
    action_path.write_text("{}\n", encoding="utf-8")
    after_action = p3._memories_source_signature()

    assert after_candidate != before
    assert after_action != after_candidate
    assert str(candidate_path) in {entry[0] for entry in after_action}
    assert str(action_path) in {entry[0] for entry in after_action}


def test_p3_fts5_refresh_debounces_recent_source_changes(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    monkeypatch.setenv("MEMCORE_FTS5_REFRESH_DEBOUNCE_SECONDS", "300")
    _write_memory(
        tmp_path,
        exp_id="exp-refresh-debounce",
        summary="refresh debounce marker",
        detail="Recent source writes must not start a full rebuild immediately.",
    )
    memories = p3.get_memories()

    schedule = p3._schedule_fts5_refresh(
        memories,
        p3._fts5_index_path(),
        "source_signature_mismatch",
        expected_source_signature=p3._fts5_expected_source_signature(memories),
    )

    assert schedule == "deferred_source_change"
    assert p3._FTS5_REFRESH_PROCESS is None
    assert p3._FTS5_REFRESH_STATUS["deferred_seconds"] > 0


def test_p3_fts5_legacy_index_migration_bypasses_startup_debounce(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-legacy-source-signature",
        summary="legacy FTS5 index marker",
        detail="An index without source_signature must migrate after restart.",
    )
    memories = p3.get_memories()
    expected = p3._fts5_expected_source_signature(memories)
    captured = {}

    monkeypatch.setattr(
        p3,
        "_fts5_status",
        lambda: {"exists": True, "source_signature": ""},
    )

    def schedule(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "scheduled"

    monkeypatch.setattr(p3, "_schedule_fts5_refresh", schedule)

    result = p3._schedule_startup_fts5_refresh(memories)

    assert result == "scheduled"
    assert captured["args"][2] == "startup_source_signature_missing"
    assert captured["kwargs"]["expected_source_signature"] == expected
    assert captured["kwargs"]["bypass_debounce"] is True


def test_p3_fts5_normal_startup_staleness_keeps_debounce(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-current-source-signature",
        summary="current FTS5 index marker",
        detail="Ordinary source churn keeps the configured quiet window.",
    )
    memories = p3.get_memories()
    captured = {}

    monkeypatch.setattr(
        p3,
        "_fts5_status",
        lambda: {"exists": True, "source_signature": "old-signature"},
    )

    def schedule(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "deferred_source_change"

    monkeypatch.setattr(p3, "_schedule_fts5_refresh", schedule)

    result = p3._schedule_startup_fts5_refresh(memories)

    assert result == "deferred_source_change"
    assert captured["args"][2] == "startup_corpus_change"
    assert captured["kwargs"]["bypass_debounce"] is False


def test_p3_fts5_missing_index_keeps_debounce(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-no-index-yet",
        summary="FTS5 is enabled before the first index exists",
        detail="Initial construction must retain the normal quiet window.",
    )
    memories = p3.get_memories()
    captured = {}

    monkeypatch.setattr(
        p3,
        "_fts5_status",
        lambda: {"exists": False, "fts5_enabled": True, "source_signature": ""},
    )

    def schedule(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "deferred_source_change"

    monkeypatch.setattr(p3, "_schedule_fts5_refresh", schedule)

    result = p3._schedule_startup_fts5_refresh(memories)

    assert result == "deferred_source_change"
    assert captured["args"][2] == "startup_corpus_change"
    assert captured["kwargs"]["bypass_debounce"] is False


def test_p3_fts5_bypass_debounce_reaches_existing_refresh_lock(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    monkeypatch.setattr(
        p3,
        "_fts5_refresh_debounce_remaining",
        lambda: (_ for _ in ()).throw(AssertionError("legacy migration must not debounce")),
    )
    monkeypatch.setattr(
        p3,
        "_fts5_acquire_refresh_lock",
        lambda *_args, **_kwargs: ("", "already_running"),
    )

    result = p3._schedule_fts5_refresh(
        [],
        p3._fts5_index_path(),
        "startup_source_signature_missing",
        expected_source_signature="expected",
        bypass_debounce=True,
    )

    assert result == "already_running"


def test_p3_bm25_stale_manifest_is_not_cached_as_current(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch)
    initial = [
        {"exp_id": "bm25-old", "summary": "old bm25", "detail": "initial corpus"},
    ]
    p3._build_full_index_from_docs(initial, batch_size=1)
    p3._BM25_MANIFEST_CACHE.update({"manifest": None, "signature": None, "N": 0})
    current = initial + [
        {"exp_id": "bm25-new", "summary": "new bm25", "detail": "changed corpus"},
    ]

    _first_manifest, first_status = p3._ensure_bm25_seg_index(current)
    _second_manifest, second_status = p3._ensure_bm25_seg_index(current)

    assert first_status == "stale_served"
    assert second_status == "stale_served"


def test_p3_bm25_filtered_query_does_not_flush_memtable(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch)
    for index in range(4):
        _write_memory(
            tmp_path,
            exp_id=f"bm25-filtered-{index}",
            summary="shared filtered marker",
            detail=f"query-time scoring fixture {index}",
        )
    monkeypatch.setattr(p3, "_trigger_bm25_background_build", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        p3,
        "_memtable_insert",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("query path must stay read-only")),
    )
    monkeypatch.setattr(
        p3,
        "_flush_memtable_to_main_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("query path must not flush")),
    )
    monkeypatch.setattr(
        p3,
        "_load_segment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("filtered query must not reopen segments")),
    )

    result = p3.handle_recall({
        "query": "shared filtered marker",
        "recall_mode": "substring",
        "top_k": 2,
    })

    assert result["returned"] == 2
    assert result["bm25_applied"] is True
    assert result["bm25_index_status"] == "cold_start"


def test_p3_bm25_all_zero_leg_preserves_primary_rank(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch)
    memories = [
        {"exp_id": "primary-second", "summary": "second", "detail": ""},
        {"exp_id": "primary-first", "summary": "first", "detail": ""},
    ]
    monkeypatch.setattr(
        p3,
        "_ensure_bm25_seg_index",
        lambda _corpus: ({"idf_map": {"marker": 1.0}, "avg_dl": 1.0}, "cache_hit"),
    )
    monkeypatch.setattr(p3, "_bm25_score_single", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(
        p3,
        "rank_memory",
        lambda memory, _query: 1.0 if memory["exp_id"] == "primary-first" else 0.5,
    )

    scored = p3._compute_bm25_scores(
        memories,
        "marker",
        corpus_memories=memories,
    )

    assert [memory["exp_id"] for _score, memory in scored] == [
        "primary-first",
        "primary-second",
    ]


def test_fts5_worker_uses_darwin_background_policy(monkeypatch):
    from tools import build_fts5_recall_index as worker

    calls = []
    monkeypatch.setattr(worker.os, "name", "posix")
    monkeypatch.setattr(worker.sys, "platform", "darwin")
    monkeypatch.setattr(worker.os, "nice", lambda value: calls.append(("nice", value)))
    monkeypatch.setattr(worker.os, "getpid", lambda: 4321)
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda command, **kwargs: calls.append(("run", command, kwargs)),
    )

    result = worker._lower_process_priority()

    assert result == "darwin_background_nice_10"
    assert ("nice", 10) in calls
    run_call = next(call for call in calls if call[0] == "run")
    assert run_call[1] == ["/usr/sbin/taskpolicy", "-b", "-p", "4321"]
    assert run_call[2]["check"] is True


def test_macos_installer_keeps_p3_foreground_and_watchers_background(tmp_path):
    installer = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    marker = 'python3 - "$plist" "$label" "$INSTALL_ROOT" "$LOG_DIR" "$log_name" "$DIALOG_ENTRY_HOST" "$DIALOG_ENTRY_TOKEN" "$@" <<\'PY\'\n'
    embedded = installer.split(marker, 1)[1].split("\nPY\n", 1)[0]
    script = tmp_path / "write_launch_agent.py"
    script.write_text(embedded, encoding="utf-8")

    def render(label, log_name):
        plist_path = tmp_path / f"{label}.plist"
        subprocess.run(
            [
                sys.executable,
                str(script),
                str(plist_path),
                label,
                str(tmp_path / "install"),
                str(tmp_path / "logs"),
                log_name,
                "127.0.0.1",
                "",
                "/usr/bin/python3",
                "service.py",
            ],
            check=True,
        )
        return plistlib.loads(plist_path.read_bytes())

    p3 = render("com.memcorecloud.p3-recall", "p3-recall")
    watcher = render("com.memcorecloud.p0-watcher", "p0-watcher")

    assert p3["ProcessType"] == "Interactive"
    assert "LowPriorityIO" not in p3
    assert watcher["ProcessType"] == "Background"
    assert watcher["LowPriorityIO"] is True


def test_fts5_existing_index_catches_up_without_process_env_flag(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    first = _write_memory(
        tmp_path,
        exp_id="exp-existing-index",
        summary="先建立索引",
        detail="existing index",
    )
    from src import fts5_recall_index

    index_path = tmp_path / "memcore" / "runtime" / "fts5" / "p3.sqlite3"
    assert fts5_recall_index.build_index([first], str(index_path))["ok"] is True
    second = _write_memory(
        tmp_path,
        exp_id="exp-catchup-without-env",
        summary="无进程 env 也要追平已存在索引",
        detail="existing index catchup",
    )

    report = fts5_recall_index.fts5_build_or_catchup([first, second])

    assert report["ok"] is True
    assert report["refresh_trigger"] == "existing_index_catchup"
    assert report["doc_count"] == 2


def test_p3_default_substring_does_not_read_feature_flags(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    _write_memory(
        tmp_path,
        exp_id="exp-default-no-flag-io",
        summary="默认路径不要读 FTS5 flag",
        detail="默认 substring recall 不应该为了 FTS5 去读 feature_flags.json。",
    )
    flag_path = tmp_path / "missing-feature-flags.json"
    monkeypatch.setenv("MEMCORE_FEATURE_FLAGS", str(flag_path))

    def explode(_name):
        raise AssertionError("feature flag path should not be read on default recall")

    monkeypatch.setattr(p3, "_feature_flag_enabled", explode)
    result = p3.handle_recall({"query": "默认路径 FTS5", "recall_mode": "substring", "top_k": 1})
    assert result["matched_memories"]
    assert "fts5_applied" not in result


def test_p3_feature_flag_config_is_not_a_default_enable_path(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    _write_memory(
        tmp_path,
        exp_id="exp-config-flag-disabled",
        summary="feature flag config 不能默认打开 FTS5",
        detail="块9要求 FTS5 只通过 body 或 MEMCORE_FTS5_RECALL 显式打开。",
    )
    flags = tmp_path / "feature_flags.json"
    flags.write_text(json.dumps({"fts5_recall": True}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("MEMCORE_FEATURE_FLAGS", str(flags))
    monkeypatch.setenv("MEMCORE_ENABLE_FEATURE_FLAG_FTS5_RECALL", "1")

    result = p3.handle_recall({"query": "feature flag config FTS5", "recall_mode": "substring", "top_k": 1})
    assert result["matched_memories"]
    assert "fts5_applied" not in result


def test_p3_vector_mode_falls_back_to_fts5_when_assets_are_unavailable(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-vector-no-fts5",
        summary="vector 模式不签 FTS5 freshness",
        detail="FTS5 只属于 substring leg。",
    )
    result = p3.handle_recall({"query": "vector 模式", "recall_mode": "vector", "top_k": 1})
    assert result["mode"] == "vector_assets_unavailable_fallback_fts5"
    assert result["vector_fallback_applied"] is True
    assert result["vector_fallback_backend"] == "FTS5+BM25"
    assert result["vector_degraded"] is True


def test_p3_open_file_limit_is_raised_for_fragmented_lancedb_tables(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    status = p3.OPEN_FILE_LIMIT_STATUS
    assert status["requested_soft_limit"] == 4096
    if status["supported"] and not status["error"]:
        assert status["soft_limit_after"] >= min(4096, status["hard_limit"])


def test_p3_fts5_fuses_with_keyword_results_instead_of_replacing_them(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    keyword_only = _write_memory(
        tmp_path,
        exp_id="exp-keyword-only",
        summary="远程桌面 3389 keyword baseline",
        detail="这条 keyword 命中，但稍后会被伪造的 FTS5 索引漏掉。",
    )
    _write_memory(
        tmp_path,
        exp_id="exp-fts5-ranked",
        summary="远程桌面 3389 fts5 ranked",
        detail="这条会从 FTS5 返回。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    original_doc_id = p3._fts5_memory_doc_id

    def fake_search_index(**_kwargs):
        return {
            "rows": [{
                "doc_id": original_doc_id({
                    "exp_id": "exp-fts5-ranked",
                    "_type": "case_memory",
                    "scope": "window/project-a",
                    "summary": "远程桌面 3389 fts5 ranked",
                    "detail": "这条会从 FTS5 返回。",
                    "source_refs": keyword_only["source_refs"],
                }),
                "exp_id": "exp-fts5-ranked",
                "rank": -1.0,
                "memory_type": "case_memory",
            }],
            "status": {
                "enabled": True,
                "applied": True,
                "error": None,
                "matched_count": 1,
                "raw_matched_count": 1,
                "stale": False,
            },
        }

    monkeypatch.setattr(p3, "_fts5_search_index", fake_search_index)
    result = p3.handle_recall({"query": "远程桌面 3389", "recall_mode": "substring", "top_k": 3})
    ids = [item["exp_id"] for item in result["matched_memories"]]
    assert "exp-keyword-only" in ids
    assert "exp-fts5-ranked" in ids
    assert result["fts5_applied"] is True
    assert result["fts5_status"]["post_lifecycle_matched_count"] == 1
    assert result["fts5_status"]["fts5_only_hits"] == 0
    assert result["fts5_status"]["fts5_keyword_overlap_hits"] == 1
    assert result["fts5_status"]["fusion_policy"] == "keyword_base_with_bounded_fts5_boost"


def test_p3_fts5_raw_match_filtered_out_is_not_reported_as_applied(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-visible-keyword",
        summary="可见 keyword 记录",
        detail="scope 过滤后仍然可见。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    def fake_search_index(**_kwargs):
        return {
            "rows": [{
                "doc_id": "missing-doc-id",
                "exp_id": "exp-filtered-out",
                "rank": -1.0,
                "memory_type": "case_memory",
            }],
            "status": {
                "enabled": True,
                "applied": True,
                "error": None,
                "matched_count": 1,
                "raw_matched_count": 1,
                "stale": False,
            },
        }

    monkeypatch.setattr(p3, "_fts5_search_index", fake_search_index)
    result = p3.handle_recall({"query": "可见 keyword", "recall_mode": "substring", "top_k": 1})
    assert result["fts5_applied"] is False
    assert result["fts5_status"]["raw_matched_count"] == 1
    assert result["fts5_status"]["post_filter_matched_count"] == 0
    assert result["fts5_status"]["discarded_by_filter_count"] == 1
    assert result["primary_recall_backend"] == "keyword"


def test_p3_fts5_only_hits_do_not_replace_keyword_base(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-visible-keyword",
        summary="可见 keyword 记录",
        detail="keyword 基线必须保留。",
    )
    _write_memory(
        tmp_path,
        exp_id="exp-fts5-only",
        summary="FTS5 only hit",
        detail="这条只从 FTS5 返回，不该替代基线。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    original_doc_id = p3._fts5_memory_doc_id

    def fake_search_index(**_kwargs):
        return {
            "rows": [{
                "doc_id": original_doc_id({
                    "exp_id": "exp-fts5-only",
                    "_type": "case_memory",
                    "scope": "window/project-a",
                    "summary": "FTS5 only hit",
                    "detail": "这条只从 FTS5 返回，不该替代基线。",
                }),
                "exp_id": "exp-fts5-only",
                "rank": -1.0,
                "memory_type": "case_memory",
            }],
            "status": {
                "enabled": True,
                "applied": True,
                "error": None,
                "matched_count": 1,
                "raw_matched_count": 1,
                "stale": False,
            },
        }

    monkeypatch.setattr(p3, "_fts5_search_index", fake_search_index)
    result = p3.handle_recall({"query": "可见 keyword", "recall_mode": "substring", "top_k": 2})
    ids = [item["exp_id"] for item in result["matched_memories"]]
    assert "exp-visible-keyword" in ids
    assert "exp-fts5-only" not in ids
    assert result["fts5_applied"] is False
    assert result["fts5_status"]["fts5_only_hits"] == 1
    assert result["primary_recall_backend"] == "keyword"


def test_p3_fts5_used_skips_xingce_supplement_to_preserve_matched_by(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-fts5-no-supplement",
        summary="FTS5 matched_by 不应被 supplement 覆盖",
        detail="FTS5 used 时不跑 xingce supplement。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    from src.fts5_recall_index import build_index

    index_path = tmp_path / "memcore" / "runtime" / "fts5" / "p3.sqlite3"
    indexed_memories = p3.get_memories()
    assert build_index(
        indexed_memories,
        str(index_path),
        source_signature=p3._fts5_expected_source_signature(indexed_memories),
    )["ok"] is True

    def explode(_matched, _query, _top_k):
        raise AssertionError("xingce supplement must not run when FTS5 was used")

    monkeypatch.setattr(p3, "_supplement_xingce_candidates", explode)
    result = p3.handle_recall({"query": "FTS5 matched_by supplement", "recall_mode": "substring", "top_k": 1})
    assert result["fts5_applied"] is True
    assert result["matched_memories"][0]["matched_by"] == "fts5_bm25"
