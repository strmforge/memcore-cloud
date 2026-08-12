"""SQLite FTS5 recall index for the P3 substring leg.

The index is a rebuildable projection over zhiyi memories. It is not the
source of truth and it is never allowed to mutate raw/archive records.
"""

from __future__ import annotations

import hashlib
import errno
import json
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional


CONTRACT = "fts5_recall_index.v2026.7.3"


def default_index_path(memcore_root: str | os.PathLike[str]) -> str:
    return str(Path(memcore_root) / "runtime" / "fts5_recall" / "p3_memories.sqlite3")


def configured_index_path(memcore_root: str | os.PathLike[str] | None = None) -> str:
    explicit = str(os.environ.get("MEMCORE_FTS5_RECALL_INDEX_PATH") or "").strip()
    if explicit:
        return explicit
    root = memcore_root or os.environ.get("MEMCORE_ROOT") or Path(__file__).resolve().parents[1]
    return default_index_path(root)


def capability_probe() -> dict[str, Any]:
    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE probe USING fts5(text, tokenize='trigram')")
        con.execute("INSERT INTO probe(text) VALUES (?)", ("Time Library freshness probe",))
        rows = con.execute("SELECT rowid FROM probe WHERE probe MATCH ?", ("freshness",)).fetchall()
        con.close()
        return {
            "ok": bool(rows),
            "sqlite_version": sqlite3.sqlite_version,
            "fts5": True,
            "trigram": True,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "sqlite_version": sqlite3.sqlite_version,
            "fts5": False,
            "trigram": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _source_refs(memory: dict[str, Any]) -> dict[str, Any]:
    refs = memory.get("source_refs") or memory.get("_source_refs") or {}
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except Exception:
            refs = {}
    return refs if isinstance(refs, dict) else {}


def memory_doc_id(memory: dict[str, Any]) -> str:
    exp_id = str(memory.get("exp_id") or "").strip()
    if exp_id:
        return exp_id
    refs = _source_refs(memory)
    payload = {
        "type": memory.get("_type") or memory.get("type") or "",
        "scope": memory.get("scope") or "",
        "source_path": refs.get("source_path") or "",
        "msg_ids": refs.get("msg_ids") or [],
        "summary": memory.get("summary") or "",
        "detail": memory.get("detail") or "",
    }
    digest = hashlib.sha256(json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"doc-{digest[:24]}"


def _memory_projection(memory: dict[str, Any]) -> dict[str, Any]:
    refs = _source_refs(memory)
    return {
        "doc_id": memory_doc_id(memory),
        "exp_id": str(memory.get("exp_id") or ""),
        "memory_type": str(memory.get("_type") or memory.get("type") or ""),
        "scope": str(memory.get("scope") or ""),
        "summary": str(memory.get("summary") or ""),
        "detail": str(memory.get("detail") or ""),
        "source_refs": _jsonable(refs),
    }


def corpus_signature(memories: Iterable[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for memory in sorted((_memory_projection(m) for m in memories if isinstance(m, dict)), key=lambda item: item["doc_id"]):
        h.update(json.dumps(memory, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def source_signature_digest(signature: Any) -> str:
    if not signature:
        return ""
    payload = json.dumps(_jsonable(signature), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute(
        "CREATE TABLE IF NOT EXISTS docs("
        "doc_id TEXT PRIMARY KEY, "
        "exp_id TEXT, "
        "memory_type TEXT, "
        "scope TEXT, "
        "summary TEXT, "
        "detail TEXT, "
        "source_refs TEXT, "
        "content_sha256 TEXT NOT NULL)"
    )
    con.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts "
        "USING fts5(doc_id UNINDEXED, summary, detail, tokenize='trigram')"
    )


def build_index(
    memories: Iterable[dict[str, Any]],
    index_path: str,
    *,
    replace: bool = True,
    source_signature: str = "",
) -> dict[str, Any]:
    capability = capability_probe()
    started = time.time()
    if not capability.get("ok"):
        return {
            "ok": False,
            "contract": CONTRACT,
            "index_path": index_path,
            "error": capability.get("error") or "fts5_trigram_unavailable",
            "capability": capability,
            "write_performed": False,
        }
    docs = [_memory_projection(m) for m in memories if isinstance(m, dict)]
    signature = corpus_signature(memories)
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = _connect(str(path))
    try:
        _ensure_schema(con)
        if replace:
            con.execute("DELETE FROM docs_fts")
            con.execute("DELETE FROM docs")
        for doc in docs:
            content_for_hash = json.dumps(doc, ensure_ascii=False, sort_keys=True)
            content_sha = hashlib.sha256(content_for_hash.encode("utf-8")).hexdigest()
            con.execute(
                "INSERT OR REPLACE INTO docs(doc_id, exp_id, memory_type, scope, summary, detail, source_refs, content_sha256) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc["doc_id"],
                    doc["exp_id"],
                    doc["memory_type"],
                    doc["scope"],
                    doc["summary"],
                    doc["detail"],
                    json.dumps(doc["source_refs"], ensure_ascii=False, sort_keys=True),
                    content_sha,
                ),
            )
            con.execute(
                "INSERT INTO docs_fts(rowid, doc_id, summary, detail) "
                "VALUES ((SELECT rowid FROM docs WHERE doc_id = ?), ?, ?, ?)",
                (doc["doc_id"], doc["doc_id"], doc["summary"], doc["detail"]),
            )
        built_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        meta = {
            "contract": CONTRACT,
            "corpus_signature": signature,
            "doc_count": str(len(docs)),
            "built_at": built_at,
            "sqlite_version": sqlite3.sqlite_version,
        }
        if source_signature:
            meta["source_signature"] = source_signature
        for key, value in meta.items():
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, str(value)))
        con.commit()
        return {
            "ok": True,
            "contract": CONTRACT,
            "index_path": str(path),
            "doc_count": len(docs),
            "corpus_signature": signature,
            "built_at": built_at,
            "elapsed_seconds": round(time.time() - started, 4),
            "write_performed": True,
            "error": None,
            "capability": capability,
        }
    finally:
        con.close()


def _cleanup_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(path) + suffix)
        try:
            sidecar.unlink()
        except OSError:
            pass


def _prepare_standalone_database(path: Path) -> dict[str, str]:
    con = sqlite3.connect(str(path))
    try:
        quick_check = con.execute("PRAGMA quick_check").fetchone()
        if not quick_check or str(quick_check[0]).lower() != "ok":
            raise RuntimeError(f"sqlite_quick_check_failed:{quick_check}")
        meta = _meta(con)
        required_meta = {"contract", "corpus_signature", "doc_count", "built_at"}
        if not required_meta.issubset(meta):
            raise RuntimeError("index_metadata_incomplete")
        checkpoint = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and int(checkpoint[0] or 0) != 0:
            raise RuntimeError(f"wal_checkpoint_busy:{checkpoint}")
        journal_mode = con.execute("PRAGMA journal_mode=DELETE").fetchone()
        if not journal_mode or str(journal_mode[0]).lower() != "delete":
            raise RuntimeError(f"journal_mode_not_standalone:{journal_mode}")
        con.commit()
        return meta
    finally:
        con.close()


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace_with_retry(source: Path, target: Path, *, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            retryable = isinstance(exc, PermissionError) or exc.errno in {errno.EACCES, errno.EBUSY, errno.EPERM}
            if not retryable or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def build_index_atomically(
    memories: Iterable[dict[str, Any]],
    index_path: str,
    *,
    expected_signature: str = "",
    source_signature: str = "",
    expected_source_signature: str = "",
    source_signature_probe: Optional[Callable[[], str]] = None,
) -> dict[str, Any]:
    """Build a complete standalone database, then atomically publish it.

    The live index remains readable while the candidate is built. Any build,
    validation, or publish failure leaves the previous live index untouched.
    """
    started = time.time()
    docs = [memory for memory in memories if isinstance(memory, dict)]
    actual_signature = corpus_signature(docs)
    target = Path(index_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if expected_signature and actual_signature != expected_signature:
        return {
            "ok": False,
            "contract": CONTRACT,
            "index_path": str(target),
            "corpus_signature": actual_signature,
            "expected_signature": expected_signature,
            "error": "source_signature_changed_before_build",
            "write_performed": False,
            "atomic_publish": False,
        }
    if expected_source_signature and source_signature != expected_source_signature:
        return {
            "ok": False,
            "contract": CONTRACT,
            "index_path": str(target),
            "corpus_signature": actual_signature,
            "source_signature": source_signature,
            "expected_source_signature": expected_source_signature,
            "error": "source_snapshot_changed_before_build",
            "write_performed": False,
            "atomic_publish": False,
        }

    descriptor, candidate_name = tempfile.mkstemp(
        prefix=f".{target.name}.build-",
        suffix=".sqlite3",
        dir=str(target.parent),
    )
    os.close(descriptor)
    candidate = Path(candidate_name)
    candidate.unlink()
    published = False
    try:
        report = build_index(docs, str(candidate), source_signature=source_signature)
        if not report.get("ok"):
            report.update({
                "index_path": str(target),
                "write_performed": False,
                "atomic_publish": False,
            })
            return report
        meta = _prepare_standalone_database(candidate)
        if meta.get("corpus_signature") != actual_signature:
            raise RuntimeError("candidate_signature_mismatch")
        if int(meta.get("doc_count") or -1) != len(docs):
            raise RuntimeError("candidate_doc_count_mismatch")
        if source_signature and meta.get("source_signature") != source_signature:
            raise RuntimeError("candidate_source_signature_mismatch")
        _cleanup_sqlite_sidecars(candidate)
        _fsync_file(candidate)

        live_wal = Path(str(target) + "-wal")
        if live_wal.exists() and live_wal.stat().st_size:
            raise RuntimeError("live_index_wal_not_checkpointed")
        if source_signature_probe is not None:
            current_source_signature = str(source_signature_probe() or "")
            if source_signature and current_source_signature != source_signature:
                raise RuntimeError("source_snapshot_changed_during_build")
        _replace_with_retry(candidate, target)
        published = True
        _cleanup_sqlite_sidecars(target)
        _fsync_directory(target.parent)
        report.update({
            "index_path": str(target),
            "elapsed_seconds": round(time.time() - started, 4),
            "write_performed": True,
            "atomic_publish": True,
            "error": None,
        })
        return report
    except Exception as exc:
        return {
            "ok": False,
            "contract": CONTRACT,
            "index_path": str(target),
            "doc_count": len(docs),
            "corpus_signature": actual_signature,
            "expected_signature": expected_signature,
            "source_signature": source_signature,
            "expected_source_signature": expected_source_signature,
            "elapsed_seconds": round(time.time() - started, 4),
            "error": f"{type(exc).__name__}: {exc}",
            "write_performed": published,
            "atomic_publish": published,
        }
    finally:
        if not published:
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
            _cleanup_sqlite_sidecars(candidate)


def _meta(con: sqlite3.Connection) -> dict[str, str]:
    try:
        return {str(k): str(v) for k, v in con.execute("SELECT key, value FROM meta").fetchall()}
    except Exception:
        return {}


def _query_terms(query: str) -> list[str]:
    q = str(query or "").strip()
    if not q:
        return []
    candidates = [q]
    candidates.extend(re.split(r"[\s,，。；;：:、/]+", q))
    terms: list[str] = []
    for term in candidates:
        term = str(term or "").strip()
        if len(term) < 3:
            continue
        if term not in terms:
            terms.append(term)
    return terms


def _match_query(query: str) -> tuple[str, list[str]]:
    terms = _query_terms(query)
    if not terms:
        return "", []
    selected = [terms[0]]
    for term in sorted(terms[1:], key=lambda item: (-len(item), item)):
        if term in selected:
            continue
        if re.fullmatch(r"[A-Za-z0-9_.-]+", term) and len(term) < 5:
            continue
        selected.append(term)
        if len(selected) >= 4:
            break
    quoted = ['"' + term.replace('"', '""') + '"' for term in selected]
    return " OR ".join(quoted), selected


def _query_timeout_seconds() -> float:
    try:
        configured = float(os.environ.get("MEMCORE_FTS5_QUERY_TIMEOUT_SECONDS") or "1.0")
    except (TypeError, ValueError):
        configured = 1.0
    return max(0.05, min(configured, 5.0))


def search_index(
    *,
    query: str,
    index_path: str,
    limit: int = 20,
    expected_signature: str = "",
    expected_source_signature: str = "",
) -> dict[str, Any]:
    started = time.time()
    match_query, terms = _match_query(query)
    status: dict[str, Any] = {
        "contract": CONTRACT,
        "enabled": True,
        "index_path": index_path,
        "query_terms": terms,
        "error": None,
        "applied": False,
        "matched_count": 0,
        "raw_matched_count": 0,
        "post_filter_matched_count": 0,
        "discarded_by_filter_count": 0,
        "stale": False,
    }
    if not match_query:
        status.update({"error": "query_too_short_for_trigram"})
        return {"ok": False, "rows": [], "status": status}
    if not os.path.exists(index_path):
        status.update({"error": "index_missing"})
        return {"ok": False, "rows": [], "status": status}
    con = None
    query_timeout = _query_timeout_seconds()
    try:
        con = sqlite3.connect(index_path)
        deadline = time.monotonic() + query_timeout
        con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        meta = _meta(con)
        required_meta = {"contract", "corpus_signature", "doc_count", "built_at"}
        if not required_meta.issubset(meta):
            status.update({
                "error": "index_not_ready",
                "build_in_progress": True,
                "elapsed_seconds": round(time.time() - started, 4),
            })
            return {"ok": False, "rows": [], "status": status}
        actual_signature = meta.get("corpus_signature", "")
        actual_source_signature = meta.get("source_signature", "")
        corpus_stale = bool(expected_signature and actual_signature and actual_signature != expected_signature)
        source_stale = bool(
            expected_source_signature
            and actual_source_signature != expected_source_signature
        )
        stale = corpus_stale or source_stale
        stale_reason = ""
        if corpus_stale:
            stale_reason = "corpus_signature_mismatch"
        elif source_stale and not actual_source_signature:
            stale_reason = "source_signature_missing"
        elif source_stale:
            stale_reason = "source_signature_mismatch"
        status.update({
            "doc_count": int(meta.get("doc_count") or 0),
            "corpus_signature": actual_signature,
            "expected_signature": expected_signature,
            "source_signature": actual_source_signature,
            "expected_source_signature": expected_source_signature,
            "built_at": meta.get("built_at", ""),
            "stale": stale,
            "stale_reason": stale_reason,
            "query_timeout_seconds": query_timeout,
        })
        if stale:
            status.update({
                "error": "stale_index",
                "fallback_required": True,
                "stale_index_skipped": True,
                "elapsed_seconds": round(time.time() - started, 4),
            })
            return {"ok": False, "rows": [], "status": status}
        rows = [
            {
                "doc_id": str(row[0]),
                "exp_id": str(row[1] or ""),
                "rank": float(row[2]),
                "memory_type": str(row[3] or ""),
            }
            for row in con.execute(
                "SELECT docs.doc_id, docs.exp_id, bm25(docs_fts) AS rank, docs.memory_type "
                "FROM docs_fts JOIN docs ON docs.rowid = docs_fts.rowid "
                "WHERE docs_fts MATCH ? "
                "ORDER BY rank ASC LIMIT ?",
                (match_query, int(limit)),
            ).fetchall()
        ]
        status.update({
            "applied": bool(rows),
            "matched_count": len(rows),
            "raw_matched_count": len(rows),
            "elapsed_seconds": round(time.time() - started, 4),
            "rank_reason": "sqlite_fts5_trigram_bm25",
        })
        return {"ok": True, "rows": rows, "status": status}
    except sqlite3.OperationalError as exc:
        interrupted = "interrupted" in str(exc).lower()
        status.update({
            "error": "query_timeout" if interrupted else f"OperationalError: {exc}",
            "elapsed_seconds": round(time.time() - started, 4),
            "fallback_required": interrupted,
            "query_timeout_seconds": query_timeout,
        })
        return {"ok": False, "rows": [], "status": status}
    except Exception as exc:
        status.update({
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_seconds": round(time.time() - started, 4),
        })
        return {"ok": False, "rows": [], "status": status}
    finally:
        if con is not None:
            con.close()


def _memory_to_legacy_doc(memory: dict[str, Any]) -> dict[str, Any]:
    refs = _source_refs(memory)
    source_path = str(refs.get("source_path") or "")
    raw_offset = refs.get("raw_offset") or refs.get("byte_offsets") or ""
    if isinstance(raw_offset, dict):
        raw_offset = json.dumps(raw_offset, ensure_ascii=False, sort_keys=True)
    return {
        "exp_id": str(memory_doc_id(memory)),
        "summary": str(memory.get("summary") or ""),
        "detail": str(memory.get("detail") or ""),
        "source_ref": str(refs.get("source_ref") or refs.get("source") or ""),
        "source_path": source_path,
        "raw_offset": str(raw_offset or ""),
        "evidence_hash": str(memory.get("evidence_hash") or memory.get("verbatim_sha256") or ""),
    }


def fts5_search(query: str, docs: list[dict[str, Any]], top_k: int = 50):
    """Compatibility wrapper for older p3 runtime branches.

    The new block9 contract should prefer ``search_index`` plus explicit p3
    gating. This wrapper intentionally reports flag_off unless the environment
    explicitly enables FTS5; it does not read feature_flags.
    """
    if str(os.environ.get("MEMCORE_FTS5_RECALL") or "").strip().lower() not in {"1", "true", "yes", "on", "enabled"}:
        return [], {"enabled": False, "fts5_enabled": False, "reason": "flag_off"}
    expected_signature = corpus_signature(docs)
    result = search_index(
        query=query,
        index_path=configured_index_path(),
        limit=top_k,
        expected_signature=expected_signature,
    )
    rows = result.get("rows") or []
    by_id = {}
    for doc in docs:
        try:
            by_id[memory_doc_id(doc)] = doc
        except Exception:
            continue
    scored = []
    for row in rows:
        memory = by_id.get(str(row.get("doc_id") or ""))
        if not memory:
            continue
        score = 1.0 / (1.0 + len(scored))
        scored.append((score, memory))
    return scored, result.get("status") or {}


def fts5_build_or_catchup(docs: list[dict[str, Any]]):
    index_path = configured_index_path()
    enabled = str(os.environ.get("MEMCORE_FTS5_RECALL") or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}
    if not enabled and not os.path.exists(index_path):
        return {"ok": True, "skipped": True, "reason": "flag_off"}
    current = fts5_status()
    expected_signature = corpus_signature(docs)
    if (
        current.get("built")
        and current.get("corpus_signature") == expected_signature
        and int(current.get("doc_count") or 0) == len(docs)
    ):
        return {
            "ok": True,
            "skipped": True,
            "reason": "index_current",
            "index_path": index_path,
            "doc_count": len(docs),
            "corpus_signature": expected_signature,
            "built_at": current.get("built_at", ""),
            "refresh_trigger": "enabled_flag" if enabled else "existing_index_catchup",
            "write_performed": False,
        }
    result = build_index(docs, index_path)
    result["refresh_trigger"] = "enabled_flag" if enabled else "existing_index_catchup"
    return result


def fts5_build_background(docs: list[dict[str, Any]]):
    # Keep compatibility non-blocking semantics conservative for local runtime:
    # build only when explicitly enabled, and do it synchronously in this small
    # wrapper so callers can still observe errors through status/build receipts.
    return fts5_build_or_catchup(docs)


def fts5_status():
    index_path = configured_index_path()
    status = {
        "fts5_enabled": str(os.environ.get("MEMCORE_FTS5_RECALL") or "").strip().lower() in {"1", "true", "yes", "on", "enabled"},
        "index_path": index_path,
        "exists": os.path.exists(index_path),
    }
    if not os.path.exists(index_path):
        status.update({"built": False, "doc_count": 0})
        return status
    try:
        con = sqlite3.connect(index_path)
        meta = _meta(con)
        con.close()
        status.update({
            "built": True,
            "doc_count": int(meta.get("doc_count") or 0),
            "corpus_signature": meta.get("corpus_signature", ""),
            "source_signature": meta.get("source_signature", ""),
            "built_at": meta.get("built_at", ""),
            "contract": meta.get("contract", CONTRACT),
        })
    except Exception as exc:
        status.update({"built": False, "error": f"{type(exc).__name__}: {exc}"})
    return status


def probe_fts5_capability() -> dict[str, Any]:
    cap = capability_probe()
    return {
        "provider": "sqlite3",
        "version": cap.get("sqlite_version", ""),
        "sqlite_version": cap.get("sqlite_version", ""),
        "fts5": bool(cap.get("fts5")),
        "trigram": bool(cap.get("trigram")),
        "fallback_required": not bool(cap.get("ok")),
        "error": cap.get("error"),
        "ok": bool(cap.get("ok")),
    }
