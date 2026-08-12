import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _env(tmp_path, projects_root):
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(SRC),
        "MEMCORE_ROOT": str(tmp_path / "memcore"),
        "MEMCORE_CONFIG": str(ROOT / "config" / "memcore.json"),
        "CLAUDE_CODE_PROJECTS_DIR": str(projects_root),
        "MEMCORE_P2_CHECKPOINT": str(tmp_path / "p2.checkpoint.json"),
    })
    return env


def _env_with_desktop(tmp_path, projects_root, desktop_root, runtime_root=None):
    env = _env(tmp_path, projects_root)
    env["CLAUDE_DESKTOP_CODE_SESSIONS_DIR"] = str(desktop_root)
    if runtime_root is not None:
        env["CLAUDE_DESKTOP_CODE_RUNTIME_DIR"] = str(runtime_root)
    return env


def _append_jsonl(path, records):
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_claude_code_session(tmp_path, *, assistant=True):
    projects_root = tmp_path / "claude-projects"
    project_dir = projects_root / "-Users-example-workspace"
    project_dir.mkdir(parents=True)
    session_id = "4f9a23ea-b37e-41d3-81f2-846611f23cc8"
    session_path = project_dir / f"{session_id}.jsonl"
    records = [
        {
            "type": "user",
            "sessionId": session_id,
            "uuid": "user-1",
            "parentUuid": None,
            "cwd": str(tmp_path / "workspace"),
            "timestamp": "2026-06-05T08:00:00Z",
            "message": {
                "role": "user",
                "content": "首先查证本地中转的 Claude Code 会话路径，然后验证Time Library是否能独立归档。",
            },
        },
    ]
    if assistant:
        records.append({
            "type": "assistant",
            "sessionId": session_id,
            "uuid": "assistant-1",
            "parentUuid": "user-1",
            "cwd": str(tmp_path / "workspace"),
            "timestamp": "2026-06-05T08:00:01Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "验证通过：Claude Code CLI 的关键路径是 ~/.claude/projects JSONL -> computer-first raw -> P2 提炼 -> 知意召回。",
                    }
                ],
            },
        })
    _append_jsonl(session_path, records)
    return projects_root, session_path, session_id


def _write_desktop_code_session_metadata(tmp_path, desktop_root, cli_session_id):
    meta_dir = desktop_root / "account" / "install"
    meta_dir.mkdir(parents=True)
    meta_path = meta_dir / "local_desktop-session-1.json"
    meta_path.write_text(json.dumps({
        "sessionId": "local_desktop-session-1",
        "cliSessionId": cli_session_id,
        "cwd": str(tmp_path / "workspace"),
        "originCwd": str(tmp_path / "workspace"),
        "title": "Desktop shell title",
        "titleSource": "auto",
        "model": "claude-haiku-4-5-20251001",
        "permissionMode": "acceptEdits",
        "completedTurns": 1,
        "createdAt": 1780000000000,
        "lastActivityAt": 1780000001000,
        "lastFocusedAt": 1780000002000,
        "isArchived": False,
    }, ensure_ascii=False), encoding="utf-8")
    return meta_path


def _write_desktop_managed_runtime(tmp_path):
    runtime_root = tmp_path / "Claude" / "claude-code" / "2.1.161"
    runtime_root.mkdir(parents=True)
    (runtime_root / "claude.exe").write_text("desktop managed runtime", encoding="utf-8")
    return runtime_root.parent


def _write_claude_desktop_entrypoint_session(tmp_path):
    projects_root = tmp_path / "claude-projects"
    project_dir = projects_root / "-Users-example-orchestration_system"
    project_dir.mkdir(parents=True)
    session_id = "9ae36939-9285-4683-a229-e9a1665a3cfe"
    session_path = project_dir / f"{session_id}.jsonl"
    records = [
        {
            "type": "user",
            "entrypoint": "claude-desktop",
            "sessionId": session_id,
            "uuid": "desktop-user-1",
            "cwd": str(tmp_path / "Projects" / "orchestration_system"),
            "timestamp": "2026-06-01T02:41:55Z",
            "message": {
                "role": "user",
                "content": "请直接调用 time-library 的 MCP 工具 zhiyi_recall，做一次最小真召回，不要走 HTTP。",
            },
        },
        {
            "type": "assistant",
            "entrypoint": "claude-desktop",
            "sessionId": session_id,
            "uuid": "desktop-assistant-1",
            "parentUuid": "desktop-user-1",
            "cwd": str(tmp_path / "Projects" / "orchestration_system"),
            "timestamp": "2026-06-01T02:48:44Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "召回汇报：ok true，matched_count 1。"}],
            },
        },
    ]
    _append_jsonl(session_path, records)
    return projects_root, session_path, session_id


def test_claude_code_scan_preserves_raw_and_registers_current_window(tmp_path):
    projects_root, session_path, session_id = _write_claude_code_session(tmp_path)
    env = _env(tmp_path, projects_root)

    scan = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(scan.stdout)
    assert payload["changed"] == 1
    assert payload["source_system"] == "claude_code_cli"
    assert payload["window_bindings_registered"] == 1

    dest = Path(payload["items"][0]["dest"])
    assert dest.exists()
    assert "/memory/local/claude_code_cli/claude_code_session_jsonl/" in str(dest)
    text = dest.read_text(encoding="utf-8")
    assert "首先查证本地中转" in text
    assert "Claude Code CLI 的关键路径" in text
    assert json.loads(dest.read_text(encoding="utf-8").splitlines()[0])["type"] == "user"

    meta = json.loads(Path(str(dest) + ".meta.json").read_text(encoding="utf-8"))
    assert meta["source_system"] == "claude_code_cli"
    assert meta["native_artifact_format"] == "claude_code_session_jsonl"
    assert meta["raw_archive_layout"] == "computer_first"
    assert meta["session_id"] == session_id
    assert meta["main_river_storage"] == "canonical_dialogue"
    assert Path(meta["canonical_dialogue_path"]).exists()
    dialogue_records = [
        json.loads(line)
        for line in Path(meta["canonical_dialogue_path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["role"] for item in dialogue_records] == ["user", "assistant"]

    registry = json.loads((tmp_path / "memcore" / "config" / "window_binding_registry.json").read_text(encoding="utf-8"))
    current = registry["current_windows"]["claude_code_cli"]
    assert current["canonical_window_id"] == session_id
    assert current["session_id"] == session_id
    assert current["source_path"] == str(dest)
    assert current["cross_window_read_allowed"] is False
    assert current["metadata"]["project_root"] == str(tmp_path / "workspace")

    raw_checkpoint = json.loads((tmp_path / "memcore" / ".checkpoint").read_text(encoding="utf-8"))
    entries = [value for key, value in raw_checkpoint.items() if key.startswith("claude_code_cli:")]
    assert entries
    assert entries[0]["offset"] == session_path.stat().st_size


def test_claude_code_source_truncation_keeps_primary_raw_byte_exact(tmp_path):
    projects_root, session_path, _ = _write_claude_code_session(tmp_path)
    env = _env(tmp_path, projects_root)

    first = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    dest = Path(json.loads(first.stdout)["items"][0]["dest"])
    archived_bytes = dest.read_bytes()
    first_line = session_path.read_bytes().splitlines(keepends=True)[0]
    session_path.write_bytes(first_line)

    second = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(second.stdout)

    assert payload["changed"] == 0
    assert payload["items"][0]["status"].startswith("source_regression_raw_retained")
    assert dest.read_bytes() == archived_bytes


def test_claude_code_divergence_generation_continues_and_reanchors_canonical_dialogue(tmp_path):
    projects_root, session_path, session_id = _write_claude_code_session(tmp_path)
    env = _env(tmp_path, projects_root)

    first_scan = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    original_dest = Path(json.loads(first_scan.stdout)["items"][0]["dest"])
    original_bytes = original_dest.read_bytes()
    original_lines = session_path.read_bytes().splitlines(keepends=True)
    assert len(original_lines) == 2

    rewritten_assistant = json.loads(original_lines[1].decode("utf-8"))
    rewritten_assistant["message"]["content"][0]["text"] = "分歧后的 Claude Code assistant 内容。"
    new_user = {
        "type": "user",
        "sessionId": session_id,
        "uuid": "user-2",
        "parentUuid": "assistant-1",
        "cwd": str(tmp_path / "workspace"),
        "timestamp": "2026-06-05T08:00:02Z",
        "message": {"role": "user", "content": "分歧之后继续写入的新问题。"},
    }
    rewritten = original_lines[0]
    rewritten += (json.dumps(rewritten_assistant, ensure_ascii=False) + "\n").encode("utf-8")
    rewritten += (json.dumps(new_user, ensure_ascii=False) + "\n").encode("utf-8")
    session_path.write_bytes(rewritten)
    expected_base = len(original_lines[0])

    second_scan = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    second_payload = json.loads(second_scan.stdout)
    second_item = second_payload["items"][0]
    generation_dest = Path(second_item["dest"])
    generation_meta = json.loads(Path(str(generation_dest) + ".meta.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((tmp_path / "memcore" / ".checkpoint").read_text(encoding="utf-8"))
    checkpoint_entry = next(value for key, value in checkpoint.items() if key.startswith("claude_code_cli:"))

    assert second_payload["changed"] == 1
    assert second_item["status"].startswith("generation_started")
    assert generation_dest.name == original_dest.stem + ".seg1" + original_dest.suffix
    assert original_dest.read_bytes() == original_bytes
    assert generation_dest.read_bytes() == rewritten[expected_base:]
    assert generation_meta["raw_generation"] == 1
    assert generation_meta["source_base_offset"] == expected_base
    assert generation_meta["raw_generation_predecessor"] == str(original_dest)
    assert generation_meta["raw_order"] == 2
    assert checkpoint_entry["generation"] == 1
    assert checkpoint_entry["source_base_offset"] == expected_base
    assert checkpoint_entry["archived_to"] == str(generation_dest)

    generation_dialogue = [
        json.loads(line)
        for line in Path(str(generation_dest) + ".canonical_dialogue.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["role"] for item in generation_dialogue] == ["assistant", "user"]
    assert all(
        item["origin_source_ref"]["native_source_byte_offsets"]["start"] >= expected_base
        for item in generation_dialogue
    )

    status = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--status"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    raw_sync = json.loads(status.stdout)["raw_sync"]
    assert raw_sync["missing_or_stale_count"] == 0
    assert raw_sync["latest_missing_or_stale"] == []

    new_assistant = {
        "type": "assistant",
        "sessionId": session_id,
        "uuid": "assistant-2",
        "parentUuid": "user-2",
        "cwd": str(tmp_path / "workspace"),
        "timestamp": "2026-06-05T08:00:03Z",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "新 generation 的 Claude Code 回复。"}],
        },
    }
    appended_line = (json.dumps(new_assistant, ensure_ascii=False) + "\n").encode("utf-8")
    with session_path.open("ab") as handle:
        handle.write(appended_line)
    third_scan = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    third_item = json.loads(third_scan.stdout)["items"][0]
    generation_dialogue_after = [
        json.loads(line)
        for line in Path(str(generation_dest) + ".canonical_dialogue.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert third_item["dest"] == str(generation_dest)
    assert third_item["status"].startswith("appended_generation")
    assert generation_dest.read_bytes() == rewritten[expected_base:] + appended_line
    assert original_dest.read_bytes() == original_bytes
    assert [item["role"] for item in generation_dialogue_after] == ["assistant", "user", "assistant"]


def test_claude_code_subagents_do_not_overwrite_parent_session_raw(tmp_path):
    projects_root, parent_path, session_id = _write_claude_code_session(tmp_path)
    subagent_dir = parent_path.with_suffix("") / "subagents"
    subagent_dir.mkdir(parents=True)
    subagent_path = subagent_dir / "agent-a3053a9a5122ec4f3.jsonl"
    _append_jsonl(
        subagent_path,
        [
            {
                "type": "user",
                "sessionId": session_id,
                "uuid": "sub-user-1",
                "cwd": str(tmp_path / "workspace"),
                "message": {"role": "user", "content": "子 agent 分支用户消息。"},
            },
            {
                "type": "assistant",
                "sessionId": session_id,
                "uuid": "sub-assistant-1",
                "cwd": str(tmp_path / "workspace"),
                "message": {"role": "assistant", "content": [{"type": "text", "text": "子 agent 分支 AI 回复。"}]},
            },
        ],
    )
    env = _env(tmp_path, projects_root)

    scan = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(scan.stdout)
    assert payload["changed"] == 2
    assert payload["discovered"] == 2

    dests = [Path(item["dest"]) for item in payload["items"]]
    assert len(set(dests)) == 2
    parent_item = next(item for item in payload["items"] if item["source_path"] == str(parent_path))
    subagent_item = next(item for item in payload["items"] if item["source_path"] == str(subagent_path))
    assert parent_item["session_id"] == subagent_item["session_id"] == session_id
    assert parent_item["raw_artifact_id"] == session_id
    assert subagent_item["raw_artifact_id"].startswith(f"{session_id}__subagent__agent-a3053a9a5122ec4f3")

    parent_raw = Path(parent_item["dest"]).read_text(encoding="utf-8")
    subagent_raw = Path(subagent_item["dest"]).read_text(encoding="utf-8")
    assert "Claude Code CLI 的关键路径" in parent_raw
    assert "子 agent 分支 AI 回复" not in parent_raw
    assert "子 agent 分支 AI 回复" in subagent_raw

    subagent_meta = json.loads(Path(str(subagent_item["dest"]) + ".meta.json").read_text(encoding="utf-8"))
    assert subagent_meta["session_id"] == session_id
    assert subagent_meta["raw_artifact_id"] == subagent_item["raw_artifact_id"]


def test_claude_code_p2_extracts_native_user_assistant_records(tmp_path):
    projects_root, _, _ = _write_claude_code_session(tmp_path)
    env = _env(tmp_path, projects_root)

    scan = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    dest = Path(json.loads(scan.stdout)["items"][0]["dest"])

    extract = subprocess.run(
        [sys.executable, str(SRC / "p2_extract.py"), "--incremental", str(dest)],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    assert "case=1" in extract.stdout

    case_path = tmp_path / "memcore" / "zhiyi" / "case_memory" / "case_memory.jsonl"
    record = json.loads(case_path.read_text(encoding="utf-8").splitlines()[0])
    refs = json.loads(record["source_refs"])
    assert record["source_system"] == "claude_code_cli"
    assert refs["source_system"] == "claude_code_cli"
    assert refs["native_artifact_format"] == "claude_code_session_jsonl"
    assert refs["raw_archive_layout"] == "computer_first"
    assert refs["byte_offsets"]


def test_claude_code_user_only_session_is_not_current_window_memory(tmp_path):
    projects_root, _, _ = _write_claude_code_session(tmp_path, assistant=False)
    env = _env(tmp_path, projects_root)

    scan = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(scan.stdout)
    assert payload["changed"] == 1
    assert payload["window_bindings_registered"] == 0
    assert payload["window_binding_skipped"] == 1
    assert payload["items"][0]["complete_conversation_candidate"] is False
    assert not (tmp_path / "memcore" / "config" / "window_binding_registry.json").exists()


def test_claude_code_metadata_updated_rebuilds_missing_manifest_and_backfills_main_river_fields(tmp_path):
    projects_root, _, _ = _write_claude_code_session(tmp_path)
    env = _env(tmp_path, projects_root)

    first_scan = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    dest = Path(json.loads(first_scan.stdout)["items"][0]["dest"])
    dialogue_path = Path(str(dest) + ".canonical_dialogue.jsonl")
    manifest_path = Path(str(dest) + ".forensic_runtime.json")
    meta_path = Path(str(dest) + ".meta.json")
    assert len(dialogue_path.read_text(encoding="utf-8").splitlines()) == 2

    manifest_path.unlink()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for key in (
        "main_river_storage",
        "forensic_runtime_storage",
        "canonical_dialogue_path",
        "forensic_runtime_manifest_path",
    ):
        meta.pop(key, None)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    second_scan = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(second_scan.stdout)
    item = payload["items"][0]
    refreshed_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    assert payload["changed"] == 1
    assert item["status"].startswith("metadata_updated(")
    assert len(dialogue_path.read_text(encoding="utf-8").splitlines()) == 2
    assert refreshed_meta["main_river_storage"] == "canonical_dialogue"
    assert refreshed_meta["forensic_runtime_storage"] == "full_raw_archive_plus_manifest"
    assert refreshed_meta["canonical_dialogue_path"] == str(dialogue_path)
    assert refreshed_meta["forensic_runtime_manifest_path"] == str(manifest_path)


def test_claude_desktop_local_agent_metadata_links_without_claiming_desktop_body(tmp_path):
    projects_root, _, session_id = _write_claude_code_session(tmp_path)
    desktop_root = tmp_path / "claude-code-sessions"
    runtime_root = _write_desktop_managed_runtime(tmp_path)
    _write_desktop_code_session_metadata(tmp_path, desktop_root, session_id)
    env = _env_with_desktop(tmp_path, projects_root, desktop_root, runtime_root)

    scan = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(scan.stdout)
    item = payload["items"][0]
    assert item["desktop_session_metadata_detected"] is True
    assert item["desktop_session_id"] == "local_desktop-session-1"
    assert item["thread_name"] == "Desktop shell title"

    dest = Path(item["dest"])
    meta = json.loads(Path(str(dest) + ".meta.json").read_text(encoding="utf-8"))
    assert meta["source_system"] == "claude_code_cli"
    assert meta["storage_owner"] == "claude_code_session_store"
    assert meta["body_storage_owner"] == "claude_code_session_store"
    assert meta["conversation_origin"] == "claude_desktop_managed_claude_code_session"
    assert meta["runtime_consumer"] == "claude_desktop_managed_claude_code_runtime"
    assert meta["desktop_installer_includes_cli"] is False
    assert meta["cli_installation_boundary"] == "claude_cli_is_independent_and_may_be_installed_after_claude_desktop"
    assert meta["desktop_cli_relationship"] == "user_installed_cli_independent_but_desktop_may_manage_local_agent_runtime"
    assert meta["user_installed_cli_independent"] is True
    assert meta["user_installed_path_cli_required"] is False
    assert meta["desktop_managed_runtime_detected"] is True
    assert meta["desktop_managed_runtime_owner"] == "claude_desktop"
    assert meta["desktop_managed_runtime_policy"] == "desktop_managed_runtime_is_distinct_from_user_installed_path_cli"
    assert meta["desktop_managed_runtime_is_user_installed_cli"] is False
    assert meta["desktop_shell_owner"] == "claude_desktop"
    assert meta["desktop_metadata_owner"] == "claude_desktop"
    assert meta["desktop_session_id"] == "local_desktop-session-1"
    assert meta["desktop_metadata_policy"] == "metadata_only_links_desktop_session_to_claude_code_jsonl_body"
    assert meta["co_source_systems"] == ["claude_desktop"]
    assert "Desktop shell title" not in dest.read_text(encoding="utf-8")

    status = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--status"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    status_payload = json.loads(status.stdout)
    assert status_payload["desktop_session_metadata_count"] == 1
    assert status_payload["desktop_installer_includes_cli"] is False
    assert status_payload["cli_installation_boundary"] == "claude_cli_is_independent_and_may_be_installed_after_claude_desktop"
    assert status_payload["desktop_cli_relationship"] == "user_installed_cli_independent_but_desktop_may_manage_local_agent_runtime"
    assert status_payload["desktop_metadata_policy"] == "metadata_only_links_desktop_session_to_claude_code_jsonl_body"
    assert status_payload["desktop_metadata_is_conversation_body"] is False
    assert status_payload["coverage_boundary"] == "captures_claude_code_session_jsonl_records_including_claude_desktop_entrypoint_and_desktop_managed_local_agent_metadata_not_ordinary_desktop_browser_store_history"
    assert status_payload["desktop_managed_runtime_detected"] is True
    assert status_payload["desktop_managed_runtime_owner"] == "claude_desktop"
    assert status_payload["desktop_managed_runtime_is_user_installed_cli"] is False
    latest = status_payload["latest"][0]
    assert latest["desktop_installer_includes_cli"] is False
    assert latest["cli_installation_boundary"] == "claude_cli_is_independent_and_may_be_installed_after_claude_desktop"
    assert latest["desktop_metadata_policy"] == "metadata_only_links_desktop_session_to_claude_code_jsonl_body"
    assert latest["storage_owner"] == "claude_code_session_store"
    assert latest["body_storage_owner"] == "claude_code_session_store"
    assert latest["conversation_origin"] == "claude_desktop_managed_claude_code_session"
    assert latest["runtime_consumer"] == "claude_desktop_managed_claude_code_runtime"
    assert latest["desktop_managed_runtime_detected"] is True
    assert latest["desktop_managed_runtime_owner"] == "claude_desktop"
    assert latest["desktop_managed_runtime_is_user_installed_cli"] is False
    assert latest["desktop_session_metadata"]["metadata_only"] is True
    assert latest["desktop_session_metadata"]["message_text_returned"] is False
    assert latest["desktop_session_metadata"]["raw_excerpt_returned"] is False
    assert latest["desktop_session_metadata"]["desktop_installer_includes_cli"] is False
    assert latest["desktop_session_metadata"]["cli_installation_boundary"] == "claude_cli_is_independent_and_may_be_installed_after_claude_desktop"


def test_windows_desktop_managed_runtime_keeps_path_cli_separate(tmp_path):
    projects_root = tmp_path / "Users" / "tester" / ".claude" / "projects"
    project_dir = projects_root / "C--Users-tester-Desktop-workspace"
    project_dir.mkdir(parents=True)
    session_id = "e0a3f9f1-8654-4627-8a48-4421797b9e44"
    session_path = project_dir / f"{session_id}.jsonl"
    _append_jsonl(
        session_path,
        [
            {
                "type": "user",
                "sessionId": session_id,
                "uuid": "user-191",
                "cwd": "C:\\Users\\tester\\Desktop\\workspace",
                "timestamp": "2026-06-05T16:45:18.182Z",
                "message": {"role": "user", "content": "Windows fixture Claude Desktop 真实任务。"},
            },
            {
                "type": "assistant",
                "sessionId": session_id,
                "uuid": "assistant-191",
                "parentUuid": "user-191",
                "cwd": "C:\\Users\\tester\\Desktop\\workspace",
                "timestamp": "2026-06-05T17:06:26.946Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "已完成 Windows 优化审查。"}],
                },
            },
        ],
    )
    desktop_sessions = tmp_path / "Users" / "tester" / "AppData" / "Roaming" / "Claude" / "claude-code-sessions"
    meta_dir = desktop_sessions / "a66096d1-e115-4d19-8abc-80b91c9469c0" / "add010bc-5ead-4b92-b016-38d68a565d76"
    meta_dir.mkdir(parents=True)
    (meta_dir / "local_85a87d88-1c08-45a4-bca8-46193ee4ec7e.json").write_text(
        json.dumps(
            {
                "sessionId": "local_85a87d88-1c08-45a4-bca8-46193ee4ec7e",
                "cliSessionId": session_id,
                "cwd": "C:\\Users\\tester\\Desktop\\workspace",
                "originCwd": "C:\\Users\\tester\\Desktop\\workspace",
                "title": "Windows optimization review",
                "model": "claude-opus-4-8",
                "completedTurns": 1,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    runtime_root = tmp_path / "Users" / "tester" / "AppData" / "Roaming" / "Claude" / "claude-code"
    (runtime_root / "2.1.161").mkdir(parents=True)
    (runtime_root / "2.1.161" / "claude.exe").write_text("desktop managed runtime", encoding="utf-8")
    env = _env_with_desktop(tmp_path, projects_root, desktop_sessions, runtime_root)
    env["MEMCORE_PLATFORM"] = "win32"
    env["APPDATA"] = str(tmp_path / "Users" / "tester" / "AppData" / "Roaming")
    env["USERPROFILE"] = str(tmp_path / "Users" / "tester")

    scan = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(scan.stdout)
    item = payload["items"][0]

    assert item["desktop_session_metadata_detected"] is True
    assert item["desktop_session_id"] == "local_85a87d88-1c08-45a4-bca8-46193ee4ec7e"
    assert item["thread_name"] == "Windows optimization review"
    assert item["runtime_consumer"] == "claude_desktop_managed_claude_code_runtime"
    assert item["conversation_origin"] == "claude_desktop_managed_claude_code_session"
    assert item["body_storage_owner"] == "claude_code_session_store"
    assert item["desktop_managed_runtime_detected"] is True
    assert item["desktop_managed_runtime_is_user_installed_cli"] is False

    dest = Path(item["dest"])
    raw = dest.read_text(encoding="utf-8")
    assert "Windows fixture Claude Desktop 真实任务" in raw
    assert "已完成 Windows 优化审查" in raw
    assert "Windows optimization review" not in raw
    meta = json.loads(Path(str(dest) + ".meta.json").read_text(encoding="utf-8"))
    assert meta["source_path"].endswith("e0a3f9f1-8654-4627-8a48-4421797b9e44.jsonl")
    assert meta["desktop_metadata_path"].endswith("local_85a87d88-1c08-45a4-bca8-46193ee4ec7e.json")
    assert meta["desktop_managed_runtime_owner"] == "claude_desktop"
    assert meta["desktop_managed_runtime_policy"] == "desktop_managed_runtime_is_distinct_from_user_installed_path_cli"
    assert meta["desktop_managed_runtime_is_user_installed_cli"] is False


def test_claude_desktop_entrypoint_jsonl_is_full_body_even_without_metadata(tmp_path):
    projects_root, _, session_id = _write_claude_desktop_entrypoint_session(tmp_path)
    desktop_root = tmp_path / "missing-claude-code-sessions"
    env = _env_with_desktop(tmp_path, projects_root, desktop_root)

    scan = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(scan.stdout)
    item = payload["items"][0]

    assert item["session_id"] == session_id
    assert item["desktop_session_metadata_detected"] is False
    assert item["entrypoint"] == "claude-desktop"
    assert item["entrypoint_counts"] == {"claude-desktop": 2}
    assert item["desktop_entrypoint_detected"] is True
    assert item["desktop_entrypoint_policy"] == "entrypoint_marks_claude_desktop_shell_but_body_is_claude_code_jsonl"
    assert item["conversation_origin"] == "claude_desktop_entrypoint_claude_code_session"
    assert item["runtime_consumer"] == "claude_desktop_managed_claude_code_runtime"
    assert item["body_storage_owner"] == "claude_code_session_store"
    assert item["desktop_metadata_is_conversation_body"] is False
    assert item["co_source_systems"] == ["claude_desktop"]
    assert item["complete_conversation_candidate"] is True

    dest = Path(item["dest"])
    raw = dest.read_text(encoding="utf-8")
    assert "请直接调用 time-library" in raw
    assert "召回汇报" in raw
    meta = json.loads(Path(str(dest) + ".meta.json").read_text(encoding="utf-8"))
    assert meta["conversation_origin"] == "claude_desktop_entrypoint_claude_code_session"
    assert meta["runtime_consumer"] == "claude_desktop_managed_claude_code_runtime"
    assert meta["body_storage_owner"] == "claude_code_session_store"
    assert meta["desktop_entrypoint_detected"] is True
    assert meta["desktop_shell_owner"] == "claude_desktop"
    assert meta["desktop_metadata_is_conversation_body"] is False
    assert meta["co_source_systems"] == ["claude_desktop"]

    status = subprocess.run(
        [sys.executable, str(SRC / "claude_code_local_connector.py"), "--status"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    status_payload = json.loads(status.stdout)
    assert status_payload["desktop_entrypoint_session_count"] == 1
    assert status_payload["desktop_entrypoint_complete_conversation_count"] == 1
    assert status_payload["desktop_shell_owner"] == "claude_desktop"
    assert status_payload["coverage_boundary"] == "captures_claude_code_session_jsonl_records_including_claude_desktop_entrypoint_and_desktop_managed_local_agent_metadata_not_ordinary_desktop_browser_store_history"
    latest = status_payload["latest"][0]
    assert latest["desktop_entrypoint_detected"] is True
    assert latest["conversation_origin"] == "claude_desktop_entrypoint_claude_code_session"
    assert latest["co_source_systems"] == ["claude_desktop"]
