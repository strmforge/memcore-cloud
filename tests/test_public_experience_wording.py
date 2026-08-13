from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _term(*parts: str) -> str:
    return "".join(parts)


def test_public_reader_surfaces_do_not_expose_private_or_legacy_product_terms():
    public_paths = [
        ROOT / "README.md",
        ROOT / "README.en.md",
        ROOT / "README.zh-CN.md",
        ROOT / "INTRODUCTION.md",
        ROOT / "CHANGELOG.md",
        ROOT / "UPDATE_HISTORY.md",
        ROOT / "RELEASE_NOTES_2026.8.13.md",
        ROOT / "web" / "console_product.html",
        *sorted((ROOT / "docs" / "wiki").glob("*.md")),
    ]
    forbidden_terms = [
        _term("Yifan", "chen"),
        _term("yifan", "chen"),
        _term("忆", "凡", "尘"),
        _term("Nantian", "men"),
        _term("南", "天", "门"),
        _term("Hong", "huang"),
        _term("洪", "荒"),
        _term("Jing", "zao"),
        _term("京", "造"),
        _term("windows", "123"),
        _term("windows", "191"),
        _term("192.", "168.", "50."),
        _term("562", "14"),
        _term("Q", "Claw"),
        _term("ssh-", "192"),
        _term("AI", " Act"),
        _term("OpenAI", " o3"),
        _term("nomic", "-embed-text"),
        _term("关键", "条款解析"),
        _term("模型", "报告要点"),
        _term("本地", "数据库快照"),
    ]
    for path in public_paths:
        text = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in text, f"{path.relative_to(ROOT)} contains blocked term {term!r}"


def test_public_docs_keep_experience_distinct_from_skill():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    history = (ROOT / "UPDATE_HISTORY.md").read_text(encoding="utf-8")

    assert "Experience is not a skill library" in default
    assert "经验层不是技能库" in short_zh
    assert "经验会进化，但不黑箱" in short_zh
    assert "有证据、有验收、有回执的采编进化" in short_zh
    assert "给所有本机 agent 接入经验" in short_zh
    assert "经验层不是某个工具的私有 skill" in short_zh
    assert "Experience for every local agent" in default
    assert "Experience can intervene across platforms" in default
    assert "Experience evolves, but it is not a black box" in default
    assert "The preference shelf keeps preference and intent experience" in default
    assert "Experience is not a skill library" in en
    assert "Experience for every local agent" in en
    assert "Experience can intervene across platforms" in en
    assert "Experience evolves, but it is not a black box" in en
    assert "The preference shelf keeps preference and intent experience" in en
    assert "The work-experience shelf keeps work experience" in en
    assert "Experience is not a skill library" in history
    assert "work-experience layer" in history
    assert "contextual judgment" not in history


def test_public_docs_describe_zhixing_library_in_both_languages():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    intro = (ROOT / "INTRODUCTION.md").read_text(encoding="utf-8")
    history = (ROOT / "UPDATE_HISTORY.md").read_text(encoding="utf-8")

    assert "The local memory layer for AI agents — with the receipts." in default
    assert "Keep local AI agents from starting over" in en
    assert "capture -> recall -> answer from evidence -> install agent rule -> health" in default
    assert "capture -> recall -> answer from evidence -> install agent rule -> health" in en
    assert "Preference and work-experience shelves" in default
    assert "source records, source refs, corrections, and work experience" in default
    assert "## Core Workflow" in default
    assert "Capture source records" in default
    assert "Recall with source refs" in default
    assert "Answer from evidence" in default
    assert "Install an agent rule" in default
    assert "Check health before trust" in default
    assert "## Advanced Capabilities" in default
    assert "Shared local context" in default
    assert "Experience for every local agent" in default
    assert "Hermes skill evolution" in default
    assert "Safe agent authority" in default
    assert "Local diagnostics" in default
    assert "## Features" not in default
    assert "Raw records first" not in default
    assert "Library ids and borrowing receipts" not in default
    assert "Zhiyi understands you" not in default
    assert "Xingce improves work" not in default
    assert "Cross-tool memory" not in default
    assert "Reusable work experience" not in default
    assert "## Quick Demo" in default
    assert "捕获 -> 召回 -> 基于证据回答 -> 安装 agent 规则 -> 健康检查" in short_zh
    assert "偏好层" in short_zh
    assert "经验层" in short_zh
    assert "原始记录仍然是最高事实" in short_zh
    assert "## 核心流程" in short_zh
    assert "捕获来源记录" in short_zh
    assert "带 source refs 召回" in short_zh
    assert "基于证据回答" in short_zh
    assert "安装 agent 规则" in short_zh
    assert "先检查健康再信任" in short_zh
    assert "## 高级能力" in short_zh
    assert "跨工具本机上下文" in short_zh
    assert "给所有本机 agent 接入经验" in short_zh
    assert "Hermes 技能经验进化" in short_zh
    assert "本机 agent 权限更安全" in short_zh
    assert "本地诊断" in short_zh
    assert "## 功能" not in short_zh
    assert "原始记录保真" not in short_zh
    assert "馆藏号和借阅回执" not in short_zh
    assert "知意：越用越懂你" not in short_zh
    assert "行策：越做越会做" not in short_zh
    assert "跨工具本机记忆" not in short_zh
    assert "可复用工作经验" not in short_zh
    assert "## 快速体验" in short_zh
    assert "Preference and work-experience shelves" in en
    assert "source records, source refs, corrections, and work experience" in en
    assert "## Core Workflow" in en
    assert "Capture source records" in en
    assert "Recall with source refs" in en
    assert "Answer from evidence" in en
    assert "Install an agent rule" in en
    assert "Check health before trust" in en
    assert "## Advanced Capabilities" in en
    assert "Shared local context" in en
    assert "Hermes skill evolution" in en
    assert "Safe agent authority" in en
    assert "Local diagnostics" in en
    assert "## Features" not in en
    assert "Raw records first" not in en
    assert "Library ids and borrowing receipts" not in en
    assert "Zhiyi understands you" not in en
    assert "Xingce improves work" not in en
    assert "时间图书馆馆藏" in intro
    assert "Time Library knowledge shelves" in history
    assert "时间图书馆馆藏" in history


def test_public_docs_explain_agent_install_without_mcp_knowledge():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    assert default.index("## Paste This To Your Local Agent") < default.index("## Quick Install")
    assert "You are installing Time Library for me on this machine." in default
    assert "Repository: https://github.com/strmforge/time-library" in default
    assert "standing memory rule" in default
    assert "not just a one-time setup note" in default
    assert "Time Library skill/instruction" in default
    assert "register the MCP tool named time-library" in default
    assert "call time_library_recall before answering" in default
    assert "do not reinstall it" in default
    assert "host report is authoritative" in default
    assert "self_report_connect" in default
    assert "proof_library_id" in default
    assert "install/test/release status" in default
    assert "MCP/tool connection is missing" in default
    assert "你正在帮我在这台机器安装 Time Library" in default
    assert "请先检查这台机器上的 Time Library 是否已经安装并在运行" in default
    assert "长期记忆规则" in default
    assert "添加 Time Library skill/指令" in default
    assert "请先调用 time_library_recall" in default
    assert "下一步/接下来呢/还有吗/然后呢" in default
    assert "不要凭印象猜" in default
    assert "Simple install options" in default
    assert "connects usable local AI tool entries" in default
    assert "Paste This To Your Local Agent" in en
    assert "You are installing Time Library for me on this machine." in en
    assert "Repository: https://github.com/strmforge/time-library" in en
    assert "standing memory rule" in en
    assert "Time Library skill/instruction" in en
    assert "call time_library_recall before answering" in en
    assert "do not reinstall it" in en
    assert "host report is authoritative" in en
    assert "self_report_connect" in en
    assert "proof_library_id" in en
    assert "next step" in en
    assert "what else" in en
    assert "then what" in en
    assert "MCP/tool connection is missing" in en
    assert "Simple install options" in en
    assert "connects usable local AI tool entries" in en
    assert "do not recall my real memory" in en
    assert "你正在帮我在这台机器安装 Time Library" in short_zh
    assert "请先调用 time_library_recall" in short_zh
    assert "不要凭印象猜" in short_zh
    assert "宿主自报是权威" in short_zh
    assert "self_report_connect" in short_zh
    assert "proof_library_id" in short_zh
    for text in (default, en, short_zh):
        assert "time-library" in text
        assert "front_door_port" in text
        assert "/mcp?startup_catalog=deferred" in text
        assert "http://127.0.0.1:9851/mcp" not in text
        assert "capability check" in text
        assert "If this platform is Claude Code" not in text
        assert "如果这个平台是 Claude Code" not in text
        assert "only connect this platform's native delivery surface" not in text
        assert "只接这一个平台的原生投递面" not in text


def test_windows_public_install_is_not_presented_as_wsl():
    public_docs = [
        ROOT / "README.md",
        ROOT / "README.en.md",
        ROOT / "README.zh-CN.md",
        ROOT / "docs" / "wiki" / "Getting-Started.md",
    ]

    for path in public_docs:
        text = path.read_text(encoding="utf-8")
        assert "macOS / Linux / WSL" not in text
        assert "Windows PowerShell" in text
        assert "install.ps1" in text
        assert "memcore-cloud-wsl-test" not in text

    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    wiki = (ROOT / "docs" / "wiki" / "Getting-Started.md").read_text(encoding="utf-8")

    for text in (default, en, wiki):
        assert "WSL is only for development or advanced testing" in text
        assert "Normal Windows installs should" in text
    assert "use the Time Library tray icon after install" in default
    assert "Time Library menu bar icon" in default
    assert "tray/menu bar icon" in en

    assert "WSL 只适合开发或高级测试" in zh
    assert "普通 Windows 用户" in zh
    assert "Windows 安装后会有 Time Library 托盘图标" in zh
    assert "macOS 安装后会有 Time Library 菜单栏图标" in zh


def test_windows_public_install_documents_custom_install_path():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    wiki = (ROOT / "docs" / "wiki" / "Getting-Started.md").read_text(encoding="utf-8")

    for text in (default, en, wiki):
        assert "%LOCALAPPDATA%\\time-library" in text
        assert "$env:TIME_LIBRARY_INSTALL_DIR" in text
        assert '.\\install.ps1 -Dir "D:\\Apps\\time-library"' in text
        assert "%LOCALAPPDATA%\\memcore-cloud" not in text
        assert "$env:MEMCORE_INSTALL_DIR" not in text
        assert '.\\install.ps1 -Dir "D:\\Apps\\memcore-cloud"' not in text
        assert "To choose a path" in text
        assert "downloaded the release zip" in text
        assert "double-click installers" in text or "installer entry" in text
    assert "Windows 默认安装到 `%LOCALAPPDATA%\\time-library`" in zh
    assert "$env:TIME_LIBRARY_INSTALL_DIR" in zh
    assert '.\\install.ps1 -Dir "D:\\Apps\\time-library"' in zh
    assert "%LOCALAPPDATA%\\memcore-cloud" not in zh
    assert "$env:MEMCORE_INSTALL_DIR" not in zh
    assert '.\\install.ps1 -Dir "D:\\Apps\\memcore-cloud"' not in zh
    assert "如果要自己选安装路径" in zh
    assert "如果下载了 release zip" in zh
    assert "双击安装入口" in zh


def test_public_agent_prompt_uses_source_refs_before_raw_excerpt():
    public_docs = [
        ROOT / "README.md",
        ROOT / "README.en.md",
        ROOT / "README.zh-CN.md",
        ROOT / "docs" / "wiki" / "Getting-Started.md",
    ]

    for path in public_docs:
        text = path.read_text(encoding="utf-8")
        assert "source refs or raw excerpts when available" not in text
        assert "source_refs / raw_excerpt 回答" not in text
        assert "use source refs by default" in text or "默认结合 source_refs 回答" in text
        assert "raw excerpts only when I explicitly need original evidence text" in text or "明确需要原文证据" in text


def test_current_release_install_points_to_latest_published_versioned_assets():
    public_docs = [
        ROOT / "README.md",
        ROOT / "README.en.md",
        ROOT / "README.zh-CN.md",
        ROOT / "docs" / "wiki" / "Getting-Started.md",
    ]

    for path in public_docs:
        text = path.read_text(encoding="utf-8")
        assert "github.com/strmforge/time-library/releases/download/v2026.8.13/" in text
        if path.name in {"README.md", "README.en.md"}:
            assert 'github.com/strmforge/time-library/releases/tag/v2026.8.13">2026.8.13' in text
        assert "bash time-library-install.sh" in text or path.name == "Getting-Started.md"
        assert ".\\install.ps1" in text
        assert "raw.githubusercontent.com/strmforge/memcore-cloud/main/install" not in text
        assert "| bash" not in text
        assert "| iex" not in text

    install_sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    install_ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    update_source = (ROOT / "src" / "update_source.py").read_text(encoding="utf-8")
    for text in (install_sh, install_ps1, update_source):
        assert "archive/refs/heads/main.zip" not in text
        assert "memcore-cloud-main.zip" not in text
    assert "2026.8.13" in install_sh
    assert "2026.8.13" in install_ps1


def test_public_entry_points_use_time_library_first():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    history = (ROOT / "UPDATE_HISTORY.md").read_text(encoding="utf-8")
    intro = (ROOT / "INTRODUCTION.md").read_text(encoding="utf-8")
    install_sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    install_ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    console = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert default.startswith("# Time Library")
    assert en.startswith("# Time Library")
    assert history.startswith("# Memcore Cloud Update History")
    assert intro.startswith("# Time Library / 时间图书馆")
    assert "Time Library is a local continuity layer for personal AI work." in intro
    assert "Time Library is a local personal AI memory and experience center." not in intro
    assert "Time Library is a local personal AI memory center." not in intro
    assert "connects usable local entries automatically" in intro
    assert "connected tools" not in intro
    assert "What Time Library Means" in default
    assert "What Time Library Means" in en
    assert "assets/brand/time-library-logo-en.png" in default
    assert "assets/brand/time-library-logo-en.png" in en
    assert "assets/brand/time-library-logo-en.png" in intro
    assert "Downloading Time Library" in install_sh
    assert "Downloading Time Library" in install_ps1
    assert "[time-library]" in install_sh
    assert "[time-library]" in install_ps1
    assert "Downloading Memcore Cloud" not in install_sh
    assert "Downloading Memcore Cloud" not in install_ps1
    assert "[memcore-cloud]" not in install_sh
    assert "[memcore-cloud]" not in install_ps1
    assert "<title>Time Library · Local Memory Center</title>" in console
    assert "/assets/time_library_emblem.png" in console
    assert "/assets/time_library_logo_zh.png" in console
    assert "/assets/time_library_logo_en.png" in console
    assert "applyBrandLogo" in console
    assert "agentInstall.prompt" in console
    assert "copy-agent-prompt-btn" in console
    assert "standing memory rule" in console
    assert "call time_library_recall before answering" in console
    assert "use source refs by default" in console
    assert "source refs or raw excerpts when available" not in console
    assert "请先调用 time_library_recall" in console
    assert "默认结合 source_refs 回答" in console
    assert "source_refs / raw_excerpt 回答" not in console
    assert "Time Library keeps only connection status" not in console
    assert "Time Library provides memory in the background" not in console
    assert "Memcore Cloud" not in console
    assert "time_library_logo.png" not in console


def test_local_wiki_draft_is_product_facing_and_keeps_internal_strategy_hidden():
    wiki_dir = ROOT / "docs" / "wiki"
    pages = {
        path.name: path.read_text(encoding="utf-8")
        for path in wiki_dir.glob("*.md")
    }

    assert {
        "Home.md",
        "Getting-Started.md",
        "Safe-Capability-Check.md",
        "AI-Tool-Boundaries.md",
        "Agent-Entrypoints.md",
        "Automatic-Reminders.md",
        "Concepts-And-Five-Shelves.md",
        "Memory-Layout.md",
        "Release-History.md",
    }.issubset(set(pages))
    assert pages["Home.md"].startswith("# Time Library Wiki")
    assert "The local memory layer for AI agents — with source refs and receipts." in pages["Home.md"]
    assert "model-in-the-loop proof is still incomplete" in pages["Home.md"]
    assert "local-first, source-backed memory and experience" not in pages["Home.md"]
    assert "Claude Desktop and Claude Code CLI are first-class surfaces" in pages["AI-Tool-Boundaries.md"]
    assert "memory/<computer-name>/<source-tool>/<app-format>/<window-or-project>/<session>.jsonl" in pages["Memory-Layout.md"]
    assert "The Five Shelves" in pages["Concepts-And-Five-Shelves.md"]
    assert "Continuity Model" in pages["Concepts-And-Five-Shelves.md"]
    assert "Memory Plus Experience" not in pages["Concepts-And-Five-Shelves.md"]
    assert "Memory helps an agent understand the user" in pages["Concepts-And-Five-Shelves.md"]
    assert "Experience helps an agent do the next task better" in pages["Concepts-And-Five-Shelves.md"]
    assert "README should stay feature-first" in pages["Concepts-And-Five-Shelves.md"]
    assert "经验层不是技能市场" in pages["Concepts-And-Five-Shelves.md"]
    assert "raw`" in pages["Concepts-And-Five-Shelves.md"]
    assert "zhiyi`" in pages["Concepts-And-Five-Shelves.md"]
    assert "xingce`" in pages["Concepts-And-Five-Shelves.md"]
    assert "toolbook`" in pages["Concepts-And-Five-Shelves.md"]
    assert "errata`" in pages["Concepts-And-Five-Shelves.md"]
    assert "Concepts And Five Shelves" in pages["Home.md"]
    assert "Concepts And Five Shelves" in pages["Memory-Layout.md"]
    assert "最新版保留独立发布说明" in pages["Release-History.md"]
    assert "python3 tools/release_gate.py --source head" in pages["Release-History.md"]
    assert "clean archive of `HEAD`" in pages["Release-History.md"]
    assert "不依赖本机运行目录或未提交文件" in pages["Release-History.md"]
    assert "when the question depends on old work, ask Time Library first" in pages["Agent-Entrypoints.md"]
    assert "你不需要研究每个工具的文件格式" in pages["Agent-Entrypoints.md"]
    assert "偷偷改项目文件或读取聊天正文" in pages["Agent-Entrypoints.md"]
    assert "common local AI tool entry points" in pages["Agent-Entrypoints.md"]
    assert "private file format" in pages["Agent-Entrypoints.md"]
    assert "常见的本机 AI 工具入口" in pages["Agent-Entrypoints.md"]
    assert "私有文件格式" in pages["Agent-Entrypoints.md"]
    for technical_term in ["dry-run", "metadata", "contract", "manifest", "adapter"]:
        assert technical_term not in pages["Agent-Entrypoints.md"]
    assert "Time Library should not wait for you to remember the memory command every time" in pages["Automatic-Reminders.md"]
    assert "if the next answer depends on old work" in pages["Automatic-Reminders.md"]
    assert "ask Time Library first" in pages["Automatic-Reminders.md"]
    assert "如果下一个回答依赖旧上下文，agent 应该先问Time Library" in pages["Automatic-Reminders.md"]
    for technical_term in ["dry-run", "metadata", "contract", "manifest", "adapter"]:
        assert technical_term not in pages["Automatic-Reminders.md"]

    all_wiki = "\n".join(pages.values())
    assert "Please install Time Library from https://github.com/strmforge/memcore-cloud" not in all_wiki
    assert "You are installing Time Library for me on this machine." in all_wiki
    assert "请帮我在本机安装 Time Library" in all_wiki or "你正在帮我在这台机器安装 Time Library" in all_wiki
    assert "read_only: true" in all_wiki
    assert "recall_performed: false" in all_wiki
    assert "finds local AI tools and connects usable local entries automatically" in all_wiki

    hidden_public_terms = [
        "公开卖点",
        "卖点",
        "README 负责揽客",
        "Private memory and work experience for local AI tools",
        "memory + experience",
        "记忆 + 经验",
        "/api/v1/platforms/thin-adapter-registry",
        "/api/v1/platforms/generic-local-ai-surfaces",
        "/api/v1/platforms/authorized-auto-connect/dry-run",
        "Tiandao thin-adapter",
        "Kiro",
        "github_watchlist",
        "platform dictionary",
        "平台字典",
        "泛发现",
        "orchestration system",
        "Project " + "Alpha",
        "central-node",
        "中央节点",
        "native_artifact_format",
        "source-system-first",
        "capability matrix",
        "能力矩阵",
        "hooks / MCP / REST",
        "AGENTS.md",
    ]
    for term in hidden_public_terms:
        assert term not in all_wiki


def test_only_current_release_notes_stays_as_root_file():
    release_notes = sorted(path.name for path in ROOT.glob("RELEASE_NOTES_*.md"))
    assert release_notes == ["RELEASE_NOTES_2026.8.13.md"]


def test_2026_6_20_2_release_note_is_version_consistency_patch():
    release = ROOT / "docs" / "releases" / "RELEASE_NOTES_2026.6.20.2.md"
    if not release.exists():
        return
    text = release.read_text(encoding="utf-8")

    assert release.exists()
    assert "Memcore Cloud 2026.6.20.2" in text
    assert "safety-followup patch" in text
    assert "passive-first" in text
    assert "Runtime version reporting" in text
    assert "PowerShell's read-only `$PID`" in text
    assert "Release gate now blocks runtime version literals" in text
    assert "安全跟进补丁" in text
    assert "运行态版本上报" in text
    assert "PowerShell 只读 `$PID`" in text
    assert "公开版本" in text
    assert "silent self-training" not in text
    assert "local release candidate" not in text
    assert "has not been pushed" not in text
    assert "Release validation" not in text
    assert "Full local tests passed" not in text
    assert "working-tree release gate" not in text
    assert "committed-HEAD" not in text
    assert "two Windows hosts" not in text
    assert "两台 Windows 主机" not in text
    assert "本轮对本机 macOS" not in text
    assert "发布前 committed-HEAD" not in text
    assert "提交后的 `HEAD`" not in text
    assert "GitHub Wiki has not been synced yet" not in text
    assert not (ROOT / "docs" / "releases" / "drafts" / "2026.6.20.2.md").exists()


def test_public_docs_explain_safe_testing_and_autodiscovery_boundaries():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    history = (ROOT / "UPDATE_HISTORY.md").read_text(encoding="utf-8")
    release_path = ROOT / "docs" / "releases" / "RELEASE_NOTES_2026.6.20.2.md"
    release = release_path.read_text(encoding="utf-8") if release_path.exists() else ""

    assert "README.zh-CN.md" in en
    assert "## Safe First Check" in default
    assert default.index("## Core Workflow") < default.index("## Quick Demo") < default.index("## What It Remembers")
    assert default.index("## Core Workflow") < default.index("## Advanced Capabilities") < default.index("## Quick Demo")
    assert default.index("## Safe First Check") < default.index("## What Makes It Different")
    assert "## Record Doctor" in default
    assert "## Local Diagnostics" in default
    assert default.index("## Safe First Check") < default.index("## Record Doctor") < default.index("## What The Local Page Shows")
    assert "python3 tools/record_doctor.py" in default
    assert "Use Record Doctor and the local health page first" in default
    assert "separate maintainer workspace" in default
    assert "public leaderboard claim" in default
    assert "python3 tools/free_memory_benchmark.py --download" not in default
    assert "LoCoMo locomo10 | 66.5/100 | 82.3/100" not in default
    assert "LongMemEval oracle | 82.6/100 | 91.2/100" not in default
    assert "39.4/100" not in default
    assert "43.7/100" not in default
    assert "[benchmarks/README.md](benchmarks/README.md)" not in default
    assert "Safe agent authority" in default
    assert "Answer from evidence" in default
    assert "Evidence-bound model use" in default
    assert "Local diagnostics" in default
    assert "OpenClaw-style interception is passive by default" in default
    assert "return `UNKNOWN`" in default
    assert "source records, raw mirrors, the canonical index, and memory/experience links" in default
    assert "does not run recall, backfill, model calls, or platform writes" in default
    assert "read_only: true" in default
    assert "recall_performed: false" in default
    assert "raw_excerpt_returned: false" in default
    assert 'mcp_tools: ["time_library_recall"]' in default
    assert "## What The Local Page Shows" in default
    assert "which AI tools are present on this machine" in default
    assert "which ones can run a safe capability check" in default
    assert "Supported local AI tool entries can be connected automatically" in default
    assert "whether source records, raw mirrors, the canonical index, and memory/experience links are guarded" in default
    assert "Conversation import uses verified local formats" in default
    assert "## AI Tool Surfaces" in default
    assert "## Supported Sources" not in default
    assert "## Safe First Check" in en
    assert en.index("## Core Workflow") < en.index("## Advanced Capabilities") < en.index("## Quick Demo")
    assert "## Record Doctor" in en
    assert "## Local Diagnostics" in en
    assert "python3 tools/record_doctor.py" in en
    assert "Use Record Doctor and the local health page first" in en
    assert "separate maintainer workspace" in en
    assert "public leaderboard claim" in en
    assert "python3 tools/free_memory_benchmark.py --download" not in en
    assert "LoCoMo locomo10 | 66.5/100 | 82.3/100" not in en
    assert "LongMemEval oracle | 82.6/100 | 91.2/100" not in en
    assert "39.4/100" not in en
    assert "43.7/100" not in en
    assert "[benchmarks/README.md](benchmarks/README.md)" not in en
    assert "## What The Local Page Shows" in en
    assert "which AI tools are present on this machine" in en
    assert "which ones can run a safe capability check" in en
    assert "Supported local AI tool entries can be connected automatically" in en
    assert "whether source records, raw mirrors, the canonical index, and memory/experience links are guarded" in en
    assert "Conversation import uses verified local formats" in en
    assert "## AI Tool Surfaces" in en
    assert "## Supported Sources" not in en
    assert "## 安全第一步" in short_zh
    assert short_zh.index("## 核心流程") < short_zh.index("## 高级能力") < short_zh.index("## 快速体验")
    assert "## 记录医生" in short_zh
    assert "## 本地诊断" in short_zh
    assert "python3 tools/record_doctor.py" in short_zh
    assert "先看记录医生和本地健康页面" in short_zh
    assert "维护者自己的独立工作区" in short_zh
    assert "公开榜单声明" in short_zh
    assert "python3 tools/free_memory_benchmark.py --download" not in short_zh
    assert "LoCoMo locomo10 | 66.5/100 | 82.3/100" not in short_zh
    assert "LongMemEval oracle | 82.6/100 | 91.2/100" not in short_zh
    assert "39.4/100" not in short_zh
    assert "43.7/100" not in short_zh
    assert "[benchmarks/README.md](benchmarks/README.md)" not in short_zh
    assert "本机 agent 权限更安全" in short_zh
    assert "基于证据回答" in short_zh
    assert "证据绑定回答路径" in short_zh
    assert "本地诊断" in short_zh
    assert "不会召回、不会回填、不会调用模型，也不会改平台配置" in short_zh
    assert "## 本地页面能看什么" in short_zh
    assert "这台机器上有哪些 AI 工具" in short_zh
    assert "可用的本机 AI 工具入口可以自动接入" in short_zh
    assert "源记录、raw 镜像、所有会话底座、记忆与经验链路是否守住" in short_zh
    assert "对话进入记忆依赖已验证的本地格式采集器" in short_zh
    assert "## AI 工具入口" in short_zh
    assert "## 支持的来源" not in short_zh

    public_docs = "\n".join([default, en, short_zh, changelog, history, release])
    hidden_public_terms = [
        "/api/v1/platforms/thin-adapter-registry",
        "/api/v1/platforms/generic-local-ai-surfaces",
        "/api/v1/platforms/authorized-auto-connect/dry-run",
        "Tiandao thin-adapter",
        "construction build",
        "construction logs",
        "construction notes",
        "docs/construction",
        "Kiro",
        "github_watchlist",
        "platform dictionary",
        "平台字典",
        "泛发现",
        "orchestration system",
        "Project " + "Alpha",
        "central-node",
        "中央节点",
        "native_artifact_format",
        "source-system-first",
        "capability matrix",
        "能力矩阵",
        "hooks / MCP / REST",
        "AGENTS.md",
        "旧的游离记录",
    ]
    for term in hidden_public_terms:
        assert term not in public_docs

    assert "## [2026.6.4] - 2026-06-04" in changelog
    assert "native Windows as the default Windows install path" in changelog
    assert "Codex stdio MCP bridge for current-window recall" in changelog
    assert "model-assisted local tool identification" in changelog
    assert "## [2026.6.2] - 2026-06-02" in changelog
    assert "Claude Desktop recall" in changelog
    assert "local AI tool discovery view" in changelog


def test_public_docs_explain_hermes_native_skill_learning_boundary():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "Hermes can inspect sources itself" in default
    assert "provide raw/source-ref pointers" in default
    assert "Hermes-owned skill changes remain Hermes-owned" in default
    assert "Hermes can inspect sources itself" in en
    assert "provide raw/source-ref pointers" in en
    assert "Hermes-owned skill changes remain Hermes-owned" in en
    assert "Hermes" in short_zh
    assert "raw/source refs 路径指针" in short_zh
    assert "raw-pointer-to-native-skill-learning chain" in changelog


def test_public_readme_keeps_old_release_highlights_in_history_page():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    history = (ROOT / "UPDATE_HISTORY.md").read_text(encoding="utf-8")

    assert "## Current Published Release: 2026.8.13" in default
    assert "## Current Published Release: 2026.8.13" in en
    assert "See [RELEASE_NOTES_2026.8.13.md](RELEASE_NOTES_2026.8.13.md) for this release" in default
    assert "See [RELEASE_NOTES_2026.8.13.md](RELEASE_NOTES_2026.8.13.md) for this release" in en
    assert "[UPDATE_HISTORY.md](UPDATE_HISTORY.md)" in default
    assert "[UPDATE_HISTORY.md](UPDATE_HISTORY.md)" in en
    assert "完整历史更新见 [UPDATE_HISTORY.md](UPDATE_HISTORY.md)" in short_zh
    assert "Organized local records" in history
    assert "按电脑整理本机记录" in history
    assert "new records are grouped by computer first" in history
    assert "先按电脑分组，再按产生记录的 AI 工具分组" in history

    assert "## 2026.5.29 新增" not in default
    assert "## 2026.5.30 新增" not in default
    assert "## 2026.5.31 新增" not in default
    assert "## New In 2026.5.29" not in en
    assert "## New In 2026.5.30" not in en
    assert "## New In 2026.5.31" not in en

    assert "### 2026.6.2" in history
    assert "### 2026.6.1" in history
    assert "### 2026.5.29" in history
    assert "### 2026.5.28" in history
    assert "### 2026.5.27" in history
    assert "### 2026.5.30" in history
    assert "### 2026.5.31" in history
    assert "Time Library knowledge shelves" in history
    assert "Hermes learning heartbeat" in history
    assert "Codex local sessions enter the memory base" in history
    assert "更轻的记忆调用方式" in history
    assert "Codex local sessions enter memory" in history
    assert "Lighter memory entry" in history
    assert "RELEASE_NOTES_2026.6.4.md" not in history
    assert "RELEASE_NOTES_2026.6.1.md" not in history
    assert "RELEASE_NOTES_2026.5.28.md" not in history
    assert "RELEASE_NOTES_2026.5.27.md" not in history


def test_public_docs_show_current_release_version():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "RELEASE_NOTES_2026.8.13.md").read_text(encoding="utf-8")

    assert "version-2026.8.13" in default
    assert "2026.8.13 is the current published release" in default
    assert "fail-closed, relay-preserving" in default
    assert "version-2026.8.13" in en
    assert "2026.8.13 is the current published release" in en
    assert "fail-closed, relay-preserving" in en
    assert "当前正式发布版本是 **2026.8.13**" in short_zh
    assert "源记录保全" in short_zh
    assert "source-preserving record reliability" in release_notes
    assert "可恢复性诊断" in release_notes
    assert "本地候选版" not in release_notes
    assert _term("隐", "私") not in release_notes
    assert _term("泄", "漏") not in release_notes
    assert _term("私", "有") not in release_notes
    assert _term("事", "故") not in release_notes
    assert "尚未 push" not in short_zh
    assert "Answer from evidence" in default
    assert "Answer from evidence" in en
    assert "证据绑定回答路径" in short_zh
    for text in (default, en, short_zh):
        assert "Current-run local maintainer validation" not in text
        assert "working-tree release gate" not in text
        assert "committed-HEAD" not in text
        assert "提交后的 HEAD" not in text
        assert "两台 Windows 主机" not in text
        assert "本轮本机 macOS" not in text
    assert "Time Library 2026.8.13" in release_notes
    assert "relay/provider" in release_notes
    assert "无人值守 Guardian 任务编排" in release_notes
    assert "release checks" not in release_notes
    assert "public package contents" not in release_notes
    assert "user-facing wording" not in release_notes
    assert "发布检查" not in release_notes
    assert "公开发布包" not in release_notes
    assert "specific local relay product" not in default
    assert "neutral `local_relay` handling" not in default
    assert "legacy stray-record diagnostics" not in default
    assert "公开文档、平台目录、watchlist、诊断和测试" not in short_zh
    assert "发布说明见 [RELEASE_NOTES_2026.8.13.md](RELEASE_NOTES_2026.8.13.md)" in short_zh
    assert "2026.6.2 is the current published release" not in default
    assert "2026.6.2 is the current published release" not in en
    assert "2026.6.2 是当前已发布版本" not in short_zh
    for text in (default, en, short_zh):
        assert "Current Development Version" not in text
        assert "latest published release is still [2026.5.31]" not in text
        assert "当前开发版本" not in text
        assert "最新已发布版本仍是 [2026.5.31]" not in text
        assert "2026.6.1 is the current published release" not in text
        assert "2026.6.1 是当前已发布版本" not in text
        assert "local candidate" not in text
        assert "本地候选" not in text


def test_public_docs_treat_claude_desktop_as_first_class_not_export_only():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    history = (ROOT / "UPDATE_HISTORY.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "Claude is handled carefully" in default
    assert "Claude Desktop and Claude Code CLI can both connect" in default
    assert "remain separate surfaces" in default
    assert "Official, relay, and CLI-related records keep attribution boundaries" in default
    assert "Claude is handled carefully" in en
    assert "Claude Desktop and Claude Code CLI can both connect" in en
    assert "remain separate surfaces" in en
    assert "Official, relay, and CLI-related records keep attribution boundaries" in en
    assert "工具边界不混读" in short_zh
    assert "Claude Desktop 和 Claude Code CLI 分开看待" in short_zh
    assert "官方登录、中转服务、CLI 运行时产生的记录会保留归属边界" in short_zh
    assert "Claude Desktop 一等公民接入" in history
    assert "只装通用 Skill 有信号" in history
    assert "按 `claude_all` 聚合全部 Claude 入口" in history
    assert "Windows 上通过中转服务或 Claude Code 运行时产生的记录" in history
    assert "Claude Code CLI from a boundary-only object to a connectable candidate" in changelog
    assert "keeping it separate from Claude Desktop" in changelog
