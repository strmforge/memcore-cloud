#!/usr/bin/env python3
"""
Time Library P3: 本机记忆召回服务
从 zhiyi/ 目录读取经验对象，按 scope/type/query 召回，
返回带 source_refs 溯源信息的 matched_memories。

J2-J7 Runtime 集成：
- J2 去重：基于 exp_id 去重，相同 exp_id 保留 lifecycle_version 最高的记录
- J3 冲突：conflict_decision=superseded 的记录不参与召回
- J4 新鲜度：effective_from 时间越近，freshness_score 越高，score 上调
- J5 混合 Ranking：lifecycle 状态参与最终 score 计算
- J6 低置信拒答：confidence 低于阈值时 should_inject=False（由 p4_inject.py 负责）
- J7 按需注入：inject_policy=never 时强制不注入

支持两种召回模式：
- recall_mode=substring: 关键词匹配（experiences 表）
- recall_mode=vector: 模型感知 LanceDB 召回；资产未就绪时回落 substring+FTS5
"""
import os, json, glob, argparse, sys, re, importlib.util, time, threading, subprocess, secrets
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlparse
# ─── RIC Interposition ───────────────────────────────────────
try:
    from runtime_context_package import InterpositionEvent, ContextPackage, log_interposition_event, hash_query
    RIC_AVAILABLE = True
except ImportError:
    RIC_AVAILABLE = False

from typing import Optional, Dict, Any

try:
    import resource
except ImportError:
    resource = None


def _ensure_open_file_limit(minimum=4096):
    status = {
        "supported": resource is not None,
        "requested_soft_limit": int(minimum),
        "soft_limit_before": None,
        "soft_limit_after": None,
        "hard_limit": None,
        "raised": False,
        "error": "",
    }
    if resource is None:
        status["error"] = "resource_module_unavailable"
        return status
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        status.update({"soft_limit_before": soft, "hard_limit": hard})
        target = min(max(int(soft), int(minimum)), int(hard))
        if target > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
        after, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        status["soft_limit_after"] = after
        status["raised"] = after > soft
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status


OPEN_FILE_LIMIT_STATUS = _ensure_open_file_limit()
try:
    from src.zhiyi_archive import attach_archive_card
except Exception:
    from zhiyi_archive import attach_archive_card
try:
    from src.evidence_bound_model import (
        EVIDENCE_BOUND_MODEL_CONTRACT,
        default_model_config,
        plan_evidence_bound_answer_model_use,
        run_evidence_bound_answer,
    )
except Exception:
    try:
        from evidence_bound_model import (
            EVIDENCE_BOUND_MODEL_CONTRACT,
            default_model_config,
            plan_evidence_bound_answer_model_use,
            run_evidence_bound_answer,
        )
    except Exception:
        EVIDENCE_BOUND_MODEL_CONTRACT = "evidence_bound_model.unavailable"
        default_model_config = None
        plan_evidence_bound_answer_model_use = None
        run_evidence_bound_answer = None
try:
    from src.vector_recall_runtime import (
        load_table_identity,
        model_contract,
        pool_hidden_state,
        table_identity_path,
        validate_table_identity,
        vector_dimension_from_schema,
    )
except Exception:
    from vector_recall_runtime import (
        load_table_identity,
        model_contract,
        pool_hidden_state,
        table_identity_path,
        validate_table_identity,
        vector_dimension_from_schema,
    )
try:
    from src.granite_vector_assets import migrate_legacy_bge_upgrade
except Exception:
    from granite_vector_assets import migrate_legacy_bge_upgrade

# ─── Scope Enforcement ───────────────────────────────────────
try:
    from src.scope_enforcement import filter_by_scope as _se_filter_by_scope
    SCOPE_ENFORCEMENT_AVAILABLE = True
except Exception as e:
    print(f"[p3] scope_enforcement not available: {e}")
    SCOPE_ENFORCEMENT_AVAILABLE = False
    def _se_filter_by_scope(results, scope): return results

# ─── FTS5 Recall Index (optional, behind flag) ──────────────
try:
    from src.fts5_recall_index import (
        build_index as _fts5_build_index,
        corpus_signature as _fts5_corpus_signature,
        default_index_path as _fts5_default_index_path,
        memory_doc_id as _fts5_memory_doc_id,
        search_index as _fts5_search_index,
        source_signature_digest as _fts5_source_signature_digest,
        fts5_build_background as _fts5_build_background,
        fts5_build_or_catchup as _fts5_build_or_catchup,
        fts5_status as _fts5_status,
        probe_fts5_capability as _probe_fts5_capability,
    )
    _FTS5_MODULE_AVAILABLE = True
except Exception:
    try:
        from fts5_recall_index import (
            build_index as _fts5_build_index,
            corpus_signature as _fts5_corpus_signature,
            default_index_path as _fts5_default_index_path,
            memory_doc_id as _fts5_memory_doc_id,
            search_index as _fts5_search_index,
            source_signature_digest as _fts5_source_signature_digest,
            fts5_build_background as _fts5_build_background,
            fts5_build_or_catchup as _fts5_build_or_catchup,
            fts5_status as _fts5_status,
            probe_fts5_capability as _probe_fts5_capability,
        )
        _FTS5_MODULE_AVAILABLE = True
    except Exception:
        _FTS5_MODULE_AVAILABLE = False
        _fts5_build_index = None
        _fts5_corpus_signature = None
        _fts5_default_index_path = None
        _fts5_memory_doc_id = None
        _fts5_search_index = None
        _fts5_source_signature_digest = None
        def _fts5_build_background(docs): pass
        def _fts5_build_or_catchup(docs): return {"ok": True, "skipped": True, "reason": "module_unavailable"}
        def _fts5_status(): return {"fts5_enabled": False, "reason": "module_unavailable"}
        def _probe_fts5_capability(): return {"fts5": False, "trigram": False, "fallback_required": True}

# ─── 配置驱动 ─────────────────────────────────────────
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "model_config.json")

def _load_config():
    try:
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}

def _get_recall_config():
    return _load_config().get("recall", {})

def _get_v2_config():
    recall_cfg = _load_config().get("recall", {})
    mode = recall_cfg.get("mode", "local_bge_m3")
    configured = recall_cfg.get(mode)
    if isinstance(configured, dict):
        return configured
    if mode == "vector":
        return recall_cfg.get("local_vector", recall_cfg.get("local_bge_m3", {}))
    return {}


def _recall_request_scope(
    *,
    canonical_window_id_filter: str = "",
    source_system_filter: str = "",
    computer_name_filter: str = "",
    scope_filter: str = "",
) -> dict[str, str]:
    if canonical_window_id_filter:
        return {
            "canonical_window_id": canonical_window_id_filter,
            "source_system": source_system_filter,
            "computer_id": computer_name_filter or _current_node_id(),
        }
    if scope_filter:
        sf = scope_filter.replace("window/", "")
        return {
            "canonical_window_id": sf,
            "source_system": source_system_filter,
            "computer_id": _current_node_id(),
        }
    return {
        "canonical_window_id": "",
        "source_system": source_system_filter,
        "computer_id": _current_node_id(),
    }

# ─── LanceDB v2 向量召回（可选）──────────────────────
_lancedb_v2_cache = {
    "tok": None,
    "model": None,
    "device": "cpu",
    "tbl": None,
    "max_seq": 256,
    "row_count": None,
    "status": {},
    "empty_search_count": 0,
    "last_search": {},
    "startup_warmup": {},
    "contract": None,
    "table_identity": None,
}
_vector_search_lock = threading.Lock()

def _dep_available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False

def _vector_dependency_status():
    checks = {
        "lancedb": "lancedb",
        "transformers": "transformers",
        "torch": "torch",
        "numpy": "numpy",
        "sentencepiece": "sentencepiece",
        "protobuf": "google.protobuf",
    }
    return {
        name: _dep_available(import_name)
        for name, import_name in checks.items()
    }

def _v2_table_name():
    return _get_v2_config().get("table", "experiences_v2")


def _v2_model_contract():
    return model_contract(_get_v2_config())

def _v2_lancedb_path():
    try:
        from config_loader import experience_lancedb as _lancedb_path
    except Exception:
        from src.config_loader import experience_lancedb as _lancedb_path
    return _lancedb_path()

def _path_is_under(parent, child):
    try:
        parent_abs = os.path.abspath(os.path.expanduser(str(parent or "")))
        child_abs = os.path.abspath(os.path.expanduser(str(child or "")))
        return bool(parent_abs and child_abs and os.path.commonpath([parent_abs, child_abs]) == parent_abs)
    except Exception:
        return False

def _select_torch_device(torch_module, v2_cfg):
    requested = str(
        os.environ.get("MEMCORE_VECTOR_DEVICE")
        or v2_cfg.get("device")
        or "auto"
    ).strip().lower()
    def cuda_available():
        try:
            return bool(getattr(torch_module, "cuda", None) and torch_module.cuda.is_available())
        except Exception:
            return False

    def mps_available():
        try:
            return bool(getattr(torch_module.backends, "mps", None) and torch_module.backends.mps.is_available())
        except Exception:
            return False

    if requested in {"", "auto", "gpu"}:
        if cuda_available():
            return "cuda"
        if mps_available():
            return "mps"
        return "cpu"
    if requested == "cuda":
        return "cuda" if cuda_available() else "cpu"
    if requested == "mps":
        return "mps" if mps_available() else "cpu"
    return "cpu"

def _v2_static_status():
    v2_cfg = _get_v2_config()
    mode = _load_config().get("recall", {}).get("mode", "off")
    table_name = v2_cfg.get("table", "experiences_v2")
    model_path = os.path.expanduser(os.path.expandvars(v2_cfg.get("model_path", "")))
    model_path_exists = os.path.isdir(model_path) if model_path else False
    memcore_root = os.path.abspath(os.environ.get("MEMCORE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    hf_home = os.path.abspath(os.path.expanduser(os.environ.get("HF_HOME") or "")) if os.environ.get("HF_HOME") else ""
    hub_cache = os.path.abspath(os.path.expanduser(os.environ.get("HUGGINGFACE_HUB_CACHE") or "")) if os.environ.get("HUGGINGFACE_HUB_CACHE") else ""
    hf_cache_under_memcore_root = _path_is_under(memcore_root, hf_home)
    hf_cache_is_mounted_volume = bool(hf_home and Path(hf_home).parts[:2] == (os.sep, "Volumes"))
    lancedb_path = _v2_lancedb_path()
    table_path = os.path.join(lancedb_path, f"{table_name}.lance")
    identity_path = table_identity_path(lancedb_path, table_name)
    identity = load_table_identity(lancedb_path, table_name)
    dependencies = _vector_dependency_status()
    expected = mode not in ("off", "substring")
    issues = []
    contract = None
    if expected:
        try:
            contract = _v2_model_contract()
        except Exception as exc:
            issues.append(f"invalid_vector_model_contract:{type(exc).__name__}")
        missing = [name for name, ok in dependencies.items() if not ok]
        if missing:
            issues.append("missing_dependencies:" + ",".join(missing))
        if not os.path.isdir(table_path):
            issues.append("missing_lancedb_table")
        if not model_path:
            issues.append("missing_model_path")
        elif not model_path_exists:
            issues.append("missing_model_path_dir")
        if hf_home and not hf_cache_under_memcore_root:
            issues.append("hf_cache_outside_memcore_root")
        if hf_cache_is_mounted_volume:
            issues.append("hf_cache_mounted_volume")
        if contract:
            issues.extend(validate_table_identity(contract, identity))
    status = {
        "ok": (not expected) or not issues,
        "status": "off" if not expected else ("ready_for_load" if not issues else "degraded"),
        "mode": mode,
        "expected": expected,
        "issues": issues,
        "dependencies": dependencies,
        "model_name": v2_cfg.get("model_name") or v2_cfg.get("embedding_model", ""),
        "model_id": (contract or {}).get("model_id", ""),
        "embedding_dim": (contract or {}).get("embedding_dim"),
        "pooling": (contract or {}).get("pooling", ""),
        "normalize": (contract or {}).get("normalize"),
        "model_path": model_path,
        "model_path_exists": model_path_exists,
        "model_local_only": not bool(v2_cfg.get("allow_download", False) or os.environ.get("MEMCORE_VECTOR_ALLOW_MODEL_DOWNLOAD") == "1"),
        "device": _lancedb_v2_cache.get("device") or "cpu",
        "device_requested": str(os.environ.get("MEMCORE_VECTOR_DEVICE") or v2_cfg.get("device") or "auto"),
        "hf_home": hf_home,
        "huggingface_hub_cache": hub_cache,
        "hf_cache_under_memcore_root": hf_cache_under_memcore_root,
        "hf_cache_is_mounted_volume": hf_cache_is_mounted_volume,
        "lancedb_path": lancedb_path,
        "table": table_name,
        "table_path": table_path,
        "table_present": os.path.isdir(table_path),
        "table_identity_path": str(identity_path),
        "table_identity_present": bool(identity),
        "table_identity": identity or {},
        "row_count": _lancedb_v2_cache.get("row_count"),
        "model_loaded": _lancedb_v2_cache.get("model") is not None,
        "table_loaded": _lancedb_v2_cache.get("tbl") is not None,
        "empty_search_count": int(_lancedb_v2_cache.get("empty_search_count") or 0),
        "last_search": _lancedb_v2_cache.get("last_search") or {},
    }
    return status

def _set_v2_status(status, *, issue=None, ok=None):
    status = dict(status or _v2_static_status())
    issues = list(status.get("issues") or [])
    if issue and issue not in issues:
        issues.append(issue)
    status["issues"] = issues
    if ok is not None:
        status["ok"] = bool(ok)
    elif status.get("expected", True):
        status["ok"] = not issues and bool(status.get("model_loaded")) and bool(status.get("table_loaded"))
    if status.get("expected", True):
        status["status"] = "ok" if status.get("ok") else "degraded"
    _lancedb_v2_cache["status"] = status
    return status

def vector_runtime_status(load_model=False):
    """Return a loud, machine-readable vector recall status."""
    if load_model:
        _get_v2_engine()
    status = dict(_lancedb_v2_cache.get("status") or _v2_static_status())
    status["row_count"] = _lancedb_v2_cache.get("row_count")
    status["model_loaded"] = _lancedb_v2_cache.get("model") is not None
    status["table_loaded"] = _lancedb_v2_cache.get("tbl") is not None
    status["empty_search_count"] = int(_lancedb_v2_cache.get("empty_search_count") or 0)
    status["last_search"] = _lancedb_v2_cache.get("last_search") or {}
    status["startup_warmup"] = _lancedb_v2_cache.get("startup_warmup") or {}
    status["open_file_limit"] = dict(OPEN_FILE_LIMIT_STATUS)
    if load_model and status.get("expected") and (not status.get("model_loaded") or not status.get("table_loaded")):
        issues = list(status.get("issues") or [])
        if not status.get("model_loaded") and "model_not_loaded" not in issues:
            issues.append("model_not_loaded")
        if not status.get("table_loaded") and "table_not_loaded" not in issues:
            issues.append("table_not_loaded")
        status["issues"] = issues
        status["ok"] = False
        status["status"] = "degraded"
    return status

def _count_lancedb_rows(tbl):
    try:
        return int(tbl.count_rows())
    except Exception:
        pass
    try:
        return int(len(tbl.to_list()))
    except Exception:
        return None

def _get_v2_engine():
    """延迟加载配置指定的嵌入模型和 LanceDB 表。"""
    if _lancedb_v2_cache["model"] is None:
        v2_cfg = _get_v2_config()
        mode = _load_config().get("recall", {}).get("mode", "off")
        if mode in {"off", "substring"}:
            _set_v2_status(_v2_static_status(), ok=True)
            return _lancedb_v2_cache
        static_status = _v2_static_status()
        if static_status.get("issues"):
            _set_v2_status(static_status, ok=False)
            return _lancedb_v2_cache
        try:
            from transformers import AutoModel, AutoTokenizer
            import lancedb
            import torch
            import os as _os
            contract = _v2_model_contract()
            model_path = contract["model_path"]
            local_only = not bool(v2_cfg.get("allow_download", False) or os.environ.get("MEMCORE_VECTOR_ALLOW_MODEL_DOWNLOAD") == "1")
            _lancedb_v2_cache["tok"] = AutoTokenizer.from_pretrained(model_path, local_files_only=local_only)
            _lancedb_v2_cache["model"] = AutoModel.from_pretrained(model_path, torch_dtype=torch.float32, local_files_only=local_only)
            _lancedb_v2_cache["device"] = _select_torch_device(torch, v2_cfg)
            if _lancedb_v2_cache["device"] != "cpu":
                _lancedb_v2_cache["model"].to(_lancedb_v2_cache["device"])
            _lancedb_v2_cache["model"].eval()
            db = lancedb.connect(_v2_lancedb_path())
            table_name = _v2_table_name()
            _lancedb_v2_cache["tbl"] = db.open_table(table_name)
            schema_dimension = vector_dimension_from_schema(_lancedb_v2_cache["tbl"].schema)
            if schema_dimension != contract["embedding_dim"]:
                raise ValueError(
                    f"vector table dimension {schema_dimension} does not match configured "
                    f"dimension {contract['embedding_dim']}"
                )
            _lancedb_v2_cache["max_seq"] = contract["max_seq_length"]
            _lancedb_v2_cache["row_count"] = _count_lancedb_rows(_lancedb_v2_cache["tbl"])
            identity = load_table_identity(_v2_lancedb_path(), table_name)
            identity_issues = validate_table_identity(contract, identity)
            if identity_issues:
                raise ValueError("vector table identity mismatch: " + ",".join(identity_issues))
            identity_row_count = int((identity or {}).get("row_count") or 0)
            if identity_row_count != _lancedb_v2_cache["row_count"]:
                raise ValueError(
                    f"vector table row count {_lancedb_v2_cache['row_count']} does not match "
                    f"identity row count {identity_row_count}"
                )
            _lancedb_v2_cache["contract"] = contract
            _lancedb_v2_cache["table_identity"] = identity
            model_name = contract["model_id"]
            print(f"[p3] v2 engine loaded: {model_name}")
            status = _v2_static_status()
            status["row_count"] = _lancedb_v2_cache["row_count"]
            status["model_loaded"] = True
            status["table_loaded"] = True
            if _lancedb_v2_cache["row_count"] == 0:
                _set_v2_status(status, issue="empty_lancedb_table", ok=False)
            else:
                _set_v2_status(status, ok=True)
        except Exception as e:
            print(f"[p3] v2 engine load failed: {e}")
            status = _v2_static_status()
            status["engine_load_error"] = str(e)[:1000]
            status["engine_load_error_type"] = type(e).__name__
            _set_v2_status(status, issue=f"engine_load_failed:{type(e).__name__}", ok=False)
    return _lancedb_v2_cache

def _encode_vector(texts):
    """Encode text with the configured model-specific pooling contract."""
    import numpy
    engine = _get_v2_engine()
    tok = engine["tok"]
    model = engine["model"]
    contract = engine.get("contract") or _v2_model_contract()
    import torch
    max_seq = engine.get("max_seq", 256)
    timings = {}
    token_started = time.perf_counter()
    inp = tok(texts, padding=True, truncation=True, max_length=max_seq, return_tensors="pt")
    timings["tokenize_seconds"] = round(time.perf_counter() - token_started, 4)
    device = engine.get("device") or "cpu"
    if device != "cpu":
        move_started = time.perf_counter()
        inp = {key: value.to(device) for key, value in inp.items()}
        timings["device_transfer_seconds"] = round(time.perf_counter() - move_started, 4)
    forward_started = time.perf_counter()
    with torch.no_grad():
        out = model(**inp)
    timings["forward_seconds"] = round(time.perf_counter() - forward_started, 4)
    pool_started = time.perf_counter()
    hidden = pool_hidden_state(out.last_hidden_state, inp["attention_mask"], contract["pooling"])
    if device != "cpu":
        hidden = hidden.cpu()
    emb = hidden.numpy()
    if contract["normalize"]:
        norms = numpy.linalg.norm(emb, axis=1, keepdims=True)
        emb = emb / numpy.maximum(norms, 1e-12)
    if emb.shape[1] != contract["embedding_dim"]:
        raise ValueError(
            f"encoded dimension {emb.shape[1]} does not match configured "
            f"dimension {contract['embedding_dim']}"
        )
    timings["pool_seconds"] = round(time.perf_counter() - pool_started, 4)
    _lancedb_v2_cache["last_encode"] = timings
    return emb.tolist()

def vector_search_v2(query, top_k=5, scope_filter=None, type_filter=None):
    """LanceDB v2 向量相似度召回（配置驱动）"""
    started = time.perf_counter()
    v2_cfg = _get_v2_config()
    if _load_config().get("recall", {}).get("mode") == "off":
        return []
    try:
        lock_started = time.perf_counter()
        with _vector_search_lock:
            engine = _get_v2_engine()
            lock_wait_seconds = round(time.perf_counter() - lock_started, 4)
            if engine["model"] is None:
                _lancedb_v2_cache["last_search"] = {
                    "ok": False,
                    "error": "engine_not_loaded",
                    "query_present": bool(query),
                    "lock_wait_seconds": lock_wait_seconds,
                    "lock_scope": "model_encode_only",
                    "total_seconds": round(time.perf_counter() - started, 4),
                }
                return []
            tbl = engine["tbl"]
            encode_started = time.perf_counter()
            q_emb = _encode_vector([query])[0]
            encode_seconds = round(time.perf_counter() - encode_started, 4)
            encode_breakdown = dict(_lancedb_v2_cache.get("last_encode") or {})
            device = _lancedb_v2_cache.get("device") or "cpu"
        search_started = time.perf_counter()
        results = tbl.search(q_emb, vector_column_name="vector").limit(top_k * 2).to_list()
        format_started = time.perf_counter()
    except Exception as e:
        print(f"[p3] v2 search error: {e}")
        _lancedb_v2_cache["last_search"] = {"ok": False, "error": f"{type(e).__name__}: {e}", "query_present": bool(query)}
        _set_v2_status(vector_runtime_status(load_model=False), issue=f"search_failed:{type(e).__name__}", ok=False)
        return []
    matched = []
    for r in results:
        exp_id = r.get("exp_id", "")
        # scope/type filter
        if scope_filter:
            sf = scope_filter.replace("window/", "")
            if sf not in (r.get("scope", "") or ""):
                continue
        if type_filter:
            if r.get("type", "") not in type_filter:
                continue
        # Get source_refs directly from LanceDB record (exp_map may not have all LanceDB exp_ids)
        sr_raw = r.get("source_refs", "{}")
        try:
            sr = json.loads(sr_raw) if isinstance(sr_raw, str) else (sr_raw or {})
        except:
            sr = {}
        sr = _normalize_source_refs_node(sr)
        dist = r.get("_distance", 0)
        confidence = max(1.0 - dist / 2.0, 0.0)
        # J1 + J3A-G3: 对原始 LanceDB 结果 r 做噪音检测
        # r 有 summary/detail，exp_map 只有 exp_id/scope/memory_id
        if _is_noise_memory(r):
            continue
        item = attach_archive_card({
            "type": r.get("type", ""),
            "exp_id": exp_id,
            "scope": r.get("scope", ""),
            "summary": r.get("summary", ""),
            "reason": f"向量相似度: dist={dist:.3f}",
            "confidence": round(confidence, 2),
            "source_refs": sr,
            "detail": r.get("detail", ""),
            "injectable_context": (r.get("summary", "") + " " + r.get("detail", "")).strip(),
        })
        matched.append(item)
        if len(matched) >= top_k:
            break
    if matched:
        _lancedb_v2_cache["empty_search_count"] = 0
    else:
        _lancedb_v2_cache["empty_search_count"] = int(_lancedb_v2_cache.get("empty_search_count") or 0) + 1
    _lancedb_v2_cache["last_search"] = {
        "ok": True,
        "query_present": bool(query),
        "top_k": top_k,
        "limit": top_k * 2,
        "raw_returned": len(results),
        "matched_after_filters": len(matched),
        "lock_wait_seconds": lock_wait_seconds,
        "lock_scope": "model_encode_only",
        "encode_seconds": encode_seconds,
        "encode_breakdown": encode_breakdown,
        "device": device,
        "search_seconds": round(format_started - search_started, 4),
        "format_seconds": round(time.perf_counter() - format_started, 4),
        "total_seconds": round(time.perf_counter() - started, 4),
    }
    return matched

def _warmup_vector_engine():
    started = time.perf_counter()
    warmup = {
        "enabled": True,
        "ok": False,
        "query": "Time Library",
    }
    try:
        vector_search_v2("Time Library", top_k=1)
        warmup.update({
            "ok": True,
            "seconds": round(time.perf_counter() - started, 4),
            "last_search": _lancedb_v2_cache.get("last_search") or {},
        })
    except Exception as exc:
        warmup.update({
            "ok": False,
            "seconds": round(time.perf_counter() - started, 4),
            "error": f"{type(exc).__name__}: {exc}",
        })
        _set_v2_status(vector_runtime_status(load_model=False), issue=f"startup_warmup_failed:{type(exc).__name__}", ok=False)
    _lancedb_v2_cache["startup_warmup"] = warmup
    return warmup

def _truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "auto"}


def _feature_flag_enabled(_name):
    """Legacy compatibility hook.

    FTS5 recall must not be enabled through feature_flags on the recall hot
    path; tests monkeypatch this helper to catch regressions.
    """
    return False


def _fts5_recall_enabled(body):
    if _truthy(body.get("fts5_recall")) or _truthy(body.get("enable_fts5_recall")):
        return True
    return _truthy(os.environ.get("MEMCORE_FTS5_RECALL"))

def _structure_analysis_config(body):
    recall_cfg = _load_config().get("recall", {})
    configured = recall_cfg.get("structure_analysis", {}) if isinstance(recall_cfg, dict) else {}
    if not isinstance(configured, dict):
        configured = {}
    requested = body.get("structure_analysis", None)
    request_cfg = requested if isinstance(requested, dict) else {}
    explicit_enabled = body.get("enable_structure_analysis", None)
    if isinstance(requested, bool):
        enabled = requested
    elif explicit_enabled is not None:
        enabled = _truthy(explicit_enabled)
    else:
        enabled = _truthy(request_cfg.get("enabled", configured.get("enabled", False)))
    merged = dict(configured)
    merged.update(request_cfg)
    merged["enabled"] = enabled
    return merged

def _memory_to_structure_evidence(memory, index):
    refs = memory.get("source_refs") or memory.get("_source_refs") or {}
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except Exception:
            refs = {}
    evidence_ref = (
        str(memory.get("catalog_id") or "")
        or str(memory.get("library_id") or "")
        or str(memory.get("exp_id") or "")
        or f"memory-{index + 1}"
    )
    source_id = str(memory.get("exp_id") or evidence_ref or f"memory-{index + 1}")
    text = "\n".join(
        part
        for part in (
            str(memory.get("summary") or "").strip(),
            str(memory.get("detail") or memory.get("injectable_context") or "").strip(),
        )
        if part
    )
    return {
        "source_id": source_id,
        "evidence_ref": evidence_ref,
        "role": "memory",
        "authority": "source_backed_memory_candidate",
        "text": text,
        "source_refs": refs if isinstance(refs, dict) else {},
        "score": memory.get("confidence") or memory.get("score"),
    }

def _apply_structure_support_order(matched, supporting_refs):
    if not supporting_refs:
        return matched, False
    supported = {str(item) for item in supporting_refs}

    def key(memory):
        ids = {
            str(memory.get("catalog_id") or ""),
            str(memory.get("library_id") or ""),
            str(memory.get("exp_id") or ""),
        }
        return 0 if ids & supported else 1

    reordered = sorted(enumerate(matched), key=lambda pair: (key(pair[1]), pair[0]))
    ordered = [memory for _, memory in reordered]
    return ordered, ordered != matched

def _run_structure_analysis(query, matched, body, vector_status=None):
    cfg = _structure_analysis_config(body)
    base = {
        "enabled": bool(cfg.get("enabled")),
        "executed": False,
        "model_call_performed": False,
        "request_sent": False,
        "response_received": False,
        "reason": "",
        "contract": EVIDENCE_BOUND_MODEL_CONTRACT,
        "model": "",
        "provider": "",
        "api_key_env": "",
        "api_key_present": False,
        "runtime_binding_ready": False,
        "evidence_count": 0,
        "supporting_refs": [],
        "verdict": "",
        "confidence": 0.0,
        "answer_excerpt": "",
        "reordered": False,
    }
    if not cfg.get("enabled"):
        base["reason"] = "disabled"
        return base, matched
    if not matched:
        base["reason"] = "no_candidates"
        return base, matched
    if default_model_config is None or plan_evidence_bound_answer_model_use is None or run_evidence_bound_answer is None:
        base["reason"] = "evidence_bound_model_unavailable"
        return base, matched

    max_items = int(cfg.get("max_evidence_items") or body.get("structure_analysis_top_k") or 5)
    evidence = [
        _memory_to_structure_evidence(memory, index)
        for index, memory in enumerate(matched[:max(1, max_items)])
        if str(memory.get("summary") or memory.get("detail") or memory.get("injectable_context") or "").strip()
    ]
    base["evidence_count"] = len(evidence)
    if not evidence:
        base["reason"] = "no_textual_candidates"
        return base, matched

    provider = str(cfg.get("provider") or body.get("structure_analysis_provider") or "").strip()
    model = str(cfg.get("model") or body.get("structure_analysis_model") or "").strip()
    base_url = str(cfg.get("base_url") or body.get("structure_analysis_base_url") or "").strip()
    api_key_env = str(cfg.get("api_key_env") or body.get("structure_analysis_api_key_env") or "").strip()
    model_cfg = default_model_config(provider=provider, model=model, base_url=base_url, api_key_env=api_key_env)
    base.update({
        "model": model_cfg.model,
        "provider": model_cfg.provider,
        "api_key_env": model_cfg.api_key_env,
        "api_key_present": bool(model_cfg.api_key_present),
        "runtime_binding_ready": bool(model_cfg.api_key_present and model_cfg.base_url and model_cfg.model),
    })
    if not base["runtime_binding_ready"]:
        base["reason"] = "model_config_missing"
        return base, matched

    draft = ""
    if vector_status and isinstance(vector_status, dict):
        draft = "vector_status=" + ",".join(str(item) for item in (vector_status.get("issues") or []))
    gating = plan_evidence_bound_answer_model_use(
        str(query or ""),
        evidence,
        draft_answer=draft,
        policy=str(cfg.get("call_policy") or "auto"),
    )
    base["gating"] = gating
    if not gating.get("should_call_model"):
        base["reason"] = str(gating.get("reason") or "model_call_gated")
        return base, matched

    result = run_evidence_bound_answer(
        str(query or ""),
        evidence,
        task_kind="recall_structure_analysis",
        draft_answer=draft,
        model_config=model_cfg,
        execute=True,
        max_evidence_items=max(1, max_items),
    )
    supporting_refs = [str(item) for item in (result.get("supporting_refs") or [])]
    reordered, did_reorder = _apply_structure_support_order(matched, supporting_refs)
    base.update({
        "executed": True,
        "model_call_performed": bool(result.get("model_call_performed")),
        "request_sent": bool(result.get("model_call_performed")),
        "response_received": bool(result.get("answer") or result.get("verdict")),
        "reason": str(result.get("validation_error") or result.get("unknown_reason") or result.get("verdict") or "ok"),
        "supporting_refs": supporting_refs,
        "verdict": str(result.get("verdict") or ""),
        "confidence": result.get("confidence", 0.0),
        "answer_excerpt": str(result.get("answer") or "")[:800],
        "reordered": did_reorder,
        "transparency_recorded": result.get("transparency_recorded"),
        "transparency_error": result.get("transparency_error", ""),
        "transparency_warning": result.get("transparency_warning", ""),
    })
    return base, reordered

def _finalize_recall_result(result, query, body, vector_status=None):
    if result.get("structure_analysis"):
        return result
    analysis, matched = _run_structure_analysis(query, result.get("matched_memories", []) or [], body, vector_status)
    if analysis.get("enabled"):
        result["structure_analysis"] = analysis
        if analysis.get("reordered"):
            result["matched_memories"] = matched
    return result

# ─── Lifecycle Overlay Cache (J2-J7 Runtime) ───────────────────────
# lifecycle overlay: exp_id -> lifecycle fields (conflict_decision, status, inject_policy, etc.)
_LIFECYCLE_CACHE: Optional[Dict[str, Dict[str, Any]]] = None
_LIFECYCLE_CACHE_TIME = {"ts": 0}
_LIFECYCLE_CACHE_SIGNATURE = None
_LIFECYCLE_TTL = 60  # seconds


def _file_signature(paths):
    signature = []
    for path in paths:
        try:
            st = os.stat(path)
            signature.append((path, st.st_mtime_ns, st.st_size))
        except FileNotFoundError:
            signature.append((path, None, None))
        except Exception:
            signature.append((path, "error", "error"))
    return tuple(signature)


def _zhiyi_path_for_runtime():
    zhiyi_root_override = os.environ.get("MEMCORE_ZHIYI_ROOT_OVERRIDE")
    return zhiyi_root_override if zhiyi_root_override else ZHIYI_ROOT


def _lifecycle_source_signature():
    zhiyi_path = _zhiyi_path_for_runtime()
    paths = [
        os.path.join(zhiyi_path, ftype, f"{ftype}.lifecycle.jsonl")
        for ftype in ["case_memory", "error_memory"]
    ]
    return _file_signature(paths)


def _load_lifecycle_overlay():
    """加载 lifecycle overlay，构建 exp_id -> lifecycle_fields 字典。"""
    # Allow test fixture override via env var (MEMCORE_ZHIYI_ROOT_OVERRIDE)
    zhiyi_path = _zhiyi_path_for_runtime()
    overlay = {}
    for ftype in ["case_memory", "error_memory"]:
        lifecycle_path = os.path.join(zhiyi_path, ftype, f"{ftype}.lifecycle.jsonl")
        if not os.path.exists(lifecycle_path):
            continue
        try:
            with open(lifecycle_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        exp_id = rec.get("exp_id", "")
                        if not exp_id:
                            continue
                        # J2: 相同 exp_id 保留 lifecycle_version 最高的记录
                        # J1 Fix: 同版本优先 active > superseded > historical_only
                        existing = overlay.get(exp_id)
                        if existing is None:
                            overlay[exp_id] = rec
                        else:
                            existing_ver = existing.get("lifecycle_version", 0)
                            new_ver = rec.get("lifecycle_version", 0)
                            if new_ver > existing_ver:
                                overlay[exp_id] = rec
                            elif new_ver == existing_ver:
                                cd_pref = {"active": 0, "superseded": 1, "historical_only": 2, "": 3}
                                existing_cd = cd_pref.get(existing.get("conflict_decision", ""), 99)
                                new_cd = cd_pref.get(rec.get("conflict_decision", ""), 99)
                                if new_cd < existing_cd:
                                    overlay[exp_id] = rec
                    except Exception:
                        pass
        except Exception as e:
            print(f"[p3] lifecycle overlay load error for {ftype}: {e}")
    return overlay


def _get_lifecycle_overlay():
    """带 TTL 和文件签名的 lifecycle overlay 缓存。"""
    global _LIFECYCLE_CACHE, _LIFECYCLE_CACHE_TIME, _LIFECYCLE_CACHE_SIGNATURE
    now = datetime.now(timezone.utc).timestamp()
    signature = _lifecycle_source_signature()
    if (
        _LIFECYCLE_CACHE is None
        or signature != _LIFECYCLE_CACHE_SIGNATURE
        or (now - _LIFECYCLE_CACHE_TIME["ts"]) > _LIFECYCLE_TTL
    ):
        _LIFECYCLE_CACHE = _load_lifecycle_overlay()
        _LIFECYCLE_CACHE_TIME["ts"] = now
        _LIFECYCLE_CACHE_SIGNATURE = signature
    return _LIFECYCLE_CACHE


def _apply_lifecycle_overlay(memories: list) -> list:
    """
    J2-J5 Runtime: 将 lifecycle overlay 应用于 memories 列表。

    J2 去重：输入已被 load_memories 预处理，相同 exp_id 仅保留一条（lifecycle_version 最高）
    J3 冲突：conflict_decision=superseded 的记录跳过
    J4 新鲜度：基于 effective_from 计算 freshness_score，合并到 confidence
    J5 混合 Ranking：lifecycle 状态作为 ranking 因子参与 score 计算

    Returns: 过滤并增强后的 memories 列表
    """
    overlay = _get_lifecycle_overlay()
    result = []
    now_ts = datetime.now(timezone.utc).timestamp()

    for m in memories:
        exp_id = m.get("exp_id", "")
        lo = overlay.get(exp_id, {})

        # ── J3 冲突：superseded 记录不参与召回 ──
        conflict_decision = lo.get("conflict_decision", "")
        if conflict_decision == "superseded":
            continue  # 被取代的记录直接跳过

        # ── J3 冲突：historical_only → 降权但不剔除 ──
        is_historical = (conflict_decision == "historical_only" or
                         lo.get("status") in ("historical", "superseded"))

        # ── J4 新鲜度：effective_from 越近 freshness_score 越高 ──
        freshness_score = 1.0  # 默认不衰减
        effective_from_str = lo.get("effective_from", "")
        if effective_from_str:
            try:
                effective_ts = datetime.strptime(effective_from_str, "%Y-%m-%d %H:%M:%S").timestamp()
                age_days = (now_ts - effective_ts) / 86400.0
                # 半衰期 30 天：超过 30 天分数减半
                freshness_score = max(0.3, 1.0 / (1.0 + age_days / 30.0))
            except Exception:
                pass

        # ── J5 混合 Ranking：lifecycle 因子参与 score 计算 ──
        base_score = m.get("score", m.get("confidence", 0.7))
        lifecycle_boost = 0.0
        status = lo.get("status", "")
        if status == "active":
            lifecycle_boost = 0.15
        elif status == "historical":
            lifecycle_boost = -0.1
        elif status in ("superseded", "deprecated"):
            lifecycle_boost = -0.25

        # 合并 confidence：base_score * freshness * lifecycle_boost
        adjusted_score = base_score * freshness_score + lifecycle_boost
        adjusted_score = max(0.0, min(1.0, adjusted_score))

        # 将 lifecycle 字段注入到 memory 对象（不修改原始数据）
        enhanced = dict(m)
        has_real_lifecycle = bool(lo)
        enhanced["_lifecycle"] = {
            "exp_id": exp_id,
            # 无 overlay 时 status=""（不应用 boost）；有 overlay 时用真实值
            "status": lo.get("status", "") if has_real_lifecycle else "",
            "inject_policy": lo.get("inject_policy", "auto") if has_real_lifecycle else "auto",
            "conflict_decision": conflict_decision,
            "freshness_score": round(freshness_score, 3),
            "lifecycle_version": lo.get("lifecycle_version", 0) if has_real_lifecycle else 0,
            "is_historical": is_historical,
        }
        enhanced["_adjusted_score"] = round(adjusted_score, 3)
        result.append(enhanced)

    return result


try:
    from src.config_loader import zhiyi_root, memory_root, raw_memory_subpath, get_memcore_root, node_id
except Exception:
    from config_loader import zhiyi_root, memory_root, raw_memory_subpath, get_memcore_root, node_id
ZHIYI_ROOT = zhiyi_root()
MEMCORE_ROOT = os.path.join(memory_root(), raw_memory_subpath())
MEMCORE_PROJECT_ROOT = get_memcore_root()


def _current_node_id():
    value = str(node_id() or "").strip()
    return value or "local"


def _source_path_belongs_to_current_node(source_path, current_node=None):
    current_node = current_node or _current_node_id()
    normalized = str(source_path or "").replace("\\", "/")
    return bool(
        current_node
        and (
            f"/memory/openclaw/{current_node}/" in normalized
            or f"/memory/{current_node}/openclaw/openclaw_session_jsonl/" in normalized
        )
    )


def _normalize_source_refs_node(source_refs):
    if not isinstance(source_refs, dict):
        return source_refs
    current_node = _current_node_id()
    if _source_path_belongs_to_current_node(source_refs.get("source_path"), current_node):
        source_refs = dict(source_refs)
        source_refs["computer_name"] = current_node
    return source_refs


def _normalize_memory_record_node(record):
    current_node = _current_node_id()
    source_refs = record.get("_source_refs")
    if isinstance(source_refs, dict) and _source_path_belongs_to_current_node(source_refs.get("source_path"), current_node):
        record["_source_refs"] = _normalize_source_refs_node(source_refs)
        if record.get("computer_id") in ("", "local", None):
            record["computer_id"] = current_node
    return record


def _xingce_project_root():
    return (
        os.environ.get("MEMCORE_XINGCE_ROOT_OVERRIDE")
        or os.environ.get("MEMCORE_ROOT")
        or MEMCORE_PROJECT_ROOT
    )


def _project_status_root():
    return (
        os.environ.get("MEMCORE_PROJECT_STATUS_ROOT_OVERRIDE")
        or os.environ.get("MEMCORE_ROOT")
        or MEMCORE_PROJECT_ROOT
    )


def _read_json_object(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _xingce_window_from_source_path(source_path):
    parts = str(source_path or "").split(os.sep)
    for index, part in enumerate(parts):
        if part == "local" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _latest_xingce_candidate_action(root, candidate_id):
    actions_dir = os.path.join(root, "output", "xingce_work_experience", "actions")
    if not os.path.isdir(actions_dir):
        return {}
    for path in sorted(glob.glob(os.path.join(actions_dir, "*.jsonl")), reverse=True):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    if isinstance(item, dict) and item.get("candidate_id") == candidate_id:
                        item["_source_path"] = path
                        return item
                    break
        except Exception:
            continue
    return {}


def _xingce_action_is_consumable(action):
    return action.get("action_status") in (
        "queued_for_experience_service_review",
        "queued_for_experience_upgrade_review",
        "auto_adopted_evidence_bound",
    )


def _first_xingce_evidence_ref(candidate):
    evidence_refs = candidate.get("evidence_refs", [])
    if isinstance(evidence_refs, list):
        for item in evidence_refs:
            if isinstance(item, dict) and item.get("source_path"):
                return dict(item)
    source_refs = candidate.get("source_refs", [])
    if isinstance(source_refs, list):
        for source_path in source_refs:
            if source_path:
                return {"source_path": source_path}
    return {}


def _xingce_candidate_to_memory(candidate, candidate_path, action):
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []
    source_refs = candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []
    ref = _first_xingce_evidence_ref(candidate)
    source_path = ref.get("source_path", "")
    window_id = ref.get("canonical_window_id") or _xingce_window_from_source_path(source_path)
    declared_source = str(candidate.get("source_system") or "").strip()
    if declared_source:
        ref.setdefault("source_system", declared_source)
    ref.setdefault("computer_name", "local")
    ref.setdefault("computer_id", ref.get("computer_name", "local"))
    ref.setdefault("canonical_window_id", window_id)
    ref["candidate_path"] = candidate_path
    if action.get("_source_path"):
        ref["action_path"] = action.get("_source_path")

    title = candidate.get("title") or "Xingce work experience candidate"
    action_status = action.get("action_status", "")
    observed_facts = candidate.get("observed_facts", []) if isinstance(candidate.get("observed_facts"), list) else []
    recommended_procedure = candidate.get("recommended_procedure", []) if isinstance(candidate.get("recommended_procedure"), list) else []
    verification_steps = candidate.get("verification_steps", []) if isinstance(candidate.get("verification_steps"), list) else []
    avoid_conditions = candidate.get("avoid_conditions", []) if isinstance(candidate.get("avoid_conditions"), list) else []
    is_auto_adopted = action_status == "auto_adopted_evidence_bound"
    if is_auto_adopted:
        summary = (
            f"行策工作经验：{title}。"
            f"状态=active usable；证据={len(evidence_refs)}；source_refs={len(source_refs)}。"
            "evidence-bound，write_boundary false。"
        )
    else:
        summary = (
            f"行策待审工作经验：{title}。"
            f"状态={action_status}；证据={len(evidence_refs)}；source_refs={len(source_refs)}。"
            "这是进入经验服务评审账本的候选，不是已采用的生产经验。"
        )
    detail_parts = []
    for key in ("summary", "upgrade_reason"):
        if candidate.get(key):
            detail_parts.append(str(candidate.get(key)))
    for values in (observed_facts, recommended_procedure, avoid_conditions, verification_steps):
        detail_parts.extend(str(item) for item in values[:3])
    detail = "\n".join(part for part in detail_parts if part)

    return {
        "_type": "xingce_work_experience_candidate",
        "exp_id": candidate_id,
        "scope": f"{window_id} openclaw local xingce_review".strip(),
        "summary": summary,
        "detail": detail,
        "verbatim_excerpt": detail,
        "work_scenario": candidate.get("work_scenario") or title,
        "action_strategy": candidate.get("action_strategy") or recommended_procedure,
        "observed_facts": observed_facts,
        "recommended_procedure": recommended_procedure,
        "avoid_conditions": avoid_conditions,
        "acceptance_checks": candidate.get("acceptance_checks") or verification_steps,
        "verification_steps": verification_steps,
        "applicable_scope": candidate.get("applicable_scope") or f"{window_id} openclaw local".strip(),
        "forbidden_as_preference": True,
        "supersedes": candidate.get("supersedes", []) if isinstance(candidate.get("supersedes"), list) else [],
        "conflicts_with": candidate.get("conflicts_with", []) if isinstance(candidate.get("conflicts_with"), list) else [],
        "score": max(float(candidate.get("confidence", 0.7) or 0.7), 0.72),
        "source_refs": ref,
        "_source_refs": ref,
        "project_id": ref.get("project_id", ""),
        "project_root": ref.get("project_root") or ref.get("workspace_root") or ref.get("cwd") or "",
        "workstream_id": ref.get("workstream_id") or ref.get("workstream") or "",
        "task_id": ref.get("task_id") or ref.get("task") or "",
        "lifecycle_version": 1,
        "_xingce": {
            "candidate_id": candidate_id,
            "candidate_type": candidate.get("candidate_type", ""),
            "frontstage_surface": candidate.get("frontstage_surface", ""),
            "lifecycle_status": candidate.get("lifecycle_status", ""),
            "action_id": action.get("action_id", ""),
            "action": action.get("action", ""),
            "action_status": action_status,
            "candidate_path": candidate_path,
            "action_path": action.get("_source_path", ""),
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
    }


def _load_xingce_work_experience_candidate_memories():
    root = _xingce_project_root()
    candidates_dir = os.path.join(root, "output", "xingce_work_experience", "candidates")
    if not os.path.isdir(candidates_dir):
        return []
    memories = []
    for path in sorted(glob.glob(os.path.join(candidates_dir, "xingce-*-candidate.json"))):
        candidate = _read_json_object(path)
        if candidate.get("candidate_type") != "xingce_work_experience":
            continue
        if candidate.get("lifecycle_status") != "candidate":
            continue
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id:
            continue
        action = _latest_xingce_candidate_action(root, candidate_id)
        if not _xingce_action_is_consumable(action):
            continue
        memories.append(_xingce_candidate_to_memory(candidate, path, action))
    return memories


PROJECT_STATUS_WRITE_BOUNDARY_RULE = (
    "写入边界说明：保持 false 是边界，不是未接通、未落盘、待触发写入，"
    "也不是下一步要补的写入线。project_status/write_boundary 里的 raw_write_performed=false、"
    "xingce_write_performed=false、hermes_write_performed=false、openclaw_write_performed=false "
    "表示这些层本轮按设计保持只读或沉默。回答时应说“保持 false 是边界”，"
    "不要说“以后再接写入线”，也不要说“后台独立工作流后续补写入链”。"
    "如果问题在“补写入链”和“验自然对话质量”之间二选一，应回答先验自然对话质量。"
    "不要引入 K/N/J、Linux、eval 等旧阶段标签。"
)


def _project_status_to_memory(status, status_path):
    status_id = str(status.get("status_id") or "").strip()
    if not status_id:
        return {}
    artifact_type = str(status.get("artifact_type") or "").strip()
    write_boundary = status.get("write_boundary", {}) if isinstance(status.get("write_boundary"), dict) else {}
    evidence_refs = status.get("evidence_refs", []) if isinstance(status.get("evidence_refs"), list) else []
    source_ref = {
        "source_system": "memcore",
        "computer_name": "local",
        "computer_id": "local",
        "canonical_window_id": status.get("canonical_window_id", "project_status"),
        "session_id": status_id,
        "source_path": status_path,
        "msg_ids": [status_id],
        "evidence_refs": evidence_refs,
    }
    summary = status.get("summary") or status.get("title") or "Time Library当前进展"
    detail_parts = [PROJECT_STATUS_WRITE_BOUNDARY_RULE]
    for key in (
        "skill_artifact_status",
        "probe_id",
        "skill_relative_path",
        "skill_path",
        "skill_sha256",
        "probe_receipt_path",
        "skill_generation_stage",
        "current_state",
        "next_step",
    ):
        if status.get(key):
            detail_parts.append(f"{key}: {status.get(key)}")
    for key in ("completed", "remaining", "limitations"):
        values = status.get(key, [])
        if isinstance(values, list):
            detail_parts.extend(str(item) for item in values)
    for ref in evidence_refs[:4]:
        if isinstance(ref, dict):
            detail_parts.append("evidence_ref: " + " ".join(
                str(ref.get(key) or "")
                for key in ("kind", "probe_id", "relative_path", "source_path", "sha256")
                if ref.get(key)
            ))
    detail = "\n".join(part for part in detail_parts if part)
    scope_parts = [
        "memcore-cloud",
        "Time Library",
        "project_status",
        "current",
        artifact_type,
        status.get("probe_id", ""),
        status.get("skill_relative_path", ""),
        status.get("skill_artifact_status", ""),
    ]
    return {
        "_type": "time_library_project_status",
        "exp_id": status_id,
        "scope": " ".join(str(part) for part in scope_parts if part).strip(),
        "summary": summary,
        "detail": detail,
        "score": float(status.get("score", 1.0) or 1.0),
        "source_refs": source_ref,
        "_source_refs": source_ref,
        "lifecycle_version": int(status.get("lifecycle_version", 1) or 1),
        "_project_status": {
            "status_id": status_id,
            "artifact_type": artifact_type,
            "status": status.get("status", ""),
            "project": status.get("project", ""),
            "source_path": status_path,
            "skill_artifact_status": status.get("skill_artifact_status", ""),
            "probe_id": status.get("probe_id", ""),
            "probe_receipt_path": status.get("probe_receipt_path", ""),
            "skill_relative_path": status.get("skill_relative_path", ""),
            "skill_path": status.get("skill_path", ""),
            "skill_sha256": status.get("skill_sha256", ""),
            "status_receipt_write_performed": bool(write_boundary.get("status_receipt_write_performed", False)),
            "production_experience_write_performed": bool(write_boundary.get("production_experience_write_performed", False)),
            "raw_write_performed": bool(write_boundary.get("raw_write_performed", False)),
            "zhiyi_write_performed": bool(write_boundary.get("zhiyi_write_performed", False)),
            "xingce_write_performed": bool(write_boundary.get("xingce_write_performed", False)),
            "hermes_write_performed": bool(write_boundary.get("hermes_write_performed", write_boundary.get("hermes_write_performed_by_time_library", False))),
            "hermes_skill_write_performed_by_time_library": bool(write_boundary.get("hermes_skill_write_performed_by_time_library", False)),
            "openclaw_write_performed": bool(write_boundary.get("openclaw_write_performed", False)),
        },
    }


def _load_time_library_project_status_memories():
    root = _project_status_root()
    specs = [
        (
            os.path.join(root, "output", "time_library_project_status", "latest.json"),
            {"time_library_project_status"},
        ),
        (
            os.path.join(root, "output", "hermes_native_learning", "skill_artifact_status", "latest.json"),
            {"hermes_skill_artifact_status"},
        ),
    ]
    memories = []
    for latest_path, allowed_types in specs:
        status = _read_json_object(latest_path)
        if status.get("artifact_type") not in allowed_types:
            continue
        if status.get("status") not in ("active", "current"):
            continue
        memory = _project_status_to_memory(status, latest_path)
        if memory:
            memories.append(memory)
    return memories


# ─── 加载经验对象 ───────────────────────────────────

def load_memories():
    """加载所有 zhiyi 对象。

    J2 去重：相同 exp_id 的对象，保留 lifecycle_version 最高的记录。
    """
    # Allow test fixture override via env var (MEMCORE_ZHIYI_ROOT_OVERRIDE)
    zhiyi_root_override = os.environ.get("MEMCORE_ZHIYI_ROOT_OVERRIDE")
    zhiyi_path = zhiyi_root_override if zhiyi_root_override else ZHIYI_ROOT
    memories = []
    seen_exp_ids = {}  # exp_id -> (lifecycle_version, record)

    memories.extend(_load_time_library_project_status_memories())

    for ftype in ["preference_memory", "case_memory", "error_memory"]:
        path = os.path.join(zhiyi_path, ftype, f"{ftype}.jsonl")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    r = json.loads(line)
                    r["_type"] = ftype
                    # 解析 source_refs
                    try:
                        r["_source_refs"] = json.loads(r.get("source_refs", "{}"))
                    except:
                        r["_source_refs"] = {}
                    r = _normalize_memory_record_node(r)

                    # J2 去重：基于 exp_id + lifecycle_version
                    exp_id = r.get("exp_id", "")
                    lifecycle_version = r.get("lifecycle_version", 1)

                    if exp_id:
                        existing = seen_exp_ids.get(exp_id)
                        if existing is None or lifecycle_version > existing[0]:
                            seen_exp_ids[exp_id] = (lifecycle_version, r)
                    else:
                        # 无 exp_id（偏好记忆）直接加入
                        memories.append(r)
                except: pass

    # 按 lifecycle_version 降序保留唯一 exp_id
    for version, rec in seen_exp_ids.values():
        memories.append(rec)

    memories.extend(_load_xingce_work_experience_candidate_memories())

    return memories

_QUERY_TERMS_CACHE = {}


def _query_terms(query):
    q = str(query or "").strip().lower()
    if not q:
        return ()
    cached = _QUERY_TERMS_CACHE.get(q)
    if cached is not None:
        return cached
    terms = []

    def add(term):
        term = str(term or "").strip().lower()
        if term and term not in terms:
            terms.append(term)

    add(q)
    for term in re.split(r"[\s,，。；;：:、/]+", q):
        add(term)

    for term in [
        "Time Library", "memcore", "知意", "行策", "openclaw", "hermes",
        "raw", "原始记忆", "模型", "使用日志", "服务", "项目",
    ]:
        if term.lower() in q:
            add(term)

    compact = q
    for filler in ["接上", "继续", "帮我", "请", "一下", "当前", "进度"]:
        compact = compact.replace(filler, " ")
    for term in re.split(r"[\s,，。；;：:、/]+", compact):
        add(term)
    result = tuple(terms)
    if len(_QUERY_TERMS_CACHE) >= 256:
        _QUERY_TERMS_CACHE.clear()
    _QUERY_TERMS_CACHE[q] = result
    return result


def _source_refs_for_filter(memory):
    sr = memory.get("_source_refs") or memory.get("source_refs") or {}
    if isinstance(sr, str):
        try:
            sr = json.loads(sr)
        except Exception:
            sr = {}
    return sr if isinstance(sr, dict) else {}


def _normalize_source_filter(value):
    value = str(value or "").strip()
    if value.lower() in ("all", "*", "shared", "raw_pool"):
        return ""
    return value


def filter_memories(
    memories,
    type_filter=None,
    scope_filter=None,
    query=None,
    source_system_filter=None,
    computer_name_filter=None,
    session_id_filter=None,
    canonical_window_id_filter=None,
):
    """过滤 memories"""
    source_system_filter = _normalize_source_filter(source_system_filter)
    computer_name_filter = str(computer_name_filter or "").strip()
    session_id_filter = str(session_id_filter or "").strip()
    canonical_window_id_filter = str(canonical_window_id_filter or "").strip()
    query_terms = _query_terms(query) if query else ()
    source_refs_needed = bool(
        source_system_filter
        or computer_name_filter
        or session_id_filter
        or canonical_window_id_filter
    )
    results = []
    for m in memories:
        # type filter
        if type_filter and m["_type"] not in type_filter:
            continue
        sr = _source_refs_for_filter(m) if source_refs_needed else {}
        is_xingce_candidate = m.get("_type") == "xingce_work_experience_candidate" or bool(m.get("_xingce"))
        if source_system_filter and not is_xingce_candidate and sr.get("source_system", "") != source_system_filter:
            continue
        if computer_name_filter and (sr.get("computer_name", "") or sr.get("computer_id", "")) != computer_name_filter:
            continue
        session_matched = bool(session_id_filter and sr.get("session_id", "") == session_id_filter)
        if session_id_filter and not session_matched:
            continue
        if canonical_window_id_filter and not session_matched:
            memory_window_id = (
                sr.get("canonical_window_id")
                or m.get("canonical_window_id")
                or str(m.get("scope", "")).replace("window/", "")
            )
            if memory_window_id != canonical_window_id_filter:
                continue
        # scope filter
        if scope_filter:
            # 支持 window/sg 或 sg 两种格式
            scope = m.get("scope", "")
            sf = scope_filter.replace("window/", "")
            if sf not in scope:
                continue
        # query filter (关键词匹配)
        if query_terms:
            summary = str(m.get("summary", "")).lower()
            detail = str(m.get("detail", "")).lower()
            matched = any(term in summary or term in detail for term in query_terms)
            if _is_project_status_memory(m):
                project_status = m.get("_project_status", {}) if isinstance(m.get("_project_status"), dict) else {}
                project_text = " ".join(str(part or "") for part in [
                    m.get("scope", ""),
                    project_status.get("project", ""),
                    project_status.get("status_id", ""),
                    project_status.get("source_path", ""),
                    project_status.get("artifact_type", ""),
                    project_status.get("skill_artifact_status", ""),
                    project_status.get("probe_id", ""),
                    project_status.get("probe_receipt_path", ""),
                    project_status.get("skill_relative_path", ""),
                    project_status.get("skill_path", ""),
                    project_status.get("skill_sha256", ""),
                ]).lower()
                matched = matched or any(term in project_text for term in query_terms)
            if not matched:
                continue
        results.append(m)
    return results

def _keyword_score(memory, query):
    if not query:
        return memory.get("score", 0.7)
    summary = memory.get("summary", "").lower()
    detail = memory.get("detail", "").lower()
    score = 0.0
    text = summary + " " + detail
    for term in _query_terms(query):
        if term in text:
            score += 0.3
    return min(score + 0.4, 1.0)


def _fts5_index_path():
    explicit = os.environ.get("MEMCORE_FTS5_RECALL_INDEX_PATH")
    if explicit:
        return explicit
    if _fts5_default_index_path is None:
        return os.path.join(MEMCORE_PROJECT_ROOT, "runtime", "fts5_recall", "p3_memories.sqlite3")
    return _fts5_default_index_path(MEMCORE_PROJECT_ROOT)


_FTS5_INDEX_LOCK = threading.Lock()
_FTS5_REFRESH_THREAD = None
_FTS5_REFRESH_PROCESS = None
_FTS5_REFRESH_STATUS = {}
_FTS5_MEMORY_SOURCE_SIGNATURES = {}


def _fts5_bind_source_signature(memories, signature):
    if _fts5_source_signature_digest is None:
        return ""
    digest = _fts5_source_signature_digest(signature)
    _FTS5_MEMORY_SOURCE_SIGNATURES[id(memories)] = digest
    while len(_FTS5_MEMORY_SOURCE_SIGNATURES) > 4:
        _FTS5_MEMORY_SOURCE_SIGNATURES.pop(next(iter(_FTS5_MEMORY_SOURCE_SIGNATURES)))
    return digest


def _fts5_expected_source_signature(memories):
    digest = _FTS5_MEMORY_SOURCE_SIGNATURES.get(id(memories), "")
    if digest:
        return digest
    if memories is MEMORIES_CACHE and MEMORIES_CACHE_SIGNATURE:
        return _fts5_bind_source_signature(memories, MEMORIES_CACHE_SIGNATURE)
    return ""


def _fts5_current_source_signature():
    if _fts5_source_signature_digest is None:
        return ""
    return _fts5_source_signature_digest(_memories_source_signature())


def _fts5_refresh_lock_path(index_path):
    return f"{index_path}.refresh.lock"


def _fts5_refresh_debounce_seconds():
    try:
        configured = float(os.environ.get("MEMCORE_FTS5_REFRESH_DEBOUNCE_SECONDS") or "300")
    except (TypeError, ValueError):
        configured = 300.0
    return max(0.0, min(configured, 3600.0))


def _fts5_refresh_debounce_remaining():
    debounce_seconds = _fts5_refresh_debounce_seconds()
    if debounce_seconds <= 0:
        return 0.0
    mtimes = []
    for entry in _memories_source_signature():
        if not isinstance(entry, tuple) or len(entry) < 2:
            continue
        mtime_ns = entry[1]
        if isinstance(mtime_ns, int):
            mtimes.append(mtime_ns / 1_000_000_000.0)
    if not mtimes:
        return 0.0
    quiet_seconds = max(0.0, time.time() - max(mtimes))
    return max(0.0, debounce_seconds - quiet_seconds)


def _fts5_process_alive(pid):
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _fts5_acquire_refresh_lock(index_path, token, trigger):
    lock_path = _fts5_refresh_lock_path(index_path)
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        try:
            descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                state = json.loads(Path(lock_path).read_text(encoding="utf-8"))
                age = max(0.0, time.time() - os.path.getmtime(lock_path))
            except Exception:
                state, age = {}, 0.0
            if _fts5_process_alive(state.get("pid")) or age < 60.0:
                return "", "already_running"
            try:
                os.unlink(lock_path)
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({
                "token": token,
                "pid": 0,
                "trigger": trigger,
                "started_at_epoch": time.time(),
            }, handle, sort_keys=True)
        return lock_path, "acquired"
    return "", "already_running"


def _fts5_release_refresh_lock(lock_path, token):
    if not lock_path:
        return
    try:
        state = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    except Exception:
        return
    if state.get("token") != token:
        return
    try:
        os.unlink(lock_path)
    except FileNotFoundError:
        pass


def _fts5_refresh_worker(process, result_path, lock_path, token, trigger):
    global _FTS5_REFRESH_THREAD, _FTS5_REFRESH_PROCESS, _FTS5_REFRESH_STATUS
    try:
        returncode = process.wait()
        try:
            report = json.loads(Path(result_path).read_text(encoding="utf-8"))
        except Exception as exc:
            report = {
                "ok": False,
                "error": f"refresh_receipt_unavailable:{type(exc).__name__}",
                "doc_count": 0,
            }
        if returncode and report.get("ok"):
            report["ok"] = False
            report["error"] = f"refresh_worker_exit_{returncode}"
        _FTS5_REFRESH_STATUS = {
            "ok": bool(report.get("ok")),
            "trigger": trigger,
            "completed_at": report.get("built_at", ""),
            "doc_count": int(report.get("doc_count") or 0),
            "error": report.get("error"),
            "worker_pid": int(report.get("worker_pid") or process.pid or 0),
            "atomic_publish": bool(report.get("atomic_publish")),
        }
    except Exception as exc:
        _FTS5_REFRESH_STATUS = {
            "ok": False,
            "trigger": trigger,
            "completed_at": "",
            "doc_count": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "worker_pid": int(getattr(process, "pid", 0) or 0),
            "atomic_publish": False,
        }
    finally:
        try:
            os.unlink(result_path)
        except FileNotFoundError:
            pass
        _fts5_release_refresh_lock(lock_path, token)
        with _FTS5_INDEX_LOCK:
            _FTS5_REFRESH_THREAD = None
            _FTS5_REFRESH_PROCESS = None


def _schedule_fts5_refresh(
    memories,
    index_path,
    trigger,
    expected_source_signature="",
    *,
    bypass_debounce=False,
):
    global _FTS5_REFRESH_THREAD, _FTS5_REFRESH_PROCESS, _FTS5_REFRESH_STATUS
    with _FTS5_INDEX_LOCK:
        if _FTS5_REFRESH_THREAD is not None and _FTS5_REFRESH_THREAD.is_alive():
            return "already_running"
        debounce_remaining = 0.0 if bypass_debounce else _fts5_refresh_debounce_remaining()
        if debounce_remaining > 0:
            _FTS5_REFRESH_STATUS = {
                "ok": False,
                "trigger": trigger,
                "completed_at": "",
                "doc_count": 0,
                "error": None,
                "worker_pid": 0,
                "atomic_publish": False,
                "deferred_seconds": round(debounce_remaining, 3),
            }
            return "deferred_source_change"
        token = secrets.token_hex(12)
        lock_path, lock_state = _fts5_acquire_refresh_lock(index_path, token, trigger)
        if lock_state != "acquired":
            return lock_state
        result_path = f"{index_path}.refresh.{token}.json"
        tool_path = Path(__file__).resolve().parents[1] / "tools" / "build_fts5_recall_index.py"
        command = [
            sys.executable,
            str(tool_path),
            "--index-path",
            str(index_path),
            "--result-path",
            result_path,
            "--lock-path",
            lock_path,
            "--lock-token",
            token,
        ]
        if expected_source_signature:
            command.extend(["--expected-source-signature", expected_source_signature])
        popen_kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(command, **popen_kwargs)
        except Exception:
            _fts5_release_refresh_lock(lock_path, token)
            raise
        try:
            Path(lock_path).write_text(json.dumps({
                "token": token,
                "pid": process.pid,
                "trigger": trigger,
                "started_at_epoch": time.time(),
            }, sort_keys=True), encoding="utf-8")
            os.chmod(lock_path, 0o600)
        except Exception:
            pass
        _FTS5_REFRESH_STATUS = {
            "ok": False,
            "trigger": trigger,
            "completed_at": "",
            "doc_count": 0,
            "error": None,
            "worker_pid": int(process.pid or 0),
            "atomic_publish": False,
            "deferred_seconds": 0.0,
        }
        _FTS5_REFRESH_THREAD = threading.Thread(
            target=_fts5_refresh_worker,
            args=(process, result_path, lock_path, token, trigger),
            daemon=True,
        )
        _FTS5_REFRESH_PROCESS = process
        _FTS5_REFRESH_THREAD.start()
    return "scheduled"


def _schedule_startup_fts5_refresh(memories):
    """Migrate legacy indexes without making ordinary source churn eager."""
    state = _fts5_status()
    expected_source_signature = _fts5_expected_source_signature(memories)
    if not (state.get("exists") or state.get("fts5_enabled")):
        return "not_configured"
    if state.get("source_signature") == expected_source_signature:
        return "current"

    missing_source_signature = bool(
        state.get("exists")
        and expected_source_signature
        and not state.get("source_signature")
    )
    trigger = (
        "startup_source_signature_missing"
        if missing_source_signature
        else "startup_corpus_change"
    )
    return _schedule_fts5_refresh(
        memories,
        _fts5_index_path(),
        trigger,
        expected_source_signature=expected_source_signature,
        bypass_debounce=missing_source_signature,
    )


def _copy_with_fts5_rank(memory, row, rank_index):
    item = dict(memory)
    item["_fts5"] = {
        "doc_id": row.get("doc_id", ""),
        "rank": row.get("rank"),
        "rank_index": rank_index,
        "matched_by": "fts5_bm25",
        "rank_reason": "sqlite_fts5_trigram_bm25",
    }
    return item


def _fts5_ordered_memories(memories, query, top_k):
    if (
        _fts5_search_index is None
        or _fts5_corpus_signature is None
        or _fts5_memory_doc_id is None
        or _fts5_build_index is None
    ):
        return [], {
            "enabled": True,
            "applied": False,
            "error": "fts5_module_unavailable",
            "matched_count": 0,
            "raw_matched_count": 0,
        }
    expected_source_signature = _fts5_current_source_signature()
    index_path = _fts5_index_path()
    result = _fts5_search_index(
        query=query,
        index_path=index_path,
        limit=max(int(top_k or 5) * 8, 20),
        expected_source_signature=expected_source_signature,
    )
    initial_status = result.get("status") or {}
    initial_error = str(initial_status.get("error") or "")
    refresh_needed = initial_error in {"index_missing", "index_not_ready"} or bool(initial_status.get("stale"))
    refresh_trigger = (
        initial_error if initial_error in {"index_missing", "index_not_ready"}
        else str(initial_status.get("stale_reason") or "source_snapshot_unknown") if initial_status.get("stale")
        else ""
    )
    refresh_schedule = ""
    if refresh_needed:
        refresh_schedule = _schedule_fts5_refresh(
            memories,
            index_path,
            refresh_trigger,
            expected_source_signature=expected_source_signature,
        )
    rows = result.get("rows") or []
    doc_map = {}
    if rows:
        requested_doc_ids = {str(row.get("doc_id") or "") for row in rows}
        requested_exp_ids = {
            str(row.get("exp_id") or "")
            for row in rows
            if str(row.get("exp_id") or "")
        }
        anonymous_doc_ids = requested_doc_ids - requested_exp_ids
        for memory in memories:
            exp_id = str(memory.get("exp_id") or "")
            if exp_id:
                if exp_id in requested_exp_ids:
                    doc_map[exp_id] = memory
                continue
            if not anonymous_doc_ids:
                continue
            try:
                doc_id = _fts5_memory_doc_id(memory)
            except Exception:
                continue
            if doc_id in anonymous_doc_ids:
                doc_map[doc_id] = memory
                anonymous_doc_ids.remove(doc_id)
                if not anonymous_doc_ids and len(doc_map) >= len(requested_doc_ids):
                    break
    ordered = []
    seen = set()
    for rank_index, row in enumerate(rows):
        doc_id = str(row.get("doc_id") or "")
        memory = doc_map.get(doc_id)
        if not memory or doc_id in seen:
            continue
        seen.add(doc_id)
        ordered.append(_copy_with_fts5_rank(memory, row, rank_index))
    status = result.get("status") or {}
    refresh_completed = bool(
        not refresh_needed
        and _FTS5_REFRESH_STATUS.get("ok")
        and status.get("built_at")
        and status.get("built_at") == _FTS5_REFRESH_STATUS.get("completed_at")
    )
    status["auto_refresh_attempted"] = bool(refresh_needed or refresh_completed)
    status["auto_refresh_completed"] = refresh_completed
    status["auto_refresh_pending"] = refresh_schedule in {"scheduled", "already_running"}
    status["auto_refresh_deferred"] = refresh_schedule == "deferred_source_change"
    status["auto_refresh_debounce_remaining_seconds"] = float(
        _FTS5_REFRESH_STATUS.get("deferred_seconds") or 0.0
    )
    status["auto_refresh_schedule"] = refresh_schedule
    status["auto_refresh_trigger"] = (
        refresh_trigger or (_FTS5_REFRESH_STATUS.get("trigger", "") if refresh_completed else "")
    )
    status["auto_refresh_error"] = _FTS5_REFRESH_STATUS.get("error")
    status["last_refresh_completed_at"] = (
        status.get("built_at", "") or _FTS5_REFRESH_STATUS.get("completed_at", "")
    )
    status["refresh_doc_count"] = int(_FTS5_REFRESH_STATUS.get("doc_count") or 0)
    status["post_filter_matched_count"] = len(ordered)
    status["discarded_by_filter_count"] = max(0, int(status.get("raw_matched_count") or status.get("matched_count") or 0) - len(ordered))
    return ordered, status


# ─── BM25-like scoring (local fallback, no external deps) ─────
# ─── v0 persistent/incremental index: disk persistence + background rebuild ─────

import math as _math
import hashlib as _hashlib
import json as _bm25_json
import threading as _threading

# ─── BM25 segment-based persistent index (attempt-4) ─────────
# manifest.json + segments/*.seg.json, atomic write, LRU segment cache.
# /health reads manifest only (no segment loads). Cold build is background-only.

_BM25_INDEX_LOCK = _threading.Lock()
_BM25_REFRESH_THREAD = None
_BM25_REFRESH_EVENT = _threading.Event()
_BM25_PATH_CONTEXT = _threading.local()

_BM25_MANIFEST_CACHE = {
    "manifest": None,
    "signature": None,
    "N": 0,
}


def _bm25_corpus_signature(memories):
    if not memories:
        return "empty"
    h = _hashlib.sha256()
    h.update(str(len(memories)).encode("utf-8"))
    for m in memories:
        for key in ("exp_id", "type", "_type", "scope",
                     "summary", "detail", "lifecycle_version", "source_refs"):
            h.update(str(m.get(key) or "").encode("utf-8"))
    return h.hexdigest()[:16]


def _bm25_index_dir():
    ctx_dir = getattr(_BM25_PATH_CONTEXT, "index_dir", None)
    if ctx_dir:
        return ctx_dir
    try:
        root = os.environ.get("MEMCORE_ROOT") or MEMCORE_PROJECT_ROOT
    except Exception:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "runtime", "bm25_index")


def _bm25_manifest_path():
    return os.path.join(_bm25_index_dir(), "manifest.json")


def _bm25_segment_path(seg_id):
    seg_dir = os.path.join(_bm25_index_dir(), "segments")
    return os.path.join(seg_dir, f"{seg_id}.seg.json")


def _persist_segment(seg_id, seg_data):
    seg_dir = os.path.join(_bm25_index_dir(), "segments")
    try:
        os.makedirs(seg_dir, exist_ok=True)
    except Exception:
        return False
    path = _bm25_segment_path(seg_id)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            _bm25_json.dump(seg_data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return False


def _persist_manifest(manifest):
    idx_dir = _bm25_index_dir()
    try:
        os.makedirs(idx_dir, exist_ok=True)
    except Exception:
        return False
    path = _bm25_manifest_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            _bm25_json.dump(manifest, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return False


def _load_manifest():
    path = _bm25_manifest_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _bm25_json.load(f)
        if not isinstance(data, dict) or "segments" not in data:
            return None
        return data
    except Exception:
        return None


_BM25_SEGMENT_CACHE = {}
_BM25_SEGMENT_CACHE_MAX = 4


def _load_segment(seg_id, _copy=True):
    cached = _BM25_SEGMENT_CACHE.get(seg_id)
    if cached is not None:
        _BM25_SEGMENT_CACHE.pop(seg_id)
        _BM25_SEGMENT_CACHE[seg_id] = cached
        return dict(cached) if _copy else cached
    path = _bm25_segment_path(seg_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            seg = _bm25_json.load(f)
    except Exception:
        return None
    if len(_BM25_SEGMENT_CACHE) >= _BM25_SEGMENT_CACHE_MAX:
        try:
            _BM25_SEGMENT_CACHE.pop(next(iter(_BM25_SEGMENT_CACHE)))
        except StopIteration:
            pass
    _BM25_SEGMENT_CACHE[seg_id] = seg
    return dict(seg) if _copy else seg


def _bm25_seg_compact_background():
    global _BM25_REFRESH_THREAD
    try:
        manifest = _load_manifest()
        if not manifest or len(manifest.get("segments", [])) <= 1:
            return
        seg_infos = manifest["segments"]
        if len(seg_infos) <= 1:
            return
        segments = []
        for si in seg_infos:
            seg = _load_segment(si["id"])
            if seg:
                segments.append((si["id"], seg))
        if len(segments) <= 1:
            return
        merged_id = f"c{int(time.time()*1000):x}{os.getpid():04x}"
        merged_tf = []
        merged_len = []
        merged_df = {}
        merged_exp = {}
        doc_offset = 0
        total_dl = 0
        for _, seg in segments:
            for i, tf_map in enumerate(seg.get("doc_tf", [])):
                merged_tf.append(tf_map)
            merged_len.extend(seg.get("doc_len", []))
            total_dl += sum(seg.get("doc_len", []))
            for eid, idx in seg.get("exp_id_index", {}).items():
                if eid not in merged_exp:
                    merged_exp[eid] = doc_offset + idx
            for t, df in seg.get("doc_freq", {}).items():
                merged_df[t] = merged_df.get(t, 0) + df
            doc_offset += seg["N"]
        N = len(merged_tf)
        avg_dl = total_dl / N if N > 0 else 1.0
        idf_map = {}
        for t, df in merged_df.items():
            idf_map[t] = _math.log(max(0.0, (N - df + 0.5) / (df + 0.5) + 1.0))
        merged_seg = {
            "N": N, "doc_tf": merged_tf, "doc_len": merged_len,
            "doc_freq": merged_df, "idf_map": idf_map,
            "avg_dl": avg_dl, "exp_id_index": merged_exp,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if not _persist_segment(merged_id, merged_seg):
            return
        old_ids = {sid for sid, _ in segments}
        manifest["N"] = manifest.get("N", 0)
        manifest["segments"] = [si for si in seg_infos if si["id"] not in old_ids]
        manifest["segments"].append({"id": merged_id, "N": N})
        manifest["total_docs"] = sum(si["N"] for si in manifest["segments"])
        all_doc_freq = {}
        for si in manifest["segments"]:
            s = _load_segment(si["id"])
            if s:
                for t, df in s.get("doc_freq", {}).items():
                    all_doc_freq[t] = all_doc_freq.get(t, 0) + df
        manifest["doc_freq"] = all_doc_freq
        total_all_dl = 0
        total_all_docs = 0
        for si in manifest["segments"]:
            s = _load_segment(si["id"])
            if s:
                total_all_dl += sum(s.get("doc_len", []))
                total_all_docs += s["N"]
        manifest["avg_dl"] = total_all_dl / total_all_docs if total_all_docs > 0 else 1.0
        merged_idf = {}
        for t, df in all_doc_freq.items():
            merged_idf[t] = _math.log(max(0.0, (total_all_docs - df + 0.5) / (df + 0.5) + 1.0))
        manifest["idf_map"] = merged_idf
        manifest["build_count"] = manifest.get("build_count", 0) + 1
        manifest["last_compaction_at"] = datetime.now(timezone.utc).isoformat()
        with _BM25_INDEX_LOCK:
            _persist_manifest(manifest)
            for sid in old_ids:
                _BM25_SEGMENT_CACHE.pop(sid, None)
        for sid in old_ids:
            try:
                os.unlink(_bm25_segment_path(sid))
            except Exception:
                pass
    except Exception:
        pass
    finally:
        with _BM25_INDEX_LOCK:
            _BM25_REFRESH_THREAD = None


def _build_full_index_from_docs(docs, batch_size=256):
    if not docs:
        return
    with _BM25_INDEX_LOCK:
        previous = _load_manifest() or {}
        old_segment_ids = {si.get("id") for si in previous.get("segments", [])}
    new_segments = []
    all_doc_freq = {}
    total_all_dl = 0
    total_all_docs = 0

    for start in range(0, len(docs), batch_size):
        batch = docs[start:start + batch_size]
        N = len(batch)
        doc_tf_list = []
        doc_len_list = []
        doc_freq = {}
        total_dl = 0
        exp_id_index = {}
        for i, m in enumerate(batch):
            text = " ".join([
                str(m.get("summary") or ""),
                str(m.get("detail") or ""),
            ])
            tokens = _tokenize_bm25(text)
            dl = len(tokens)
            doc_len_list.append(dl)
            total_dl += dl
            tf_map = {}
            for t in tokens:
                tf_map[t] = tf_map.get(t, 0) + 1
            doc_tf_list.append(tf_map)
            for t in tf_map:
                doc_freq[t] = doc_freq.get(t, 0) + 1
            eid = str(m.get("exp_id") or "")
            if eid:
                exp_id_index[eid] = i
        avg_dl = total_dl / N if N > 0 else 1.0
        idf_map = {}
        for t, df in doc_freq.items():
            idf_map[t] = _math.log(max(0.0, (N - df + 0.5) / (df + 0.5) + 1.0))
        seg_id = f"f{int(time.time()*1000):x}{os.getpid():04x}"
        seg_data = {
            "N": N, "doc_tf": doc_tf_list, "doc_len": doc_len_list,
            "doc_freq": doc_freq, "idf_map": idf_map,
            "avg_dl": avg_dl, "exp_id_index": exp_id_index,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if not _persist_segment(seg_id, seg_data):
            continue
        new_segments.append({"id": seg_id, "N": N})
        total_all_dl += total_dl
        total_all_docs += N
        for t, df in doc_freq.items():
            all_doc_freq[t] = all_doc_freq.get(t, 0) + df
    if total_all_docs <= 0:
        return
    merged_idf = {}
    for t, df in all_doc_freq.items():
        merged_idf[t] = _math.log(max(0.0, (total_all_docs - df + 0.5) / (df + 0.5) + 1.0))
    sig = _bm25_corpus_signature(docs)
    manifest = {
        "segments": new_segments,
        "total_docs": total_all_docs,
        "doc_freq": all_doc_freq,
        "idf_map": merged_idf,
        "avg_dl": total_all_dl / total_all_docs if total_all_docs > 0 else 1.0,
        "build_count": int(previous.get("build_count", 0) or 0) + 1,
        "created_at": previous.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "signature": sig,
        "last_refresh_completed_at": datetime.now(timezone.utc).isoformat(),
    }
    with _BM25_INDEX_LOCK:
        if _persist_manifest(manifest):
            for sid in old_segment_ids:
                _BM25_SEGMENT_CACHE.pop(sid, None)
            _BM25_MANIFEST_CACHE["manifest"] = manifest
            _BM25_MANIFEST_CACHE["signature"] = sig
            _BM25_MANIFEST_CACHE["N"] = manifest.get("total_docs", 0)


def _trigger_bm25_background_build(docs):
    global _BM25_REFRESH_THREAD
    index_dir = _bm25_index_dir()
    with _BM25_INDEX_LOCK:
        if _BM25_REFRESH_THREAD is not None:
            return
    def _bg():
        global _BM25_REFRESH_THREAD
        _BM25_PATH_CONTEXT.index_dir = index_dir
        try:
            _build_full_index_from_docs(docs)
        except Exception:
            pass
        finally:
            try:
                del _BM25_PATH_CONTEXT.index_dir
            except Exception:
                pass
            with _BM25_INDEX_LOCK:
                _BM25_REFRESH_THREAD = None
    t = _threading.Thread(target=_bg, daemon=True)
    with _BM25_INDEX_LOCK:
        _BM25_REFRESH_THREAD = t
    t.start()


_BM25_MEMTABLE_MAX_DOCS = 128
_BM25_MEMTABLE_FLUSH_THRESHOLD = _BM25_MEMTABLE_MAX_DOCS

_BM25_MEMTABLE_LOCK = _threading.Lock()
_BM25_MEMTABLE = {
    "segments": [],
    "doc_count": 0,
    "flush_count": 0,
    "last_flush_at": None,
}


def _memtable_exp_id_set():
    ids = set()
    for seg in _BM25_MEMTABLE["segments"]:
        ids.update(seg.get("exp_id_index", {}).keys())
    return ids


def _memtable_insert(docs):
    if not docs:
        return 0
    with _BM25_MEMTABLE_LOCK:
        current_count = _BM25_MEMTABLE["doc_count"]
        remaining = _BM25_MEMTABLE_MAX_DOCS - current_count
        if remaining <= 0:
            return 0
        to_add = docs[-remaining:]
        segment = _build_memtable_segment(to_add)
        _BM25_MEMTABLE["segments"].append(segment)
        _BM25_MEMTABLE["doc_count"] += segment["N"]
        return segment["N"]


def _build_memtable_segment(docs):
    N = len(docs)
    doc_tf_list = []
    doc_len_list = []
    doc_freq = {}
    total_dl = 0
    exp_id_index = {}
    for i, m in enumerate(docs):
        text = " ".join([
            str(m.get("summary") or ""),
            str(m.get("detail") or ""),
        ])
        tokens = _tokenize_bm25(text)
        dl = len(tokens)
        doc_len_list.append(dl)
        total_dl += dl
        tf_map = {}
        for t in tokens:
            tf_map[t] = tf_map.get(t, 0) + 1
        doc_tf_list.append(tf_map)
        for t in tf_map:
            doc_freq[t] = doc_freq.get(t, 0) + 1
        eid = str(m.get("exp_id") or "")
        if eid:
            exp_id_index[eid] = i
    avg_dl = total_dl / N if N > 0 else 1.0
    idf_map = {}
    for t, df in doc_freq.items():
        idf_map[t] = _math.log(max(0.0, (N - df + 0.5) / (df + 0.5) + 1.0))
    return {
        "N": N, "doc_tf": doc_tf_list, "doc_len": doc_len_list,
        "doc_freq": doc_freq, "idf_map": idf_map,
        "avg_dl": avg_dl, "exp_id_index": exp_id_index,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _flush_memtable_to_main_index(corpus_signature=None):
    with _BM25_MEMTABLE_LOCK:
        if not _BM25_MEMTABLE["segments"]:
            return
        segments = list(_BM25_MEMTABLE["segments"])
        _BM25_MEMTABLE["segments"] = []
        _BM25_MEMTABLE["doc_count"] = 0
    merged_tf = []
    merged_len = []
    for seg in reversed(segments):
        merged_tf.extend(seg["doc_tf"])
        merged_len.extend(seg["doc_len"])
    merged_df = {}
    merged_exp = {}
    for seg in reversed(segments):
        for t, df in seg.get("doc_freq", {}).items():
            merged_df[t] = merged_df.get(t, 0) + df
    doc_offset = 0
    for seg in reversed(segments):
        for eid, idx in seg.get("exp_id_index", {}).items():
            if eid not in merged_exp:
                merged_exp[eid] = doc_offset + idx
        doc_offset += seg["N"]
    N = len(merged_tf)
    total_dl = sum(merged_len)
    avg_dl = total_dl / N if N > 0 else 1.0
    idf_map = {}
    for t, df in merged_df.items():
        idf_map[t] = _math.log(max(0.0, (N - df + 0.5) / (df + 0.5) + 1.0))
    seg_id = f"m{int(time.time()*1000):x}{os.getpid():04x}"
    seg_data = {
        "N": N, "doc_tf": merged_tf, "doc_len": merged_len,
        "doc_freq": merged_df, "idf_map": idf_map,
        "avg_dl": avg_dl, "exp_id_index": merged_exp,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if not _persist_segment(seg_id, seg_data):
        with _BM25_MEMTABLE_LOCK:
            _BM25_MEMTABLE["segments"] = segments
            _BM25_MEMTABLE["doc_count"] = sum(s["N"] for s in segments)
        return
    manifest = _load_manifest()
    if manifest is None:
        manifest = {
            "segments": [], "total_docs": 0,
            "doc_freq": {}, "idf_map": {}, "avg_dl": 1.0,
            "build_count": 0, "created_at": datetime.now(timezone.utc).isoformat(),
        }
    manifest["segments"].append({"id": seg_id, "N": N})
    manifest["total_docs"] = sum(si["N"] for si in manifest["segments"])
    all_doc_freq = dict(manifest.get("doc_freq", {}))
    for t, df in merged_df.items():
        all_doc_freq[t] = all_doc_freq.get(t, 0) + df
    manifest["doc_freq"] = all_doc_freq
    all_dl_total = total_dl
    all_doc_count = N
    for si in manifest["segments"]:
        if si["id"] != seg_id:
            s = _load_segment(si["id"])
            if s:
                all_dl_total += sum(s.get("doc_len", []))
                all_doc_count += s["N"]
    manifest["avg_dl"] = all_dl_total / all_doc_count if all_doc_count > 0 else 1.0
    merged_idf = {}
    for t, df in all_doc_freq.items():
        merged_idf[t] = _math.log(max(0.0, (all_doc_count - df + 0.5) / (df + 0.5) + 1.0))
    manifest["idf_map"] = merged_idf
    if corpus_signature is not None:
        manifest["signature"] = corpus_signature
    else:
        manifest.setdefault("signature", f"segment-flush:{manifest.get('total_docs', 0)}")
    with _BM25_INDEX_LOCK:
        _persist_manifest(manifest)
        _BM25_MANIFEST_CACHE["manifest"] = manifest
        _BM25_MANIFEST_CACHE["signature"] = manifest.get("signature")
        _BM25_MANIFEST_CACHE["N"] = manifest.get("total_docs", 0)
    with _BM25_MEMTABLE_LOCK:
        _BM25_MEMTABLE["flush_count"] += 1
        _BM25_MEMTABLE["last_flush_at"] = datetime.now(timezone.utc).isoformat()


def _ensure_bm25_seg_index(memories):
    sig = _bm25_corpus_signature(memories)
    with _BM25_INDEX_LOCK:
        if (_BM25_MANIFEST_CACHE["manifest"] is not None
                and _BM25_MANIFEST_CACHE["signature"] == sig
                and _BM25_MANIFEST_CACHE["N"] == len(memories)):
            return _BM25_MANIFEST_CACHE["manifest"], "cache_hit"
    manifest = _load_manifest()
    if manifest and manifest.get("total_docs", 0) > 0:
        manifest_signature = manifest.get("signature")
        manifest_doc_count = int(manifest.get("total_docs") or 0)
        with _BM25_INDEX_LOCK:
            _BM25_MANIFEST_CACHE["manifest"] = manifest
            _BM25_MANIFEST_CACHE["signature"] = manifest_signature
            _BM25_MANIFEST_CACHE["N"] = manifest_doc_count
        if manifest_signature == sig and manifest_doc_count == len(memories):
            return manifest, "cache_hit"
        return manifest, "stale_served"
    empty = {"segments": [], "total_docs": 0, "doc_freq": {},
             "idf_map": {}, "avg_dl": 1.0, "build_count": 0}
    return empty, "cold_start"


def _bm25_freshness_boundary(index_status, refresh_pending):
    if refresh_pending:
        return "pending_refresh"
    if index_status in ("stale_served",):
        return "stale_index_served"
    if index_status in ("cache_hit", "refresh_completed", "fresh", "cold_build"):
        return "fresh_index"
    return "unknown"


def _memory_freshness_boundary(cache_status, refresh_pending):
    if refresh_pending:
        return "pending_refresh"
    if cache_status in ("stale_served",):
        return "stale_index_served"
    if cache_status in ("cache_hit", "refresh_completed", "cold_load"):
        return "fresh_index"
    return "unknown"


def _bm25_corpus_stats():
    with _BM25_INDEX_LOCK:
        bm25_pending = _BM25_REFRESH_THREAD is not None
    manifest = _load_manifest()
    if manifest and manifest.get("total_docs", 0) > 0:
        seg_count = len(manifest.get("segments", []))
        status = "stale_served" if bm25_pending else "cache_hit"
        return {
            "signature": manifest.get("signature"),
            "build_count": manifest.get("build_count", 0),
            "hit_count": manifest.get("hit_count", 0),
            "last_signature": manifest.get("signature"),
            "N": manifest.get("total_docs", 0),
            "index_status": status,
            "created_at": manifest.get("created_at"),
            "refresh_status": "pending" if bm25_pending else "completed",
            "refresh_pending": bm25_pending,
            "freshness_boundary": _bm25_freshness_boundary(status, bm25_pending),
            "refresh_trigger_count": manifest.get("refresh_trigger_count", 0),
            "last_refresh_duration_seconds": manifest.get("last_refresh_duration_seconds"),
            "last_refresh_started_at": manifest.get("last_refresh_started_at"),
            "last_refresh_completed_at": manifest.get("last_refresh_completed_at"),
            "tail_overlay_count": 0,
            "segment_count": seg_count,
            "segment_doc_count": manifest.get("total_docs", 0),
            "memtable_doc_count": _memtable_stats()["segment_doc_count"],
            "memtable_flush_count": _memtable_stats()["flush_count"],
            "segment_cache_size": len(_BM25_SEGMENT_CACHE),
            "compaction_status": "pending" if bm25_pending and seg_count > 1 else "idle",
        }
    return {
        "signature": None, "build_count": 0, "hit_count": 0,
        "last_signature": None, "N": 0,
        "index_status": "no_index",
        "created_at": None,
        "refresh_status": "pending" if bm25_pending else "idle",
        "refresh_pending": bm25_pending,
        "freshness_boundary": "unknown",
        "refresh_trigger_count": 0,
        "last_refresh_duration_seconds": None,
        "last_refresh_started_at": None,
        "last_refresh_completed_at": None,
        "tail_overlay_count": 0,
        "segment_count": 0,
        "segment_doc_count": 0,
        "memtable_doc_count": _memtable_stats()["segment_doc_count"],
        "memtable_flush_count": _memtable_stats()["flush_count"],
        "segment_cache_size": len(_BM25_SEGMENT_CACHE),
        "compaction_status": "idle",
    }


def _tokenize_bm25(text):
    """Simple tokenizer: split on non-alphanumeric + CJK char boundaries."""
    if not text:
        return []
    text_lower = text.lower()
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text_lower)
    return tokens


def _bm25_score_from_cache(query_tokens, idf_map, avg_dl, tf_map, dl, k1=1.5, b=0.75):
    """Score a single pre-tokenized document against query tokens."""
    if dl == 0:
        return 0.0
    score = 0.0
    for qt in query_tokens:
        tf = tf_map.get(qt, 0)
        if tf == 0:
            continue
        idf = idf_map.get(qt, 0.0)
        score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
    return score


def _bm25_score_single(memory, query_tokens, idf_map, avg_dl, k1=1.5, b=0.75):
    """Compute BM25 score for a single memory against tokenized query."""
    text = " ".join([
        str(memory.get("summary") or ""),
        str(memory.get("detail") or ""),
    ])
    doc_tokens = _tokenize_bm25(text)
    dl = len(doc_tokens)
    if dl == 0:
        return 0.0
    tf_map = {}
    for t in doc_tokens:
        tf_map[t] = tf_map.get(t, 0) + 1
    score = 0.0
    for qt in query_tokens:
        tf = tf_map.get(qt, 0)
        if tf == 0:
            continue
        idf = idf_map.get(qt, 0.0)
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * dl / avg_dl)
        score += idf * numerator / denominator
    return score


def _memtable_stats():
    with _BM25_MEMTABLE_LOCK:
        seg_count = len(_BM25_MEMTABLE["segments"])
        return {
            "segment_count": seg_count,
            "segment_doc_count": _BM25_MEMTABLE["doc_count"],
            "memtable_max_docs": _BM25_MEMTABLE_MAX_DOCS,
            "memtable_full": _BM25_MEMTABLE["doc_count"] >= _BM25_MEMTABLE_MAX_DOCS,
            "flush_count": _BM25_MEMTABLE["flush_count"],
            "last_flush_at": _BM25_MEMTABLE["last_flush_at"],
        }


def _compute_memtable_idf():
    total_docs = 0
    doc_freq = {}
    total_dl = 0
    for seg in _BM25_MEMTABLE["segments"]:
        total_docs += seg["N"]
        total_dl += sum(seg["doc_len"])
        for t, df in seg.get("doc_freq", {}).items():
            doc_freq[t] = doc_freq.get(t, 0) + df
    if total_docs == 0:
        return {}, 1.0
    avg_dl = total_dl / total_docs
    idf_map = {}
    for t, df in doc_freq.items():
        idf_map[t] = _math.log(max(0.0, (total_docs - df + 0.5) / (df + 0.5) + 1.0))
    return idf_map, avg_dl


def _compute_bm25_scores(memories, query, k1=1.5, b=0.75, corpus_memories=None):
    """Compute BM25 scores using segment index + bounded memtable.

    Returns list of (bm25_score, memory) tuples, sorted descending.
    Same format as before for caller compatibility. Always returns
    all input memories (unscored ones get 0.0).
    """
    if not query or not memories:
        return [(0.0, m) for m in memories]
    query_tokens = _tokenize_bm25(query)
    if not query_tokens:
        return [(0.0, m) for m in memories]
    corpus = corpus_memories if corpus_memories is not None else memories
    manifest, index_status = _ensure_bm25_seg_index(corpus)
    _BM25_PATH_CONTEXT.last_query_status = index_status
    if index_status == "cold_start" and len(corpus) > _BM25_MEMTABLE_MAX_DOCS:
        _trigger_bm25_background_build([dict(m) for m in corpus])
    elif index_status == "stale_served":
        mtotal = manifest.get("total_docs", 0)
        if mtotal > 0 and len(corpus) > mtotal * 2 and len(corpus) > _BM25_MEMTABLE_MAX_DOCS:
            _trigger_bm25_background_build(corpus)
    idf_map = manifest.get("idf_map", {})
    avg_dl = manifest.get("avg_dl", 1.0)

    # A query filter is a view over the corpus, not an incremental corpus write.
    # Score current text against the manifest IDF read-only. The segment files
    # are forward-document caches; reopening all of them for a filtered view is
    # slower and creates allocator churn in the long-lived P3 process.
    if corpus_memories is not None:
        if not idf_map and len(memories) <= _BM25_MEMTABLE_MAX_DOCS:
            transient = _build_memtable_segment(memories)
            idf_map = transient.get("idf_map", {})
            avg_dl = transient.get("avg_dl", 1.0)
        scored = [
            (_bm25_score_single(memory, query_tokens, idf_map, avg_dl, k1, b), memory)
            for memory in memories
        ]
        if scored:
            max_score = max(score for score, _memory in scored)
            if max_score > 0:
                scored = [(score / max_score, memory) for score, memory in scored]
            else:
                # An all-zero auxiliary leg must not let source-file order
                # overturn decision/lifecycle ranking during RRF fusion.
                scored = [(rank_memory(memory, query), memory) for memory in memories]
        scored.sort(key=lambda item: -item[0])
        return scored

    seg_exp_id_index = {}
    for si in manifest.get("segments", []):
        seg = _load_segment(si["id"])
        if seg:
            for eid, local_idx in seg.get("exp_id_index", {}).items():
                seg_exp_id_index[eid] = (si["id"], local_idx)
    main = []
    tail = []
    for m in memories:
        eid = str(m.get("exp_id") or "")
        entry = seg_exp_id_index.get(eid)
        if entry:
            seg_id, local_idx = entry
            seg = _load_segment(seg_id)
            if seg and local_idx < len(seg["doc_tf"]):
                score = _bm25_score_from_cache(
                    query_tokens, idf_map, avg_dl,
                    seg["doc_tf"][local_idx], seg["doc_len"][local_idx], k1, b,
                )
                main.append((score, m))
                continue
        tail.append(m)
    memtable_ids = _memtable_exp_id_set()
    new_docs = [m for m in tail if str(m.get("exp_id") or "") not in memtable_ids]
    if new_docs:
        _memtable_insert(new_docs)
    did_flush = False
    if _BM25_MEMTABLE["doc_count"] >= _BM25_MEMTABLE_FLUSH_THRESHOLD:
        _flush_memtable_to_main_index(_bm25_corpus_signature(memories))
        did_flush = True
    if did_flush:
        manifest = _load_manifest() or manifest
        idf_map = manifest.get("idf_map", {})
        avg_dl = manifest.get("avg_dl", 1.0)
        seg_exp_id_index = {}
        for si in manifest.get("segments", []):
            seg = _load_segment(si["id"])
            if seg:
                for eid, local_idx in seg.get("exp_id_index", {}).items():
                    seg_exp_id_index[eid] = (si["id"], local_idx)
        scored_eids = {str(m.get("exp_id") or "") for _, m in main}
        for m in tail:
            eid = str(m.get("exp_id") or "")
            if eid in scored_eids:
                continue
            entry = seg_exp_id_index.get(eid)
            if entry:
                seg_id, local_idx = entry
                seg = _load_segment(seg_id)
                if seg and local_idx < len(seg["doc_tf"]):
                    score = _bm25_score_from_cache(
                        query_tokens, idf_map, avg_dl,
                        seg["doc_tf"][local_idx], seg["doc_len"][local_idx], k1, b,
                    )
                    main.append((score, m))
                    continue
            main.append((0.0, m))
        results = list(main)
        if results:
            max_score = max(s for s, _ in results)
            if max_score > 0:
                results = [(s / max_score, m) for s, m in results]
        results.sort(key=lambda x: -x[0])
        return results
    mt_idf, mt_avg_dl = _compute_memtable_idf()
    mt_scored_eids = set()
    if mt_idf:
        with _BM25_MEMTABLE_LOCK:
            segments_snapshot = list(_BM25_MEMTABLE["segments"])
        for seg in segments_snapshot:
            for eid, local_idx in seg.get("exp_id_index", {}).items():
                mt_scored_eids.add(eid)
                if eid not in seg_exp_id_index and local_idx < len(seg["doc_tf"]):
                    score = _bm25_score_from_cache(
                        query_tokens, mt_idf, mt_avg_dl,
                        seg["doc_tf"][local_idx], seg["doc_len"][local_idx], k1, b,
                    )
                    for m in memories:
                        if str(m.get("exp_id") or "") == eid:
                            main.append((score, m))
                            break
    results = list(main)
    scored_eids = {str(m.get("exp_id") or "") for _, m in results}
    for m in memories:
        if str(m.get("exp_id") or "") not in scored_eids:
            results.append((0.0, m))
    if results:
        max_score = max(s for s, _ in results)
        if max_score > 0:
            results = [(s / max_score, m) for s, m in results]
    results.sort(key=lambda x: -x[0])
    return results





# ─── RRF (Reciprocal Rank Fusion) ──────────────────────────

def _rrf_fuse(ranked_lists, k=60):
    """Fuse multiple ranked lists using Reciprocal Rank Fusion.

    Args:
        ranked_lists: list of lists, each containing (score, memory) tuples sorted by score desc.
        k: RRF constant (default 60, standard value).

    Returns:
        List of (rrf_score, memory) tuples sorted by rrf_score desc.
    """
    # Use exp_id as key for dedup
    rrf_scores = {}
    memory_by_id = {}

    for ranked in ranked_lists:
        for rank, (score, m) in enumerate(ranked):
            mid = m.get("exp_id") or m.get("summary", "")[:50]
            if mid not in rrf_scores:
                rrf_scores[mid] = 0.0
                memory_by_id[mid] = m
            elif isinstance(m, dict) and m.get("_fts5"):
                merged = dict(memory_by_id[mid])
                merged["_fts5"] = m["_fts5"]
                memory_by_id[mid] = merged
            rrf_scores[mid] += 1.0 / (k + rank + 1)

    results = [(rrf_scores[mid], memory_by_id[mid]) for mid in rrf_scores]
    results.sort(key=lambda x: -x[0])
    return results


def _is_decision_focus_query(query):
    q = str(query or "").strip().lower()
    if not q:
        return False
    return any(term in q for term in (
        "定论", "结论", "边界", "纠偏", "拍死", "拍板", "不要", "不能",
        "不该", "不是", "定位", "原则", "decision", "boundary", "correction",
    ))


def _decision_focus_boost(memory, query):
    if not _is_decision_focus_query(query):
        return 0.0
    text = f"{memory.get('summary', '')} {memory.get('detail', '')}".lower()
    boost = 0.0
    if (memory.get("_type") or memory.get("type")) in ("preference_memory", "error_memory"):
        boost += 0.08
    if any(term in text for term in ("定论", "结论", "边界", "纠偏", "拍死", "不要", "不能", "不该", "不是", "定位", "原则")):
        boost += 0.16
    if any(term in text for term in ("只读模型事实", "不写回平台", "不做模型中心", "不是模型中心", "不是“模型中心")):
        boost += 0.12
    if any(term in text for term in (
        "原始定论本身", "原始结论本身", "我刚刚说我要查", "正在查",
        "继续查", "二手排查", "二手记录", "没命中", "有没有成为可召回",
    )):
        boost -= 0.32
    if any(term in text for term in (
        "live 排序", "排序已经改善", "第一条变成", "本机服务验证",
        "同步本机服务", "9851", "验证 9851", "这次查询", "召回请求",
        "跑全组测试", "服务验证", "验证流水",
    )):
        boost -= 0.48
    return boost


def rank_memory(memory, query):
    """Internal ranking score.

    Confidence stays bounded for callers, but decision-focused queries need
    stronger tie-breaking so durable conclusions beat fresh meta chatter.
    """
    return score_memory(memory, query) + _decision_focus_boost(memory, query)


def score_memory(memory, query):
    """计算 relevance score。

    J5 混合 Ranking：查询相关性仍是排序底座，lifecycle 只做增强/降权。
    不能让无 overlay 的 _adjusted_score 抹平“Time Library/项目”等查询命中。
    """
    if query:
        base_score = _keyword_score(memory, query)
        lifecycle = memory.get("_lifecycle", {})
        freshness_score = lifecycle.get("freshness_score", 1.0) if isinstance(lifecycle, dict) else 1.0
        try:
            freshness_score = float(freshness_score)
        except Exception:
            freshness_score = 1.0
        lifecycle_boost = 0.0
        status = lifecycle.get("status", "") if isinstance(lifecycle, dict) else ""
        if status == "active":
            lifecycle_boost = 0.15
        elif status == "historical":
            lifecycle_boost = -0.1
        elif status in ("superseded", "deprecated"):
            lifecycle_boost = -0.25
        return max(0.0, min(1.0, base_score * freshness_score + lifecycle_boost))

    # J5: 无查询时沿用 lifecycle 增强分数
    if "_adjusted_score" in memory:
        return memory["_adjusted_score"]

    return _keyword_score(memory, query)


def _is_project_status_focus_query(query):
    q = str(query or "").strip().lower()
    if not q:
        return False
    has_project_name = "Time Library" in q or "memcore" in q
    has_hermes_skill_status_marker = any(
        term in q
        for term in (
            "hermes-skill-generation-probe",
            "hermes skill generation",
            "skill generation probe",
            "skill artifact",
            "skill-artifact",
            "skill_artifact",
            "zhiyi-recall-check",
            "probe_only",
            "probe-only",
            "probe only",
            "原生 skill",
            "生成skill",
            "生成 skill",
            "探针",
            "技能探针",
            "skill 探针",
        )
    )
    if has_hermes_skill_status_marker:
        return True
    has_progress_marker = bool(re.search(r"\bb\d+\b", q, re.IGNORECASE)) and any(
        term in q
        for term in (
            "openclaw", "hermes", "native feedback", "长工作流", "验收",
            "整体 pass", "不能宣称", "当前状态", "当前进展", "进展",
        )
    )
    if not has_project_name and not has_progress_marker:
        return False
    if re.search(r"\bb\d+\b", q, re.IGNORECASE):
        return True
    for term in (
        "project status", "latest", "当前状态", "当前进展", "进展断点",
        "下一步", "接手", "质量缺口", "质量", "进度",
    ):
        if term in q:
            return True
    return False


def _is_project_status_memory(memory):
    return (memory.get("type") or memory.get("_type")) == "time_library_project_status"


def _focus_project_status_matches(matched, query):
    """Keep current project-state handoff answers from being diluted by old memories."""
    if not _is_project_status_focus_query(query):
        return matched
    project_status_matches = [
        m for m in matched
        if _is_project_status_memory(m)
    ]
    if not project_status_matches:
        return matched
    return project_status_matches


def _focus_project_status_scored(scored, query):
    if not _is_project_status_focus_query(query):
        return scored
    project_status_scored = [
        item for item in scored
        if _is_project_status_memory(item[1])
    ]
    if not project_status_scored:
        return scored
    return project_status_scored


def format_memory(m, query):
    """格式化单条 memory 用于输出。

    保留 _lifecycle 和 _adjusted_score 字段供下游（p4_inject / zhiyi_gateway）使用。
    """
    # Try both keys: source_refs (LanceDB) and _source_refs (zhiyi JSONL)
    sr = m.get("source_refs") or m.get("_source_refs") or {}
    # If source_refs is a string (serialized), parse it
    if isinstance(sr, str):
        try:
            sr = json.loads(sr)
        except:
            sr = {}
    confidence = score_memory(m, query)
    # 生成 injectable_context
    summary = m.get("summary", "")
    detail = m.get("detail", "")
    injectable = f"{summary} {detail}".strip()
    result = {
        "type": m["_type"],
        "exp_id": m.get("exp_id", ""),
        "scope": m.get("scope", ""),
        "summary": summary,
        "detail": detail,
        "reason": f"命中关键词: {query}" if query else "历史经验",
        "confidence": round(confidence, 2),
        "source_refs": sr,
        "injectable_context": injectable,
    }
    # J2-J5: 传递 lifecycle overlay 信息
    if "_lifecycle" in m:
        result["_lifecycle"] = m["_lifecycle"]
    if "_adjusted_score" in m:
        result["_adjusted_score"] = m["_adjusted_score"]
    if "_xingce" in m:
        result["_xingce"] = m["_xingce"]
    if "_fts5" in m:
        # Response-time ranking telemetry only; attach_archive_card below must
        # not fold this into the durable archive card.
        result["_fts5"] = m["_fts5"]
    if "_project_status" in m:
        result["_project_status"] = m["_project_status"]
    result = attach_archive_card(result)
    return result

def should_inject(memory, threshold=0.7):
    """判断是否建议注入"""
    return memory.get("confidence", 0) >= threshold

# ─── API server ────────────────────────────────────

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

MEMORIES_CACHE = None
CACHE_TTL = 60  # seconds
CACHE_TIME = {"ts": 0}
MEMORIES_CACHE_SIGNATURE = None
_MEMORY_LAST_SERVED_SIGNATURE = None
_MEMORY_RELOAD_THREAD = None
_MEMORY_CACHE_STATUS = "cold_load"
_RECENT_DELTA_MAX_DOCS = int(os.environ.get("MEMCORE_RECENT_DELTA_MAX_DOCS") or "128")
_RECENT_DELTA_MAX_BYTES = int(os.environ.get("MEMCORE_RECENT_DELTA_MAX_BYTES") or str(2 * 1024 * 1024))
_RECENT_DELTA_STATUS = {
    "applied": False,
    "reason": "not_checked",
    "doc_count": 0,
    "truncated": False,
    "source_files": [],
    "bytes_read": 0,
}


def _memories_source_signature():
    zhiyi_path = _zhiyi_path_for_runtime()
    paths = [
        os.path.join(zhiyi_path, ftype, f"{ftype}.jsonl")
        for ftype in ["preference_memory", "case_memory", "error_memory"]
    ]
    paths.append(
        os.path.join(
            _project_status_root(),
            "output",
            "time_library_project_status",
            "latest.json",
        )
    )
    paths.append(
        os.path.join(
            _project_status_root(),
            "output",
            "hermes_native_learning",
            "skill_artifact_status",
            "latest.json",
        )
    )
    xingce_root = _xingce_project_root()
    paths.extend(sorted(glob.glob(os.path.join(
        xingce_root,
        "output",
        "xingce_work_experience",
        "candidates",
        "xingce-*-candidate.json",
    ))))
    paths.extend(sorted(glob.glob(os.path.join(
        xingce_root,
        "output",
        "xingce_work_experience",
        "actions",
        "*.jsonl",
    ))))
    return _file_signature(paths)


def _memory_signature_size_map(signature):
    result = {}
    if not isinstance(signature, tuple):
        return result
    for entry in signature:
        if not isinstance(entry, tuple) or len(entry) < 3:
            continue
        path, _mtime_ns, size = entry[:3]
        if isinstance(size, int):
            result[path] = size
    return result


def _zero_size_signature_for_current_paths(signature):
    zeroed = []
    if not isinstance(signature, tuple):
        return tuple()
    for entry in signature:
        if not isinstance(entry, tuple) or len(entry) < 3:
            continue
        path, _mtime_ns, size = entry[:3]
        if isinstance(size, int):
            zeroed.append((path, None, 0))
    return tuple(zeroed)


def _recent_delta_file_specs():
    zhiyi_path = _zhiyi_path_for_runtime()
    return [
        (
            ftype,
            os.path.join(zhiyi_path, ftype, f"{ftype}.jsonl"),
        )
        for ftype in ["preference_memory", "case_memory", "error_memory"]
    ]


def _normalize_zhiyi_jsonl_record(record, ftype):
    r = dict(record)
    r["_type"] = ftype
    try:
        r["_source_refs"] = json.loads(r.get("source_refs", "{}"))
    except Exception:
        r["_source_refs"] = {}
    return attach_archive_card(_normalize_memory_record_node(r))


def _memory_dedupe_key(memory):
    exp_id = str(memory.get("exp_id") or "").strip()
    if exp_id:
        return ("exp_id", exp_id)
    evidence_hash = str(memory.get("evidence_hash") or "").strip()
    if evidence_hash:
        return ("evidence_hash", evidence_hash)
    sr = _source_refs_for_filter(memory)
    source_path = str(sr.get("source_path") or "").strip()
    raw_offset = str(sr.get("raw_offset") or sr.get("source_offset") or "").strip()
    if source_path or raw_offset:
        return ("source_ref", source_path, raw_offset)
    return ("text", str(memory.get("summary") or "")[:120], str(memory.get("detail") or "")[:120])


def _dedupe_memories_preserve_delta(base_memories, delta_memories):
    merged = []
    index_by_key = {}
    replaced = 0
    added = 0

    for memory in base_memories or []:
        key = _memory_dedupe_key(memory)
        if key in index_by_key:
            continue
        index_by_key[key] = len(merged)
        merged.append(memory)

    for memory in delta_memories or []:
        key = _memory_dedupe_key(memory)
        if key in index_by_key:
            idx = index_by_key[key]
            old_version = merged[idx].get("lifecycle_version", 1) or 1
            new_version = memory.get("lifecycle_version", 1) or 1
            if new_version >= old_version:
                merged[idx] = memory
                replaced += 1
            continue
        index_by_key[key] = len(merged)
        merged.append(memory)
        added += 1
    return merged, {"added": added, "replaced": replaced}


def _read_recent_delta_records(previous_signature, current_signature):
    """Read only bounded JSONL tail appended since the last served cache.

    This is the attempt-4 fast path: serve a tiny append delta while the full
    cache refresh happens in the background. It deliberately ignores shrink or
    unknown baselines so it cannot become an unbounded tail overlay.
    """
    previous_sizes = _memory_signature_size_map(previous_signature)
    current_sizes = _memory_signature_size_map(current_signature)
    records = []
    source_files = []
    bytes_read = 0
    truncated = False
    remaining_bytes = max(0, _RECENT_DELTA_MAX_BYTES)

    for ftype, path in _recent_delta_file_specs():
        old_size = previous_sizes.get(path)
        new_size = current_sizes.get(path)
        if not isinstance(old_size, int) or not isinstance(new_size, int):
            continue
        if new_size <= old_size:
            continue
        if remaining_bytes <= 0:
            truncated = True
            break

        available = new_size - old_size
        to_read = min(available, remaining_bytes)
        start = new_size - to_read
        if start > old_size:
            truncated = True
        else:
            start = old_size
            to_read = available

        try:
            with open(path, "rb") as f:
                f.seek(start)
                if start > old_size:
                    f.readline()
                data = f.read(to_read)
        except Exception:
            continue

        bytes_read += len(data)
        remaining_bytes -= len(data)
        source_files.append(path)
        for raw_line in data.decode("utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            try:
                records.append(_normalize_zhiyi_jsonl_record(rec, ftype))
            except Exception:
                continue

    if len(records) > _RECENT_DELTA_MAX_DOCS:
        records = records[-_RECENT_DELTA_MAX_DOCS:]
        truncated = True

    return records, {
        "source_files": source_files,
        "bytes_read": bytes_read,
        "truncated": truncated,
    }


def _merge_recent_delta_memories(base_memories):
    global _RECENT_DELTA_STATUS
    current_signature = _memories_source_signature()
    previous_signature = _MEMORY_LAST_SERVED_SIGNATURE or MEMORIES_CACHE_SIGNATURE
    if not previous_signature or current_signature == previous_signature:
        _RECENT_DELTA_STATUS = {
            "applied": False,
            "reason": "no_source_change",
            "doc_count": 0,
            "truncated": False,
            "source_files": [],
            "bytes_read": 0,
            "full_refresh_waited": False,
        }
        return base_memories, dict(_RECENT_DELTA_STATUS)

    delta_memories, read_info = _read_recent_delta_records(previous_signature, current_signature)
    if not delta_memories:
        _RECENT_DELTA_STATUS = {
            "applied": False,
            "reason": "no_bounded_append_delta",
            "doc_count": 0,
            "truncated": bool(read_info.get("truncated")),
            "source_files": read_info.get("source_files", []),
            "bytes_read": read_info.get("bytes_read", 0),
            "full_refresh_waited": False,
        }
        return base_memories, dict(_RECENT_DELTA_STATUS)

    merged, merge_info = _dedupe_memories_preserve_delta(base_memories, delta_memories)
    _RECENT_DELTA_STATUS = {
        "applied": True,
        "reason": "bounded_append_delta_served",
        "doc_count": len(delta_memories),
        "merged_added": merge_info.get("added", 0),
        "merged_replaced": merge_info.get("replaced", 0),
        "truncated": bool(read_info.get("truncated")),
        "max_docs": _RECENT_DELTA_MAX_DOCS,
        "max_bytes": _RECENT_DELTA_MAX_BYTES,
        "source_files": read_info.get("source_files", []),
        "bytes_read": read_info.get("bytes_read", 0),
        "full_refresh_waited": False,
    }
    return merged, dict(_RECENT_DELTA_STATUS)


def _default_recent_delta_matches(
    *,
    query,
    top_k,
    threshold,
    type_filter,
    scope_filter,
    source_system_filter,
    computer_name_filter,
    session_id_filter,
    canonical_window_id_filter,
    request_scope,
):
    """Return bounded recent append matches for the default recall path.

    The vector index is not a freshness proof: new zhiyi JSONL lines can be
    visible in source storage before the vector table is rebuilt.  This helper
    checks only the bounded append delta and lets the default recall path serve
    exact near-write hits without enabling the explicit FTS5 leg.
    """
    status = {
        "applied": False,
        "reason": "not_checked",
        "doc_count": 0,
        "truncated": False,
        "source_files": [],
        "bytes_read": 0,
        "full_refresh_waited": False,
    }
    if not str(query or "").strip():
        status["reason"] = "empty_query"
        return [], status

    global _MEMORY_RELOAD_THREAD, _MEMORY_CACHE_STATUS
    previous_signature = _MEMORY_LAST_SERVED_SIGNATURE or MEMORIES_CACHE_SIGNATURE
    current_signature = _memories_source_signature()
    cold_tail = False
    if not previous_signature:
        previous_signature = _zero_size_signature_for_current_paths(current_signature)
        cold_tail = True
        status["cold_start_tail"] = True
    if not previous_signature:
        status["reason"] = "no_recent_delta_baseline"
        return [], status
    if current_signature == previous_signature and not cold_tail:
        status["reason"] = "no_source_change"
        return [], status

    if cold_tail:
        if _MEMORY_RELOAD_THREAD is None:
            _MEMORY_CACHE_STATUS = "refresh_pending"
            _MEMORY_RELOAD_THREAD = threading.Thread(
                target=_memory_background_reload,
                args=(current_signature,),
                daemon=True,
            )
            _MEMORY_RELOAD_THREAD.start()
    else:
        # Trigger the ordinary background reload so the bounded overlay is only a
        # short-lived bridge, not a replacement for the full memory cache.
        try:
            get_memories()
        except Exception:
            pass

    delta_memories, read_info = _read_recent_delta_records(previous_signature, current_signature)
    status.update({
        "doc_count": len(delta_memories),
        "truncated": bool(read_info.get("truncated")),
        "source_files": read_info.get("source_files", []),
        "bytes_read": read_info.get("bytes_read", 0),
        "cold_start_tail": cold_tail,
    })
    if not delta_memories:
        status["reason"] = "no_bounded_append_delta"
        return [], status

    filtered = filter_memories(
        delta_memories,
        type_filter=type_filter,
        scope_filter=scope_filter,
        query=query,
        source_system_filter=source_system_filter,
        computer_name_filter=computer_name_filter,
        session_id_filter=session_id_filter,
        canonical_window_id_filter=canonical_window_id_filter,
    )
    filtered = [m for m in filtered if not _is_noise_memory(m)]
    if _LIFECYCLE_CACHE is None:
        status["lifecycle_overlay_skipped"] = "cache_cold_recent_delta_fast_path"
    else:
        filtered = _apply_lifecycle_overlay(filtered)

    scored = sorted(
        [(rank_memory(m, query), m) for m in filtered],
        key=lambda x: -x[0],
    )
    matched = [format_memory(m, query) for _score, m in scored[: max(top_k, 1) * 3]]
    if SCOPE_ENFORCEMENT_AVAILABLE and scope_filter:
        matched = _se_filter_by_scope(matched, request_scope)
    matched = matched[:top_k]
    for m in matched:
        m["confidence"] = round(m.get("confidence", 0), 2)
        m["should_inject"] = m.get("confidence", 0) >= threshold
        lifecycle = m.get("_lifecycle", {})
        if lifecycle.get("inject_policy") == "never":
            m["should_inject"] = False
        m.update(attach_archive_card(m))
        m["matched_by"] = "recent_delta"
        m["rank_reason"] = "bounded_recent_delta_default_recall"

    status["applied"] = bool(matched)
    status["reason"] = (
        "bounded_recent_tail_default_recall_hit"
        if cold_tail and matched
        else "bounded_append_delta_default_recall_hit"
        if matched
        else "bounded_append_delta_no_query_hit"
    )
    return matched, status


def _merge_formatted_matches_preserve_first(primary, secondary, top_k):
    merged = []
    seen = set()
    for item in list(primary or []) + list(secondary or []):
        key = (
            str(item.get("exp_id") or ""),
            str(item.get("summary") or "")[:120],
            str(item.get("detail") or "")[:120],
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= top_k:
            break
    return merged

def _is_noise_memory(m):
    """J3A-G3 + J1: 噪音记录检测（Hard Block）

    检测维度：
    1. 关键词：injected_context / bootstrap_context / SOUL.md 等
    2. 溯源缺失：source_refs 为空或 source_path 不存在

    Returns: True if record is noise (should be blocked)
    """
    if _is_project_status_memory(m):
        return False

    # ── 噪音关键词检测 ──
    NOISE_KEYWORDS = [
        "injected_context", "system_prompt", "bootstrap_context",
        "taskbook_context", "panel_context", "payload_context",
        "SOUL.md", "AGENTS.md", "SKILL.md",
        # J3A-Gate-Closure G3: compaction shadow upgrade
        "compaction", "context_compression", "compressed_context", "memory_compaction",
    ]
    text = (m.get("summary", "") + " " + m.get("detail", "")).lower()
    for kw in NOISE_KEYWORDS:
        if kw.lower() in text:
            return True
    # ── 无 source_refs 检测 ──
    # 兼容两种 key 和两种格式：_source_refs（dict）/ source_refs（dict 或 JSON字符串）
    sr_raw = m.get("_source_refs") or m.get("source_refs") or {}
    if isinstance(sr_raw, str):
        try:
            sr = json.loads(sr_raw)
        except:
            sr = {}
    else:
        sr = sr_raw or {}
    if not sr or not sr.get("source_path", ""):
        return True
    # source_path 文件存在性检查已移除（J3A-Gate-Closure）
    # 原因：LanceDB 存储的 source_path 引用了大量已不存在的文件，
    # 会导致全部 LanceDB 结果被过滤为噪音，造成 G4 recall 回归。
    # 文件不存在检测应由 lifecycle 管理层处理，不在噪音层过滤。
    return False


def get_lifecycle_active_view():
    """J1: Lifecycle Active View — 返回所有活跃（active）记录。

    从 lifecycle.jsonl 读取，返回 conflict_decision=active 的记录。
    用于 recall path 统一 lifecycle gate 和 audit 报告。
    """
    overlay = _get_lifecycle_overlay()
    active_records = []
    for exp_id, lo in overlay.items():
        if lo.get("conflict_decision") == "active":
            active_records.append({
                "exp_id": exp_id,
                "status": lo.get("status", "active"),
                "conflict_decision": "active",
                "scope": lo.get("scope", ""),
                "summary": lo.get("summary", ""),
                "detail": lo.get("detail", ""),
                "memory_id": lo.get("memory_id", ""),
                "canonical_window_id": lo.get("canonical_window_id", ""),
                "source_system": lo.get("source_system", ""),
                "effective_from": lo.get("effective_from", ""),
                "lifecycle_version": lo.get("lifecycle_version", 1),
            })
    return active_records


def check_supersession_chain():
    """J1: Supersession Chain 检查。

    验证 lifecycle.jsonl 中的 supersedes / superseded_by 字段。
    当前状态：所有 supersedes / superseded_by 均为空。

    Returns: (is_valid, issues)
    """
    issues = []
    overlay = _get_lifecycle_overlay()
    supersedes_graph = {}
    for exp_id, lo in overlay.items():
        supersedes = lo.get("supersedes", []) or []
        if supersedes:
            supersedes_graph[exp_id] = set(supersedes)

    def has_cycle(node, visited, rec_stack):
        visited.add(node)
        rec_stack.add(node)
        for neighbor in supersedes_graph.get(node, []):
            if neighbor not in visited:
                if has_cycle(neighbor, visited, rec_stack):
                    return True
            elif neighbor in rec_stack:
                issues.append(f"Cycle: {node} -> {neighbor}")
                return True
        rec_stack.remove(node)
        return False

    visited = set()
    for node in supersedes_graph:
        if node not in visited:
            has_cycle(node, visited, set())

    all_exp_ids = set(overlay.keys())
    for exp_id, supersedes_list in supersedes_graph.items():
        for target in supersedes_list:
            if target not in all_exp_ids:
                issues.append(f"Lost reference: {exp_id} supersedes non-existent {target}")

    return (len(issues) == 0, issues)



_MEMORY_RELOAD_DELAY = 1.0  # seconds — defer reload to let foreground query finish before GIL contention


def _deferred_memory_reload(sig):
    """Sleep briefly then reload memories. Runs in background thread."""
    import time as _time
    _time.sleep(_MEMORY_RELOAD_DELAY)
    _memory_background_reload(sig)


def _memory_background_reload(sig):
    """Background thread: reload memories and update cache."""
    global MEMORIES_CACHE, CACHE_TIME, MEMORIES_CACHE_SIGNATURE, _MEMORY_LAST_SERVED_SIGNATURE, _MEMORY_RELOAD_THREAD, _MEMORY_CACHE_STATUS
    try:
        new_memories = load_memories()
        MEMORIES_CACHE = new_memories
        CACHE_TIME["ts"] = datetime.now(timezone.utc).timestamp()
        MEMORIES_CACHE_SIGNATURE = sig
        expected_source_signature = _fts5_bind_source_signature(MEMORIES_CACHE, sig)
        _MEMORY_LAST_SERVED_SIGNATURE = sig
        _MEMORY_CACHE_STATUS = "refresh_completed"
        try:
            fts5_state = _fts5_status()
            if (
                (fts5_state.get("exists") or fts5_state.get("fts5_enabled"))
                and fts5_state.get("source_signature") != expected_source_signature
            ):
                _schedule_fts5_refresh(
                    MEMORIES_CACHE,
                    _fts5_index_path(),
                    "memory_reload_corpus_change",
                    expected_source_signature=expected_source_signature,
                )
        except Exception:
            pass
    except Exception:
        _MEMORY_CACHE_STATUS = "refresh_failed"
    finally:
        _MEMORY_RELOAD_THREAD = None


def get_memories():
    """带 TTL 和文件签名的缓存，支持 stale-serve。

    当 MEMORIES_CACHE 已存在但 source signature 变化时，先返回旧缓存（stale_served），
    并触发后台 memory reload（deferred，不在前台立即抢占 GIL）。
    无缓存首次启动仍同步 cold load。
    TTL 到期但 source signature 未变时，重置 TTL 不重载。
    """
    now = datetime.now(timezone.utc).timestamp()
    global MEMORIES_CACHE, CACHE_TIME, MEMORIES_CACHE_SIGNATURE, _MEMORY_LAST_SERVED_SIGNATURE, _MEMORY_RELOAD_THREAD, _MEMORY_CACHE_STATUS
    signature = _memories_source_signature()

    # 无缓存：首次 cold load（同步）
    if MEMORIES_CACHE is None:
        _MEMORY_CACHE_STATUS = "cold_load"
        MEMORIES_CACHE = load_memories()
        CACHE_TIME["ts"] = now
        MEMORIES_CACHE_SIGNATURE = signature
        _fts5_bind_source_signature(MEMORIES_CACHE, signature)
        _MEMORY_LAST_SERVED_SIGNATURE = signature
        return MEMORIES_CACHE

    # 签名命中 + TTL 未过期：cache_hit
    if signature == MEMORIES_CACHE_SIGNATURE and (now - CACHE_TIME["ts"]) <= CACHE_TTL:
        _MEMORY_CACHE_STATUS = "cache_hit"
        _MEMORY_LAST_SERVED_SIGNATURE = MEMORIES_CACHE_SIGNATURE
        return MEMORIES_CACHE

    # TTL 过期但签名未变：重置 TTL，不重载
    if signature == MEMORIES_CACHE_SIGNATURE and (now - CACHE_TIME["ts"]) > CACHE_TTL:
        CACHE_TIME["ts"] = now
        _MEMORY_CACHE_STATUS = "cache_hit"
        _MEMORY_LAST_SERVED_SIGNATURE = MEMORIES_CACHE_SIGNATURE
        return MEMORIES_CACHE

    # 签名变化：stale serve + 后台 deferred reload
    if _MEMORY_RELOAD_THREAD is None:
        _MEMORY_CACHE_STATUS = "refresh_pending"
        _MEMORY_RELOAD_THREAD = threading.Thread(
            target=_deferred_memory_reload,
            args=(signature,),
            daemon=True,
        )
        _MEMORY_RELOAD_THREAD.start()
    else:
        _MEMORY_CACHE_STATUS = "stale_served"
    _MEMORY_LAST_SERVED_SIGNATURE = MEMORIES_CACHE_SIGNATURE
    return MEMORIES_CACHE

def _is_xingce_candidate_memory(m):
    return m.get("_type") == "xingce_work_experience_candidate" or bool(m.get("_xingce"))


def _cjk_bigrams(text):
    chars = re.findall(r"[\u4e00-\u9fff]", str(text or ""))
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def _xingce_candidate_search_text(memory):
    parts = [
        memory.get("summary", ""),
        memory.get("detail", ""),
        memory.get("verbatim_excerpt", ""),
        memory.get("work_scenario", ""),
        memory.get("action_strategy", ""),
        memory.get("applicable_scope", ""),
        memory.get("scope", ""),
    ]
    for key in (
        "observed_facts",
        "recommended_procedure",
        "avoid_conditions",
        "acceptance_checks",
        "verification_steps",
    ):
        values = memory.get(key, [])
        if isinstance(values, list):
            parts.extend(str(item) for item in values)
        elif values:
            parts.append(str(values))
    meta = memory.get("_xingce", {}) if isinstance(memory.get("_xingce"), dict) else {}
    parts.extend(str(meta.get(key, "")) for key in ("candidate_id", "candidate_type", "frontstage_surface"))
    return " ".join(str(part or "") for part in parts).lower()


def _xingce_candidate_query_score(memory, query):
    query_text = str(query or "").strip().lower()
    if not query_text:
        return 0.0
    text = _xingce_candidate_search_text(memory)
    if not text:
        return 0.0

    terms = [term for term in _query_terms(query_text) if len(term) >= 2]
    exact_hits = sum(1 for term in terms if term in text)
    query_bigrams = _cjk_bigrams(query_text)
    text_bigrams = _cjk_bigrams(text)
    cjk_overlap = len(query_bigrams & text_bigrams)

    if exact_hits == 0 and cjk_overlap < 2:
        return 0.0
    return min(1.0, 0.72 + exact_hits * 0.06 + cjk_overlap * 0.02)


def _supplement_xingce_candidates(matched, query, top_k, threshold=0.7):
    """Ensure xingce work-experience candidates loaded from file-based storage
    are present in recall results.  Vector/LanceDB search cannot find them and
    substring query filtering may also drop them.  Only candidates that match
    the current query are bridged, so the delivery fix does not pollute ordinary
    recall with every pending work-experience candidate."""
    candidates = _load_xingce_work_experience_candidate_memories()
    if not candidates:
        return matched
    existing_ids = {m.get("exp_id") for m in matched if m.get("exp_id")}
    xingce_extras = []
    for m in candidates:
        eid = m.get("exp_id", "")
        if not eid or eid in existing_ids:
            continue
        bridge_score = _xingce_candidate_query_score(m, query)
        if bridge_score <= 0:
            continue
        formatted = format_memory(m, query)
        formatted["matched_by"] = "xingce_candidate_bridge"
        formatted["confidence"] = max(float(formatted.get("confidence") or 0.0), round(bridge_score, 2))
        formatted["should_inject"] = formatted["confidence"] >= threshold
        xingce_extras.append(formatted)
    if xingce_extras:
        matched = sorted(
            matched + xingce_extras,
            key=lambda item: float(item.get("confidence") or 0.0),
            reverse=True,
        )[:top_k]
    return matched


def handle_recall(body):
    """处理 recall 请求。

    J2-J5 Runtime:
    - J2: load_memories 已做 exp_id 去重
    - J3: _apply_lifecycle_overlay 过滤掉 conflict_decision=superseded 的记录
    - J4: _apply_lifecycle_overlay 计算 freshness_score 并合并到 _adjusted_score
    - J5: score_memory 优先使用 _adjusted_score（J5 混合 ranking）
    - J6/J7: inject_policy=never 时 should_inject=False（在 format_memory 中处理）
    """
    query = body.get("query", "")
    scope_filter = body.get("scope_filter", "")
    type_filter = body.get("type_filter", [])
    top_k = body.get("top_k", 5)
    threshold = body.get("threshold", 0.7)
    recall_mode_explicit = "recall_mode" in body
    recall_mode = body.get("recall_mode", "vector")  # substring / vector
    source_system_filter = _normalize_source_filter(
        body.get("source_system_filter", body.get("source_system", ""))
    )
    computer_name_filter = str(body.get("computer_name_filter", body.get("computer_name", "")) or "").strip()
    session_id_filter = str(body.get("session_id_filter", body.get("session_id", "")) or "").strip()
    canonical_window_id_filter = str(
        body.get("canonical_window_id_filter", body.get("canonical_window_id", ""))
        or ""
    ).strip()

    # ─── 构造 scope dict for enforcement ────────────────────
    request_scope = _recall_request_scope(
        canonical_window_id_filter=canonical_window_id_filter,
        source_system_filter=source_system_filter,
        computer_name_filter=computer_name_filter,
        scope_filter=scope_filter,
    )

    # v2 向量召回
    if recall_mode == "vector" and query:
        if not recall_mode_explicit:
            recent_delta_matches, recent_delta_status = _default_recent_delta_matches(
                query=query,
                top_k=top_k,
                threshold=threshold,
                type_filter=type_filter,
                scope_filter=scope_filter,
                source_system_filter=source_system_filter,
                computer_name_filter=computer_name_filter,
                session_id_filter=session_id_filter,
                canonical_window_id_filter=canonical_window_id_filter,
                request_scope=request_scope,
            )
            if recent_delta_matches:
                _mem_refresh_pending = _MEMORY_RELOAD_THREAD is not None
                _bm25_refresh_pending = _BM25_REFRESH_THREAD is not None
                _any_refresh_pending = _mem_refresh_pending or _bm25_refresh_pending
                _refresh_status = "pending" if _any_refresh_pending else (
                    "completed"
                    if _MEMORY_CACHE_STATUS in ("cache_hit", "refresh_completed", "stale_served")
                    else "idle"
                )
                _bm25_stats = _bm25_corpus_stats()
                vector_status = vector_runtime_status(load_model=False)
                recent_delta_result = {
                    "total_matched": len(recent_delta_matches),
                    "returned": len(recent_delta_matches),
                    "mode": "vector_with_bounded_recent_delta",
                    "bm25_applied": False,
                    "bm25_index_status": "no_index",
                    "memory_cache_status": _MEMORY_CACHE_STATUS,
                    "refresh_status": _refresh_status,
                    "refresh_pending": _any_refresh_pending,
                    "freshness_boundary": "bounded_recent_delta",
                    "last_refresh_started_at": _bm25_stats.get("last_refresh_started_at"),
                    "last_refresh_completed_at": _bm25_stats.get("last_refresh_completed_at"),
                    "last_refresh_duration_seconds": _bm25_stats.get("last_refresh_duration_seconds"),
                    "refresh_trigger_count": _bm25_stats.get("refresh_trigger_count", 0),
                    "rrf_applied": False,
                    "recall_methods_used": ["recent_delta", "keyword"],
                    "recent_delta_applied": True,
                    "recent_delta_status": recent_delta_status,
                    "recent_delta_doc_count": int(recent_delta_status.get("doc_count") or 0),
                    "recent_delta_bounded": True,
                    "recent_delta_full_refresh_waited": bool(recent_delta_status.get("full_refresh_waited")),
                    "freshness_fast_path": "bounded_recent_delta",
                    "default_recall_freshness_covered": True,
                    "default_vector_freshness_covered": False,
                    "vector_search_deferred_for_recent_delta": True,
                    "_scope_enforced": SCOPE_ENFORCEMENT_AVAILABLE,
                    "_scope_used": request_scope,
                    "_source_system_filter": source_system_filter or "all",
                    "_memory_base_scope": "filtered" if source_system_filter else "shared",
                    "_agent_boundary": "isolated_per_window",
                    "vector_runtime_status": vector_status,
                    "matched_memories": recent_delta_matches,
                    "structure_analysis": {
                        "enabled": False,
                        "executed": False,
                        "reason": "skipped_recent_delta_fast_path",
                    },
                }
                return _finalize_recall_result(recent_delta_result, query, body, vector_status)

        vector_multiplier = 12 if (source_system_filter or computer_name_filter or session_id_filter or canonical_window_id_filter) else 3
        matched = vector_search_v2(query, top_k=top_k * vector_multiplier, scope_filter=scope_filter, type_filter=type_filter)
        vector_status = vector_runtime_status(load_model=False)
        vector_pre_filter_count = len(matched)
        if source_system_filter or computer_name_filter or session_id_filter or canonical_window_id_filter:
            matched = filter_memories(
                matched,
                source_system_filter=source_system_filter,
                computer_name_filter=computer_name_filter,
                session_id_filter=session_id_filter,
                canonical_window_id_filter=canonical_window_id_filter,
            )
        # J2-J5: 应用 lifecycle overlay
        matched = _apply_lifecycle_overlay(matched)
        # B5: 强制 scope 过滤
        if SCOPE_ENFORCEMENT_AVAILABLE and scope_filter:
            matched = _se_filter_by_scope(matched, request_scope)
        matched = matched[:top_k]
        for m in matched:
            m["confidence"] = round(score_memory(m, query), 2)
            # J6: 低置信拒答
            m["should_inject"] = (m.get("confidence", 0) >= threshold)
            # J7: inject_policy=never 强制不注入
            lifecycle = m.get("_lifecycle", {})
            if lifecycle.get("inject_policy") == "never":
                m["should_inject"] = False
            m.update(attach_archive_card(m))
        for m in matched:
            m["matched_by"] = "vector"
        _mem_refresh_pending = _MEMORY_RELOAD_THREAD is not None
        _bm25_refresh_pending = _BM25_REFRESH_THREAD is not None
        _any_refresh_pending = _mem_refresh_pending or _bm25_refresh_pending
        _refresh_status = "pending" if _any_refresh_pending else (
            "completed" if _MEMORY_CACHE_STATUS in ("cache_hit", "refresh_completed", "stale_served") else "idle"
        )
        _bm25_stats = _bm25_corpus_stats()
        vector_result = {
            "total_matched": len(matched),
            "returned": len(matched),
            "mode": "vector",
            "bm25_applied": False,
            "bm25_index_status": "no_index",
            "memory_cache_status": _MEMORY_CACHE_STATUS,
            "refresh_status": _refresh_status,
            "refresh_pending": _any_refresh_pending,
            "freshness_boundary": _memory_freshness_boundary(_MEMORY_CACHE_STATUS, _any_refresh_pending),
            "last_refresh_started_at": _bm25_stats.get("last_refresh_started_at"),
            "last_refresh_completed_at": _bm25_stats.get("last_refresh_completed_at"),
            "last_refresh_duration_seconds": _bm25_stats.get("last_refresh_duration_seconds"),
            "refresh_trigger_count": _bm25_stats.get("refresh_trigger_count", 0),
            "rrf_applied": False,
            "recall_methods_used": ["vector"],
            "_scope_enforced": SCOPE_ENFORCEMENT_AVAILABLE,
            "_scope_used": request_scope,
            "_source_system_filter": source_system_filter or "all",
            "_memory_base_scope": "filtered" if source_system_filter else "shared",
            "_agent_boundary": "isolated_per_window",
            "vector_runtime_status": vector_status,
            "matched_memories": matched,
        }
        recent_delta_matches = []
        recent_delta_status = {
            "applied": False,
            "reason": "not_checked",
            "doc_count": 0,
            "truncated": False,
            "source_files": [],
            "bytes_read": 0,
            "full_refresh_waited": False,
        }
        if query and not recall_mode_explicit:
            recent_delta_matches, recent_delta_status = _default_recent_delta_matches(
                query=query,
                top_k=top_k,
                threshold=threshold,
                type_filter=type_filter,
                scope_filter=scope_filter,
                source_system_filter=source_system_filter,
                computer_name_filter=computer_name_filter,
                session_id_filter=session_id_filter,
                canonical_window_id_filter=canonical_window_id_filter,
                request_scope=request_scope,
            )
            vector_result.update({
                "recent_delta_applied": bool(recent_delta_status.get("applied")),
                "recent_delta_status": recent_delta_status,
                "recent_delta_doc_count": int(recent_delta_status.get("doc_count") or 0),
                "recent_delta_bounded": True,
                "recent_delta_full_refresh_waited": bool(recent_delta_status.get("full_refresh_waited")),
                "freshness_fast_path": (
                    "bounded_recent_delta"
                    if recent_delta_status.get("applied")
                    else "base_cache"
                ),
                "default_recall_freshness_covered": bool(recent_delta_status.get("applied")),
                "default_vector_freshness_covered": False,
            })
        if recent_delta_matches:
            vector_result["matched_memories"] = _merge_formatted_matches_preserve_first(
                recent_delta_matches,
                vector_result.get("matched_memories", []),
                top_k,
            )
            vector_result["returned"] = len(vector_result["matched_memories"])
            vector_result["total_matched"] = max(
                int(vector_result.get("total_matched") or 0),
                len(vector_result["matched_memories"]),
            )
            vector_result["mode"] = "vector_with_bounded_recent_delta"
            vector_result["freshness_boundary"] = "bounded_recent_delta"
            vector_result["recall_methods_used"] = ["vector", "recent_delta", "keyword"]
            vector_result["structure_analysis"] = {
                "enabled": False,
                "executed": False,
                "reason": "skipped_recent_delta_fast_path",
            }
            return _finalize_recall_result(vector_result, query, body, vector_status)
        if matched and not recall_mode_explicit and _is_project_status_focus_query(query):
            project_status_matches = [
                m for m in matched
                if _is_project_status_memory(m)
            ]
            if project_status_matches:
                vector_result["matched_memories"] = project_status_matches[:top_k]
                vector_result["returned"] = len(vector_result["matched_memories"])
                vector_result["mode"] = "vector_focus_project_status"
                return _finalize_recall_result(vector_result, query, body, vector_status)
            fallback_body = dict(body)
            fallback_body["recall_mode"] = "substring"
            fallback_body["structure_analysis"] = {"enabled": False}
            fallback_body["enable_structure_analysis"] = False
            fallback_result = handle_recall(fallback_body)
            fallback_project_status = [
                m for m in fallback_result.get("matched_memories", [])
                if _is_project_status_memory(m)
            ]
            if fallback_project_status:
                fallback_result["mode"] = "vector_focus_project_status_substring"
                fallback_result["vector_result_project_status_missing"] = True
                fallback_result["vector_result"] = vector_result
                return _finalize_recall_result(fallback_result, query, body, vector_status)
        if matched:
            vector_result["matched_memories"] = _supplement_xingce_candidates(
                vector_result.get("matched_memories", []), query, top_k, threshold,
            )
            vector_result["returned"] = len(vector_result["matched_memories"])
            return _finalize_recall_result(vector_result, query, body, vector_status)
        if recall_mode_explicit and vector_status.get("ok"):
            vector_result["matched_memories"] = _supplement_xingce_candidates(
                vector_result.get("matched_memories", []), query, top_k, threshold,
            )
            vector_result["returned"] = len(vector_result["matched_memories"])
            return _finalize_recall_result(vector_result, query, body, vector_status)
        if (
            vector_pre_filter_count
            and (source_system_filter or computer_name_filter or session_id_filter or canonical_window_id_filter)
        ):
            vector_result["mode"] = "vector_filtered_empty"
            vector_result["vector_result_empty"] = True
            vector_result["vector_filter_empty"] = True
            vector_result["vector_pre_filter_count"] = vector_pre_filter_count
            vector_result["vector_degraded"] = False
            vector_result["vector_degradation_issues"] = []
            return _finalize_recall_result(vector_result, query, body, vector_status)
        fallback_body = dict(body)
        fallback_body["recall_mode"] = "substring"
        fallback_body["structure_analysis"] = {"enabled": False}
        fallback_body["enable_structure_analysis"] = False
        fallback_result = handle_recall(fallback_body)
        fallback_result["mode"] = "vector_assets_unavailable_fallback_fts5" if not vector_status.get("ok") else "vector_fallback_substring"
        fallback_result["vector_result_empty"] = True
        fallback_result["vector_runtime_status"] = vector_status
        fallback_result["vector_degraded"] = not bool(vector_status.get("ok"))
        fallback_result["vector_degradation_issues"] = vector_status.get("issues", [])
        fallback_result["vector_fallback_applied"] = True
        fallback_result["vector_fallback_backend"] = "FTS5+BM25"
        fallback_result["vector_result"] = vector_result
        return _finalize_recall_result(fallback_result, query, body, vector_status)

    # substring 召回
    recall_started = time.time()
    memories = get_memories()
    memories, recent_delta_status = _merge_recent_delta_memories(memories)
    fts5_enabled = _fts5_recall_enabled(body)
    fts5_status_info = {
        "enabled": fts5_enabled,
        "applied": False,
        "error": None,
        "matched_count": 0,
        "raw_matched_count": 0,
    }
    fts5_filtered = []
    fts5_used = False
    fts5_fusion = {
        "fts5_only_hits": 0,
        "fts5_keyword_overlap_hits": 0,
        "fusion_policy": "",
    }
    if fts5_enabled:
        fts5_candidates, fts5_status_info = _fts5_ordered_memories(memories, query, top_k)
        if fts5_candidates:
            fts5_filtered = filter_memories(
                fts5_candidates,
                type_filter=type_filter,
                scope_filter=scope_filter,
                query=None,
                source_system_filter=source_system_filter,
                computer_name_filter=computer_name_filter,
                session_id_filter=session_id_filter,
                canonical_window_id_filter=canonical_window_id_filter,
            )
    filtered = filter_memories(
        memories,
        type_filter=type_filter,
        scope_filter=scope_filter,
        query=query,
        source_system_filter=source_system_filter,
        computer_name_filter=computer_name_filter,
        session_id_filter=session_id_filter,
        canonical_window_id_filter=canonical_window_id_filter,
    )

    # J1 + J3A-G3: 噪音过滤（Hard Block）
    filtered = [m for m in filtered if not _is_noise_memory(m)]
    fts5_filtered = [m for m in fts5_filtered if not _is_noise_memory(m)]
    if fts5_enabled:
        raw_count = int(fts5_status_info.get("raw_matched_count") or fts5_status_info.get("matched_count") or 0)
        fts5_status_info["post_filter_matched_count"] = len(fts5_filtered)
        fts5_status_info["discarded_by_filter_count"] = max(0, raw_count - len(fts5_filtered))

    # J2-J5: 应用 lifecycle overlay（J3 过滤掉 superseded，J4/J5 增强分数）
    filtered = _apply_lifecycle_overlay(filtered)
    fts5_filtered = _apply_lifecycle_overlay(fts5_filtered) if fts5_filtered else []
    if fts5_enabled:
        raw_count = int(fts5_status_info.get("raw_matched_count") or fts5_status_info.get("matched_count") or 0)
        fts5_status_info["post_lifecycle_matched_count"] = len(fts5_filtered)
        fts5_status_info["discarded_by_filter_count"] = max(0, raw_count - len(fts5_filtered))

    # ─── BM25 scoring (always compute when query present) ───
    bm25_applied = False
    bm25_scored = []
    bm25_index_status = "no_index"
    if query and filtered:
        bm25_scored = _compute_bm25_scores(
            filtered,
            query,
            corpus_memories=memories,
        )
        bm25_applied = bool(bm25_scored)
        bm25_index_status = getattr(_BM25_PATH_CONTEXT, "last_query_status", "no_index")

    # 打分排序（使用 lifecycle 增强后的 _adjusted_score）
    keyword_scored = [(rank_memory(m, query), m) for m in filtered]
    keyword_scored.sort(key=lambda x: -x[0])

    # ─── RRF fusion: merge available legs ───
    rrf_applied = False
    ranked_lists = [keyword_scored]
    if bm25_applied and bm25_scored:
        ranked_lists.append(bm25_scored)
    if fts5_filtered:
        base_ids = {str(memory.get("exp_id") or "") for _, memory in (keyword_scored + bm25_scored)}
        fts5_scored = []
        fts5_only_hits = 0
        fts5_overlap_hits = 0
        for rank_index, memory in enumerate(fts5_filtered):
            exp_id = str(memory.get("exp_id") or "")
            if exp_id not in base_ids:
                fts5_only_hits += 1
                continue
            fts5_overlap_hits += 1
            memory = dict(memory)
            boost = 1.0 / (60.0 + rank_index)
            fts5_scored.append((boost, memory))
        if fts5_scored:
            fts5_used = True
            fts5_status_info["applied"] = True
            ranked_lists.append(fts5_scored)
        else:
            fts5_status_info["applied"] = False
        fts5_fusion = {
            "fts5_only_hits": fts5_only_hits,
            "fts5_keyword_overlap_hits": fts5_overlap_hits,
            "fusion_policy": "keyword_base_with_bounded_fts5_boost",
        }
    else:
        fts5_status_info["applied"] = False
    if len(ranked_lists) > 1 and query:
        fused = _rrf_fuse(ranked_lists, k=60)
        scored = fused
        rrf_applied = True
    else:
        scored = keyword_scored

    # top_k (预取更多用于 scope 过滤)
    # Current construction handoff queries must not lose project_status before
    # the later focus filter can see it.
    top_source = _focus_project_status_scored(scored, query)
    top = top_source[:top_k * 3]

    matched = [format_memory(m, query) for s, m in top]
    matched = _focus_project_status_matches(matched, query)
    # B5: 强制 scope 过滤
    if SCOPE_ENFORCEMENT_AVAILABLE and scope_filter:
        matched = _se_filter_by_scope(matched, request_scope)
    matched = matched[:top_k]
    for m in matched:
        m["confidence"] = round(m["confidence"], 2)
        # J6: 低置信拒答
        m["should_inject"] = (m.get("confidence", 0) >= threshold)
        # J7: inject_policy=never 强制不注入
        lifecycle = m.get("_lifecycle", {})
        if lifecycle.get("inject_policy") == "never":
            m["should_inject"] = False
        m.update(attach_archive_card(m))
        # 标记 matched_by（必须在 attach_archive_card 之后，否则被 library_card 覆盖）
        m["matched_by"] = "substring"
        if rrf_applied:
            m["matched_by"] = "rrf(keyword+bm25)" if not fts5_used else "rrf(keyword+bm25+fts5)"
        elif fts5_used:
            m["matched_by"] = "fts5_bm25"
        elif bm25_applied:
            m["matched_by"] = "bm25"
        if m.get("_fts5"):
            m["matched_by"] = "fts5_bm25"
            m["rank_reason"] = "sqlite_fts5_trigram_bm25"

    _mem_refresh_pending = _MEMORY_RELOAD_THREAD is not None
    _bm25_refresh_pending = _BM25_REFRESH_THREAD is not None
    _any_refresh_pending = _mem_refresh_pending or _bm25_refresh_pending
    _refresh_status = "pending" if _any_refresh_pending else (
        "completed" if _MEMORY_CACHE_STATUS in ("cache_hit", "refresh_completed", "stale_served") else "idle"
    )
    _bm25_stats = _bm25_corpus_stats()
    methods_used = ["keyword"]
    if bm25_applied:
        methods_used.append("bm25")
    if fts5_used:
        methods_used.append("fts5")
    if rrf_applied:
        methods_used.append("rrf")
    result = {
        "query": query,
        "total_matched": len(filtered),
        "returned": len(matched),
        "bm25_applied": bm25_applied,
        "bm25_index_status": bm25_index_status,
        "memory_cache_status": _MEMORY_CACHE_STATUS,
        "refresh_status": _refresh_status,
        "refresh_pending": _any_refresh_pending,
        "freshness_boundary": _memory_freshness_boundary(_MEMORY_CACHE_STATUS, _any_refresh_pending),
        "recent_delta_applied": bool(recent_delta_status.get("applied")),
        "recent_delta_status": recent_delta_status,
        "recent_delta_doc_count": int(recent_delta_status.get("doc_count") or 0),
        "recent_delta_bounded": True,
        "recent_delta_full_refresh_waited": bool(recent_delta_status.get("full_refresh_waited")),
        "freshness_fast_path": (
            "bounded_recent_delta"
            if recent_delta_status.get("applied")
            else "base_cache"
        ),
        "default_vector_freshness_covered": False,
        "last_refresh_started_at": _bm25_stats.get("last_refresh_started_at"),
        "last_refresh_completed_at": _bm25_stats.get("last_refresh_completed_at"),
        "last_refresh_duration_seconds": _bm25_stats.get("last_refresh_duration_seconds"),
        "refresh_trigger_count": _bm25_stats.get("refresh_trigger_count", 0),
        "rrf_applied": rrf_applied,
        "recall_methods_used": methods_used,
        "_scope_enforced": SCOPE_ENFORCEMENT_AVAILABLE,
        "_scope_used": request_scope,
        "_source_system_filter": source_system_filter or "all",
        "_memory_base_scope": "filtered" if source_system_filter else "shared",
        "_agent_boundary": "isolated_per_window",
        "matched_memories": matched,
    }
    if fts5_enabled:
        fts5_current = not bool(fts5_status_info.get("stale")) and not bool(fts5_status_info.get("error"))
        result.update({
            "fts5_applied": fts5_used,
            "fts5_status": dict(fts5_status_info, **fts5_fusion),
            "fts5_rank_reason": "sqlite_fts5_trigram_bm25" if fts5_used else "",
            "primary_recall_backend": "keyword+fts5" if fts5_used else "keyword",
            "ranking_owner": "keyword+fts5" if fts5_used and any(bool(item.get("_fts5")) for item in matched) else "keyword",
            "primary_recall_modes": ["substring", "fts5"] if fts5_used else ["substring"],
            "primary_recall_elapsed_seconds": round(time.time() - recall_started, 4),
            "primary_recall_items_count": len(matched),
            "freshness_boundary": "substring_fts5_partial_not_default_vector",
            "default_recall_freshness_covered": fts5_current,
        })
    if not fts5_used:
        result["matched_memories"] = _supplement_xingce_candidates(
            result.get("matched_memories", []), query, top_k, threshold,
        )
    result["returned"] = len(result["matched_memories"])
    return _finalize_recall_result(result, query, body)

def _health_payload(vector_probe=""):
    load_vector = vector_probe in ("1", "true", "load", "full", "warmup")
    vector_status = vector_runtime_status(load_model=load_vector)
    vector_warmup = {}
    if vector_probe == "warmup":
        if vector_status.get("expected") and vector_status.get("ok"):
            vector_warmup = _warmup_vector_engine()
            vector_status = vector_runtime_status(load_model=False)
        else:
            vector_warmup = {
                "enabled": True,
                "ok": False,
                "error": "vector_runtime_not_ready",
            }
    payload = {
        "status": "ok",
        "memory_count": len(get_memories()),
        "vector_recall": vector_status,
    }
    if vector_probe == "warmup":
        payload["vector_warmup"] = vector_warmup
    return payload


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # 静默

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            params = parse_qs(parsed.query)
            vector_probe = (params.get("vector") or [""])[0].lower()
            payload = _health_payload(vector_probe)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/recall":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = handle_recall(body)
            # GAP-3: Emit RIC recall_observed event (p3_recall bypass hook)
            if RIC_AVAILABLE and body.get("query"):
                try:
                    ctx_pkg = ContextPackage(
                        query=body.get("query", ""),
                        canonical_window_id=body.get("scope", {}).get("canonical_window_id", ""),
                        session_id=body.get("scope", {}).get("session_id", ""),
                        intent_mode=body.get("mode", "summary"),
                        matched_memories=result.get("matched_memories", []),
                        source_refs=[m.get("source_refs", {}) for m in result.get("matched_memories", []) if m.get("source_refs")],
                        scope_enforced=True,
                    )
                    evt = InterpositionEvent(
                        event_type="recall_observed",
                        source_system=str(
                            body.get("source_system_filter")
                            or body.get("source_system")
                            or "unknown"
                        ).strip(),
                        context_package=ctx_pkg.to_dict(),
                        observe_only=True,
                        dry_run=True,
                        applied=False,
                    )
                    log_interposition_event(evt)
                except Exception:
                    pass  # Never let RIC event crash the recall endpoint
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_server(port=None):
    if port is None:
        port = int(os.environ.get("TIME_LIBRARY_INTERNAL_P3_PORT", "19300"))
    migration = migrate_legacy_bge_upgrade(
        os.environ.get("MEMCORE_ROOT") or str(Path(__file__).resolve().parents[1])
    )
    if migration.get("write_performed"):
        print(f"[p3] vector upgrade migration: {migration.get('state')}")
    preload = str(os.environ.get("MEMCORE_P3_PRELOAD_VECTOR") or "1").strip().lower()
    startup_vector_status = vector_runtime_status(load_model=preload not in {"0", "false", "no", "off", "disabled"})
    if startup_vector_status.get("expected") and not startup_vector_status.get("ok"):
        print(f"[p3] vector recall degraded: {startup_vector_status.get('issues', [])}")
    warmup_enabled = str(os.environ.get("MEMCORE_P3_WARMUP_VECTOR") or "1").strip().lower()
    if (
        startup_vector_status.get("expected")
        and startup_vector_status.get("ok")
        and warmup_enabled not in {"0", "false", "no", "off", "disabled"}
    ):
        warmup = _warmup_vector_engine()
        print(f"[p3] vector warmup: {warmup}")
    try:
        startup_memories = get_memories()
        _schedule_startup_fts5_refresh(startup_memories)
    except Exception:
        pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[p3] recall service running on http://127.0.0.1:{port}")
    server.serve_forever()

# ─── CLI 模式 ────────────────────────────────────

def cmd_recall(args):
    memories = get_memories()
    filtered = filter_memories(memories, type_filter=args.type, scope_filter=args.window, query=args.query)
    scored = sorted([(score_memory(m, args.query), m) for m in filtered], key=lambda x: -x[0])
    for score, m in scored[:args.top_k]:
        sr = m.get("_source_refs", {})
        print(f"\n[{m['_type']}] score={score:.2f} scope={m.get('scope','')}")
        print(f"  summary: {m.get('summary','')[:80]}")
        print(f"  window: {sr.get('canonical_window_id','')}")
        print(f"  session: {sr.get('session_id','')[:16]}...")
        print(f"  path: {sr.get('source_path','')}")

def cmd_list(args):
    memories = get_memories()
    by_type = defaultdict(int)
    for m in memories:
        by_type[m["_type"]] += 1
    print("知意对象统计:")
    for t, cnt in sorted(by_type.items()):
        print(f"  {t}: {cnt} 条")

def main():
    p = argparse.ArgumentParser(description="Time Library P3 本机记忆召回服务")
    sub = p.add_subparsers()

    srv = sub.add_parser("serve", help="启动 recall HTTP 服务")
    srv.add_argument("--port", type=int, default=int(os.environ.get("TIME_LIBRARY_INTERNAL_P3_PORT", "19300")))
    srv.set_defaults(fn=lambda a: run_server(a.port))

    rec = sub.add_parser("recall", help="CLI 召回")
    rec.add_argument("--query", default="", help="查询内容")
    rec.add_argument("--window", default="", help="window 过滤")
    rec.add_argument("--type", action="append", help="类型过滤 (case_memory/error_memory)")
    rec.add_argument("--top-k", type=int, default=5)
    rec.set_defaults(fn=cmd_recall)

    lst = sub.add_parser("list", help="列出所有对象")
    lst.set_defaults(fn=cmd_list)

    args = p.parse_args()
    if hasattr(args, "fn"):
        args.fn(args)
    else:
        p.print_help()

if __name__ == "__main__":
    main()
