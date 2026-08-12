#!/usr/bin/env python3
"""Experience governance console workbench under the Time River contract.

This module owns review queues, candidate lifecycle receipts, Zhiyi experience
recycle/restore overlays, and authorized case-memory adoption/rollback/upgrade
flows for the local console. It is a derived Experience Governance workbench:
queries are read-only by default, authorized actions may write receipts or
Zhiyi case-memory lifecycle overlays, and raw records remain the Time Origin.
"""

from __future__ import annotations

import datetime
import glob
import json
import os

try:
    from src.config_loader import base_path
except Exception:
    from config_loader import base_path
try:
    from src.zhiyi_archive import attach_archive_card
except Exception:
    from zhiyi_archive import attach_archive_card
try:
    from src.zhixing_library import (
        attach_library_card,
        benchmark_plan,
        replay_plan,
    )
except Exception:
    from zhixing_library import (
        attach_library_card,
        benchmark_plan,
        replay_plan,
    )
try:
    from src.p6_zhiyi_model_runtime import _compact_text, _usage_log_positive_int
except Exception:
    from p6_zhiyi_model_runtime import _compact_text, _usage_log_positive_int
try:
    from src import zhixing_library_dashboard as _library_dashboard
except Exception:
    import zhixing_library_dashboard as _library_dashboard
try:
    from src.time_river_sediment import get_time_river_sediment_contract
except Exception:
    from time_river_sediment import get_time_river_sediment_contract
try:
    from src.material_processing_pipeline import get_material_processing_pipeline_contract
except Exception:
    from material_processing_pipeline import get_material_processing_pipeline_contract
try:
    from src.second_brain import get_second_brain_contract
except Exception:
    from second_brain import get_second_brain_contract
try:
    from p6_experience_hermes_feedback import *
    import p6_experience_hermes_feedback as _hermes_feedback_governance
except Exception:
    from src.p6_experience_hermes_feedback import *
    from src import p6_experience_hermes_feedback as _hermes_feedback_governance

MEMCORE_ROOT = str(base_path())
EXPERIENCE_GOVERNANCE_CONTRACT = "tiandao_experience_governance_console.v1"
_load_zhiyi_objects_callback = None
_get_zhiyi_stats_callback = None
_raw_evidence_for_refs_callback = None


def _m6_proposals_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "P9-System-M6", "proposals")


def configure_experience_governance(
    memcore_root,
    *,
    load_zhiyi_objects=None,
    get_zhiyi_stats=None,
    raw_evidence_for_refs=None,
):
    global MEMCORE_ROOT, M6_PROPOSALS_DIR
    global _load_zhiyi_objects_callback, _get_zhiyi_stats_callback, _raw_evidence_for_refs_callback
    MEMCORE_ROOT = str(memcore_root)
    M6_PROPOSALS_DIR = _m6_proposals_dir()
    try:
        _hermes_feedback_governance.configure_experience_hermes_feedback(MEMCORE_ROOT)
    except Exception:
        pass
    try:
        _library_dashboard.configure_zhixing_library_dashboard(
            MEMCORE_ROOT,
            load_zhiyi_objects=load_zhiyi_objects,
            get_zhiyi_stats=get_zhiyi_stats,
            raw_evidence_for_refs=_m5_raw_evidence_for_refs,
            query_xingce_candidates=query_xingce_work_experience_candidates,
            zhiyi_recycle_overlay=_zhiyi_experience_recycle_overlay,
        )
    except Exception:
        pass
    if load_zhiyi_objects is not None:
        _load_zhiyi_objects_callback = load_zhiyi_objects
    if get_zhiyi_stats is not None:
        _get_zhiyi_stats_callback = get_zhiyi_stats
    if raw_evidence_for_refs is not None:
        _raw_evidence_for_refs_callback = raw_evidence_for_refs


def get_experience_governance_contract():
    return {
        "ok": True,
        "contract": EXPERIENCE_GOVERNANCE_CONTRACT,
        "zh_name": "经验治理工作台",
        "en_name": "Experience Governance Workbench",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "workbench_id": "experience_governance",
        "console_layer": "experience_governance",
        "derived_layer": "zhiyi_xingce_hermes",
        "read_only_by_default": True,
        "write_capable": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "not_raw_origin": True,
        "raw_origin_policy": "experience_governance_never_claims_or_replaces_time_origin_raw_records",
        "authorization_required_for_write": True,
        "authorized_write_scopes": [
            "governance_proposal_dry_run",
            "candidate_action_receipt",
            "consumption_receipt",
            "zhiyi_recycle_overlay",
            "zhiyi_case_memory_lifecycle_overlay",
            "experience_service_receipt",
        ],
        "default_query_boundary": {
            "read_only": True,
            "write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
        },
    }


def _default_get_zhiyi_stats():
    stats = {}
    for ftype in ["case_memory", "error_memory", "preference_memory"]:
        path = os.path.join(str(MEMCORE_ROOT), "zhiyi", ftype, f"{ftype}.jsonl")
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                stats[ftype] = sum(1 for line in f if line.strip())
        except Exception:
            stats[ftype] = 0
    return stats


def get_zhiyi_stats():
    if _get_zhiyi_stats_callback is not None:
        return _get_zhiyi_stats_callback()
    return _default_get_zhiyi_stats()


def _default_load_zhiyi_objects(ftype=None, limit=None):
    objects = []
    types = [ftype] if ftype else ["case_memory", "error_memory", "preference_memory"]
    for item_type in types:
        path = os.path.join(str(MEMCORE_ROOT), "zhiyi", item_type, f"{item_type}.jsonl")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    obj["_type"] = item_type
                    try:
                        obj["_source_refs"] = json.loads(obj.get("source_refs", "{}"))
                    except Exception:
                        obj["_source_refs"] = {}
                    objects.append(obj)
                    if limit is not None and len(objects) >= limit:
                        return objects
                except Exception:
                    pass
    return objects


def load_zhiyi_objects(ftype=None, limit=None):
    if _load_zhiyi_objects_callback is not None:
        return _load_zhiyi_objects_callback(ftype=ftype, limit=limit)
    return _default_load_zhiyi_objects(ftype=ftype, limit=limit)


def _default_raw_evidence_for_refs(refs, excerpt_chars=600):
    refs = refs or {}
    if not isinstance(refs, dict):
        return {
            "raw_evidence_status": "invalid_source_refs",
            "raw_excerpt": "",
            "evidence_hash": None,
            "source_path": "",
            "msg_ids": [],
        }
    source_path = refs.get("source_path", "")
    msg_ids = refs.get("msg_ids", []) or []
    if not source_path:
        return {
            "raw_evidence_status": "not_raw",
            "raw_excerpt": "",
            "evidence_hash": None,
            "source_path": "",
            "msg_ids": msg_ids,
        }
    try:
        try:
            from src.raw_consumption_gateway import _extract_bounded_raw_excerpt
        except Exception:
            from raw_consumption_gateway import _extract_bounded_raw_excerpt
        raw_excerpt, raw_status, evidence_hash = _extract_bounded_raw_excerpt(source_path, msg_ids, excerpt_chars)
    except Exception as exc:
        raw_excerpt, raw_status, evidence_hash = "", f"read_error:{str(exc)[:80]}", None
    return {
        "raw_evidence_status": raw_status,
        "raw_excerpt": raw_excerpt,
        "raw_excerpt_chars": len(raw_excerpt or ""),
        "evidence_hash": evidence_hash,
        "source_path": source_path,
        "msg_ids": msg_ids,
    }


def _m5_raw_evidence_for_refs(refs, excerpt_chars=600):
    if _raw_evidence_for_refs_callback is not None:
        return _raw_evidence_for_refs_callback(refs, excerpt_chars=excerpt_chars)
    return _default_raw_evidence_for_refs(refs, excerpt_chars=excerpt_chars)

# ─── M6 Governance Proposal Helpers ─────────────────────────────────────
# Zhiyi governance proposal dry-run.
# 原则：所有 proposal dry_run_only=true, applied=false
# 只写治理 proposal 目录，不改 raw / OpenClaw / 生产知意

M6_PROPOSALS_DIR = _m6_proposals_dir()


def _m6_ensure_proposals_dir():
    import os
    os.makedirs(M6_PROPOSALS_DIR, exist_ok=True)


def _m6_validate_target_exp_ids(exp_ids):
    """验证 exp_ids 存在于 base zhiyi 数据中"""
    objs = load_zhiyi_objects()
    valid_exp_ids = set(o.get("exp_id", "") for o in objs)
    invalid = [eid for eid in exp_ids if eid not in valid_exp_ids]
    return invalid


def _m6_write_proposal(proposal_record):
    """将 proposal 写入 JSONL（dry-run only）"""
    import os, uuid
    _m6_ensure_proposals_dir()
    if not proposal_record.get("proposal_id"):
        proposal_record["proposal_id"] = str(uuid.uuid4())
    if not proposal_record.get("created_at"):
        from datetime import datetime, timezone
        proposal_record["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    # Enforce dry_run_only and applied
    proposal_record["dry_run_only"] = True
    proposal_record["applied"] = False
    proposal_path = f"{M6_PROPOSALS_DIR}/{proposal_record['proposal_id']}.jsonl"
    with open(proposal_path, "w") as f:
        f.write(json.dumps(proposal_record, ensure_ascii=False) + "\n")
    return proposal_record


def _m6_compute_impact(target_exp_ids, proposal_type, proposal_data):
    """计算 proposal 影响范围"""
    import os, json as _json
    objs = load_zhiyi_objects()
    exp_id_set = set(target_exp_ids)
    target_objs = [o for o in objs if o.get("exp_id") in exp_id_set]
    type_ctr = {}
    for o in target_objs:
        t = o.get("_type", "unknown")
        type_ctr[t] = type_ctr.get(t, 0) + 1
    return {
        "target_count": len(target_exp_ids),
        "matched_in_base": len(target_objs),
        "by_type": type_ctr,
        "proposal_type": proposal_type,
    }


def m6_create_proposal(body):
    """M6-1: 创建治理 proposal（dry-run only）"""
    import os, uuid
    # Validate required fields
    target_exp_ids = body.get("target_exp_ids", [])
    proposal_type = body.get("proposal_type", "")
    valid_types = ["duplicate", "conflict", "superseded", "archived", "inject_policy", "edit_summary"]
    if not target_exp_ids:
        return {"error": "target_exp_ids required"}
    if proposal_type not in valid_types:
        return {"error": f"proposal_type must be one of {valid_types}"}
    # Validate targets exist
    invalid = _m6_validate_target_exp_ids(target_exp_ids)
    if invalid:
        return {"error": f"exp_ids not found: {invalid[:3]}"}
    # Build proposal record
    proposal_record = {
        "proposal_id": str(uuid.uuid4()),
        "created_at": body.get("created_at", ""),
        "dry_run_only": True,
        "applied": False,
        "target_exp_ids": target_exp_ids,
        "proposal_type": proposal_type,
        "rationale": body.get("rationale", ""),
        # Type-specific fields
        "duplicate_of": body.get("duplicate_of", None),
        "conflict_with": body.get("conflict_with", None),
        "new_status": body.get("new_status", None),
        "inject_policy": body.get("inject_policy", None),
        "new_summary": body.get("new_summary", None),
        "edit_field": body.get("edit_field", None),
    }
    # Compute impact
    proposal_record["impact"] = _m6_compute_impact(target_exp_ids, proposal_type, proposal_record)
    # Write to output (dry-run only)
    proposal_record = _m6_write_proposal(proposal_record)
    return {
        "proposal_id": proposal_record["proposal_id"],
        "dry_run_only": True,
        "applied": False,
        "impact": proposal_record["impact"],
        "status": "draft",
        "_note": "dry-run proposal: not applied to production zhiyi or raw",
    }


def m5_create_experience_action(body):
    """P1-1: create durable backend proposal for frontstage lifecycle actions."""
    action = body.get("action", "")
    target_exp_ids = body.get("target_exp_ids", [])
    if isinstance(target_exp_ids, str):
        target_exp_ids = [target_exp_ids]
    target_exp_ids = [eid for eid in target_exp_ids if eid]
    if action not in ("adopt", "upgrade", "recycle"):
        return {"error": "action must be one of adopt, upgrade, recycle"}
    if not target_exp_ids:
        return {"error": "target_exp_ids required"}

    proposal = {
        "target_exp_ids": target_exp_ids,
        "rationale": body.get("rationale") or f"frontstage {action} action",
    }
    if action == "adopt":
        proposal.update({
            "proposal_type": "inject_policy",
            "inject_policy": body.get("inject_policy") or "on_demand",
        })
    elif action == "upgrade":
        proposal.update({
            "proposal_type": "edit_summary",
            "new_summary": body.get("new_summary", None),
            "edit_field": body.get("edit_field", "summary"),
        })
    elif action == "recycle":
        proposal.update({
            "proposal_type": "archived",
            "new_status": "archived",
        })

    result = m6_create_proposal(proposal)
    if "error" in result:
        return result
    result["action"] = action
    result["target_exp_ids"] = target_exp_ids
    result["backend_persisted"] = True
    result["_note"] = "backend governance proposal created; no browser-local lifecycle state"
    return result


def m6_list_proposals():
    """M6-2: 列出所有 proposal"""
    _m6_ensure_proposals_dir()
    proposals = []
    try:
        for fname in os.listdir(M6_PROPOSALS_DIR):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(M6_PROPOSALS_DIR, fname)
            with open(fpath) as f:
                line = f.readline()
                if line.strip():
                    proposals.append(json.loads(line))
    except Exception:
        pass
    proposals.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    by_type = {}
    for p in proposals:
        pt = p.get("proposal_type", "unknown")
        by_type[pt] = by_type.get(pt, 0) + 1
    return {
        "total": len(proposals),
        "by_type": by_type,
        "proposals": proposals,
    }


def m6_get_proposal(proposal_id):
    """M6-3: proposal 详情"""
    import os
    _m6_ensure_proposals_dir()
    fpath = f"{M6_PROPOSALS_DIR}/{proposal_id}.jsonl"
    if not os.path.exists(fpath):
        return {"error": f"Proposal {proposal_id} not found", "proposal_id": proposal_id}
    with open(fpath) as f:
        line = f.readline()
        if not line.strip():
            return {"error": "Empty proposal file"}
        return json.loads(line)


def m6_get_proposal_summary(proposal_id):
    """M6-4: proposal 复制摘要"""
    p = m6_get_proposal(proposal_id)
    if "error" in p:
        return {"error": p["error"]}
    lines = []
    lines.append(f"## Governance Proposal")
    lines.append(f"**ID**: {p.get('proposal_id', '')}")
    lines.append(f"**类型**: {p.get('proposal_type', '')}")
    lines.append(f"**状态**: {p.get('status', 'draft')} (dry_run_only={p.get('dry_run_only')}, applied={p.get('applied')})")
    lines.append(f"**时间**: {p.get('created_at', '')}")
    lines.append(f"**目标**: {p.get('target_exp_ids', [])}")
    impact = p.get("impact", {})
    lines.append(f"**影响**: {impact.get('matched_in_base', 0)} 条记忆")
    if p.get("rationale"):
        lines.append(f"**理由**: {p.get('rationale')}")
    lines.append(f"")
    lines.append(f"⚠️ **dry-run only**: 此 proposal 不会修改 raw 或生产知意对象")
    return {
        "proposal_id": proposal_id,
        "summary_text": "\n".join(lines),
        "dry_run_only": p.get("dry_run_only"),
        "applied": p.get("applied"),
    }


def m6_get_stats():
    """M6-5: governance 统计"""
    listing = m6_list_proposals()
    total = listing.get("total", 0)
    by_type = listing.get("by_type", {})
    return {
        "total_proposals": total,
        "by_type": by_type,
        "by_status": {
            "draft": total,  # all are draft since none ever applied
        },
        "dry_run_only": True,
        "applied_count": 0,
        "proposals_dir": M6_PROPOSALS_DIR,
        "_note": "all proposals are dry-run: applied=0",
    }



# Zhiyi model/runtime console helpers live under p6_zhiyi_model_runtime.py.

def _xingce_work_experience_candidates_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "xingce_work_experience", "candidates")


def _xingce_work_experience_actions_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "xingce_work_experience", "actions")


def _experience_service_adoptions_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "experience_service", "adoptions")


def _experience_service_rollbacks_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "experience_service", "rollbacks")


def _experience_service_upgrades_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "experience_service", "upgrades")


def _zhixing_replay_feedback_applications_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "zhixing_replay_feedback", "applications")


def _zhiyi_case_memory_dir():
    return os.path.join(str(MEMCORE_ROOT), "zhiyi", "case_memory")


def _zhiyi_case_memory_path():
    return os.path.join(_zhiyi_case_memory_dir(), "case_memory.jsonl")


def _zhiyi_case_memory_lifecycle_path():
    return os.path.join(_zhiyi_case_memory_dir(), "case_memory.lifecycle.jsonl")


def _safe_experience_id(exp_id):
    exp_id = str(exp_id or "").strip()
    safe = "".join(ch for ch in exp_id if ch.isalnum() or ch in ("-", "_"))
    if not safe or safe != exp_id:
        return ""
    return safe


def _zhiyi_experience_recycle_path():
    return os.path.join(str(MEMCORE_ROOT), "output", "zhiyi_experience_lifecycle", "recycle_bin.jsonl")


def _zhiyi_experience_recycle_records():
    return _read_jsonl_records(_zhiyi_experience_recycle_path())


def _zhiyi_experience_recycle_overlay():
    overlay = {}
    for rec in _zhiyi_experience_recycle_records():
        exp_id = str(rec.get("exp_id") or "").strip()
        if not exp_id:
            continue
        action = rec.get("action") or "recycle"
        if action == "restore":
            overlay.pop(exp_id, None)
            continue
        if rec.get("deleted_state") == "recycle_bin" or action == "recycle":
            overlay[exp_id] = rec
    return overlay


def _zhiyi_experience_find(exp_id):
    safe_exp_id = _safe_experience_id(exp_id)
    if not safe_exp_id:
        return None
    for obj in load_zhiyi_objects():
        if obj.get("exp_id") == safe_exp_id:
            return obj
    return None


def recycle_zhiyi_experience(exp_id, body=None):
    body = body or {}
    safe_exp_id = _safe_experience_id(exp_id)
    if not safe_exp_id:
        return {"ok": False, "error": "invalid_exp_id"}
    obj = _zhiyi_experience_find(safe_exp_id)
    if not obj:
        return {"ok": False, "error": "experience_not_found", "exp_id": safe_exp_id}

    import uuid
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    refs = obj.get("_source_refs", {})
    if not isinstance(refs, dict):
        refs = {}
    source_path = refs.get("source_path", "")
    record = {
        "action_id": str(uuid.uuid4()),
        "action": "recycle",
        "exp_id": safe_exp_id,
        "title": _experience_title(obj, obj.get("_type", ""), 0),
        "type": obj.get("_type", ""),
        "deleted_state": "recycle_bin",
        "status": "recycled",
        "suppression_marker": True,
        "created_at": now,
        "reason": str(body.get("reason") or "frontstage_delete")[:240],
        "operator": str(body.get("operator") or "frontstage")[:80],
        "source_path": source_path,
        "raw_deleted": False,
        "raw_write_performed": False,
        "zhiyi_base_write_performed": False,
        "platform_write_performed": False,
        "restore_supported_now": True,
        "recycle_policy": "manual_restore",
    }
    _jsonl_append(_zhiyi_experience_recycle_path(), record)
    return {
        "ok": True,
        "exp_id": safe_exp_id,
        "deleted_state": "recycle_bin",
        "recycle_bin_count": len(_zhiyi_experience_recycle_overlay()),
        "raw_deleted": False,
        "raw_write_performed": False,
        "zhiyi_base_write_performed": False,
        "suppression_marker": True,
        "restore_supported_now": True,
        "restore_endpoint": "/api/v1/zhiyi/experiences/{exp_id}/restore",
        "record": record,
    }


def restore_zhiyi_experience(exp_id, body=None):
    body = body or {}
    safe_exp_id = _safe_experience_id(exp_id)
    if not safe_exp_id:
        return {"ok": False, "error": "invalid_exp_id"}
    if safe_exp_id not in _zhiyi_experience_recycle_overlay():
        return {"ok": False, "error": "experience_not_in_trash", "exp_id": safe_exp_id}
    obj = _zhiyi_experience_find(safe_exp_id)
    if not obj:
        return {"ok": False, "error": "experience_not_found", "exp_id": safe_exp_id}

    import uuid
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    refs = obj.get("_source_refs", {})
    if not isinstance(refs, dict):
        refs = {}
    record = {
        "action_id": str(uuid.uuid4()),
        "action": "restore",
        "exp_id": safe_exp_id,
        "title": _experience_title(obj, obj.get("_type", ""), 0),
        "type": obj.get("_type", ""),
        "deleted_state": "active",
        "status": "restored",
        "suppression_marker": False,
        "created_at": now,
        "reason": str(body.get("reason") or "frontstage_restore")[:240],
        "operator": str(body.get("operator") or "frontstage")[:80],
        "source_path": refs.get("source_path", ""),
        "raw_deleted": False,
        "raw_write_performed": False,
        "zhiyi_base_write_performed": False,
        "platform_write_performed": False,
        "restore_supported_now": True,
        "recycle_policy": "manual_restore",
    }
    _jsonl_append(_zhiyi_experience_recycle_path(), record)
    return {
        "ok": True,
        "exp_id": safe_exp_id,
        "deleted_state": "active",
        "recycle_bin_count": len(_zhiyi_experience_recycle_overlay()),
        "raw_deleted": False,
        "raw_write_performed": False,
        "zhiyi_base_write_performed": False,
        "suppression_marker": False,
        "record": record,
    }


def get_zhiyi_experience_recycle_bin(limit=20):
    try:
        limit = max(1, min(int(limit), 100))
    except Exception:
        limit = 20
    records = list(_zhiyi_experience_recycle_overlay().values())
    records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {
        "ok": True,
        "total": len(records),
        "items": records[:limit],
        "raw_deleted": False,
        "restore_supported_now": True,
        "recycle_policy": "manual_restore",
    }


def _window_from_raw_source_path(source_path):
    parts = str(source_path or "").split(os.sep)
    for index, part in enumerate(parts):
        if part == "local" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _latest_xingce_work_experience_candidate_id(candidates_dir):
    latest_path = os.path.join(candidates_dir, "latest.json")
    latest, err = _read_hermes_feedback_json(latest_path)
    if err:
        return "", latest_path, {}
    return str(latest.get("candidate_id", "") or ""), latest_path, latest


def _xingce_work_experience_candidate_summary(candidate, source_path="", latest_candidate_id=""):
    write_boundary = candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {}
    comparison = candidate.get("comparison_result", {}) if isinstance(candidate.get("comparison_result"), dict) else {}
    evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []
    source_refs = candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []
    candidate_id = candidate.get("candidate_id", "")
    recommended_procedure = candidate.get("recommended_procedure", []) if isinstance(candidate.get("recommended_procedure"), list) else []
    verification_steps = candidate.get("verification_steps", []) if isinstance(candidate.get("verification_steps"), list) else []
    avoid_conditions = candidate.get("avoid_conditions", []) if isinstance(candidate.get("avoid_conditions"), list) else []
    lifecycle_status = str(candidate.get("lifecycle_status", "") or "candidate")
    library_record = {
        "_type": "xingce_work_experience_candidate",
        "exp_id": candidate_id,
        "title": candidate.get("title", ""),
        "summary": candidate.get("summary", ""),
        "detail": "\n".join(str(item) for item in recommended_procedure + verification_steps),
        "verbatim_excerpt": candidate.get("verbatim_excerpt") or candidate.get("raw_excerpt") or candidate.get("summary", ""),
        "lifecycle_status": lifecycle_status,
        "source_refs": evidence_refs[0] if evidence_refs and isinstance(evidence_refs[0], dict) else {},
        "supersedes": candidate.get("supersedes", []) if isinstance(candidate.get("supersedes"), list) else [],
        "conflicts_with": candidate.get("conflicts_with", []) if isinstance(candidate.get("conflicts_with"), list) else [],
        "_xingce": {
            "candidate_id": candidate_id,
            "candidate_type": candidate.get("candidate_type", ""),
            "lifecycle_status": lifecycle_status,
            "action_status": "",
            "production_experience_write_performed": bool(write_boundary.get("production_experience_write_performed", False)),
        },
        "work_scenario": candidate.get("work_scenario") or candidate.get("title", ""),
        "action_strategy": candidate.get("action_strategy") or recommended_procedure,
        "avoid_conditions": avoid_conditions,
        "acceptance_checks": candidate.get("acceptance_checks") or verification_steps,
        "applicable_scope": candidate.get("applicable_scope") or candidate.get("frontstage_surface", ""),
    }
    library_record = attach_library_card(library_record)
    return {
        "candidate_id": candidate_id,
        "library_id": library_record.get("library_id", ""),
        "library_shelf": library_record.get("library_shelf", "xingce"),
        "library_card": library_record.get("library_card", {}),
        "evidence_contract": library_record.get("library_card", {}).get("evidence_contract", {}),
        "candidate_type": candidate.get("candidate_type", ""),
        "source_draft_id": candidate.get("source_draft_id", ""),
        "title": candidate.get("title", ""),
        "summary": _compact_text(candidate.get("summary", ""), 360),
        "created_at": candidate.get("created_at", ""),
        "lifecycle_status": lifecycle_status,
        "lifecycle": {
            "status": lifecycle_status,
            "allowed_statuses": ["candidate", "pending_review", "adopted", "deprecated", "superseded"],
            "review_required": lifecycle_status in ("candidate", "pending_review"),
        },
        "work_scenario": library_record.get("work_experience", {}).get("work_scenario", ""),
        "action_strategy": library_record.get("work_experience", {}).get("action_strategy", ""),
        "avoid_conditions": library_record.get("work_experience", {}).get("avoid_conditions", []),
        "acceptance_checks": library_record.get("work_experience", {}).get("acceptance_checks", []),
        "applicable_scope": library_record.get("work_experience", {}).get("applicable_scope", ""),
        "not_a_skill": True,
        "not_a_user_preference": True,
        "frontstage_surface": candidate.get("frontstage_surface", ""),
        "source_mode": candidate.get("source_mode", ""),
        "change_class": comparison.get("change_class", ""),
        "raw_evidence_contract_gate_passed": bool(comparison.get("raw_evidence_contract_gate_passed", False)),
        "confidence": candidate.get("confidence", 0.0),
        "evidence_refs_count": len(evidence_refs),
        "source_refs_count": len(source_refs),
        "write_boundary": write_boundary,
        "production_experience_write_performed": bool(write_boundary.get("production_experience_write_performed", False)),
        "raw_write_performed": bool(write_boundary.get("raw_write_performed", False)),
        "zhiyi_write_performed": bool(write_boundary.get("zhiyi_write_performed", False)),
        "xingce_write_performed": bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_performed": bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_performed": bool(write_boundary.get("openclaw_write_performed", False)),
        "source_path": source_path,
        "is_latest": bool(candidate_id and candidate_id == latest_candidate_id),
        "detail_endpoint": f"/api/v1/xingce/work-experience-candidates/{candidate_id}" if candidate_id else "",
    }


def _sync_library_dashboard_bindings():
    _library_dashboard.configure_zhixing_library_dashboard(
        MEMCORE_ROOT,
        load_zhiyi_objects=load_zhiyi_objects,
        get_zhiyi_stats=get_zhiyi_stats,
        raw_evidence_for_refs=_m5_raw_evidence_for_refs,
        query_xingce_candidates=query_xingce_work_experience_candidates,
        zhiyi_recycle_overlay=_zhiyi_experience_recycle_overlay,
    )


def query_zhixing_library(params=None):
    _sync_library_dashboard_bindings()
    return _library_dashboard.query_zhixing_library(params)


def query_zhixing_library_trust_dashboard(params=None):
    _sync_library_dashboard_bindings()
    return _library_dashboard.query_zhixing_library_trust_dashboard(params)


def get_zhixing_replay_plan():
    return replay_plan()


def get_zhixing_benchmark_plan():
    return benchmark_plan()


def get_time_river_sediment_plan():
    return get_time_river_sediment_contract()


def get_material_processing_pipeline_plan():
    return get_material_processing_pipeline_contract()


def get_second_brain_plan():
    return get_second_brain_contract()


def apply_zhixing_replay_feedback_candidate(body=None):
    body = body or {}
    candidate = body.get("candidate") if isinstance(body.get("candidate"), dict) else {}
    authorization = body.get("authorization") if isinstance(body.get("authorization"), dict) else {}
    candidate_id = _safe_hermes_candidate_id(candidate.get("candidate_id", ""))
    candidate_type = str(candidate.get("candidate_type") or "").strip()

    def confirmed(name):
        return _hermes_feedback_action_bool(authorization.get(name, body.get(name)))

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    allowed_types = {
        "replay_adoption_candidate",
        "replay_errata_candidate",
        "proactive_resurfacing_candidate",
    }
    required_checks = {
        "confirm_apply_replay_feedback": confirmed("confirm_apply_replay_feedback"),
        "confirm_write_replay_feedback_receipt": confirmed("confirm_write_replay_feedback_receipt"),
        "confirm_no_raw_platform_or_memory_write": confirmed("confirm_no_raw_platform_or_memory_write"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    guard_checks = {
        "candidate_id_safe": bool(candidate_id),
        "candidate_type_allowed": candidate_type in allowed_types,
        "candidate_requires_authorization": bool(candidate.get("requires_authorization", True)),
        "candidate_write_performed_false": not bool(candidate.get("write_performed", False)),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "replay_feedback_receipt_write_performed": False,
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
            "candidate_id": candidate_id,
            "candidate_type": candidate_type,
            "requires_authorization": True,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": required_checks,
            "guard_checks": guard_checks,
            "guard_failures": guard_failures,
            "error": "blocked_missing_authorization_or_guard_failure",
        }

    import uuid
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    application_id = "replay-feedback-application-" + uuid.uuid4().hex[:16]
    receipt = {
        "schema_version": "1.0",
        "application_id": application_id,
        "created_at": now_iso,
        "candidate_id": candidate_id,
        "candidate_type": candidate_type,
        "recommended_action": candidate.get("recommended_action", ""),
        "operator": str(authorization.get("operator", body.get("operator", "")) or ""),
        "reason": str(authorization.get("reason", body.get("reason", "")) or ""),
        "candidate": candidate,
        "write_boundary": {
            "replay_feedback_receipt_write_performed": True,
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
            "proactive_hint_rule_write_performed": False,
            "errata_write_performed": False,
        },
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "notes": [
            "replay_feedback_application_receipt_only",
            "no_adopted_experience_or_errata_written_yet",
            "candidate_can_be_used_by_future_authorized_apply_step",
        ],
    }
    applications_dir = _zhixing_replay_feedback_applications_dir()
    os.makedirs(applications_dir, exist_ok=True)
    receipt_path = os.path.join(applications_dir, f"{now_iso.replace(':', '').replace('-', '')}-{candidate_id}.jsonl")
    _jsonl_append(receipt_path, receipt)
    latest_path = os.path.join(applications_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "replay_feedback_receipt_write_performed": True,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidate_id": candidate_id,
        "candidate_type": candidate_type,
        "application_id": application_id,
        "receipt_path": receipt_path,
        "latest_path": latest_path,
        "receipt": receipt,
    }


def _xingce_work_experience_action_history(candidate_id="", limit=20):
    actions_dir = _xingce_work_experience_actions_dir()
    items = []
    parse_errors = []
    if not os.path.isdir(actions_dir):
        return items, parse_errors
    try:
        names = sorted(os.listdir(actions_dir), reverse=True)
    except Exception as exc:
        return items, [{"path": actions_dir, "error": str(exc)[:120]}]
    safe_id = _safe_hermes_candidate_id(candidate_id)
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(actions_dir, name)
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                line = f.readline().strip()
            if not line:
                continue
            item = json.loads(line)
        except Exception as exc:
            parse_errors.append({"path": path, "error": str(exc)[:120]})
            continue
        if safe_id and item.get("candidate_id") != safe_id:
            continue
        item["_source_path"] = path
        items.append(item)
        if len(items) >= limit:
            break
    return items, parse_errors


def query_xingce_work_experience_candidates(params=None):
    params = params or {}
    candidates_dir = _xingce_work_experience_candidates_dir()
    candidates_dir_exists = os.path.isdir(candidates_dir)
    latest_candidate_id, latest_path, latest_candidate = _latest_xingce_work_experience_candidate_id(candidates_dir)
    page = _usage_log_positive_int(params.get("page", 1), 1, 1000000)
    page_size = _usage_log_positive_int(params.get("page_size", 20), 20, 50)
    status_filter = str(params.get("lifecycle_status", "") or "").strip()

    items = []
    parse_errors = []
    seen = set()
    if candidates_dir_exists:
        for path in sorted(glob.glob(os.path.join(candidates_dir, "xingce-*-candidate.json"))):
            candidate, err = _read_hermes_feedback_json(path)
            if err:
                parse_errors.append({"path": path, "error": err})
                continue
            if candidate.get("candidate_type") != "xingce_work_experience":
                continue
            candidate_id = str(candidate.get("candidate_id", "") or "")
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            items.append(_xingce_work_experience_candidate_summary(candidate, path, latest_candidate_id))

    if latest_candidate and latest_candidate_id and latest_candidate_id not in seen:
        items.append(_xingce_work_experience_candidate_summary(latest_candidate, latest_path, latest_candidate_id))

    items.sort(key=lambda item: (item.get("created_at") or "", item.get("candidate_id") or ""), reverse=True)
    if status_filter:
        items = [item for item in items if item.get("lifecycle_status") == status_filter]
    for item in items:
        history, _ = _xingce_work_experience_action_history(item.get("candidate_id", ""), limit=1)
        item["action_count"] = len(_xingce_work_experience_action_history(item.get("candidate_id", ""), limit=1000000)[0])
        item["latest_action"] = history[0] if history else None
        item["action_endpoint"] = f"/api/v1/xingce/work-experience-candidates/{item.get('candidate_id', '')}/actions"

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "api_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidates_dir": candidates_dir,
        "candidates_dir_exists": candidates_dir_exists,
        "latest_candidate_id": latest_candidate_id,
        "latest_path": latest_path,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "items": items[start:end],
        "parse_errors": parse_errors,
        "filters": {"lifecycle_status": status_filter},
        "query_contract": {
            "schema_version": "1.0",
            "source": "output/xingce_work_experience/candidates/xingce-*-candidate.json",
            "order": "newest_first",
            "method": "GET",
            "write_performed": False,
        },
        "notes": [
            "xingce_candidate_artifact_read_only",
            "no_raw_zhiyi_xingce_hermes_openclaw_write",
            "production_experience_upgrade_not_applied_by_this_api",
        ],
    }


def query_xingce_work_experience_actions(params=None):
    params = params or {}
    candidate_id = str(params.get("candidate_id", "") or "").strip()
    limit = _usage_log_positive_int(params.get("limit", 20), 20, 100)
    items, parse_errors = _xingce_work_experience_action_history(candidate_id, limit=limit)
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "actions_dir": _xingce_work_experience_actions_dir(),
        "candidate_id": candidate_id,
        "total": len(items),
        "items": items,
        "parse_errors": parse_errors,
    }


def get_xingce_work_experience_candidate(candidate_id):
    candidates_dir = _xingce_work_experience_candidates_dir()
    safe_id = _safe_hermes_candidate_id(candidate_id)
    latest_candidate_id, latest_path, latest_candidate = _latest_xingce_work_experience_candidate_id(candidates_dir)
    if safe_id == "latest":
        candidate = latest_candidate
        source_path = latest_path
    elif safe_id:
        source_path = os.path.join(candidates_dir, f"{safe_id}.json")
        candidate, err = _read_hermes_feedback_json(source_path)
        if err and safe_id == latest_candidate_id and latest_candidate:
            candidate = latest_candidate
            source_path = latest_path
    else:
        candidate = {}
        source_path = ""
    if not candidate:
        return {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "error": "xingce_candidate_not_found",
            "candidate_id": candidate_id,
            "candidates_dir": candidates_dir,
        }
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "api_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidate_id": candidate.get("candidate_id", safe_id),
        "latest_candidate_id": latest_candidate_id,
        "candidates_dir": candidates_dir,
        "source_path": source_path,
        "summary": _xingce_work_experience_candidate_summary(candidate, source_path, latest_candidate_id),
        "write_boundary": candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {},
        "actions": _xingce_work_experience_action_history(candidate.get("candidate_id", safe_id), limit=20)[0],
        "candidate": candidate,
    }


def apply_xingce_work_experience_candidate_action(candidate_id, body=None):
    body = body or {}
    detail = get_xingce_work_experience_candidate(candidate_id)
    if not detail.get("ok"):
        return detail
    candidate = detail.get("candidate", {})
    safe_id = _safe_hermes_candidate_id(candidate.get("candidate_id", candidate_id))
    action = str(body.get("action", "") or "").strip()
    aliases = {
        "adopt": "adopt_as_experience",
        "adopt_as_experience": "adopt_as_experience",
        "upgrade": "upgrade_experience",
        "upgrade_experience": "upgrade_experience",
        "recycle": "recycle",
    }
    action = aliases.get(action, "")
    if action not in ("adopt_as_experience", "upgrade_experience", "recycle"):
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "error": "action_must_be_one_of_adopt_as_experience_upgrade_experience_recycle",
            "candidate_id": safe_id,
        }

    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        return _hermes_feedback_action_bool(authorization.get(name, body.get(name)))

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    required_checks = {
        "confirm_process_xingce_candidate": confirmed("confirm_process_xingce_candidate"),
        "confirm_write_xingce_candidate_action": confirmed("confirm_write_xingce_candidate_action"),
        "confirm_no_raw_zhiyi_xingce_hermes_openclaw_write": confirmed("confirm_no_raw_zhiyi_xingce_hermes_openclaw_write"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    write_boundary = candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {}
    guard_checks = {
        "candidate_id_safe": bool(safe_id),
        "candidate_type": candidate.get("candidate_type") == "xingce_work_experience",
        "candidate_lifecycle_status": candidate.get("lifecycle_status") == "candidate",
        "candidate_artifact_exists": os.path.isfile(detail.get("source_path", "")),
        "candidate_not_production_written": not bool(write_boundary.get("production_experience_write_performed", False)),
        "raw_write_stays_false": not bool(write_boundary.get("raw_write_performed", False)),
        "zhiyi_write_stays_false": not bool(write_boundary.get("zhiyi_write_performed", False)),
        "xingce_write_stays_false": not bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_stays_false": not bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_stays_false": not bool(write_boundary.get("openclaw_write_performed", False)),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "action_write_performed": False,
            "candidate_id": safe_id,
            "action": action,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": required_checks,
            "guard_checks": guard_checks,
            "guard_failures": guard_failures,
            "error": "blocked_missing_authorization_or_guard_failure",
        }

    import uuid
    actions_dir = _xingce_work_experience_actions_dir()
    os.makedirs(actions_dir, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action_id = "xingce-action-" + uuid.uuid4().hex[:16]
    action_status = {
        "adopt_as_experience": "queued_for_experience_service_review",
        "upgrade_experience": "queued_for_experience_upgrade_review",
        "recycle": "recycled_from_xingce_candidate_queue",
    }[action]
    receipt = {
        "schema_version": "1.0",
        "action_id": action_id,
        "created_at": now,
        "candidate_id": safe_id,
        "candidate_type": candidate.get("candidate_type", ""),
        "action": action,
        "action_status": action_status,
        "operator": str(authorization.get("operator", body.get("operator", "")) or ""),
        "reason": str(authorization.get("reason", body.get("reason", "")) or ""),
        "source_candidate_path": detail.get("source_path", ""),
        "source_mode": candidate.get("source_mode", ""),
        "change_class": (candidate.get("comparison_result", {}) if isinstance(candidate.get("comparison_result"), dict) else {}).get("change_class", ""),
        "evidence_refs_count": len(candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []),
        "source_refs_count": len(candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []),
        "write_boundary": {
            "action_receipt_write_performed": True,
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "notes": [
            "live_xingce_work_experience_action_receipt",
            "candidate_artifact_not_modified",
            "no_raw_zhiyi_xingce_hermes_openclaw_write",
        ],
    }
    action_path = os.path.join(actions_dir, f"{now.replace(':', '').replace('-', '')}-{safe_id}-{action}.jsonl")
    with open(action_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")) + "\n")
    latest_path = os.path.join(actions_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "action_write_performed": True,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidate_id": safe_id,
        "action": action,
        "action_status": action_status,
        "action_id": action_id,
        "action_path": action_path,
        "latest_path": latest_path,
        "receipt": receipt,
    }


def _first_xingce_evidence_ref(candidate):
    evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []
    for item in evidence_refs:
        if isinstance(item, dict) and item.get("source_path"):
            return dict(item)
    source_refs = candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []
    for source_path in source_refs:
        if source_path:
            return {"source_path": source_path}
    return {}


def _stable_xingce_case_exp_id(candidate_id):
    import hashlib
    digest = hashlib.sha1(str(candidate_id or "").encode("utf-8")).hexdigest()[:12]
    return f"exp-case-{digest}"


def _decode_record_source_refs(record):
    raw = record.get("source_refs", {}) if isinstance(record, dict) else {}
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
            return decoded if isinstance(decoded, dict) else {}
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


def _find_case_memory_record(exp_id):
    for record in _read_jsonl_records(_zhiyi_case_memory_path()):
        if record.get("exp_id") == exp_id:
            return record
    return {}


def _latest_case_memory_record(exp_id):
    latest = {}
    for record in _read_jsonl_records(_zhiyi_case_memory_path()):
        if record.get("exp_id") != exp_id:
            continue
        if not latest or int(record.get("lifecycle_version", 0) or 0) >= int(latest.get("lifecycle_version", 0) or 0):
            latest = record
    return latest


def _latest_case_memory_lifecycle_record(exp_id):
    latest = {}
    for record in _read_jsonl_records(_zhiyi_case_memory_lifecycle_path()):
        if record.get("exp_id") != exp_id:
            continue
        if not latest or int(record.get("lifecycle_version", 0) or 0) >= int(latest.get("lifecycle_version", 0) or 0):
            latest = record
    return latest


def _candidate_to_case_memory_record(candidate, detail, action, exp_id, authorization, now_display):
    import hashlib
    safe_id = str(candidate.get("candidate_id", "") or "")
    evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []
    raw_source_refs = candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []
    first_ref = _first_xingce_evidence_ref(candidate)
    source_path = first_ref.get("source_path", "")
    window_id = first_ref.get("canonical_window_id") or _window_from_raw_source_path(source_path)
    computer_name = first_ref.get("computer_name") or first_ref.get("computer_id") or "local"
    source_refs = {
        "source_system": first_ref.get("source_system", "openclaw"),
        "computer_name": computer_name,
        "computer_id": first_ref.get("computer_id", computer_name),
        "canonical_window_id": window_id,
        "session_id": first_ref.get("session_id", ""),
        "source_path": source_path,
        "msg_ids": first_ref.get("msg_ids", []),
        "evidence_refs": evidence_refs,
        "raw_source_refs": raw_source_refs,
        "experience_service": {
            "source": "xingce_work_experience_candidate",
            "candidate_id": safe_id,
            "candidate_path": detail.get("source_path", ""),
            "action_id": action.get("action_id", ""),
            "action_path": action.get("_source_path", ""),
            "action_status": action.get("action_status", ""),
            "projection_desensitized": False,
            "raw_projection_policy": "preserve_verbatim_refs",
        },
    }
    title = candidate.get("title") or "Xingce work experience"
    summary = candidate.get("summary") or "Xingce work experience adopted into Zhiyi"
    observed = candidate.get("observed_facts", []) if isinstance(candidate.get("observed_facts"), list) else []
    procedures = candidate.get("recommended_procedure", []) if isinstance(candidate.get("recommended_procedure"), list) else []
    verification = candidate.get("verification_steps", []) if isinstance(candidate.get("verification_steps"), list) else []
    detail_parts = [
        f"candidate_id={safe_id}",
        f"source_mode={candidate.get('source_mode', '')}",
        f"operator_reason={authorization.get('reason', '')}",
    ]
    detail_parts.extend(str(item) for item in observed[:5])
    detail_parts.extend(str(item) for item in procedures[:5])
    detail_parts.extend(str(item) for item in verification[:5])
    memory_id = hashlib.sha256(f"{exp_id}:{safe_id}:production_case_memory".encode("utf-8")).hexdigest()
    try:
        score = max(float(candidate.get("confidence", 0.75) or 0.75), 0.75)
    except Exception:
        score = 0.75
    return {
        "exp_id": exp_id,
        "type": "case_memory",
        "canonical_window_id": window_id,
        "session_id": first_ref.get("session_id", ""),
        "computer_id": source_refs["computer_id"],
        "source_system": source_refs["source_system"],
        "scope": f"window/{window_id}" if window_id else "window/main",
        "summary": f"案例：[行策经验已采用] {title}。{summary}。candidate_id={safe_id}",
        "detail": "\n".join(part for part in detail_parts if part),
        "source_refs": json.dumps(source_refs, ensure_ascii=False, separators=(",", ":")),
        "evidence_level": "high" if evidence_refs else "medium",
        "score": score,
        "extracted_at": now_display,
        "memory_id": memory_id,
        "lifecycle_version": 1,
    }


def _case_memory_lifecycle_record(case_record, status, conflict_decision, lifecycle_version, reason, now_display):
    lifecycle = dict(case_record)
    lifecycle.update({
        "status": status,
        "visibility": "canonical" if conflict_decision == "active" else "suppressed",
        "inject_policy": "inject_on_match" if conflict_decision == "active" else "never",
        "supersedes": [],
        "superseded_by": [],
        "lifecycle_updated_at": now_display,
        "lifecycle_version": lifecycle_version,
        "conflict_group_id": f"CG-{case_record.get('exp_id', '')}",
        "conflict_type": "experience_service_action",
        "conflict_decision": conflict_decision,
        "conflict_reason": reason,
        "effective_from": now_display,
        "validity_scope": case_record.get("scope", ""),
    })
    return lifecycle


def _latest_adopt_action_for_candidate(candidate_id, requested_action_id=""):
    actions, _ = _xingce_work_experience_action_history(candidate_id, limit=1000000)
    for action in actions:
        if action.get("action") != "adopt_as_experience":
            continue
        if action.get("action_status") != "queued_for_experience_service_review":
            continue
        if requested_action_id and action.get("action_id") != requested_action_id:
            continue
        return action
    return {}


def apply_experience_service_xingce_adoption(candidate_id, body=None):
    body = body or {}
    detail = get_xingce_work_experience_candidate(candidate_id)
    if not detail.get("ok"):
        return detail
    candidate = detail.get("candidate", {})
    safe_id = _safe_hermes_candidate_id(candidate.get("candidate_id", candidate_id))
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        return _hermes_feedback_action_bool(authorization.get(name, body.get(name)))

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    requested_action_id = str(body.get("action_id", "") or authorization.get("action_id", "") or "").strip()
    action = _latest_adopt_action_for_candidate(safe_id, requested_action_id=requested_action_id)
    evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []
    raw_source_refs = candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []
    exp_id = _stable_xingce_case_exp_id(safe_id)
    existing_record = _find_case_memory_record(exp_id)
    existing_refs = _decode_record_source_refs(existing_record)
    existing_candidate_id = (
        (existing_refs.get("experience_service", {}) if isinstance(existing_refs.get("experience_service"), dict) else {}).get("candidate_id")
        or existing_refs.get("candidate_id", "")
    )

    required_checks = {
        "confirm_adopt_production_experience": confirmed("confirm_adopt_production_experience"),
        "confirm_write_zhiyi_case_memory": confirmed("confirm_write_zhiyi_case_memory"),
        "confirm_write_zhiyi_lifecycle_overlay": confirmed("confirm_write_zhiyi_lifecycle_overlay"),
        "confirm_preserve_raw_source_refs": confirmed("confirm_preserve_raw_source_refs"),
        "confirm_projection_not_desensitized": confirmed("confirm_projection_not_desensitized"),
        "confirm_no_raw_xingce_hermes_openclaw_write": confirmed("confirm_no_raw_xingce_hermes_openclaw_write"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    write_boundary = candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {}
    guard_checks = {
        "candidate_id_safe": bool(safe_id),
        "candidate_type": candidate.get("candidate_type") == "xingce_work_experience",
        "candidate_lifecycle_status": candidate.get("lifecycle_status") == "candidate",
        "candidate_artifact_exists": os.path.isfile(detail.get("source_path", "")),
        "queued_adopt_action_exists": bool(action),
        "source_mode_raw_source_refs": candidate.get("source_mode") == "raw_source_refs",
        "evidence_refs_present": len(evidence_refs) > 0,
        "raw_source_refs_present": len(raw_source_refs) > 0,
        "case_exp_id_unclaimed_or_same_candidate": not existing_record or existing_candidate_id == safe_id,
        "candidate_not_production_written": not bool(write_boundary.get("production_experience_write_performed", False)),
        "raw_write_stays_false": not bool(write_boundary.get("raw_write_performed", False)),
        "xingce_write_stays_false": not bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_stays_false": not bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_stays_false": not bool(write_boundary.get("openclaw_write_performed", False)),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "production_experience_write_performed": False,
            "zhiyi_write_performed": False,
            "raw_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
            "candidate_id": safe_id,
            "exp_id": exp_id,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": required_checks,
            "guard_checks": guard_checks,
            "guard_failures": guard_failures,
            "error": "blocked_missing_authorization_or_guard_failure",
        }

    import uuid
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_display = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    case_record = existing_record or _candidate_to_case_memory_record(candidate, detail, action, exp_id, authorization, now_display)
    case_memory_append_performed = False
    if not existing_record:
        _jsonl_append(_zhiyi_case_memory_path(), case_record)
        case_memory_append_performed = True

    latest_lifecycle = _latest_case_memory_lifecycle_record(exp_id)
    latest_decision = latest_lifecycle.get("conflict_decision", "")
    lifecycle_append_performed = False
    lifecycle_version = int(latest_lifecycle.get("lifecycle_version", 0) or 0)
    if latest_decision != "active":
        lifecycle = _case_memory_lifecycle_record(
            case_record,
            status="active",
            conflict_decision="active",
            lifecycle_version=lifecycle_version + 1,
            reason=str(authorization.get("reason", body.get("reason", "")) or "experience service adoption"),
            now_display=now_display,
        )
        _jsonl_append(_zhiyi_case_memory_lifecycle_path(), lifecycle)
        lifecycle_append_performed = True

    receipt_id = "experience-adoption-" + uuid.uuid4().hex[:16]
    receipt = {
        "schema_version": "1.0",
        "receipt_id": receipt_id,
        "created_at": now_iso,
        "candidate_id": safe_id,
        "source_candidate_path": detail.get("source_path", ""),
        "source_action_id": action.get("action_id", ""),
        "source_action_path": action.get("_source_path", ""),
        "exp_id": exp_id,
        "target_case_memory_path": _zhiyi_case_memory_path(),
        "target_lifecycle_path": _zhiyi_case_memory_lifecycle_path(),
        "operator": str(authorization.get("operator", body.get("operator", "")) or ""),
        "reason": str(authorization.get("reason", body.get("reason", "")) or ""),
        "case_memory_append_performed": case_memory_append_performed,
        "lifecycle_append_performed": lifecycle_append_performed,
        "idempotent_existing_case_memory": bool(existing_record),
        "idempotent_existing_active_lifecycle": bool(latest_decision == "active"),
        "source_refs_preserved": True,
        "projection_desensitized": False,
        "write_boundary": {
            "adoption_receipt_write_performed": True,
            "production_experience_write_performed": bool(case_memory_append_performed or lifecycle_append_performed),
            "raw_write_performed": False,
            "zhiyi_write_performed": bool(case_memory_append_performed or lifecycle_append_performed),
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "notes": [
            "live_experience_service_adoption",
            "raw_source_refs_preserved_without_desensitization",
            "candidate_and_action_artifacts_not_modified",
        ],
    }
    adoptions_dir = _experience_service_adoptions_dir()
    os.makedirs(adoptions_dir, exist_ok=True)
    receipt_path = os.path.join(adoptions_dir, f"{now_iso.replace(':', '').replace('-', '')}-{safe_id}-adopt.jsonl")
    _jsonl_append(receipt_path, receipt)
    latest_path = os.path.join(adoptions_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    production_write = bool(case_memory_append_performed or lifecycle_append_performed)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "adoption_receipt_write_performed": True,
        "production_experience_write_performed": production_write,
        "raw_write_performed": False,
        "zhiyi_write_performed": production_write,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidate_id": safe_id,
        "exp_id": exp_id,
        "case_memory_append_performed": case_memory_append_performed,
        "lifecycle_append_performed": lifecycle_append_performed,
        "source_refs_preserved": True,
        "projection_desensitized": False,
        "receipt_id": receipt_id,
        "receipt_path": receipt_path,
        "latest_path": latest_path,
        "receipt": receipt,
    }


def apply_experience_service_case_memory_rollback(exp_id, body=None):
    body = body or {}
    safe_exp_id = _safe_experience_id(exp_id)
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        return _hermes_feedback_action_bool(authorization.get(name, body.get(name)))

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    case_record = _find_case_memory_record(safe_exp_id)
    latest_lifecycle = _latest_case_memory_lifecycle_record(safe_exp_id)
    required_checks = {
        "confirm_rollback_production_experience": confirmed("confirm_rollback_production_experience"),
        "confirm_write_zhiyi_lifecycle_overlay": confirmed("confirm_write_zhiyi_lifecycle_overlay"),
        "confirm_preserve_case_memory_file": confirmed("confirm_preserve_case_memory_file"),
        "confirm_no_raw_xingce_hermes_openclaw_write": confirmed("confirm_no_raw_xingce_hermes_openclaw_write"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    guard_checks = {
        "exp_id_safe": bool(safe_exp_id),
        "case_memory_record_exists": bool(case_record),
        "case_memory_file_exists": os.path.isfile(_zhiyi_case_memory_path()),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "production_experience_write_performed": False,
            "zhiyi_write_performed": False,
            "raw_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
            "exp_id": safe_exp_id,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": required_checks,
            "guard_checks": guard_checks,
            "guard_failures": guard_failures,
            "error": "blocked_missing_authorization_or_guard_failure",
        }

    import uuid
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_display = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    already_superseded = latest_lifecycle.get("conflict_decision") == "superseded"
    lifecycle_append_performed = False
    if not already_superseded:
        lifecycle_version = int(latest_lifecycle.get("lifecycle_version", case_record.get("lifecycle_version", 1)) or 1)
        lifecycle = _case_memory_lifecycle_record(
            case_record,
            status="superseded",
            conflict_decision="superseded",
            lifecycle_version=lifecycle_version + 1,
            reason=str(authorization.get("reason", body.get("reason", "")) or "experience service rollback"),
            now_display=now_display,
        )
        _jsonl_append(_zhiyi_case_memory_lifecycle_path(), lifecycle)
        lifecycle_append_performed = True

    rollback_id = "experience-rollback-" + uuid.uuid4().hex[:16]
    receipt = {
        "schema_version": "1.0",
        "rollback_id": rollback_id,
        "created_at": now_iso,
        "exp_id": safe_exp_id,
        "target_case_memory_path": _zhiyi_case_memory_path(),
        "target_lifecycle_path": _zhiyi_case_memory_lifecycle_path(),
        "operator": str(authorization.get("operator", body.get("operator", "")) or ""),
        "reason": str(authorization.get("reason", body.get("reason", "")) or ""),
        "case_memory_deleted": False,
        "case_memory_preserved": True,
        "lifecycle_append_performed": lifecycle_append_performed,
        "idempotent_existing_superseded_lifecycle": already_superseded,
        "write_boundary": {
            "rollback_receipt_write_performed": True,
            "production_experience_write_performed": bool(lifecycle_append_performed),
            "raw_write_performed": False,
            "zhiyi_write_performed": bool(lifecycle_append_performed),
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "notes": [
            "live_experience_service_rollback",
            "rollback_uses_lifecycle_overlay_no_case_memory_delete",
            "raw_source_refs_preserved_without_desensitization",
        ],
    }
    rollbacks_dir = _experience_service_rollbacks_dir()
    os.makedirs(rollbacks_dir, exist_ok=True)
    receipt_path = os.path.join(rollbacks_dir, f"{now_iso.replace(':', '').replace('-', '')}-{safe_exp_id}-rollback.jsonl")
    _jsonl_append(receipt_path, receipt)
    latest_path = os.path.join(rollbacks_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "rollback_receipt_write_performed": True,
        "production_experience_write_performed": bool(lifecycle_append_performed),
        "raw_write_performed": False,
        "zhiyi_write_performed": bool(lifecycle_append_performed),
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "exp_id": safe_exp_id,
        "case_memory_deleted": False,
        "case_memory_preserved": True,
        "lifecycle_append_performed": lifecycle_append_performed,
        "rollback_id": rollback_id,
        "receipt_path": receipt_path,
        "latest_path": latest_path,
        "receipt": receipt,
    }


def _hermes_upgrade_input_flags(upgrade_input):
    fresh = upgrade_input.get("fresh_observation", {}) if isinstance(upgrade_input.get("fresh_observation"), dict) else {}
    flags = fresh.get("observed_write_flags", {}) if isinstance(fresh.get("observed_write_flags"), dict) else {}
    return {
        "skill": bool(flags.get("skill", False)),
        "learning": bool(flags.get("learning", False)),
        "memory": bool(flags.get("memory", False)),
    }


def _case_memory_upgrade_source_refs(existing_record, upgrade_input, upgrade_detail, authorization):
    source_refs = _decode_record_source_refs(existing_record)
    if not source_refs:
        source_refs = {}
    experience_service = source_refs.get("experience_service", {})
    if not isinstance(experience_service, dict):
        experience_service = {}
    upgrades = experience_service.get("upgrades", [])
    if not isinstance(upgrades, list):
        upgrades = []
    fresh = upgrade_input.get("fresh_observation", {}) if isinstance(upgrade_input.get("fresh_observation"), dict) else {}
    comparison = upgrade_input.get("comparison_result", {}) if isinstance(upgrade_input.get("comparison_result"), dict) else {}
    upgrade_ref = {
        "source": "hermes_feedback_upgrade_input",
        "upgrade_input_id": upgrade_input.get("upgrade_input_id", ""),
        "upgrade_input_path": upgrade_detail.get("source_path", ""),
        "candidate_id": upgrade_input.get("candidate_id", ""),
        "fresh_change_class": comparison.get("fresh_change_class", ""),
        "native_change_observed_after_action": bool(comparison.get("native_change_observed_after_action", False)),
        "observed_write_flags": _hermes_upgrade_input_flags(upgrade_input),
        "source_refs": fresh.get("source_refs", []) if isinstance(fresh.get("source_refs"), list) else [],
        "operator_reason": str(authorization.get("reason", "") or ""),
        "projection_desensitized": False,
        "raw_projection_policy": "preserve_verbatim_refs",
    }
    upgrades.append(upgrade_ref)
    experience_service["last_upgrade"] = upgrade_ref
    experience_service["upgrades"] = upgrades
    experience_service["projection_desensitized"] = False
    experience_service["raw_projection_policy"] = "preserve_verbatim_refs"
    source_refs["experience_service"] = experience_service
    return source_refs


def _case_memory_record_with_hermes_upgrade(existing_record, upgrade_input, upgrade_detail, authorization, lifecycle_version, now_display):
    import hashlib
    upgraded = dict(existing_record)
    upgrade_input_id = str(upgrade_input.get("upgrade_input_id", "") or "")
    flags = _hermes_upgrade_input_flags(upgrade_input)
    comparison = upgrade_input.get("comparison_result", {}) if isinstance(upgrade_input.get("comparison_result"), dict) else {}
    fresh = upgrade_input.get("fresh_observation", {}) if isinstance(upgrade_input.get("fresh_observation"), dict) else {}
    base_summary = str(existing_record.get("summary", "") or "")
    if "经验语义升级" not in base_summary:
        summary = f"案例：[经验语义升级] {base_summary}"
    else:
        summary = base_summary
    summary = f"{summary}。upgrade_input_id={upgrade_input_id}"
    detail_parts = [
        str(existing_record.get("detail", "") or ""),
        f"experience_upgrade_source=hermes_feedback_upgrade_input",
        f"upgrade_input_id={upgrade_input_id}",
        f"candidate_id={upgrade_input.get('candidate_id', '')}",
        f"fresh_change_class={comparison.get('fresh_change_class', '')}",
        f"native_change_observed_after_action={comparison.get('native_change_observed_after_action', False)}",
        f"observed_write_flags={json.dumps(flags, ensure_ascii=False, sort_keys=True)}",
        f"agent_created_skill_count={fresh.get('agent_created_skill_count', 0)}",
        f"operator_reason={authorization.get('reason', '')}",
    ]
    upgraded.update({
        "summary": summary,
        "detail": "\n".join(part for part in detail_parts if part),
        "source_refs": json.dumps(
            _case_memory_upgrade_source_refs(existing_record, upgrade_input, upgrade_detail, authorization),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "score": max(float(existing_record.get("score", 0.75) or 0.75), 0.8),
        "extracted_at": now_display,
        "lifecycle_version": lifecycle_version,
        "memory_id": hashlib.sha256(
            f"{existing_record.get('exp_id', '')}:{upgrade_input_id}:production_case_memory_upgrade:{lifecycle_version}".encode("utf-8")
        ).hexdigest(),
    })
    return upgraded


def _case_memory_has_upgrade(record, upgrade_input_id):
    refs = _decode_record_source_refs(record)
    experience_service = refs.get("experience_service", {}) if isinstance(refs, dict) else {}
    if not isinstance(experience_service, dict):
        return False
    last_upgrade = experience_service.get("last_upgrade", {})
    if isinstance(last_upgrade, dict) and last_upgrade.get("upgrade_input_id") == upgrade_input_id:
        return True
    upgrades = experience_service.get("upgrades", [])
    if isinstance(upgrades, list):
        return any(isinstance(item, dict) and item.get("upgrade_input_id") == upgrade_input_id for item in upgrades)
    return False


def apply_experience_service_hermes_upgrade_input(upgrade_input_id, body=None):
    body = body or {}
    detail = get_hermes_feedback_upgrade_input(upgrade_input_id)
    if not detail.get("ok"):
        return detail
    upgrade_input = detail.get("upgrade_input", {})
    safe_upgrade_id = _safe_hermes_candidate_id(upgrade_input.get("upgrade_input_id", upgrade_input_id))
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        return _hermes_feedback_action_bool(authorization.get(name, body.get(name)))

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    target_exp_id = _safe_experience_id(
        body.get("target_exp_id", "") or authorization.get("target_exp_id", "")
    )
    existing_record = _latest_case_memory_record(target_exp_id) if target_exp_id else {}
    latest_lifecycle = _latest_case_memory_lifecycle_record(target_exp_id) if target_exp_id else {}
    flags = _hermes_upgrade_input_flags(upgrade_input)
    comparison = upgrade_input.get("comparison_result", {}) if isinstance(upgrade_input.get("comparison_result"), dict) else {}
    write_boundary = upgrade_input.get("write_boundary", {}) if isinstance(upgrade_input.get("write_boundary"), dict) else {}

    required_checks = {
        "confirm_apply_production_experience_upgrade": confirmed("confirm_apply_production_experience_upgrade"),
        "confirm_write_zhiyi_case_memory": confirmed("confirm_write_zhiyi_case_memory"),
        "confirm_write_zhiyi_lifecycle_overlay": confirmed("confirm_write_zhiyi_lifecycle_overlay"),
        "confirm_preserve_raw_source_refs": confirmed("confirm_preserve_raw_source_refs"),
        "confirm_projection_not_desensitized": confirmed("confirm_projection_not_desensitized"),
        "confirm_no_raw_xingce_hermes_openclaw_write": confirmed("confirm_no_raw_xingce_hermes_openclaw_write"),
        "target_exp_id": bool(target_exp_id),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    guard_checks = {
        "upgrade_input_id_safe": bool(safe_upgrade_id),
        "upgrade_input_artifact_exists": os.path.isfile(detail.get("source_path", "")),
        "upgrade_input_ready": bool(upgrade_input.get("experience_upgrade_ready", False)),
        "upgrade_input_status_ready": upgrade_input.get("upgrade_input_status") == "ready_for_experience_review_native_change_observed",
        "native_change_observed_after_action": bool(comparison.get("native_change_observed_after_action", False)),
        "native_write_flag_present": any(flags.values()),
        "target_case_memory_exists": bool(existing_record),
        "target_case_memory_active": latest_lifecycle.get("conflict_decision") == "active",
        "upgrade_input_not_already_production_written": not bool(upgrade_input.get("production_experience_write_performed", False)),
        "raw_write_stays_false": not bool(write_boundary.get("raw_write_performed", False)),
        "xingce_write_stays_false": not bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_stays_false": not bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_stays_false": not bool(write_boundary.get("openclaw_write_performed", False)),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "production_experience_write_performed": False,
            "zhiyi_write_performed": False,
            "raw_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
            "upgrade_input_id": safe_upgrade_id,
            "target_exp_id": target_exp_id,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": required_checks,
            "guard_checks": guard_checks,
            "guard_failures": guard_failures,
            "error": "blocked_missing_authorization_or_guard_failure",
        }

    import uuid
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_display = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    already_applied = _case_memory_has_upgrade(existing_record, safe_upgrade_id)
    case_memory_append_performed = False
    lifecycle_append_count = 0
    new_lifecycle_version = int(latest_lifecycle.get("lifecycle_version", existing_record.get("lifecycle_version", 1)) or 1)
    upgraded_record = existing_record
    if not already_applied:
        superseded_version = new_lifecycle_version + 1
        active_version = new_lifecycle_version + 2
        superseded = _case_memory_lifecycle_record(
            existing_record,
            status="superseded",
            conflict_decision="superseded",
            lifecycle_version=superseded_version,
            reason=f"superseded by Hermes upgrade input {safe_upgrade_id}",
            now_display=now_display,
        )
        upgraded_record = _case_memory_record_with_hermes_upgrade(
            existing_record,
            upgrade_input,
            detail,
            authorization,
            active_version,
            now_display,
        )
        active = _case_memory_lifecycle_record(
            upgraded_record,
            status="active",
            conflict_decision="active",
            lifecycle_version=active_version,
            reason=str(authorization.get("reason", body.get("reason", "")) or "experience service semantic upgrade"),
            now_display=now_display,
        )
        _jsonl_append(_zhiyi_case_memory_path(), upgraded_record)
        _jsonl_append(_zhiyi_case_memory_lifecycle_path(), superseded)
        _jsonl_append(_zhiyi_case_memory_lifecycle_path(), active)
        case_memory_append_performed = True
        lifecycle_append_count = 2
        new_lifecycle_version = active_version

    upgrade_id = "experience-upgrade-" + uuid.uuid4().hex[:16]
    receipt = {
        "schema_version": "1.0",
        "upgrade_id": upgrade_id,
        "created_at": now_iso,
        "upgrade_input_id": safe_upgrade_id,
        "source_upgrade_input_path": detail.get("source_path", ""),
        "target_exp_id": target_exp_id,
        "target_case_memory_path": _zhiyi_case_memory_path(),
        "target_lifecycle_path": _zhiyi_case_memory_lifecycle_path(),
        "operator": str(authorization.get("operator", body.get("operator", "")) or ""),
        "reason": str(authorization.get("reason", body.get("reason", "")) or ""),
        "case_memory_append_performed": case_memory_append_performed,
        "lifecycle_append_count": lifecycle_append_count,
        "idempotent_existing_upgrade": already_applied,
        "latest_lifecycle_version": new_lifecycle_version,
        "source_refs_preserved": True,
        "projection_desensitized": False,
        "observed_write_flags": flags,
        "write_boundary": {
            "upgrade_receipt_write_performed": True,
            "production_experience_write_performed": bool(case_memory_append_performed or lifecycle_append_count),
            "raw_write_performed": False,
            "zhiyi_write_performed": bool(case_memory_append_performed or lifecycle_append_count),
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "notes": [
            "experience_service_live_semantic_upgrade",
            "upgrade_uses_case_memory_version_and_lifecycle_overlay",
            "raw_source_refs_preserved_without_desensitization",
        ],
    }
    upgrades_dir = _experience_service_upgrades_dir()
    os.makedirs(upgrades_dir, exist_ok=True)
    receipt_path = os.path.join(upgrades_dir, f"{now_iso.replace(':', '').replace('-', '')}-{safe_upgrade_id}-apply.jsonl")
    _jsonl_append(receipt_path, receipt)
    latest_path = os.path.join(upgrades_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    production_write = bool(case_memory_append_performed or lifecycle_append_count)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "upgrade_receipt_write_performed": True,
        "production_experience_write_performed": production_write,
        "raw_write_performed": False,
        "zhiyi_write_performed": production_write,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "upgrade_input_id": safe_upgrade_id,
        "target_exp_id": target_exp_id,
        "case_memory_append_performed": case_memory_append_performed,
        "lifecycle_append_count": lifecycle_append_count,
        "idempotent_existing_upgrade": already_applied,
        "latest_lifecycle_version": new_lifecycle_version,
        "source_refs_preserved": True,
        "projection_desensitized": False,
        "receipt_id": upgrade_id,
        "receipt_path": receipt_path,
        "latest_path": latest_path,
        "receipt": receipt,
        "upgraded_case_memory": upgraded_record,
    }


# OpenClaw chat-send console helpers live under p6_console_openclaw.py.

def _experience_type_label(ftype):
    return {
        "case_memory": "案例经验",
        "error_memory": "错误经验",
        "preference_memory": "偏好经验",
    }.get(ftype, "经验")


def _experience_text(obj):
    if not isinstance(obj, dict):
        return ""
    for key in ("title", "name", "summary", "content", "text", "memory", "description", "answer", "insight"):
        value = obj.get(key)
        if value:
            return _compact_text(value, 260)
    for value in obj.values():
        if isinstance(value, str) and len(value.strip()) >= 8:
            return _compact_text(value, 260)
    return ""


def _experience_title(obj, ftype, index):
    text = _experience_text(obj)
    if text:
        for sep in ("。", "，", ".", ";", "；", ":"):
            if sep in text[:48]:
                text = text.split(sep, 1)[0]
                break
        return _compact_text(text, 30)
    return f"{_experience_type_label(ftype)} {index + 1}"


def _normalize_duplicate_key(title, detail):
    import re
    text = f"{title}|{detail}".lower()
    return re.sub(r"\s+", "", text)


def get_zhiyi_experience_summary(sample_limit=18, duplicate_limit=8):
    stats = get_zhiyi_stats()
    active_stats = {"case_memory": 0, "error_memory": 0, "preference_memory": 0}
    recycle_overlay = _zhiyi_experience_recycle_overlay()
    samples = []
    sample_count_by_type = {}
    duplicate_map = {}
    parse_errors = 0
    for ftype in ["case_memory", "error_memory", "preference_memory"]:
        path = f"{MEMCORE_ROOT}/zhiyi/{ftype}/{ftype}.jsonl"
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for index, line in enumerate(f):
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        parse_errors += 1
                        continue
                    exp_id = obj.get("exp_id", "")
                    if exp_id and exp_id in recycle_overlay:
                        continue
                    active_stats[ftype] = active_stats.get(ftype, 0) + 1
                    title = _experience_title(obj, ftype, index)
                    detail = _experience_text(obj) or title
                    key = _normalize_duplicate_key(title, detail)
                    if key:
                        entry = duplicate_map.setdefault(key, {
                            "title": title,
                            "detail": _compact_text(detail, 160),
                            "type": ftype,
                            "type_label": _experience_type_label(ftype),
                            "count": 0,
                            "exp_ids": [],
                        })
                        entry["count"] += 1
                        if exp_id and exp_id not in entry["exp_ids"]:
                            entry["exp_ids"].append(exp_id)
                    if len(samples) < sample_limit and sample_count_by_type.get(ftype, 0) < max(4, sample_limit // 3):
                        raw_refs = obj.get("source_refs") or obj.get("_source_refs") or {}
                        if isinstance(raw_refs, str):
                            try:
                                raw_refs = json.loads(raw_refs)
                            except Exception:
                                raw_refs = {}
                        if not isinstance(raw_refs, dict):
                            raw_refs = {}
                        obj["_source_refs"] = raw_refs
                        obj.update(attach_archive_card(obj))
                        card = obj.get("archive_card", {})
                        raw_evidence = _m5_raw_evidence_for_refs(raw_refs, excerpt_chars=220)
                        source_path = raw_refs.get("source_path", "")
                        source_label = os.path.basename(source_path) if source_path else ""
                        quote_excerpt = (
                            obj.get("quote_excerpt")
                            or raw_evidence.get("raw_excerpt")
                            or detail
                        )
                        samples.append({
                            "id": f"{ftype}:{index}",
                            "catalog_id": obj.get("catalog_id", ""),
                            "exp_id": exp_id,
                            "type": ftype,
                            "type_label": _experience_type_label(ftype),
                            "title": title,
                            "archive_title": card.get("title", title),
                            "evidence_level": card.get("evidence_level", ""),
                            "archive_status": card.get("status", ""),
                            "one_line_description": _compact_text(detail, 110),
                            "detail": _compact_text(detail, 220),
                            "quote_excerpt": _compact_text(quote_excerpt, 180),
                            "source_label": source_label,
                            "status": obj.get("status") or "adopted",
                            "deleted_state": "active",
                            "has_source_refs": bool(raw_refs),
                        })
                        sample_count_by_type[ftype] = sample_count_by_type.get(ftype, 0) + 1
        except Exception:
            parse_errors += 1
    duplicates = [value for value in duplicate_map.values() if value.get("count", 0) > 1]
    duplicates.sort(key=lambda item: item.get("count", 0), reverse=True)
    return {
        "total": sum(active_stats.values()),
        "raw_total": sum(stats.values()),
        "stats": active_stats,
        "raw_stats": stats,
        "samples": samples,
        "duplicate_candidates": duplicates[:duplicate_limit],
        "duplicate_candidate_count": len(duplicates),
        "delete_supported_now": True,
        "recycle_supported_now": True,
        "delete_requires_future_authorization": False,
        "lifecycle_actions_supported_now": True,
        "lifecycle_action_endpoint": "/api/v1/zhiyi/experiences/{exp_id}/recycle",
        "restore_supported_now": True,
        "restore_endpoint": "/api/v1/zhiyi/experiences/{exp_id}/restore",
        "recycle_bin_endpoint": "/api/v1/zhiyi/experience-recycle-bin",
        "recycle_bin_count": len(recycle_overlay),
        "raw_delete_performed": False,
        "detail_endpoint_available": True,
        "raw_excerpt_available_on_detail": True,
        "parse_errors": parse_errors,
        "detail_is_summary_only": False,
    }


__all__ = [
    "EXPERIENCE_GOVERNANCE_CONTRACT",
    "M6_PROPOSALS_DIR",
    "configure_experience_governance",
    "get_experience_governance_contract",
    "_m6_proposals_dir",
    "_default_get_zhiyi_stats",
    "get_zhiyi_stats",
    "_default_load_zhiyi_objects",
    "load_zhiyi_objects",
    "_default_raw_evidence_for_refs",
    "_m5_raw_evidence_for_refs",
    "_m6_ensure_proposals_dir",
    "_m6_validate_target_exp_ids",
    "_m6_write_proposal",
    "_m6_compute_impact",
    "m6_create_proposal",
    "m5_create_experience_action",
    "m6_list_proposals",
    "m6_get_proposal",
    "m6_get_proposal_summary",
    "m6_get_stats",
    "_hermes_feedback_candidates_dir",
    "_hermes_feedback_actions_dir",
    "_hermes_feedback_upgrade_inputs_dir",
    "_hermes_consumption_receipts_dir",
    "query_hermes_native_learning_liveness",
    "persist_hermes_consumption_receipt",
    "query_hermes_consumption_receipts",
    "build_hermes_self_review_wake_http_dry_run",
    "apply_hermes_self_review_signal_receipt_http",
    "build_hermes_self_review_trigger_http_dry_run",
    "apply_hermes_self_review_trigger_http",
    "query_hermes_self_review_triggers_http",
    "build_hermes_skill_generation_probe_http_dry_run",
    "apply_hermes_skill_generation_probe_http",
    "query_hermes_skill_generation_probes_http",
    "build_hermes_skill_artifact_status_http_dry_run",
    "record_hermes_skill_artifact_status_http",
    "query_hermes_skill_artifact_statuses_http",
    "query_hermes_autonomous_loop_state_http",
    "build_hermes_autonomous_loop_http_dry_run",
    "apply_hermes_autonomous_loop_http",
    "query_hermes_autonomous_loop_runs_http",
    "_xingce_work_experience_candidates_dir",
    "_xingce_work_experience_actions_dir",
    "_experience_service_adoptions_dir",
    "_experience_service_rollbacks_dir",
    "_experience_service_upgrades_dir",
    "_zhixing_replay_feedback_applications_dir",
    "_zhiyi_case_memory_dir",
    "_zhiyi_case_memory_path",
    "_zhiyi_case_memory_lifecycle_path",
    "_hermes_feedback_action_bool",
    "_read_hermes_feedback_json",
    "_safe_hermes_candidate_id",
    "_safe_experience_id",
    "_jsonl_append",
    "_read_jsonl_records",
    "_zhiyi_experience_recycle_path",
    "_zhiyi_experience_recycle_records",
    "_zhiyi_experience_recycle_overlay",
    "_zhiyi_experience_find",
    "recycle_zhiyi_experience",
    "restore_zhiyi_experience",
    "get_zhiyi_experience_recycle_bin",
    "_window_from_raw_source_path",
    "_latest_xingce_work_experience_candidate_id",
    "_xingce_work_experience_candidate_summary",
    "query_zhixing_library",
    "query_zhixing_library_trust_dashboard",
    "get_zhixing_replay_plan",
    "get_zhixing_benchmark_plan",
    "get_time_river_sediment_plan",
    "get_material_processing_pipeline_plan",
    "get_second_brain_plan",
    "apply_zhixing_replay_feedback_candidate",
    "_xingce_work_experience_action_history",
    "query_xingce_work_experience_candidates",
    "query_xingce_work_experience_actions",
    "get_xingce_work_experience_candidate",
    "apply_xingce_work_experience_candidate_action",
    "_first_xingce_evidence_ref",
    "_stable_xingce_case_exp_id",
    "_decode_record_source_refs",
    "_find_case_memory_record",
    "_latest_case_memory_record",
    "_latest_case_memory_lifecycle_record",
    "_candidate_to_case_memory_record",
    "_case_memory_lifecycle_record",
    "_latest_adopt_action_for_candidate",
    "apply_experience_service_xingce_adoption",
    "apply_experience_service_case_memory_rollback",
    "_hermes_upgrade_input_flags",
    "_case_memory_upgrade_source_refs",
    "_case_memory_record_with_hermes_upgrade",
    "_case_memory_has_upgrade",
    "apply_experience_service_hermes_upgrade_input",
    "_hermes_feedback_candidate_summary",
    "_hermes_feedback_upgrade_input_summary",
    "_latest_hermes_feedback_candidate_id",
    "_latest_hermes_feedback_upgrade_input_id",
    "_hermes_feedback_action_history",
    "query_hermes_feedback_candidates",
    "query_hermes_feedback_actions",
    "query_hermes_feedback_upgrade_inputs",
    "get_hermes_feedback_upgrade_input",
    "get_hermes_feedback_candidate",
    "apply_hermes_feedback_candidate_action",
    "_experience_type_label",
    "_experience_text",
    "_experience_title",
    "_normalize_duplicate_key",
    "get_zhiyi_experience_summary",
]
