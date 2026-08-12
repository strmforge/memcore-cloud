import importlib
import importlib.util
import hashlib
import json
import os
import sqlite3
import sys
import threading
import types
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _reload_modules(tmp_path):
    root = tmp_path / "memcore"
    root.mkdir(parents=True, exist_ok=True)
    (root / "VERSION").write_text("2099.1.2\n", encoding="utf-8")
    os.environ["MEMCORE_ROOT"] = str(root)
    os.environ["MEMCORE_CONFIG"] = str(ROOT / "config" / "memcore.json")
    os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(root / "zhiyi")
    os.environ["MEMCORE_PROJECT_STATUS_ROOT_OVERRIDE"] = str(root)
    os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(root)
    os.environ["MEMCORE_P3_RECALL_TRANSPORT"] = "inline"
    for name in [
        "config_loader",
        "src.config_loader",
        "memcore_version",
        "src.memcore_version",
        "src.p3_recall",
        "src.raw_consumption_gateway",
    ]:
        sys.modules.pop(name, None)
    p3 = importlib.import_module("src.p3_recall")
    raw_gateway = importlib.import_module("src.raw_consumption_gateway")
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    return p3, raw_gateway


def _clear_raw_gateway_env():
    for key in [
        "MEMCORE_RAW_GATEWAY_STATE_DIR",
        "MEMCORE_RAW_SEGMENT_BYTES",
        "MEMCORE_RAW_SEGMENT_MAX_SEGMENTS",
        "MEMCORE_RAW_EXCERPT_DEADLINE_SECONDS",
    ]:
        os.environ.pop(key, None)


def _mcp_connection_context(
    tmp_path,
    client_name,
    *,
    token="session-a",
    client_version="1",
    inferred_platform_hint="",
    proof_library_id="",
    proof_source_system_filter="",
    proof_matched_count=1,
    proof_source_refs_count=1,
    proof_raw_excerpt_returned=False,
):
    normalized_hint = (
        str(inferred_platform_hint).strip()
        or str(client_name).strip().lower().replace("-", "_").replace(" ", "_")
    )
    context = {
        "transport_session_id": f"{tmp_path}:{token}",
        "initialized": True,
        "client_info_present": bool(str(client_name).strip()),
        "client_name": str(client_name),
        "client_version": str(client_version),
        "inferred_platform_hint": normalized_hint,
        "capability_check_observed_at_epoch": 0.5,
    }
    if proof_library_id:
        context["real_recall_proofs"] = {
            proof_library_id: {
                "library_id": proof_library_id,
                "matched_count": proof_matched_count,
                "source_refs_count": proof_source_refs_count,
                "raw_excerpt_returned": proof_raw_excerpt_returned,
                "recall_source_system_filter": proof_source_system_filter,
                "observed_at_epoch": 1.0,
            }
        }
    return context


def _write_declared_source_filter_binding(
    tmp_path,
    *,
    source_system,
    canonical_window_id,
    session_id,
    source_system_filters,
):
    path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "current_windows": {
                    source_system: {
                        "source_system": source_system,
                        "canonical_window_id": canonical_window_id,
                        "session_id": session_id,
                        "metadata": {
                            "source_system_filters": list(source_system_filters),
                            "source_system_filter_authority": "host_declared_binding",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_memory(
    tmp_path,
    source_system,
    session_id,
    msg_id,
    summary,
    content,
    window_id="project-a",
    project_id="",
    project_root="",
    workstream_id="",
    task_id="",
    memory_type="case_memory",
):
    root = tmp_path / "memcore"
    raw_path = root / "memory" / source_system / "local" / window_id / f"{session_id}.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps({
            "timestamp": msg_id,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
            },
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    refs = {
        "source_system": source_system,
        "computer_name": "local",
        "canonical_window_id": window_id,
        "session_id": session_id,
        "project_id": project_id,
        "project_root": project_root,
        "workstream_id": workstream_id,
        "task_id": task_id,
        "source_path": str(raw_path),
        "msg_ids": [msg_id],
        "artifact_type": f"{source_system}_session_jsonl",
    }
    record = {
        "exp_id": f"exp-{source_system}-{session_id}",
        "type": memory_type,
        "canonical_window_id": window_id,
        "session_id": session_id,
        "project_id": project_id,
        "project_root": project_root,
        "workstream_id": workstream_id,
        "task_id": task_id,
        "computer_id": "local",
        "source_system": source_system,
        "scope": f"window/{window_id}",
        "summary": summary,
        "detail": "shared-base smoke marker Time Library Codex OpenClaw Hermes",
        "source_refs": json.dumps(refs, ensure_ascii=False),
        "score": 0.8,
    }
    zhiyi_path = root / "zhiyi" / memory_type / f"{memory_type}.jsonl"
    zhiyi_path.parent.mkdir(parents=True, exist_ok=True)
    with zhiyi_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_canonical_message(
    tmp_path,
    *,
    source_system="claude_code_cli",
    computer_name="WINNODEA",
    session_id="session-a",
    window_id="window-a",
    project_id="memcore-cloud",
    project_root="",
    content_preview="canonical preview",
    message_id=None,
    record_id=None,
    native_id=None,
    role="assistant",
    native_type=None,
    timestamp="2026-06-15T12:21:00Z",
    line_no=1,
    updated_at="2026-06-15T12:21:01Z",
    raw_path_override=None,
    raw_bytes=None,
    raw_offset_start=0,
    raw_offset_end=200,
):
    root = tmp_path / "memcore"
    records_db = root / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    raw_path = (
        Path(raw_path_override)
        if raw_path_override is not None
        else root / "memory" / computer_name / source_system / f"{source_system}_session_jsonl" / window_id / f"{session_id}.jsonl"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_bytes is None:
        raw_path.write_text("", encoding="utf-8")
    else:
        raw_path.write_bytes(raw_bytes)
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table if not exists canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
        conn.execute(
            "create index if not exists idx_canonical_messages_project_time "
            "on canonical_messages(project_id, timestamp desc, line_no desc)"
        )
        conn.execute(
            "create index if not exists idx_canonical_messages_project_root_time "
            "on canonical_messages(project_root, timestamp desc, line_no desc)"
        )
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, project_root, source_path,
                raw_path, role, native_type, native_id, timestamp, line_no,
                raw_line_no, source_offset_start, source_offset_end,
                raw_offset_start, raw_offset_end, content_preview, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id or f"msg-{session_id}",
                record_id or f"record-{session_id}",
                source_system,
                session_id,
                window_id,
                project_id,
                project_root or "/work/memcore-cloud",
                str(raw_path),
                str(raw_path),
                role,
                native_type or f"{source_system}_session_jsonl",
                native_id or f"native-{session_id}",
                timestamp,
                line_no,
                line_no,
                raw_offset_start,
                raw_offset_end,
                raw_offset_start,
                raw_offset_end,
                content_preview,
                updated_at,
            ),
        )
    return records_db, raw_path


def test_canonical_window_index_ranks_full_query_match_before_newer_weak_match(tmp_path, monkeypatch):
    records_db = None
    for index in range(45):
        records_db, _ = _write_canonical_message(
            tmp_path,
            source_system="claude_code_cli",
            session_id="session-a",
            window_id="window-a",
            message_id=f"msg-newer-weak-{index}",
            record_id=f"record-newer-weak-{index}",
            native_id=f"native-newer-weak-{index}",
            timestamp=f"2026-06-23T10:{index:02d}:00Z",
            line_no=index + 2,
            content_preview=f"win-node-a Codex provider bucket 这是一条较新的弱匹配记录 {index}。",
        )
    _write_canonical_message(
        tmp_path,
        source_system="claude_code_cli",
        session_id="session-a",
        window_id="window-a",
        message_id="msg-older-strong",
        record_id="record-older-strong",
        native_id="native-older-strong",
        timestamp="2026-06-22T10:00:00Z",
        line_no=1,
        content_preview="win-node-a Codex provider bucket drift 修复为 model_provider=token。",
    )
    assert records_db is not None
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    sys.modules.pop("src.raw_recall_catalog_index", None)
    catalog_index = importlib.import_module("src.raw_recall_catalog_index")

    items, status = catalog_index.query_canonical_window_index(
        query="win-node-a Codex provider bucket drift",
        source_system="claude_code_cli",
        session_id="session-a",
        canonical_window_id="window-a",
        limit=1,
        excerpt_chars=300,
    )

    assert status == "hit"
    assert items
    assert "model_provider=token" in items[0]["raw_excerpt"]
    assert "较新的弱匹配" not in items[0]["raw_excerpt"]


def _write_hermes_skill_artifact_status(tmp_path):
    root = tmp_path / "memcore"
    status_dir = root / "output" / "hermes_native_learning" / "skill_artifact_status"
    status_dir.mkdir(parents=True, exist_ok=True)
    status = {
        "artifact_type": "hermes_skill_artifact_status",
        "schema_version": "2026.6.1",
        "status_id": "hermes-skill-artifact-status-test",
        "status": "current",
        "project": "memcore-cloud / Time Library",
        "skill_artifact_status": "probe_only_not_adopted",
        "probe_id": "hermes-skill-generation-probe-2fec7027343c3a92",
        "probe_receipt_path": str(root / "output" / "hermes_native_learning" / "skill_generation_probes" / "latest.json"),
        "skill_relative_path": "time_library/zhiyi-recall-check/SKILL.md",
        "skill_path": r"<windows-home>\AppData\Local\hermes\skills\time_library\zhiyi-recall-check\SKILL.md",
        "skill_sha256": "1c2fb11afc3148e5c21686c6401c576b73d483c85753be5803ebc63eec1f1e34",
        "summary": "Hermes skill generation probe verdict: zhiyi-recall-check is probe-only and not adopted.",
        "current_state": "Fresh Hermes did not naturally use MCP recall for the probe verdict.",
        "next_step": "Make this status recallable before any skill adoption.",
        "completed": ["Hermes generated a native skill artifact."],
        "remaining": ["Skill adoption is still blocked by quality review."],
        "limitations": ["This is not production experience adoption."],
        "write_boundary": {
            "write_performed": True,
            "status_receipt_write_performed": True,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_skill_write_performed_by_time_library": False,
            "production_experience_write_performed": False,
            "openclaw_write_performed": False,
        },
    }
    (status_dir / "latest.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_startup_catalog_candidate(tmp_path):
    root = tmp_path / "memcore"
    candidates_dir = root / "output" / "xingce_work_experience" / "candidates"
    actions_dir = root / "output" / "xingce_work_experience" / "actions"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    actions_dir.mkdir(parents=True, exist_ok=True)
    candidate_id = "xingce-startup-catalog-001"
    source_path = root / "raw" / "sessions" / "startup-catalog.jsonl"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("启动书单源片段\n", encoding="utf-8")
    candidate = {
        "candidate_id": candidate_id,
        "candidate_type": "xingce_work_experience",
        "lifecycle_status": "candidate",
        "title": "发布前应执行完整测试",
        "work_scenario": "发布前收口",
        "summary": "正文不应进入 startup catalog",
        "detail": "这是正文 detail，不应进入 startup catalog",
        "recommended_procedure": ["先跑测试再签"],
        "verification_steps": ["测试通过"],
        "evidence_refs": [
            {
                "source_path": str(source_path),
                "canonical_window_id": "startup-window",
                "byte_offsets": {"start": 0, "end": 24},
            }
        ],
        "source_refs": [str(source_path)],
    }
    (candidates_dir / f"{candidate_id}-candidate.json").write_text(
        json.dumps(candidate, ensure_ascii=False),
        encoding="utf-8",
    )
    (actions_dir / "2026-07-01-startup-action.jsonl").write_text(
        json.dumps({
            "candidate_id": candidate_id,
            "action_status": "auto_adopted_evidence_bound",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_startup_catalog_errata_candidate(tmp_path):
    root = tmp_path / "memcore"
    errata_dir = root / "output" / "zhiyi_errata" / "candidates"
    errata_dir.mkdir(parents=True, exist_ok=True)
    source_path = root / "raw" / "sessions" / "startup-errata.jsonl"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    text = "这条旧卡用了转贴的 AI 总结语气，应该换锚到我的原话"
    source_path.write_text(text, encoding="utf-8")
    end = len(text.encode("utf-8"))
    candidate = {
        "candidate_id": "errata-startup-catalog-001",
        "candidate_type": "zhiyi_errata_candidate",
        "library_shelf": "errata",
        "lifecycle_status": "active",
        "type": "errata_record",
        "title": "勘误：旧锚误署 user",
        "summary": "startup initialize 应把 errata 架送达给消费者。",
        "verbatim_excerpt": text,
        "verbatim_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "source_author": "user",
        "source_role": "user",
        "source_mode": "evidence_bound_errata_adjudication",
        "source_refs": {
            "source_system": "claude_code_cli",
            "source_path": str(source_path),
            "source_role": "user",
            "byte_offsets": {"start": 0, "end": end},
            "verbatim_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
        "old_library_id": "ZX-ZHIYI-OLD-001",
        "new_library_id": "ZX-ZHIYI-NEW-001",
        "supersedes": ["ZX-ZHIYI-OLD-001"],
        "conflicts_with": ["ZX-ZHIYI-OLD-001"],
    }
    (errata_dir / "errata-startup-catalog-001.json").write_text(
        json.dumps(candidate, ensure_ascii=False),
        encoding="utf-8",
    )


def test_hermes_normal_raw_pool_requires_explicit_workflow_or_cross_window_flag(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex 共享底座经验",
        "Codex 这条经验来自 Codex 窗口，但只能作为 Hermes 背景记忆。",
    )
    _write_memory(
        tmp_path,
        "openclaw",
        "openclaw-session",
        "msg_001",
        "OpenClaw 共享底座经验",
        "OpenClaw 这条经验来自 OpenClaw 窗口，也只能带来源使用。",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "共享底座经验",
        source_system="",
        computer_name="",
        session_id="",
        limit=5,
        excerpt_chars=200,
        consumer="hermes",
        request_id="test-shared",
        memory_scope="raw_pool",
    )

    assert result["ok"] is True
    assert result["memory_scope"] == "raw_pool"
    assert result["memory_base_scope"] == "shared"
    assert result["scope_missing"] is True
    assert result["recall_status"] == "cross_window_permission_required"
    assert result["cross_window_read"] is True
    assert result["cross_window_read_allowed"] is False
    assert result["cross_window_permission_explicit"] is False
    assert result["cross_window_reason_is_authorization"] is False
    assert result["missing_scope_fields"] == ["allow_cross_window_recall"]
    assert "Every client must pass" in result["window_binding_hint"]
    assert result["matched_count"] == 0
    assert result["items"] == []


def test_hermes_skill_generation_workflow_can_read_shared_base_with_receipt(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex 共享底座经验",
        "Codex 这条经验来自 Codex 窗口，但只能作为 Hermes 背景记忆。",
    )
    _write_memory(
        tmp_path,
        "openclaw",
        "openclaw-session",
        "msg_001",
        "OpenClaw 共享底座经验",
        "OpenClaw 这条经验来自 OpenClaw 窗口，也只能带来源使用。",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "共享底座经验",
        source_system="",
        computer_name="",
        session_id="",
        limit=5,
        excerpt_chars=200,
        consumer="hermes",
        request_id="test-hermes-skill-generation",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
        cross_window_reason="skill_generation",
    )

    assert result["ok"] is True
    assert result["scope_missing"] is False
    assert result["memory_scope"] == "raw_pool"
    assert result["memory_base_scope"] == "shared"
    assert result["cross_window_read"] is True
    assert result["cross_window_read_allowed"] is True
    assert result["cross_window_permission_explicit"] is True
    assert result["cross_window_reason_is_authorization"] is False
    assert result["cross_window_reason"] == "skill_generation"
    assert result["agent_boundary"] == "active_window_first_explicit_broad_scope"
    assert result["injection_boundary"] == "source_refs_only_no_cross_agent_window_write"
    sources = {item["source_system"] for item in result["items"]}
    assert {"codex", "openclaw"}.issubset(sources)


def test_active_default_can_continue_same_project_without_current_window_identity(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-a",
        "2026-05-27T10:00:00Z",
        "Codex active project continuation marker ACTIVE_PROJECT_MARKER",
        "ACTIVE_PROJECT_MARKER should continue across windows in the same project.",
        window_id="window-a",
        project_id="memcore-cloud-rebuilt-20260527",
        project_root="/workspace/memcore-cloud-rebuilt-20260527",
    )
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-b",
        "2026-05-27T10:01:00Z",
        "Codex active project continuation marker ACTIVE_PROJECT_MARKER",
        "ACTIVE_PROJECT_MARKER from another project must not leak.",
        window_id="window-b",
        project_id="other-project",
        project_root="/workspace/other-project",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "ACTIVE_PROJECT_MARKER",
        consumer="codex",
        request_id="test-active-project",
        project_id="memcore-cloud-rebuilt-20260527",
    )

    assert result["ok"] is True
    assert result["memory_scope"] == "active"
    assert result["memory_base_scope"] == "active_layered"
    assert result["scope_missing"] is False
    assert result["cross_window_read"] is False
    assert result["project_id_filter"] == "memcore-cloud-rebuilt-20260527"
    assert result["active_layers_used"] == ["same_project_workspace"]
    assert result["injection_boundary"] == "active_layered_source_refs_only"
    assert result["items"]
    assert {item["project_id"] for item in result["items"]} == {"memcore-cloud-rebuilt-20260527"}
    assert {item["active_memory_layer"] for item in result["items"]} == {"same_project_workspace"}
    assert "another project must not leak" not in json.dumps(result["items"], ensure_ascii=False)


def test_active_default_uses_registry_current_window_with_explicit_source_identity(tmp_path):
    marker = "REGISTRY_CURRENT_WINDOW_MARKER"
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-a",
        "2026-05-27T10:00:00Z",
        "Codex registry current window marker",
        marker,
        window_id="window-a",
    )
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-b",
        "2026-05-27T10:01:00Z",
        "Codex registry current window marker",
        "REGISTRY_OTHER_WINDOW_SHOULD_NOT_LEAK",
        window_id="window-b",
    )
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "codex": {
                        "source_system": "codex",
                        "canonical_window_id": "window-a",
                        "session_id": "codex-session-a",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Codex registry current window marker",
        consumer="codex",
        source_system="codex",
        request_id="test-registry-current-window",
    )

    assert result["memory_scope"] == "active"
    assert result["current_window_binding_applied"] is True
    assert result["current_window_binding_key"] == "codex"
    assert set(result["current_window_binding_fields"]) == {"canonical_window_id", "session_id"}
    assert result["canonical_window_id_filter"] == "window-a"
    assert result["active_layers_used"] == ["current_window"]
    assert result["tiandao_context_package_valid"] is True
    tiandao_pkg = result["tiandao_context_package"]
    assert tiandao_pkg["schema"] == "tiandao_context_package.v1"
    assert tiandao_pkg["contract_role"] == "memory_context_candidate"
    assert tiandao_pkg["source_system"] == "codex"
    assert tiandao_pkg["canonical_window_id"] == "window-a"
    assert tiandao_pkg["session_id"] == "codex-session-a"
    assert tiandao_pkg["memory_context_mode"] == "mode_a"
    assert tiandao_pkg["active_memory_routing_contract"] == "tiandao_active_memory_routing.v1"
    assert tiandao_pkg["tiandao_routing_contract"]["contract"] == "tiandao_active_memory_routing.v1"
    assert tiandao_pkg["active_layers_used"] == ["current_window"]
    assert tiandao_pkg["current_window_binding_applied"] is True
    assert tiandao_pkg["cross_window_read"] is False
    assert tiandao_pkg["cross_window_read_allowed"] is True
    assert tiandao_pkg["scope_enforced"] is True
    assert tiandao_pkg["memory_write"] is False
    assert tiandao_pkg["permission_boundary"]["memory_write_enabled"] is False
    assert tiandao_pkg["permission_boundary"]["apply_to_platform_blocked"] is True
    assert tiandao_pkg["adapter_verdict"]["adapter_verdict"] == "READY_FOR_MEMORY_CONTEXT_CANDIDATE"
    assert tiandao_pkg["validation"]["valid"] is True
    assert tiandao_pkg["source_refs"]
    assert tiandao_pkg["matched_memories"][0]["active_memory_layer"] == "current_window"
    assert result["items"]
    assert {item["session_id"] for item in result["items"]} == {"codex-session-a"}
    assert {item["canonical_window_id"] for item in result["items"]} == {"codex-session-a"}
    assert {item["project_id"] for item in result["items"]} == {"window-a"}
    assert {item["source_refs_canonical_window_id"] for item in result["items"]} == {"window-a"}
    assert marker in result["items"][0]["raw_excerpt"]
    assert "REGISTRY_OTHER_WINDOW_SHOULD_NOT_LEAK" not in json.dumps(result["items"], ensure_ascii=False)


def test_active_default_uses_registry_project_anchor_with_explicit_source_identity(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-old-session",
        "2026-05-27T10:00:00Z",
        "Codex registry same project marker REGISTRY_PROJECT_MARKER",
        "REGISTRY_PROJECT_MARKER can continue in a new window for the same project.",
        window_id="old-window",
        project_id="memcore-cloud-rebuilt-20260527",
        project_root="/workspace/memcore-cloud-rebuilt-20260527",
    )
    _write_memory(
        tmp_path,
        "codex",
        "codex-other-session",
        "2026-05-27T10:01:00Z",
        "Codex registry same project marker REGISTRY_PROJECT_MARKER",
        "REGISTRY_OTHER_PROJECT_SHOULD_NOT_LEAK",
        window_id="other-window",
        project_id="other-project",
        project_root="/workspace/other-project",
    )
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "codex": {
                        "source_system": "codex",
                        "canonical_window_id": "new-window",
                        "session_id": "new-session",
                        "metadata": {
                            "project_id": "memcore-cloud-rebuilt-20260527",
                            "project_root": "/workspace/memcore-cloud-rebuilt-20260527",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "REGISTRY_PROJECT_MARKER",
        consumer="codex",
        source_system="codex",
        request_id="test-registry-project-anchor",
    )

    assert result["memory_scope"] == "active"
    assert result["current_window_binding_applied"] is True
    assert result["canonical_window_id_filter"] == "new-window"
    assert result["project_id_filter"] == "memcore-cloud-rebuilt-20260527"
    assert result["active_layers_used"] == ["same_project_workspace"]
    assert result["tiandao_context_package_valid"] is True
    assert result["tiandao_context_package"]["schema"] == "tiandao_context_package.v1"
    assert result["tiandao_context_package"]["memory_context_mode"] == "mode_b"
    assert result["tiandao_context_package"]["active_layers_used"] == ["same_project_workspace"]
    assert result["tiandao_context_package"]["current_window_binding_applied"] is True
    assert result["items"]
    assert {item["project_id"] for item in result["items"]} == {"memcore-cloud-rebuilt-20260527"}
    assert {item["active_memory_layer"] for item in result["items"]} == {"same_project_workspace"}
    assert "REGISTRY_OTHER_PROJECT_SHOULD_NOT_LEAK" not in json.dumps(result["items"], ensure_ascii=False)


def test_active_bound_empty_window_falls_back_to_same_project_cross_source(tmp_path, monkeypatch):
    marker = "CLAUDE_EMPTY_WINDOW_PROJECT_FALLBACK_MARKER"
    _write_canonical_message(
        tmp_path,
        source_system="codex",
        session_id="codex-project-session",
        window_id="codex-old-window",
        project_id="time-library-project",
        content_preview=f"{marker} source-backed project evidence should surface in an empty Claude Code window.",
    )
    _write_canonical_message(
        tmp_path,
        source_system="claude_code_cli",
        session_id="claude-other-session",
        window_id="claude-other-window",
        project_id="other-project",
        content_preview=f"{marker} OTHER_PROJECT_SHOULD_NOT_LEAK even though it is the same source system.",
    )
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_code_cli": {
                        "source_system": "claude_code_cli",
                        "canonical_window_id": "claude-live-window",
                        "session_id": "claude-live-session",
                        "metadata": {
                            "project_id": "time-library-project",
                            "project_root": "/workspace/time-library",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    def bounded_recall_only(body):
        assert body.get("source_system_filter") == "claude_code_cli"
        return {"matched_memories": []}

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", lambda: bounded_recall_only)
    result = raw_gateway.query_raw_source_refs(
        marker,
        consumer="claude_code_hook",
        source_system="claude_code_cli",
        request_id="test-empty-window-project-fallback",
    )

    assert result["memory_scope"] == "active"
    assert result["current_window_binding_applied"] is True
    assert result["canonical_window_id_filter"] == "claude-live-window"
    assert result["active_empty_window_project_fallback_used"] is True
    assert result["active_empty_window_project_fallback_status"] == "hit"
    assert result["active_empty_window_project_fallback_index_status"] == "hit"
    assert result["active_empty_window_project_fallback_policy"] == "same_project_workstream_only_source_backed_no_raw_pool"
    assert result["active_empty_window_project_fallback_source_system_filters"] == ["all"]
    assert result["active_layers_used"] == ["same_project_workspace"]
    assert result["items"]
    assert {item["source_system"] for item in result["items"]} == {"codex"}
    assert {item["project_id"] for item in result["items"]} == {"time-library-project"}
    assert {item["active_memory_layer"] for item in result["items"]} == {"same_project_workspace"}
    assert result["source_refs_count"] > 0
    assert result["raw_items_count"] > 0
    assert marker in result["items"][0]["raw_excerpt"]
    assert "OTHER_PROJECT_SHOULD_NOT_LEAK" not in json.dumps(result["items"], ensure_ascii=False)
    assert result["cross_window_read"] is False
    assert result["injection_boundary"] == "active_layered_source_refs_only"


def test_preflight_bound_empty_window_project_fallback_surfaces_source_backed_context(tmp_path, monkeypatch):
    marker = "CLAUDE_EMPTY_WINDOW_PREFLIGHT_SURFACE_MARKER"
    _write_canonical_message(
        tmp_path,
        source_system="codex",
        session_id="codex-project-session",
        window_id="codex-old-window",
        project_id="time-library-project",
        content_preview=f"继续 route B L2 验收：{marker} source-backed same project evidence should surface.",
    )
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_code_cli": {
                        "source_system": "claude_code_cli",
                        "canonical_window_id": "claude-live-window",
                        "session_id": "claude-live-session",
                        "metadata": {
                            "project_id": "time-library-project",
                            "project_root": "/workspace/time-library",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    def bounded_recall_only(body):
        assert body.get("source_system_filter") == "claude_code_cli"
        return {"matched_memories": []}

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", lambda: bounded_recall_only)
    result = raw_gateway.preflight_payload(
        f"继续 route B L2 验收 {marker}",
        consumer="claude_code_hook",
        source_system="claude_code_cli",
        session_id="claude-live-session",
        canonical_window_id="claude-live-window",
        request_id="test-empty-window-project-preflight-surface",
        fast_window_preflight=False,
    )

    assert result["decision"] == "surface"
    assert result["should_surface"] is True
    assert result["scope_missing"] is False
    assert result["active_empty_window_project_fallback_used"] is True
    assert result["active_empty_window_project_fallback_status"] == "hit"
    assert result["active_empty_window_project_fallback_index_status"] == "hit"
    assert result["active_layers_used"] == ["same_project_workspace"]
    assert result["matched_count"] > 0
    assert result["source_refs_count"] > 0
    assert result["raw_items_count"] > 0
    assert result["must_surface"]
    assert result["must_surface"][0]["source_system"] == "codex"
    assert result["must_surface"][0]["active_memory_layer"] == "same_project_workspace"


def test_active_preflight_bound_empty_window_uses_project_index_without_cold_recall(tmp_path, monkeypatch):
    marker = "CLAUDE_ACTIVE_PREFLIGHT_PROJECT_INDEX_MARKER"
    _write_canonical_message(
        tmp_path,
        source_system="codex",
        session_id="codex-project-session",
        window_id="codex-old-window",
        project_id="time-library-project",
        content_preview=f"继续 L2 route B：{marker} should surface from same project canonical index.",
    )
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_code_cli": {
                        "source_system": "claude_code_cli",
                        "canonical_window_id": "claude-live-window",
                        "session_id": "claude-live-session",
                        "metadata": {
                            "project_id": "time-library-project",
                            "project_root": "/workspace/time-library",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    def fail_cold_recall():
        raise AssertionError("active Claude preflight route B must stay on canonical indexes")

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", fail_cold_recall)
    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 77,
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "query": f"继续 L2 route B {marker}",
                "mode": "preflight",
                "consumer": "claude_code_hook",
                "source_system": "claude_code_cli",
                "memory_scope": "active",
                "canonical_window_id": "claude-live-window",
                "session_id": "claude-live-session",
                "project_id": "time-library-project",
                "project_root": "/workspace/time-library",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["decision"] == "surface"
    assert content["should_surface"] is True
    assert content["fast_window_preflight"] is True
    assert content["fast_recall_path"] == "canonical_window_index+canonical_project_index"
    assert content["fast_window_index_status"] == "project_fallback_hit"
    assert content["active_empty_window_project_fallback_used"] is True
    assert content["active_empty_window_project_fallback_index_status"] == "hit"
    assert content["active_layers_used"] == ["same_project_workspace"]
    assert content["source_refs_count"] > 0
    assert content["raw_items_count"] > 0
    assert content["must_surface"][0]["source_system"] == "codex"
    assert content["must_surface"][0]["active_memory_layer"] == "same_project_workspace"
    assert content["raw_fallback_status"] == "skipped_active_project_index_hit"


def test_active_project_fallback_query_uses_indexed_plans(tmp_path):
    marker = "INDEXED_PROJECT_FALLBACK_QUERY_MARKER"
    records_db, _ = _write_canonical_message(
        tmp_path,
        source_system="claude_code_cli",
        session_id="declared-session",
        window_id="declared-window",
        project_id="time-library-project-abc123",
        project_root="/workspace/time-library",
        content_preview=f"{marker} indexed project fallback evidence.",
    )
    _, raw_gateway = _reload_modules(tmp_path)
    conn = sqlite3.connect(records_db)
    conn.row_factory = sqlite3.Row
    try:
        plans = []
        for sql, params in raw_gateway._project_row_query_plans(
            project_id="time-library-project",
            project_root="/workspace/time-library",
            row_limit=20,
        ):
            plans.extend(
                str(item[-1])
                for item in conn.execute("explain query plan " + sql, params).fetchall()
            )
    finally:
        conn.close()

    assert plans
    assert all("SCAN canonical_messages" not in plan for plan in plans)
    assert any("idx_canonical_messages_project_time" in plan for plan in plans)
    assert any("idx_canonical_messages_project_root_time" in plan for plan in plans)


def test_active_project_fallback_resolves_declared_project_to_technical_anchor(tmp_path, monkeypatch):
    marker = "DECLARED_PROJECT_TECHNICAL_ANCHOR_FALLBACK_MARKER"
    _write_canonical_message(
        tmp_path,
        source_system="claude_code_cli",
        session_id="declared-opus-session",
        window_id="declared-opus-session",
        project_id="memcore-cloud-x4-eccd9801",
        project_root="<home>/memcore-cloud-x4",
        content_preview=f"继续 L2 route B {marker} source-backed declared project evidence.",
    )
    reading_registry = tmp_path / "memcore" / "config" / "reading_area_registry.json"
    reading_registry.parent.mkdir(parents=True, exist_ok=True)
    reading_registry.write_text(
        json.dumps(
            {
                "projects": {
                    "project:time-library:03657f57bf": {
                        "id": "project:time-library:03657f57bf",
                        "name": "time-library",
                        "aliases": ["time-library"],
                    }
                },
                "aliases": {
                    "project": {
                        "time-library": "project:time-library:03657f57bf",
                        "project:time-library:03657f57bf": "project:time-library:03657f57bf",
                    }
                },
                "borrowing_cards": {
                    "card:opus": {
                        "source_system": "claude_code",
                        "consumer": "opus",
                        "canonical_window_id": "declared-opus-session",
                        "session_id": "declared-opus-session",
                        "declared_project_ids": ["project:time-library:03657f57bf"],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMCORE_READING_AREA_REGISTRY", str(reading_registry))
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_code_cli": {
                        "source_system": "claude_code_cli",
                        "canonical_window_id": "claude-live-window",
                        "session_id": "claude-live-session",
                        "metadata": {
                            "project_id": "time-library",
                            "project_root": "<workspace-root>/time-library",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    def fail_cold_recall():
        raise AssertionError("declared project route B must stay on canonical indexes")

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", fail_cold_recall)
    result = raw_gateway.preflight_payload(
        f"继续 L2 route B {marker}",
        consumer="claude_code_hook",
        source_system="claude_code_cli",
        session_id="claude-live-session",
        canonical_window_id="claude-live-window",
        project_id="time-library",
        project_root="<workspace-root>/time-library",
        request_id="test-declared-project-technical-anchor",
    )

    assert result["decision"] == "surface"
    assert result["active_empty_window_project_fallback_used"] is True
    assert result["active_empty_window_project_fallback_index_status"] == "hit_declared_project_anchor"
    assert result["active_layers_used"] == ["same_project_workspace"]
    assert result["source_refs_count"] > 0
    assert result["raw_items_count"] > 0
    assert result["must_surface"][0]["project_id"] == "memcore-cloud-x4-eccd9801"
    assert result["must_surface"][0]["active_memory_layer"] == "same_project_workspace"
    assert marker in json.dumps(result["must_surface"], ensure_ascii=False)


def test_active_project_fallback_does_not_starve_later_declared_technical_anchors(tmp_path, monkeypatch):
    marker = "时间双子星"
    for index in range(90):
        _write_canonical_message(
            tmp_path,
            source_system="codex",
            session_id="declared-codex-session",
            window_id="declared-codex-session",
            project_id="codex-technical-project",
            project_root="<home>/codex-worktree",
            message_id=f"codex-noise-{index}",
            record_id=f"codex-noise-record-{index}",
            native_id=f"codex-noise-native-{index}",
            line_no=index + 1,
            timestamp=f"2026-07-05T12:{index % 60:02d}:00Z",
            content_preview=f"Codex same declared project noise {index} without the target evidence.",
        )
    _write_canonical_message(
        tmp_path,
        source_system="claude_code_cli",
        session_id="declared-opus-session",
        window_id="declared-opus-session",
        project_id="memcore-cloud-x4-eccd9801",
        project_root="<home>/memcore-cloud-x4",
        content_preview=f"还记得{marker}吗？{marker}复位证明是 source-backed declared project evidence.",
    )
    reading_registry = tmp_path / "memcore" / "config" / "reading_area_registry.json"
    reading_registry.parent.mkdir(parents=True, exist_ok=True)
    reading_registry.write_text(
        json.dumps(
            {
                "projects": {
                    "project:time-library:03657f57bf": {
                        "id": "project:time-library:03657f57bf",
                        "name": "time-library",
                        "aliases": ["time-library"],
                    }
                },
                "aliases": {
                    "project": {
                        "time-library": "project:time-library:03657f57bf",
                        "project:time-library:03657f57bf": "project:time-library:03657f57bf",
                    }
                },
                "borrowing_cards": {
                    "card:codex": {
                        "source_system": "codex",
                        "consumer": "codex",
                        "canonical_window_id": "declared-codex-session",
                        "session_id": "declared-codex-session",
                        "declared_project_ids": ["project:time-library:03657f57bf"],
                        "technical_anchors": {
                            "project_id": "codex-technical-project",
                            "project_root": "<home>/codex-worktree",
                        },
                    },
                    "card:opus": {
                        "source_system": "claude_code",
                        "consumer": "opus",
                        "canonical_window_id": "declared-opus-session",
                        "session_id": "declared-opus-session",
                        "declared_project_ids": ["project:time-library:03657f57bf"],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMCORE_READING_AREA_REGISTRY", str(reading_registry))
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.preflight_payload(
        f"你还记得{marker}吗",
        consumer="claude_code_hook",
        source_system="claude_code_cli",
        session_id="claude-live-session",
        canonical_window_id="claude-live-window",
        project_id="time-library",
        project_root="<workspace-root>/time-library",
        limit=3,
        request_id="test-declared-project-anchor-no-starvation",
    )

    assert result["decision"] == "surface"
    assert result["active_empty_window_project_fallback_index_status"] == "hit_declared_project_anchor"
    assert result["active_layers_used"] == ["same_project_workspace"]
    assert result["must_surface"][0]["project_id"] == "memcore-cloud-x4-eccd9801"
    assert marker in json.dumps(result["must_surface"], ensure_ascii=False)


def test_active_project_fallback_ignores_tool_runtime_rows(tmp_path, monkeypatch):
    marker = "RUNTIME_TOOL_ROW_MUST_NOT_SURFACE"
    _write_canonical_message(
        tmp_path,
        source_system="codex",
        session_id="codex-tool-session",
        window_id="codex-tool-session",
        project_id="time-library-project",
        project_root="/workspace/time-library",
        role="tool",
        native_type="function_call_output",
        content_preview=f"Chunk ID: abc Output: 继续 {marker} appears only in tool runtime output.",
    )
    _write_canonical_message(
        tmp_path,
        source_system="codex",
        session_id="codex-dialogue-session",
        window_id="codex-dialogue-session",
        project_id="time-library-project",
        project_root="/workspace/time-library",
        message_id="codex-dialogue-visible",
        record_id="codex-dialogue-visible-record",
        native_id="codex-dialogue-visible-native",
        role="assistant",
        native_type="message",
        line_no=2,
        content_preview=f"继续 {marker} appears in visible dialogue evidence.",
    )
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_code_cli": {
                        "source_system": "claude_code_cli",
                        "canonical_window_id": "claude-live-window",
                        "session_id": "claude-live-session",
                        "metadata": {
                            "project_id": "time-library-project",
                            "project_root": "/workspace/time-library",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.preflight_payload(
        f"继续 {marker}",
        consumer="claude_code_hook",
        source_system="claude_code_cli",
        session_id="claude-live-session",
        canonical_window_id="claude-live-window",
        project_id="time-library-project",
        project_root="/workspace/time-library",
        request_id="test-project-fallback-runtime-row-filter",
    )

    assert result["decision"] == "surface"
    assert result["must_surface"][0]["session_id"] == "codex-dialogue-session"
    assert result["must_surface"][0]["artifact_type"] == "message"
    assert "Chunk ID" not in json.dumps(result["must_surface"], ensure_ascii=False)


def test_active_bound_empty_window_project_fallback_keeps_window_scope_strict(tmp_path, monkeypatch):
    marker = "WINDOW_SCOPE_MUST_NOT_PROJECT_FALLBACK_MARKER"
    _write_canonical_message(
        tmp_path,
        source_system="codex",
        session_id="codex-project-session",
        window_id="codex-old-window",
        project_id="time-library-project",
        content_preview=f"{marker} must not surface through explicit window scope.",
    )
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_code_cli": {
                        "source_system": "claude_code_cli",
                        "canonical_window_id": "claude-live-window",
                        "session_id": "claude-live-session",
                        "metadata": {
                            "project_id": "time-library-project",
                            "project_root": "/workspace/time-library",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    monkeypatch.setattr(
        raw_gateway,
        "_load_handle_recall",
        lambda: (lambda body: {"matched_memories": []}),
    )
    result = raw_gateway.query_raw_source_refs(
        marker,
        consumer="claude_code_hook",
        source_system="claude_code_cli",
        memory_scope="window",
        request_id="test-window-scope-no-project-fallback",
    )

    assert result["memory_scope"] == "window"
    assert result["scope_missing"] is False
    assert result["active_empty_window_project_fallback_used"] is False
    assert result["matched_count"] == 0
    assert result["items"] == []


def test_active_bound_empty_window_project_fallback_stays_silent_without_same_project_evidence(tmp_path, monkeypatch):
    marker = "NO_SAME_PROJECT_FALLBACK_MARKER"
    _write_canonical_message(
        tmp_path,
        source_system="codex",
        session_id="codex-other-session",
        window_id="codex-other-window",
        project_id="other-project",
        content_preview=f"{marker} OTHER_PROJECT_SHOULD_NOT_LEAK.",
    )
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_code_cli": {
                        "source_system": "claude_code_cli",
                        "canonical_window_id": "claude-live-window",
                        "session_id": "claude-live-session",
                        "metadata": {
                            "project_id": "time-library-project",
                            "project_root": "/workspace/time-library",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    def bounded_recall_only(body):
        assert body.get("source_system_filter") == "claude_code_cli"
        return {"matched_memories": []}

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", lambda: bounded_recall_only)
    result = raw_gateway.query_raw_source_refs(
        marker,
        consumer="claude_code_hook",
        source_system="claude_code_cli",
        request_id="test-empty-window-project-fallback-miss",
    )

    assert result["memory_scope"] == "active"
    assert result["current_window_binding_applied"] is True
    assert result["active_empty_window_project_fallback_used"] is False
    assert result["active_empty_window_project_fallback_status"] == "miss_no_same_project_or_workstream_source_backed_evidence"
    assert result["matched_count"] == 0
    assert result["items"] == []
    assert "OTHER_PROJECT_SHOULD_NOT_LEAK" not in json.dumps(result, ensure_ascii=False)


def test_claude_desktop_active_alias_stays_on_current_window_anchor(tmp_path):
    marker = "CLAUDE_ACTIVE_ALIAS_WINDOW_MARKER"
    _write_memory(
        tmp_path,
        "claude_code_cli",
        "managed-session-a",
        "2026-06-15T10:00:00Z",
        f"Claude managed current window {marker}",
        f"{marker} from Claude Code CLI under the Claude Desktop current window.",
        window_id="desktop-window-a",
    )
    _write_memory(
        tmp_path,
        "claude_code_cli",
        "managed-session-b",
        "2026-06-15T10:01:00Z",
        f"Claude managed other window {marker}",
        f"{marker} OTHER_WINDOW_SHOULD_NOT_LEAK from a different Claude window.",
        window_id="desktop-window-b",
    )
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_desktop": {
                        "source_system": "claude_desktop",
                        "canonical_window_id": "desktop-window-a",
                        "session_id": "managed-session-a",
                        "metadata": {
                            "source_system_filters": ["claude_desktop", "claude_code_cli"],
                            "source_system_filter_authority": "host_declared_binding",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        marker,
        consumer="claude_desktop",
        source_system="claude_desktop",
        request_id="test-claude-active-alias-window-anchor",
    )

    assert result["memory_scope"] == "active"
    assert result["source_system_filter"] == "claude_desktop"
    assert result["source_system_filter_aliases"] == ["claude_desktop", "claude_code_cli"]
    assert result["source_collection_filter"] == "binding_declared_source_systems"
    assert result["source_collection_alias_applied"] is True
    assert result["source_collection_alias_boundary"] == "verified_binding_same_window_or_session_anchor_only"
    assert result["cross_window_read"] is False
    assert result["canonical_window_id_filter"] == "desktop-window-a"
    assert result["active_layers_used"] == ["current_window"]
    assert result["items"]
    assert {item["source_system"] for item in result["items"]} == {"claude_code_cli"}
    assert {item["session_id"] for item in result["items"]} == {"managed-session-a"}
    assert "OTHER_WINDOW_SHOULD_NOT_LEAK" not in json.dumps(result["items"], ensure_ascii=False)


def test_active_default_without_anchor_only_returns_stable_facts(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-case",
        "2026-05-27T10:00:00Z",
        "Codex active no anchor marker ACTIVE_STABLE_MARKER",
        "ACTIVE_STABLE_MARKER ordinary case memory must not appear without an anchor.",
        window_id="case-window",
    )
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-pref",
        "2026-05-27T10:01:00Z",
        "Codex active no anchor marker ACTIVE_STABLE_MARKER",
        "ACTIVE_STABLE_MARKER stable preference can appear without a project anchor.",
        window_id="pref-window",
        memory_type="preference_memory",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "ACTIVE_STABLE_MARKER",
        consumer="codex",
        request_id="test-active-stable-only",
    )

    assert result["memory_scope"] == "active"
    assert result["scope_missing"] is False
    assert result["active_layers_used"] == ["stable_user_preferences_tool_facts"]
    assert result["items"]
    assert {item["memory_type"] for item in result["items"]} == {"preference_memory"}
    assert "ordinary case memory must not appear" not in json.dumps(result["items"], ensure_ascii=False)
    assert result["raw_fallback_used"] is False
    assert result["raw_fallback_status"] == "skipped_active_without_window_identity"


def test_active_default_without_anchor_does_not_scan_raw_jsonl(tmp_path, monkeypatch):
    marker = "ACTIVE_NO_ANCHOR_RAW_SCAN_SHOULD_NOT_RUN"
    root = tmp_path / "memcore"
    raw_path = root / "memory" / "WINNODEA" / "claude_code_cli" / "claude_code_session_jsonl" / "workspace-f2a87c03" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps({
            "timestamp": "2026-06-15T12:35:00Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": marker},
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)
    monkeypatch.setattr(
        raw_gateway,
        "_query_raw_jsonl_fallback",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("active recall without anchor must not scan raw JSONL")),
    )

    result = raw_gateway.query_raw_source_refs(
        marker,
        consumer="claude_desktop",
        source_system="claude_desktop",
        request_id="test-active-no-anchor-no-raw-scan",
    )

    assert result["memory_scope"] == "active"
    assert result["current_window_binding_applied"] is False
    assert result["matched_count"] == 0
    assert result["raw_fallback_used"] is False
    assert result["raw_fallback_status"] == "skipped_active_without_window_identity"
    assert marker not in json.dumps(result["items"], ensure_ascii=False)


def test_explicit_window_recall_requires_current_window_identity(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex 显式窗口必须绑定",
        "Explicit window scope still needs current window identity.",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Codex 显式窗口必须绑定",
        consumer="codex",
        request_id="test-explicit-window-required",
        memory_scope="window",
    )

    assert result["ok"] is True
    assert result["memory_scope"] == "window"
    assert result["memory_base_scope"] == "window"
    assert result["scope_missing"] is True
    assert result["recall_status"] == "window_identity_required"
    assert "not proof that memory is empty" in result["window_binding_hint"]
    assert set(result["missing_scope_fields"]) == {"canonical_window_id", "session_id"}
    assert result["recall_performed"] is False
    assert result["raw_excerpt_returned"] is False
    assert result["matched_count"] == 0
    assert result["source_refs_count"] == 0
    assert result["raw_items_count"] == 0
    assert result["items"] == []
    assert result["tiandao_context_package_valid"] is True
    tiandao_pkg = result["tiandao_context_package"]
    assert tiandao_pkg["schema"] == "tiandao_context_package.v1"
    assert tiandao_pkg["source_system"] == "codex"
    assert tiandao_pkg["scope_enforced"] is True
    assert tiandao_pkg["injection_blocked"] is True
    assert tiandao_pkg["block_reason"] == "window_identity_required"
    assert tiandao_pkg["memory_write"] is False
    assert tiandao_pkg["permission_boundary"]["read_only"] is True
    assert tiandao_pkg["validation"]["valid"] is True


def test_every_client_raw_pool_requires_explicit_cross_window_flag(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex raw pool 越界防线",
        "Codex cannot read the raw pool unless the caller marks the cross-window intent.",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Codex raw pool 越界防线",
        consumer="codex",
        request_id="test-raw-pool-blocked",
        memory_scope="raw_pool",
    )

    assert result["memory_scope"] == "raw_pool"
    assert result["scope_missing"] is True
    assert result["recall_status"] == "cross_window_permission_required"
    assert "Every client must pass allow_cross_window_recall=true" in result["window_binding_hint"]
    assert result["missing_scope_fields"] == ["allow_cross_window_recall"]
    assert result["cross_window_read"] is True
    assert result["cross_window_read_allowed"] is False
    assert result["matched_count"] == 0
    assert result["items"] == []


def test_every_client_platform_scope_also_requires_explicit_cross_window_flag(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex platform scope 越界防线",
        "Platform scope is still cross-window for ordinary clients.",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Codex platform scope 越界防线",
        consumer="codex",
        request_id="test-platform-scope-blocked",
        memory_scope="platform",
    )

    assert result["memory_scope"] == "platform"
    assert result["source_system_filter"] == "unresolved"
    assert result["inferred_source_system"] == "codex"
    assert result["consumer_name_inference_used_for_routing"] is False
    assert result["scope_missing"] is True
    assert result["recall_status"] == "cross_window_permission_required"
    assert result["missing_scope_fields"] == ["source_system", "allow_cross_window_recall"]
    assert result["cross_window_read"] is True
    assert result["cross_window_read_allowed"] is False
    assert result["matched_count"] == 0
    assert result["items"] == []


def test_every_client_raw_pool_can_read_only_when_explicitly_allowed(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex raw pool 显式越界",
        "Explicitly allowed raw pool read returns source-backed records.",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Codex raw pool 显式越界",
        consumer="codex",
        request_id="test-raw-pool-allowed",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert result["scope_missing"] is False
    assert result["cross_window_read"] is True
    assert result["cross_window_read_allowed"] is True
    assert result["items"]
    assert result["items"][0]["source_system"] == "codex"


def test_window_scope_filters_same_platform_to_one_window(tmp_path):
    marker = "CURRENT_WINDOW_ONLY_MARKER"
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-a",
        "2026-05-27T10:00:00Z",
        "同平台窗口隔离 marker",
        marker,
        window_id="window-a",
    )
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-b",
        "2026-05-27T10:01:00Z",
        "同平台窗口隔离 marker",
        "OTHER_WINDOW_SHOULD_NOT_LEAK",
        window_id="window-b",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "同平台窗口隔离 marker",
        consumer="codex",
        request_id="test-window-filter",
        memory_scope="window",
        canonical_window_id="window-a",
    )

    assert result["scope_missing"] is False
    assert result["memory_scope"] == "window"
    assert result["memory_base_scope"] == "window"
    assert result["canonical_window_id_filter"] == "window-a"
    assert result["items"]
    assert {item["session_id"] for item in result["items"]} == {"codex-session-a"}
    assert {item["canonical_window_id"] for item in result["items"]} == {"codex-session-a"}
    assert {item["project_id"] for item in result["items"]} == {"window-a"}
    assert {item["source_refs_canonical_window_id"] for item in result["items"]} == {"window-a"}
    assert marker in result["items"][0]["raw_excerpt"]
    assert "OTHER_WINDOW_SHOULD_NOT_LEAK" not in json.dumps(result["items"], ensure_ascii=False)


def test_window_scope_prefers_matching_session_when_codex_window_id_is_legacy_project(tmp_path):
    marker = "SESSION_FIRST_ZHIYI_WINDOW_DRIFT_MARKER"
    _write_memory(
        tmp_path,
        "codex",
        "session-a",
        "2026-06-10T01:20:00Z",
        "Codex session-first window drift marker",
        marker,
        window_id="legacy-project-window",
    )
    _write_memory(
        tmp_path,
        "codex",
        "session-b",
        "2026-06-10T01:21:00Z",
        "Codex session-first window drift marker",
        "SESSION_FIRST_ZHIYI_OTHER_SESSION_SHOULD_NOT_LEAK",
        window_id="session-b",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Codex session-first window drift marker",
        consumer="codex",
        request_id="test-session-first-zhiyi-window-drift",
        source_system="codex",
        memory_scope="window",
        session_id="session-a",
        canonical_window_id="session-a",
    )

    assert result["scope_missing"] is False
    assert result["memory_scope"] == "window"
    assert result["canonical_window_id_filter"] == "session-a"
    assert result["items"]
    assert {item["session_id"] for item in result["items"]} == {"session-a"}
    assert {item["canonical_window_id"] for item in result["items"]} == {"session-a"}
    assert {item["project_id"] for item in result["items"]} == {"legacy-project-window"}
    assert marker in result["items"][0]["raw_excerpt"]
    assert "OTHER_SESSION_SHOULD_NOT_LEAK" not in json.dumps(result["items"], ensure_ascii=False)


def test_p3_filter_prefers_matching_session_when_codex_window_id_is_legacy_project(tmp_path):
    p3, _ = _reload_modules(tmp_path)
    memory = {
        "_type": "case_memory",
        "type": "case_memory",
        "scope": "window/legacy-project-window",
        "canonical_window_id": "legacy-project-window",
        "summary": "P3_SESSION_FIRST_MARKER",
        "detail": "session match should override legacy project window identity",
        "source_refs": json.dumps(
            {
                "source_system": "codex",
                "computer_name": "local",
                "session_id": "session-a",
                "canonical_window_id": "legacy-project-window",
            },
            ensure_ascii=False,
        ),
    }

    matched = p3.filter_memories(
        [memory],
        query="P3_SESSION_FIRST_MARKER",
        source_system_filter="codex",
        session_id_filter="session-a",
        canonical_window_id_filter="session-a",
    )

    assert matched == [memory]


def test_raw_gateway_source_filter_is_explicit_not_default(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex 共享底座经验",
        "Codex filtered raw excerpt.",
    )
    _write_memory(
        tmp_path,
        "openclaw",
        "openclaw-session",
        "msg_001",
        "OpenClaw 共享底座经验",
        "OpenClaw should not appear in a Codex-filtered result.",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "共享底座经验",
        source_system="codex",
        computer_name="",
        session_id="",
        limit=5,
        excerpt_chars=200,
        consumer="hermes",
        request_id="test-filtered",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert result["memory_base_scope"] == "filtered"
    assert result["source_system_filter"] == "codex"
    assert result["items"]
    assert {item["source_system"] for item in result["items"]} == {"codex"}


def test_raw_gateway_returns_platform_record_text_verbatim(tmp_path):
    marker = "用户原话 token=USER_OWN_TEXT_1234567890 password=不是凭据只是聊天内容。"
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex 原样保存经验",
        marker,
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "原样保存经验",
        source_system="codex",
        computer_name="",
        session_id="",
        limit=5,
        excerpt_chars=300,
        consumer="hermes",
        request_id="test-verbatim",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert result["items"]
    raw_excerpt = result["items"][0]["raw_excerpt"]
    assert marker in raw_excerpt
    assert "REDACTED" not in raw_excerpt


def test_raw_gateway_exposes_readonly_zhiyi_mcp_tool(tmp_path):
    marker = "MCP 只读工具返回原始摘录 token=USER_OWN_TEXT_MCP。"
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "MCP 知意召回经验",
        marker,
    )
    _, raw_gateway = _reload_modules(tmp_path)

    listed = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    })
    tools = listed["result"]["tools"]
    tool_names = {tool["name"] for tool in tools}
    assert "time_library_recall" in tool_names
    assert "zhiyi_recall" in tool_names
    assert "time_library_reading_area" in tool_names

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "MCP 知意召回经验",
                "consumer": "codex",
                "canonical_window_id": "project-a",
                "limit": 3,
                "excerpt_chars": 300,
            },
        },
    })
    content = called["result"]["structuredContent"]
    assert content["ok"] is True
    assert content["consumer_receipt"]["write_performed"] is False
    assert content["items"][0]["library_id"].startswith("ZX-")
    assert content["items"][0]["matched_by"]
    assert content["items"][0]["rank_reason"]
    assert content["response_budget"]["mode"] == "raw_gateway_compact"
    assert content["response_budget"]["raw_excerpt_returned"] is False
    assert content["raw_excerpt_returned"] is False
    assert content["items"][0]["library_id"] in content["consumer_receipt"]["used_library_ids"]
    assert content["consumer_receipt"]["used_source_refs"]
    assert "raw_excerpt" not in content["items"][0]
    assert "zhixing_library" not in content
    assert "hybrid_recall" not in content
    assert "library_card" not in content["items"][0]
    assert marker not in json.dumps(content, ensure_ascii=False)

    raw_called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "MCP 知意召回经验",
                "consumer": "codex",
                "canonical_window_id": "project-a",
                "limit": 3,
                "excerpt_chars": 300,
                "response_budget": "raw",
            },
        },
    })
    raw_content = raw_called["result"]["structuredContent"]
    assert raw_content["response_budget"]["mode"] == "raw"
    assert raw_content["raw_excerpt_returned"] is True
    assert marker in raw_content["items"][0]["raw_excerpt"]
    assert "REDACTED" not in raw_content["items"][0]["raw_excerpt"]


def test_raw_gateway_mcp_direct_library_id_borrow_bypasses_fuzzy_recall(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    p4_provider = importlib.import_module("src.p4_provider")

    def fail_recall():
        raise AssertionError("library_id borrow must not call fuzzy recall")

    def fake_fetch(library_id, **kwargs):
        return {
            "ok": True,
            "read_only": True,
            "write_performed": False,
            "library_id": library_id,
            "shelf": "raw",
            "card": {
                "library_id": library_id,
                "shelf": "raw",
                "type": "raw_jsonl",
                "title": "Opus raw lane",
                "summary": "Opus raw lane",
                "source_refs": {
                    "source_system": "claude_code_cli",
                    "source_path": "/tmp/opus.jsonl",
                    "session_id": "opus-session",
                    "canonical_window_id": "opus-session",
                    "byte_offsets": {"start": 0, "end": 42},
                },
                "verbatim_excerpt": "raw lane excerpt",
                "source_ref_status": "available",
                "raw_available": True,
            },
            "source_refs": {
                "source_system": "claude_code_cli",
                "source_path": "/tmp/opus.jsonl",
                "session_id": "opus-session",
                "canonical_window_id": "opus-session",
                "byte_offsets": {"start": 0, "end": 42},
            },
            "verbatim_excerpt": "raw lane excerpt",
            "raw_source_excerpt_status": "ok",
            "raw_source_excerpt": "raw lane excerpt",
            "raw_source_excerpt_ref": {
                "source_path": "/tmp/opus.jsonl",
                "byte_offsets": {"start": 0, "end": 42},
            },
        }

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", fail_recall)
    monkeypatch.setattr(p4_provider, "fetch_catalog_card_by_library_id", fake_fetch)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "query": "ZX-RAW-DIRECT",
                "consumer": "opus",
                "request_id": "direct-borrow",
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["ok"] is True
    assert content["mode"] == "library_card_borrow"
    assert content["recall_performed"] is False
    assert content["matched_count"] == 1
    assert content["catalog_card"]["verbatim_excerpt"] == "raw lane excerpt"
    assert content["items"][0]["library_id"] == "ZX-RAW-DIRECT"
    assert content["items"][0]["raw_excerpt"] == "raw lane excerpt"
    assert content["consumer_receipt"]["used_library_ids"] == ["ZX-RAW-DIRECT"]
    assert content["consumer_receipt"]["query_path"] == "/catalog-card"
    assert content["consumer_receipt"]["write_performed"] is False


def test_raw_gateway_mcp_direct_library_id_argument_normalizes_case(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    p4_provider = importlib.import_module("src.p4_provider")
    seen = {}

    def fail_recall():
        raise AssertionError("library_id borrow must not call fuzzy recall")

    def fake_fetch(library_id, **kwargs):
        seen["library_id"] = library_id
        return {
            "ok": True,
            "read_only": True,
            "write_performed": False,
            "library_id": library_id,
            "shelf": "raw",
            "card": {
                "library_id": library_id,
                "shelf": "raw",
                "title": "Raw lane",
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "/tmp/codex.jsonl",
                    "byte_offsets": {"start": 0, "end": 12},
                },
                "verbatim_excerpt": "raw excerpt",
            },
            "source_refs": {
                "source_system": "codex",
                "source_path": "/tmp/codex.jsonl",
                "byte_offsets": {"start": 0, "end": 12},
            },
            "verbatim_excerpt": "raw excerpt",
            "raw_source_excerpt_status": "ok",
            "raw_source_excerpt": "raw excerpt",
            "raw_source_excerpt_ref": {
                "source_path": "/tmp/codex.jsonl",
                "byte_offsets": {"start": 0, "end": 12},
            },
        }

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", fail_recall)
    monkeypatch.setattr(p4_provider, "fetch_catalog_card_by_library_id", fake_fetch)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "library_id": "zx-raw-direct",
                "consumer": "opus",
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert seen["library_id"] == "ZX-RAW-DIRECT"
    assert content["ok"] is True
    assert content["library_id"] == "ZX-RAW-DIRECT"
    assert content["consumer_receipt"]["used_library_ids"] == ["ZX-RAW-DIRECT"]


def test_raw_gateway_mcp_direct_library_id_supports_non_raw_catalog_ids(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    p4_provider = importlib.import_module("src.p4_provider")
    seen = {}

    def fail_recall():
        raise AssertionError("library_id borrow must not call fuzzy recall")

    def fake_fetch(library_id, **kwargs):
        seen["library_id"] = library_id
        return {
            "ok": True,
            "read_only": True,
            "write_performed": False,
            "library_id": library_id,
            "shelf": "xingce",
            "card": {
                "library_id": library_id,
                "shelf": "xingce",
                "title": "隔离测试环境用纯净 VM",
                "summary": "隔离测试环境用纯净 VM",
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "/tmp/codex.jsonl",
                    "byte_offsets": {"start": 10, "end": 42},
                },
                "verbatim_excerpt": "测试环境需要纯净 VM。",
            },
            "source_refs": {
                "source_system": "codex",
                "source_path": "/tmp/codex.jsonl",
                "byte_offsets": {"start": 10, "end": 42},
            },
            "verbatim_excerpt": "测试环境需要纯净 VM。",
            "raw_source_excerpt_status": "ok",
            "raw_source_excerpt": "测试环境需要纯净 VM。",
            "raw_source_excerpt_ref": {
                "source_path": "/tmp/codex.jsonl",
                "byte_offsets": {"start": 10, "end": 42},
            },
        }

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", fail_recall)
    monkeypatch.setattr(p4_provider, "fetch_catalog_card_by_library_id", fake_fetch)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "library_id": "ZX-XINGCE-DIRECT",
                "consumer": "opus",
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert seen["library_id"] == "ZX-XINGCE-DIRECT"
    assert content["ok"] is True
    assert content["mode"] == "library_card_borrow"
    assert content["catalog_card"]["shelf"] == "xingce"
    assert content["items"][0]["library_shelf"] == "xingce"
    assert content["items"][0]["raw_excerpt"] == "测试环境需要纯净 VM。"
    assert content["consumer_receipt"]["used_library_ids"] == ["ZX-XINGCE-DIRECT"]


def test_raw_gateway_mcp_direct_library_id_supports_whiteboard_records(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    p4_provider = importlib.import_module("src.p4_provider")
    seen = {}

    def fail_recall():
        raise AssertionError("whiteboard library_id borrow must not call fuzzy recall")

    def fake_fetch(library_id, **kwargs):
        seen["library_id"] = library_id
        return {
            "ok": True,
            "read_only": True,
            "write_performed": False,
            "library_id": library_id,
            "shelf": "whiteboard",
            "card": {
                "library_id": library_id,
                "shelf": "whiteboard",
                "type": "whiteboard_record",
                "title": "甲块施工完成，交接二签",
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "/tmp/codex.jsonl",
                    "byte_offsets": {"start": 30, "end": 88},
                },
                "verbatim_excerpt": "甲块施工完成，交接二签。",
            },
            "source_refs": {
                "source_system": "codex",
                "source_path": "/tmp/codex.jsonl",
                "byte_offsets": {"start": 30, "end": 88},
            },
            "verbatim_excerpt": "甲块施工完成，交接二签。",
            "raw_source_excerpt_status": "ok",
            "raw_source_excerpt": "甲块施工完成，交接二签。",
            "raw_source_excerpt_ref": {
                "source_path": "/tmp/codex.jsonl",
                "byte_offsets": {"start": 30, "end": 88},
            },
        }

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", fail_recall)
    monkeypatch.setattr(p4_provider, "fetch_catalog_card_by_library_id", fake_fetch)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "library_id": "wb-direct-001",
                "consumer": "opus",
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert seen["library_id"] == "WB-DIRECT-001"
    assert content["ok"] is True
    assert content["mode"] == "library_card_borrow"
    assert content["catalog_card"]["shelf"] == "whiteboard"
    assert content["items"][0]["library_shelf"] == "whiteboard"
    assert content["items"][0]["raw_excerpt"] == "甲块施工完成，交接二签。"
    assert content["consumer_receipt"]["used_library_ids"] == ["WB-DIRECT-001"]


def test_raw_gateway_compact_includes_adjacent_context_bundle_refs_without_excerpt(tmp_path):
    root = tmp_path / "memcore"
    raw_path = root / "memory" / "codex" / "local" / "project-a" / "codex-session.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    before_marker = "MCP 证据包前一条原文 token=ADJACENT_BEFORE_SECRET。"
    anchor_marker = "MCP 证据包锚点原文 token=ANCHOR_SECRET。"
    after_marker = "MCP 证据包后一条原文 token=ADJACENT_AFTER_SECRET。"
    raw_records = [
        ("bundle-before-001", "user", before_marker),
        ("bundle-anchor-001", "assistant", anchor_marker),
        ("bundle-after-001", "user", after_marker),
    ]
    raw_path.write_text(
        "".join(
            json.dumps({
                "timestamp": msg_id,
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": role,
                    "content": [{"type": "output_text", "text": text}],
                },
            }, ensure_ascii=False) + "\n"
            for msg_id, role, text in raw_records
        ),
        encoding="utf-8",
    )
    refs = {
        "source_system": "codex",
        "computer_name": "local",
        "canonical_window_id": "project-a",
        "session_id": "codex-session",
        "source_path": str(raw_path),
        "msg_ids": ["bundle-anchor-001"],
        "artifact_type": "codex_session_jsonl",
    }
    record = {
        "exp_id": "exp-codex-context-bundle",
        "type": "case_memory",
        "canonical_window_id": "project-a",
        "session_id": "codex-session",
        "computer_id": "local",
        "source_system": "codex",
        "scope": "window/project-a",
        "summary": "MCP 证据包锚点经验",
        "detail": "context bundle smoke marker",
        "source_refs": json.dumps(refs, ensure_ascii=False),
        "score": 0.8,
    }
    zhiyi_path = root / "zhiyi" / "case_memory" / "case_memory.jsonl"
    zhiyi_path.parent.mkdir(parents=True, exist_ok=True)
    zhiyi_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    _, raw_gateway = _reload_modules(tmp_path)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "MCP 证据包锚点经验",
                "consumer": "codex",
                "source_system": "codex",
                "canonical_window_id": "project-a",
                "limit": 3,
                "excerpt_chars": 300,
            },
        },
    })
    content = called["result"]["structuredContent"]
    item = content["items"][0]

    assert content["response_budget"]["mode"] == "raw_gateway_compact"
    assert content["raw_excerpt_returned"] is False
    assert content["context_bundle_policy"] == "anchor_plus_adjacent_raw_refs_no_excerpt"
    assert content["context_bundle_refs_count"] >= 3
    assert item["context_bundle_available"] is True
    assert item["context_bundle_size"] == 3
    assert "raw_excerpt" not in item
    assert {ref["neighbor_direction"] for ref in item["context_bundle_refs"]} == {"previous", "anchor", "next"}
    assert [ref["msg_ids"][0] for ref in item["context_bundle_refs"]] == [
        "bundle-before-001",
        "bundle-anchor-001",
        "bundle-after-001",
    ]
    dumped = json.dumps(content, ensure_ascii=False)
    assert before_marker not in dumped
    assert anchor_marker not in dumped
    assert after_marker not in dumped


def test_raw_gateway_mcp_preflight_surfaces_xingce_without_raw_excerpt(tmp_path):
    marker = "Hermes 平台配置经验：先查 profile config；不要改 root config 当默认继承；验收用 hermes profile show。"
    root = tmp_path / "memcore"
    raw_path = root / "memory" / "codex" / "local" / "project-a" / "codex-session.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps({
            "timestamp": "2026-06-09T10:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": marker}],
            },
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    candidates_dir = root / "output" / "xingce_work_experience" / "candidates"
    actions_dir = root / "output" / "xingce_work_experience" / "actions"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    actions_dir.mkdir(parents=True, exist_ok=True)
    candidate_id = "xingce-hermes-profile-preflight"
    (candidates_dir / "xingce-hermes-profile-candidate.json").write_text(
        json.dumps({
            "candidate_id": candidate_id,
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "Hermes profile config preflight",
            "summary": "Hermes 平台配置经验 profile config",
            "work_scenario": "Hermes profile config",
            "recommended_procedure": ["先查 profile config"],
            "avoid_conditions": ["不要改 root config 当默认继承"],
            "verification_steps": ["hermes profile show"],
            "evidence_refs": [
                {
                    "source_system": "codex",
                    "computer_name": "local",
                    "canonical_window_id": "project-a",
                    "session_id": "codex-session",
                    "project_id": "memcore-cloud",
                    "project_root": "/work/memcore-cloud",
                    "workstream_id": "release-check",
                    "source_path": str(raw_path),
                    "msg_ids": ["2026-06-09T10:00:00Z"],
                }
            ],
            "source_refs": [str(raw_path)],
            "confidence": 0.8,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (actions_dir / "2026-06-09-actions.jsonl").write_text(
        json.dumps({
            "action_id": "action-hermes-profile-preflight",
            "candidate_id": candidate_id,
            "action": "queue_for_experience_service_review",
            "action_status": "queued_for_experience_service_review",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    listed = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    })
    mode_schema = listed["result"]["tools"][0]["inputSchema"]["properties"]["mode"]
    assert "preflight" in mode_schema["enum"]
    assert "work_preflight" in mode_schema["enum"]
    assert "agent_work_preflight" in mode_schema["enum"]
    schema_props = listed["result"]["tools"][0]["inputSchema"]["properties"]
    assert "deep_work_preflight" in schema_props
    assert "full_work_preflight" in schema_props
    assert schema_props["fast_preflight_miss_policy"]["enum"] == [
        "continue_recall",
        "return_without_cold_recall",
    ]

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "继续 Hermes 平台配置问题，接下来怎么做",
                "mode": "preflight",
                "consumer": "codex",
                "source_system": "codex",
                "canonical_window_id": "project-a",
                "project_id": "memcore-cloud",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]
    encoded = json.dumps(content, ensure_ascii=False)

    assert content["ok"] is True
    assert content["mode"] == "preflight"
    assert content["read_only"] is True
    assert content["write_performed"] is False
    assert content["raw_write_performed"] is False
    assert content["zhiyi_write_performed"] is False
    assert content["xingce_write_performed"] is False
    assert content["platform_write_performed"] is False
    assert content["model_call_performed"] is False
    assert content["should_recall"] is True
    assert content["should_surface"] is True
    assert content["decision"] == "surface"
    assert content["proactive_resurfacing_required"] is True
    assert "action_strategy" in content["xingce_focus"]
    assert "continuation_state" in content["xingce_focus"]
    assert content["must_surface"]
    assert content["must_surface"][0]["library_shelf"] == "xingce"
    assert content["must_surface"][0]["project_id"] == "memcore-cloud"
    assert any("不要改 root config" in item for item in content["do_not_repeat"])
    assert any("hermes profile show" in item for item in content["acceptance_checks"])
    assert content["raw_excerpt_returned"] is False
    assert content["consumer_receipt"]["receipt_scope"] == "zhixing_preflight_read_only"
    assert '"raw_excerpt":' not in encoded
    assert marker not in encoded

    work_called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "继续 Hermes 平台配置问题，动手前先查已有机制",
                "mode": "work_preflight",
                "consumer": "codex",
                "source_system": "codex",
                "canonical_window_id": "project-a",
                "project_id": "memcore-cloud",
                "deep_work_preflight": True,
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    work_content = work_called["result"]["structuredContent"]
    work_encoded = json.dumps(work_content, ensure_ascii=False)

    assert work_content["ok"] is True
    assert work_content["mode"] == "work_preflight"
    assert work_content["contract"] == "agent_work_preflight.v2026.6.20"
    assert work_content["source_preflight_contract"] == "zhixing_preflight.v2026.6.20"
    assert work_content["classification"] in {
        "already_built_but_forgotten",
        "built_but_miswired",
        "diagnostic_gap",
    }
    assert work_content["should_intervene"] is True
    assert work_content["read_only"] is True
    assert work_content["write_performed"] is False
    assert work_content["raw_write_performed"] is False
    assert work_content["zhiyi_write_performed"] is False
    assert work_content["xingce_write_performed"] is False
    assert work_content["platform_write_performed"] is False
    assert work_content["model_call_performed"] is False
    assert work_content["evidence"]
    assert work_content["evidence"][0]["library_shelf"] == "xingce"
    assert work_content["evidence"][0]["project_id"] == "memcore-cloud"
    assert "raw_excerpt" not in work_content["evidence"][0]
    assert any("不要改 root config" in item for item in work_content["do_not_repeat"])
    assert any("hermes profile show" in item for item in work_content["acceptance_checks"])
    assert work_content["raw_excerpt_returned"] is False
    assert work_content["consumer_receipt"]["receipt_scope"] == "agent_work_preflight_read_only"
    assert work_content["consumer_receipt"]["write_performed"] is False
    assert '"raw_excerpt":' not in work_encoded
    assert marker not in work_encoded

    project_called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "继续 Hermes 平台配置问题，接下来怎么做",
                "mode": "preflight",
                "consumer": "codex",
                "source_system": "codex",
                "project_id": "memcore-cloud",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    project_content = project_called["result"]["structuredContent"]
    assert project_content["decision"] == "surface"
    assert project_content["should_surface"] is True
    assert project_content["active_layers_used"] == ["same_project_workspace"]


def test_raw_gateway_mcp_window_preflight_uses_canonical_index_without_cold_recall(tmp_path, monkeypatch):
    root = tmp_path / "memcore"
    records_db = root / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    marker = "FAST_WINDOW_INDEX_PREFLIGHT_MARKER"
    raw_path = root / "memory" / "local" / "claude_code_cli" / "claude_code_session_jsonl" / "window-a" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("", encoding="utf-8")
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, project_root, source_path,
                raw_path, role, native_type, native_id, timestamp, line_no,
                raw_line_no, source_offset_start, source_offset_end,
                raw_offset_start, raw_offset_end, content_preview, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-fast-window",
                "record-fast-window",
                "claude_code_cli",
                "session-a",
                "window-a",
                "memcore-cloud",
                "/work/memcore-cloud",
                str(raw_path),
                str(raw_path),
                "assistant",
                "claude_code_session_jsonl",
                "native-fast-window",
                "2026-06-10T01:00:00Z",
                1,
                1,
                0,
                160,
                0,
                160,
                f"继续 {marker}：当前窗口已经有 canonical index，可用于自动 preflight。",
                "2026-06-10T01:00:01Z",
            ),
        )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _, raw_gateway = _reload_modules(tmp_path)

    def fail_cold_recall():
        raise AssertionError("window preflight should not cold-load zhiyi recall")

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", fail_cold_recall)
    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": f"继续 {marker}",
                "mode": "preflight",
                "consumer": "claude_code_hook",
                "source_system": "claude_code_cli",
                "memory_scope": "window",
                "canonical_window_id": "window-a",
                "session_id": "session-a",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["ok"] is True
    assert content["mode"] == "preflight"
    assert content["decision"] == "surface"
    assert content["should_surface"] is True
    assert content["fast_window_preflight"] is True
    assert content["fast_recall_path"] == "canonical_window_index"
    assert content["fast_window_index_status"] == "hit"
    assert content["zhiyi_layer_skipped_for_fast_preflight"] is True
    assert content["library_index_projection_used"] is True
    assert content["library_index_projection_policy"] == "navigation_hint_only_raw_evidence_required"
    assert content["library_index_projection_refs_count"] == 1
    assert content["library_index_projection_refs"][0]["authority"] == "navigation_hint_only_raw_evidence_required"
    assert content["raw_recall_trajectory_contract"] == "raw_recall_trajectory.v2026.6.17"
    trajectory = {step["step"]: step for step in content["raw_recall_trajectory"]}
    assert trajectory["catalog_index_projection"]["layer"] == "L1_library_index_projection"
    assert trajectory["catalog_index_projection"]["status"] == "hit"
    assert trajectory["catalog_index_projection"]["used"] is True
    assert trajectory["catalog_index_projection"]["authority"] == "navigation_hint_only_raw_evidence_required"
    assert trajectory["raw_fallback"]["status"] == "skipped_fast_window_index_hit"
    assert trajectory["raw_fallback"]["used"] is False
    assert trajectory["final_receipt"]["status"] == "raw"
    assert content["recall_performed"] is True
    assert content["active_layers_used"] == ["current_window"]
    assert content["raw_items_count"] == 1
    assert content["must_surface"]
    assert content["must_surface"][0]["source_system"] == "claude_code_cli"
    assert content["must_surface"][0]["session_id"] == "session-a"
    assert content["must_surface"][0]["canonical_window_id"] == "session-a"
    assert content["must_surface"][0]["source_refs_canonical_window_id"] == "window-a"
    assert content["must_surface"][0]["raw_evidence_status"] == "raw_index"
    assert content["raw_excerpt_returned"] is False
    assert content["consumer_receipt"]["receipt_scope"] == "zhixing_preflight_read_only"
    assert content["consumer_receipt"]["library_index_projection_used"] is True
    assert content["consumer_receipt"]["library_index_projection_refs_count"] == 1
    assert content["consumer_receipt"]["raw_recall_trajectory_contract"] == "raw_recall_trajectory.v2026.6.17"


def test_raw_gateway_mcp_work_preflight_project_window_anchor_stays_on_fast_index(tmp_path, monkeypatch):
    root = tmp_path / "memcore"
    records_db = root / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    marker = "WORK_PREFLIGHT_PROJECT_WINDOW_FAST_PATH_MARKER"
    raw_path = root / "memory" / "local" / "codex" / "codex_session_jsonl" / "window-a" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("", encoding="utf-8")
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, project_root, source_path,
                raw_path, role, native_type, native_id, timestamp, line_no,
                raw_line_no, source_offset_start, source_offset_end,
                raw_offset_start, raw_offset_end, content_preview, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-work-preflight-fast-window",
                "record-work-preflight-fast-window",
                "codex",
                "session-a",
                "window-a",
                "memcore-cloud",
                "/work/memcore-cloud",
                str(raw_path),
                str(raw_path),
                "assistant",
                "codex_session_jsonl",
                "native-work-preflight-fast-window",
                "2026-06-17T01:00:00Z",
                1,
                1,
                0,
                200,
                0,
                200,
                f"继续 {marker}：Codex 桥带 window/session/project_root 时 work_preflight 仍应走快索引。",
                "2026-06-17T01:00:01Z",
            ),
        )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _, raw_gateway = _reload_modules(tmp_path)

    def fail_cold_recall():
        raise AssertionError("work_preflight with window/project anchors must not cold-load zhiyi recall by default")

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", fail_cold_recall)
    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 24,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": f"继续 {marker}",
                "mode": "work_preflight",
                "consumer": "codex",
                "source_system": "codex",
                "memory_scope": "window",
                "canonical_window_id": "window-a",
                "session_id": "session-a",
                "project_id": "memcore-cloud",
                "project_root": "/work/memcore-cloud",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["ok"] is True
    assert content["mode"] == "work_preflight"
    assert content["classification"] in {"already_built_but_forgotten", "diagnostic_gap"}
    assert content["should_intervene"] is True
    assert content["fast_window_preflight"] is True
    assert content["fast_recall_path"] == "canonical_window_index"
    assert content["fast_window_index_status"] == "hit"
    assert content["zhiyi_layer_skipped_for_fast_preflight"] is True
    assert content["project_root_filter"] == "/work/memcore-cloud"
    assert content["evidence"][0]["raw_evidence_status"] == "raw_index"
    assert content["consumer_receipt"]["receipt_scope"] == "agent_work_preflight_read_only"


def test_raw_gateway_mcp_window_preflight_uses_recent_context_for_short_continuation(tmp_path, monkeypatch):
    root = tmp_path / "memcore"
    records_db = root / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    raw_path = root / "memory" / "local" / "claude_code_cli" / "claude_code_session_jsonl" / "window-a" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("", encoding="utf-8")
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, project_root, source_path,
                raw_path, role, native_type, native_id, timestamp, line_no,
                raw_line_no, source_offset_start, source_offset_end,
                raw_offset_start, raw_offset_end, content_preview, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-recent-context",
                "record-recent-context",
                "claude_code_cli",
                "session-a",
                "window-a",
                "memcore-cloud",
                "/work/memcore-cloud",
                str(raw_path),
                str(raw_path),
                "assistant",
                "claude_code_session_jsonl",
                "native-recent-context",
                "2026-06-10T01:20:00Z",
                1,
                1,
                0,
                180,
                0,
                180,
                "上一轮已经完成 9851 fast index 和 cold import 修复，下一刀是 release gate smoke。",
                "2026-06-10T01:20:01Z",
            ),
        )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _, raw_gateway = _reload_modules(tmp_path)
    monkeypatch.setattr(
        raw_gateway,
        "_load_handle_recall",
        lambda: (_ for _ in ()).throw(AssertionError("short preflight must stay on canonical index fast path")),
    )

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 25,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "继续发布前检查",
                "mode": "preflight",
                "consumer": "claude_code_hook",
                "source_system": "claude_code_cli",
                "memory_scope": "window",
                "canonical_window_id": "window-a",
                "session_id": "session-a",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["decision"] == "surface"
    assert content["should_surface"] is True
    assert content["fast_window_preflight"] is True
    assert content["fast_window_index_status"] == "hit_recent_context"
    assert content["library_index_projection_used"] is True
    trajectory = {step["step"]: step for step in content["raw_recall_trajectory"]}
    assert trajectory["catalog_index_projection"]["status"] == "hit_recent_context"
    assert trajectory["catalog_index_projection"]["used"] is True
    assert trajectory["raw_fallback"]["status"] == "skipped_fast_window_index_hit"
    assert content["recall_performed"] is True
    assert content["active_layers_used"] == ["current_window"]
    assert content["raw_items_count"] == 1
    assert content["must_surface"][0]["source_system"] == "claude_code_cli"
    assert content["must_surface"][0]["session_id"] == "session-a"
    assert content["must_surface"][0]["canonical_window_id"] == "session-a"
    assert content["must_surface"][0]["source_refs_canonical_window_id"] == "window-a"
    assert content["must_surface"][0]["raw_evidence_status"] == "raw_index"
    assert content["raw_excerpt_returned"] is False


def test_raw_gateway_mcp_window_preflight_does_not_use_recent_context_for_long_unrelated_task(tmp_path, monkeypatch):
    root = tmp_path / "memcore"
    records_db = root / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    raw_path = root / "memory" / "local" / "claude_code_cli" / "claude_code_session_jsonl" / "window-a" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("", encoding="utf-8")
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, project_root, source_path,
                raw_path, role, native_type, native_id, timestamp, line_no,
                raw_line_no, source_offset_start, source_offset_end,
                raw_offset_start, raw_offset_end, content_preview, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-long-unrelated",
                "record-long-unrelated",
                "claude_code_cli",
                "session-a",
                "window-a",
                "memcore-cloud",
                "/work/memcore-cloud",
                str(raw_path),
                str(raw_path),
                "assistant",
                "claude_code_session_jsonl",
                "native-long-unrelated",
                "2026-06-10T01:30:00Z",
                1,
                1,
                0,
                180,
                0,
                180,
                "上一轮是 9851 preflight 快索引验证，不涉及新网站设计任务。",
                "2026-06-10T01:30:01Z",
            ),
        )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _, raw_gateway = _reload_modules(tmp_path)
    monkeypatch.setattr(
        raw_gateway,
        "_load_handle_recall",
        lambda: (_ for _ in ()).throw(AssertionError("long unmatched window preflight must not cold-load recall")),
    )

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 26,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "修复一个完全不同的问题并重新设计公开网站的按钮样式和配色以及新增营销落地页文案，同时检查另一个全新项目的数据库迁移流程和移动端布局",
                "mode": "preflight",
                "consumer": "claude_code_hook",
                "source_system": "claude_code_cli",
                "memory_scope": "window",
                "canonical_window_id": "window-a",
                "session_id": "session-a",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["decision"] == "silent"
    assert content["silence_reason"] == "no_relevant_evidence"
    assert content["fast_window_preflight"] is True
    assert content["fast_window_index_status"] == "miss_content_filter"
    assert content["library_index_projection_used"] is False
    trajectory = {step["step"]: step for step in content["raw_recall_trajectory"]}
    assert trajectory["catalog_index_projection"]["used"] is False
    assert trajectory["catalog_index_projection"]["status"] == "miss_content_filter"
    assert trajectory["raw_fallback"]["status"] == "skipped_fast_window_index_miss"
    assert trajectory["final_receipt"]["status"] == "not_raw"
    assert content["recall_performed"] is False
    assert content["matched_count"] == 0
    assert content["must_surface"] == []


def test_raw_gateway_mcp_window_preflight_missing_index_silently_skips_cold_recall(tmp_path, monkeypatch):
    records_db = tmp_path / "memcore" / "output" / "records" / "missing-records.db"
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _, raw_gateway = _reload_modules(tmp_path)

    def fail_cold_recall():
        raise AssertionError("missing index must not fall back to cold zhiyi recall for window preflight")

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", fail_cold_recall)
    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 23,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "继续发布前检查",
                "mode": "preflight",
                "consumer": "claude_code_hook",
                "source_system": "claude_code_cli",
                "memory_scope": "window",
                "canonical_window_id": "window-a",
                "session_id": "session-a",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["ok"] is True
    assert content["decision"] == "silent"
    assert content["silence_reason"] == "no_relevant_evidence"
    assert content["fast_window_preflight"] is True
    assert content["fast_recall_path"] == "canonical_window_index"
    assert content["fast_window_index_status"] == "records_db_missing"
    assert content["fast_preflight_miss_policy"] == "continue_recall"
    assert content["fast_preflight_miss_returned_without_cold_recall"] is True
    assert content["fast_preflight_miss_continued_to_cold_recall"] is False
    assert content["fast_preflight_miss_return_reason"] == "explicit_window_scope"
    assert content["library_index_projection_used"] is False
    trajectory = {step["step"]: step for step in content["raw_recall_trajectory"]}
    assert trajectory["catalog_index_projection"]["status"] == "records_db_missing"
    assert trajectory["catalog_index_projection"]["used"] is False
    assert trajectory["raw_fallback"]["status"] == "skipped_fast_window_index_miss"
    assert content["zhiyi_layer_skipped_for_fast_preflight"] is True
    assert content["recall_performed"] is False
    assert content["matched_count"] == 0
    assert content["must_surface"] == []


def test_raw_gateway_mcp_window_preflight_prefers_session_when_registry_window_drifts(tmp_path, monkeypatch):
    root = tmp_path / "memcore"
    records_db = root / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    marker = "SESSION_FIRST_WINDOW_DRIFT_MARKER"
    raw_path = root / "memory" / "local" / "claude_code_cli" / "claude_code_session_jsonl" / "db-window" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("", encoding="utf-8")
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, project_root, source_path,
                raw_path, role, native_type, native_id, timestamp, line_no,
                raw_line_no, source_offset_start, source_offset_end,
                raw_offset_start, raw_offset_end, content_preview, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-window-drift",
                "record-window-drift",
                "claude_code_cli",
                "session-a",
                "db-window",
                "memcore-cloud",
                "/work/memcore-cloud",
                str(raw_path),
                str(raw_path),
                "assistant",
                "claude_code_session_jsonl",
                "native-window-drift",
                "2026-06-10T01:10:00Z",
                1,
                1,
                0,
                160,
                0,
                160,
                f"继续 {marker}：session 精确匹配时，不应被 registry window 漂移挡掉。",
                "2026-06-10T01:10:01Z",
            ),
        )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _, raw_gateway = _reload_modules(tmp_path)
    monkeypatch.setattr(
        raw_gateway,
        "_load_handle_recall",
        lambda: (_ for _ in ()).throw(AssertionError("must stay on canonical index fast path")),
    )

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 24,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": f"继续 {marker}",
                "mode": "preflight",
                "consumer": "claude_code_hook",
                "source_system": "claude_code_cli",
                "memory_scope": "window",
                "canonical_window_id": "registry-window",
                "session_id": "session-a",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["decision"] == "surface"
    assert content["fast_window_index_status"] == "hit"
    assert content["must_surface"][0]["session_id"] == "session-a"
    assert content["must_surface"][0]["canonical_window_id"] == "session-a"
    assert content["must_surface"][0]["project_id"] == "memcore-cloud"
    assert content["canonical_window_id_filter"] == "registry-window"


def test_raw_gateway_records_db_path_avoids_guardian_import_on_preflight_path(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    sys.modules.pop("raw_record_guardian", None)
    sys.modules.pop("src.raw_record_guardian", None)

    path = raw_gateway._records_db_path_for_gateway()

    assert path == tmp_path / "memcore" / "output" / "records" / "records.db"
    assert "raw_record_guardian" not in sys.modules
    assert "src.raw_record_guardian" not in sys.modules


def test_raw_gateway_mcp_preflight_skips_trivial_prompt_without_recall(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)

    def fail_query(*args, **kwargs):
        raise AssertionError("trivial preflight must not query raw/source refs")

    monkeypatch.setattr(raw_gateway, "query_raw_source_refs", fail_query)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "好的",
                "mode": "preflight",
                "consumer": "codex",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["ok"] is True
    assert content["mode"] == "preflight"
    assert content["decision"] == "skip"
    assert content["prompt_class"] == "trivial"
    assert content["should_recall"] is False
    assert content["should_surface"] is False
    assert content["recall_performed"] is False
    assert content["silence_reason"] == "trivial_prompt"
    assert content["must_surface"] == []
    assert content["consumer_receipt"]["items_count"] == 0
    assert content["write_performed"] is False


def test_raw_gateway_mcp_preflight_requires_active_anchor_before_recall(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)

    def fail_query(*args, **kwargs):
        raise AssertionError("unanchored preflight must not query raw/source refs")

    monkeypatch.setattr(raw_gateway, "query_raw_source_refs", fail_query)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "继续 Hermes 平台配置问题，接下来怎么做",
                "mode": "preflight",
                "consumer": "codex",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["ok"] is True
    assert content["mode"] == "preflight"
    assert content["decision"] == "scope_required"
    assert content["prompt_class"] == "continuation"
    assert content["should_recall"] is True
    assert content["should_surface"] is False
    assert content["recall_performed"] is False
    assert content["scope_missing"] is True
    assert content["recall_status"] == "active_preflight_anchor_required"
    assert content["silence_reason"] == "scope_missing"
    assert "project_id" in content["missing_scope_fields"]
    assert content["must_surface"] == []


def test_raw_gateway_run_uses_threading_http_server(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    created = []

    class FakeServer:
        def __init__(self, address, handler):
            self.address = address
            self.handler = handler
            self.served = False
            created.append(self)

        def serve_forever(self):
            self.served = True

    monkeypatch.setattr(raw_gateway, "ThreadingHTTPServer", FakeServer)

    raw_gateway.run(port=9917)

    assert len(created) == 1
    assert created[0].address == ("127.0.0.1", 9917)
    assert created[0].handler is raw_gateway.Handler
    assert created[0].served is True


def test_raw_gateway_exposes_active_memory_routing_status_without_recall(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    status = raw_gateway.active_memory_routing_status()

    assert status["ok"] is True
    assert status["contract"] == "active_memory_routing.v2026.7.15"
    assert status["tiandao_contract"] == "tiandao_active_memory_routing.v1"
    assert status["tiandao_routing_contract"]["contract"] == "tiandao_active_memory_routing.v1"
    assert (
        status["tiandao_memory_experience_layering_contract"]["contract"]
        == "tiandao_memory_experience_layering.v1"
    )
    assert status["tiandao_time_river_contract"]["contract"] == "tiandao_time_river.v1"
    assert status["tiandao_time_river_contract"]["zh_name"] == "时间长河"
    assert status["tiandao_time_river_contract"]["platform_policy"] == "platforms_are_inlets_not_river_laws"
    assert status["tiandao_time_river_contract"]["raw_authority_policy"] == "raw_source_text_is_highest_authority"
    assert (
        status["tiandao_time_river_contract"]["summary_policy"]
        == "summaries_are_navigation_not_source_replacement"
    )
    assert status["all_queryable_memory_layers"] == ["raw", "zhiyi", "xingce", "toolbook"]
    assert status["platform_is_not_memory_layer"] is True
    assert "platform_memory_method_biases" not in status
    assert status["example_signal_layering"]["workflow"] == "xingce"
    assert status["example_signal_layering"]["correction"] == "zhiyi"
    assert status["example_signal_layering"]["skill"] == "xingce"
    assert status["example_signal_layering"]["tool_fact"] == "toolbook"
    assert status["read_only"] is True
    assert status["write_performed"] is False
    assert status["platform_write_performed"] is False
    assert status["memory_write_performed"] is False
    assert status["recall_performed"] is False
    assert status["raw_excerpt_returned"] is False
    assert status["default_memory_scope"] == "active"
    assert status["default_recall_order"] == [
        "current_window",
        "current_session",
        "same_project_workspace",
        "same_workstream_task",
        "stable_user_preferences_tool_facts",
        "explicit_raw_pool_global_only_when_requested",
    ]
    assert status["ordinary_client_contract"]["default_scope"] == "active"
    assert status["ordinary_client_contract"]["requires_current_window_identity"] is False
    assert status["ordinary_client_contract"]["missing_identity_status"] == "active_layered"
    assert status["ordinary_client_contract"]["missing_identity_is_not_no_memory"] is True
    assert status["ordinary_client_contract"]["window_scope_is_strict_when_explicit"] is True
    assert status["ordinary_client_contract"]["active_recall_is_window_first_not_window_only"] is True
    assert status["ordinary_client_contract"]["cross_window_requires_explicit_flag"] is True
    assert status["ordinary_client_contract"]["cross_window_flag"] == "allow_cross_window_recall"
    assert status["scope_modes"]["active"]["memory_base_scope"] == "active_layered"
    assert status["scope_modes"]["active"]["cross_window_read"] is False
    assert status["scope_modes"]["active"]["raw_pool_or_global"] == "explicit_only"
    assert status["scope_modes"]["window"]["cross_window_read"] is False
    assert status["scope_modes"]["platform"]["cross_window_read"] is True
    assert status["scope_modes"]["raw_pool"]["ordinary_clients_require_explicit_flag"] is True
    assert status["cross_window_authorization"]["identity_based_exceptions"] == []
    assert status["cross_window_authorization"]["same_contract_for_every_client"] is True
    assert status["cross_window_authorization"]["cross_window_reason_role"] == "audit_only_not_authorization"
    assert status["example_resolutions"]["ordinary_active_without_identity"]["scope_missing"] is False
    assert status["example_resolutions"]["ordinary_active_without_identity"]["recall_status"] == "active_layered"
    assert status["example_resolutions"]["ordinary_active_without_identity"]["active_layered_continuation"] is True
    assert status["example_resolutions"]["ordinary_window_without_identity"]["scope_missing"] is True
    assert status["example_resolutions"]["ordinary_window_without_identity"]["recall_status"] == "window_identity_required"
    assert status["example_resolutions"]["ordinary_raw_pool_without_flag"]["recall_status"] == "cross_window_permission_required"
    assert status["example_resolutions"]["ordinary_raw_pool_without_flag"]["cross_window_read_allowed"] is False
    assert status["example_resolutions"]["second_client_raw_pool_without_flag"]["scope_missing"] is True
    assert status["example_resolutions"]["second_client_raw_pool_without_flag"]["recall_status"] == "cross_window_permission_required"
    assert status["example_resolutions"]["second_client_raw_pool_without_flag"]["cross_window_read_allowed"] is False
    assert status["example_resolutions"]["raw_pool_with_explicit_flag"]["scope_missing"] is False
    assert status["example_resolutions"]["raw_pool_with_explicit_flag"]["cross_window_read_allowed"] is True
    assert status["example_resolutions"]["raw_pool_with_explicit_flag"]["cross_window_permission_explicit"] is True
    assert status["example_resolutions"]["raw_pool_with_explicit_flag"]["same_result_for_second_client"] is True
    assert status["example_resolutions"]["raw_pool_with_explicit_flag"]["cross_window_reason"] == "skill_generation"
    assert "items" not in status
    assert '"raw_excerpt":' not in json.dumps(status, ensure_ascii=False)


def test_raw_gateway_mcp_initialize_reports_service_version(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    initialized = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    })

    assert initialized["result"]["serverInfo"]["version"] == "2099.1.2"
    receipt = initialized["result"]["platformHandshakeReceipt"]
    assert receipt["contract"] == "time_library_platform_handshake_receipt.v1"
    assert receipt["client_info_present"] is False
    assert receipt["current_stage"] == "client_info_missing"
    assert receipt["handshake_observed"] is False
    assert receipt["handshake_verified"] is False
    assert receipt["verification_level"] == "none"
    assert receipt["registered"] is False
    assert receipt["recall_proven"] is False
    assert receipt["platform_write_performed"] is False


def test_raw_gateway_mcp_initialize_captures_client_info_as_unregistered_handshake(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    initialized = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": "Codex Desktop", "version": "26.630.12135"},
            "capabilities": {},
        },
    })

    receipt = initialized["result"]["platformHandshakeReceipt"]
    assert receipt["contract"] == "time_library_platform_handshake_receipt.v1"
    assert receipt["evidence_source"] == "mcp_initialize.params.clientInfo"
    assert receipt["client_info_present"] is True
    assert receipt["client_name"] == "Codex Desktop"
    assert receipt["client_version"] == "26.630.12135"
    assert receipt["inferred_platform"] == "codex"
    assert receipt["current_stage"] == "client_info_observed"
    assert receipt["handshake_observed"] is True
    assert receipt["handshake_verified"] is False
    assert receipt["verification_level"] == "client_info_observed_only"
    assert receipt["capability_check_performed"] is False
    assert receipt["real_recall_performed"] is False
    assert receipt["recall_proven"] is False
    assert receipt["registered"] is False
    assert receipt["registration_blockers"] == [
        "handshake_not_verified_beyond_client_info",
        "capability_check_not_performed",
        "real_recall_not_proven",
        "self_report_answers_not_observed",
        "self_report_not_verified",
    ]
    assert receipt["read_only"] is True
    assert receipt["platform_write_performed"] is False
    assert receipt["memory_write_performed"] is False
    assert receipt["chat_body_included"] is False
    assert receipt["raw_excerpt_included"] is False
    assert receipt["client_info_redaction_policy"] == "name_version_only"
    assert receipt["client_info_sanitized"] is True
    assert receipt["self_report_policy"]["contract"] == "time_library_platform_self_report_questions.v1"
    assert receipt["self_report_policy"]["read_only"] is True
    assert receipt["self_report_policy"]["write_performed"] is False
    assert receipt["self_report_policy"]["platform_write_performed"] is False
    assert receipt["self_report_policy"]["answers_observed"] is False
    assert receipt["self_report_policy"]["answers_verified"] is False
    assert receipt["self_report_policy"]["question_count"] == 6
    assert receipt["self_report_policy"]["no_user_prompt_performed"] is True
    assert receipt["self_report_answers_observed"] is False
    assert receipt["self_report_verified"] is False
    assert receipt["self_report_blockers"] == [
        "self_report_answers_not_observed",
        "self_report_not_verified",
    ]
    question_ids = {item["id"] for item in receipt["platform_self_report_questions"]}
    assert question_ids == {
        "platform_identity",
        "mcp_capability",
        "skill_surface",
        "config_write_authority",
        "declared_project_series",
        "post_connect_proof",
    }
    assert all(item["required_before_registration"] is True for item in receipt["platform_self_report_questions"])


def test_raw_gateway_rejects_expired_transport_session_before_dispatch(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), raw_gateway.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}/mcp"

    try:
        initialize = urllib.request.Request(
            endpoint,
            data=json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "stale-session-test", "version": "1"}},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(initialize, timeout=3) as response:
            session_id = response.headers["Mcp-Session-Id"]
            assert session_id

        runtime = raw_gateway._mcp_runtime()
        with runtime._MCP_SESSION_LOCK:
            runtime._MCP_SESSIONS.clear()

        called = []
        monkeypatch.setattr(
            raw_gateway,
            "handle_mcp_request",
            lambda *_args, **_kwargs: called.append(True) or {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"should_not_run": True},
            },
        )
        stale = urllib.request.Request(
            endpoint,
            data=json.dumps({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": session_id,
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(stale, timeout=3)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
            payload = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("expired MCP session was accepted")

        assert payload["error"]["code"] == -32001
        assert "reinitialize" in payload["error"]["message"]
        assert payload["error"]["data"] == {
            "contract": "time_library.mcp_session_rejection.v1",
            "reason": "session_not_found",
            "request_dispatched": False,
            "safe_to_retry_after_initialize": True,
        }
        assert called == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_persisted_host_resume_expires_without_restoring_verified_identity(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    delivery = importlib.import_module("src.time_library_delivery_runtime")
    old_context = _mcp_connection_context(
        tmp_path,
        "future xyz",
        token="expired-resume-token",
        inferred_platform_hint="unknown_mcp_client",
    )
    real_now = delivery._now
    monkeypatch.setattr(
        delivery,
        "_now",
        lambda: datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    receipt = delivery.record_verified_host_connection(
        old_context,
        {
            "ok": True,
            "self_report_verified": True,
            "client_info": {"self_reported_platform": "future_xyz"},
            "real_recall_proof": {
                "library_id": "ZX-EXPIRED-RESUME",
                "matched_count": 1,
                "source_refs_count": 1,
                "raw_excerpt_returned": False,
            },
        },
    )
    assert receipt["ok"] is True
    monkeypatch.setattr(delivery, "_now", real_now)

    runtime = raw_gateway._mcp_runtime()
    resumed_token, resumed_context = runtime.new_mcp_transport_session(
        {"clientInfo": {"name": "future xyz", "version": "1"}},
        resume_token=old_context["transport_session_id"],
    )

    assert resumed_token != old_context["transport_session_id"]
    assert resumed_context["resumed_verified_connection"] is False
    assert resumed_context["resume_rejected_reason"] == "verified_host_resume_expired"
    assert delivery.verified_host_connection(resumed_context)["ok"] is False


def test_verified_resume_serializes_against_old_bearer_business_dispatch(
    tmp_path,
    monkeypatch,
):
    _, raw_gateway = _reload_modules(tmp_path)
    delivery = importlib.import_module("src.time_library_delivery_runtime")
    runtime = raw_gateway._mcp_runtime()
    old_context = _mcp_connection_context(
        tmp_path,
        "future xyz",
        token="concurrent-old-bearer",
        inferred_platform_hint="unknown_mcp_client",
    )
    old_context["transport_session_id"] = "concurrent-old-bearer"
    receipt = delivery.record_verified_host_connection(
        old_context,
        {
            "ok": True,
            "self_report_verified": True,
            "client_info": {"self_reported_platform": "future_xyz"},
            "real_recall_proof": {
                "library_id": "ZX-CONCURRENT-RESUME",
                "matched_count": 1,
                "source_refs_count": 1,
                "raw_excerpt_returned": False,
            },
        },
    )
    assert receipt["ok"] is True
    old_token = old_context["transport_session_id"]
    with runtime._MCP_SESSION_LOCK:
        runtime._MCP_SESSIONS.clear()
        runtime._MCP_SESSIONS[old_token] = dict(old_context)

    rotation_entered = threading.Event()
    allow_rotation = threading.Event()
    real_rotate = delivery.rotate_verified_host_connection_resume

    def slow_rotate(*args, **kwargs):
        rotation_entered.set()
        assert allow_rotation.wait(timeout=3)
        return real_rotate(*args, **kwargs)

    monkeypatch.setattr(delivery, "rotate_verified_host_connection_resume", slow_rotate)
    business_dispatches = []
    real_handle = raw_gateway.handle_mcp_request

    def counted_handle(data, **kwargs):
        if data.get("method") == "tools/list":
            business_dispatches.append(data.get("id"))
        return real_handle(data, **kwargs)

    monkeypatch.setattr(raw_gateway, "handle_mcp_request", counted_handle)
    server = ThreadingHTTPServer(("127.0.0.1", 0), raw_gateway.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/mcp"
    resume_result = {}
    business_result = {}
    business_done = threading.Event()

    def post(payload, result):
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": old_token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                result["status"] = response.status
                result["headers"] = dict(response.headers.items())
                result["payload"] = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            result["status"] = exc.code
            result["payload"] = json.loads(exc.read().decode("utf-8"))

    resume_thread = threading.Thread(
        target=post,
        args=(
            {
                "jsonrpc": "2.0",
                "id": "resume",
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": old_context["client_name"],
                        "version": old_context["client_version"],
                    }
                },
            },
            resume_result,
        ),
    )

    def run_business():
        post(
            {
                "jsonrpc": "2.0",
                "id": "old-business",
                "method": "tools/list",
                "params": {},
            },
            business_result,
        )
        business_done.set()

    business_thread = threading.Thread(target=run_business)
    try:
        resume_thread.start()
        assert rotation_entered.wait(timeout=3)
        business_thread.start()
        assert business_done.wait(timeout=0.15) is False
        allow_rotation.set()
        resume_thread.join(timeout=5)
        business_thread.join(timeout=5)

        assert resume_thread.is_alive() is False
        assert business_thread.is_alive() is False
        assert resume_result["status"] == 200
        assert resume_result["headers"]["Mcp-Session-Id"] != old_token
        assert business_result["status"] == 404
        assert business_result["payload"]["error"]["data"]["request_dispatched"] is False
        assert business_dispatches == []
    finally:
        allow_rotation.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_invalid_session_tokens_do_not_accumulate_request_locks(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    runtime = raw_gateway._mcp_runtime()
    with runtime._MCP_SESSION_LOCK:
        runtime._MCP_SESSIONS.clear()
        runtime._MCP_SESSION_REQUEST_LOCKS.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), raw_gateway.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/mcp"

    def rejected_request(payload, token, expected_status):
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": token,
            },
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=5)
        try:
            assert raised.value.code == expected_status
            raised.value.read()
        finally:
            raised.value.close()

    try:
        for index in range(1000):
            rejected_request(
                {
                    "jsonrpc": "2.0",
                    "id": f"unknown-business-{index}",
                    "method": "tools/list",
                    "params": {},
                },
                f"unknown-business-token-{index}",
                404,
            )
        for index in range(1000):
            rejected_request(
                {
                    "jsonrpc": "2.0",
                    "id": f"unknown-resume-{index}",
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "unknown resume host",
                            "version": "1",
                        }
                    },
                },
                f"unknown-resume-token-{index}",
                409,
            )

        with runtime._MCP_SESSION_LOCK:
            assert runtime._MCP_SESSION_REQUEST_LOCKS == {}
            assert runtime._MCP_SESSIONS == {}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_agent_work_preflight_http_does_not_create_real_recall_proof(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    runtime = raw_gateway._mcp_runtime()
    server = ThreadingHTTPServer(("127.0.0.1", 0), raw_gateway.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/mcp"

    def post(payload, token=""):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Mcp-Session-Id"] = token
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return (
                json.loads(response.read().decode("utf-8")),
                response.headers.get("Mcp-Session-Id", ""),
            )

    try:
        _, token = post(
            {
                "jsonrpc": "2.0",
                "id": "initialize-agent-preflight",
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "agent preflight host",
                        "version": "1",
                    }
                },
            }
        )
        assert token
        response, _ = post(
            {
                "jsonrpc": "2.0",
                "id": "agent-preflight",
                "method": "tools/call",
                "params": {
                    "name": "time_library_recall",
                    "arguments": {
                        "query": "verified resume",
                        "mode": "agent_work_preflight",
                    },
                },
            },
            token,
        )
        assert response["result"]["structuredContent"]["mode"] == "work_preflight"
        state = runtime.mcp_transport_session(token)
        assert "real_recall_proofs" not in state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_rejected_resume_issues_no_session_and_does_not_dispatch_initialize(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), raw_gateway.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}/mcp"

    try:
        initial = urllib.request.Request(
            endpoint,
            data=json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "unverified host", "version": "1"}},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(initial, timeout=3) as response:
            old_token = response.headers["Mcp-Session-Id"]
        runtime = raw_gateway._mcp_runtime()
        with runtime._MCP_SESSION_LOCK:
            runtime._MCP_SESSIONS.clear()
        dispatched = []
        monkeypatch.setattr(
            raw_gateway,
            "handle_mcp_request",
            lambda *_args, **_kwargs: dispatched.append(True),
        )
        retry = urllib.request.Request(
            endpoint,
            data=json.dumps({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "initialize",
                "params": {"clientInfo": {"name": "unverified host", "version": "1"}},
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Mcp-Session-Id": old_token,
            },
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(retry, timeout=3)
        assert raised.value.code == 409
        assert raised.value.headers.get("Mcp-Session-Id") is None
        payload = json.loads(raised.value.read().decode("utf-8"))
        assert payload["error"]["code"] == -32002
        assert payload["error"]["data"] == {
            "contract": "time_library.mcp_resume_rejection.v1",
            "reason": "verified_host_connection_required",
            "request_dispatched": False,
            "session_issued": False,
            "safe_to_retry_without_user_reverification": False,
        }
        assert dispatched == []
        with runtime._MCP_SESSION_LOCK:
            assert runtime._MCP_SESSIONS == {}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_raw_gateway_mcp_initialize_malformed_client_info_stays_unregistered(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    initialized = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "clientInfo": {
                "name": ["Not", "A", "String"],
                "version": {"bad": "shape"},
                "raw_excerpt": "must not be propagated",
            },
        },
    })

    receipt = initialized["result"]["platformHandshakeReceipt"]
    assert receipt["client_info_present"] is True
    assert receipt["current_stage"] == "client_info_observed"
    assert receipt["handshake_observed"] is True
    assert receipt["handshake_verified"] is False
    assert receipt["registered"] is False
    assert receipt["recall_proven"] is False
    assert receipt["platform_write_performed"] is False
    assert receipt["memory_write_performed"] is False
    assert receipt["raw_excerpt_included"] is False
    assert receipt["self_report_policy"]["question_count"] == 6
    assert receipt["self_report_blockers"] == [
        "self_report_answers_not_observed",
        "self_report_not_verified",
    ]
    assert "must not be propagated" not in json.dumps(receipt, ensure_ascii=False)


def test_raw_gateway_mcp_initialize_empty_client_info_fields_count_as_missing(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    initialized = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"clientInfo": {"name": "", "version": ""}},
    })

    receipt = initialized["result"]["platformHandshakeReceipt"]
    assert receipt["client_info_present"] is False
    assert receipt["current_stage"] == "client_info_missing"
    assert receipt["handshake_observed"] is False
    assert receipt["handshake_verified"] is False
    assert receipt["verification_level"] == "none"
    assert receipt["registered"] is False
    assert receipt["recall_proven"] is False
    assert receipt["platform_write_performed"] is False
    assert receipt["memory_write_performed"] is False
    assert receipt["self_report_policy"]["question_count"] == 0
    assert receipt["platform_self_report_questions"] == []
    assert receipt["self_report_blockers"] == []


def test_raw_gateway_mcp_initialize_self_report_questions_are_sanitized_and_read_only(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    initialized = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "clientInfo": {
                "name": "Codex\u0000Desktop\n" + "x" * 200,
                "version": "26.630\t12135",
                "raw_excerpt": "must not be propagated",
            },
        },
    })

    receipt = initialized["result"]["platformHandshakeReceipt"]
    assert receipt["client_info_present"] is True
    assert receipt["current_stage"] == "client_info_observed"
    assert receipt["registered"] is False
    assert receipt["platform_write_performed"] is False
    assert receipt["memory_write_performed"] is False
    assert receipt["chat_body_included"] is False
    assert receipt["raw_excerpt_included"] is False
    assert "\u0000" not in receipt["client_name"]
    assert "\n" not in receipt["client_name"]
    assert "\t" not in receipt["client_version"]
    assert len(receipt["client_name"]) <= 120
    assert receipt["client_name"].endswith("…")
    assert "must not be propagated" not in json.dumps(receipt, ensure_ascii=False)
    assert receipt["self_report_policy"]["read_only"] is True
    assert receipt["self_report_policy"]["write_performed"] is False
    assert receipt["self_report_policy"]["platform_write_performed"] is False
    assert receipt["self_report_policy"]["question_count"] == 6
    assert receipt["self_report_answers_observed"] is False
    assert receipt["self_report_verified"] is False


def test_raw_gateway_mcp_initialize_control_only_client_info_counts_as_missing(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    initialized = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"clientInfo": {"name": "\u0000\n\t", "version": "\r\u0000"}},
    })

    receipt = initialized["result"]["platformHandshakeReceipt"]
    assert receipt["client_info_present"] is False
    assert receipt["current_stage"] == "client_info_missing"
    assert receipt["registered"] is False
    assert receipt["platform_write_performed"] is False
    assert receipt["memory_write_performed"] is False
    assert receipt["platform_self_report_questions"] == []
    assert receipt["self_report_answers_observed"] is False
    assert receipt["self_report_verified"] is False
    assert receipt["self_report_blockers"] == []


def test_platform_handshake_self_report_contract_makes_no_shell_call(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    calls: list[str] = []

    def fail_shell(command):
        calls.append(str(command))
        raise AssertionError("shell call is not allowed in platform handshake")

    monkeypatch.setattr(raw_gateway.os, "system", fail_shell)

    receipt = raw_gateway._platform_handshake_receipt({
        "clientInfo": {"name": "MiniMax Agent", "version": "M3"},
    })

    assert calls == []
    assert receipt["inferred_platform"] == "minimax"
    assert receipt["registered"] is False
    assert receipt["platform_write_performed"] is False
    assert receipt["self_report_policy"]["question_source"] == "static_read_only_handshake_contract"


def test_mcp_reading_area_self_report_connect_issues_card_and_proves_recall(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    p4_provider = importlib.import_module("src.p4_provider")

    def fake_fetch(*_args, **_kwargs):
        raise AssertionError("self_report_connect must not perform a hidden catalog borrow")

    monkeypatch.setattr(p4_provider, "fetch_catalog_card_by_library_id", fake_fetch)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "self_report_connect",
                "source_system": "minimax",
                "consumer": "minimax",
                "client_name": "MiniMax Agent",
                "client_version": "M3",
                "client_surface": "skill+mcp",
                "canonical_window_id": "m3-window-001",
                "session_id": "m3-session-001",
                "title": "MiniMax M3 working window",
                "reading_area": "阅读区",
                "declared_project_ids": ["Time Library"],
                "declared_series_ids": ["Shared Reading Series"],
                "skill_surface_status": "skill_installed",
                "config_write_authority": False,
                "proof_library_id": "ZX-RAW-PROOF",
                "request_id": "self-report-001",
            },
        },
    }, connection_context=_mcp_connection_context(
        tmp_path,
        "MiniMax Agent",
        client_version="M3",
        proof_library_id="ZX-RAW-PROOF",
        proof_source_system_filter="minimax",
    ))
    content = called["result"]["structuredContent"]

    assert called["result"]["isError"] is False
    assert content["contract"] == "time_library_platform_self_report_receipt.v1"
    assert content["reading_area_registered"] is True
    assert content["platform_config_registered"] is False
    assert content["registration_blockers"] == []
    assert content["platform_write_performed"] is False
    assert content["memory_write_performed"] is False
    assert content["raw_write_performed"] is False
    assert content["reading_area_content_write_performed"] is False
    assert content["capability_check_advert"]["ok"] is True
    assert content["capability_check_advert"]["recall_performed"] is False
    assert content["real_recall_proof"]["ok"] is True
    assert content["real_recall_proof"]["raw_excerpt_returned"] is False
    assert content["borrowing_card_receipt"]["ok"] is True
    assert content["membership_receipt"]["ok"] is True
    assert content["membership_receipt"]["technical_project_id_used_as_declared_identity"] is False

    registry = importlib.import_module("src.reading_area_registry").load_registry()
    cards = registry["borrowing_cards"]
    assert len(cards) == 1
    card = next(iter(cards.values()))
    assert card["source_system"] == "minimax"
    assert card["canonical_window_id"] == "m3-window-001"
    assert card["declared_project_ids"] == content["membership_receipt"]["project_ids"]
    assert card["declared_series_ids"] == content["membership_receipt"]["series_ids"]


def test_self_reported_identity_is_authoritative_when_client_name_hint_disagrees(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    p4_provider = importlib.import_module("src.p4_provider")

    monkeypatch.setattr(
        p4_provider,
        "fetch_catalog_card_by_library_id",
        lambda library_id, **_kwargs: {
            "ok": True,
            "library_id": library_id,
            "shelf": "raw",
            "card": {
                "library_id": library_id,
                "source_refs": {"source_system": "codex", "source_path": "/tmp/proof.jsonl"},
            },
            "source_refs": {"source_system": "codex", "source_path": "/tmp/proof.jsonl"},
            "raw_source_excerpt": "identity proof",
            "verbatim_excerpt": "identity proof",
        },
    )

    result = raw_gateway._platform_self_report_connect_payload({
        "source_system": "hermes",
        "consumer": "hermes",
        "client_name": "Codex Desktop",
        "client_version": "test",
        "session_id": "identity-mismatch-session",
        "declared_project_ids": ["Time Library"],
        "skill_surface_status": "mcp_only",
        "config_write_authority": False,
        "proof_library_id": "ZX-RAW-IDENTITY-PROOF",
    }, connection_context=_mcp_connection_context(
        tmp_path,
        "Codex Desktop",
        inferred_platform_hint="codex",
        proof_library_id="ZX-RAW-IDENTITY-PROOF",
        proof_source_system_filter="codex",
    ))

    assert result["ok"] is True
    assert result["client_info"]["self_reported_platform"] == "hermes"
    assert result["client_info"]["inferred_platform_hint"] == "codex"
    assert result["client_info"]["identity_authority"] == "host_self_report"
    assert result["client_info"]["identity_mismatch"] is True


def test_verified_transport_session_rebind_is_rejected_before_registry_write(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    p4_provider = importlib.import_module("src.p4_provider")
    reading_registry = importlib.import_module("src.reading_area_registry")
    delivery_runtime = importlib.import_module("src.time_library_delivery_runtime")

    monkeypatch.setattr(
        p4_provider,
        "fetch_catalog_card_by_library_id",
        lambda library_id, **_kwargs: {
            "ok": True,
            "library_id": library_id,
            "shelf": "raw",
            "card": {
                "library_id": library_id,
                "source_refs": {"source_system": "local_files", "source_path": "/tmp/proof.jsonl"},
            },
            "source_refs": {"source_system": "local_files", "source_path": "/tmp/proof.jsonl"},
            "raw_source_excerpt": "connection identity proof",
            "verbatim_excerpt": "connection identity proof",
        },
    )
    context = _mcp_connection_context(
        tmp_path,
        "Generic Host",
        token="immutable-session",
        proof_library_id="ZX-RAW-CONNECTION-PROOF",
        proof_source_system_filter="local_files",
        proof_matched_count=7,
        proof_raw_excerpt_returned=False,
    )
    first = raw_gateway._platform_self_report_connect_payload({
        "source_system": "host_alpha",
        "consumer": "host alpha",
        "session_id": "alpha-session",
        "declared_project_ids": ["Example Project A"],
        "skill_surface_status": "mcp_only",
        "config_write_authority": False,
        "proof_library_id": "ZX-RAW-CONNECTION-PROOF",
    }, connection_context=context)

    assert first["ok"] is True
    registry_path = reading_registry.registry_path()
    registry_before = registry_path.read_bytes()
    connection_rows_before = delivery_runtime.query_verified_host_connections(
        memcore_root=tmp_path / "memcore",
    )

    repeated = raw_gateway._platform_self_report_connect_payload({
        "source_system": "host_alpha",
        "consumer": "different display label",
        "session_id": "attempted-new-session",
        "declared_project_ids": ["Project Must Not Be Added"],
        "skill_surface_status": "mcp_only",
        "config_write_authority": False,
        "proof_library_id": "ZX-RAW-CONNECTION-PROOF",
    }, connection_context=context)
    rebound = raw_gateway._platform_self_report_connect_payload({
        "source_system": "host_beta",
        "consumer": "host beta",
        "session_id": "beta-session",
        "declared_project_ids": ["Project Beta"],
        "skill_surface_status": "mcp_only",
        "config_write_authority": False,
        "proof_library_id": "ZX-RAW-CONNECTION-PROOF",
    }, connection_context=context)

    assert repeated["ok"] is True
    assert repeated["idempotent"] is True
    assert repeated["write_performed"] is False
    assert repeated["real_recall_proof"]["matched_count"] == 7
    assert repeated["real_recall_proof"]["raw_excerpt_returned"] is False
    assert repeated["real_recall_proof"]["recall_source_system_filter"] == "local_files"
    assert rebound["ok"] is False
    assert rebound["error"] == "transport_session_identity_already_bound"
    assert rebound["write_performed"] is False
    assert registry_path.read_bytes() == registry_before
    assert delivery_runtime.query_verified_host_connections(
        memcore_root=tmp_path / "memcore",
    ) == connection_rows_before
    saved = reading_registry.load_registry()
    assert len(saved["borrowing_cards"]) == 1
    assert next(iter(saved["borrowing_cards"].values()))["source_system"] == "host_alpha"


def test_consumer_self_report_does_not_depend_on_a_native_history_parser(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    p4_provider = importlib.import_module("src.p4_provider")
    hermes_paths = importlib.import_module("src.hermes_paths")

    monkeypatch.setattr(
        p4_provider,
        "fetch_catalog_card_by_library_id",
        lambda library_id, **_kwargs: {
            "ok": True,
            "library_id": library_id,
            "shelf": "raw",
            "card": {
                "library_id": library_id,
                "source_refs": {"source_system": "local_files", "source_path": "/tmp/proof.jsonl"},
            },
            "source_refs": {"source_system": "local_files", "source_path": "/tmp/proof.jsonl"},
            "raw_source_excerpt": "parser independent proof",
            "verbatim_excerpt": "parser independent proof",
        },
    )
    monkeypatch.setattr(
        hermes_paths,
        "hermes_state_db_path",
        lambda: (_ for _ in ()).throw(AssertionError("native parser lookup must not run")),
    )

    result = raw_gateway._platform_self_report_connect_payload({
        "source_system": "hermes",
        "consumer": "hermes",
        "client_name": "",
        "session_id": "parser-free-consumer-session",
        "declared_project_ids": ["Time Library"],
        "skill_surface_status": "mcp_only",
        "config_write_authority": False,
        "proof_library_id": "ZX-RAW-PARSER-FREE",
    }, connection_context=_mcp_connection_context(
        tmp_path,
        "Hermes",
        proof_library_id="ZX-RAW-PARSER-FREE",
        proof_source_system_filter="codex",
    ))

    assert result["ok"] is True
    assert result["reading_area_registered"] is True
    assert result["client_info"]["self_reported_platform"] == "hermes"
    assert result["consumer_connection_requires_native_parser"] is False


def test_self_report_connect_as_first_request_fails_before_any_registry_or_delivery_write(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "self_report_connect",
                "source_system": "uninitialized_host",
                "session_id": "uninitialized-window",
                "declared_project_ids": ["Time Library"],
                "skill_surface_status": "mcp_only",
                "config_write_authority": False,
                "proof_library_id": "ZX-NOT-READ",
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["error"] == "mcp_initialize_session_required"
    assert content["self_report_verified"] is False
    assert content["registry_write_performed"] is False
    assert not (tmp_path / "memcore" / "runtime" / "delivery-events.sqlite3").exists()
    registry = importlib.import_module("src.reading_area_registry").load_registry()
    assert registry["borrowing_cards"] == {}


def test_unknown_client_runs_install_recall_challenge_delivery_and_accounting(tmp_path):
    _write_startup_catalog_candidate(tmp_path)
    marker = "platform-neutral-real-recall-marker-20260715"
    _write_memory(
        tmp_path,
        "codex",
        "platform-neutral-session",
        "2026-07-15T12:00:00Z",
        marker,
        "真实回源内容 " + marker,
    )
    _, raw_gateway = _reload_modules(tmp_path)
    registry_module = importlib.import_module("src.platform_thin_adapter_registry")
    connection_context = _mcp_connection_context(
        tmp_path,
        "future xyz",
        token="future-transport",
        inferred_platform_hint="unknown_mcp_client",
    )

    initialized = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"clientInfo": {"name": "future xyz", "version": "1"}},
    }, connection_context=connection_context)
    startup_library_id = initialized["result"]["startupCatalog"]["catalog"][0]["library_id"]
    unverified = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "library_id": startup_library_id,
                "consumer": "future_xyz",
            },
        },
    }, connection_context=connection_context)["result"]["structuredContent"]
    assert unverified["delivery_runtime"]["error"] == "verified_host_connection_required"
    assert not (tmp_path / "memcore" / "runtime" / "delivery-events.sqlite3").exists()

    capability = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "query": "capability check",
                "mode": "capability_check",
                "consumer": "future_xyz",
            },
        },
    }, connection_context=connection_context)["result"]["structuredContent"]
    assert capability["ok"] is True
    assert capability["recall_performed"] is False

    first_recall_request = {
        "jsonrpc": "2.0",
        "id": "first-authorized-recall",
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "query": marker,
                "consumer": "future_xyz",
                "source_system": "codex",
                "memory_scope": "raw_pool",
                "allow_cross_window_recall": True,
                "limit": 3,
            },
        },
    }
    first_recall_response = raw_gateway.handle_mcp_request(
        first_recall_request,
        connection_context=connection_context,
    )
    first_recall = first_recall_response["result"]["structuredContent"]
    assert first_recall["matched_count"] > 0
    assert first_recall["delivery_runtime"]["error"] == "verified_host_connection_required"
    session_proofs = raw_gateway._mcp_real_recall_proofs(
        first_recall_request,
        first_recall_response,
    )
    assert session_proofs
    connection_context["real_recall_proofs"] = {
        proof["library_id"]: proof for proof in session_proofs
    }
    proof_library_id = session_proofs[0]["library_id"]

    connected = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "self_report_connect",
                "source_system": "future_xyz",
                "consumer": "future_xyz",
                "client_name": "future xyz",
                "session_id": "future-session",
                "declared_project_ids": ["Time Library"],
                "skill_surface_status": "custom_instruction_installed",
                "config_write_authority": False,
                "proof_library_id": proof_library_id,
            },
        },
    }, connection_context=connection_context)["result"]["structuredContent"]
    assert connected["self_report_verified"] is True
    connection_receipt_id = connected["connection_receipt"]["receipt_id"]

    install = registry_module.apply_authorized_auto_connect(
        {
            "system": "future_xyz",
            "host_capabilities": {
                "mcp_capability": True,
                "skill_surface": "custom_instruction",
                "config_write_owner": "host",
                "startup_catalog_policy": "deferred",
            },
            "host_install_performed": True,
            "host_install_receipt": "future-host-installed-time-library-mcp",
            "connection_receipt_id": connection_receipt_id,
        },
        home=tmp_path / "future-home",
        memcore_root=tmp_path / "memcore",
    )
    assert install["ok"] is True
    assert install["status"] == "host_self_install_recorded"
    assert install["platform_write_performed"] is False

    runtime = raw_gateway._mcp_runtime()
    prior_transport_token = connection_context["transport_session_id"]
    with runtime._MCP_SESSION_LOCK:
        runtime._MCP_SESSIONS.clear()
        runtime._MCP_SESSIONS[prior_transport_token] = dict(connection_context)
    resumed_token, resumed_context = runtime.new_mcp_transport_session(
        {"clientInfo": {"name": "future xyz", "version": "1"}},
        resume_token=prior_transport_token,
    )
    assert resumed_token != prior_transport_token
    assert resumed_context["resumed_verified_connection"] is True
    assert resumed_context["verified_platform"] == "future_xyz"
    assert resumed_context["resume_rejected_reason"] == ""
    with runtime._MCP_SESSION_LOCK:
        assert prior_transport_token not in runtime._MCP_SESSIONS
        assert resumed_token in runtime._MCP_SESSIONS
    first_rotated_receipt = runtime._delivery_runtime().verified_host_connection(
        resumed_context
    )
    assert first_rotated_receipt["resume_generation"] == 1
    replayed_token, replayed_context = runtime.new_mcp_transport_session(
        {"clientInfo": {"name": "future xyz", "version": "1"}},
        resume_token=prior_transport_token,
    )
    assert replayed_token not in {prior_transport_token, resumed_token}
    assert replayed_context["resumed_verified_connection"] is False
    assert replayed_context["resume_rejected_reason"] == "verified_host_resume_already_consumed"
    with runtime._MCP_SESSION_LOCK:
        runtime._MCP_SESSIONS.clear()
    second_resumed_token, second_resumed_context = runtime.new_mcp_transport_session(
        {"clientInfo": {"name": "future xyz", "version": "1"}},
        resume_token=resumed_token,
    )
    assert second_resumed_token not in {
        prior_transport_token,
        resumed_token,
        replayed_token,
    }
    assert second_resumed_context["resumed_verified_connection"] is True
    second_rotated_receipt = runtime._delivery_runtime().verified_host_connection(
        second_resumed_context
    )
    assert second_rotated_receipt["resume_generation"] == 2
    connection_context = second_resumed_context

    whiteboard = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": "post-restart-whiteboard",
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "whiteboard_list",
                "source_system": "future_xyz",
            },
        },
    }, connection_context=connection_context)["result"]["structuredContent"]
    assert whiteboard["ok"] is True

    direct_borrow = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": "post-restart-direct-borrow",
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "library_id": startup_library_id,
                "consumer": "future_xyz",
            },
        },
    }, connection_context=connection_context)["result"]["structuredContent"]
    assert direct_borrow["delivery_runtime"]["ok"] is True

    recalled = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "query": marker,
                "consumer": "future_xyz",
                "source_system": "codex",
                "memory_scope": "raw_pool",
                "allow_cross_window_recall": True,
                "limit": 3,
            },
        },
    }, connection_context=connection_context)["result"]["structuredContent"]
    assert recalled["matched_count"] > 0
    challenge = recalled["delivery_runtime"]["challenge"]

    bad = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "time_library_delivery_ack",
            "arguments": {
                "challenge_id": challenge["challenge_id"],
                "challenge": "wrong-challenge",
                "retrieval_id": challenge["retrieval_id"],
                "platform": "future_xyz",
                "request_id": "future-host-request-bad",
                "used_source_refs": challenge["selected_source_refs"],
                "response_evidence_ref": "future-host-response",
            },
        },
    }, connection_context=connection_context)["result"]["structuredContent"]
    assert bad["error"] == "delivery_challenge_mismatch"

    delivered = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "time_library_delivery_ack",
            "arguments": {
                "challenge_id": challenge["challenge_id"],
                "challenge": challenge["challenge"],
                "retrieval_id": challenge["retrieval_id"],
                "platform": "future_xyz",
                "request_id": "future-host-request-good",
                "used_source_refs": challenge["selected_source_refs"],
                "response_evidence_ref": "future-host-response",
            },
        },
    }, connection_context=connection_context)["result"]["structuredContent"]
    assert delivered["ok"] is True
    assert delivered["latest_proven_stage"] == "used"

    delivery_runtime = importlib.import_module("src.time_library_delivery_runtime")
    status = delivery_runtime.query_delivery_status(
        memcore_root=tmp_path / "memcore",
        platform="future_xyz",
    )
    assert status["stages"]["delivered"]["state"] == "observed"
    assert status["stages"]["used"]["state"] == "observed"
    assert status["totals"]["security_events"] == 1


def test_mcp_reading_area_self_report_connect_requires_real_recall_proof(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    runtime = importlib.import_module("src.raw_gateway_mcp_runtime")
    monkeypatch.setattr(
        runtime,
        "_catalog_card_borrow_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("missing session proof must not trigger a hidden catalog borrow")
        ),
    )

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "self_report_connect",
                "source_system": "minimax",
                "consumer": "minimax",
                "client_name": "MiniMax Agent",
                "canonical_window_id": "m3-window-002",
                "reading_area": "阅读区",
                "declared_project_ids": ["Time Library"],
                "declared_series_ids": ["Shared Reading Series"],
                "skill_surface_status": "skill_installed",
                "config_write_authority": False,
                "proof_library_id": "ZX-NOT-READ",
            },
        },
    }, connection_context=_mcp_connection_context(tmp_path, "MiniMax Agent", token="missing-proof"))
    content = called["result"]["structuredContent"]

    assert called["result"]["isError"] is True
    assert content["ok"] is False
    assert content["reading_area_registered"] is False
    assert "real_recall_not_proven" in content["registration_blockers"]
    assert content["registry_write_performed"] is False
    assert content["borrowing_card_receipt"]["status"] == "not_attempted_until_self_report_and_recall_proof_pass"
    assert content["platform_write_performed"] is False
    assert content["memory_write_performed"] is False
    assert content["raw_write_performed"] is False
    registry = importlib.import_module("src.reading_area_registry").load_registry()
    assert registry["borrowing_cards"] == {}


def test_mcp_reading_area_self_report_connect_rejects_empty_recall_proof(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    p4_provider = importlib.import_module("src.p4_provider")

    def fake_fetch(library_id, **kwargs):
        return {
            "ok": True,
            "library_id": library_id,
            "shelf": "raw",
            "card": {"library_id": library_id, "shelf": "raw", "title": "empty proof"},
            "source_refs": {},
            "raw_source_excerpt": "",
            "verbatim_excerpt": "",
        }

    monkeypatch.setattr(p4_provider, "fetch_catalog_card_by_library_id", fake_fetch)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "self_report_connect",
                "source_system": "minimax",
                "consumer": "minimax",
                "client_name": "MiniMax Agent",
                "canonical_window_id": "m3-window-004",
                "reading_area": "阅读区",
                "declared_project_ids": ["Time Library"],
                "declared_series_ids": ["Shared Reading Series"],
                "skill_surface_status": "skill_installed",
                "config_write_authority": False,
                "proof_library_id": "ZX-RAW-EMPTY",
            },
        },
    }, connection_context=_mcp_connection_context(
        tmp_path,
        "MiniMax Agent",
        token="empty-proof",
        proof_library_id="ZX-RAW-EMPTY",
        proof_source_system_filter="minimax",
        proof_source_refs_count=0,
    ))
    content = called["result"]["structuredContent"]

    assert called["result"]["isError"] is True
    assert content["ok"] is False
    assert content["real_recall_proof"]["ok"] is True
    assert content["real_recall_proof"]["raw_excerpt_returned"] is False
    assert "real_recall_not_proven" in content["registration_blockers"]
    assert content["registry_write_performed"] is False
    registry = importlib.import_module("src.reading_area_registry").load_registry()
    assert registry["borrowing_cards"] == {}


def test_mcp_reading_area_tool_rejects_unknown_arguments(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "issue_borrowing_card",
                "source_system": "minimax",
                "canonical_window_id": "m3-window-003",
                "unexpected": "must not pass strict tool boundary",
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert called["result"]["isError"] is True
    assert content["ok"] is False
    assert content["error"] == "unknown_reading_area_arguments"
    assert content["unknown_arguments"] == ["unexpected"]
    assert content["registry_write_performed"] is False


def test_mcp_borrowing_card_requires_explicit_source_system_and_never_infers_from_display_name(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    for index, identity_fields in enumerate(
        (
            {"consumer": "mimocode", "client_name": "MiMoCode"},
            {"consumer": "future client", "client_name": "Future Client"},
            {"platform_name": "mimocode", "consumer": "mimocode"},
        ),
        start=1,
    ):
        called = raw_gateway.handle_mcp_request({
            "jsonrpc": "2.0",
            "id": 40 + index,
            "method": "tools/call",
            "params": {
                "name": "time_library_reading_area",
                "arguments": {
                    "action": "issue_borrowing_card",
                    "canonical_window_id": f"window-{index}",
                    **identity_fields,
                },
            },
        })
        content = called["result"]["structuredContent"]

        assert called["result"]["isError"] is True
        assert content["ok"] is False
        assert content["error"] == "source_system_self_report_required"
        assert content["registry_write_performed"] is False
        assert content["write_performed"] is False

    registry = importlib.import_module("src.reading_area_registry").load_registry()
    assert registry["borrowing_cards"] == {}


def test_mcp_reading_area_whiteboard_write_and_list(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    issue = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "issue_borrowing_card",
                "source_system": "codex",
                "consumer": "codex",
                "canonical_window_id": "wb-gateway-window",
                "session_id": "wb-gateway-session",
            },
        },
    })["result"]["structuredContent"]
    card_id = issue["card_id"]

    membership = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "declare_membership",
                "borrowing_card_id": card_id,
                "reading_area": "Time Library阅读区",
                "declared_project_ids": ["Time Library"],
                "declared_series_ids": ["Shared Reading Series"],
                "declared_roles": ["施工"],
            },
        },
    })["result"]["structuredContent"]

    written = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 12,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "whiteboard_write",
                "borrowing_card_id": card_id,
                "record_type": "claim_task",
                "task_id": "gateway-whiteboard-alpha",
                "task_name": "whiteboard block A",
                "summary": "甲块施工中，等二签接棒。",
                "next_owner": "二签",
                "request_id": "wb-gateway-1",
                "library_ids": ["ZX-ZHIYI-1"],
            },
        },
    })
    content = written["result"]["structuredContent"]

    assert written["result"]["isError"] is False
    assert content["mode"] == "whiteboard_write"
    assert content["record"]["role"] == "施工"
    assert content["record"]["declared_project_ids"] == membership["project_ids"]

    listed = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 13,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "whiteboard_list",
                "borrowing_card_id": card_id,
            },
        },
    })
    listed_content = listed["result"]["structuredContent"]

    assert listed["result"]["isError"] is False
    assert listed_content["mode"] == "whiteboard_list"
    assert listed_content["record_count"] == 1
    assert listed_content["records"][0]["record_id"] == content["record_id"]
    assert listed_content["records"][0]["display_line"].startswith("在飞：施工/codex whiteboard block A")


def test_mcp_reading_area_project_history_and_nomination_actions(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    source_path = tmp_path / "history-source.jsonl"
    text = "用户裁定：白板历史从蒸馏补到项目页 history。"
    source_path.write_text(text, encoding="utf-8")

    issue = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "issue_borrowing_card",
                "source_system": "codex",
                "consumer": "codex",
                "canonical_window_id": "history-gateway-window",
                "session_id": "history-gateway-session",
            },
        },
    })["result"]["structuredContent"]
    card_id = issue["card_id"]
    membership = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "declare_membership",
                "borrowing_card_id": card_id,
                "declared_project_ids": ["Time Library"],
                "declared_series_ids": ["Shared Reading Series"],
            },
        },
    })["result"]["structuredContent"]

    written = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "project_history_write",
                "borrowing_card_id": card_id,
                "history_type": "decision",
                "title": "白板历史从蒸馏补",
                "summary": "老项目进入白板后从现在记录，历史由蒸馏补。",
                "source_refs": [{
                    "source_system": "codex",
                    "source_path": str(source_path),
                    "source_author": "user",
                    "byte_offsets": {"start": 0, "end": len(text.encode("utf-8"))},
                    "verbatim_excerpt": text,
                }],
                "request_id": "mcp-history-1",
            },
        },
    })["result"]["structuredContent"]

    assert written["ok"] is True
    assert written["mode"] == "project_history_write"
    assert written["record_id"].startswith("PH-")
    listed = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 23,
        "method": "tools/call",
        "params": {
                "name": "time_library_reading_area",
                "arguments": {
                    "action": "project_history_list",
                    "borrowing_card_id": card_id,
                    "declared_project_ids": membership["project_ids"],
                },
        },
    })["result"]["structuredContent"]
    assert listed["mode"] == "project_history_list"
    assert listed["record_count"] == 1
    assert listed["records"][0]["record_id"] == written["record_id"]

    nomination = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 24,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "nomination_create",
                "source_system": "codex",
                "session_id": "old-session",
                "source_path": "/tmp/old-session.jsonl",
                "nominated_project": "Time Library",
                "reason": "关键词相似，只生成提名。",
                "confidence": 0.5,
            },
        },
    })["result"]["structuredContent"]
    assert nomination["ok"] is True
    assert nomination["declared_membership_written"] is False

    claimed = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 25,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {
                "action": "claim_nomination",
                "nomination_id": nomination["nomination_id"],
                "borrowing_card_id": card_id,
            },
        },
    })["result"]["structuredContent"]
    assert claimed["ok"] is True
    assert claimed["declared_membership_written"] is True


def test_raw_gateway_mcp_initialize_passively_delivers_startup_catalog(tmp_path):
    _write_startup_catalog_candidate(tmp_path)
    _, raw_gateway = _reload_modules(tmp_path)

    initialized = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    })

    result = initialized["result"]
    assert result["serverInfo"]["name"] == "time-library"
    assert "time-library" in result["serverInfo"]["legacyNames"]
    assert "Time Library" in result["instructions"]
    assert "发布前应执行完整测试" in result["instructions"]
    assert "正文 detail" not in result["instructions"]
    assert result["startupCatalog"]["ok"] is True
    assert result["startupCatalog"]["catalog_entry_count"] == 1
    assert result["startupCatalog"]["system_prompt_token_count"] >= result["startupCatalog"]["inject_token_count"]
    assert result["startupCatalog"]["reading_area_block_token_count"] == 0
    assert result["startupCatalog"]["contains_body_markers"] is False
    assert result["startupCatalog"]["no_window_binding_required"] is True
    assert result["startupCatalog"]["catalog"][0]["library_id"].startswith("ZX-XINGCE-")
    assert result["startupCatalog"]["catalog"][0]["source_ref"]
    receipt = result["startupCatalogDeliveryReceipt"]
    assert receipt["contract"] == "time_library_startup_catalog_delivery_receipt.v1"
    assert receipt["passive_delivery"] is True
    assert receipt["consumer_invoked_tool"] is False
    assert receipt["consumer_called_catalog_endpoint"] is False
    assert receipt["new_window_startup_auto_injection"] is True
    assert receipt["system_prompt_token_count"] >= receipt["inject_token_count"]
    assert receipt["reading_area_block_token_count"] == 0
    assert receipt["library_id_pull_available"] is True


def test_raw_gateway_mcp_initialize_can_defer_private_startup_catalog(tmp_path):
    _write_startup_catalog_candidate(tmp_path)
    _, raw_gateway = _reload_modules(tmp_path)

    initialized = raw_gateway.handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "claude-code", "version": "test"}},
        },
        startup_catalog_mode="deferred",
    )

    result = initialized["result"]
    encoded = json.dumps(result, ensure_ascii=False)
    assert result["startupCatalog"]["delivery"] == "deferred_native_preflight_client"
    assert result["startupCatalog"]["catalog_entry_count"] == 0
    assert result["startupCatalog"]["catalog"] == []
    assert result["startupCatalog"]["private_catalog_text_delivered"] is False
    assert "发布前应执行完整测试" not in encoded
    assert "正文 detail" not in encoded
    assert result["startupCatalogDeliveryReceipt"]["passive_delivery"] is False
    assert result["startupCatalogDeliveryReceipt"]["new_window_startup_auto_injection"] is False


def test_raw_gateway_mcp_initialize_startup_catalog_matches_p4_builder_including_errata(tmp_path):
    _write_startup_catalog_candidate(tmp_path)
    _write_startup_catalog_errata_candidate(tmp_path)
    _, raw_gateway = _reload_modules(tmp_path)
    p4_provider = importlib.import_module("src.p4_provider")

    assert raw_gateway.STARTUP_CATALOG_TARGET_TOKENS == p4_provider.DEFAULT_CATALOG_TARGET_TOKENS

    initialized = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    })
    startup = initialized["result"]["startupCatalog"]
    builder = p4_provider.build_catalog_inject_from_candidates(
        target_tokens=p4_provider.DEFAULT_CATALOG_TARGET_TOKENS,
        xingce_root=str(tmp_path / "memcore"),
        include_raw_index=False,
    )

    startup_counts = {}
    for entry in startup["catalog"]:
        startup_counts[entry["shelf"]] = startup_counts.get(entry["shelf"], 0) + 1
    builder_counts = {}
    for entry in builder["catalog"]:
        builder_counts[entry["shelf"]] = builder_counts.get(entry["shelf"], 0) + 1

    assert startup["catalog_entry_count"] == builder["catalog_entry_count"]
    assert startup_counts == builder_counts
    assert startup_counts["errata"] == 1
    assert any(entry["shelf"] == "errata" for entry in startup["catalog"])


def test_raw_gateway_mcp_tools_expose_time_library_name_and_legacy_alias(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    tools = raw_gateway.mcp_tools_payload()["tools"]
    names = {tool["name"] for tool in tools}
    primary = next(tool for tool in tools if tool["name"] == "time_library_recall")
    schema_properties = primary["inputSchema"]["properties"]

    assert "time_library_recall" in names
    assert "zhiyi_recall" in names
    assert "time_library_reading_area" in names
    assert "time_library_delivery_ack" in names
    assert "library_id" in schema_properties
    assert primary["inputSchema"]["required"] == []
    assert "recall_mode" in schema_properties
    assert schema_properties["recall_mode"]["enum"] == ["", "substring", "vector"]
    assert "fts5_recall" in schema_properties
    assert schema_properties["fts5_recall"]["type"] == "boolean"
    assert "enable_fts5_recall" in schema_properties
    assert schema_properties["enable_fts5_recall"]["type"] == "boolean"

    reading_area = next(tool for tool in tools if tool["name"] == "time_library_reading_area")
    reading_schema = reading_area["inputSchema"]
    assert reading_schema["required"] == ["action"]
    assert "oneOf" in reading_schema
    assert reading_schema["properties"]["action"]["enum"] == [
        "issue_borrowing_card",
        "declare_membership",
        "self_report_connect",
        "whiteboard_write",
        "whiteboard_list",
        "project_history_write",
        "project_history_list",
        "nomination_create",
        "nomination_list",
        "claim_nomination",
        "reject_nomination",
    ]
    assert "proof_library_id" in reading_schema["properties"]
    assert "declared_roles" in reading_schema["properties"]
    assert "record_type" in reading_schema["properties"]
    assert "history_type" in reading_schema["properties"]
    assert "nomination_id" in reading_schema["properties"]
    assert "nominated_project" in reading_schema["properties"]
    assert "nominated_series" in reading_schema["properties"]


def test_raw_gateway_mcp_explicit_fts5_recall_reaches_p3_and_surfaces_telemetry(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    raw_path = tmp_path / "source.jsonl"
    source_text = "远程桌面 3389 需要通过组网工具再连接。"
    raw_path.write_text(source_text, encoding="utf-8")
    calls = []

    def fake_handle_recall(body):
        calls.append(dict(body))
        assert body["recall_mode"] == "substring"
        assert body["fts5_recall"] is True
        return {
            "matched_memories": [
                {
                    "exp_id": "exp-fts5",
                    "type": "xingce_work_experience_candidate",
                    "summary": "远程桌面不要直暴露3389端口",
                    "detail": "远程桌面不要直暴露3389端口",
                    "source_refs": json.dumps(
                        {
                            "source_system": "codex",
                            "computer_name": "local",
                            "canonical_window_id": "window-a",
                            "session_id": "session-a",
                            "source_path": str(raw_path),
                            "byte_offsets": {"start": 0, "end": len(source_text.encode("utf-8"))},
                        },
                        ensure_ascii=False,
                    ),
                    "matched_by": "fts5_bm25",
                    "rank_reason": "sqlite_fts5_trigram_bm25",
                    "_fts5": {
                        "matched_by": "fts5_bm25",
                        "rank_reason": "sqlite_fts5_trigram_bm25",
                    },
                }
            ],
            "fts5_applied": True,
            "fts5_status": {"error": None, "doc_count": 3, "applied": True},
            "fts5_rank_reason": "sqlite_fts5_trigram_bm25",
            "primary_recall_backend": "keyword+fts5",
            "primary_recall_modes": ["substring", "fts5"],
            "ranking_owner": "keyword+fts5",
            "recall_methods_used": ["keyword", "bm25", "fts5", "rrf"],
            "freshness_boundary": "substring_fts5_partial_not_default_vector",
            "default_vector_freshness_covered": False,
        }

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", lambda: fake_handle_recall)

    response = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "query": "远程桌面 3389",
                "recall_mode": "substring",
                "fts5_recall": True,
                "memory_scope": "raw_pool",
                "allow_cross_window_recall": True,
            },
        },
    })

    content = response["result"]["structuredContent"]
    assert calls and calls[0]["fts5_recall"] is True
    assert content["fts5_recall_requested"] is True
    assert content["fts5_applied"] is True
    assert content["fts5_status"]["error"] is None
    assert content["recall_methods_used"] == ["keyword", "bm25", "fts5", "rrf"]
    assert content["freshness_boundary"] == "substring_fts5_partial_not_default_vector"
    assert content["default_vector_freshness_covered"] is False


def test_raw_gateway_default_recall_uses_saved_bge_preference(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    config_dir = tmp_path / "memcore" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "zhiyi_model_binding.user.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "binding_kind": "platform_default",
            "vector_recall_preference": {
                "schema_version": "vector-recall-preference.v1",
                "enabled": False,
                "default_recall_mode": "substring",
                "fts5_recall": True,
                "hot_switch_status": "effective_for_new_gateway_requests",
                "requires_restart": False,
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    calls = []

    def fake_handle_recall(body):
        calls.append(dict(body))
        return {
            "matched_memories": [],
            "recall_methods_used": ["keyword", "bm25", "fts5", "rrf"],
            "fts5_applied": True,
            "fts5_status": {"error": None, "applied": True},
        }

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", lambda: fake_handle_recall)

    result = raw_gateway.query_raw_source_refs(
        query="默认检索偏好",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert calls and calls[0]["recall_mode"] == "substring"
    assert calls[0]["fts5_recall"] is True
    assert result["default_recall_preference_applied"] is True
    assert result["default_recall_preference"]["enabled"] is False
    assert result["default_recall_preference"]["default_recall_mode"] == "substring"

    calls.clear()
    (config_dir / "zhiyi_model_binding.user.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "binding_kind": "platform_default",
            "vector_recall_preference": {
                "schema_version": "vector-recall-preference.v1",
                "enabled": True,
                "default_recall_mode": "vector",
                "fts5_recall": False,
                "hot_switch_status": "effective_for_new_gateway_requests",
                "requires_restart": False,
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    granite_assets = importlib.import_module("src.granite_vector_assets")
    monkeypatch.setattr(granite_assets, "granite_asset_status", lambda root: {"ready": True, "state": "ready"})
    monkeypatch.setattr(
        raw_gateway,
        "_query_gateway_recent_delta_items",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("saved vector preference must reach P3 before gateway recent_delta")
        ),
    )

    raw_gateway.query_raw_source_refs(
        query="默认检索偏好",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert calls and calls[0]["recall_mode"] == "vector"
    assert "fts5_recall" not in calls[0]


def test_raw_gateway_explicit_recall_mode_overrides_saved_bge_preference(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    config_dir = tmp_path / "memcore" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "zhiyi_model_binding.user.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "binding_kind": "platform_default",
            "vector_recall_preference": {
                "schema_version": "vector-recall-preference.v1",
                "enabled": True,
                "default_recall_mode": "vector",
                "fts5_recall": False,
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    calls = []

    def fake_handle_recall(body):
        calls.append(dict(body))
        return {"matched_memories": [], "recall_methods_used": ["keyword"]}

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", lambda: fake_handle_recall)

    result = raw_gateway.query_raw_source_refs(
        query="显式检索",
        recall_mode="substring",
        fts5_recall=True,
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert calls and calls[0]["recall_mode"] == "substring"
    assert calls[0]["fts5_recall"] is True
    assert "default_recall_preference_applied" not in result


def test_raw_gateway_unconfigured_bge_preference_uses_ui_default_fts5_recall(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    calls = []

    def fake_handle_recall(body):
        calls.append(dict(body))
        return {"matched_memories": [], "recall_methods_used": ["keyword", "bm25", "fts5", "rrf"]}

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", lambda: fake_handle_recall)

    result = raw_gateway.query_raw_source_refs(
        query="未配置检索偏好",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert calls
    assert calls[0]["recall_mode"] == "substring"
    assert calls[0]["fts5_recall"] is True
    assert result["default_recall_preference_applied"] is True
    assert result["default_recall_preference"]["configured"] is False
    assert result["default_recall_preference"]["enabled"] is False


def test_mcp_default_recall_surfaces_recent_delta_freshness_telemetry(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    raw_path = tmp_path / "source.jsonl"
    source_text = "默认召回 recent_delta freshness 证据。"
    raw_path.write_text(source_text, encoding="utf-8")
    calls = []

    def fake_handle_recall(body):
        calls.append(dict(body))
        assert body["recall_mode"] == "substring"
        assert body["fts5_recall"] is True
        return {
            "matched_memories": [
                {
                    "exp_id": "exp-recent-delta",
                    "type": "case_memory",
                    "summary": "默认召回立刻命中新写记忆",
                    "detail": "bounded recent_delta 负责近写可见。",
                    "source_refs": json.dumps(
                        {
                            "source_system": "codex",
                            "computer_name": "local",
                            "canonical_window_id": "window-a",
                            "session_id": "session-a",
                            "source_path": str(raw_path),
                            "byte_offsets": {"start": 0, "end": len(source_text.encode("utf-8"))},
                        },
                        ensure_ascii=False,
                    ),
                    "matched_by": "recent_delta",
                    "rank_reason": "bounded_recent_delta_default_recall",
                }
            ],
            "memory_cache_status": "refresh_pending",
            "refresh_status": "pending",
            "refresh_pending": True,
            "freshness_boundary": "bounded_recent_delta",
            "recent_delta_applied": True,
            "recent_delta_status": {"applied": True, "reason": "bounded_append_delta_default_recall_hit"},
            "recent_delta_doc_count": 1,
            "recent_delta_bounded": True,
            "recent_delta_full_refresh_waited": False,
            "freshness_fast_path": "bounded_recent_delta",
            "default_recall_freshness_covered": True,
            "default_vector_freshness_covered": False,
            "recall_methods_used": ["vector", "recent_delta", "keyword"],
        }

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", lambda: fake_handle_recall)

    response = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 12,
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "query": "默认召回立刻命中新写记忆",
                "memory_scope": "raw_pool",
                "allow_cross_window_recall": True,
            },
        },
    })

    content = response["result"]["structuredContent"]
    assert calls
    assert content["default_recall_preference_applied"] is True
    assert content["default_recall_preference"]["default_recall_mode"] == "substring"
    assert content["default_recall_preference"]["fts5_recall"] is True
    assert content["freshness_boundary"] == "bounded_recent_delta"
    assert content["recent_delta_applied"] is True
    assert content["recent_delta_status"]["reason"] == "bounded_append_delta_default_recall_hit"
    assert content["freshness_fast_path"] == "bounded_recent_delta"
    assert content["default_recall_freshness_covered"] is True
    assert content["default_vector_freshness_covered"] is False
    assert content["recall_methods_used"] == ["vector", "recent_delta", "keyword"]


def test_raw_gateway_default_recall_hits_gateway_recent_delta_without_p3(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    root = tmp_path / "memcore"
    raw_path = root / "memory" / "local" / "codex" / "codex_session_jsonl" / "no-cwd" / "probe-session.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    token = "full-chain-probe-gateway-delta"
    msg_id = "probe-msg-gateway-delta"
    raw_line = json.dumps(
        {
            "timestamp": "2026-07-04T00:00:00Z",
            "id": msg_id,
            "type": "response_item",
            "source_system": "codex",
            "payload": {
                "type": "message",
                "role": "user",
                "content": f"我希望默认召回立刻看到 {token}。",
            },
        },
        ensure_ascii=False,
    ) + "\n"
    raw_path.write_text(raw_line, encoding="utf-8")
    raw_bytes = raw_line.encode("utf-8")
    source_refs = {
        "source_system": "codex",
        "computer_name": "local",
        "canonical_window_id": "no-cwd",
        "session_id": "probe-session",
        "source_path": str(raw_path),
        "msg_ids": [msg_id],
        "byte_offsets": {msg_id: {"start": 0, "end": len(raw_bytes)}},
    }
    record = {
        "exp_id": "exp-pref-gateway-delta",
        "type": "preference_memory",
        "canonical_window_id": "no-cwd",
        "session_id": "probe-session",
        "computer_id": "local",
        "source_system": "codex",
        "scope": "window/no-cwd",
        "summary": f"我希望默认召回立刻看到 {token}。",
        "detail": f"用户表达了默认召回 freshness 偏好 {token}。",
        "source_refs": json.dumps(source_refs, ensure_ascii=False),
        "score": 0.7,
    }
    zhiyi_path = root / "zhiyi" / "preference_memory" / "preference_memory.jsonl"
    zhiyi_path.parent.mkdir(parents=True, exist_ok=True)
    zhiyi_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    case_path = root / "zhiyi" / "case_memory" / "case_memory.jsonl"
    case_path.parent.mkdir(parents=True, exist_ok=True)
    with case_path.open("w", encoding="utf-8") as f:
        for idx in range(80):
            f.write(json.dumps({
                "exp_id": f"exp-case-noise-{idx}",
                "type": "case_memory",
                "source_system": "codex",
                "summary": f"case tail noise {idx}",
                "detail": "这些尾部 case 不应把 preference recent_delta 挤掉。",
                "source_refs": json.dumps({
                    "source_system": "codex",
                    "computer_name": "local",
                    "canonical_window_id": "noise-window",
                    "session_id": f"noise-session-{idx}",
                    "source_path": str(raw_path),
                    "msg_ids": [msg_id],
                }, ensure_ascii=False),
            }, ensure_ascii=False) + "\n")

    def fail_handle_recall():
        raise AssertionError("gateway recent_delta hit must return before p3 recall")

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", fail_handle_recall)

    result = raw_gateway.query_raw_source_refs(
        token,
        source_system="codex",
        limit=5,
        excerpt_chars=300,
        consumer="full-chain-probe",
        memory_scope="active",
    )

    assert result["matched_count"] == 1
    assert token in json.dumps(result["items"], ensure_ascii=False)
    assert result["freshness_boundary"] == "bounded_recent_delta"
    assert result["freshness_fast_path"] == "bounded_recent_delta"
    assert result["recent_delta_applied"] is True
    assert result["recent_delta_status"]["reason"] == "bounded_gateway_recent_delta_default_recall_hit"
    assert result["default_recall_freshness_covered"] is True
    assert result["default_vector_freshness_covered"] is False
    assert result["vector_search_deferred_for_recent_delta"] is True
    assert result["items"][0]["active_memory_layer"] == "stable_user_preferences_tool_facts"
    assert result["items"][0]["raw_evidence_status"] == "raw_offset"


def test_raw_gateway_core_platform_identity_is_declaration_driven(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    source = Path(raw_gateway.__file__).read_text(encoding="utf-8")

    assert "source_system_runtime_declarations" in source
    assert "SESSION_WINDOW_ID_SOURCE_SYSTEMS" not in source
    assert "CLAUDE_WINDOW_RECALL_ALIASES" not in source
    assert '"codex"' not in source
    assert '"claude_desktop"' not in source
    assert '"claude_code_cli"' not in source


def test_raw_gateway_recent_delta_normalizes_session_window_without_platform_declaration(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)

    root = tmp_path / "memcore"
    raw_path = (
        root
        / "memory"
        / "local"
        / "dummy_session_platform"
        / "dummy_session_jsonl"
        / "legacy-window"
        / "probe-session.jsonl"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    token = "dummy-platform-freshness-marker"
    msg_id = "probe-msg-dummy-platform"
    raw_line = json.dumps(
        {
            "timestamp": "2026-07-04T00:00:00Z",
            "id": msg_id,
            "type": "response_item",
            "source_system": "dummy_session_platform",
            "payload": {
                "type": "message",
                "role": "user",
                "content": f"我希望新平台默认召回立刻看到 {token}。",
            },
        },
        ensure_ascii=False,
    ) + "\n"
    raw_path.write_text(raw_line, encoding="utf-8")
    raw_bytes = raw_line.encode("utf-8")
    source_refs = {
        "source_system": "dummy_session_platform",
        "computer_name": "local",
        "canonical_window_id": "legacy-window",
        "session_id": "probe-session",
        "source_path": str(raw_path),
        "msg_ids": [msg_id],
        "byte_offsets": {msg_id: {"start": 0, "end": len(raw_bytes)}},
    }
    record = {
        "exp_id": "exp-pref-dummy-platform",
        "type": "preference_memory",
        "canonical_window_id": "legacy-window",
        "session_id": "probe-session",
        "computer_id": "local",
        "source_system": "dummy_session_platform",
        "scope": "window/legacy-window",
        "summary": f"我希望新平台默认召回立刻看到 {token}。",
        "detail": f"用户表达了新平台默认召回 freshness 偏好 {token}。",
        "source_refs": json.dumps(source_refs, ensure_ascii=False),
        "score": 0.7,
    }
    zhiyi_path = root / "zhiyi" / "preference_memory" / "preference_memory.jsonl"
    zhiyi_path.parent.mkdir(parents=True, exist_ok=True)
    zhiyi_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", lambda: (_ for _ in ()).throw(AssertionError("recent delta hit must not fall through to p3 recall")))

    result = raw_gateway.query_raw_source_refs(
        token,
        source_system="dummy_session_platform",
        limit=5,
        excerpt_chars=300,
        consumer="dummy-consumer",
        memory_scope="active",
    )

    assert result["matched_count"] == 1
    assert result["freshness_boundary"] == "bounded_recent_delta"
    assert result["recent_delta_applied"] is True
    item = result["items"][0]
    assert item["source_system"] == "dummy_session_platform"
    assert item["canonical_window_id"] == "probe-session"
    assert item["session_id"] == "probe-session"
    assert item["project_id"] == "legacy-window"
    assert item["source_refs_canonical_window_id"] == "legacy-window"
    assert item["raw_evidence_status"] == "raw_offset"


def test_runtime_source_system_declarations_unknown_platform_uses_safe_default():
    declarations = importlib.import_module("src.source_system_runtime_declarations")

    filters, extra = declarations.recall_source_system_filters(
        effective_source_system="future_platform",
        session_id="future-session",
        canonical_window_id="future-window",
    )
    identity = declarations.normalize_source_system_window_identity(
        source_system="future_platform",
        session_id="future-session",
        canonical_window_id="future-window",
        project_id="",
    )

    assert filters == ["future_platform"]
    assert extra == {}
    assert identity["session_id"] == "future-session"
    assert identity["canonical_window_id"] == "future-session"
    assert identity["project_id"] == "future-window"
    assert identity["source_refs_canonical_window_id"] == "future-window"
    assert declarations.source_system_distillable("future_platform") is False
    assert declarations.source_system_raw_backfill_kind("future_platform") == "none"
    assert declarations.source_system_filter_matches("future_platform", ["future_platform"]) is True
    assert declarations.source_system_filter_matches("future_platform", ["mimo"]) is False
    assert declarations.source_system_filter_matches("future_platform", ["all"]) is True
    assert declarations.source_system_filter_matches("future_platform", ["*"]) is True


def test_raw_gateway_all_source_filter_keeps_p3_matches(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    raw_path = tmp_path / "source.jsonl"
    source_text = "Granite 向量召回保留真实来源。"
    raw_path.write_text(source_text, encoding="utf-8")
    calls = []

    def fake_handle_recall(body):
        calls.append(dict(body))
        return {
            "matched_memories": [
                {
                    "exp_id": "exp-granite-all-sources",
                    "type": "preference_memory",
                    "summary": source_text,
                    "detail": source_text,
                    "source_refs": json.dumps(
                        {
                            "source_system": "codex",
                            "computer_name": "local",
                            "canonical_window_id": "window-a",
                            "session_id": "session-a",
                            "source_path": str(raw_path),
                            "byte_offsets": {
                                "start": 0,
                                "end": len(source_text.encode("utf-8")),
                            },
                        },
                        ensure_ascii=False,
                    ),
                    "matched_by": "vector",
                    "rank_reason": "lancedb_cosine",
                }
            ],
            "recall_methods_used": ["vector"],
            "primary_recall_backend": "lancedb",
            "primary_recall_modes": ["vector"],
        }

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", lambda: fake_handle_recall)

    result = raw_gateway.query_raw_source_refs(
        source_text,
        source_system="all",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
        recall_mode="vector",
    )

    assert calls and calls[0]["source_system_filter"] == "all"
    assert result["matched_count"] == 1
    assert result["items"][0]["source_system"] == "codex"
    assert result["items"][0]["exp_id"] == "exp-granite-all-sources"
    assert result["recall_methods_used"] == ["vector"]


def test_raw_gateway_surfaces_p3_transport_and_vector_fallback_telemetry(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    monkeypatch.setattr(raw_gateway, "_load_handle_recall", lambda: lambda body: {
        "matched_memories": [],
        "recall_methods_used": ["keyword", "bm25", "fts5", "rrf"],
        "recall_transport": "inline_fallback_p3_service_unavailable",
        "vector_degraded": True,
        "vector_fallback_applied": True,
        "vector_fallback_backend": "FTS5+BM25",
    })

    result = raw_gateway.query_raw_source_refs(
        "Granite fallback telemetry",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
        recall_mode="vector",
    )

    assert result["recall_transport"] == "inline_fallback_p3_service_unavailable"
    assert result["vector_degraded"] is True
    assert result["vector_fallback_applied"] is True
    assert result["vector_fallback_backend"] == "FTS5+BM25"


def test_raw_gateway_default_recall_transport_uses_p3_http_service(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    monkeypatch.setattr(raw_gateway, "P3_RECALL_TRANSPORT", "http")
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout=0):
        seen.append((request.full_url, json.loads(request.data), timeout))
        response = Response()
        response.read = lambda: b'{"matched_memories": [], "recall_methods_used": ["vector"]}'
        return response

    monkeypatch.setattr(raw_gateway.urllib.request, "urlopen", fake_urlopen)
    result = raw_gateway._load_handle_recall()({"query": "Granite transport", "recall_mode": "vector"})

    assert seen == [("http://127.0.0.1:19300/recall", {"query": "Granite transport", "recall_mode": "vector"}, 90)]
    assert result["recall_transport"] == "p3_http_service"
    assert result["recall_methods_used"] == ["vector"]


def test_raw_gateway_p3_http_unavailable_falls_back_inline(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    monkeypatch.setattr(raw_gateway, "P3_RECALL_TRANSPORT", "http")
    monkeypatch.setattr(
        raw_gateway.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    monkeypatch.setattr(
        raw_gateway,
        "_inline_handle_recall",
        lambda: lambda body: {"matched_memories": [], "body_seen": body},
    )

    result = raw_gateway._load_handle_recall()({"query": "fallback", "recall_mode": "vector"})

    assert result["body_seen"]["query"] == "fallback"
    assert result["body_seen"]["recall_mode"] == "substring"
    assert result["body_seen"]["fts5_recall"] is True
    assert result["recall_transport"] == "inline_fallback_p3_service_unavailable"
    assert result["vector_fallback_applied"] is True
    assert result["vector_fallback_backend"] == "FTS5+BM25"


def test_runtime_source_system_declarations_drive_batch_bc_source_system_shapes():
    declarations = importlib.import_module("src.source_system_runtime_declarations")

    assert declarations.source_system_filter_matches("mimocode", ["mimo"])
    assert declarations.source_system_filter_matches("mimo_code", ["mimocode"])
    assert set(declarations.source_system_filter_query_tokens(["mimocode"])) == {"mimocode", "mimo", "mimo_code"}
    assert declarations.source_system_from_consumer_name("claude code") == "claude_code_cli"
    assert declarations.source_system_from_consumer_name("mimo") == "mimocode"
    assert declarations.source_system_from_consumer_name("unknown client") == ""
    assert not hasattr(declarations.SourceSystemRuntimeDeclaration, "default_recall_scope_source")
    assert not hasattr(declarations.SourceSystemRuntimeDeclaration, "default_work_preflight_source")
    assert not hasattr(declarations, "default_recall_scope_source_system")
    assert not hasattr(declarations, "default_work_preflight_source_system")
    assert declarations.source_system_supports_distill_target_shape("mimo", "mimocode_deep_distill")
    assert (
        declarations.source_system_required_coverage_source_for_distill_target_shape("mimo", "mimocode_deep_distill")
        == "reading_area_declared_mimocode_checkpoint"
    )
    assert declarations.source_system_uses_distill_checkpoint_adapter(
        "future_platform",
        index_status="mimocode_checkpoint_source_path_fallback",
        kind="checkpoint_markdown_sections",
    )
    assert declarations.source_system_uses_reading_area_raw_index(
        "mimo",
        kind="declared_checkpoint_markdown",
    )
    assert not declarations.source_system_uses_reading_area_raw_index(
        "unknown",
        kind="declared_checkpoint_markdown",
    )
    assert declarations.source_system_raw_backfill_kind("hermes") == "state_db_messages"
    assert declarations.source_system_raw_backfill_kind("openclaw") == "source_artifact_copy"


def test_runtime_source_system_declarations_drive_generic_source_ref_shapes():
    source_refs = importlib.import_module("src.source_refs")
    refs = source_refs.make_source_refs(
        "dummy_session_platform",
        source_path="/tmp/dummy.jsonl",
        session_id="dummy-session",
        canonical_window_id="dummy-window",
        artifact_type="dummy_session_jsonl",
        msg_ids=["msg-1"],
    )

    assert refs["source_system"] == "dummy_session_platform"
    assert refs["source_path"] == "/tmp/dummy.jsonl"
    assert refs["session_id"] == "dummy-session"
    assert refs["canonical_window_id"] == "dummy-window"
    assert refs["artifact_type"] == "dummy_session_jsonl"
    assert refs["msg_ids"] == ["msg-1"]


def test_active_memory_routing_uses_runtime_declaration_consumer_tokens_without_identity_permissions():
    routing = importlib.import_module("src.active_memory_routing")

    assert routing.source_system_from_consumer("Claude Code CLI") == "claude_code_cli"
    assert routing.source_system_from_consumer("mimo") == "mimocode"
    assert routing.source_system_from_consumer("unknown future client") == ""

    without_flag = [
        routing.resolve_recall_scope(
            source_system="",
            consumer=consumer,
            memory_scope="raw_pool",
            canonical_window_id="",
            session_id="",
            cross_window_reason="skill_generation",
        )
        for consumer in ("Hermes", "future client")
    ]
    with_flag = [
        routing.resolve_recall_scope(
            source_system="",
            consumer=consumer,
            memory_scope="raw_pool",
            canonical_window_id="",
            session_id="",
            allow_cross_window_recall=True,
            cross_window_reason="skill_generation",
        )
        for consumer in ("Hermes", "future client")
    ]

    assert {item["cross_window_read_allowed"] for item in without_flag} == {False}
    assert {tuple(item["missing_scope_fields"]) for item in without_flag} == {("allow_cross_window_recall",)}
    assert {item["cross_window_read_allowed"] for item in with_flag} == {True}
    assert {item["cross_window_permission_explicit"] for item in with_flag} == {True}
    assert {item["cross_window_reason_is_authorization"] for item in without_flag + with_flag} == {False}


def test_active_memory_routing_treats_consumer_name_as_hint_not_source_filter():
    routing = importlib.import_module("src.active_memory_routing")

    known = routing.resolve_recall_scope(
        source_system="",
        consumer="Codex",
        memory_scope="active",
        canonical_window_id="",
        session_id="",
    )
    unknown = routing.resolve_recall_scope(
        source_system="",
        consumer="Future Client",
        memory_scope="active",
        canonical_window_id="",
        session_id="",
    )

    assert known["inferred_source_system"] == "codex"
    assert unknown["inferred_source_system"] == ""
    assert known["effective_source_system"] == unknown["effective_source_system"] == ""
    assert known["memory_base_scope"] == unknown["memory_base_scope"] == "active_layered"
    assert known["consumer_name_inference_used_for_routing"] is False
    assert unknown["consumer_name_inference_used_for_routing"] is False

    for consumer in ("Codex", "Future Client"):
        explicit = routing.resolve_recall_scope(
            source_system="shared_origin",
            consumer=consumer,
            memory_scope="active",
            canonical_window_id="",
            session_id="",
        )
        assert explicit["effective_source_system"] == "shared_origin"
        assert explicit["source_filter_authority"] == "explicit_request_or_verified_window_binding"


def test_mcp_runtime_client_platform_inference_uses_runtime_declaration_tokens():
    runtime = importlib.import_module("src.raw_gateway_mcp_runtime")

    assert runtime._platform_from_client_name("Claude Code") == "claude_code_cli"
    assert runtime._platform_from_client_name("MiMo") == "mimocode"
    assert runtime._platform_from_client_name("Future Client") == "future_client"


def test_raw_gateway_health_reports_install_source_identity(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    payload = raw_gateway.health_payload()
    source_path = Path(payload["source_path"])

    assert payload["ok"] is True
    assert payload["service"] == "raw_consumption_gateway"
    assert payload["version"] == "2099.1.2"
    assert payload["preflight"] is True
    assert payload["identity_contract"] == "raw_gateway_health_identity.v1"
    assert source_path == Path(raw_gateway.__file__).resolve()
    assert payload["source_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()


def test_hermes_skill_artifact_status_is_recallable_by_probe_id(tmp_path):
    _write_hermes_skill_artifact_status(tmp_path)
    p3, raw_gateway = _reload_modules(tmp_path)

    result = p3.handle_recall({
        "query": "hermes-skill-generation-probe-2fec7027343c3a92 zhiyi-recall-check",
        "top_k": 3,
        "recall_mode": "substring",
    })

    assert result["matched_memories"]
    first = result["matched_memories"][0]
    assert first["type"] == "time_library_project_status"
    assert first["_project_status"]["artifact_type"] == "hermes_skill_artifact_status"
    assert first["_project_status"]["probe_id"] == "hermes-skill-generation-probe-2fec7027343c3a92"
    assert first["_project_status"]["skill_artifact_status"] == "probe_only_not_adopted"
    assert "not adopted" in first["detail"] or "not adopted" in first["summary"]

    raw_result = raw_gateway.query_raw_source_refs(
        "Hermes skill generation probe 结论是什么 zhiyi-recall-check",
        source_system="",
        computer_name="",
        session_id="",
        limit=3,
        excerpt_chars=600,
        consumer="codex",
        request_id="test-hermes-status",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert raw_result["items"]
    item = raw_result["items"][0]
    assert item["memory_type"] == "time_library_project_status"
    assert item["raw_evidence_status"] == "artifact"
    assert item["project_status"]["artifact_type"] == "hermes_skill_artifact_status"
    assert item["project_status"]["probe_id"] == "hermes-skill-generation-probe-2fec7027343c3a92"
    assert item["project_status"]["skill_artifact_status"] == "probe_only_not_adopted"
    assert item["project_status"]["hermes_skill_write_performed_by_time_library"] is False


def test_decision_focus_recall_prioritizes_boundary_memory_over_meta_lookup(tmp_path):
    p3, _ = _reload_modules(tmp_path)
    zhiyi_root = tmp_path / "memcore" / "zhiyi"
    case_path = zhiyi_root / "case_memory" / "case_memory.jsonl"
    error_path = zhiyi_root / "error_memory" / "error_memory.jsonl"
    case_path.parent.mkdir(parents=True, exist_ok=True)
    error_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = tmp_path / "memcore" / "memory" / "local" / "codex" / "codex_session_jsonl" / "project-a" / "decision.jsonl"
    source_ref = {"source_system": "codex", "source_path": str(raw_path)}

    meta_record = {
        "exp_id": "exp-meta-lookup",
        "type": "case_memory",
        "scope": "window/project-a",
        "summary": "案例：我正在查time-rule中性 / minimax-cn 网页认证不通 / 模型中心是time-rule 是否成为可召回经验。",
        "detail": "这只是二手排查记录，不是原始结论本身。",
        "source_refs": json.dumps(source_ref, ensure_ascii=False),
        "score": 0.9,
    }
    live_validation_record = {
        "exp_id": "exp-live-validation",
        "type": "error_memory",
        "scope": "window/project-a",
        "summary": "错误相关：现在 live 排序已经改善：第一条变成“Time Library读回来自己用，不写回平台，不是模型中心复刻”，这正是之前丢的定论。",
        "detail": "接下来跑全组测试，然后同步本机服务验证 9851。这是验证流水，不是原始定论本身。",
        "source_refs": json.dumps(source_ref, ensure_ascii=False),
        "score": 0.95,
    }
    boundary_record = {
        "exp_id": "exp-boundary-decision",
        "type": "error_memory",
        "scope": "window/project-a",
        "summary": "错误相关：对，这句话把性质拍死了：Time Library只读模型事实，不做模型中心。",
        "detail": "定论：time-rule中性；minimax-cn 网页认证不通；模型中心是time-rule。Time Library读取 OpenClaw/Hermes/Codex 的模型事实供自己用，不写回平台。",
        "source_refs": json.dumps(source_ref, ensure_ascii=False),
        "score": 0.7,
    }
    case_path.write_text(json.dumps(meta_record, ensure_ascii=False) + "\n", encoding="utf-8")
    error_path.write_text(
        json.dumps(live_validation_record, ensure_ascii=False) + "\n"
        + json.dumps(boundary_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = p3.handle_recall({
        "query": "time-rule中性 minimax-cn 网页认证不通 模型中心是time-rule 定论",
        "top_k": 2,
        "recall_mode": "substring",
    })

    assert result["matched_memories"]
    assert result["matched_memories"][0]["exp_id"] == "exp-boundary-decision"
    assert "模型事实" in result["matched_memories"][0]["detail"]


def test_raw_gateway_capability_check_does_not_recall_or_return_excerpts(tmp_path):
    marker = "能力检查不能泄露这段真实记忆 token=USER_OWN_TEXT_CAPABILITY。"
    _write_memory(
        tmp_path,
        "openclaw",
        "openclaw-session",
        "2026-05-28T10:00:00Z",
        "MCP 知意召回经验",
        marker,
    )
    _, raw_gateway = _reload_modules(tmp_path)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "MCP 知意召回经验",
                "mode": "capability_check",
                "consumer": "openclaw-smoke",
                "request_id": "cap-smoke",
            },
        },
    })
    content = called["result"]["structuredContent"]
    encoded = json.dumps(content, ensure_ascii=False)

    assert content["ok"] is True
    assert content["mode"] == "capability_check"
    assert content["recall_performed"] is False
    assert content["raw_excerpt_returned"] is False
    assert content["read_only"] is True
    assert content["write_performed"] is False
    assert content["platform_write_performed"] is False
    assert content["mcp_tools"] == [
        "time_library_recall",
        "time_library_delivery_ack",
        "time_library_reading_area",
        "zhiyi_recall",
    ]
    assert content["source_memory_read_only"] is True
    assert content["derived_delivery_audit_write_performed"] is False
    assert content["matched_count"] == 0
    assert content["source_refs_count"] == 0
    assert content["raw_items_count"] == 0
    assert content["items"] == []
    assert content["consumer_receipt"]["receipt_scope"] == "capability_check_no_recall"
    assert content["consumer_receipt"]["write_performed"] is False
    assert content["consumer_receipt"]["used_source_refs"] == []
    assert marker not in encoded
    assert '"raw_excerpt":' not in encoded


def test_raw_gateway_mcp_tool_exception_returns_jsonrpc_error(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)

    def explode(*_args, **_kwargs):
        raise RuntimeError("simulated recall failure")

    monkeypatch.setattr(raw_gateway, "query_raw_source_refs", explode)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 44,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "trigger failure"},
        },
    })

    assert called == {
        "jsonrpc": "2.0",
        "id": 44,
        "error": {
            "code": -32603,
            "message": "Internal error while calling tool: RuntimeError: simulated recall failure",
        },
    }
    assert "ok" not in called


def test_raw_gateway_mcp_errors_use_valid_response_id(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    missing_id = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "method": "unknown/method",
        "params": {},
    })
    bool_id = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": True,
        "method": "unknown/method",
        "params": {},
    })

    assert missing_id == {
        "jsonrpc": "2.0",
        "id": "unknown",
        "error": {"code": -32601, "message": "Method not found: unknown/method"},
    }
    assert bool_id["id"] == "unknown"
    assert "ok" not in missing_id


def test_raw_gateway_accepts_loopback_clients_only(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    assert raw_gateway._is_loopback_client(("127.0.0.1", 12345)) is True
    assert raw_gateway._is_loopback_client(("::1", 12345, 0, 0)) is True
    assert raw_gateway._is_loopback_client(("::ffff:127.0.0.1", 12345, 0, 0)) is True
    assert raw_gateway._is_loopback_client(("localhost", 12345)) is True
    assert raw_gateway._is_loopback_client(("192.0.2.10", 12345)) is False
    assert raw_gateway._is_loopback_client(("10.0.0.8", 12345)) is False


def test_raw_gateway_state_dir_override_is_guarded(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    allowed_state = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(allowed_state)
    try:
        assert raw_gateway._raw_segment_state_dir() == allowed_state.resolve()
    finally:
        _clear_raw_gateway_env()

    project_state = ROOT / "output" / "raw_gateway_state_test"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(project_state)
    try:
        assert raw_gateway._raw_segment_state_dir() == project_state.resolve()
    finally:
        _clear_raw_gateway_env()

    for dirname in [".openclaw", ".codex", ".hermes", ".ssh"]:
        os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(tmp_path / dirname / "raw_gateway_state")
        try:
            try:
                raw_gateway._raw_segment_state_dir()
            except ValueError as exc:
                assert "unsafe MEMCORE_RAW_GATEWAY_STATE_DIR" in str(exc)
            else:
                raise AssertionError(f"{dirname} override should be rejected")
        finally:
            _clear_raw_gateway_env()


def test_hermes_provider_defaults_to_window_scope_without_cross_window_mix():
    agent_mod = types.ModuleType("agent")
    memory_provider_mod = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        pass

    memory_provider_mod.MemoryProvider = MemoryProvider
    sys.modules["agent"] = agent_mod
    sys.modules["agent.memory_provider"] = memory_provider_mod

    plugin_path = ROOT / "system" / "hermes" / "plugins" / "time_library" / "__init__.py"
    spec = importlib.util.spec_from_file_location("test_time_library_plugin", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    provider = module.TimeLibraryMemoryProvider({})
    provider.initialize("hermes-session")
    assert provider._memory_scope() == "window"

    window_payload = provider._build_payload("帮我接一下前文", session_id="hermes-session")
    assert window_payload["consumer"] == "hermes"
    assert window_payload["memory_scope"] == "window"
    assert window_payload["source_system"] == ""
    assert window_payload["session_id"] == "hermes-session"
    assert "cross_window_reason" not in window_payload

    platform_payload = provider._build_payload(
        "帮我接一下前文",
        session_id="hermes-session",
        memory_scope="platform",
    )
    assert platform_payload["source_system"] == "hermes"

    accidental_raw_pool_provider = module.TimeLibraryMemoryProvider({
        "memory_scope": "raw_pool",
    })
    accidental_raw_pool_provider.initialize("hermes-session")
    assert accidental_raw_pool_provider._memory_scope() == "window"
    accidental_payload = accidental_raw_pool_provider._build_payload("帮我接一下前文", session_id="hermes-session")
    assert accidental_payload["memory_scope"] == "window"
    assert accidental_payload["session_id"] == "hermes-session"
    assert "cross_window_reason" not in accidental_payload

    accidental_dual_provider = module.TimeLibraryMemoryProvider({
        "memory_scope": "dual",
        "cross_window_reason": "ordinary_recall",
    })
    accidental_dual_provider.initialize("hermes-session")
    assert accidental_dual_provider._memory_scope() == "window"

    raw_pool_provider = module.TimeLibraryMemoryProvider({
        "memory_scope": "raw_pool",
        "cross_window_reason": "skill_generation",
    })
    raw_pool_provider.initialize("hermes-session")
    shared_payload = raw_pool_provider._build_payload("帮我接一下前文", session_id="hermes-session")
    assert shared_payload["consumer"] == "hermes"
    assert shared_payload["memory_scope"] == "raw_pool"
    assert shared_payload["source_system"] == ""
    assert shared_payload["computer_name"] == ""
    assert shared_payload["session_id"] == ""
    assert shared_payload["allow_cross_window_recall"] is True
    assert shared_payload["cross_window_reason"] == "skill_generation"

    context = provider._format_context({
        "items": [{
            "source_system": "hermes",
            "session_id": "hermes-session",
            "source_path": "/tmp/hermes.jsonl",
            "raw_excerpt": "Hermes 当前窗口自己的记录。",
        }]
    }, window_payload)
    assert "memory_base_scope: window for normal Hermes recall" in context
    assert "ordinary Hermes recall stays isolated per window" in context
    assert "raw_pool requires an explicit skill-generation or self-review workflow" in context
    assert "injection_boundary: use source_refs as attributed background only" in context


def test_hermes_provider_accepts_multilingual_zhiyi_entry_commands():
    import importlib.util

    plugin_path = ROOT / "system" / "hermes" / "plugins" / "time_library" / "__init__.py"
    spec = importlib.util.spec_from_file_location("test_time_library_plugin_i18n", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    provider = module.TimeLibraryMemoryProvider({})
    provider.initialize("hermes-session")

    zhiyi_payload = provider._build_payload("/zhiyi 这个项目现在做到哪里了", session_id="hermes-session")
    assert zhiyi_payload["query"] == "这个项目现在做到哪里了"
    assert zhiyi_payload["original_query"] == "/zhiyi 这个项目现在做到哪里了"
    assert zhiyi_payload["zhiyi_entry"]["requested"] is True
    assert zhiyi_payload["zhiyi_entry"]["command"] == "/zhiyi"

    english_payload = provider._build_payload("catch me up on this project", session_id="hermes-session")
    assert english_payload["query"] == "catch me up on this project"
    assert english_payload["zhiyi_entry"]["requested"] is True


def test_hermes_provider_sync_turn_posts_consumption_receipt(monkeypatch):
    import importlib.util

    agent_mod = types.ModuleType("agent")
    memory_provider_mod = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        pass

    memory_provider_mod.MemoryProvider = MemoryProvider
    sys.modules["agent"] = agent_mod
    sys.modules["agent.memory_provider"] = memory_provider_mod

    plugin_path = ROOT / "system" / "hermes" / "plugins" / "time_library" / "__init__.py"
    spec = importlib.util.spec_from_file_location("test_time_library_plugin_sync", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    captured = {}
    posted = threading.Event()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode("utf-8")

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        posted.set()
        return Response()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    provider = module.TimeLibraryMemoryProvider({
        "receipt_url": "http://127.0.0.1:9850/api/v1/hermes/consumption-receipts",
        "enable_receipts": True,
    })
    provider.initialize("hermes-session")
    provider._last_prefetch = {
        "ok": True,
        "request_id": "hermes-memcore-prefetch-test",
        "matched_count": 2,
        "source_refs_count": 2,
    }

    provider.sync_turn("用户问题", "Hermes 回答", session_id="hermes-session", messages=[{"role": "user", "content": "用户问题"}])

    assert posted.wait(1.0)
    assert captured["url"] == "http://127.0.0.1:9850/api/v1/hermes/consumption-receipts"
    body = captured["body"]
    assert body["event_type"] == "hermes_turn_consumption_receipt"
    assert body["session_id"] == "hermes-session"
    assert body["user_content"] == "用户问题"
    assert body["assistant_content"] == "Hermes 回答"
    assert body["last_prefetch"]["matched_count"] == 2
    assert body["write_boundary"]["hermes_skill_write_performed"] is False
    assert body["write_boundary"]["raw_write_performed"] is False


def test_hermes_provider_reads_profile_config_before_root_config(tmp_path):
    agent_mod = types.ModuleType("agent")
    memory_provider_mod = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        pass

    memory_provider_mod.MemoryProvider = MemoryProvider
    sys.modules["agent"] = agent_mod
    sys.modules["agent.memory_provider"] = memory_provider_mod

    hermes_home = tmp_path / "hermes"
    profile_config = hermes_home / "profiles" / "default" / "config.yaml"
    root_config = hermes_home / "config.yaml"
    profile_config.parent.mkdir(parents=True)
    profile_config.write_text(
        "plugins:\n"
        "  time_library:\n"
        "    memory_scope: platform\n"
        "    cross_window_reason: self_review\n"
        "    limit: 2\n",
        encoding="utf-8",
    )
    root_config.write_text(
        "plugins:\n"
        "  time_library:\n"
        "    memory_scope: raw_pool\n"
        "    limit: 7\n",
        encoding="utf-8",
    )

    plugin_path = ROOT / "system" / "hermes" / "plugins" / "time_library" / "__init__.py"
    spec = importlib.util.spec_from_file_location("test_time_library_plugin_profiles", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    provider = module.TimeLibraryMemoryProvider({})
    provider.initialize("hermes-session", hermes_home=str(hermes_home))

    assert provider._memory_scope() == "platform"
    profile_payload = provider._build_payload("继续", session_id="hermes-session")
    assert profile_payload["limit"] == 2
    assert profile_payload["allow_cross_window_recall"] is True


def test_raw_experience_provider_legacy_redaction_policy_is_verbatim():
    from src.raw_experience_provider import REDACTION_LEGACY_SECRET_LIKE, build_item

    marker = "平台原文 token=USER_OWN_TEXT_1234567890 password=只是聊天内容"
    item = build_item(marker, source_system="codex", redaction_policy=REDACTION_LEGACY_SECRET_LIKE)

    assert item["raw_excerpt"] == marker
    assert item["_redaction_applied"] is False
    assert item["_redaction_policy"] == "none"
    assert "REDACTED" not in item["raw_excerpt"]


def test_raw_excerpt_segment_resume_reads_next_chunk(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    os.environ["MEMCORE_RAW_SEGMENT_BYTES"] = "4096"
    os.environ["MEMCORE_RAW_SEGMENT_MAX_SEGMENTS"] = "1"
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "big.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-message-id"
        filler = "x" * 5000
        raw_path.write_text(
            json.dumps({
                "timestamp": "filler-1",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": filler},
            }, ensure_ascii=False) + "\n" +
            json.dumps({
                "timestamp": target_id,
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "续读命中的目标内容"},
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        first = raw_gateway._extract_bounded_raw_excerpt_by_cursor_segments(raw_path.resolve(), [target_id], 100)
        assert first[0] == ""
        assert first[1] == "segment_pending"
        state = raw_gateway._load_raw_segment_state()
        assert state
        first_cursor = next(iter(state.values()))["next_offset"]
        assert first_cursor > 0

        second = raw_gateway._extract_bounded_raw_excerpt_by_cursor_segments(raw_path.resolve(), [target_id], 100)
        assert "续读命中的目标内容" in second[0]
        assert second[1] == "raw_segmented"
        state = raw_gateway._load_raw_segment_state()
        saved = next(iter(state.values()))
        assert saved["hit_offset"] >= first_cursor

        third = raw_gateway._extract_bounded_raw_excerpt_by_cursor_segments(raw_path.resolve(), [target_id], 100)
        assert "续读命中的目标内容" in third[0]
        assert third[1] == "raw_segmented"
        state = raw_gateway._load_raw_segment_state()
        assert next(iter(state.values()))["next_offset"] == saved["next_offset"]
    finally:
        _clear_raw_gateway_env()


def test_raw_excerpt_uses_byte_offsets_without_segment_walk(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    os.environ["MEMCORE_RAW_SEGMENT_BYTES"] = "4096"
    os.environ["MEMCORE_RAW_SEGMENT_MAX_SEGMENTS"] = "1"
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "offset.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-message-id"
        first_line = json.dumps({
            "timestamp": "filler-1",
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": "x" * 5000},
        }, ensure_ascii=False) + "\n"
        second_line = json.dumps({
            "timestamp": target_id,
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": "偏移直达命中的目标内容"},
        }, ensure_ascii=False) + "\n"
        raw_path.write_text(first_line + second_line, encoding="utf-8")
        start = len(first_line.encode("utf-8"))
        end = start + len(second_line.encode("utf-8"))

        excerpt, status, evidence_hash = raw_gateway._extract_bounded_raw_excerpt(
            str(raw_path),
            [target_id],
            100,
            {"byte_offsets": {target_id: {"start": start, "end": end}}},
        )

        assert "偏移直达命中的目标内容" in excerpt
        assert status == "raw_offset"
        assert evidence_hash
        assert raw_gateway._load_raw_segment_state() == {}
    finally:
        _clear_raw_gateway_env()


def test_raw_excerpt_builds_offset_index_for_old_source_refs(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    os.environ["MEMCORE_RAW_SEGMENT_BYTES"] = "4096"
    os.environ["MEMCORE_RAW_SEGMENT_MAX_SEGMENTS"] = "1"
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "indexed.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-message-id"
        raw_path.write_text(
            json.dumps({
                "timestamp": "filler-1",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "x" * 5000},
            }, ensure_ascii=False) + "\n" +
            json.dumps({
                "timestamp": target_id,
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "旧经验索引命中的目标内容"},
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        excerpt, status, evidence_hash = raw_gateway._extract_bounded_raw_excerpt(str(raw_path), [target_id], 100)

        assert "旧经验索引命中的目标内容" in excerpt
        assert status == "raw_offset"
        assert evidence_hash
        assert raw_gateway._load_raw_segment_state() == {}
        index = raw_gateway._load_raw_offset_index()
        assert index
        entry = next(iter(index.values()))
        assert target_id in entry["offsets"]
    finally:
        _clear_raw_gateway_env()


def test_raw_excerpt_resolves_relocated_memory_absolute_source_path(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "relocated.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-message-id"
        raw_path.write_text(
            json.dumps({
                "timestamp": target_id,
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": "迁移后旧绝对路径仍能回源的目标内容",
                },
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        old_absolute_path = "/old-install/memcore-cloud/memory/codex/local/project-a/relocated.jsonl"

        resolved = raw_gateway._resolve_source_path(old_absolute_path)
        excerpt, status, evidence_hash = raw_gateway._extract_bounded_raw_excerpt(
            old_absolute_path,
            [target_id],
            120,
        )

        assert resolved == raw_path.resolve()
        assert "迁移后旧绝对路径仍能回源的目标内容" in excerpt
        assert status == "raw_offset"
        assert evidence_hash
    finally:
        _clear_raw_gateway_env()


def test_raw_excerpt_decodes_utf16_byte_offsets_without_mojibake(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "utf16-offset.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-message-id"
        marker = "中文定论：time-rule中性，minimax-cn 网页认证不通，模型中心是time-rule。"
        first_line = json.dumps({
            "timestamp": "filler-1",
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": "前置填充"},
        }, ensure_ascii=False) + "\n"
        second_line = json.dumps({
            "timestamp": target_id,
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": marker},
        }, ensure_ascii=False) + "\n"
        raw_path.write_bytes((first_line + second_line).encode("utf-16"))
        start = len(first_line.encode("utf-16"))
        end = len((first_line + second_line).encode("utf-16"))

        excerpt, status, evidence_hash = raw_gateway._extract_bounded_raw_excerpt(
            str(raw_path),
            [target_id],
            300,
            {"byte_offsets": {target_id: {"start": start, "end": end}}},
        )

        assert marker in excerpt
        assert "\ufffd" not in excerpt
        assert status == "raw_offset"
        assert evidence_hash
    finally:
        _clear_raw_gateway_env()


def test_raw_excerpt_builds_offset_index_for_utf16_source_refs_without_mojibake(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    os.environ["MEMCORE_RAW_SEGMENT_BYTES"] = "4096"
    os.environ["MEMCORE_RAW_SEGMENT_MAX_SEGMENTS"] = "1"
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "utf16-indexed.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-message-id"
        marker = "中文定论：time-rule中性，minimax-cn 网页认证不通，模型中心是time-rule。"
        payload = (
            json.dumps({
                "timestamp": "filler-1",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "x" * 2000},
            }, ensure_ascii=False) + "\n" +
            json.dumps({
                "timestamp": target_id,
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": marker},
            }, ensure_ascii=False) + "\n"
        )
        raw_path.write_bytes(payload.encode("utf-16"))

        excerpt, status, evidence_hash = raw_gateway._extract_bounded_raw_excerpt(str(raw_path), [target_id], 300)

        assert marker in excerpt
        assert "\ufffd" not in excerpt
        assert status == "raw_offset"
        assert evidence_hash
        assert raw_gateway._load_raw_segment_state() == {}
    finally:
        _clear_raw_gateway_env()


def test_raw_excerpt_offset_index_scan_limit_does_not_degrade_to_slow_segment_scan(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    os.environ["MEMCORE_RAW_OFFSET_INDEX_MAX_SCAN_BYTES"] = "65536"
    os.environ["MEMCORE_RAW_SEGMENT_BYTES"] = "65536"
    os.environ["MEMCORE_RAW_SEGMENT_MAX_SEGMENTS"] = "32"
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "scan-limited.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-after-scan-limit"
        raw_path.write_text(
            json.dumps({
                "timestamp": "filler-before-limit",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "x" * 70000},
            }, ensure_ascii=False) + "\n" +
            json.dumps({
                "timestamp": target_id,
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "不应慢扫命中的目标内容"},
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        excerpt, status, evidence_hash = raw_gateway._extract_bounded_raw_excerpt(str(raw_path), [target_id], 100)

        assert excerpt == ""
        assert status == "offset_index_scan_limited"
        assert evidence_hash is None
        assert raw_gateway._is_raw_evidence_status(status) is False
        assert raw_gateway._load_raw_offset_index() == {}
        assert raw_gateway._load_raw_segment_state() == {}
    finally:
        _clear_raw_gateway_env()


def test_raw_excerpt_deadline_env_is_bounded(monkeypatch):
    excerpt_mod = importlib.import_module("src.raw_evidence_excerpt")

    monkeypatch.setenv("MEMCORE_RAW_EXCERPT_DEADLINE_SECONDS", "999")
    assert excerpt_mod._raw_excerpt_deadline_seconds() == excerpt_mod.MAX_RAW_EXCERPT_DEADLINE_SECONDS

    monkeypatch.setenv("MEMCORE_RAW_EXCERPT_DEADLINE_SECONDS", "0")
    assert excerpt_mod._raw_excerpt_deadline_seconds() == 0.05

    monkeypatch.setenv("MEMCORE_RAW_EXCERPT_DEADLINE_SECONDS", "not-a-number")
    assert excerpt_mod._raw_excerpt_deadline_seconds() == excerpt_mod.DEFAULT_RAW_EXCERPT_DEADLINE_SECONDS


def test_raw_excerpt_deadline_timeout_does_not_write_reader_cache(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    excerpt_mod = importlib.import_module("src.raw_evidence_excerpt")
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "deadline.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-after-deadline"
        raw_path.write_text(
            json.dumps({
                "timestamp": "filler-before-timeout",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "x" * 1000},
            }, ensure_ascii=False) + "\n" +
            json.dumps({
                "timestamp": target_id,
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "不应在超时后继续扫描命中"},
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(excerpt_mod, "_deadline_exceeded", lambda _deadline: True)

        excerpt, status, evidence_hash = raw_gateway._extract_bounded_raw_excerpt(str(raw_path), [target_id], 100)

        assert excerpt == ""
        assert status == "excerpt_timeout"
        assert evidence_hash is None
        assert raw_gateway._is_raw_evidence_status(status) is False
        assert raw_gateway._load_raw_offset_index() == {}
        assert raw_gateway._load_raw_segment_state() == {}
    finally:
        _clear_raw_gateway_env()


def test_raw_gateway_falls_back_to_raw_jsonl_when_zhiyi_has_not_indexed_yet(tmp_path):
    marker = "yfc-codex-live-fallback token=USER_OWN_TEXT_RAW_DIRECT"
    root = tmp_path / "memcore"
    raw_path = root / "memory" / "local" / "codex" / "codex_session_jsonl" / "project-a" / "codex-live.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps({
            "timestamp": "2026-05-27T14:00:12Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "output": marker,
            },
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        marker,
        source_system="codex",
        computer_name="",
        session_id="",
        limit=5,
        excerpt_chars=300,
        consumer="codex",
        request_id="test-raw-direct",
        canonical_window_id="project-a",
    )

    assert result["items"]
    item = result["items"][0]
    assert item["memory_type"] == "raw_jsonl"
    assert item["raw_evidence_status"] == "raw_direct"
    assert item["raw_mapping_mode"] == "raw_jsonl_fallback"
    assert item["source_system"] == "codex"
    assert item["computer_name"] == "local"
    assert item["native_artifact_format"] == "codex_session_jsonl"
    assert item["raw_archive_layout"] == "computer_first"
    assert marker in item["raw_excerpt"]
    assert item["raw_excerpt"].startswith("[tool]")
    assert item["byte_offsets"]["start"] == 0
    assert item["source_path"] == str(raw_path)


def test_raw_gateway_fallback_prefers_matching_session_when_codex_window_id_is_legacy_project(tmp_path):
    marker = "RAW_FALLBACK_SESSION_FIRST_WINDOW_DRIFT_MARKER"
    root = tmp_path / "memcore"
    raw_path = root / "memory" / "local" / "codex" / "codex_session_jsonl" / "legacy-project-window" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps({
            "timestamp": "2026-06-10T01:30:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": marker}],
            },
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        marker,
        source_system="codex",
        computer_name="",
        session_id="session-a",
        limit=5,
        excerpt_chars=300,
        consumer="codex",
        request_id="test-raw-fallback-session-first-window-drift",
        memory_scope="window",
        canonical_window_id="session-a",
    )

    assert result["items"]
    item = result["items"][0]
    assert item["raw_evidence_status"] == "raw_direct"
    assert item["raw_mapping_mode"] == "raw_jsonl_fallback"
    assert item["session_id"] == "session-a"
    assert item["canonical_window_id"] == "session-a"
    assert item["project_id"] == "legacy-project-window"
    assert marker in item["raw_excerpt"]


def test_raw_gateway_fallback_matches_query_terms_across_meta_and_raw_text(tmp_path):
    root = tmp_path / "memcore"
    session_id = "claude-session-1"
    raw_path = (
        root
        / "memory"
        / "WINDOWS-FIXTURE"
        / "claude_code_cli"
        / "claude_code_session_jsonl"
        / "workspace-cb118856"
        / f"{session_id}.jsonl"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    marker = "用户要求检查 Windows 设置，助手给出优化建议。"
    raw_path.write_text(
        json.dumps({
            "timestamp": "2026-06-05T16:45:18.182Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": marker,
            },
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    Path(str(raw_path) + ".meta.json").write_text(
        json.dumps({
            "thread_name": "Windows optimization review",
            "conversation_origin": "claude_desktop_managed_claude_code_session",
            "runtime_consumer": "claude_desktop_managed_claude_code_runtime",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Windows optimization review workspace Claude Desktop",
        source_system="claude_code_cli",
        computer_name="WINDOWS-FIXTURE",
        session_id="",
        limit=5,
        excerpt_chars=300,
        consumer="claude_desktop",
        request_id="test-meta-raw-direct",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert result["raw_items_count"] >= 1
    item = next(item for item in result["items"] if item["raw_evidence_status"] == "raw_direct")
    assert item["raw_mapping_mode"] == "raw_jsonl_fallback"
    assert item["source_system"] == "claude_code_cli"
    assert item["computer_name"] == "WINDOWS-FIXTURE"
    assert item["canonical_window_id"] == "claude-session-1"
    assert item["project_id"] == "workspace-cb118856"
    assert item["source_refs_canonical_window_id"] == "workspace-cb118856"
    assert marker in item["raw_excerpt"]


def test_claude_desktop_window_recall_can_find_desktop_managed_claude_code_raw(tmp_path):
    root = tmp_path / "memcore"
    session_id = "claude-managed-session"
    raw_path = (
        root
        / "memory"
        / "WINNODEB"
        / "claude_code_cli"
        / "claude_code_session_jsonl"
        / "workspace-f2a87c03"
        / f"{session_id}.jsonl"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    marker = "WINDOWS_CLAUDE_RECALL_ALIAS_MARKER source_system 错配也要在同窗口召回。"
    raw_path.write_text(
        json.dumps({
            "timestamp": "2026-06-15T12:20:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": marker,
            },
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    Path(str(raw_path) + ".meta.json").write_text(
        json.dumps({
            "conversation_origin": "claude_desktop_managed_claude_code_session",
            "runtime_consumer": "claude_desktop_managed_claude_code_runtime",
            "storage_owner": "claude_desktop",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_declared_source_filter_binding(
        tmp_path,
        source_system="claude_desktop",
        canonical_window_id="workspace-f2a87c03",
        session_id=session_id,
        source_system_filters=["claude_desktop", "claude_code_cli"],
    )
    _, raw_gateway = _reload_modules(tmp_path)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "WINDOWS_CLAUDE_RECALL_ALIAS_MARKER",
                "consumer": "claude_desktop",
                "source_system": "claude_desktop",
                "memory_scope": "window",
                "canonical_window_id": "workspace-f2a87c03",
                "session_id": session_id,
                "limit": 5,
                "excerpt_chars": 300,
                "response_budget": "raw",
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["source_system_filter"] == "claude_desktop"
    assert content["source_system_filter_aliases"] == ["claude_desktop", "claude_code_cli"]
    assert content["source_collection_filter"] == "binding_declared_source_systems"
    assert content["source_collection_alias_applied"] is True
    assert content["source_collection_alias_boundary"] == "verified_binding_same_window_or_session_anchor_only"
    assert content["matched_count"] >= 1
    item = next(item for item in content["items"] if item["source_system"] == "claude_code_cli")
    assert item["session_id"] == session_id
    assert item["canonical_window_id"] == session_id
    assert item["source_refs_canonical_window_id"] == "workspace-f2a87c03"
    assert marker in item["raw_excerpt"]
    assert content["cross_window_read"] is False
    assert content["cross_window_read_allowed"] is True


def test_claude_desktop_preflight_uses_claude_code_alias_for_same_window_index(tmp_path, monkeypatch):
    root = tmp_path / "memcore"
    records_db = root / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    session_id = "claude-managed-session"
    raw_path = root / "memory" / "WINNODEB" / "claude_code_cli" / "claude_code_session_jsonl" / "workspace-f2a87c03" / f"{session_id}.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("", encoding="utf-8")
    marker = "CLAUDE_DESKTOP_PREFLIGHT_ALIAS_MARKER"
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, project_root, source_path,
                raw_path, role, native_type, native_id, timestamp, line_no,
                raw_line_no, source_offset_start, source_offset_end,
                raw_offset_start, raw_offset_end, content_preview, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-claude-desktop-alias",
                "record-claude-desktop-alias",
                "claude_code_cli",
                session_id,
                "workspace-f2a87c03",
                "memcore-cloud",
                "/work/memcore-cloud",
                str(raw_path),
                str(raw_path),
                "assistant",
                "claude_code_session_jsonl",
                "native-claude-desktop-alias",
                "2026-06-15T12:21:00Z",
                1,
                1,
                0,
                200,
                0,
                200,
                f"继续 {marker}：Desktop MCP 当前窗口实际由 Claude Code CLI 记录承载。",
                "2026-06-15T12:21:01Z",
            ),
        )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _write_declared_source_filter_binding(
        tmp_path,
        source_system="claude_desktop",
        canonical_window_id="workspace-f2a87c03",
        session_id=session_id,
        source_system_filters=["claude_desktop", "claude_code_cli"],
    )
    _, raw_gateway = _reload_modules(tmp_path)
    monkeypatch.setattr(
        raw_gateway,
        "_load_handle_recall",
        lambda: (_ for _ in ()).throw(AssertionError("same-window alias preflight must stay on canonical index")),
    )

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 43,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": f"继续 {marker}",
                "mode": "preflight",
                "consumer": "claude_desktop",
                "source_system": "claude_desktop",
                "memory_scope": "window",
                "canonical_window_id": "workspace-f2a87c03",
                "session_id": session_id,
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["decision"] == "surface"
    assert content["source_system_filter"] == "claude_desktop"
    assert content["source_system_filter_aliases"] == ["claude_desktop", "claude_code_cli"]
    assert content["source_collection_filter"] == "binding_declared_source_systems"
    assert content["source_collection_alias_applied"] is True
    assert content["fast_window_index_status"] == "claude_desktop:miss_identity;claude_code_cli:hit"
    assert content["must_surface"][0]["source_system"] == "claude_code_cli"
    assert content["must_surface"][0]["session_id"] == session_id
    assert content["must_surface"][0]["source_refs_canonical_window_id"] == "workspace-f2a87c03"
    assert content["cross_window_read"] is False

    unknown_host_call = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 430,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": f"继续 {marker}",
                "mode": "preflight",
                "consumer": "unlisted_host",
                "source_system": "claude_desktop",
                "memory_scope": "window",
                "canonical_window_id": "workspace-f2a87c03",
                "session_id": session_id,
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    unknown_host_content = unknown_host_call["result"]["structuredContent"]
    assert unknown_host_content["source_system_filter_aliases"] == content["source_system_filter_aliases"]
    assert unknown_host_content["source_collection_alias_applied"] is True
    assert unknown_host_content["matched_count"] == content["matched_count"]


def test_claude_desktop_window_recall_uses_catalog_index_before_raw_fallback(tmp_path, monkeypatch):
    marker = "WINNODEA_CLAUDE_CATALOG_FIRST_MARKER"
    session_id = "claude-managed-session"
    records_db, _ = _write_canonical_message(
        tmp_path,
        source_system="claude_code_cli",
        computer_name="WINNODEA",
        session_id=session_id,
        window_id="workspace-f2a87c03",
        content_preview=f"继续 {marker}：同窗口 Claude Desktop 召回应先读 canonical index。",
    )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _write_declared_source_filter_binding(
        tmp_path,
        source_system="claude_desktop",
        canonical_window_id="workspace-f2a87c03",
        session_id=session_id,
        source_system_filters=["claude_desktop", "claude_code_cli"],
    )
    _, raw_gateway = _reload_modules(tmp_path)
    monkeypatch.setattr(
        raw_gateway,
        "_query_raw_jsonl_fallback",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("catalog hit must not scan raw JSONL")),
    )
    monkeypatch.setattr(
        raw_gateway,
        "_extract_bounded_raw_excerpt",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("compact catalog recall must not expand raw excerpts")
        ),
    )

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 44,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": marker,
                "consumer": "claude_desktop",
                "source_system": "claude_desktop",
                "memory_scope": "window",
                "canonical_window_id": "workspace-f2a87c03",
                "session_id": session_id,
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["source_system_filter"] == "claude_desktop"
    assert content["source_system_filter_aliases"] == ["claude_desktop", "claude_code_cli"]
    assert content["catalog_index_used"] is True
    assert content["catalog_index_status"] == "claude_desktop:miss_identity;claude_code_cli:hit"
    assert content["catalog_index_items_count"] == 1
    assert content["library_index_projection_used"] is True
    assert content["library_index_projection_policy"] == "navigation_hint_only_raw_evidence_required"
    assert content["library_index_projection_refs_count"] == 1
    assert content["library_index_projection_refs"][0]["authority"] == "navigation_hint_only_raw_evidence_required"
    assert content["raw_recall_trajectory_contract"] == "raw_recall_trajectory.v2026.6.17"
    assert content["raw_recall_trajectory_policy"] == "retrieval_steps_are_diagnostics_not_evidence"
    trajectory = {step["step"]: step for step in content["raw_recall_trajectory"]}
    assert trajectory["catalog_index_projection"]["layer"] == "L1_library_index_projection"
    assert trajectory["catalog_index_projection"]["status"] == "claude_desktop:miss_identity;claude_code_cli:hit"
    assert trajectory["catalog_index_projection"]["used"] is True
    assert trajectory["catalog_index_projection"]["authority"] == "navigation_hint_only_raw_evidence_required"
    assert trajectory["raw_fallback"]["layer"] == "L2_raw_records"
    assert trajectory["raw_fallback"]["status"] == "skipped_catalog_index_hit"
    assert trajectory["raw_fallback"]["used"] is False
    assert trajectory["final_receipt"]["status"] == "raw"
    assert content["raw_fallback_used"] is False
    assert content["raw_fallback_status"] == "skipped_catalog_index_hit"
    assert content["raw_fallback_scanned_files"] == 0
    assert content["response_budget"]["mode"] == "raw_gateway_compact"
    assert content["response_budget"]["raw_excerpt_returned"] is False
    assert content["items"][0]["source_system"] == "claude_code_cli"
    assert content["items"][0]["raw_evidence_status"] == "raw_index"
    assert content["items"][0]["library_index_projection_used"] is True
    assert content["items"][0]["library_index_projection_authority"] == "navigation_hint_only_raw_evidence_required"
    assert content["consumer_receipt"]["library_index_projection_used"] is True
    assert content["consumer_receipt"]["library_index_projection_refs_count"] == 1
    assert content["consumer_receipt"]["raw_recall_trajectory_contract"] == "raw_recall_trajectory.v2026.6.17"
    assert content["consumer_receipt"]["raw_recall_trajectory"][1]["step"] == "catalog_index_projection"
    assert "raw_excerpt" not in content["items"][0]


def test_mcp_raw_recall_reads_each_canonical_generation_from_its_own_raw_segment(tmp_path, monkeypatch):
    root = tmp_path / "memcore"
    session_id = "generation-session"
    window_id = "generation-window"
    raw_dir = root / "memory" / "LOCALNODE" / "codex" / "codex_session_jsonl" / window_id
    first_raw = raw_dir / f"{session_id}.jsonl"
    second_raw = raw_dir / f"{session_id}.seg1.jsonl"
    first_lookup = "GENERATION_ZERO_LOOKUP"
    second_lookup = "GENERATION_ONE_LOOKUP"
    first_marker = "SEGMENT_ZERO_VERBATIM_SOURCE"
    second_marker = "SEGMENT_ONE_VERBATIM_SOURCE"
    first_line = (
        json.dumps(
            {
                "id": "native-generation-zero",
                "timestamp": "2026-07-31T10:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": first_marker}],
                },
            },
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    second_line = (
        json.dumps(
            {
                "id": "native-generation-one",
                "timestamp": "2026-07-31T10:01:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": second_marker}],
                },
            },
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")

    records_db, _ = _write_canonical_message(
        tmp_path,
        source_system="codex",
        computer_name="LOCALNODE",
        session_id=session_id,
        window_id=window_id,
        message_id="message-generation-zero",
        record_id="record-generation-lineage",
        native_id="native-generation-zero",
        role="user",
        timestamp="2026-07-31T10:00:00Z",
        line_no=1,
        content_preview=f"{first_lookup} catalog navigation only",
        raw_path_override=first_raw,
        raw_bytes=first_line,
        raw_offset_start=0,
        raw_offset_end=len(first_line),
    )
    _write_canonical_message(
        tmp_path,
        source_system="codex",
        computer_name="LOCALNODE",
        session_id=session_id,
        window_id=window_id,
        message_id="message-generation-one",
        record_id="record-generation-lineage",
        native_id="native-generation-one",
        role="assistant",
        timestamp="2026-07-31T10:01:00Z",
        line_no=2,
        content_preview=f"{second_lookup} catalog navigation only",
        raw_path_override=second_raw,
        raw_bytes=second_line,
        raw_offset_start=0,
        raw_offset_end=len(second_line),
    )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _, raw_gateway = _reload_modules(tmp_path)

    def recall(query):
        response = raw_gateway.handle_mcp_request({
            "jsonrpc": "2.0",
            "id": query,
            "method": "tools/call",
            "params": {
                "name": "time_library_recall",
                "arguments": {
                    "query": query,
                    "consumer": "codex",
                    "source_system": "codex",
                    "memory_scope": "window",
                    "canonical_window_id": window_id,
                    "session_id": session_id,
                    "limit": 1,
                    "excerpt_chars": 300,
                    "response_budget": "raw",
                    "delivery_tracking": False,
                },
            },
        })
        content = response["result"]["structuredContent"]
        assert content["catalog_index_used"] is True
        assert content["response_budget"]["mode"] == "raw"
        assert content["raw_fallback_used"] is False
        assert len(content["items"]) == 1
        item = content["items"][0]
        assert content["consumer_receipt"]["used_source_refs"][0]["source_path"] == item["source_path"]
        assert content["library_index_projection_refs"][0]["source_path"] == item["source_path"]
        assert content["library_index_projection_refs"][0]["raw_evidence_status"] == "raw_offset"
        return item

    first_item = recall(first_lookup)
    second_item = recall(second_lookup)

    assert first_item["source_path"] == str(first_raw)
    assert second_item["source_path"] == str(second_raw)
    assert first_marker in first_item["raw_excerpt"]
    assert second_marker not in first_item["raw_excerpt"]
    assert second_marker in second_item["raw_excerpt"]
    assert first_marker not in second_item["raw_excerpt"]
    assert first_lookup not in first_item["raw_excerpt"]
    assert second_lookup not in second_item["raw_excerpt"]

    for item, expected in ((first_item, first_line), (second_item, second_line)):
        offsets = item["byte_offsets"]
        source_bytes = Path(item["source_path"]).read_bytes()
        assert source_bytes[offsets["start"]:offsets["end"]] == expected
        assert item["raw_evidence_status"] == "raw_offset"
        assert item["raw_expand_status"] == "raw_offset"
        assert item["raw_expand_from_catalog_index"] is True
        assert item["evidence_hash"] == hashlib.sha256(item["raw_excerpt"].encode("utf-8")).hexdigest()
        assert item["library_card"]["verbatim_excerpt"] == item["raw_excerpt"]
        assert item["library_card"]["verbatim_sha256"] == item["evidence_hash"]
        assert item["library_card"]["byte_offsets"] == offsets


def test_raw_gateway_window_recall_catalog_miss_uses_bounded_raw_fallback_stats(tmp_path, monkeypatch):
    marker = "BOUNDED_RAW_FALLBACK_MARKER"
    root = tmp_path / "memcore"
    records_db = root / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    raw_path = root / "memory" / "WINNODEA" / "claude_code_cli" / "claude_code_session_jsonl" / "workspace-f2a87c03" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps({
            "timestamp": "2026-06-15T12:30:00Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": marker},
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _write_declared_source_filter_binding(
        tmp_path,
        source_system="claude_desktop",
        canonical_window_id="workspace-f2a87c03",
        session_id="session-a",
        source_system_filters=["claude_desktop", "claude_code_cli"],
    )
    _, raw_gateway = _reload_modules(tmp_path)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 45,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": marker,
                "consumer": "claude_desktop",
                "source_system": "claude_desktop",
                "memory_scope": "window",
                "canonical_window_id": "workspace-f2a87c03",
                "session_id": "session-a",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["catalog_index_used"] is False
    assert content["catalog_index_status"] == "claude_desktop:miss_identity;claude_code_cli:miss_identity"
    trajectory = {step["step"]: step for step in content["raw_recall_trajectory"]}
    assert trajectory["catalog_index_projection"]["used"] is False
    assert trajectory["catalog_index_projection"]["status"] == "claude_desktop:miss_identity;claude_code_cli:miss_identity"
    assert trajectory["raw_fallback"]["used"] is True
    assert trajectory["raw_fallback"]["status"] == "claude_desktop:miss;claude_code_cli:hit"
    assert trajectory["raw_fallback"]["authority"] == "raw_records_are_final_evidence"
    assert content["raw_fallback_used"] is True
    assert content["raw_fallback_status"] == "claude_desktop:miss;claude_code_cli:hit"
    assert content["raw_fallback_scanned_files"] == 1
    assert content["raw_fallback_scanned_lines"] == 1
    assert content["raw_fallback_timed_out"] is False
    assert content["items"][0]["raw_evidence_status"] == "raw_direct"
    assert "raw_excerpt" not in content["items"][0]
    assert content["response_budget"]["raw_excerpt_available"] is True


def test_raw_gateway_fallback_decodes_gb18030_jsonl_without_mojibake(tmp_path):
    marker = "中文定论：time-rule中性，minimax-cn 网页认证不通，模型中心是time-rule。"
    root = tmp_path / "memcore"
    raw_path = root / "memory" / "local" / "codex" / "codex_session_jsonl" / "project-a" / "gb18030-live.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "timestamp": "2026-06-02T09:00:00Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": marker,
        },
    }, ensure_ascii=False) + "\n"
    raw_path.write_bytes(line.encode("gb18030"))
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        marker,
        source_system="codex",
        computer_name="",
        session_id="",
        limit=5,
        excerpt_chars=300,
        consumer="codex",
        request_id="test-gb18030-raw-direct",
        canonical_window_id="project-a",
    )

    assert result["items"]
    item = result["items"][0]
    assert item["raw_evidence_status"] == "raw_direct"
    assert item["raw_mapping_mode"] == "raw_jsonl_fallback"
    assert marker in item["raw_excerpt"]
    assert "\ufffd" not in item["raw_excerpt"]


def test_raw_direct_pool_decodes_gb18030_jsonl_without_mojibake(tmp_path):
    marker = "中文定论：time-rule中性，minimax-cn 网页认证不通，模型中心是time-rule。"
    root = tmp_path / "memcore"
    raw_path = root / "local" / "codex" / "codex_session_jsonl" / "project-a" / "raw-direct.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "timestamp": "2026-06-02T09:10:00Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": marker,
        },
    }, ensure_ascii=False) + "\n"
    raw_path.write_bytes(line.encode("gb18030"))

    from src.raw_direct_experience_pool import query_raw_direct

    items = query_raw_direct(
        query_hint=marker,
        source_system="codex",
        computer_name="local",
        raw_root=str(root),
        limit=3,
        excerpt_chars=300,
    )

    assert items
    assert marker in items[0]["raw_excerpt"]
    assert "\ufffd" not in items[0]["raw_excerpt"]
