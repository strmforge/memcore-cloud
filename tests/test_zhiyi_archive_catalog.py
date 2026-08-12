import importlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _reload_p3(tmp_path):
    os.environ["MEMCORE_ROOT"] = str(tmp_path / "memcore")
    os.environ["MEMCORE_CONFIG"] = str(ROOT / "config" / "memcore.json")
    os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(tmp_path / "memcore" / "zhiyi")
    for name in ["config_loader", "src.config_loader", "src.zhiyi_archive", "src.p3_recall"]:
        sys.modules.pop(name, None)
    p3 = importlib.import_module("src.p3_recall")
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    return p3


def test_archive_card_catalog_id_is_stable_and_evidence_aware():
    archive = importlib.import_module("src.zhiyi_archive")
    record = {
        "type": "case_memory",
        "exp_id": "exp-case-abc",
        "summary": "档案馆验证",
        "detail": "完整内容",
        "source_refs": {
            "source_system": "codex",
            "source_path": "/tmp/session.jsonl",
            "msg_ids": ["m1"],
            "byte_offsets": {"m1": {"start": 0, "end": 20}},
        },
    }

    first = archive.archive_card(record)
    second = archive.archive_card(dict(record))

    assert first["catalog_id"] == second["catalog_id"]
    assert first["catalog_id"].startswith("ZY-CASE-")
    assert first["evidence_level"] == "high"
    assert first["raw_available"] is True
    assert first["byte_offsets_available"] is True


def test_attach_archive_card_keeps_recycle_state_consistent():
    archive = importlib.import_module("src.zhiyi_archive")
    record = {
        "type": "case_memory",
        "exp_id": "exp-recycle-123",
        "_deleted_state": "recycle_bin",
        "status": "active",
        "summary": "回收态验证",
        "detail": "已删除但仍可恢复",
    }

    attached = archive.attach_archive_card(record)

    assert attached["status"] == "recycled"
    assert attached["deleted_state"] == "recycle_bin"
    assert attached["_deleted_state"] == "recycle_bin"
    assert attached["_lifecycle"]["deleted_state"] == "recycle_bin"
    assert attached["archive_card"]["status"] == "recycled"


def test_p3_format_memory_returns_archive_card(tmp_path):
    p3 = _reload_p3(tmp_path)
    memory = {
        "_type": "preference_memory",
        "exp_id": "exp-pref-123",
        "summary": "用户偏好自然接上前文",
        "detail": "用户希望新窗口用自然话术找回前情。",
        "source_refs": json.dumps({
            "source_system": "codex",
            "source_path": str(tmp_path / "session.jsonl"),
            "msg_ids": ["m1"],
        }, ensure_ascii=False),
        "score": 0.8,
    }

    formatted = p3.format_memory(memory, "帮我接一下前文")

    assert formatted["catalog_id"].startswith("ZY-PREF-")
    assert formatted["archive_card"]["catalog_id"] == formatted["catalog_id"]
    assert formatted["archive_card"]["evidence_level"] == "medium"
    assert formatted["archive_card"]["source_refs"]["source_system"] == "codex"


def test_p3_load_defers_archive_card_until_result_formatting(tmp_path):
    p3 = _reload_p3(tmp_path)
    zhiyi_path = tmp_path / "memcore" / "zhiyi" / "case_memory" / "case_memory.jsonl"
    zhiyi_path.parent.mkdir(parents=True, exist_ok=True)
    zhiyi_path.write_text(json.dumps({
        "exp_id": "exp-lazy-card",
        "summary": "延迟生成档案卡",
        "detail": "缓存不重复生成，返回结果仍必须带完整档案卡。",
        "score": 0.8,
        "source_refs": json.dumps({
            "source_system": "codex",
            "source_path": str(tmp_path / "source.jsonl"),
            "msg_ids": ["m-lazy"],
        }, ensure_ascii=False),
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    loaded = p3.load_memories()

    assert len(loaded) == 1
    assert "archive_card" not in loaded[0]
    assert "library_card" not in loaded[0]
    formatted = p3.format_memory(loaded[0], "延迟生成档案卡")
    assert formatted["archive_card"]["catalog_id"] == formatted["catalog_id"]
    assert formatted["library_id"].startswith("ZX-")


def test_zhiyi_gateway_evidence_and_verbatim_use_catalog_id_without_truncating(tmp_path):
    os.environ["MEMCORE_ROOT"] = str(tmp_path / "memcore")
    os.environ["MEMCORE_CONFIG"] = str(ROOT / "config" / "memcore.json")
    for name in ["config_loader", "src.config_loader", "src.zhiyi_gateway", "src.zhiyi_archive"]:
        sys.modules.pop(name, None)
    gateway = importlib.import_module("src.zhiyi_gateway")
    source = tmp_path / "raw.jsonl"
    long_text = "原话" + ("很长" * 350) + "结尾必须保留"
    source.write_text(json.dumps({
        "type": "message",
        "id": "m1",
        "message": {"role": "user", "content": long_text},
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    memory = {
        "type": "case_memory",
        "exp_id": "exp-case-long",
        "summary": "长原文验证",
        "detail": long_text,
        "source_refs": {
            "source_system": "codex",
            "source_path": str(source),
            "msg_ids": ["m1"],
        },
        "confidence": 0.9,
    }

    evidence = gateway.route_evidence({}, [memory], "看证据")
    verbatim = gateway.route_verbatim([memory], "看原话")

    assert evidence["evidence"][0]["catalog_id"].startswith("ZY-CASE-")
    assert evidence["archive_cards"][0]["catalog_id"] == evidence["evidence"][0]["catalog_id"]
    fragment = verbatim["fragments"][0]["fragments"][0]
    assert "结尾必须保留" in fragment
    assert len(fragment) > 700
    assert verbatim["fragments"][0]["catalog_id"] == evidence["evidence"][0]["catalog_id"]


def test_p4_inject_prompt_is_archivist_prompt():
    p4 = importlib.import_module("src.p4_inject")
    result = p4.build_inject_prompt({
        "intent_mode": "summary",
        "context": "[ZY-CASE-ABC][case_memory][window-a][evidence:high] 证据",
        "should_inject": True,
    }, "帮我接一下前文")

    assert "知意档案馆" in result["system_prompt"]
    assert "你是档案员，不是创作者" in result["system_prompt"]
    assert "catalog_id" in result["system_prompt"]
    assert "不要把向量相似当成事实本身" in result["system_prompt"]
