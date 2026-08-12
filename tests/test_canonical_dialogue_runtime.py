import json
from pathlib import Path

from src.canonical_dialogue_runtime import (
    CANONICAL_DIALOGUE_CAPTURE_CONTRACT,
    CANONICAL_DIALOGUE_MIGRATION_REPORT_CONTRACT,
    FORENSIC_RUNTIME_MANIFEST_CONTRACT,
    build_canonical_dialogue_migration_report,
    canonical_dialogue_sidecar_path,
    forensic_runtime_manifest_path,
    materialize_canonical_dialogue,
)


def _append_jsonl(path: Path, records) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_materialize_canonical_dialogue_filters_runtime_exhaust_from_codex_jsonl(tmp_path):
    raw_path = tmp_path / "memory" / "local" / "codex" / "codex_session_jsonl" / "project" / "session.jsonl"
    _append_jsonl(
        raw_path,
        [
            {
                "type": "session_meta",
                "payload": {"id": "sess-1", "cwd": "/tmp/project"},
            },
            {
                "id": "u1",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "请记住只保留对话原样。"}],
                },
            },
            {
                "id": "t1",
                "type": "response_item",
                "payload": {
                    "type": "tool_result",
                    "role": "user",
                    "content": [{"type": "tool_result", "text": "The file has been updated successfully."}],
                },
            },
            {
                "id": "a1",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "结论：主河只保留对话。"}],
                },
            },
            {
                "id": "a2",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "data:image/png;base64,AAAA"}],
                },
            },
        ],
    )

    result = materialize_canonical_dialogue(
        raw_path,
        source_system="codex",
        session_id="sess-1",
        canonical_window_id="win-1",
        native_artifact_format="codex_session_jsonl",
        reset=True,
    )

    assert result["ok"] is True
    assert result["contract"] == FORENSIC_RUNTIME_MANIFEST_CONTRACT
    assert result["dialogue_message_count"] == 2
    assert result["excluded_counts"]["runtime_tool_event"] == 1
    assert result["excluded_counts"]["runtime_blob"] == 1

    dialogue_lines = [
        json.loads(line)
        for line in canonical_dialogue_sidecar_path(raw_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["role"] for item in dialogue_lines] == ["user", "assistant"]
    assert dialogue_lines[0]["content"] == "请记住只保留对话原样。"
    assert dialogue_lines[1]["content"] == "结论：主河只保留对话。"
    assert all(item["contract"] == CANONICAL_DIALOGUE_CAPTURE_CONTRACT for item in dialogue_lines)


def test_materialize_canonical_dialogue_appends_incrementally(tmp_path):
    raw_path = tmp_path / "memory" / "local" / "claude_code_cli" / "claude_code_session_jsonl" / "project" / "session.jsonl"
    _append_jsonl(
        raw_path,
        [
            {
                "type": "user",
                "uuid": "u1",
                "sessionId": "sess-2",
                "message": {"role": "user", "content": "先保留这句用户原话。"},
            }
        ],
    )

    first = materialize_canonical_dialogue(
        raw_path,
        source_system="claude_code_cli",
        session_id="sess-2",
        canonical_window_id="win-2",
        native_artifact_format="claude_code_session_jsonl",
        reset=True,
    )
    assert first["dialogue_message_count"] == 1

    _append_jsonl(
        raw_path,
        [
            {
                "type": "assistant",
                "uuid": "a1",
                "sessionId": "sess-2",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "再追加一句可见答复。"}]},
            },
            {
                "type": "user",
                "uuid": "u2",
                "sessionId": "sess-2",
                "message": {"role": "user", "content": [{"type": "tool_result", "text": "tool output"}]},
            },
        ],
    )
    second = materialize_canonical_dialogue(
        raw_path,
        source_system="claude_code_cli",
        session_id="sess-2",
        canonical_window_id="win-2",
        native_artifact_format="claude_code_session_jsonl",
        reset=False,
    )

    assert second["dialogue_message_count"] == 2
    assert second["excluded_counts"]["non_dialogue_role"] == 1
    lines = canonical_dialogue_sidecar_path(raw_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert any("再追加一句可见答复。" in line for line in lines)
    manifest = json.loads(forensic_runtime_manifest_path(raw_path).read_text(encoding="utf-8"))
    assert manifest["source_offset_processed"] == raw_path.stat().st_size
    assert manifest["dialogue_message_count"] == 2


def test_materialize_canonical_dialogue_rebuilds_when_manifest_is_missing_without_duplicates(tmp_path):
    raw_path = tmp_path / "memory" / "local" / "codex" / "codex_session_jsonl" / "project" / "session.jsonl"
    _append_jsonl(
        raw_path,
        [
            {
                "id": "u1",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "先保留这句。"}],
                },
            },
            {
                "id": "a1",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "再保留这句。"}],
                },
            },
        ],
    )

    first = materialize_canonical_dialogue(
        raw_path,
        source_system="codex",
        session_id="sess-3",
        canonical_window_id="win-3",
        native_artifact_format="codex_session_jsonl",
        reset=True,
    )
    assert first["dialogue_message_count"] == 2
    forensic_runtime_manifest_path(raw_path).unlink()

    second = materialize_canonical_dialogue(
        raw_path,
        source_system="codex",
        session_id="sess-3",
        canonical_window_id="win-3",
        native_artifact_format="codex_session_jsonl",
        reset=False,
    )

    assert second["dialogue_message_count"] == 2
    lines = canonical_dialogue_sidecar_path(raw_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_materialized_canonical_dialogue_entry_has_self_borrowable_source_ref(tmp_path):
    raw_path = tmp_path / "memory" / "local" / "codex" / "codex_session_jsonl" / "project" / "session.jsonl"
    _append_jsonl(
        raw_path,
        [
            {
                "id": "u1",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "只保留真正的对话内容。"}],
                },
            },
            {
                "id": "a1",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "收到，运行态进冷层。"}],
                },
            },
        ],
    )

    result = materialize_canonical_dialogue(
        raw_path,
        source_system="codex",
        session_id="sess-4",
        canonical_window_id="win-4",
        native_artifact_format="codex_session_jsonl",
        reset=True,
    )

    assert result["ok"] is True
    dialogue_path = canonical_dialogue_sidecar_path(raw_path)
    with dialogue_path.open("rb") as handle:
        first_line = handle.readline()
    first = json.loads(first_line.decode("utf-8"))
    refs = first["source_refs"]
    assert refs["source_path"] == str(dialogue_path)
    assert refs["native_artifact_format"] == "canonical_dialogue_jsonl"
    assert first["source_ref"].startswith(str(dialogue_path) + ":")
    start = refs["byte_offsets"]["start"]
    end = refs["byte_offsets"]["end"]
    assert start == 0
    assert end == len(first_line)
    with dialogue_path.open("rb") as handle:
        handle.seek(start)
        borrowed = handle.read(end - start)
    assert borrowed == first_line


def test_generation_event_identity_deduplicates_exact_overlap_but_keeps_rewrite(tmp_path):
    source_path = tmp_path / "native" / "session.jsonl"
    first_raw = tmp_path / "raw" / "session.jsonl"
    second_raw = tmp_path / "raw" / "session.seg1.jsonl"
    third_raw = tmp_path / "raw" / "session.seg2.jsonl"
    shared_user = {
        "id": "u1",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "同一条用户内容。"}],
        },
    }
    shared_assistant = {
        "id": "a1",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "同一条助手内容。"}],
        },
    }
    rewritten_assistant = json.loads(json.dumps(shared_assistant, ensure_ascii=False))
    rewritten_assistant["payload"]["content"][0]["text"] = "真实改写后的助手内容。"
    first_meta = {"type": "session_meta", "payload": {"id": "s1", "model_provider": "token"}}
    second_meta = {"type": "session_meta", "payload": {"id": "s1", "model_provider": "custom"}}
    _append_jsonl(first_raw, [first_meta, shared_user, shared_assistant])
    _append_jsonl(second_raw, [second_meta, shared_user, shared_assistant])
    _append_jsonl(third_raw, [second_meta, shared_user, rewritten_assistant])

    for generation, raw_path in enumerate((first_raw, second_raw, third_raw)):
        materialize_canonical_dialogue(
            raw_path,
            source_system="codex",
            session_id="s1",
            canonical_window_id="w1",
            native_artifact_format="codex_session_jsonl",
            reset=True,
            native_source_path=source_path,
            source_base_offset=0,
            generation=generation,
            predecessor=str((first_raw, first_raw, second_raw)[generation]),
        )

    entries = []
    for raw_path in (first_raw, second_raw, third_raw):
        entries.append([
            json.loads(line)
            for line in canonical_dialogue_sidecar_path(raw_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ])

    assert [item["event_id"] for item in entries[0]] == [item["event_id"] for item in entries[1]]
    assert entries[0][0]["event_id"] == entries[2][0]["event_id"]
    assert entries[0][1]["event_id"] != entries[2][1]["event_id"]
    assert entries[1][0]["origin_source_ref"]["generation"] == 1
    assert entries[1][0]["origin_source_ref"]["native_source_path"] == str(source_path)


def test_build_canonical_dialogue_migration_report_emits_ref_map_and_metrics(tmp_path):
    raw_path = tmp_path / "memory" / "local" / "claude_code_cli" / "claude_code_session_jsonl" / "project" / "session.jsonl"
    _append_jsonl(
        raw_path,
        [
            {
                "type": "user",
                "uuid": "u1",
                "sessionId": "sess-5",
                "message": {"role": "user", "content": "对话为水，运行态为沫。"},
            },
            {
                "type": "assistant",
                "uuid": "a1",
                "sessionId": "sess-5",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "记住这条法。"}]},
            },
            {
                "type": "user",
                "uuid": "u2",
                "sessionId": "sess-5",
                "message": {"role": "user", "content": [{"type": "tool_result", "text": "tool output"}]},
            },
        ],
    )

    report = build_canonical_dialogue_migration_report(
        raw_path,
        source_system="claude_code_cli",
        session_id="sess-5",
        canonical_window_id="win-5",
        native_artifact_format="claude_code_session_jsonl",
        reset=True,
    )

    assert report["ok"] is True
    assert report["contract"] == CANONICAL_DIALOGUE_MIGRATION_REPORT_CONTRACT
    assert report["session_status"] == "materialized_for_reanchor"
    assert report["before_after"]["parsed_message_count"] == 3
    assert report["before_after"]["dialogue_message_count"] == 2
    assert report["before_after"]["excluded_total"] == 1
    assert report["before_after"]["retained_dialogue_content_bytes"] == len("对话为水，运行态为沫。记住这条法。".encode("utf-8"))
    assert report["before_after"]["canonical_dialogue_storage_ratio"] > 0
    assert len(report["old_ref_to_new_ref_map"]) == 2
    assert report["needs_reanchor"] == []
    first_map = report["old_ref_to_new_ref_map"][0]
    assert first_map["status"] == "ready"
    assert first_map["old_source_ref"].endswith(".jsonl:0-" + first_map["old_source_ref"].split(":")[-1].split("-")[-1])
    assert ".canonical_dialogue.jsonl:" in first_map["new_source_ref"]
    assert first_map["verbatim_sha256"]
    assert report["reanchor_readiness"]["message_id_ready"] == 2
    assert report["reanchor_readiness"]["verbatim_sha_ready"] == 2


def test_build_canonical_dialogue_migration_report_marks_missing_raw_as_needs_reanchor(tmp_path):
    raw_path = tmp_path / "missing" / "session.jsonl"
    report = build_canonical_dialogue_migration_report(
        raw_path,
        source_system="codex",
        session_id="sess-missing",
        canonical_window_id="win-missing",
        native_artifact_format="codex_session_jsonl",
        reset=True,
    )

    assert report["ok"] is False
    assert report["contract"] == CANONICAL_DIALOGUE_MIGRATION_REPORT_CONTRACT
    assert report["session_status"] == "migration_failed"
    assert report["needs_reanchor"][0]["status"] == "needs_reanchor"
    assert report["needs_reanchor"][0]["reason"] == "raw_path_missing"
