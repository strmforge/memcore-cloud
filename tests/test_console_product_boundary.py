import importlib
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _reload_p6(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    for name in [
        "config_loader",
        "src.config_loader",
        "p6_console",
        "src.p6_console",
        "p6_experience_governance",
        "src.p6_experience_governance",
    ]:
        sys.modules.pop(name, None)
    return importlib.import_module("p6_console")


def test_console_i18n_keeps_zh_cn_labels_chinese(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    zh = p6.I18N["zh-CN"]
    assert zh["nav.settings"] == "设置"
    assert zh["nav.update"] == "系统更新"
    assert zh["nav.sourceSystems"] == "数据源"
    assert zh["runtime.refresh"] == "刷新"


def test_p6_pid_file_owner_cleanup(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    pid_path = tmp_path / "runtime" / "p6-console.pid"
    monkeypatch.setattr(p6, "P6_PID_PATH", pid_path)

    assert p6._write_p6_pid_file() is True

    assert pid_path.read_text(encoding="ascii") == f"{os.getpid()}\n"
    p6._clear_p6_pid_file()
    assert not pid_path.exists()


def test_p6_pid_write_failure_does_not_become_service_failure(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    pid_path = tmp_path / "runtime" / "p6-console.pid"
    monkeypatch.setattr(p6, "P6_PID_PATH", pid_path)
    monkeypatch.setattr(
        p6._console_runtime_profile.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("read-only runtime")),
    )

    assert p6._write_p6_pid_file() is False
    assert not pid_path.exists()


def test_p6_pid_cleanup_preserves_new_process_owner(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    pid_path = tmp_path / "runtime" / "p6-console.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("999999\n", encoding="ascii")
    monkeypatch.setattr(p6, "P6_PID_PATH", pid_path)

    p6._clear_p6_pid_file()

    assert pid_path.read_text(encoding="ascii") == "999999\n"


def test_console_user_visible_text_has_no_internal_phase_codes(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    visible_payload = json.dumps(p6.I18N, ensure_ascii=False) + p6.HTML_TEMPLATE

    assert "".join(["P9", "-Audit", "-Fix-1"]) not in visible_payload
    assert "".join(["Audit", "-Fix"]) not in visible_payload
    assert p6.I18N["zh-CN"]["dashboard.sealed"] == "本机服务就绪"
    assert p6.I18N["en-US"]["dashboard.sealed"] == "Local Service Ready"


def test_console_status_api_uses_public_phase_name(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    monkeypatch.setattr(p6, "get_watcher_status", lambda: True)
    monkeypatch.setattr(p6, "get_raw_stats", lambda: {"sessions": 0})
    monkeypatch.setattr(p6, "get_zhiyi_stats", lambda: {"total": 0})

    overview = p6._console_status.m3_get_overview(
        get_watcher_status_fn=lambda: True,
        get_raw_stats_fn=lambda: {"sessions": 0},
        get_zhiyi_stats_fn=lambda: {"total": 0},
        get_service_ports_fn=lambda: {"p3recall": "up", "p4inject": "up"},
    )

    assert overview["status"] == "ok"
    assert overview["phase"] == "local-service-ready"
    assert "P9" not in json.dumps(overview, ensure_ascii=False)


def test_console_legacy_review_apis_hide_internal_phase_names(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    payload = {
        "risk_backlog": p6.m4_get_risk_backlog(),
        "next_decision": p6.m4_get_next_decision_summary(),
    }
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "".join(["P9", "-System"]) not in serialized
    assert "".join(["Audit", "-Fix"]) not in serialized
    assert payload["risk_backlog"]["evidence_status"] in {"measured", "not_measured"}
    assert payload["next_decision"]["status"] == "not_configured"
    assert payload["next_decision"]["pending_decisions"] == []
    assert payload["next_decision"]["current_phase"] == "unknown"


def test_console_legacy_risk_api_surfaces_measured_guardian_failures(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    from src import raw_record_guardian

    monkeypatch.setattr(
        raw_record_guardian,
        "build_guardian_status",
        lambda **_kwargs: {
            "ok": False,
            "summary": {
                "lost_raw_count": 2,
                "corrupt_record_count": 0,
                "lost_source_count": 1,
                "raw_attention_count": 2,
            },
        },
    )

    audit = p6.m3_get_audit_risks()
    assert audit["evidence_status"] == "measured"
    assert audit["audit1_pass"] is False
    assert {item["type"] for item in audit["risks"]} == {
        "lost_raw",
        "lost_source",
        "raw_attention",
    }

    backlog = p6.m4_get_risk_backlog()
    assert backlog["evidence_status"] == "measured"
    assert backlog["audit1_pass"] is False
    assert {item["id"] for item in backlog["risks"]} >= {"LOST-RAW", "LOST-SOURCE"}


def test_product_console_explains_preference_and_work_experience_in_both_languages():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert "偏好层负责理解，经验层负责落地" in html
    assert "知行合一" in html
    assert "The preference layer understands intent" in html
    assert "The work-experience layer turns source-backed work into reusable paths" in html
    assert "Knowing and doing as one" in html
    assert "经验不是技能库" in html
    assert "Experience is not a skill library" in html
    assert "Zhiyi understands intent" not in html
    assert "Xingce turns source-backed work into work experience" not in html
    assert "platform.rawCurrent" in html
    assert "archive-layout/audit" in html
    assert "理解某人的偏好" not in html
    assert "understanding a person" not in html


def test_product_console_final_canvas_pass_keeps_responsive_tracks_shrinkable():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")
    final_css = html.split("/* Canvas visual pass 5.1:", 1)[1].split("</style>", 1)[0]

    assert "grid-template-columns: minmax(0, 0.88fr) minmax(0, 0.86fr) minmax(0, 0.94fr);" in final_css
    assert "@media (max-width: 1499px)" in final_css
    assert '"report insight"' in final_css
    assert "@media (min-width: 1181px) and (max-width: 1380px)" in final_css
    mobile_css = final_css.split("@media (max-width: 1180px)", 1)[1]
    assert "grid-template-columns: minmax(0, 1fr);" in mobile_css
    assert "grid-template-areas: none;" in mobile_css


def test_product_console_overview_shows_detected_local_ai_tools_only():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert "/api/v1/platforms/discovery-dashboard" in html
    assert "function visibleLocalPlatformItem" in html
    assert "item.detected === true" in html
    assert "function visibleCurrentLocalPlatformItem" in html
    assert "freshness === 'active_recent' || freshness === 'warm'" in html
    assert "filter(visibleCurrentLocalPlatformItem)" in html
    assert "function runtimeLocalStatus" in html
    assert "Array.isArray(profile)" in html
    assert "entry.key === 'openclaw' || entry.key === 'hermes'" not in html
    assert "claude_code_cli" in html
    assert "claude_desktop" in html
    assert "productPlatformEntries(ss, runtime, discovery)" in html
    assert "platformDiscoveryCards(data.items || [], runtime)" in html
    assert "fetchJson('/api/v1/runtime/profile/instances')" in html
    overview_loader = html.split("async function loadOverview()", 1)[1].split("function productHealthRows", 1)[0]
    assert "/api/v1/runtime/profile')" not in overview_loader
    assert "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1" in overview_loader
    assert "healthIsOk(health) && guardianIsOk(guardian)" in overview_loader
    assert "state.overviewSnapshot" in overview_loader


def test_product_console_reading_room_uses_real_projection_and_unified_status_helpers():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert "fetchJson('/api/v1/reading-area/summary')" in html
    assert "function readingAreaProjectStages()" in html
    assert "function allReadingRoomStages()" in html
    assert "function prefCount(stats)" in html
    assert "function zhiyiObjectTotal(stats)" in html
    assert "function serviceStatusValues(health)" in html
    assert "values.length > 0 && values.every" in html
    assert "state.readingArea = data && data.ok ? data : {}" in html
    assert "const libraryP = loadReadingAreaSummary().catch(function(){ return {}; })" in html
    assert "{ id: 'errata', countKey: 'errata'" in html
    assert "const total = (stats.case_memory || 0) + (stats.error_memory || 0) + (stats.pref_memory || 0)" not in html
    assert "const zhiyiTotal = (zhiyi.case_memory || 0) + (zhiyi.error_memory || 0) + (zhiyi.pref_memory || 0)" not in html


def test_product_console_hides_discovery_strategy_terms():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    hidden_terms = [
        "泛发现",
        "平台字典",
        "GitHub Watchlist",
        "github_top100",
        "Known adapter",
        "Generic surface",
        "knownThinAdapter",
        "genericSurface",
        "generic_local_ai_surface",
        "mcp_config_detected",
        "inspect_authorized_connect_plan",
        "authorized-auto-connect",
        "collector_pending",
        "install_scan_only",
        "platform.catalog",
        "support_level",
        "catalog_level",
        "stars ",
    ]
    for term in hidden_terms:
        assert term not in html
    assert "可识别应用" not in html
    assert "可识别工具" in html
    assert "Recognized apps" not in html
    assert "Recognized tool" in html
    assert "Continuous sync" in html
    assert "持续同步" in html
    assert "Live tracking" in html
    assert "持续跟踪" in html
    assert "本机运行 · 可回源" in html
    assert "Local · Source-backed" in html
    assert "local-first" + " · " + "source-backed" not in html
    assert "Supported tool" not in html
    assert "Connectable app" not in html
    assert "Time Library" in html
    assert "/assets/time_library_emblem.png" in html
    assert "/assets/time_library_logo_zh.png" in html
    assert "/assets/time_library_logo_en.png" in html
    assert "Memcore Cloud" not in html


def test_product_console_personal_edition_four_page_structure_and_naming():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert "nav.overview': '今晨'" in html
    assert "nav.zhiyi': '馆藏'" in html
    assert "nav.platforms': '阅读室'" in html
    assert "nav.settings': '设置'" in html
    assert 'data-page="status"' not in html
    assert "readingRoom.title': '阅读室'" in html
    assert "whiteboard.title': '白板'" in html
    assert "多 agent 共享读书和协作的空间；里面挂着的进度流程图叫白板" in html
    assert 'id="project-intake-panel" hidden' in html
    assert "readingRoom.projectIntakeTitle': '添加项目'" in html
    assert "readingRoom.projectNameLabel': '项目名称'" in html
    assert "readingRoom.projectSourceLabel': '来源位置'" in html
    assert "readingRoom.projectDraftButton': '保存项目'" in html
    assert "readingRoom.projectRemove': '移除本机项目'" in html
    assert "renderReadingRoomProjects" in html
    assert "/api/v1/console/projects" in html
    assert "/api/v1/console/projects/delete" in html
    assert "removeProjectDraft" in html
    assert "data-project-remove" in html
    assert "/api/v1/console/state" in html
    assert "writeLocalList('timeLibrary.projectDrafts'" not in html
    assert "readLocalList('timeLibrary.projectDrafts'" not in html
    assert "saveProjectDraft" in html
    assert "whiteboard.empty': '白板还没有项目记录。'" in html
    assert "平台无关化" not in html
    assert "Project " + "Alpha" not in html
    assert 'data-project="orchestration_system"' not in html
    assert 'data-project="time_library"' not in html
    assert "待裁" + "只显示" + "为状态节点，不提供后台裁决按钮" not in html
    assert "background arbitration button" not in html


def test_product_console_does_not_ship_fake_home_tasks_or_private_project_presets():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    forbidden = [
        "示例：项目复盘记忆检索方案",
        "整理：example compliance notes 合规要点笔记",
        "阅读：example technical report 技术报告",
        "备份：本地数据快照",
        "已完成 12 项",
        "taskReview",
        "taskDistill",
        "taskReading",
        "taskBackup",
        "doneTasks",
        "示例条款解析",
        "示例报告要点",
        "从短期对话到长期画像",
        "向量数据库选型对比",
        "命中率" + "示例%",
        "已用" + "示例容量",
        "example" + "-embed-model",
        "跨机接六道",
        "Sixdao cross-machine route",
        "L4 自主环待真新料触发",
    ]
    for term in forbidden:
        assert term not in html

    assert 'id="overview-task-add-btn"' in html
    assert 'id="overview-task-save-btn"' in html
    assert 'id="overview-task-view-btn"' not in html
    assert "overview.viewTasks" not in html
    assert "renderOverviewTasks" in html
    assert "/api/v1/console/tasks" in html
    assert "/api/v1/console/tasks/delete" in html
    assert "settings.vectorPreparingRuntime" in html
    assert "vectorAssets.state === 'installing_dependencies'" in html
    assert "settings.vectorDisabled" in html
    assert "payload.vector_recall_enabled && vectorNote" in html
    assert html.count("await loadModelOptions();") >= 2
    model_save_handler = html.split("document.getElementById('save-model-btn').addEventListener", 1)[1].split(
        "document.getElementById('model-apply-gate-btn').addEventListener", 1
    )[0]
    assert "const vectorNote = document.getElementById('vector-bge-note');" in model_save_handler
    task_renderer = html.split("function renderOverviewTasks()", 1)[1].split("function setOverviewTaskComposerVisible", 1)[0]
    assert "refreshOverviewKeyFindings()" in task_renderer
    task_save = html.split("async function saveOverviewTaskDraft()", 1)[1].split("function renderMorningBrief", 1)[0]
    assert "refreshOverviewKeyFindings()" in task_save
    assert "writeLocalList('timeLibrary.taskDrafts'" not in html
    assert "readLocalList('timeLibrary.taskDrafts'" not in html
    assert "overview.emptyTasks': '还没有本机事项" in html
    assert "overview.localTools': '本机工具'" in html


def test_product_console_home_health_includes_guardian_and_never_renders_message_minus_one():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert "你的本机记忆库状态如下。" in html
    assert "所有服务运行正常" not in html
    assert "local services are running normally" not in html
    assert "text === 'bad'" in html
    assert "text === 'warn'" in html
    assert "function lostSourceTriage(summary)" in html
    assert "function guardianIsOk(guardian)" in html
    assert "Number(summary.lost_raw_count || 0) === 0" in html
    assert "triage.unrecoverable === 0" in html
    guardian_check = html.split("function guardianIsOk(guardian)", 1)[1].split("function guardianSummaryText", 1)[0]
    assert "lost_source_count || 0) === 0" not in guardian_check
    assert "function rawMessageCountText(raw)" in html
    health_rows = html.split("function productHealthRows(health, guardian, raw, zhiyi)", 1)[1].split("async function loadZhiyi", 1)[0]
    assert "const documentCount = rawMessageCountText(raw)" in health_rows
    assert "guardianSummaryText(guardian)" in health_rows
    assert "guardianIsOk(guardian) ? 'active' : 'pending'" in health_rows
    assert "raw.messages || raw.total_messages || 0" not in health_rows


def test_product_console_ui_rebuild_keeps_logo_and_core_interactions():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert '<img class="brand-mark" src="/assets/time_library_emblem.png"' in html
    assert '<img class="brand-mark" data-brand-logo' not in html
    assert 'data-logo-zh="/assets/time_library_logo_zh_sidebar.png"' in html
    assert "/assets/time_library_logo_zh_sidebar.png" in html
    assert 'data-logo-en="/assets/time_library_logo_en_sidebar.png"' in html
    assert "/assets/time_library_logo_en_sidebar.png" in html
    assert "time_library_logo_zh.png" in html
    assert "time_library_logo_en.png" in html
    assert "time-library-logo" not in html
    assert "settings.modelCenter': '模型与召回'" in html
    assert "settings.currentMainModel': '当前分析模型'" in html
    assert "settings.platformModelUnchanged': '平台模型不变'" in html
    assert "settings.vectorOptional': '向量召回 可选，默认 FTS5+BM25'" in html
    assert "settings.currentVectorModel': '当前向量模型'" in html
    assert 'id="vector-model-status"' in html
    settings_header = html.split('<div class="settings-header">', 1)[1].split('<div class="settings-grid">', 1)[0]
    model_control = html.split('<div class="model-control">', 1)[1].split('<div class="current-model-strip">', 1)[0]
    assert 'id="reload-models-btn"' not in settings_header
    assert 'id="reload-models-btn"' in model_control
    assert '<div class="field-head">' in model_control
    assert "document.getElementById('model-runtime-preflight-visible-btn')" in html
    visible_test_handler = html.split("document.getElementById('model-runtime-preflight-visible-btn').addEventListener('click'", 1)[1].split("document.getElementById('model-runtime-apply-gate-btn')", 1)[0]
    assert "/api/v1/zhiyi/model-connection/smoke" in visible_test_handler
    assert "const payload = zhiyiModelPayload()" in visible_test_handler
    assert "confirm_live_model_call: true" in visible_test_handler
    assert "confirm_no_platform_config_write: true" in visible_test_handler
    assert "model.runtimeLiveRunning" in visible_test_handler
    assert "/api/v1/zhiyi/runtime-adapter/dry-run" not in visible_test_handler
    assert "model-runtime-preflight-btn" not in visible_test_handler
    assert 'id="zhiyi-model-api-key-value" type="password"' in html
    assert 'id="toggle-api-key-btn"' in html
    assert "settings.apiKeyPlaceholder" in html
    assert "settings.showKey" in html
    assert "settings.hideKey" in html
    assert "resetZhiyiApiKeyField" in html
    assert 'id="zhiyi-model-api-key-env"' in html
    assert "option_category: option.category || ''" in html
    assert "Fall back when the browser denies clipboard permission" in html
    assert "agentInstall.copyFailed" in html
    assert "status.textContent = t('agentInstall.copyFailed')" in html
    assert '<label class="switch-row"><input id="vector-bge-toggle" type="checkbox" role="switch">' in html
    assert '<span class="switch-slider" aria-hidden="true"></span>' in html
    assert 'id="vector-bge-note" data-i18n="settings.vectorSavedNote"' in html
    assert "const vectorRecallEnabled = !!(vectorToggle && vectorToggle.checked)" in html
    assert "vector_recall_enabled: vectorRecallEnabled" in html
    assert "vector_bge_m3_enabled: vectorBgeEnabled" not in html
    assert "const currentVectorModel = data.current_vector_model || {}" in html
    assert "const vectorPreference = data.vector_recall_preference || userDefault.vector_recall_preference || {}" in html
    assert "const vectorAssets = data.vector_asset_status || {}" in html
    assert "/api/v1/zhiyi/vector-assets/status" in html
    assert "settings.vectorDownloading" in html
    assert "settings.vectorBuilding" in html
    assert "settings.vectorFailed" in html
    assert "vectorToggle.checked = !!vectorPreference.enabled" in html
    assert 'id="vector-bge-toggle" type="checkbox"><span data-i18n="settings.vectorOptional"' not in html
    assert "zhiyi.recycleBin': '回收站'" in html
    assert "已放入回收站，原始记忆保留。" in html
    assert "renderShelfGrid" in html
    assert "renderWhiteboardTimeline" in html
    assert "loadReadingRoom" in html


def test_library_page_splits_search_note_and_single_trash_entry():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert html.count('id="recycle-bin-btn"') == 1
    assert "experience-recycle-inline" not in html
    header_block = html.split('<div class="library-header">', 1)[1].split('<section class="desk-card library-note-entry">', 1)[0]
    assert "library-search-input" not in header_block
    assert "library-note-btn" not in header_block
    assert "library-note-entry" in html
    assert "library-card-actions" in html
    assert "document.getElementById('recycle-bin-btn').addEventListener('click', openRecycleBinModal)" in html
    assert "library-note-composer" in html
    assert "openLibraryNoteComposer" in html
    assert "document.getElementById('library-note-btn').addEventListener('click', openLibraryNoteComposer)" in html
    assert "filterLibraryExperienceCards" in html
    assert "/api/v1/library/search?q=" in html
    assert "p3_fts5_plus_catalog" not in html
    search_function = html.split("async function filterLibraryExperienceCards(query)", 1)[1].split("function zhiyiSummaryHtml", 1)[0]
    assert "fetchJson('/api/v1/library/search?q='" in search_function
    assert "querySelectorAll('.experience-card')" not in search_function
    assert "document.getElementById('library-search-input').addEventListener('input'" in html
    assert 'id="library-note-save-btn"' in html
    assert "/api/v1/console/notes" in html
    assert "/api/v1/console/notes/delete" in html
    assert "library.noteNoWriteStatus': '未保存；保存后只进入本机控制台。'" in html
    assert "zhiyi.recycleAction': '回收'" in html
    assert "pendingRecycleExpId" in html
    assert "zhiyi.recycleConfirm" in html
    recycle_function = html.split("async function recycleExperience(expId)", 1)[1].split("async function restoreExperience", 1)[0]
    assert "state.pendingRecycleExpId !== expId" in recycle_function
    assert "postJson('/api/v1/zhiyi/experiences/'" in recycle_function
    assert recycle_function.index("state.pendingRecycleExpId !== expId") < recycle_function.index("postJson('/api/v1/zhiyi/experiences/'")
    assert "⌫" not in html


def test_product_console_does_not_show_internal_direction_audit():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    hidden_internal_terms = [
        "方向完成度",
        "收口审计",
        "internal_direction_audit",
        "memcore_internal_direction_audit",
        "memcore_subtractive_strategy",
        "core_keep",
        "subcapability_constrain",
        "pause_expansion",
        "protect_raw_records_and_continue_with_evidence_first",
        "maintainer_only_not_product_ui",
        "未产品化",
        "底座完成",
    ]
    for term in hidden_internal_terms:
        assert term not in html


def test_product_console_surfaces_record_guardian_without_auto_write():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert "五大工作台" in html
    assert "Five Workbenches" in html
    assert "tiandao-workbenches-panel" in html
    assert "renderTiandaoWorkbenchesBlock" in html
    assert "/api/v1/tiandao/workbenches/dashboard" in html
    assert "第二大脑" in html
    assert "Second Brain" in html
    assert "平台守护" in html
    assert "Platform Guard" in html
    assert "经验治理" in html
    assert "Experience Governance" in html
    assert "Hermes 观察" in html
    assert "Hermes Observatory" in html
    assert "只读聚合，不写 raw、不写记忆、不改平台配置" in html
    assert "Read-only aggregation: no raw, memory, or platform config writes" in html
    assert "记录守护" in html
    assert "Record Guard" in html
    assert "记录医生" in html
    assert "Record Doctor" in html
    assert "开工前检查" in html
    assert "Preflight Check" in html
    assert "preflight-doctor-panel" in html
    assert "renderPreflightDoctorPanel" in html
    assert "preflight-smoke-btn" in html
    assert "preflight-full-btn" in html
    assert "preflight.sourceBacked" in html
    assert "preflight.rawTrace" in html
    assert "preflight.answerDebug" in html
    assert "preflight.modelReady" in html
    assert "preflight.evidenceAuthority" in html
    assert "raw_source_refs" in html
    assert "/api/v1/preflight-doctor?live_work_preflight_smoke_samples=3&canonical_window_id=codex-current" in html
    assert "diagnostic_profile=full" in html
    assert "runPreflightDoctor('smoke')" in html
    assert "runPreflightDoctor('full')" in html
    assert "record-doctor-panel" in html
    assert "renderRecordDoctorBlock" in html
    assert "/api/v1/records/doctor?limit=80&mode=fast" in html
    assert "馆藏可信自检" in html
    assert "Library Trust Check" in html
    assert "library-trust-panel" in html
    assert "renderLibraryTrustBlock" in html
    assert "const dashboardReport = report || {}" in html
    assert "libraryTrustDemoPayload" not in html
    assert "library.rawShelf" in html
    assert "library.zhiyiShelf" in html
    assert "library.xingceShelf" in html
    assert "library.toolbookShelf" in html
    assert "library.errataShelf" in html
    assert "library.sourcePath" in html
    assert "/api/v1/zhixing/library-trust-dashboard?limit=12" in html
    assert "ZX-ZHIYI-STATUS-DEMO" not in html
    assert "ZX-XINGCE-STATUS-DEMO" not in html
    assert "/api/v1/zhixing/library-index-projection/dry-run" not in html
    assert "活性书签" in html
    assert "Active bookmarks" in html
    assert "经验履历" in html
    assert "Experience history" in html
    assert "经验进化候选" in html
    assert "Experience candidates" in html
    assert "只读候选，等待复核，不自动采纳" in html
    assert "Review-only candidates; nothing is auto-adopted" in html
    assert "复核下一步" in html
    assert "Review next steps" in html
    assert "dashboardReport.experience_review_actions" in html
    assert "仅生成复核意图预览，不改变候选状态" in html
    assert "Intent preview only; candidate status is unchanged" in html
    assert "复核队列" in html
    assert "Review queue" in html
    assert "只读分拣候选，不改变状态，不自动采纳" in html
    assert "Read-only candidate triage" in html
    assert "dashboardReport.experience_review_queue" in html
    assert "验证报告" in html
    assert "Validation report" in html
    assert "采纳前只读证据报告，确认 replay、履历和来源，不写入经验" in html
    assert "Read-only pre-apply evidence report" in html
    assert "dashboardReport.experience_validation_report" in html
    assert "验证回执" in html
    assert "Validation receipts" in html
    assert "只读回执预览，不写入验证结果，也不改变候选状态" in html
    assert "Read-only receipt preview; no validation result is written and candidate status is unchanged" in html
    assert "dashboardReport.experience_validation_receipt_schema" in html
    assert "采纳门禁" in html
    assert "Apply gate" in html
    assert "只读门禁预览，ready 也不代表已经采纳" in html
    assert "ready still does not mean adopted" in html
    assert "dashboardReport.experience_review_apply_gate" in html
    assert "回执与回滚" in html
    assert "Receipts and rollback" in html
    assert "只读格式预览，不写入经验，也不落盘回执" in html
    assert "no experience or receipt is written" in html
    assert "dashboardReport.experience_apply_receipt_schema" in html
    assert "采纳包" in html
    assert "Apply package" in html
    assert "最终只读预览包，ready 也不代表已经采纳" in html
    assert "Final read-only preview package; ready still does not mean adopted" in html
    assert "dashboardReport.experience_apply_package" in html
    assert "链路总览" in html
    assert "Flow overview" in html
    assert "内部只读路线图，集中列出经验采纳链路顺序和禁止事项" in html
    assert "Internal read-only route map for experience apply order and forbidden actions" in html
    assert "dashboardReport.experience_flow_overview" in html
    assert "只读自检，不写 raw、不写记忆、不写注记文件" in html
    assert "no raw, memory, or note-file writes" in html
    assert "记录链路" in html
    assert "Record Chain" in html
    assert "record-chain-panel" in html
    assert "record-chain-timeline" in html
    assert "renderRecordChainTimelineBlock" in html
    assert "/api/v1/records/timeline?limit=12&mode=fast" in html
    assert "记忆与经验" in html
    assert "Memory and experience" in html
    assert "not a memory wall" in html
    assert "record-guardian-panel" in html
    assert "record-backfill-btn" in html
    assert "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1" in html
    assert "/api/v1/records/canonical-index?limit=12" in html
    assert "/api/v1/records/guardian/index" not in html
    assert "/api/v1/records/guardian/backfill" in html
    assert "runRecordBackfill" in html
    assert "renderRecordGuardianBlock" in html
    assert "renderCanonicalIndexBlock" in html
    assert "initialPageFromHash" in html
    assert "VALID_PAGES" in html
    assert "window.addEventListener('hashchange'" in html
    assert "history.replaceState(null, '', nextHash)" in html
    assert "switchPage(state.page);" in html
    assert "applyLanguage();\nloadCurrentPage();" not in html
    assert "if (!report || !report.summary)" in html
    assert "if (!report || !report.ok)" not in html
    assert "raw_not_current_count" in html
    assert "raw_attention_count" in html
    assert "raw_lagging_or_missing_count" in html
    assert "origin_event_count" in html
    assert "lost_source_count" in html
    assert "lost_source_recoverable_count" in html
    assert "lost_source_unrecoverable_count" in html
    assert "lost_source_not_measured_count" in html
    assert "record.actionRetainedRaw" in html
    assert "record.actionMeasureRecoverability" in html
    assert "item.recoverable_from_raw === true" in html
    assert "supported && (item.backfill_recommended || issueKind === 'lost_raw')" in html
    assert "lost_raw_count" in html
    assert "时间起源" in html
    assert "遗失源" in html
    assert "遗失 raw" in html
    assert "backfill_recommended_count" in html
    assert "raw_catching_up_count" in html
    assert "max_raw_lag_bytes" in html
    assert "max_raw_lag_milliseconds" in html
    assert "claude_desktop_evidence" in html
    assert "claude-desktop-evidence-grid" in html
    assert "Claude Desktop 证据" in html
    assert "Claude Desktop evidence" in html
    assert "请求线索" in html
    assert "Request clue" in html
    assert "所有会话底座" in html
    assert "All-session base" in html
    assert "canonical_index" in html
    assert "canonical-index-grid" in html
    assert "canonical-index-messages" in html
    assert "从记录索引读取所有会话与消息，不触发回填。" in html
    assert "without triggering backfill" in html
    assert "raw 可回源" in html
    assert "Raw available" in html
    assert "记录证据明细" in html
    assert "Record evidence detail" in html
    assert "record-lost-details" in html
    assert "renderRecordIssueDetails" in html
    assert "recordIssueKind" in html
    assert "record-diagnostic" in html
    assert "diagnostic-grid" in html
    assert "record-platform-backfill-btn" in html
    assert "runRecordPlatformBackfill" in html
    assert "bindRecordGuardianActions" in html
    assert "source_systems: [sourceSystem]" in html
    assert "claude_desktop" in html
    assert "回填此平台" in html
    assert "Backfill this platform" in html
    assert "诊断" in html
    assert "Diagnostics" in html
    assert "record.recoverable" in html
    assert "可从 raw 救回" in html
    assert "Recoverable from raw" in html
    assert "不自动扫描写库" in html
    assert "does not auto-scan or write the index" in html
    assert "local_relay" not in html.lower()
    assert "Backfill is an explicit action" in html
    assert "hooks / MCP / REST" not in html
    assert "capability matrix" not in html.lower()


def test_product_console_keeps_model_settings_inside_main_model_panel():
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert "分析模型" in html
    assert "Analysis Model" in html
    assert "保存偏好" in html
    assert "Save preference" in html
    assert "知意模型" not in html
    assert "Zhiyi Model" not in html
    assert "zhiyi-model-provider" in html
    assert "zhiyi-model-provider-id" in html
    assert "zhiyi-model-name" in html
    assert "zhiyi-model-base-url" in html
    assert "zhiyi-model-api-key-env" in html
    assert 'id="zhiyi-model-api-key-value" type="password"' in html
    assert 'id="toggle-api-key-btn"' in html
    assert "settings.showKey" in html
    assert "settings.hideKey" in html
    assert "payload.api_key_value = apiKeyValue" in html
    assert "changedFromOption ? '' : (option.credential_ref || '')" in html
    assert "本机 loopback 模型连接测试可留空" in html
    assert "Local loopback model connection tests can leave this blank" in html
    assert "MEMCORE_ZHIYI_API_KEY" in html
    assert "本机工具识别模型" not in html
    assert "Local Tool Recognition Model" not in html
    assert "recognition-model" not in html
    assert "settings.recognition" not in html


def test_zhiyi_model_binding_apply_writes_unified_user_default(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    result = p6.apply_zhiyi_model_binding_user_default({
        "manual_override": True,
        "provider": "DeepSeek",
        "provider_id": "deepseek",
        "model_name": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "MEMCORE_ZHIYI_API_KEY",
    })

    target = tmp_path / "memcore" / "config" / "zhiyi_model_binding.user.json"
    legacy_target = tmp_path / "memcore" / "config" / "model_identification.user.json"
    payload = json.loads(target.read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["config_write_performed"] is True
    assert result["analysis_model_preference_write_performed"] is True
    assert result["platform_model_config_write_performed"] is False
    assert result["runtime_binding_write_performed"] is False
    assert result["written"]["secrets_stored"] is False
    assert result["written"]["model_call_performed"] is False
    assert result["written"]["vector_recall_preference"]["enabled"] is False
    assert result["written"]["vector_recall_preference"]["default_recall_mode"] == "substring"
    assert result["written"]["vector_recall_preference"]["fts5_recall"] is True
    assert payload["provider"] == "DeepSeek"
    assert payload["provider_id"] == "deepseek"
    assert payload["model_name"] == "deepseek-chat"
    assert payload["api_key_env"] == "MEMCORE_ZHIYI_API_KEY"
    assert payload["applies_to"] == [
        "evidence_bound_analysis",
        "preflight_answer_debug",
        "experience_distillation",
        "local_tool_identification",
    ]
    assert payload["vector_recall_preference"]["enabled"] is False
    assert payload["vector_recall_preference"]["requires_restart"] is False
    assert not legacy_target.exists()


def test_model_binding_encrypts_direct_key_and_never_returns_it(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    secret = "fixture-private-direct-key"

    result = p6.apply_zhiyi_model_binding_user_default({
        "manual_override": True,
        "provider": "DeepSeek",
        "provider_id": "deepseek",
        "model_name": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "api_key_value": secret,
    })

    target = tmp_path / "memcore" / "config" / "zhiyi_model_binding.user.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    serialized_result = json.dumps(result, ensure_ascii=False)
    options = p6.get_zhiyi_model_options()
    serialized_options = json.dumps(options, ensure_ascii=False)

    assert result["ok"] is True
    assert result["credential_write_performed"] is True
    assert result["credential_status"]["configured"] is True
    assert result["secret_value_returned"] is False
    assert payload["api_key_env"] == "DEEPSEEK_API_KEY"
    assert payload["credential_ref"] == "analysis-model:deepseek"
    assert payload["secrets_stored"] is True
    assert payload["secret_values_returned"] is False
    assert secret not in target.read_text(encoding="utf-8")
    assert secret not in serialized_result
    assert secret not in serialized_options
    assert options["user_default"]["api_key_configured"] is True
    assert options["user_default"]["secret_value_returned"] is False


def test_model_binding_rejects_secret_in_environment_name_field(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    result = p6.build_zhiyi_model_binding_plan({
        "manual_override": True,
        "provider": "DeepSeek",
        "provider_id": "deepseek",
        "model_name": "deepseek-chat",
        "api_key_env": "fixture-direct-secret-value",
    })

    assert result["ok"] is False
    assert result["error"] == "invalid_api_key_env_name"
    assert result["secret_like_value_rejected"] is True
    assert "fixture-direct-secret-value" not in json.dumps(result)


def test_bge_vector_switch_persists_and_reloads_from_user_default(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    monkeypatch.setitem(p6.apply_zhiyi_model_binding_user_default.__globals__, "granite_asset_status", lambda root, verify=False: {"ready": True, "state": "ready"})
    monkeypatch.setitem(p6.apply_zhiyi_model_binding_user_default.__globals__, "_warm_vector_runtime", lambda: {"ok": True})

    result = p6.apply_zhiyi_model_binding_user_default({
        "manual_override": True,
        "provider": "MiniMax",
        "provider_id": "minimax",
        "model_name": "MiniMax-M2",
        "base_url": "https://api.minimax.chat/v1",
        "api_key_env": "MEMCORE_ZHIYI_API_KEY",
        "vector_bge_m3_enabled": True,
    })

    target = tmp_path / "memcore" / "config" / "zhiyi_model_binding.user.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    model_config = json.loads(
        (tmp_path / "memcore" / "config" / "model_config.json").read_text(encoding="utf-8")
    )
    options = p6.get_zhiyi_model_options()

    assert result["ok"] is True
    assert result["written"]["vector_recall_preference"] == payload["vector_recall_preference"]
    assert payload["vector_recall_preference"]["enabled"] is True
    assert payload["vector_recall_preference"]["default_recall_mode"] == "vector"
    assert payload["vector_recall_preference"]["fts5_recall"] is False
    assert payload["vector_recall_preference"]["hot_switch_status"] == "effective_for_new_gateway_requests"
    assert payload["vector_recall_preference"]["requires_restart"] is False
    assert model_config["recall"]["mode"] == "local_vector"
    assert model_config["recall"]["local_vector"]["model_id"] == (
        "ibm-granite/granite-embedding-97m-multilingual-r2"
    )
    assert model_config["recall"]["local_vector"]["embedding_dim"] == 384
    assert model_config["recall"]["local_vector"]["table"] == "experiences_v2_granite_97m"
    assert model_config["recall"]["local_vector"]["model_path"] == str(
        tmp_path / "memcore" / "runtime" / "model_cache" / "granite-embedding-97m-multilingual-r2"
    )
    assert options["user_default"]["vector_recall_preference"]["enabled"] is True
    assert options["vector_recall_preference"]["default_recall_mode"] == "vector"


def test_vector_switch_waits_for_granite_dependencies_before_enabling(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    callbacks = {}
    monkeypatch.setitem(p6.apply_zhiyi_model_binding_user_default.__globals__, "_warm_vector_runtime", lambda: {"ok": True})
    monkeypatch.setitem(p6.apply_zhiyi_model_binding_user_default.__globals__, "granite_asset_status", lambda root, verify=False: {
        "ready": False,
        "state": "dependencies_missing",
        "model_ready": True,
        "table_ready": True,
        "dependencies_ready": False,
    })

    def start_prepare(root, on_complete=None):
        callbacks["on_complete"] = on_complete
        return {
            "ready": False, "state": "downloading", "started": True,
            "progress": {"percent": 0},
        }

    monkeypatch.setitem(
        p6.apply_zhiyi_model_binding_user_default.__globals__,
        "start_granite_asset_prepare",
        start_prepare,
    )

    result = p6.apply_zhiyi_model_binding_user_default({
        "manual_override": True,
        "provider": "MiniMax",
        "provider_id": "minimax",
        "model_name": "MiniMax-M2",
        "vector_recall_enabled": True,
    })

    assert result["ok"] is True
    assert result["vector_enable_pending"] is True
    assert result["write_performed"] is False
    assert result["vector_recall_preference"]["enabled"] is False
    assert not (tmp_path / "memcore" / "config" / "zhiyi_model_binding.user.json").exists()

    callbacks["on_complete"]({"ready": False, "state": "failed"})
    assert not (tmp_path / "memcore" / "config" / "zhiyi_model_binding.user.json").exists()

    callbacks["on_complete"]({"ready": True, "state": "ready", "table_row_count": 3})
    model_config = json.loads(
        (tmp_path / "memcore" / "config" / "model_config.json").read_text(encoding="utf-8")
    )
    user_default = json.loads(
        (tmp_path / "memcore" / "config" / "zhiyi_model_binding.user.json").read_text(encoding="utf-8")
    )
    assert model_config["recall"]["mode"] == "local_vector"
    assert model_config["recall"]["local_vector"]["model_id"] == (
        "ibm-granite/granite-embedding-97m-multilingual-r2"
    )
    assert model_config["recall"]["local_vector"]["embedding_dim"] == 384
    assert model_config["recall"]["local_vector"]["table"] == "experiences_v2_granite_97m"
    assert user_default["vector_recall_preference"]["enabled"] is True


def test_vector_enable_rolls_back_both_configs_when_preference_write_fails(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    monkeypatch.setitem(p6.apply_zhiyi_model_binding_user_default.__globals__, "granite_asset_status", lambda root, verify=False: {"ready": True, "state": "ready"})
    monkeypatch.setitem(p6.apply_zhiyi_model_binding_user_default.__globals__, "_warm_vector_runtime", lambda: {"ok": True})
    config_dir = tmp_path / "memcore" / "config"
    model_path = config_dir / "model_config.json"
    user_path = config_dir / "zhiyi_model_binding.user.json"
    config_dir.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps({"recall": {"mode": "substring"}}), encoding="utf-8")
    original_model = json.loads(model_path.read_text(encoding="utf-8"))
    original_user = {"schema_version": "1.0", "vector_recall_preference": {"enabled": False}}
    user_path.write_text(json.dumps(original_user), encoding="utf-8")
    runtime_globals = p6.apply_zhiyi_model_binding_user_default.__globals__
    original_atomic_write = runtime_globals["_atomic_write_json"]

    def fail_user_write(path, payload):
        if Path(path) == user_path and payload.get("vector_recall_preference", {}).get("enabled"):
            raise OSError("preference write failed")
        return original_atomic_write(path, payload)

    monkeypatch.setitem(runtime_globals, "_atomic_write_json", fail_user_write)
    with pytest.raises(OSError, match="preference write failed"):
        p6.apply_zhiyi_model_binding_user_default({
            "manual_override": True,
            "provider": "MiniMax",
            "provider_id": "minimax",
            "model_name": "MiniMax-M2",
            "vector_recall_enabled": True,
        })

    assert json.loads(model_path.read_text(encoding="utf-8")) == original_model
    assert json.loads(user_path.read_text(encoding="utf-8")) == original_user


def test_vector_enable_rolls_back_before_preference_when_warmup_fails(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    runtime_globals = p6.apply_zhiyi_model_binding_user_default.__globals__
    monkeypatch.setitem(runtime_globals, "granite_asset_status", lambda root, verify=False: {
        "ready": True, "state": "ready",
    })
    monkeypatch.setitem(
        runtime_globals,
        "_warm_vector_runtime",
        lambda: (_ for _ in ()).throw(RuntimeError("vector runtime warmup failed")),
    )
    config_dir = tmp_path / "memcore" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    model_path = config_dir / "model_config.json"
    user_path = config_dir / "zhiyi_model_binding.user.json"
    original_model = {"recall": {"mode": "substring"}}
    original_user = {"vector_recall_preference": {"enabled": False}}
    model_path.write_text(json.dumps(original_model), encoding="utf-8")
    user_path.write_text(json.dumps(original_user), encoding="utf-8")

    with pytest.raises(RuntimeError, match="vector runtime warmup failed"):
        p6.apply_zhiyi_model_binding_user_default({
            "manual_override": True,
            "provider": "MiniMax",
            "provider_id": "minimax",
            "model_name": "MiniMax-M2",
            "vector_recall_enabled": True,
        })

    assert json.loads(model_path.read_text(encoding="utf-8")) == original_model
    assert json.loads(user_path.read_text(encoding="utf-8")) == original_user


def test_console_state_persists_local_tasks_notes_and_projects_without_memory_writes(tmp_path):
    for name in ["src.p6_console_state", "p6_console_state"]:
        sys.modules.pop(name, None)
    console_state = importlib.import_module("src.p6_console_state")
    console_state.configure_console_state(tmp_path / "memcore")

    initial = console_state.get_console_state()
    assert initial["ok"] is True
    assert initial["state_storage"] == "runtime/console_state.user.json"
    assert "state_path" not in initial
    assert initial["tasks"] == []
    assert initial["notes"] == []
    assert initial["projects"] == []
    assert initial["write_boundary"]["console_state_write_performed"] is False
    assert initial["write_boundary"]["raw_write_performed"] is False
    assert initial["write_boundary"]["memory_write_performed"] is False
    assert initial["write_boundary"]["platform_write_performed"] is False

    task = console_state.add_console_task({"title": "真实测试事项", "priority": "high"})
    assert task["ok"] is True
    assert task["console_state_write_performed"] is True
    assert task["write_boundary"]["console_state_write_performed"] is True
    assert task["write_boundary"]["raw_write_performed"] is False
    assert task["write_boundary"]["memory_write_performed"] is False
    assert task["write_boundary"]["platform_write_performed"] is False
    task_id = task["item"]["id"]
    assert console_state.get_console_state()["tasks"][0]["title"] == "真实测试事项"

    note = console_state.add_console_note({"title": "真实测试线索", "body": "只进本机控制台"})
    assert note["ok"] is True
    note_id = note["item"]["id"]
    assert console_state.get_console_state()["notes"][0]["body"] == "只进本机控制台"

    project = console_state.add_console_project({
        "name": "公开演示项目",
        "source": "/tmp/public-demo",
        "note": "不预设私有项目",
        "shared": False,
    })
    assert project["ok"] is True
    project_id = project["item"]["id"]
    assert console_state.get_console_state()["projects"][0]["name"] == "公开演示项目"
    assert console_state.get_console_state()["projects"][0]["shared"] is False

    assert console_state.delete_console_task({"id": task_id})["deleted"] is True
    assert console_state.delete_console_note({"id": note_id})["deleted"] is True
    assert console_state.delete_console_project({"id": project_id})["deleted"] is True
    final = console_state.get_console_state()
    assert final["tasks"] == []
    assert final["notes"] == []
    assert final["projects"] == []


def test_p6_reading_area_summary_is_read_only_catalog_projection(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    fake_registry = {
        "projects": {
            "project:time-library:abc": {"name": "time-library"},
        },
        "borrowing_cards": {"card:1": {}},
        "whiteboard_records": [{"record_id": "WB-1"}],
        "project_history_records": [{"record_id": "PH-1"}],
    }
    fake_catalog = {
        "ok": True,
        "startup_instruction_mode": "reading_area_lanes_only",
        "catalog_entry_count": 4,
        "catalog_token_count": 120,
        "reading_area_project_page_count": 1,
        "reading_area_projection": {
            "contract": "time_library_reading_area_projection.v1",
            "contains_body_markers": False,
            "shelf_sections": {
                "zhiyi": {"entry_count": 1},
                "xingce": {"entry_count": 2},
                "toolbook": {"entry_count": 0},
                "raw": {"entry_count": 1},
                "errata": {"entry_count": 1},
            },
            "whiteboard": {
                "record_count": 1,
                "visible_record_count": 1,
                "lines": ["在飞：施工/codex -> 待接棒；[WB-1]"],
                "visible_record_ids": ["WB-1"],
                "contains_body_markers": False,
            },
            "history": {
                "record_count": 1,
                "visible_record_count": 1,
                "lines": ["历史：decision 项目史进入项目页；[PH-1]"],
                "visible_record_ids": ["PH-1"],
                "contains_body_markers": False,
            },
            "project_pages": [
                {
                    "contract": "time_library_reading_area_project_page.v1",
                    "project_id": "project:time-library:abc",
                    "lane_count": 1,
                    "visible_lane_count": 1,
                    "library_id_pull_handles": ["ZX-XINGCE-1", "ZX-RAW-1"],
                    "visible_library_id_pull_handles": ["ZX-XINGCE-1"],
                    "whiteboard": {
                        "record_count": 1,
                        "visible_record_count": 1,
                        "lines": ["在飞：施工/codex -> 待接棒；[WB-1]"],
                        "visible_record_ids": ["WB-1"],
                        "contains_body_markers": False,
                    },
                    "history": {
                        "record_count": 1,
                        "visible_record_count": 1,
                        "lines": ["历史：decision 项目史进入项目页；[PH-1]"],
                        "visible_record_ids": ["PH-1"],
                        "contains_body_markers": False,
                    },
                    "visible_lane_summaries": [
                        {
                            "agent": "codex",
                            "item_count": 2,
                            "shelf_counts": {"xingce": 1, "raw": 1},
                            "library_ids": ["ZX-XINGCE-1"],
                        }
                    ],
                }
            ],
        },
    }

    monkeypatch.setattr(p6, "load_reading_area_registry", lambda path=None: fake_registry)
    monkeypatch.setattr(p6, "build_catalog_inject_from_candidates", lambda **kwargs: fake_catalog)

    summary = p6.build_reading_area_summary()

    assert summary["ok"] is True
    assert summary["read_only"] is True
    assert summary["write_performed"] is False
    assert summary["raw_write_performed"] is False
    assert summary["memory_write_performed"] is False
    assert summary["platform_write_performed"] is False
    assert summary["reading_area_content_write_performed"] is False
    assert summary["project_page_count"] == 1
    assert summary["project_pages"][0]["project_name"] == "time-library"
    assert summary["project_pages"][0]["lanes"][0]["agent"] == "codex"
    assert summary["whiteboard"]["record_count"] == 1
    assert summary["history"]["record_count"] == 1
    assert summary["shelf_counts"]["errata"] == 1
    assert summary["raw_pull_required_for_body"] is True
    assert summary["contains_body_markers"] is False


def test_runtime_profile_part_failure_returns_unknown_instead_of_raising(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    def broken_builder():
        raise RuntimeError("profile probe failed")

    result = p6._safe_runtime_profile_part("openclaw", broken_builder)

    assert result["system"] == "openclaw"
    assert result["status"] == "unknown"
    assert result["ok"] is False
    assert result["error"] == "runtime_profile_part_failed"
    assert "RuntimeError" in result["detail"]


def test_runtime_profile_instances_endpoint_uses_public_shape(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    result = p6._public_runtime_profile_instances({
        "openclaw": [
            {
                "type": "running",
                "pid": 123,
                "command": "<home>/.openclaw/bin/openclaw gateway",
                "path": "<home>/.openclaw",
            },
            {"type": "openclaw_home", "path": "<home>/.openclaw"},
        ],
        "hermes": [{"type": "hermes_home", "path": "<home>/.hermes"}],
        "claude_desktop": [{"type": "running", "command": "/Applications/Claude.app/Contents/MacOS/Claude"}],
        "memcore_cloud": [{"type": "installed", "path": "<home>/Library/Application Support/memcore-cloud", "version": "2026.7.7"}],
        "detected_count": 3,
        "openclaw_detected": True,
        "hermes_detected": True,
        "claude_desktop_detected": True,
    })

    serialized = json.dumps(result, ensure_ascii=False)
    assert result["openclaw"][0] == {"type": "running"}
    assert result["memcore_cloud"][0] == {"type": "installed", "version": "2026.7.7"}
    assert result["detected_count"] == 3
    assert "command" not in serialized
    assert "path" not in serialized
    assert "<home>" not in serialized


def test_runtime_profile_module_loader_works_from_install_root_without_tools_package(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    tools_dir = tmp_path / "memcore" / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "runtime_profile.py").write_text(
        "def ts():\n"
        "    return '2026-07-07T00:00:00Z'\n"
        "def build_instances_summary():\n"
        "    return {'hermes': [{'type': 'running'}]}\n",
        encoding="utf-8",
    )
    for name in ["tools.runtime_profile", "tools"]:
        sys.modules.pop(name, None)
    monkeypatch.setattr(p6, "MEMCORE_ROOT", tmp_path / "memcore")

    module = p6._load_runtime_profile_module()

    assert module.ts() == "2026-07-07T00:00:00Z"
    assert module.build_instances_summary()["hermes"][0]["type"] == "running"


def test_runtime_profile_module_loader_reports_missing_install_asset(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    for name in ["tools.runtime_profile", "tools"]:
        sys.modules.pop(name, None)
    monkeypatch.setattr(p6, "MEMCORE_ROOT", tmp_path / "memcore")

    module = p6._load_runtime_profile_module()

    assert module.build_instances_summary()["error"] == "runtime_profile_asset_missing"
    assert "tools/runtime_profile.py" in module.build_instances_summary()["detail"]
    assert module.build_openclaw_profile()["status"] == "unknown"


def test_p6_toolbook_candidate_dry_run_validates_without_writing(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    result = p6.build_toolbook_candidate({
        "platform": "Hermes",
        "environment": "isolated probe",
        "observed_behavior": "profile config is read from the profile directory",
        "raw_source_path": "raw/probe_logs/hermes-profile-config.jsonl",
        "verbatim_excerpt": "profile config.yaml was read from profiles/default/config.yaml",
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["candidate"]["library_shelf"] == "toolbook"
    assert result["validation"]["checks"]["toolbook_raw_source"] is True


def test_p6_zhixing_library_exposes_loop_and_replay_offense_metric(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    library = p6.query_zhixing_library()
    plan = p6.get_zhixing_replay_plan()
    replay = p6.run_replay_dry_run({
        "case": {
            "case_id": "p6-proactive",
            "query": "继续平台配置问题",
            "expected_proactive_resurfacing": ["profile 无 config 显示 auto"],
        },
        "records": [
            {
                "_type": "xingce_work_experience_candidate",
                "exp_id": "xingce-p6-proactive",
                "summary": "过去做对过：profile 无 config 显示 auto。",
                "source_refs": {
                    "source_system": "probe",
                    "source_path": "raw/probe_logs/hermes-profile.jsonl",
                },
                "verbatim_excerpt": "profile 无 config 显示 auto。",
                "supersedes": [],
                "conflicts_with": [],
                "_xingce": {"candidate_id": "xingce-p6-proactive", "lifecycle_status": "candidate"},
            },
        ],
    })

    assert library["loop"]["zh_name"] == "知行闭环"
    assert len(library["loop"]["steps"]) == 7
    assert plan["metrics"][-1] == "proactive_resurfacing"
    assert plan["loop"]["connector_persona"]["zh_name"] == "接引者"
    assert replay["summary"]["proactive_resurfacing_passed"] is True
    assert replay["write_performed"] is False
    assert replay["feedback_candidates"]["write_performed"] is False
    assert "proactive_resurfacing_candidate" in replay["feedback_candidates"]["candidate_types"]

    trust_dashboard = p6.query_zhixing_library_trust_dashboard({"limit": 3})

    assert trust_dashboard["ok"] is True
    assert trust_dashboard["read_only"] is True
    assert trust_dashboard["write_performed"] is False
    assert trust_dashboard["raw_write_performed"] is False
    assert trust_dashboard["memory_write_performed"] is False
    assert trust_dashboard["platform_write_performed"] is False
    assert trust_dashboard["markdown_write_performed"] is False
    assert trust_dashboard["contract"] == "zhixing_library_trust_dashboard.v1"
    assert trust_dashboard["data_source"] == "real_zhixing_library"
    assert trust_dashboard["demo_fallback_used"] is False
    assert trust_dashboard["trust_doctor"]["contract"] == "zhixing_library_trust_doctor.v1"
    assert trust_dashboard["index_projection"]["contract"] == "zhixing_library_index_projection.v1"
    assert trust_dashboard["active_bookmarks"]["contract"] == "zhixing_library_active_bookmarks.v1"
    assert trust_dashboard["experience_history"]["contract"] == "zhixing_library_experience_history.v1"
    assert trust_dashboard["experience_evolution"]["contract"] == "zhixing_library_experience_evolution_candidates.v1"
    assert trust_dashboard["experience_review_actions"]["contract"] == "zhixing_library_experience_review_action.v1"
    assert trust_dashboard["experience_review_actions"]["write_performed"] is False
    assert trust_dashboard["experience_review_actions"]["markdown_write_performed"] is False
    assert trust_dashboard["experience_validation_report"]["contract"] == "zhixing_library_experience_validation_report.v1"
    assert trust_dashboard["experience_validation_report"]["write_performed"] is False
    assert trust_dashboard["experience_validation_report"]["markdown_write_performed"] is False
    assert trust_dashboard["experience_validation_receipt_schema"]["contract"] == "zhixing_library_experience_validation_receipt_schema.v1"
    assert trust_dashboard["experience_validation_receipt_schema"]["write_performed"] is False
    assert trust_dashboard["experience_validation_receipt_schema"]["markdown_write_performed"] is False
    assert trust_dashboard["experience_validation_receipt_schema"]["validation_result_write_performed"] is False
    assert trust_dashboard["experience_validation_receipt_schema"]["candidate_status_change_performed"] is False
    assert trust_dashboard["experience_review_queue"]["contract"] == "zhixing_library_experience_review_queue.v1"
    assert trust_dashboard["experience_review_queue"]["write_performed"] is False
    assert trust_dashboard["experience_review_queue"]["markdown_write_performed"] is False
    assert trust_dashboard["experience_review_apply_gate"]["contract"] == "zhixing_library_experience_review_apply_gate.v1"
    assert trust_dashboard["experience_review_apply_gate"]["write_performed"] is False
    assert trust_dashboard["experience_review_apply_gate"]["markdown_write_performed"] is False
    assert trust_dashboard["experience_review_apply_gate"]["validation_receipt_preferred_for_future_apply"] is True
    assert trust_dashboard["experience_review_apply_gate"]["validation_receipt_attached"] is True
    assert trust_dashboard["experience_apply_receipt_schema"]["contract"] == "zhixing_library_experience_apply_receipt_schema.v1"
    assert trust_dashboard["experience_apply_receipt_schema"]["write_performed"] is False
    assert trust_dashboard["experience_apply_receipt_schema"]["durable_write_performed"] is False
    assert trust_dashboard["experience_apply_package"]["contract"] == "zhixing_library_experience_apply_package.v1"
    assert trust_dashboard["experience_apply_package"]["write_performed"] is False
    assert trust_dashboard["experience_apply_package"]["durable_write_performed"] is False
    assert trust_dashboard["experience_apply_package"]["authorized_apply_performed"] is False
    assert trust_dashboard["experience_flow_overview"]["contract"] == "zhixing_library_experience_flow_overview.v1"
    assert trust_dashboard["experience_flow_overview"]["write_performed"] is False
    assert trust_dashboard["experience_flow_overview"]["candidate_status_change_performed"] is False
    assert trust_dashboard["experience_flow_overview"]["stage_count"] == 8


def test_p6_library_trust_dashboard_counts_five_tiandao_shelves(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    governance = sys.modules.get("src.p6_experience_governance") or sys.modules.get("p6_experience_governance")

    def fake_load_zhiyi_objects(ftype=None, limit=None):
        items = [
            {
                "_type": "preference_memory",
                "type": "preference_memory",
                "exp_id": "pref-five-shelf",
                "summary": "用户偏好：先给结论。",
                "source_refs": json.dumps({
                    "source_system": "codex",
                    "source_path": "raw/codex/pref-five-shelf.jsonl",
                }),
                "verbatim_excerpt": "先给结论。",
            },
            {
                "_type": "case_memory",
                "type": "case_memory",
                "exp_id": "case-recycled",
                "summary": "旧记录，已回收。",
                "source_refs": json.dumps({
                    "source_system": "codex",
                    "source_path": "raw/codex/case-recycled.jsonl",
                }),
                "verbatim_excerpt": "旧记录，已回收。",
            },
        ]
        if ftype:
            items = [item for item in items if item.get("_type") == ftype or item.get("type") == ftype]
        return items[:limit] if limit is not None else items

    monkeypatch.setattr(governance, "load_zhiyi_objects", fake_load_zhiyi_objects)
    monkeypatch.setattr(governance, "_zhiyi_experience_recycle_overlay", lambda: {
        "case-recycled": {
            "action_id": "act-recycle",
            "action": "recycle",
            "exp_id": "case-recycled",
            "status": "recycled",
            "deleted_state": "recycle_bin",
            "reason": "用户确认这条旧记录不再适用。",
        }
    })
    monkeypatch.setattr(governance, "query_xingce_work_experience_candidates", lambda params=None: {
        "ok": True,
        "total": 2,
        "items": [
            {
                "candidate_id": "xingce-five-shelf",
                "library_id": "ZX-XINGCE-FIVE-SHELF",
                "library_shelf": "xingce",
                "title": "发布前验收",
                "summary": "发布前先跑记录医生。",
                "source_refs": {"source_system": "probe", "source_path": "raw/probe_logs/xingce-five-shelf.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
                "lifecycle_status": "candidate",
            },
            {
                "candidate_id": "toolbook-five-shelf",
                "library_id": "ZX-TOOL-FIVE-SHELF",
                "library_shelf": "toolbook",
                "title": "Hermes 配置路径",
                "summary": "Hermes 配置事实来自探针日志。",
                "source_refs": {"source_system": "probe", "source_path": "raw/probe_logs/toolbook-five-shelf.jsonl"},
                "verbatim_excerpt": "Hermes 配置事实来自探针日志。",
                "lifecycle_status": "active",
            },
        ],
    })

    library = p6.query_zhixing_library({"limit": 5})
    assert library["data_source"] == "real_zhixing_library"
    assert library["record_count"] == 8
    assert library["shelf_counts"]["raw"] == 4
    assert library["shelf_counts"]["zhiyi"] == 1
    assert library["shelf_counts"]["xingce"] == 1
    assert library["shelf_counts"]["toolbook"] == 1
    assert library["shelf_counts"]["errata"] == 1
    assert library["shelf_index_preview"]["raw"]["count"] == 4
    assert library["shelf_index_preview"]["zhiyi"]["entries"][0]["source_path"] == "raw/codex/pref-five-shelf.jsonl"
    assert library["shelf_index_preview"]["xingce"]["entries"][0]["library_id"] == "ZX-XINGCE-FIVE-SHELF"
    assert library["shelf_index_preview"]["toolbook"]["entries"][0]["source_path"] == "raw/probe_logs/toolbook-five-shelf.jsonl"
    assert library["shelf_index_preview"]["errata"]["entries"][0]["status"] == "recycled"

    dashboard = p6.query_zhixing_library_trust_dashboard({"limit": 5})
    shelf_counts = dashboard["shelf_counts"]

    assert dashboard["ok"] is True
    assert dashboard["read_only"] is True
    assert dashboard["write_performed"] is False
    assert dashboard["markdown_write_performed"] is False
    assert dashboard["record_count"] == 8
    assert shelf_counts["raw"] == 4
    assert shelf_counts["zhiyi"] == 1
    assert shelf_counts["xingce"] == 1
    assert shelf_counts["toolbook"] == 1
    assert shelf_counts["errata"] == 1
    assert set(dashboard["index_projection"]["index"]["shelf_index"]) >= {"raw", "zhiyi", "xingce", "toolbook", "errata"}
    assert dashboard["experience_evolution"]["contract"] == "zhixing_library_experience_evolution_candidates.v1"
    assert dashboard["experience_evolution"]["write_performed"] is False
    assert dashboard["experience_evolution"]["markdown_write_performed"] is False
    assert dashboard["experience_evolution"]["candidate_count"] >= 1
    assert "experience_xingce_validation_candidate" in dashboard["experience_evolution"]["candidate_types"]
    assert dashboard["experience_review_actions"]["contract"] == "zhixing_library_experience_review_action.v1"
    assert dashboard["experience_review_actions"]["action_count"] >= 1
    assert dashboard["experience_review_actions"]["review_actions"][0]["requested_action"] == "defer"
    assert dashboard["experience_review_actions"]["review_actions"][0]["planned_lifecycle_status"] == "pending_review"
    assert dashboard["experience_review_actions"]["review_actions"][0]["receipt_preview"]["would_write"] is False
    assert dashboard["experience_validation_report"]["contract"] == "zhixing_library_experience_validation_report.v1"
    assert dashboard["experience_validation_report"]["validation_report_count"] >= 1
    assert dashboard["experience_validation_report"]["write_performed"] is False
    assert dashboard["experience_validation_report"]["markdown_write_performed"] is False
    assert dashboard["experience_validation_receipt_schema"]["contract"] == "zhixing_library_experience_validation_receipt_schema.v1"
    assert dashboard["experience_validation_receipt_schema"]["receipt_count"] >= 1
    assert dashboard["experience_validation_receipt_schema"]["write_performed"] is False
    assert dashboard["experience_validation_receipt_schema"]["markdown_write_performed"] is False
    assert dashboard["experience_validation_receipt_schema"]["validation_result_write_performed"] is False
    assert dashboard["experience_validation_receipt_schema"]["candidate_status_change_performed"] is False
    assert dashboard["experience_review_queue"]["contract"] == "zhixing_library_experience_review_queue.v1"
    assert dashboard["experience_review_queue"]["queue_count"] >= 1
    assert dashboard["experience_review_queue"]["write_performed"] is False
    assert dashboard["experience_review_queue"]["markdown_write_performed"] is False
    assert dashboard["experience_review_apply_gate"]["contract"] == "zhixing_library_experience_review_apply_gate.v1"
    assert dashboard["experience_review_apply_gate"]["status"] == "blocked"
    assert dashboard["experience_review_apply_gate"]["review_action_count"] >= 1
    assert "missing_authorization_confirmations" in dashboard["experience_review_apply_gate"]["blocked_reasons"]
    assert dashboard["experience_review_apply_gate"]["validation_receipt_preferred_for_future_apply"] is True
    assert dashboard["experience_review_apply_gate"]["validation_receipt_attached"] is True
    assert dashboard["experience_review_apply_gate"]["validation_receipt_count"] >= 1
    assert dashboard["experience_review_apply_gate"]["receipt_preview"]["would_write"] is False
    assert dashboard["experience_apply_receipt_schema"]["contract"] == "zhixing_library_experience_apply_receipt_schema.v1"
    assert dashboard["experience_apply_receipt_schema"]["receipt_count"] >= 1
    assert dashboard["experience_apply_receipt_schema"]["rollback_plans"][0]["write_performed"] is False
    assert dashboard["experience_apply_receipt_schema"]["durable_write_performed"] is False
    assert dashboard["experience_apply_receipt_schema"]["source_evidence_complete"] is True
    assert dashboard["experience_apply_package"]["contract"] == "zhixing_library_experience_apply_package.v1"
    assert dashboard["experience_apply_package"]["package_status"] == "blocked"
    assert dashboard["experience_apply_package"]["write_performed"] is False
    assert dashboard["experience_apply_package"]["authorized_apply_performed"] is False
    assert "apply_gate_not_ready" in dashboard["experience_apply_package"]["blocked_reasons"]
    assert dashboard["experience_flow_overview"]["contract"] == "zhixing_library_experience_flow_overview.v1"
    assert dashboard["experience_flow_overview"]["flow_status"] == "blocked_preview"
    assert dashboard["experience_flow_overview"]["blocked_stage_count"] >= 1
    assert dashboard["experience_flow_overview"]["write_performed"] is False
    assert dashboard["experience_flow_overview"]["candidate_status_change_performed"] is False


def test_p6_state_ledger_and_context_unit_helpers_are_read_only(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    ledger_plan = p6.get_state_ledger_plan()
    ledger = p6.build_state_ledger_snapshot({
        "topic": "ExampleTool naming",
        "records": [
            {
                "library_id": "ZX-ZHIYI-OLD",
                "status": "superseded",
                "updated_at": "2026-05-29T10:00:00Z",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/old.jsonl"},
                "verbatim_excerpt": "Windows 原生 OpenClaw 你称为 ExampleTool",
            },
            {
                "library_id": "ZX-ZHIYI-CURRENT",
                "status": "adopted",
                "updated_at": "2026-05-30T10:00:00Z",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/current.jsonl"},
                "verbatim_excerpt": "腾讯那个我会称呼 ExampleTool，不会和 openclaw 混说",
                "supersedes": ["ZX-ZHIYI-OLD"],
            },
        ],
    })
    unit_contract = p6.get_context_budget_unit_contract()
    unit = p6.build_context_budget_unit_candidate({
        "unit_text": "ExampleTool 指腾讯那个，不是 Windows 原生 OpenClaw。",
        "source_refs": {"source_system": "codex", "source_path": "raw/codex/exampletool.jsonl"},
        "verbatim_excerpt": "腾讯那个我会称呼 ExampleTool，不会和 openclaw 混说",
        "objective_link": "prevent ExampleTool naming drift",
    })

    assert ledger_plan["read_only"] is True
    assert ledger_plan["write_performed"] is False
    assert ledger["latest_trusted_judgment"]["record_id"] == "ZX-ZHIYI-CURRENT"
    assert ledger["write_performed"] is False
    assert ledger["write_flags"]["raw_write_performed"] is False
    assert unit_contract["read_only"] is True
    assert unit["ok"] is True
    assert unit["candidate"]["candidate_type"] == "context_budget_unit_candidate"
    assert unit["candidate"]["platform_write_performed"] is False


def test_p6_replay_feedback_apply_requires_authorization_and_writes_receipt_only(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    replay = p6.run_replay_dry_run({
        "case": {
            "case_id": "p6-feedback-apply",
            "expected_library_ids": ["ZX-XINGCE-APPLY"],
            "expected_proactive_resurfacing": ["过去做对过的验收路径"],
        },
        "records": [
            {
                "_type": "xingce_work_experience_candidate",
                "library_id": "ZX-XINGCE-APPLY",
                "exp_id": "xingce-p6-apply",
                "summary": "过去做对过的验收路径。",
                "source_refs": {
                    "source_system": "probe",
                    "source_path": "raw/probe_logs/apply.jsonl",
                },
                "verbatim_excerpt": "过去做对过的验收路径。",
                "supersedes": [],
                "conflicts_with": [],
                "_xingce": {"candidate_id": "xingce-p6-apply", "lifecycle_status": "candidate"},
            },
        ],
    })
    candidate = next(
        item for item in replay["feedback_candidates"]["candidates"]
        if item["candidate_type"] == "proactive_resurfacing_candidate"
    )

    blocked = p6.apply_zhixing_replay_feedback_candidate({"candidate": candidate})
    assert blocked["ok"] is False
    assert blocked["write_performed"] is False
    assert "confirm_apply_replay_feedback" in blocked["authorization_missing"]

    applied = p6.apply_zhixing_replay_feedback_candidate({
        "candidate": candidate,
        "authorization": {
            "confirm_apply_replay_feedback": True,
            "confirm_write_replay_feedback_receipt": True,
            "confirm_no_raw_platform_or_memory_write": True,
            "operator": "test",
            "reason": "verify replay feedback apply gate",
        },
    })

    assert applied["ok"] is True
    assert applied["write_performed"] is True
    assert applied["replay_feedback_receipt_write_performed"] is True
    assert applied["production_experience_write_performed"] is False
    assert applied["raw_write_performed"] is False
    assert applied["zhiyi_write_performed"] is False
    assert applied["xingce_write_performed"] is False
    assert applied["hermes_write_performed"] is False
    assert applied["openclaw_write_performed"] is False
    assert p6.os.path.exists(applied["receipt_path"])
    assert p6.os.path.exists(applied["latest_path"])


def test_http_zhixing_loop_replay_and_capability_check_smoke(tmp_path, monkeypatch):
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    p6 = _reload_p6(tmp_path, monkeypatch)
    monkeypatch.setattr(p6, "build_reading_area_summary", lambda: {
        "ok": True,
        "contract": "time_library_console_reading_area_summary.v1",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "reading_area_content_write_performed": False,
        "project_page_count": 1,
        "catalog_entry_count": 2,
        "shelf_counts": {"zhiyi": 1, "xingce": 1, "errata": 0, "raw": 0, "toolbook": 0},
        "project_pages": [{"project_id": "project:test", "project_name": "test", "lanes": []}],
        "whiteboard": {"record_count": 1, "lines": ["在飞：测试；[WB-1]"]},
        "history": {"record_count": 0, "lines": []},
    })
    monkeypatch.setattr(p6, "build_record_doctor", lambda **kwargs: {
        "ok": True,
        "contract": "record_chain_doctor.v1",
        "doctor_status": "records_guarded",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "not_memory_wall": True,
        "summary": {"record_count": 1, "record_guarded_count": 1, "canonical_messages": 2},
    })
    monkeypatch.setattr(p6, "build_record_chain_timeline", lambda **kwargs: {
        "ok": True,
        "contract": "record_chain_timeline.v1",
        "timeline_kind": "record_chain",
        "read_only": True,
        "write_performed": False,
        "not_memory_wall": True,
        "record_chains": [
            {
                "source_system": "codex",
                "session_id": "session-1",
                "chain_status": "guarded",
                "stages": [
                    {"id": "source_record", "status": "seen"},
                    {"id": "raw_mirror", "status": "guarded"},
                    {"id": "canonical_index", "status": "indexed"},
                    {"id": "memory_experience", "status": "source_refs_ready"},
                ],
            }
        ],
        "recent_messages": [],
    })
    monkeypatch.setattr(p6, "build_record_chain_replay", lambda **kwargs: {
        "ok": True,
        "contract": "record_chain_replay.v1",
        "replay_kind": "record_chain",
        "read_only": True,
        "write_performed": False,
        "not_memory_wall": True,
        "session_id": "session-1",
        "messages": [],
        "message_count": 0,
    })
    for name in ["raw_consumption_gateway", "src.raw_consumption_gateway"]:
        sys.modules.pop(name, None)
    raw_gateway = importlib.import_module("src.raw_consumption_gateway")

    p6_server = p6.ThreadingHTTPServer(("127.0.0.1", 0), p6.Handler)
    raw_server = raw_gateway.HTTPServer(("127.0.0.1", 0), raw_gateway.Handler)
    servers = [p6_server, raw_server]
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in servers
    ]
    for thread in threads:
        thread.start()

    def get_json(port, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=8) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def post_json(port, path, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if port == p6_server.server_address[1]:
            headers.update({
                "Origin": f"http://127.0.0.1:{port}",
                "X-Memcore-Console-Token": p6.CONSOLE_CSRF_TOKEN,
            })
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        p6_port = p6_server.server_address[1]
        raw_port = raw_server.server_address[1]

        status, console_initial = get_json(p6_port, "/api/v1/console/state")
        assert status == 200
        assert console_initial["ok"] is True
        assert console_initial["state_storage"] == "runtime/console_state.user.json"
        assert "state_path" not in console_initial
        assert console_initial["tasks"] == []
        assert console_initial["notes"] == []
        assert console_initial["projects"] == []
        assert console_initial["write_boundary"]["raw_write_performed"] is False
        assert console_initial["write_boundary"]["memory_write_performed"] is False
        assert console_initial["write_boundary"]["platform_write_performed"] is False

        status, reading_area = get_json(p6_port, "/api/v1/reading-area/summary")
        assert status == 200
        assert reading_area["ok"] is True
        assert reading_area["read_only"] is True
        assert reading_area["write_performed"] is False
        assert reading_area["reading_area_content_write_performed"] is False
        assert reading_area["project_page_count"] == 1
        assert reading_area["whiteboard"]["record_count"] == 1

        status, console_task = post_json(p6_port, "/api/v1/console/tasks", {
            "title": "HTTP 本机事项",
            "priority": "high",
        })
        assert status == 200
        assert console_task["ok"] is True
        assert console_task["console_state_write_performed"] is True
        assert console_task["item"]["title"] == "HTTP 本机事项"
        assert console_task["write_boundary"]["console_state_write_performed"] is True
        assert console_task["write_boundary"]["raw_write_performed"] is False
        assert console_task["write_boundary"]["memory_write_performed"] is False
        assert console_task["write_boundary"]["platform_write_performed"] is False
        task_id = console_task["item"]["id"]
        status, console_after_task = get_json(p6_port, "/api/v1/console/state")
        assert status == 200
        assert [item["id"] for item in console_after_task["tasks"]] == [task_id]

        status, console_note = post_json(p6_port, "/api/v1/console/notes", {
            "title": "HTTP 本机线索",
            "body": "这条只写本机控制台状态",
        })
        assert status == 200
        assert console_note["ok"] is True
        note_id = console_note["item"]["id"]
        assert console_note["item"]["body"] == "这条只写本机控制台状态"

        status, console_project = post_json(p6_port, "/api/v1/console/projects", {
            "name": "HTTP 公开演示项目",
            "source": "/tmp/time-library-demo",
            "note": "没有预置私有项目",
            "shared": False,
        })
        assert status == 200
        assert console_project["ok"] is True
        project_id = console_project["item"]["id"]
        assert console_project["item"]["name"] == "HTTP 公开演示项目"
        assert console_project["item"]["shared"] is False

        status, console_delete_task = post_json(p6_port, "/api/v1/console/tasks/delete", {"id": task_id})
        assert status == 200
        assert console_delete_task["deleted"] is True
        status, console_delete_note = post_json(p6_port, "/api/v1/console/notes/delete", {"id": note_id})
        assert status == 200
        assert console_delete_note["deleted"] is True
        status, console_delete_project = post_json(p6_port, "/api/v1/console/projects/delete", {"id": project_id})
        assert status == 200
        assert console_delete_project["deleted"] is True
        status, console_final = get_json(p6_port, "/api/v1/console/state")
        assert status == 200
        assert console_final["tasks"] == []
        assert console_final["notes"] == []
        assert console_final["projects"] == []

        status, loop = get_json(p6_port, "/api/v1/zhixing/loop")
        assert status == 200
        assert len(loop["steps"]) == 7
        assert loop["metric_shape"]["defense_count"] == 4
        assert loop["metric_shape"]["offense_metric"] == "proactive_resurfacing"
        assert loop["connector_persona"]["zh_name"] == "接引者"
        assert loop["connector_persona"]["zhiyi_remains_implicit"] is True

        status, plan = get_json(p6_port, "/api/v1/zhixing/replay/plan")
        assert status == 200
        assert plan["comparison_sets"] == ["no_memory", "zhiyi_only", "zhiyi_plus_xingce"]

        status, benchmark_plan = get_json(p6_port, "/api/v1/zhixing/benchmark/plan")
        assert status == 200
        assert benchmark_plan["comparison_sets"] == ["no_memory", "zhiyi_only", "zhiyi_plus_xingce"]
        assert benchmark_plan["promotion_rule"]["queue_should_wait_for_benchmark"] is True

        status, note_contract = get_json(p6_port, "/api/v1/zhixing/library-note-projection/contract")
        assert status == 200
        assert note_contract["not_a_new_memory_layer"] is True
        assert note_contract["requires_obsidian"] is False
        assert note_contract["projection_of"] == "zhixing_library_five_shelves"

        status, admission_contract = get_json(p6_port, "/api/v1/zhixing/admission-candidates/contract")
        assert status == 200
        assert admission_contract["not_durable_memory"] is True
        assert "write_markdown_file" in admission_contract["forbidden_by_default"]

        status, evolution_contract = get_json(p6_port, "/api/v1/zhixing/experience-evolution/contract")
        assert status == 200
        assert evolution_contract["contract"] == "zhixing_library_experience_evolution_candidates.v1"
        assert evolution_contract["not_a_new_memory_layer"] is True
        assert "auto_adopt_experience" in evolution_contract["forbidden_by_default"]

        status, review_action_contract = get_json(p6_port, "/api/v1/zhixing/experience-review-actions/contract")
        assert status == 200
        assert review_action_contract["contract"] == "zhixing_library_experience_review_action.v1"
        assert review_action_contract["source_contract"] == "zhixing_library_experience_evolution_candidates.v1"
        assert review_action_contract["not_a_new_memory_layer"] is True
        assert review_action_contract["allowed_actions"] == ["approve", "reject", "defer", "request_evidence"]
        assert "change_candidate_status" in review_action_contract["forbidden_by_default"]

        status, review_queue_contract = get_json(p6_port, "/api/v1/zhixing/experience-review-queue/contract")
        assert status == 200
        assert review_queue_contract["contract"] == "zhixing_library_experience_review_queue.v1"
        assert review_queue_contract["read_only"] is True
        assert review_queue_contract["queue_buckets"] == [
            "ready_for_review",
            "needs_validation",
            "needs_source_evidence",
            "should_errata",
            "defer",
        ]
        assert "change_candidate_status" in review_queue_contract["forbidden_by_default"]

        status, review_apply_gate_contract = get_json(p6_port, "/api/v1/zhixing/experience-review-actions/apply-gate/contract")
        assert status == 200
        assert review_apply_gate_contract["contract"] == "zhixing_library_experience_review_apply_gate.v1"
        assert review_apply_gate_contract["source_contract"] == "zhixing_library_experience_review_action.v1"
        assert review_apply_gate_contract["read_only"] is True
        assert "confirm_review_action_intent" in review_apply_gate_contract["authorization_required"]

        status, validation_report_contract = get_json(p6_port, "/api/v1/zhixing/experience-validation-report/contract")
        assert status == 200
        assert validation_report_contract["contract"] == "zhixing_library_experience_validation_report.v1"
        assert validation_report_contract["read_only"] is True
        assert validation_report_contract["not_a_new_memory_layer"] is True
        assert "treat_boolean_confirmation_as_validation_evidence" in validation_report_contract["forbidden_by_default"]

        status, validation_receipts_contract = get_json(p6_port, "/api/v1/zhixing/experience-validation-receipts/contract")
        assert status == 200
        assert validation_receipts_contract["contract"] == "zhixing_library_experience_validation_receipt_schema.v1"
        assert validation_receipts_contract["source_contract"] == "zhixing_library_experience_validation_report.v1"
        assert validation_receipts_contract["read_only"] is True
        assert validation_receipts_contract["not_a_new_memory_layer"] is True
        assert "write_validation_result" in validation_receipts_contract["forbidden_by_default"]
        assert "change_candidate_status" in validation_receipts_contract["forbidden_by_default"]

        status, apply_receipt_contract = get_json(p6_port, "/api/v1/zhixing/experience-apply-receipts/contract")
        assert status == 200
        assert apply_receipt_contract["contract"] == "zhixing_library_experience_apply_receipt_schema.v1"
        assert apply_receipt_contract["source_contract"] == "zhixing_library_experience_review_apply_gate.v1"
        assert apply_receipt_contract["read_only"] is True
        assert "experience_rollback_receipt" in apply_receipt_contract["receipt_types"]

        status, apply_package_contract = get_json(p6_port, "/api/v1/zhixing/experience-apply-package/contract")
        assert status == 200
        assert apply_package_contract["contract"] == "zhixing_library_experience_apply_package.v1"
        assert apply_package_contract["read_only"] is True
        assert apply_package_contract["not_a_new_memory_layer"] is True
        assert "write_apply_receipt" in apply_package_contract["forbidden_by_default"]
        assert "change_candidate_status" in apply_package_contract["forbidden_by_default"]

        status, flow_overview_contract = get_json(p6_port, "/api/v1/zhixing/experience-flow-overview/contract")
        assert status == 200
        assert flow_overview_contract["contract"] == "zhixing_library_experience_flow_overview.v1"
        assert flow_overview_contract["read_only"] is True
        assert flow_overview_contract["stage_count"] == 8
        assert "write_xingce" in flow_overview_contract["forbidden_everywhere"]
        assert "auto_adopt_experience" in flow_overview_contract["forbidden_everywhere"]

        status, trust_dashboard = get_json(p6_port, "/api/v1/zhixing/library-trust-dashboard?limit=3")
        assert status == 200
        assert trust_dashboard["contract"] == "zhixing_library_trust_dashboard.v1"
        assert trust_dashboard["read_only"] is True
        assert trust_dashboard["write_performed"] is False
        assert trust_dashboard["data_source"] == "real_zhixing_library"
        assert trust_dashboard["trust_doctor"]["contract"] == "zhixing_library_trust_doctor.v1"
        assert trust_dashboard["experience_evolution"]["contract"] == "zhixing_library_experience_evolution_candidates.v1"
        assert trust_dashboard["experience_evolution"]["write_performed"] is False

        status, routes = get_json(p6_port, "/api/v1/dialog/intent-routes")
        assert status == 200
        assert routes["read_only"] is True
        assert routes["write_performed"] is False
        assert "correction_errata" in routes["routes"]
        assert "method_signal" in routes["routes"]
        assert "state_ledger" in routes["routes"]
        assert "context_unit" in routes["routes"]

        status, memory_routing = get_json(p6_port, "/api/v1/memory-routing/status")
        assert status == 200
        assert memory_routing["contract"] == "active_memory_routing.v2026.7.15"
        assert memory_routing["read_only"] is True
        assert memory_routing["write_performed"] is False
        assert memory_routing["platform_write_performed"] is False
        assert memory_routing["memory_write_performed"] is False
        assert memory_routing["recall_performed"] is False
        assert memory_routing["raw_excerpt_returned"] is False
        assert memory_routing["default_memory_scope"] == "active"
        assert memory_routing["ordinary_client_contract"]["requires_current_window_identity"] is False
        assert memory_routing["ordinary_client_contract"]["missing_identity_status"] == "active_layered"
        assert memory_routing["ordinary_client_contract"]["missing_identity_is_not_no_memory"] is True
        assert memory_routing["ordinary_client_contract"]["window_scope_is_strict_when_explicit"] is True
        assert memory_routing["ordinary_client_contract"]["active_recall_is_window_first_not_window_only"] is True
        assert memory_routing["ordinary_client_contract"]["cross_window_requires_explicit_flag"] is True
        assert memory_routing["example_resolutions"]["ordinary_window_without_identity"]["recall_status"] == "window_identity_required"
        assert memory_routing["example_resolutions"]["ordinary_raw_pool_without_flag"]["cross_window_read_allowed"] is False
        assert memory_routing["cross_window_authorization"]["identity_based_exceptions"] == []
        assert memory_routing["example_resolutions"]["second_client_raw_pool_without_flag"]["recall_status"] == "cross_window_permission_required"
        assert memory_routing["example_resolutions"]["second_client_raw_pool_without_flag"]["cross_window_read_allowed"] is False
        assert memory_routing["example_resolutions"]["raw_pool_with_explicit_flag"]["cross_window_read_allowed"] is True
        assert memory_routing["example_resolutions"]["raw_pool_with_explicit_flag"]["cross_window_permission_explicit"] is True
        assert memory_routing["example_resolutions"]["raw_pool_with_explicit_flag"]["same_result_for_second_client"] is True
        assert memory_routing["example_resolutions"]["raw_pool_with_explicit_flag"]["cross_window_reason"] == "skill_generation"

        status, record_doctor = get_json(p6_port, "/api/v1/records/doctor?limit=3")
        assert status == 200
        assert record_doctor["contract"] == "record_chain_doctor.v1"
        assert record_doctor["read_only"] is True
        assert record_doctor["write_performed"] is False
        assert record_doctor["not_memory_wall"] is True

        status, record_timeline = get_json(p6_port, "/api/v1/records/timeline?limit=3")
        assert status == 200
        assert record_timeline["contract"] == "record_chain_timeline.v1"
        assert record_timeline["timeline_kind"] == "record_chain"
        assert record_timeline["record_chains"][0]["stages"][0]["id"] == "source_record"
        assert record_timeline["record_chains"][0]["stages"][-1]["id"] == "memory_experience"

        status, record_replay = get_json(p6_port, "/api/v1/records/replay?session_id=session-1")
        assert status == 200
        assert record_replay["contract"] == "record_chain_replay.v1"
        assert record_replay["replay_kind"] == "record_chain"
        assert record_replay["read_only"] is True

        status, model_facts_plan = get_json(p6_port, "/api/v1/model-facts/plan")
        assert status == 200
        assert model_facts_plan["read_only"] is True
        assert model_facts_plan["write_performed"] is False
        assert "detected_is_not_runnable" in model_facts_plan["contracts"]
        assert "platform_configs_are_never_written" in model_facts_plan["contracts"]

        status, model_facts = get_json(p6_port, "/api/v1/model-facts")
        assert status == 200
        assert model_facts["read_only"] is True
        assert model_facts["platform_write_performed"] is False
        assert model_facts["runtime_boundary"]["time_library_is_not_a_model_center"] is True
        assert model_facts["runtime_boundary"]["platform_writeback_allowed"] is False
        assert model_facts["detected_is_not_runnable"] is True

        status, autodiscovery = get_json(p6_port, "/api/v1/platforms/autodiscovery")
        assert status == 200
        assert autodiscovery["name"] == "Time Library"
        assert autodiscovery["read_only"] is True
        assert autodiscovery["platform_write_performed"] is False
        assert autodiscovery["connection_contract"]["default_connection_mode"] == "host_self_install_then_verified_self_report"
        assert autodiscovery["connection_contract"]["can_auto_connect_supported_configs"] is False
        assert autodiscovery["connection_contract"]["time_library_writes_host_config"] is False
        assert autodiscovery["connection_contract"]["unknown_clients_admitted_by_generic_self_report"] is True
        assert autodiscovery["connection_contract"]["conversation_import_mode"] == "verified_format_collectors"
        assert autodiscovery["thin_adapter_registry"]["read_only"] is True
        assert "cursor" in autodiscovery["known_adapter_targets"]
        assert autodiscovery["platform_catalog"]["github_watchlist_entry_count"] >= 99

        status, platform_catalog = get_json(p6_port, "/api/v1/platforms/catalog")
        assert status == 200
        assert platform_catalog["contract"] == "platform_catalog.v1"
        assert platform_catalog["read_only"] is True
        assert platform_catalog["platform_write_performed"] is False
        assert platform_catalog["curated_entry_count"] >= 12
        assert platform_catalog["github_watchlist_entry_count"] >= 99

        status, package_inventory = get_json(p6_port, "/api/v1/platforms/package-manager-inventory")
        assert status == 200
        assert package_inventory["contract"] == "package_manager_agent_inventory.v1"
        assert package_inventory["read_only"] is True
        assert package_inventory["platform_write_performed"] is False
        assert package_inventory["global_guarantees"]["does_not_install_packages"] is True

        status, raw_layout = get_json(p6_port, "/api/v1/raw/archive-layout")
        assert status == 200
        assert raw_layout["contract"] == "raw_archive_layout.v1"
        assert raw_layout["read_only"] is True
        assert raw_layout["effective_from_version"] == "2026.6.1"
        assert raw_layout["new_install_default_layout"] == "computer_first"
        assert raw_layout["new_raw_writes_must_use_preferred_layout"] is True
        assert raw_layout["preferred_segment_order"] == [
            "computer_name",
            "source_system",
            "native_artifact_format",
        ]
        assert raw_layout["primary_partition_key"] == "computer_name"
        assert raw_layout["secondary_partition_key"] == "source_system"
        assert raw_layout["legacy_layout_status"] == "read_compatibility_only"
        assert raw_layout["legacy_layout_allowed_for_new_writes"] is False

        status, raw_layout_audit = get_json(p6_port, "/api/v1/raw/archive-layout/audit")
        assert status == 200
        assert raw_layout_audit["contract"] == "raw_archive_layout_audit.v1"
        assert raw_layout_audit["read_only"] is True
        assert raw_layout_audit["new_raw_writes_must_use_preferred_layout"] is True
        assert raw_layout_audit["legacy_layout_allowed_for_new_writes"] is False
        assert "computer_first_files" in raw_layout_audit["totals"]
        assert "legacy_source_first_files" in raw_layout_audit["totals"]

        status, thin_adapter_registry = get_json(p6_port, "/api/v1/platforms/thin-adapter-registry")
        assert status == 200
        assert thin_adapter_registry["contract"] == "thin_adapter_registry.v1"
        assert thin_adapter_registry["read_only"] is True
        assert thin_adapter_registry["platform_write_performed"] is False
        assert thin_adapter_registry["github_watchlist_entry_count"] >= 99
        assert any(item["system"] == "cursor" for item in thin_adapter_registry["adapters"])
        assert any(
            item["system"] == "claude_code_cli"
            and item["current_focus"] is True
            and item["support_level"] == "adapter_candidate_separate_claude_surface"
            for item in thin_adapter_registry["adapters"]
        )
        assert all("connectable_now" in item for item in thin_adapter_registry["adapters"])
        assert all("mcp_config_detected" in item for item in thin_adapter_registry["adapters"])
        assert all("memcore_mcp_detected" in item for item in thin_adapter_registry["adapters"])
        assert thin_adapter_registry["generic_surface_discovery"]["contract"] == "generic_local_ai_surface_discovery.v1"

        status, discovery_dashboard = get_json(p6_port, "/api/v1/platforms/discovery-dashboard")
        assert status == 200
        assert discovery_dashboard["contract"] == "platform_discovery_dashboard.v1"
        assert discovery_dashboard["read_only"] is True
        assert discovery_dashboard["platform_write_performed"] is False
        assert discovery_dashboard["global_guarantees"]["auto_connect_supported_skill_mcp_surfaces"] is False
        assert discovery_dashboard["global_guarantees"]["time_library_platform_write_supported"] is False
        assert discovery_dashboard["global_guarantees"]["host_owns_platform_config_and_rollback"] is True
        assert discovery_dashboard["global_guarantees"]["unknown_clients_admitted_by_generic_self_report"] is True
        assert discovery_dashboard["global_guarantees"]["conversation_import_mode"] == "verified_format_collectors"
        assert "ready_for_capability_check" in discovery_dashboard["counts"]
        assert discovery_dashboard["view"] == "public"
        assert "other_local_tools" in discovery_dashboard["counts"]
        assert "recently_quiet_tools" in discovery_dashboard["counts"]
        assert discovery_dashboard["global_guarantees"]["new_memory_layout"] == "computer_first"
        assert discovery_dashboard["global_guarantees"]["legacy_memory_layout"] == "read_compatibility_only"
        assert all("safe_next_step" in item for item in discovery_dashboard["items"])
        assert all(item["writes_now"] is False for item in discovery_dashboard["items"])

        serialized_dashboard = json.dumps(discovery_dashboard, ensure_ascii=False)
        for hidden_term in [
            "github_watchlist",
            "platform_catalog",
            "thin_adapter",
            "catalog_watchlist",
            "generic_local_ai_surface",
            "known_thin_adapter",
            "support_level",
            "surface_type",
            "mcp_config_detected",
            "memcore_mcp_detected",
            "authorized_connect_plan_endpoint",
            "/api/v1/platforms/thin-adapter-registry",
            "/api/v1/platforms/authorized-auto-connect/dry-run",
        ]:
            assert hidden_term not in serialized_dashboard

        status, internal_dashboard = get_json(p6_port, "/api/v1/platforms/discovery-dashboard?view=internal")
        assert status == 200
        assert internal_dashboard["view"] == "internal"
        assert internal_dashboard["counts"]["catalog_watchlist"] >= 99
        assert internal_dashboard["links"]["platform_catalog"] == "/api/v1/platforms/catalog"
        assert internal_dashboard["links"]["package_manager_inventory"] == "/api/v1/platforms/package-manager-inventory"
        assert internal_dashboard["global_guarantees"]["raw_archive_layout_order"] == [
            "computer_name",
            "source_system",
            "native_artifact_format",
        ]
        assert internal_dashboard["global_guarantees"]["raw_archive_primary_partition_key"] == "computer_name"
        assert internal_dashboard["global_guarantees"]["raw_archive_secondary_partition_key"] == "source_system"
        assert internal_dashboard["global_guarantees"]["raw_archive_effective_from_version"] == "2026.6.1"
        assert internal_dashboard["global_guarantees"]["raw_archive_new_install_default_layout"] == "computer_first"
        assert internal_dashboard["global_guarantees"]["raw_archive_legacy_layout_status"] == "read_compatibility_only"
        assert internal_dashboard["global_guarantees"]["raw_archive_legacy_layout_allowed_for_new_writes"] is False

        status, generic_surfaces = get_json(p6_port, "/api/v1/platforms/generic-local-ai-surfaces")
        assert status == 200
        assert generic_surfaces["contract"] == "generic_local_ai_surface_discovery.v1"
        assert generic_surfaces["read_only"] is True
        assert generic_surfaces["platform_write_performed"] is False

        status, model_identification = get_json(p6_port, "/api/v1/platforms/model-identification")
        assert status == 200
        assert model_identification["contract"] == "local_ai_tool_model_identification.v1"
        assert model_identification["read_only"] is True
        assert model_identification["platform_write_performed"] is False
        assert model_identification["memory_write_performed"] is False
        assert model_identification["input_kind"] == "local_metadata_only"
        assert model_identification["scan_mode"] == "fast_snapshot"
        assert model_identification["execute_requested"] is False
        assert model_identification["model_call_performed"] is False
        assert "items" in model_identification

        status, fast_model_identification = get_json(p6_port, "/api/v1/platforms/model-identification?scan=fast")
        assert status == 200
        assert fast_model_identification["scan_mode"] == "fast_snapshot"
        assert fast_model_identification["summary"]["surface_count"] == 0

        status, smart_model_identification = get_json(p6_port, "/api/v1/platforms/model-identification?scan=smart")
        assert status == 200
        assert smart_model_identification["scan_mode"] == "smart"

        status, provisional_candidates = get_json(p6_port, "/api/v1/platforms/provisional-adapter-candidates")
        assert status == 200
        assert provisional_candidates["contract"] == "provisional_adapter_candidates.v1"
        assert provisional_candidates["read_only"] is True
        assert provisional_candidates["platform_write_performed"] is False
        assert provisional_candidates["memory_write_performed"] is False
        assert provisional_candidates["scan_mode"] == "fast_snapshot"
        assert provisional_candidates["execute_requested"] is False
        assert "candidates" in provisional_candidates

        status, fast_provisional_candidates = get_json(p6_port, "/api/v1/platforms/provisional-adapter-candidates?scan=fast")
        assert status == 200
        assert fast_provisional_candidates["scan_mode"] == "fast_snapshot"
        assert fast_provisional_candidates["candidate_count"] == 0

        status, smart_provisional_candidates = get_json(p6_port, "/api/v1/platforms/provisional-adapter-candidates?scan=smart")
        assert status == 200
        assert smart_provisional_candidates["scan_mode"] == "smart"

        status, auto_connect_dry_run = get_json(p6_port, "/api/v1/platforms/authorized-auto-connect/dry-run")
        assert status == 200
        assert auto_connect_dry_run["contract"] == "authorized_auto_connect_dry_run.v1"
        assert auto_connect_dry_run["read_only"] is True
        assert auto_connect_dry_run["platform_write_performed"] is False
        assert auto_connect_dry_run["apply_endpoint_status"] == "host_self_install_receipt_only"
        assert auto_connect_dry_run["implemented_apply_systems"] == []
        assert auto_connect_dry_run["global_guarantees"]["host_owns_platform_config_and_rollback"] is True
        assert auto_connect_dry_run["global_guarantees"]["time_library_platform_write_supported"] is False
        assert auto_connect_dry_run["global_guarantees"]["conversation_import_mode"] == "verified_format_collectors"
        assert all("would_write" in item for item in auto_connect_dry_run["plans"])
        assert all("rollback_plan" in item for item in auto_connect_dry_run["plans"])
        assert all(item.get("plan_source") == "adapter_draft" for item in auto_connect_dry_run["plans"])
        assert all(item.get("adapter_draft_consumed") is True for item in auto_connect_dry_run["plans"])
        assert all("mcp_plan" in item for item in auto_connect_dry_run["plans"])
        assert all("collector_plan" in item for item in auto_connect_dry_run["plans"])
        assert all("raw_archive_plan" in item for item in auto_connect_dry_run["plans"])
        assert all((item.get("mcp_plan") or {}).get("would_write") == item.get("would_write") for item in auto_connect_dry_run["plans"])
        assert all((item.get("collector_plan") or {}).get("content_read") is False for item in auto_connect_dry_run["plans"])
        assert all((item.get("collector_plan") or {}).get("chat_body_included") is False for item in auto_connect_dry_run["plans"])
        assert all((item.get("raw_archive_plan") or {}).get("layout") == "computer_first" for item in auto_connect_dry_run["plans"])
        assert all((item.get("raw_archive_plan") or {}).get("segment_order") == [
            "computer_name",
            "source_system",
            "native_artifact_format",
        ] for item in auto_connect_dry_run["plans"])

        status, cursor_connect_plan = get_json(p6_port, "/api/v1/platforms/cursor/authorized-connect-plan")
        assert status == 200
        assert cursor_connect_plan["system_filter"] == "cursor"
        assert cursor_connect_plan["read_only"] is True
        assert cursor_connect_plan["platform_write_performed"] is False
        assert len(cursor_connect_plan["plans"]) == 1
        assert cursor_connect_plan["plans"][0]["plan_source"] == "adapter_draft"
        assert cursor_connect_plan["plans"][0]["adapter_draft_consumed"] is True
        assert cursor_connect_plan["plans"][0]["collector_plan"]["content_read"] is False
        assert cursor_connect_plan["plans"][0]["raw_archive_plan"]["layout"] == "computer_first"

        status, apply_gate_blocked = post_json(p6_port, "/api/v1/platforms/authorized-auto-connect/apply-gate/dry-run", {
            "system": "cursor",
        })
        assert status == 200
        assert apply_gate_blocked["contract"] == "authorized_auto_connect_apply_gate.v1"
        assert apply_gate_blocked["read_only"] is True
        assert apply_gate_blocked["platform_write_performed"] is False
        assert apply_gate_blocked["status"] == "blocked"
        assert apply_gate_blocked["missing_confirmations"] == []
        assert apply_gate_blocked["missing_host_capabilities"]
        assert set(apply_gate_blocked["blocked_reasons"]) == {
            "host_capability_declaration_incomplete",
            "host_install_not_reported",
            "host_install_receipt_missing",
            "verified_connection_receipt_id_missing",
        }
        if apply_gate_blocked["plan"]:
            assert apply_gate_blocked["plan"]["plan_source"] == "adapter_draft"
            assert apply_gate_blocked["receipt_preview"]["plan_source"] == "adapter_draft"
            assert apply_gate_blocked["receipt_preview"]["adapter_draft_consumed"] is True
            assert apply_gate_blocked["receipt_preview"]["mcp_plan"]["would_write"] == apply_gate_blocked["receipt_preview"]["would_write"]
            assert apply_gate_blocked["receipt_preview"]["collector_plan"]["content_read"] is False
            assert apply_gate_blocked["receipt_preview"]["collector_plan"]["chat_body_included"] is False
            assert apply_gate_blocked["receipt_preview"]["raw_archive_plan"]["layout"] == "computer_first"
        if apply_gate_blocked["status"] == "blocked":
            assert set(apply_gate_blocked["blocked_reasons"]).issubset({
                "system_required",
                "host_capability_declaration_incomplete",
                "host_install_not_reported",
                "host_install_receipt_missing",
                "verified_connection_receipt_id_missing",
                "verified_connection_receipt_not_found_or_identity_mismatch",
            })

        status, autoconnect_plan = get_json(p6_port, "/api/v1/platforms/authorized-auto-connect/plan")
        assert status == 200
        assert autoconnect_plan["read_only"] is True
        assert autoconnect_plan["apply_endpoint_status"] == "host_self_install_receipt_only"
        assert autoconnect_plan["required_confirmations"] == []
        assert "verified_connection_receipt" in autoconnect_plan["required_host_actions"]
        assert autoconnect_plan["time_library_platform_write_supported"] is False

        status, agent_entrypoints = get_json(p6_port, "/api/v1/platforms/agent-entrypoints/preview")
        assert status == 200
        assert agent_entrypoints["contract"] == "agent_native_entrypoints_preview.v1"
        assert agent_entrypoints["read_only"] is True
        assert agent_entrypoints["dry_run"] is True
        assert agent_entrypoints["write_performed"] is False
        assert agent_entrypoints["platform_write_performed"] is False
        assert agent_entrypoints["memory_write_performed"] is False
        assert agent_entrypoints["content_reads_performed"] is False
        assert agent_entrypoints["chat_body_included"] is False
        assert agent_entrypoints["model_call_performed"] is False
        assert agent_entrypoints["summary"]["writes_planned"] == 0
        assert agent_entrypoints["summary"]["entrypoint_count"] >= 6
        assert "codex" in {item["system"] for item in agent_entrypoints["entrypoints"]}
        assert "gemini_cli" in {item["system"] for item in agent_entrypoints["entrypoints"]}
        assert "github_copilot" in {item["system"] for item in agent_entrypoints["entrypoints"]}
        assert "Use Time Library as the standing memory rule" in json.dumps(agent_entrypoints, ensure_ascii=False)

        status, event_triggers = get_json(p6_port, "/api/v1/platforms/agent-event-triggers/preview")
        assert status == 200
        assert event_triggers["contract"] == "agent_event_trigger_preview.v1"
        assert event_triggers["read_only"] is True
        assert event_triggers["dry_run"] is True
        assert event_triggers["write_performed"] is False
        assert event_triggers["platform_write_performed"] is False
        assert event_triggers["memory_write_performed"] is False
        assert event_triggers["content_reads_performed"] is False
        assert event_triggers["chat_body_included"] is False
        assert event_triggers["model_call_performed"] is False
        assert event_triggers["summary"]["writes_planned"] == 0
        assert event_triggers["summary"]["platform_count"] >= 5
        assert "claude_code" in {item["system"] for item in event_triggers["platforms"]}
        assert "gemini_cli" in {item["system"] for item in event_triggers["platforms"]}
        assert "before_tool_use" in event_triggers["common_moments"]
        assert "session_end" in event_triggers["common_moments"]

        status, runnable_doctor_plan = get_json(p6_port, "/api/v1/model-facts/runnable-doctor/plan")
        assert status == 200
        assert runnable_doctor_plan["read_only"] is True
        assert runnable_doctor_plan["write_performed"] is False
        assert runnable_doctor_plan["smoke_endpoint"] == "/api/v1/model-facts/runnable-doctor/smoke"
        assert "confirm_live_runtime_smoke" in runnable_doctor_plan["authorization_required"]

        status, runnable_doctor_blocked = post_json(p6_port, "/api/v1/model-facts/runnable-doctor/smoke", {
            "platform": "hermes",
            "operator": "pytest-http-smoke",
            "reason": "missing confirmation",
        })
        assert status == 400
        assert runnable_doctor_blocked["ok"] is False
        assert runnable_doctor_blocked["runtime_smoke_performed"] is False
        assert runnable_doctor_blocked["write_performed"] is False
        assert "confirm_live_runtime_smoke" in runnable_doctor_blocked["missing_authorization"]

        status, method_contract = get_json(p6_port, "/api/v1/zhixing/method-signals/contract")
        assert status == 200
        assert method_contract["read_only"] is True
        assert method_contract["write_performed"] is False
        assert method_contract["candidate_type"] == "external_method_signal_candidate"
        assert "install_or_activate_skill" in method_contract["forbidden_by_default"]

        status, ledger_plan = get_json(p6_port, "/api/v1/zhixing/state-ledger/plan")
        assert status == 200
        assert ledger_plan["read_only"] is True
        assert ledger_plan["write_performed"] is False
        assert ledger_plan["temporal_index_role"] == "navigation_only_not_authority"

        status, unit_contract = get_json(p6_port, "/api/v1/zhixing/context-units/contract")
        assert status == 200
        assert unit_contract["read_only"] is True
        assert unit_contract["write_performed"] is False
        assert unit_contract["candidate_type"] == "context_budget_unit_candidate"

        status, docs_contract = get_json(p6_port, "/api/v1/zhixing/external-docs-evidence/contract")
        assert status == 200
        assert docs_contract["read_only"] is True
        assert docs_contract["write_performed"] is False
        assert docs_contract["candidate_type"] == "external_docs_evidence_plan"
        assert docs_contract["raw_source_root"] == "raw/external_docs/"
        assert docs_contract["third_party_tool_dependency"] is False

        status, compaction_contract = get_json(p6_port, "/api/v1/zhixing/context-delivery-compaction/contract")
        assert status == 200
        assert compaction_contract["read_only"] is True
        assert compaction_contract["write_performed"] is False
        assert compaction_contract["candidate_type"] == "context_delivery_compaction_plan"
        assert compaction_contract["context_package_role"] == "delivery_optimization_only"
        assert compaction_contract["raw_authority_preserved"] is True
        assert compaction_contract["third_party_tool_dependency"] is False
        assert "compress_user_intent" in compaction_contract["forbidden_by_default"]

        status, time_origin = get_json(p6_port, "/api/v1/tiandao/time-origin/contract")
        assert status == 200
        assert time_origin["ok"] is True
        assert time_origin["read_only"] is True
        assert time_origin["write_performed"] is False
        assert time_origin["contract"] == "tiandao_time_origin.v1"
        assert time_origin["zh_name"] == "时间起源"
        assert time_origin["origin_layer"] == "raw"
        assert time_origin["no_raw_no_river"] is True
        assert time_origin["multi_machine_policy"] == "source_streams_merge_not_overwrite"
        assert time_origin["platform_policy"] == "platforms_are_inlets_not_origin"
        assert time_origin["lost_source_label"] == "遗失源"
        assert time_origin["lost_raw_label"] == "遗失 raw"

        status, time_twin_star = get_json(p6_port, "/api/v1/tiandao/time-twin-star/status")
        assert status == 200
        assert time_twin_star["ok"] is True
        assert time_twin_star["contract"] == "time_twin_star_runtime_status.v1"
        assert time_twin_star["runtime_status"] == "source_runtime_route_present"
        assert time_twin_star["installed_runtime_status"] == "proven"
        assert time_twin_star["platform_delivery_status"] == "proven"
        assert time_twin_star["runtime_behavior_changed"] is True
        assert time_twin_star["platform_delivery_scope"] == "controlled_openclaw_smoke_path_only"
        assert time_twin_star["behavior_proof"]["trace_sufficient_for_behavior_proven"] is True
        assert time_twin_star["rule_status_counts"]["source_proven"] == 11
        assert time_twin_star["read_only"] is True
        assert time_twin_star["write_performed"] is False

        status, sediment_contract = get_json(p6_port, "/api/v1/tiandao/time-river-sediment/contract")
        assert status == 200
        assert sediment_contract["ok"] is True
        assert sediment_contract["read_only"] is True
        assert sediment_contract["write_performed"] is False
        assert sediment_contract["contract"] == "tiandao_time_river_sediment.v1"
        assert sediment_contract["zh_name"] == "时间长河沉积链"
        assert sediment_contract["time_origin_contract"] == "tiandao_time_origin.v1"
        assert sediment_contract["time_river_contract"] == "tiandao_time_river.v1"
        assert sediment_contract["trusted_status"] == "origin_linked"
        assert sediment_contract["raw_authority_policy"] == "raw_source_text_is_highest_authority"

        status, material_contract = get_json(p6_port, "/api/v1/zhixing/material-processing-pipeline/contract")
        assert status == 200
        assert material_contract["ok"] is True
        assert material_contract["read_only"] is True
        assert material_contract["write_performed"] is False
        assert material_contract["contract"] == "zhixing_material_processing_pipeline.v1"
        assert material_contract["zh_name"] == "资料处理流水线"
        assert material_contract["raw_authority_preserved"] is True
        assert material_contract["third_party_tool_dependency"] is False
        assert "batch_level_screening" in material_contract["pipeline_stages"]

        status, second_brain_contract = get_json(p6_port, "/api/v1/tiandao/second-brain/contract")
        assert status == 200
        assert second_brain_contract["ok"] is True
        assert second_brain_contract["read_only"] is True
        assert second_brain_contract["write_performed"] is False
        assert second_brain_contract["contract"] == "tiandao_second_brain.v1"
        assert second_brain_contract["zh_name"] == "第二大脑"
        assert second_brain_contract["en_name"] == "Second Brain"
        assert second_brain_contract["parent_tiandao_contract"] == "tiandao_time_river.v1"
        assert second_brain_contract["first_major_module_under_time_river"] is True

        status, replay = post_json(p6_port, "/api/v1/zhixing/replay/dry-run", {
            "case": {
                "case_id": "http-smoke",
                "expected_source_refs": ["raw/probe_logs/hermes-profile-effective-config.jsonl"],
                "expected_library_ids": ["ZX-XINGCE-HTTP"],
                "expected_behavior_markers": ["先查 profile config"],
                "forbidden_repeated_mistakes": ["改 root config 当默认继承"],
                "required_acceptance_checks": ["hermes profile show"],
                "expected_proactive_resurfacing": ["profile 无 config 显示 auto"],
            },
            "records": [
                {
                    "_type": "xingce_work_experience_candidate",
                    "library_id": "ZX-XINGCE-HTTP",
                    "exp_id": "xingce-http",
                    "summary": "Hermes 平台配置经验：先查 profile config，profile 无 config 显示 auto。",
                    "detail": "不要改 root config 当默认继承；验收用 hermes profile show。",
                    "source_refs": {
                        "source_system": "probe",
                        "source_path": "raw/probe_logs/hermes-profile-effective-config.jsonl",
                    },
                    "verbatim_excerpt": "profile 无 config 显示 auto；hermes profile show 可验收。",
                    "acceptance_checks": ["hermes profile show"],
                    "supersedes": [],
                    "conflicts_with": [],
                    "_xingce": {"candidate_id": "xingce-http", "lifecycle_status": "candidate"},
                },
            ],
        })
        assert status == 200
        assert replay["summary"]["best_mode"] == "zhiyi_plus_xingce"
        assert replay["summary"]["proactive_resurfacing_passed"] is True
        feedback = replay["feedback_candidates"]
        assert feedback["write_performed"] is False
        assert "replay_adoption_candidate" in feedback["candidate_types"]
        assert "proactive_resurfacing_candidate" in feedback["candidate_types"]

        status, sediment = post_json(p6_port, "/api/v1/tiandao/time-river-sediment/dry-run", {
            "record": {
                "library_id": "ZX-XINGCE-HTTP-SEDIMENT",
                "library_shelf": "xingce",
                "summary": "HTTP dry-run 回源挂接。",
                "source_refs": {
                    "source_system": "codex",
                    "session_id": "http-sediment",
                    "source_path": "/tmp/source.jsonl",
                    "raw_session_path": "/tmp/raw.jsonl",
                },
                "origin_event": {
                    "origin_id": "origin_http_sediment",
                    "origin_status": "origin_witnessed",
                    "origin_label": "起源已见证",
                },
            },
        })
        assert status == 200
        assert sediment["ok"] is True
        assert sediment["dry_run"] is True
        assert sediment["write_performed"] is False
        assert sediment["sediment"]["sediment_status"] == "origin_linked"
        assert sediment["sediment"]["trusted_sediment"] is True

        status, material = post_json(p6_port, "/api/v1/zhixing/material-processing-pipeline/dry-run", {
            "need": "整理 Codex raw 起源和记录守护资料",
            "batch_size": 2,
            "wip_limit": 1,
            "sources": [
                {
                    "title": "Codex raw origin report",
                    "path": "/notes/codex-raw-origin.md",
                    "summary": "Codex raw 起源、记录守护、回源证据。",
                    "priority": "high",
                },
                {
                    "title": "Unrelated color draft",
                    "path": "/notes/colors.md",
                    "summary": "颜色草稿。",
                },
            ],
        })
        assert status == 200
        assert material["ok"] is True
        assert material["dry_run"] is True
        assert material["write_performed"] is False
        assert material["summary"]["source_count"] == 2
        assert material["summary"]["batch_count"] == 1
        assert material["controls"]["wip_limit"] == 1
        assert material["policies"]["screening_policy"] == "metadata_before_full_text"

        status, second_brain = post_json(p6_port, "/api/v1/tiandao/second-brain/dry-run", {
            "need": "整理 Codex raw 起源和记录守护资料",
            "batch_size": 2,
            "wip_limit": 1,
            "sources": [
                {
                    "title": "Codex raw origin report",
                    "path": "/notes/codex-raw-origin.md",
                    "summary": "Codex raw 起源、记录守护、回源证据。",
                    "content": "Codex raw 起源需要记录守护，source_refs 与 verbatim excerpt 必须保留。",
                    "source_refs": {"source_path": "/notes/codex-raw-origin.md"},
                    "priority": "high",
                },
                {
                    "title": "Unrelated color draft",
                    "path": "/notes/colors.md",
                    "summary": "颜色草稿。",
                },
            ],
        })
        assert status == 200
        assert second_brain["ok"] is True
        assert second_brain["dry_run"] is True
        assert second_brain["write_performed"] is False
        assert second_brain["contract"] == "tiandao_second_brain.v1"
        assert second_brain["summary"]["source_count"] == 2
        assert second_brain["summary"]["evidence_plan_count"] == 1
        assert second_brain["receipt"]["contract"] == "second_brain_receipt.v1"
        assert second_brain["policies"]["raw_origin_policy"] == "second_brain_does_not_replace_time_origin"

        status, benchmark = post_json(p6_port, "/api/v1/zhixing/benchmark/dry-run", {
            "cases": [
                {
                    "case_id": "http-benchmark",
                    "query": "继续 Hermes 配置真实生效验证",
                    "expected_source_refs": ["raw/probe_logs/hermes-profile-effective-config.jsonl"],
                    "expected_library_ids": ["ZX-XINGCE-HTTP"],
                    "expected_behavior_markers": ["先查 profile config"],
                    "forbidden_repeated_mistakes": ["改 root config 当默认继承"],
                    "required_acceptance_checks": ["hermes profile show"],
                    "expected_proactive_resurfacing": ["profile 无 config 显示 auto"],
                    "records": [
                        {
                            "_type": "xingce_work_experience_candidate",
                            "library_id": "ZX-XINGCE-HTTP",
                            "exp_id": "xingce-http",
                            "summary": "Hermes 平台配置经验：先查 profile config，profile 无 config 显示 auto。",
                            "detail": "不要改 root config 当默认继承；验收用 hermes profile show。",
                            "source_refs": {
                                "source_system": "probe",
                                "source_path": "raw/probe_logs/hermes-profile-effective-config.jsonl",
                            },
                            "verbatim_excerpt": "profile 无 config 显示 auto；hermes profile show 可验收。",
                            "acceptance_checks": ["hermes profile show"],
                            "supersedes": [],
                            "conflicts_with": [],
                            "_xingce": {"candidate_id": "xingce-http", "lifecycle_status": "candidate"},
                        },
                    ],
                },
            ],
        })
        assert status == 200
        assert benchmark["case_count"] == 1
        assert benchmark["summary"]["best_mode"] == "zhiyi_plus_xingce"
        assert benchmark["summary"]["xingce_signal_detected"] is True
        assert benchmark["summary"]["queue_should_wait_for_benchmark"] is True
        assert benchmark["summary"]["machine_ascension_not_claimed"] is True
        assert benchmark["write_performed"] is False

        status, note_projection = post_json(p6_port, "/api/v1/zhixing/library-note-projection/dry-run", {
            "record": {
                "_type": "xingce_work_experience_candidate",
                "library_id": "ZX-XINGCE-HTTP-NOTE",
                "summary": "HTTP smoke 经验：馆藏注记只是五层书架投影。",
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "raw/codex/http-library-note.jsonl",
                },
                "verbatim_excerpt": "馆藏注记只是五层书架投影，不是第六层。",
                "supersedes": [],
                "conflicts_with": [],
                "_xingce": {"candidate_id": "http-note", "lifecycle_status": "candidate"},
            }
        })
        assert status == 200
        assert note_projection["dry_run"] is True
        assert note_projection["write_performed"] is False
        assert note_projection["projection"]["not_a_new_memory_layer"] is True
        assert note_projection["projection"]["requires_obsidian"] is False
        assert "library_id: \"ZX-XINGCE-HTTP-NOTE\"" in note_projection["markdown"]

        status, admission = post_json(p6_port, "/api/v1/zhixing/admission-candidates/dry-run", {
            "source_type": "markdown_note",
            "target_shelf": "xingce",
            "title": "馆藏注记方向",
            "text": "馆藏注记是五层书架的 AI 可读投影，不依赖 Obsidian。",
            "source_refs": {
                "source_system": "local_note",
                "source_path": "raw/external_docs/library-note-direction.jsonl",
            },
            "verbatim_excerpt": "馆藏注记是五层书架的 AI 可读投影，不依赖 Obsidian。",
        })
        assert status == 200
        assert admission["dry_run"] is True
        assert admission["write_performed"] is False
        assert admission["target_shelf"] == "xingce"
        assert admission["library_note_projection"]["not_a_new_memory_layer"] is True
        assert "admission_candidate_is_not_durable_memory" in admission["notes"]

        status, active = post_json(p6_port, "/api/v1/zhixing/active-bookmarks/dry-run", {
            "query": "发布前检查这条旧记录是不是不对",
            "limit": 2,
            "records": [
                {
                    "_type": "xingce_work_experience_candidate",
                    "library_id": "ZX-XINGCE-HTTP-ACTIVE",
                    "summary": "发布前先跑记录医生。",
                    "source_refs": {
                        "source_system": "codex",
                        "source_path": "raw/codex/http-active.jsonl",
                    },
                    "verbatim_excerpt": "发布前先跑记录医生。",
                    "acceptance_checks": ["record doctor passed"],
                    "supersedes": [],
                    "conflicts_with": [],
                    "_xingce": {"candidate_id": "http-active", "lifecycle_status": "candidate"},
                },
                {
                    "type": "case_memory",
                    "library_shelf": "errata",
                    "library_id": "ZX-ERRATA-HTTP-ACTIVE",
                    "summary": "旧记录已废弃。",
                    "source_refs": {
                        "source_system": "codex",
                        "source_path": "raw/codex/http-errata.jsonl",
                    },
                    "verbatim_excerpt": "旧记录已废弃。",
                    "status": "superseded",
                    "supersedes": ["ZX-XINGCE-OLD"],
                    "conflicts_with": ["ZX-XINGCE-OLD"],
                },
            ],
        })
        assert status == 200
        assert active["dry_run"] is True
        assert active["write_performed"] is False
        assert active["not_a_new_memory_layer"] is True
        assert active["global_memory_scan_performed"] is False
        assert active["bookmarks"][0]["library_id"] == "ZX-ERRATA-HTTP-ACTIVE"
        assert active["recall_volume_control"]["output_count"] == 2

        status, history = post_json(p6_port, "/api/v1/zhixing/experience-history/dry-run", {
            "records": [
                {
                    "_type": "xingce_work_experience_candidate",
                    "library_id": "ZX-XINGCE-HTTP-HISTORY",
                    "summary": "发布前先跑记录医生。",
                    "source_refs": {
                        "source_system": "codex",
                        "source_path": "raw/codex/http-history.jsonl",
                    },
                    "verbatim_excerpt": "发布前先跑记录医生。",
                    "acceptance_checks": ["record doctor passed"],
                    "supersedes": [],
                    "conflicts_with": [],
                    "_xingce": {"candidate_id": "http-history", "lifecycle_status": "candidate"},
                }
            ],
            "events": [
                {"library_id": "ZX-XINGCE-HTTP-HISTORY", "event_type": "replay_passed", "at": "2026-06-14T10:00:00Z"}
            ],
        })
        assert status == 200
        assert history["dry_run"] is True
        assert history["write_performed"] is False
        assert history["not_a_new_memory_layer"] is True
        assert history["histories"][0]["library_id"] == "ZX-XINGCE-HTTP-HISTORY"
        assert history["histories"][0]["validation_status"] == "validated"

        status, trust_doctor = post_json(p6_port, "/api/v1/zhixing/library-trust-doctor/dry-run", {
            "query": "发布前检查",
            "records": [
                {
                    "_type": "xingce_work_experience_candidate",
                    "library_id": "ZX-XINGCE-HTTP-DOCTOR",
                    "summary": "发布前先跑记录医生。",
                    "source_refs": {
                        "source_system": "codex",
                        "source_path": "raw/codex/http-doctor.jsonl",
                    },
                    "verbatim_excerpt": "发布前先跑记录医生。",
                    "acceptance_checks": ["record doctor passed"],
                    "supersedes": [],
                    "conflicts_with": [],
                    "_xingce": {"candidate_id": "http-doctor", "lifecycle_status": "candidate"},
                }
            ],
            "events": [
                {"library_id": "ZX-XINGCE-HTTP-DOCTOR", "event_type": "replay_passed", "at": "2026-06-14T10:00:00Z"}
            ],
        })
        assert status == 200
        assert trust_doctor["dry_run"] is True
        assert trust_doctor["write_performed"] is False
        assert trust_doctor["doctor_status"] == "records_guarded"
        assert trust_doctor["active_bookmarks"]["bookmarks"][0]["library_id"] == "ZX-XINGCE-HTTP-DOCTOR"
        assert trust_doctor["experience_history"]["histories"][0]["validation_status"] == "validated"

        status, library_index = post_json(p6_port, "/api/v1/zhixing/library-index-projection/dry-run", {
            "title": "HTTP 馆藏目录",
            "records": [
                {
                    "type": "preference_memory",
                    "library_id": "ZX-ZHIYI-HTTP-INDEX",
                    "summary": "用户偏好：先给结论。",
                    "source_refs": {
                        "source_system": "codex",
                        "source_path": "raw/codex/http-index-pref.jsonl",
                    },
                    "verbatim_excerpt": "先给结论。",
                    "supersedes": [],
                    "conflicts_with": [],
                },
                {
                    "_type": "xingce_work_experience_candidate",
                    "library_id": "ZX-XINGCE-HTTP-INDEX",
                    "summary": "发布前先跑记录医生。",
                    "source_refs": {
                        "source_system": "codex",
                        "source_path": "raw/codex/http-index-xingce.jsonl",
                    },
                    "verbatim_excerpt": "发布前先跑记录医生。",
                    "acceptance_checks": ["record doctor passed"],
                    "supersedes": [],
                    "conflicts_with": [],
                    "_xingce": {"candidate_id": "http-index", "lifecycle_status": "candidate"},
                },
            ],
        })
        assert status == 200
        assert library_index["dry_run"] is True
        assert library_index["write_performed"] is False
        assert library_index["markdown_write_performed"] is False
        assert library_index["not_a_new_memory_layer"] is True
        assert library_index["requires_obsidian"] is False
        assert library_index["index"]["shelf_index"]["zhiyi"]["count"] == 1
        assert "`ZX-XINGCE-HTTP-INDEX`" in library_index["markdown"]

        status, evolution = post_json(p6_port, "/api/v1/zhixing/experience-evolution/dry-run", {
            "records": [
                {
                    "_type": "xingce_work_experience_candidate",
                    "library_id": "ZX-XINGCE-HTTP-EVOLUTION",
                    "summary": "发布前先跑记录医生。",
                    "source_refs": {
                        "source_system": "codex",
                        "source_path": "raw/codex/http-evolution.jsonl",
                    },
                    "verbatim_excerpt": "发布前先跑记录医生。",
                    "acceptance_checks": ["record doctor passed"],
                    "supersedes": [],
                    "conflicts_with": [],
                    "_xingce": {"candidate_id": "http-evolution", "lifecycle_status": "candidate"},
                },
                {
                    "type": "case_memory",
                    "library_id": "ZX-ZHIYI-HTTP-MISSING",
                    "summary": "只有总结没有来源。",
                    "supersedes": [],
                    "conflicts_with": [],
                },
            ],
        })
        assert status == 200
        assert evolution["dry_run"] is True
        assert evolution["write_performed"] is False
        assert evolution["raw_write_performed"] is False
        assert evolution["memory_write_performed"] is False
        assert evolution["platform_write_performed"] is False
        assert evolution["markdown_write_performed"] is False
        assert evolution["not_a_new_memory_layer"] is True
        assert evolution["target_shelf_counts"]["xingce"] >= 1
        assert "experience_errata_candidate" in evolution["candidate_types"]
        source_backed_candidate = next(
            candidate for candidate in evolution["candidates"]
            if candidate["target_shelf"] == "xingce"
            and candidate.get("source_refs")
        )

        status, review_action = post_json(p6_port, "/api/v1/zhixing/experience-review-actions/dry-run", {
            "experience_evolution": evolution,
            "actions": [
                {
                    "candidate_id": source_backed_candidate["candidate_id"],
                    "action": "approve",
                    "reason": "HTTP smoke review only.",
                }
            ],
        })
        assert status == 200
        assert review_action["contract"] == "zhixing_library_experience_review_action.v1"
        assert review_action["dry_run"] is True
        assert review_action["write_performed"] is False
        assert review_action["raw_write_performed"] is False
        assert review_action["memory_write_performed"] is False
        assert review_action["platform_write_performed"] is False
        assert review_action["markdown_write_performed"] is False
        assert review_action["authorization_required_for_apply"] is True
        assert review_action["review_actions"][0]["planned_lifecycle_status"] == "pending_authorized_adoption"
        assert review_action["review_actions"][0]["adoption_status"] == "not_adopted_in_dry_run"
        assert review_action["review_actions"][0]["receipt_preview"]["would_write"] is False

        status, validation_report = post_json(p6_port, "/api/v1/zhixing/experience-validation-report/dry-run", {
            "experience_review_actions": review_action,
            "experience_history": {
                "histories": [
                    {
                        "library_id": "ZX-XINGCE-HTTP-EVOLUTION",
                        "validation_status": "validated",
                        "replay_count": 1,
                    }
                ]
            },
        })
        assert status == 200
        assert validation_report["contract"] == "zhixing_library_experience_validation_report.v1"
        assert validation_report["dry_run"] is True
        assert validation_report["read_only"] is True
        assert validation_report["write_performed"] is False
        assert validation_report["xingce_write_performed"] is False
        assert validation_report["markdown_write_performed"] is False
        assert validation_report["report_passed"] is True
        assert validation_report["validation_issue_count"] == 0

        status, validation_receipts = post_json(p6_port, "/api/v1/zhixing/experience-validation-receipts/dry-run", {
            "experience_review_actions": review_action,
            "experience_validation_report": validation_report,
        })
        assert status == 200
        assert validation_receipts["contract"] == "zhixing_library_experience_validation_receipt_schema.v1"
        assert validation_receipts["dry_run"] is True
        assert validation_receipts["read_only"] is True
        assert validation_receipts["write_performed"] is False
        assert validation_receipts["raw_write_performed"] is False
        assert validation_receipts["xingce_write_performed"] is False
        assert validation_receipts["markdown_write_performed"] is False
        assert validation_receipts["validation_result_write_performed"] is False
        assert validation_receipts["candidate_status_change_performed"] is False
        assert validation_receipts["receipt_count"] >= 1
        assert validation_receipts["would_allow_apply_gate_count"] >= 1
        assert validation_receipts["validation_receipts"][0]["would_allow_apply_gate"] is True

        status, review_queue = post_json(p6_port, "/api/v1/zhixing/experience-review-queue/dry-run", {
            "experience_evolution": evolution,
            "experience_review_actions": review_action,
            "experience_validation_report": validation_report,
        })
        assert status == 200
        assert review_queue["contract"] == "zhixing_library_experience_review_queue.v1"
        assert review_queue["dry_run"] is True
        assert review_queue["read_only"] is True
        assert review_queue["write_performed"] is False
        assert review_queue["xingce_write_performed"] is False
        assert review_queue["markdown_write_performed"] is False
        assert review_queue["queue_count"] >= 1
        assert review_queue["bucket_counts"]["ready_for_review"] >= 1

        status, review_apply_blocked = post_json(p6_port, "/api/v1/zhixing/experience-review-actions/apply-gate/dry-run", {
            "experience_review_actions": review_action,
        })
        assert status == 200
        assert review_apply_blocked["contract"] == "zhixing_library_experience_review_apply_gate.v1"
        assert review_apply_blocked["status"] == "blocked"
        assert review_apply_blocked["write_performed"] is False
        assert review_apply_blocked["receipt_preview"]["would_write"] is False
        assert "missing_authorization_confirmations" in review_apply_blocked["blocked_reasons"]

        status, review_apply_ready = post_json(p6_port, "/api/v1/zhixing/experience-review-actions/apply-gate/dry-run", {
            "experience_review_actions": review_action,
            "experience_validation_report": validation_report,
            "experience_validation_receipt_schema": validation_receipts,
            "authorization": {
                "confirm_review_action_intent": True,
                "confirm_source_refs_checked": True,
                "confirm_replay_or_validation_checked": True,
                "confirm_no_raw_or_markdown_write": True,
                "operator": "http-smoke",
                "reason": "dry-run only",
            },
        })
        assert status == 200
        assert review_apply_ready["status"] == "ready"
        assert review_apply_ready["authorization_complete"] is True
        assert review_apply_ready["validation_report_attached"] is True
        assert review_apply_ready["validation_report_passed"] is True
        assert review_apply_ready["validation_receipt_preferred_for_future_apply"] is True
        assert review_apply_ready["validation_receipt_attached"] is True
        assert review_apply_ready["validation_receipt_count"] >= 1
        assert review_apply_ready["validation_receipts_allow_gate"] is True
        assert review_apply_ready["receipt_preview"]["validation_receipt_attached"] is True
        assert review_apply_ready["write_performed"] is False
        assert review_apply_ready["xingce_write_performed"] is False
        assert review_apply_ready["markdown_write_performed"] is False
        assert review_apply_ready["receipt_preview"]["future_apply_required"] is True
        assert review_apply_ready["receipt_preview"]["would_write"] is False

        status, apply_receipts = post_json(p6_port, "/api/v1/zhixing/experience-apply-receipts/dry-run", {
            "experience_review_actions": review_action,
            "experience_review_apply_gate": review_apply_ready,
        })
        assert status == 200
        assert apply_receipts["contract"] == "zhixing_library_experience_apply_receipt_schema.v1"
        assert apply_receipts["dry_run"] is True
        assert apply_receipts["read_only"] is True
        assert apply_receipts["durable_write_performed"] is False
        assert apply_receipts["write_performed"] is False
        assert apply_receipts["raw_write_performed"] is False
        assert apply_receipts["xingce_write_performed"] is False
        assert apply_receipts["markdown_write_performed"] is False
        assert apply_receipts["receipt_count"] >= 1
        assert apply_receipts["source_evidence_complete"] is True
        assert apply_receipts["receipts"][0]["rollback_plan"]["receipt_type"] == "experience_rollback_receipt"
        assert apply_receipts["receipts"][0]["rollback_plan"]["write_performed"] is False
        assert apply_receipts["receipts"][0]["future_apply_allowed_by_schema"] is True

        status, apply_package = post_json(p6_port, "/api/v1/zhixing/experience-apply-package/dry-run", {
            "experience_review_actions": review_action,
            "experience_validation_receipt_schema": validation_receipts,
            "experience_review_apply_gate": review_apply_ready,
            "experience_apply_receipt_schema": apply_receipts,
        })
        assert status == 200
        assert apply_package["contract"] == "zhixing_library_experience_apply_package.v1"
        assert apply_package["dry_run"] is True
        assert apply_package["read_only"] is True
        assert apply_package["package_status"] == "ready"
        assert apply_package["ready_for_authorized_apply"] is True
        assert apply_package["authorized_apply_performed"] is False
        assert apply_package["write_performed"] is False
        assert apply_package["raw_write_performed"] is False
        assert apply_package["xingce_write_performed"] is False
        assert apply_package["markdown_write_performed"] is False
        assert apply_package["apply_receipt_write_performed"] is False
        assert apply_package["candidate_status_change_performed"] is False
        assert apply_package["apply_receipt_count"] >= 1
        assert apply_package["rollback_plan_count"] >= 1
        assert apply_package["package_items"][0]["would_write"] is False

        status, flow_overview = post_json(p6_port, "/api/v1/zhixing/experience-flow-overview/dry-run", {
            "experience_evolution": evolution,
            "experience_review_actions": review_action,
            "experience_validation_report": validation_report,
            "experience_validation_receipt_schema": validation_receipts,
            "experience_review_queue": review_queue,
            "experience_review_apply_gate": review_apply_ready,
            "experience_apply_receipt_schema": apply_receipts,
            "experience_apply_package": apply_package,
        })
        assert status == 200
        assert flow_overview["contract"] == "zhixing_library_experience_flow_overview.v1"
        assert flow_overview["dry_run"] is True
        assert flow_overview["read_only"] is True
        assert flow_overview["write_performed"] is False
        assert flow_overview["raw_write_performed"] is False
        assert flow_overview["xingce_write_performed"] is False
        assert flow_overview["markdown_write_performed"] is False
        assert flow_overview["candidate_status_change_performed"] is False
        assert flow_overview["stage_count"] == 8
        assert flow_overview["flow_status"] == "ready_for_future_authorized_apply"
        assert flow_overview["ready_stage_count"] == 8
        assert flow_overview["blocked_stage_count"] == 0
        assert flow_overview["stage_statuses"][0]["stage"] == "experience_evolution"
        assert flow_overview["stage_statuses"][-1]["stage"] == "apply_package"

        status, missing_evidence_receipts = post_json(p6_port, "/api/v1/zhixing/experience-apply-receipts/dry-run", {
            "experience_review_actions": {
                "review_actions": [
                    {
                        "candidate_id": "http-missing-evidence",
                        "requested_action": "approve",
                        "target_shelf": "xingce",
                        "review_action_id": "review-http-missing-evidence",
                    }
                ]
            },
            "experience_review_apply_gate": review_apply_ready,
        })
        assert status == 200
        assert missing_evidence_receipts["source_evidence_complete"] is False
        assert missing_evidence_receipts["source_evidence_issue_count"] == 1
        assert "source_refs" in missing_evidence_receipts["source_evidence_issues"][0]["missing"]
        assert missing_evidence_receipts["receipts"][0]["future_apply_allowed_by_schema"] is False
        assert missing_evidence_receipts["receipts"][0]["write_performed"] is False

        status, failed_validation_report = post_json(p6_port, "/api/v1/zhixing/experience-validation-report/dry-run", {
            "experience_review_actions": review_action,
        })
        assert status == 200
        assert failed_validation_report["report_passed"] is False
        status, failed_validation_receipts = post_json(p6_port, "/api/v1/zhixing/experience-validation-receipts/dry-run", {
            "experience_review_actions": review_action,
            "experience_validation_report": failed_validation_report,
        })
        assert status == 200
        assert failed_validation_receipts["would_allow_apply_gate_count"] == 0
        status, failed_review_queue = post_json(p6_port, "/api/v1/zhixing/experience-review-queue/dry-run", {
            "experience_review_actions": review_action,
            "experience_validation_report": failed_validation_report,
        })
        assert status == 200
        assert failed_review_queue["bucket_counts"]["needs_validation"] >= 1
        assert failed_review_queue["write_performed"] is False
        status, validation_blocked_gate = post_json(p6_port, "/api/v1/zhixing/experience-review-actions/apply-gate/dry-run", {
            "experience_review_actions": review_action,
            "experience_validation_report": failed_validation_report,
            "experience_validation_receipt_schema": failed_validation_receipts,
            "authorization": {
                "confirm_review_action_intent": True,
                "confirm_source_refs_checked": True,
                "confirm_replay_or_validation_checked": True,
                "confirm_no_raw_or_markdown_write": True,
                "operator": "http-smoke",
                "reason": "dry-run only",
            },
        })
        assert status == 200
        assert validation_blocked_gate["status"] == "blocked"
        assert "validation_receipt_not_passed" in validation_blocked_gate["blocked_reasons"]
        assert "validation_report_not_passed" not in validation_blocked_gate["blocked_reasons"]
        assert validation_blocked_gate["validation_receipt_attached"] is True
        assert validation_blocked_gate["validation_receipts_allow_gate"] is False
        assert validation_blocked_gate["write_performed"] is False

        status, routed = post_json(p6_port, "/api/v1/dialog/intent-route/dry-run", {
            "message": "这条记录不对，不是我的原话",
        })
        assert status == 200
        assert routed["route"] == "correction_errata"
        assert routed["action"] == "zhiyi_errata_candidate"
        assert routed["target_shelf"] == "errata"
        assert routed["write_performed"] is False

        status, routed_signal = post_json(p6_port, "/api/v1/dialog/intent-route/dry-run", {
            "message": "这个 GitHub repo 可能对Time Library有用，是个新方向",
        })
        assert status == 200
        assert routed_signal["route"] == "method_signal"
        assert routed_signal["action"] == "zhixing_method_signal_candidate"
        assert routed_signal["target_shelf"] == "incubator"
        assert routed_signal["write_performed"] is False

        status, errata = post_json(p6_port, "/api/v1/zhiyi/errata-candidates/dry-run", {
            "correction_text": "这条记录不对，不是我的原话",
            "target": {
                "library_id": "ZX-ZHIYI-HTTP",
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "raw/codex/http-smoke.jsonl",
                },
            },
        })
        assert status == 200
        assert errata["ok"] is True
        assert errata["read_only"] is True
        assert errata["write_performed"] is False
        assert errata["candidate"]["candidate_type"] == "zhiyi_errata_candidate"
        assert errata["candidate"]["verbatim_feedback"] == "这条记录不对，不是我的原话"
        assert errata["candidate"]["raw_write_performed"] is False
        assert errata["candidate"]["zhiyi_write_performed"] is False
        assert errata["candidate"]["errata_write_performed"] is False

        status, method_signal = post_json(p6_port, "/api/v1/zhixing/method-signals/dry-run", {
            "title": "Tianlu feed-to-method",
            "signal": "这个 GitHub repo 可能对Time Library有用，是个新方向：把外部资讯变成方法候选。",
            "source_url": "https://github.com/strmforge/tianlu-skills",
            "source_refs": {
                "source_system": "github",
                "source_url": "https://github.com/strmforge/tianlu-skills",
                "commit": "f5ac7db",
            },
            "verbatim_excerpt": "The incubator is the entrance for new methods.",
            "proposed_trigger": "用户说新方向、外部仓库、可能对Time Library有用",
            "proposed_mechanism": "先生成 method_card_candidate，再由 Replay/Benchmark 决定是否升格。",
            "initial_scope": "Time Library method governance",
        })
        assert status == 200
        assert method_signal["ok"] is True
        assert method_signal["read_only"] is True
        assert method_signal["write_performed"] is False
        assert method_signal["candidate"]["candidate_type"] == "external_method_signal_candidate"
        assert method_signal["candidate"]["activation_allowed"] is False
        assert method_signal["candidate"]["install_allowed"] is False
        assert method_signal["candidate"]["skill_write_performed"] is False
        assert method_signal["candidate"]["platform_write_performed"] is False

        status, ledger = post_json(p6_port, "/api/v1/zhixing/state-ledger/dry-run", {
            "topic": "ExampleTool naming",
            "records": [
                {
                    "library_id": "ZX-ZHIYI-OLD",
                    "status": "superseded",
                    "updated_at": "2026-05-29T10:00:00Z",
                    "source_refs": {"source_system": "codex", "source_path": "raw/codex/old.jsonl"},
                    "verbatim_excerpt": "Windows 原生 OpenClaw 你称为 ExampleTool",
                },
                {
                    "library_id": "ZX-ZHIYI-CURRENT",
                    "status": "adopted",
                    "updated_at": "2026-05-30T10:00:00Z",
                    "source_refs": {"source_system": "codex", "source_path": "raw/codex/current.jsonl"},
                    "verbatim_excerpt": "腾讯那个我会称呼 ExampleTool，不会和 openclaw 混说",
                    "supersedes": ["ZX-ZHIYI-OLD"],
                },
            ],
        })
        assert status == 200
        assert ledger["latest_trusted_judgment"]["record_id"] == "ZX-ZHIYI-CURRENT"
        assert ledger["write_performed"] is False
        assert ledger["write_flags"]["raw_write_performed"] is False

        status, context_unit = post_json(p6_port, "/api/v1/zhixing/context-units/dry-run", {
            "unit_text": "ExampleTool 指腾讯那个，不是 Windows 原生 OpenClaw。",
            "source_refs": {"source_system": "codex", "source_path": "raw/codex/exampletool.jsonl"},
            "verbatim_excerpt": "腾讯那个我会称呼 ExampleTool，不会和 openclaw 混说",
            "objective_link": "prevent ExampleTool naming drift",
        })
        assert status == 200
        assert context_unit["ok"] is True
        assert context_unit["candidate"]["candidate_type"] == "context_budget_unit_candidate"
        assert context_unit["candidate"]["write_performed"] is False
        assert context_unit["candidate"]["platform_write_performed"] is False

        status, docs_evidence = post_json(p6_port, "/api/v1/zhixing/external-docs-evidence/dry-run", {
            "query": "The local SDK upgrade fails after version 2.4; check official docs before answering.",
            "project": "http-smoke",
            "version": "2.4",
        })
        assert status == 200
        assert docs_evidence["ok"] is True
        assert docs_evidence["read_only"] is True
        assert docs_evidence["write_performed"] is False
        assert docs_evidence["network_call_performed"] is False
        assert docs_evidence["raw_write_performed"] is False
        assert docs_evidence["platform_write_performed"] is False
        assert docs_evidence["candidate"]["candidate_type"] == "external_docs_evidence_plan"
        assert docs_evidence["candidate"]["external_docs_recommended"] is True
        assert docs_evidence["candidate"]["raw_target"].startswith("raw/external_docs/")
        assert docs_evidence["candidate"]["third_party_tool_dependency"] is False

        status, compaction = post_json(p6_port, "/api/v1/zhixing/context-delivery-compaction/dry-run", {
            "content": "\n".join(["2026-06-08T00:00:00 INFO build ok"] * 120 + ["2026-06-08T00:03:00 FATAL build failed"]),
            "source_refs": {"source_system": "codex", "source_path": "raw/codex/http-smoke-build.jsonl"},
            "max_tokens": 180,
            "target_tokens": 90,
        })
        assert status == 200
        assert compaction["ok"] is True
        assert compaction["read_only"] is True
        assert compaction["write_performed"] is False
        assert compaction["network_call_performed"] is False
        assert compaction["cache_write_performed"] is False
        assert compaction["raw_write_performed"] is False
        assert compaction["platform_write_performed"] is False
        assert compaction["candidate"]["candidate_type"] == "context_delivery_compaction_plan"
        assert compaction["candidate"]["compaction_recommended"] is True
        assert compaction["candidate"]["reversibility"]["ready"] is True
        assert compaction["candidate"]["preservation_policy"]["summary_may_replace_raw"] is False

        status, hermes_diff_plan = get_json(p6_port, "/api/v1/hermes/skill-experience-diff/plan")
        assert status == 200
        assert hermes_diff_plan["read_only"] is True
        assert hermes_diff_plan["write_performed"] is False
        assert "write_hermes_skill" in hermes_diff_plan["forbidden_by_default"]

        status, hermes_diff = post_json(p6_port, "/api/v1/hermes/skill-experience-diff/dry-run", {
            "skills": [
                {
                    "skill_id": "software-development/hermes-profile-config",
                    "title": "Hermes profile config",
                    "text": "# Hermes profile config\nProfile config.yaml is read from the profile directory. No root fallback. Validate with hermes profile show.",
                    "source_refs": {
                        "source_system": "hermes",
                        "artifact_type": "hermes_skill_file",
                        "source_path": "/tmp/hermes/skills/hermes-profile-config/SKILL.md",
                    },
                },
            ],
            "experiences": [
                {
                    "library_id": "ZX-XINGCE-HERMES-PROFILE",
                    "summary": "Hermes profile config is read from the profile directory.",
                    "detail": "Validate with hermes profile show.",
                    "source_refs": {
                        "source_system": "probe",
                        "source_path": "raw/probe_logs/hermes-profile.jsonl",
                    },
                    "verbatim_excerpt": "profile config.yaml was read from profiles/default/config.yaml",
                },
            ],
        })
        assert status == 200
        assert hermes_diff["ok"] is True
        assert hermes_diff["write_performed"] is False
        assert hermes_diff["summary"]["upgrade_candidate_count"] == 1
        assert hermes_diff["upgrade_candidates"]["candidates"][0]["candidate_type"] == "hermes_skill_experience_upgrade_candidate"

        status, hermes_receipt = post_json(p6_port, "/api/v1/hermes/consumption-receipts", {
            "event_type": "hermes_turn_consumption_receipt",
            "provider": "time_library",
            "session_id": "hermes-http-session",
            "memory_scope": "raw_pool",
            "user_content": "用户问题",
            "assistant_content": "Hermes 回答",
            "last_prefetch": {
                "ok": True,
                "request_id": "hermes-memcore-prefetch-http",
                "matched_count": 2,
                "source_refs_count": 2,
            },
        })
        assert status == 200
        assert hermes_receipt["ok"] is True
        assert hermes_receipt["consumption_receipt_write_performed"] is True
        assert hermes_receipt["raw_write_performed"] is False
        assert hermes_receipt["hermes_skill_write_performed"] is False

        status, hermes_receipts = get_json(p6_port, "/api/v1/hermes/consumption-receipts")
        assert status == 200
        assert hermes_receipts["read_only"] is True
        assert hermes_receipts["latest"]["receipt_id"] == hermes_receipt["receipt_id"]

        status, hermes_trigger_plan = get_json(p6_port, "/api/v1/hermes/native-learning/self-review/trigger/dry-run")
        assert status == 200
        assert hermes_trigger_plan["read_only"] is True
        assert hermes_trigger_plan["write_performed"] is False
        assert "confirm_live_hermes_trigger" in hermes_trigger_plan["authorization_required"]
        assert hermes_trigger_plan["write_boundary"]["hermes_skill_write_performed_by_time_library"] is False

        status, hermes_triggers = get_json(p6_port, "/api/v1/hermes/native-learning/self-review/triggers")
        assert status == 200
        assert hermes_triggers["read_only"] is True
        assert hermes_triggers["write_performed"] is False
        assert hermes_triggers["trigger_receipt_write_performed"] is False
        assert hermes_triggers["items"] == []

        status, hermes_trigger_blocked = post_json(p6_port, "/api/v1/hermes/native-learning/self-review/trigger", {
            "operator": "pytest-http-smoke",
            "reason": "verify trigger gate",
        })
        assert status == 400
        assert hermes_trigger_blocked["ok"] is False
        assert hermes_trigger_blocked["hermes_trigger_called"] is False
        assert hermes_trigger_blocked["write_performed"] is False
        assert "confirm_live_hermes_trigger" in hermes_trigger_blocked["missing_authorization"]

        status, skill_probe_plan = get_json(p6_port, "/api/v1/hermes/native-learning/skill-generation/probe/dry-run")
        assert status == 200
        assert skill_probe_plan["read_only"] is True
        assert skill_probe_plan["write_performed"] is False
        assert skill_probe_plan["probe_id"].startswith("hermes-skill-generation-probe-")
        assert skill_probe_plan["stage_gates"]["c_skill_artifact_change"] == "non-Time Library skill file is added or modified"
        assert skill_probe_plan["write_boundary"]["hermes_skill_write_performed_by_time_library"] is False

        status, skill_probes = get_json(p6_port, "/api/v1/hermes/native-learning/skill-generation/probes")
        assert status == 200
        assert skill_probes["read_only"] is True
        assert skill_probes["write_performed"] is False
        assert skill_probes["probe_receipt_write_performed"] is False
        assert skill_probes["items"] == []

        status, skill_probe_blocked = post_json(p6_port, "/api/v1/hermes/native-learning/skill-generation/probe", {
            "operator": "pytest-http-smoke",
            "reason": "verify skill probe gate",
        })
        assert status == 400
        assert skill_probe_blocked["ok"] is False
        assert skill_probe_blocked["hermes_trigger_called"] is False
        assert skill_probe_blocked["write_performed"] is False
        assert "confirm_live_hermes_skill_generation_probe" in skill_probe_blocked["missing_authorization"]

        status, skill_status_plan = get_json(p6_port, "/api/v1/hermes/native-learning/skill-artifact-status/plan")
        assert status == 200
        assert skill_status_plan["read_only"] is True
        assert skill_status_plan["write_performed"] is False
        assert skill_status_plan["record_endpoint"] == "/api/v1/hermes/native-learning/skill-artifact-status/record"
        assert skill_status_plan["status_draft"]["artifact_type"] == "hermes_skill_artifact_status"
        assert skill_status_plan["status_draft"]["write_boundary"]["hermes_skill_write_performed_by_time_library"] is False

        status, skill_statuses = get_json(p6_port, "/api/v1/hermes/native-learning/skill-artifact-statuses")
        assert status == 200
        assert skill_statuses["read_only"] is True
        assert skill_statuses["write_performed"] is False
        assert skill_statuses["status_receipt_write_performed"] is False
        assert skill_statuses["items"] == []

        status, skill_status_blocked = post_json(p6_port, "/api/v1/hermes/native-learning/skill-artifact-status/record", {
            "operator": "pytest-http-smoke",
            "reason": "verify skill artifact status gate",
        })
        assert status == 400
        assert skill_status_blocked["ok"] is False
        assert skill_status_blocked["write_performed"] is False
        assert "confirm_record_hermes_skill_artifact_status" in skill_status_blocked["missing_authorization"]
        assert "confirm_no_hermes_skill_write_by_time_library" in skill_status_blocked["missing_authorization"]

        status, self_review_report_plan = get_json(p6_port, "/api/v1/hermes/native-learning/self-review/report/plan")
        assert status == 200
        assert self_review_report_plan["read_only"] is True
        assert self_review_report_plan["write_performed"] is False
        assert self_review_report_plan["record_endpoint"] == "/api/v1/hermes/native-learning/self-review/report/record"

        status, self_review_report_blocked = post_json(p6_port, "/api/v1/hermes/native-learning/self-review/report/record", {
            "review_text": "## Time Library原始记忆自审 — Review Report\n#### 候选 #1: 测试\n> 原话",
            "trigger_id": "hermes-self-review-http",
            "operator": "pytest-http-smoke",
            "reason": "missing confirmation",
        })
        assert status == 400
        assert self_review_report_blocked["ok"] is False
        assert self_review_report_blocked["write_performed"] is False
        assert "confirm_record_self_review_report_candidate" in self_review_report_blocked["missing_authorization"]

        candidate = feedback["candidates"][0]
        status, blocked = post_json(p6_port, "/api/v1/zhixing/replay/feedback-candidates/apply", {
            "candidate": candidate,
        })
        assert status == 400
        assert blocked["ok"] is False
        assert blocked["requires_authorization"] is True
        assert blocked["write_performed"] is False

        status, applied = post_json(p6_port, "/api/v1/zhixing/replay/feedback-candidates/apply", {
            "candidate": candidate,
            "confirm_apply_replay_feedback": True,
            "confirm_write_replay_feedback_receipt": True,
            "confirm_no_raw_platform_or_memory_write": True,
            "operator": "pytest-http-smoke",
            "reason": "verify HTTP replay feedback gate",
        })
        assert status == 200
        assert applied["replay_feedback_receipt_write_performed"] is True
        assert applied["production_experience_write_performed"] is False
        assert applied["raw_write_performed"] is False
        assert applied["zhiyi_write_performed"] is False
        assert applied["xingce_write_performed"] is False
        assert applied["hermes_write_performed"] is False
        assert applied["openclaw_write_performed"] is False

        status, capability = post_json(raw_port, "/api/v1/raw/query", {
            "query": "capability check",
            "mode": "capability_check",
            "consumer": "pytest-http-smoke",
            "request_id": "capability-http-smoke",
        })
        assert status == 200
        assert capability["mode"] == "capability_check"
        assert capability["recall_performed"] is False
        assert capability["raw_excerpt_returned"] is False
        assert capability["items"] == []
        assert capability["consumer_receipt"]["receipt_scope"] == "capability_check_no_recall"

        status, raw_memory_routing = get_json(raw_port, "/api/v1/memory-routing/status")
        assert status == 200
        assert raw_memory_routing["contract"] == "active_memory_routing.v2026.7.15"
        assert raw_memory_routing["read_only"] is True
        assert raw_memory_routing["recall_performed"] is False
        assert raw_memory_routing["raw_excerpt_returned"] is False
        assert raw_memory_routing["default_memory_scope"] == "active"
        assert raw_memory_routing["ordinary_client_contract"]["requires_current_window_identity"] is False
        assert raw_memory_routing["ordinary_client_contract"]["missing_identity_status"] == "active_layered"
        assert raw_memory_routing["ordinary_client_contract"]["window_scope_is_strict_when_explicit"] is True
        assert raw_memory_routing["ordinary_client_contract"]["active_recall_is_window_first_not_window_only"] is True
        assert raw_memory_routing["example_resolutions"]["ordinary_window_without_identity"]["recall_status"] == "window_identity_required"
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


def test_p6_hermes_native_learning_liveness_is_read_only(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    home = tmp_path / "hermes"
    (home / "logs").mkdir(parents=True)
    (home / "logs" / "agent.log").write_text("plain chat\n", encoding="utf-8")
    skill = home / "skills" / "time_library" / "time-library" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Time Library\n", encoding="utf-8")

    result = p6.query_hermes_native_learning_liveness({"hermes_home": str(home)})

    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["hermes_write_performed"] is False
    assert result["liveness_status"] == "cold"
    assert "no_skill_manage_seen" in result["cold_reasons"]
    assert result["self_review_signal"]["signal_type"] == "hermes_self_review_signal"
    assert result["self_review_signal"]["signal_status"] == "wake_signal"


def test_p6_hermes_skill_experience_diff_is_read_only(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    plan = p6.get_hermes_skill_experience_diff_plan()
    result = p6.build_hermes_skill_experience_diff_dry_run({
        "skills": [
            {
                "skill_id": "software-development/hermes-profile-config",
                "title": "Hermes profile config",
                "text": "# Hermes profile config\nProfile config.yaml is read from the profile directory. No root fallback. Validate with hermes profile show.",
                "source_refs": {
                    "source_system": "hermes",
                    "artifact_type": "hermes_skill_file",
                    "source_path": "/tmp/hermes/skills/hermes-profile-config/SKILL.md",
                },
            },
        ],
        "experiences": [
            {
                "library_id": "ZX-XINGCE-HERMES-PROFILE",
                "summary": "Hermes profile config is read from the profile directory.",
                "detail": "Validate with hermes profile show.",
                "source_refs": {
                    "source_system": "probe",
                    "source_path": "raw/probe_logs/hermes-profile.jsonl",
                },
                "verbatim_excerpt": "profile config.yaml was read from profiles/default/config.yaml",
            },
        ],
    })

    assert plan["read_only"] is True
    assert result["ok"] is True
    assert result["write_performed"] is False
    assert result["summary"]["upgrade_candidate_count"] == 1
    candidate = result["upgrade_candidates"]["candidates"][0]
    assert candidate["candidate_type"] == "hermes_skill_experience_upgrade_candidate"
    assert candidate["write_boundary"]["hermes_write_performed"] is False
    assert candidate["write_boundary"]["production_experience_write_performed"] is False


def test_p6_hermes_consumption_receipt_records_sync_turn_without_memory_writes(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)

    result = p6.persist_hermes_consumption_receipt({
        "event_type": "hermes_turn_consumption_receipt",
        "provider": "time_library",
        "session_id": "hermes-session",
        "memory_scope": "raw_pool",
        "user_content": "用户问题",
        "assistant_content": "Hermes 回答",
        "last_prefetch": {
            "ok": True,
            "request_id": "hermes-memcore-prefetch-test",
            "matched_count": 2,
            "source_refs_count": 2,
        },
    })
    receipts = p6.query_hermes_consumption_receipts({"limit": 5})

    assert result["ok"] is True
    assert result["write_performed"] is True
    assert result["consumption_receipt_write_performed"] is True
    assert result["raw_write_performed"] is False
    assert result["zhiyi_write_performed"] is False
    assert result["xingce_write_performed"] is False
    assert result["hermes_write_performed"] is False
    assert result["hermes_skill_write_performed"] is False
    assert result["production_experience_write_performed"] is False
    assert p6.os.path.exists(result["receipt_path"])
    assert receipts["ok"] is True
    assert receipts["read_only"] is True
    assert receipts["latest"]["receipt_id"] == result["receipt_id"]
    assert receipts["items"][0]["consumption_summary"]["prefetch_matched_count"] == 2


def test_p6_hermes_self_review_wake_and_receipt_boundaries(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    home = tmp_path / "hermes"
    (home / "logs").mkdir(parents=True)
    (home / "logs" / "agent.log").write_text("plain chat\n", encoding="utf-8")
    skill = home / "skills" / "time_library" / "time-library" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Time Library\n", encoding="utf-8")

    dry = p6.build_hermes_self_review_wake_http_dry_run({
        "hermes_home": str(home),
        "operator": "pytest",
        "reason": "verify p6 boundary",
    })
    assert dry["ok"] is True
    assert dry["dry_run"] is True
    assert dry["write_performed"] is False
    assert dry["hermes_write_performed"] is False
    assert dry["wake_plan"]["read_scope"] == "all_raw_memory"
    assert dry["wake_plan"]["does_not_package_zhiyi_summary"] is True

    blocked = p6.apply_hermes_self_review_signal_receipt_http({
        "hermes_home": str(home),
        "operator": "pytest",
    })
    assert blocked["ok"] is False
    assert blocked["write_performed"] is False
    assert "confirm_record_signal_receipt" in blocked["missing_authorization"]

    applied = p6.apply_hermes_self_review_signal_receipt_http({
        "hermes_home": str(home),
        "authorization": {
            "operator": "pytest",
            "reason": "record p6 signal only",
            "confirm_record_signal_receipt": True,
            "confirm_no_hermes_write": True,
            "confirm_no_raw_zhiyi_xingce_write": True,
        },
    })
    assert applied["ok"] is True
    assert applied["signal_receipt_write_performed"] is True
    assert applied["raw_write_performed"] is False
    assert applied["zhiyi_write_performed"] is False
    assert applied["xingce_write_performed"] is False
    assert applied["hermes_write_performed"] is False
    assert applied["openclaw_write_performed"] is False
