# Memcore Cloud Update History

This page keeps the longer release highlights out of the README homepage. The
current published release is [2026.8.13](https://github.com/strmforge/time-library/releases/tag/v2026.8.13);
see [RELEASE_NOTES_2026.8.13.md](RELEASE_NOTES_2026.8.13.md) for its release notes.
For engineering-level changes, see [CHANGELOG.md](CHANGELOG.md).

## 中文

### 2026.6.20.2

- **版本上报归一**：运行态版本面统一读取根目录 `VERSION`，不再让 gateway、MCP、preflight、console API 或本地控制台 UI 显示旧版本号。
- **Windows 脚本修复**：guardian 和卸载脚本不再给 PowerShell 只读 `$PID` 自动变量赋值，避免 smoke / uninstall 走到对应路径时直接失败。
- **发布门加固**：release gate 会拒绝运行态版本字面量回到用户可见/健康上报面，也会拒绝 PowerShell `$PID` 赋值类回归。
- **安全边界不变**：继续保留 2026.6.20 的 passive-first 止血结果，普通聊天默认不被偏好层直接接管。

### 2026.6.12

- **公开仓库去名化**：公开文档、平台目录、watchlist、诊断和测试不再把某个本地中转工具写成公开依赖或平台入口。
- **兼容但不宣传**：旧个人环境中的本地中转路径、环境变量、数据库名和 raw format 仍可被兼容识别，但用户可见 payload 使用中性的 `local_relay` 口径。
- **遗失口径固定**：记录守护继续使用遗失源 / 遗失 raw。
- **打包验证防回归**：release gate 增加公开面和仓库文本扫描，阻止被移除的中转工具名和不合规记录诊断重新进入发布包。
- **版本一致性**：安装器、gateway health、active memory routing、preflight metadata、本地控制台和随包 Time Library skill 统一报告 2026.6.12。

### 2026.6.11

- **checkpoint 坏账本可恢复**：P0 / P2 checkpoint 损坏时不再直接中断采集，而是备份为 `.corrupt-backup-*`，后续保存使用原子替换。
- **canonical session 身份更稳**：Codex 和 Claude Code 记录在 canonical index 里统一使用 session id，同时保留旧 workspace/window 线索。
- **preference / work-experience preflight 主动但克制**：短续问、状态追问和纠错类问题可以先得到有来源的锚点；没有强证据时静默退回。
- **当前窗口快路径**：raw gateway 可以直接从 canonical record index 回答当前窗口 preflight，不冷启动宽范围召回，也不暴露 raw 原文。
- **Claude Code 自动上场 hook**：安装器可写入 `UserPromptSubmit` hook，只有 source-backed surface 决策才给 Claude Code 补上下文。
- **运行守护收紧**：raw gateway health 带 source 身份和哈希，Windows guardian 会报告端口归属，dialog-entry token 只注入 dialog-entry 服务命令。

### 2026.6.9

- **记录优先**：把原始 source / raw 记录重新放回系统起点，记录守护会检查新鲜度、损坏、可恢复状态、遗失源和遗失 raw。
- **所有会话索引**：Codex、Claude Code CLI、Claude Desktop、OpenClaw、Hermes 和其他已验证本机记录可以进入 canonical index，但摘要仍然只是导航，不替代 raw。
- **Claude Desktop 分成三类表面**：Chat 是 `claude.ai` 网页聊天和本地缓存证据；Cowork 和 Code/agent 在验证后使用本地 JSONL 正文。
- **LAN 安全分档**：本地动作入口加 token gate，同时保留有意使用局域网连接 OpenClaw / Hermes 的能力。
- **第二大脑和时间长河收束**：资料处理、外部文档证据、上下文投递压缩和时间长河沉积进入 dry-run 合同，只增强可回源召回，不替代原始记录。
- **发布前检查增强**：release gate 检查安装脚本、公开文案、内部方向、核心记录可靠性，并跑完整测试。

### 2026.6.6

- **桌面常驻入口**：Windows 托盘和 macOS 菜单栏可以直接打开本地页面、查看健康状态和补扫漏掉的记录。
- **本机同步更接近实时使用**：watcher 会持续运行，不是安装时扫一次；重启或修复安装后可以继续追上新增记录。
- **偏好层模型口径统一**：用户只需要看一个“偏好层模型”设置。它既给偏好层使用，也能在明确配置后帮助识别陌生本机 AI 工具。
- **自动识别更聪明但仍克制**：默认扫描只看本机元数据；需要模型判断时，也不发送聊天正文或原始摘录。
- **来源边界继续清楚**：Codex、Claude Desktop、Claude Code CLI、OpenClaw、Hermes 和开源 agent 各自保留来源，普通召回按 active 分层逐步放宽。
- **Windows 继续原生优先**：普通 Windows 用户走 PowerShell 原生安装；WSL 只保留给开发和特殊排障。

### 2026.6.4

- **Windows 官方 Codex 原生接入跑通**：在原生 Windows 机器上验证官方 Codex 不在 PATH 时，Time Library也能从 native-host 元数据找到 bundled `codex.exe`，再用官方 `codex mcp add` 注册 `time-library-memory`。
- **Windows 原生验收脚本**：新增可重复运行的本机 smoke，检查服务健康、官方 Codex MCP 注册和只读 capability check，不做真实召回。
- **三端 smoke 口径统一**：macOS / Linux 安装后 smoke 也会执行只读 capability check，确认 `time_library_recall` 入口可用且不做真实召回。
- **Windows 原生安装成为默认路径**：普通 Windows 用户走 PowerShell 原生安装；WSL 只保留给开发、高级测试和特殊排障。
- **Codex 当前窗口 bridge**：Codex MCP 不再直接用裸 HTTP 猜会话，而是通过 stdio bridge 注入窗口/session 绑定线索，缺绑定时按窗口优先契约返回缺口。
- **窗口级防污染继续收紧**：默认召回仍是当前窗口/当前 session；跨窗口、platform、raw-pool 等宽范围读取必须显式 routing，Hermes 宽上下文仍只属于 skill 生成或审查特例。
- **持续同步状态可见**：新增状态说明 watcher 是持续循环，不是安装时扫一次；已验证采集器和仍待验证的工具会分开显示。
- **本地对话采集更严**：本地 assistant 工具必须证明同时保留用户发言和 AI 回复，才算完整对话记忆来源；只保存用户话时只能作为证据候选。
- **模型识别作为第二层**：先用本地规则、路径、配置和存储形态识别；如果用户配置了模型，再用模型根据元数据识别陌生本机 AI 工具。
- **知识库补齐**：新增 Windows 官方 Codex 原生验证说明和 wiki 排障页，避免下个窗口又从头判断。

### 2026.6.3

- **Skill 变成长期记忆规则**：安装后不只是提示一次，而是要求 Codex、Claude Desktop 和其他本机 agent 在旧决定、纠错、边界、安装/测试/发布状态和“下一步/还有吗”这类问题前先调 `time_library_recall`。
- **自动接入计划更完整**：平台发现不再只停在“看见了入口”，接入前预览和接入回执会说明 MCP 连接、采集边界和原始归档形状。
- **采集边界继续钉住**：自动发现和 dry-run 阶段不读聊天正文；只有验证过的本地格式采集器才能把工具提升为 source-backed conversation memory。
- **窗口级防污染重新写入知识库**：默认仍是每个窗口先读自己的记录；Hermes 普通召回也按窗口隔离，项目级、同电脑、全局和 Hermes 审查/skill 生成这类宽范围读取必须走显式 routing。
- **Claude 当前窗口采集列为紧急缺口**：Claude 能调用 `time_library_recall` 不等于当前 Claude 窗口自己的历史已进库；后续要补当前窗口 ingestion 和 source attribution。
- **Windows 原生安装重新明确**：Windows 用户默认走原生 PowerShell 安装，WSL 仅用于开发或高级测试。
- **本地 assistant 工具进入验证项**：有些工具可能本地只保存用户话、不保存 AI 回复；未证实前只标记为候选，不宣传完整对话召回。
- **发布历史整理**：旧版本细节归入历史页，README 只保留当前版本和最常用入口。

### 2026.6.2

- **Claude 真实召回跑通**：Claude 可以通过本机 `time-library-memory` MCP 先做只读能力检查，再做真实 recall；旧的超时和错误响应路径已经收口。
- **中文摘录恢复可读**：Windows Claude 召回到的 `raw_excerpt` 不再乱码，可以直接读中文原文片段。
- **Windows Claude 配置更稳**：Claude 配置文件不再被 BOM 卡住，本机 bridge 输出 Claude 期望的 JSON-line；普通安装路径和 Store 路径都纳入注册。
- **多工具来源一起可见**：OpenClaw、Hermes 等来源的本机记录可以一起召回，同时保留 source refs、归属和证据线索。
- **按电脑优先的目录真实可见**：新增记录开始按“计算机名 -> 软件名 -> 软件各自保存格式”组织，方便以后多机器汇总时先按电脑看。
- **Skill 更会提醒 agent 调记忆**：遇到旧决定、纠错、项目边界、安装/测试/发布状态和“下一步”这类问题，提示 agent 先调用 `time_library_recall`。
- **Wiki 源文件补齐**：新增本地 Wiki 源页，覆盖入门、安全能力检查、AI 工具边界、记忆目录和发布历史分流。

### 2026.6.1

- **英文首屏改为 Memcore Cloud**：对外英文名统一为 Memcore Cloud，Time Library 保留为中文名和 product name，方便英文搜索和仓库定位。
- **本机 agent 安装提示前置**：README 首屏放置可直接发给 Codex、Claude Code CLI、OpenClaw、Hermes 等本机 agent 的安装提示，让 agent 顺手安装 Skill 并注册 `time-library-memory` MCP。
- **本机 AI 工具发现**：新增只读状态页和接入前预览，能显示这台机器上有哪些 AI 工具、哪些可以检查、哪些需要下一步授权。
- **Claude Code CLI 可接入候选**：Claude Code CLI 不再只是边界说明对象；现在可以进入授权接入预检，但仍与 Claude Desktop 分开管理，不读取 CLI 对话正文。
- **按电脑整理本机记录**：2026.6.1 起，新装和新增记录先按电脑分组，再按产生记录的 AI 工具分组。旧目录继续可读，但新记录走新契约。
- **公开入口更像产品页**：README 和发布说明减少内部工程词，优先讲用户能直接试的能力。

### 2026.5.31

- **自然语言纠错入口**：当用户在原来的 AI 工具里说“这条记错了”“你理解偏了”“不是我的意思”时，Time Library会把它识别为勘误候选，而不是继续当作普通偏好写入。
- **方法信号候选**：外部资讯、工具仓库和实践反馈可以先进入 `external_method_signal_candidate` dry-run，作为“新方法是否值得沉淀”的候选，不直接安装或激活。
- **Agent 安装闭环**：README 提供可直接发给 AI agent 的安装提示；安装器会自动安装 Codex skill，并在检测到 Codex CLI 时注册 `time-library-memory` MCP，也会在检测到 Claude Desktop 时注册本机 MCP bridge，用户不需要先理解 Skill 或 MCP。
- **Hermes learning heartbeat**：新增只读 native learning liveness 检查，报告最近是否有 Hermes `background_review`、`skill_manage` 和 skill 文件变化，帮助区分“会被触发时能学”和“这几天自然链路冷掉了”。
- **Hermes 消费回执**：按 Hermes 官方 MemoryProvider 生命周期补齐 `sync_turn` 回执和 `queue_prefetch` 预热；`sync_turn` 回执走后台线程，避免阻塞 Hermes hook。Hermes 不复制 OpenClaw 的 before-dispatch 拦截形态，但每轮可以记录“是否召回、命中多少、是否进入 turn 后回执”。
- **Hermes 技能与经验对比升级**：新增只读 `skill-experience-diff` dry-run，把 Hermes 生成或修改的 skill 与Time Library现有经验对照，产出待审 adoption / upgrade 候选；不直接写 Hermes skill，也不直接写正式经验。
- **Claude Desktop 一等公民接入**：Claude Desktop 与 Claude Code CLI 分开登记。Claude Desktop 可作为 MCP / Desktop Extension 消费端，也可作为本机 source-system 被发现；新增消费侧诊断，区分“只装通用 Skill 有信号”和“已检测到 MCP / Desktop Extension 可真正召回”。主链路是本机用户态同步清单和 sync-state receipt；读取和页面展示可以按 `claude_all` 聚合全部 Claude 入口，Windows 上通过中转服务或 Claude Code 运行时产生的记录会保留 `storage_owner`、`conversation_origin`、`runtime_consumer` 双归属字段和隔离边界。官方导出包只作冷启动或补档 fallback，内容读取另走授权 parser gate。
- **状态账本 / 时间索引**：新增只读 dry-run，回答“当前最新可信判断是什么”，同时把已采用、待复核、已废弃、被替代和冲突记录放在同一条时间线上；时间索引只是导航，不替代 raw。
- **上下文预算最小单元**：新增 `context_budget_unit_candidate` dry-run，把纠错、工具事实、方法信号、工作经验等整理成可回源、可组合、可过期复核的上下文最小单元；“粒子/离子”命名仍按待核验方向处理，不写成已确认原话。
- **模型事实只读方向**：Time Library读取 OpenClaw / Hermes / Codex 已有模型配置供自己判断和测试，不写回平台，不把自己做成模型中心。

### 2026.5.30

- **真实任务集 benchmark**：新增多案例 dry-run，用同一批真实任务形状对比无记忆、只有偏好层、preference plus work-experience，先看信号质量，再决定是否建设 Replay 反哺队列。
- **偏好提取更谨慎**：新增偏好意图 gate。用户纠错、指代澄清、转述审计材料和创作提示不会因为出现“称呼”“偏好”等词就被写成长期偏好层偏好。
- **Windows 大样本实测**：在 Windows 本地服务上做运行测试，验证 Web、Replay/benchmark、MCP、OpenClaw raw 查询、source_refs 和错误日志状态。

### 2026.5.29

- **时间图书馆馆藏**：原始记忆是底本，偏好层是理解类馆藏，经验层是工作经验和工具书。图书馆里不只放“懂你”的书，也放能指导做事的工具书。
- **召回可解释**：召回结果会带 `library_id`、书架、来源、命中方式和排序理由，方便知道这条经验为什么被带出来。
- **经验层对象生产化**：经验层候选开始按工作场景、行动策略、禁用条件、验收方式和生命周期整理。
- **轻量图谱与混合召回契约**：先提供用户、项目、平台、任务、偏好、工作经验这些节点和强关系，配合 source_refs、关键词、向量可用状态和项目过滤。
- **效果回放计划**：新增只读回放计划，用同一批任务对比无记忆、只有偏好层、preference plus work-experience的差异。
- **经验闭环 dry-run**：7 步流程穿过五书架，并用确定性规则检查 4 个防御指标和 1 个进攻指标；回放后生成待审反哺候选，不自动写入正式经验。
- **使用回执**：每次召回都会说明用了哪些馆藏号、哪些来源、为什么命中，以及本轮没有写入平台。
- **工具书候选入口**：平台事实、环境差异和命令实测可以先生成工具书候选；当前是 dry-run / validate，不直接写入馆藏。
- **Codex 本地接入**：读取本机 Codex 会话记录，进入同一个本地记忆底座。
- **通用偏好层入口**：新窗口可以用 `/memory` 接上前情；英文环境可用 `/memory`、`/recall`、`/continue` 或 `catch me up`。
- **Skill / MCP 接入**：提供平台中立的 `time-library-memory` Skill，以及只读的 `time_library_recall` 召回入口。
- **能力检查模式**：安装和冒烟测试可以用 `mode=capability_check` 验证 Skill / MCP / 只读状态，不触发召回、不返回原文。
- **共享记忆底座**：OpenClaw、Hermes、Codex 可以使用同一套本地原始记忆，但各自窗口和 agent 仍分开管理。
- **增量与续读**：正在增长的会话文件从上次位置继续读取，旧记录回源时支持分段补查。
- **来源可回看**：偏好层经验带馆藏号、状态和来源线索，尽量回到原话出处。
- **经验层说明补齐**：经验层作为工作经验层，负责把做事过程里的经验沉淀成下一次可参考的路径。
- **本地网关加固**：只读召回网关显式限制本机回环访问，并防止续读状态误写入平台配置目录。

### 2026.5.28

- **更轻的记忆调用方式**：`/memory`、`/memory`、`/recall`、`/continue` 和 `catch me up` 可以作为入口意图，让新窗口接上前情。
- **初版归档目录**：偏好层开始有稳定目录号、归档卡片、可回源证据输出和 archivist 风格提示。
- **经验层定位清晰**：经验层被明确为工作经验层，把过去的失败、修正、检查和做事路径沉淀成下一步参考。
- **经验不等于 Skill**：偏好层保存偏好和意图经验，经验层保存可回源工作经验；经验不能被压扁成一个可调用函数。
- **平台中立 Skill / MCP**：提供 `time-library-memory` skill，以及只读 `time_library_recall` 召回入口。
- **原话仍是最高事实**：保存内容不脱敏、不改写、不只保留哈希；摘要和经验可以帮助浏览，但不能替代原文。
- **本地网关加固**：raw gateway 明确拒绝非本机回环访问，并防止 cursor-state 误写进平台配置目录。

### 2026.5.27

- **Codex local sessions enter the memory base**：Codex 本地 sessions 可以被发现并保存为 raw memory。
- **Codex 记录可进入偏好层经验**：Codex 记录可以整理成带 source refs 的偏好层经验。
- **多平台共享本机 raw 底座**：OpenClaw、Hermes、Codex 使用同一个本地原始记忆底座，同时保持平台和窗口边界。
- **增量读取**：正在增长的 session 文件从上次偏移继续捕获。
- **raw 证据回看**：支持按 byte offset 直接回到证据位置，旧记录可用分段 fallback。
- **Hermes 默认只读消费**：Hermes 以只读方式读取共享本地记忆底座。

## English

### 2026.6.12

- **Public relay denaming**: public docs, catalogs, watchlists, diagnostics, and tests no longer present a specific local relay product as a public dependency or platform entry.
- **Compatibility without publicity**: existing personal relay paths, environment variables, database names, and raw formats can still be recognized, while user-visible payloads use neutral `local_relay` wording.
- **Lost wording is fixed**: record guardian diagnostics keep lost source / lost raw semantics instead of legacy stray-record wording.
- **Package validation prevents regression**: the release gate scans public and repository text surfaces for removed relay names and legacy stray-record diagnostics before a package is accepted.
- **Version consistency**: installers, gateway health, active-memory routing, preflight metadata, the local console, and packaged Time Library skill metadata report 2026.6.12.

### 2026.6.11

- **Recoverable checkpoints**: corrupt P0 and P2 checkpoints are backed up as `.corrupt-backup-*`, and new checkpoint saves use atomic replacement.
- **Stable canonical session identity**: Codex and Claude Code records use the native session id in the canonical index while preserving older workspace/window hints.
- **Active but restrained memory preflight**: short continuations, status follow-ups, and corrections can surface source-backed anchors before an answer; weak matches retreat silently.
- **Current-window fast path**: the raw gateway can answer current-window preflight from the canonical record index without broad recall or returning raw excerpts.
- **Claude Code auto-entry hook**: installers can write a `UserPromptSubmit` hook that only adds context when preflight returns a source-backed surface decision.
- **Tighter runtime guards**: raw gateway health includes source identity and hash, Windows guardian reports port ownership, and dialog-entry tokens stay scoped to dialog-entry service commands.

### 2026.6.9

- **Record first**: raw source records are treated as the origin of the memory timeline, with guardian checks for freshness, corruption, recovery, lost source, and lost raw states.
- **All-session indexing**: Codex, Claude Code CLI, Claude Desktop, OpenClaw, Hermes, and other verified local records can enter the canonical index while summaries remain navigation rather than authority.
- **Claude Desktop has three surfaces**: Chat is the `claude.ai` web-chat and cache-evidence surface; Cowork and Code/agent use verified local JSONL bodies when available.
- **LAN safety tiers**: local action entry points are token-gated while intentional LAN use for OpenClaw / Hermes remains possible.
- **Second Brain and Time River are constrained**: material processing, external docs evidence, context delivery compaction, and Time River sediment now have bounded dry-run contracts that strengthen source-backed recall without replacing raw.
- **Stronger package validation**: the release gate checks installers, public wording, internal direction, core record reliability, and the full test suite.

### 2026.6.6

- **Desktop companion entries**: Windows tray and macOS menu bar entries can open the local page, show health, and catch up missed records.
- **Local sync is closer to live use**: watchers keep running after install instead of acting like a one-time scan; restart and repair flows can catch up new records.
- **One main model setting**: users only see one model setting for Time Library. The same route can also help identify unfamiliar local AI tools when configured.
- **Smarter recognition with restraint**: default scans stay metadata-only; optional model calls do not include chat bodies or raw excerpts.
- **Source boundaries stay clear**: Codex, Claude Desktop, Claude Code CLI, OpenClaw, Hermes, and open-source agents keep their own source trails, with ordinary recall widening through active routing.
- **Native Windows remains first**: normal Windows users install with PowerShell on Windows itself; WSL stays for development and special troubleshooting.

### 2026.6.4

- **Official Windows Codex was verified natively**: on a clean native Windows machine, Memcore Cloud found the bundled official `codex.exe` from native-host metadata even when `codex` was not on `PATH`, then registered `time-library-memory` through official `codex mcp add`.
- **Native Windows smoke check**: added a repeatable local smoke script for service health, official Codex MCP registration, and read-only capability checks without real recall.
- **Three-end smoke checks are aligned**: macOS and Linux post-install smoke now also runs read-only capability check to prove `time_library_recall` is available without real recall.
- **Native Windows is the default path**: normal Windows installs use PowerShell natively; WSL remains for development, advanced testing, and special debugging.
- **Codex uses a current-window bridge**: Codex MCP now goes through a stdio bridge that injects window/session binding hints instead of guessing another Codex session.
- **Window-level anti-pollution stays enforced**: default recall is current-window/current-session first; platform, raw-pool, and cross-window scopes require explicit routing, with Hermes broad context limited to skill-generation or review workflows.
- **Continuous sync status is visible**: the local service reports watcher loop state and separates ready collectors from discovered-but-pending tools.
- **Local conversation collectors are stricter**: local assistant tools must prove both user turns and assistant replies persist before they count as complete conversation memory.
- **Model identification is the second layer**: deterministic local recognition runs first; model-assisted identification can classify unfamiliar local AI tools from metadata when a model provider is configured.
- **Knowledge base pages were updated**: the native Windows official Codex validation and troubleshooting path now live in the wiki.

### 2026.6.3

- **The skill is now a standing memory rule**: after install, Codex, Claude Desktop, and other local agents are told to call `time_library_recall` before answering prior-decision, correction, boundary, install/test/release-status, and short follow-up questions.
- **Auto-connect plans are more complete**: discovery no longer stops at "we saw an entry point"; previews and receipts now describe the MCP connection, collection boundary, and raw-archive shape.
- **Collection boundaries stay locked**: discovery and dry-runs do not read chat bodies; only verified local format collectors can promote a tool into source-backed conversation memory.
- **Window-level anti-pollution is documented again**: the default is still current-window first; ordinary Hermes recall is window-scoped too, while project, same-computer, global, and Hermes review/skill-generation scopes must be routed explicitly.
- **Claude current-window capture is an urgent gap**: Claude can call `time_library_recall`, but that does not prove the current Claude window's own history has entered memory.
- **Native Windows install is the default**: WSL remains for development or advanced testing, not normal Windows installs.
- **Local assistant tools need assistant-reply verification**: if local records only persist user prompts, the tool stays a candidate until complete conversation persistence is proven.
- **Release history was cleaned up**: older details moved into this history page so the README can stay focused on the current release and common entry points.

### 2026.6.2

- **Claude real recall works**: Claude can call the local `time-library-memory` MCP path, run a read-only capability check first, and then perform real recall without the old timeout / error-response failure.
- **Chinese excerpts are readable again**: recalled `raw_excerpt` text from Windows Claude no longer turns into garbled characters.
- **Windows Claude setup is steadier**: Claude config is written without BOM trouble, the local bridge returns JSON lines, and both regular and Store-style config locations are covered.
- **Multiple local tools show up together**: OpenClaw and Hermes records can appear in the same recall result while keeping source refs, attribution, and evidence visible.
- **Computer-first layout is visible in practice**: new records follow the computer -> source tool -> app format shape, which keeps multi-machine memory easier to browse later.
- **The skill nudges agents to ask memory first**: previous decisions, corrections, project boundaries, install/test/release status, and "what next" questions now have a stronger `time_library_recall` instruction.
- **Wiki source pages are ready**: local Wiki pages now cover getting started, safe capability checks, AI tool boundaries, memory layout, and release-history routing.

### 2026.6.1

- **English-first name: Memcore Cloud**: the repository now presents Memcore Cloud as the product name while keeping Time Library as the Chinese name and product name.
- **Local-agent install prompt near the top**: the README exposes a prompt users can paste into Codex, Claude Code CLI, OpenClaw, Hermes, or another local agent so the agent can install the workflow skill and register `time-library-memory` MCP.
- **Local AI tool discovery**: adds a read-only status page and connect-before-changing preview so users can see which local AI tools are present, which ones are checkable, and which ones need one more permission step.
- **Claude Code CLI as a connectable candidate**: Claude Code CLI can now enter the connection preview flow while staying separate from Claude Desktop and behind a parser gate for conversation bodies.
- **Organized local records**: starting in 2026.6.1, new records are grouped by computer first, then by the AI tool that produced them. Older layouts remain readable, but new records follow the new contract.
- **More product-facing public entry**: the README and release notes now talk first about what users can try, with implementation details kept in lower-level change logs.

### 2026.5.31

- **Natural-language correction entry**: when the user says a memory is wrong, misunderstood, or not their meaning inside the AI tool they already use, Time Library can shape that into an errata candidate instead of treating it as another preference.
- **Method-signal candidates**: external news, tool repositories, and practice feedback can enter an `external_method_signal_candidate` dry-run before anything is installed or activated.
- **Agent install loop**: README now includes a prompt users can send directly to an AI agent; installers automatically install the Codex skill, register the `time-library-memory` Codex MCP when Codex CLI is available, and register a Claude Desktop local MCP bridge when Claude Desktop is detected, so users do not need to understand Skill or MCP first.
- **Hermes learning heartbeat**: adds a read-only native learning liveness check for recent Hermes `background_review`, `skill_manage`, and skill-file changes, making it visible when the natural learning chain has gone cold.
- **Hermes consumption receipts**: follows the official Hermes MemoryProvider lifecycle. `prefetch` recalls and injects context, `queue_prefetch` warms the next turn, and `sync_turn` records a Time Library-side consumption receipt on a background thread without writing Hermes skills or memory.
- **Hermes skill vs experience diff**: adds a read-only `skill-experience-diff` dry-run that compares Hermes-created or updated skills with existing Time Library experience and produces review-only adoption / upgrade candidates. It does not write Hermes skills or production experience.
- **Claude Desktop first-class source**: Claude Desktop is registered separately from Claude Code CLI. It can consume Time Library through MCP / Desktop Extensions and can be discovered as a local source system. Consumer diagnostics now distinguish a generic skill signal from a working MCP / Desktop Extension recall connection. The primary line is a local sync manifest plus sync-state receipt; readers can aggregate all Claude surfaces under `claude_all`, while Windows relay / Claude Code related records keep separate `storage_owner`, `conversation_origin`, and `runtime_consumer` attribution fields plus isolation boundaries. Official exports are cold-start/backfill fallback only, with content parsing behind an authorized parser gate.
- **State Ledger / Temporal Index**: adds a read-only dry-run for answering the latest trusted judgment while keeping adopted, pending, deprecated, superseded, and conflicting records visible on the same timeline. The temporal index is navigation only, not a replacement for raw records.
- **Context Budget Units**: adds a `context_budget_unit_candidate` dry-run for source-backed, composable, reviewable context units such as corrections, tool facts, method signals, and work experience. The particle/ion wording remains an unconfirmed direction, not claimed source wording.
- **Read-only model facts**: Time Library reads existing OpenClaw / Hermes / Codex model facts for its own checks and does not write them back.

### 2026.5.30

- **Real-task benchmark dry-run**: adds a multi-case benchmark so the same task set can compare no memory, preference-only memory, and preference plus work-experience memory before any Replay feedback queue is built.
- **More precise preference extraction**: adds an intent gate so corrections, deictic disambiguation, relayed audit/task text, and creative prompts do not become durable preferences just because they contain preference-like words.
- **Windows large-sample smoke test**: the Windows local service was verified with Web, Replay/benchmark, MCP, OpenClaw raw query, source refs, and error-log checks.

### 2026.5.29

- **Time Library knowledge shelves**: raw records are the source texts, the preference shelf is the understanding shelf, and the work-experience shelf keeps work experience and toolbook-like guidance.
- **Explainable recall**: recall results can include `library_id`, shelf, source refs, match method, and rank reason.
- **Production-shaped work-experience objects**: work-experience candidates now carry scenario, action strategy, avoid conditions, acceptance checks, scope, and lifecycle status.
- **Light typed graph and hybrid recall contract**: starts with user, project, platform, task, preference, and work-experience nodes, then combines source refs, keyword matching, vector readiness, and project/time filters.
- **Replay plan**: adds a read-only plan for comparing no memory, preference-only memory, and preference plus work-experience memory on the same task set.
- **Experience loop dry-run**: a seven-step flow crosses the five shelves, checks four defensive metrics plus one offensive metric, and produces review-only feedback candidates instead of writing adopted experience automatically.
- **Explainable usage receipts**: each recall can report which library ids and source refs were used, why they matched, and that no platform write happened.
- **Toolbook candidate entry**: platform facts, environment differences, and command probes can be shaped into toolbook candidates; this first entry is dry-run / validate only.
- **Codex local support**: reads local Codex session records into the same local memory base.
- **Universal memory entry**: use `/memory` to pick up a thread in a new window; English users can also use `/memory`, `/recall`, `/continue`, or `catch me up`.
- **Skill / MCP access**: includes the platform-neutral `time-library-memory` skill and a read-only `time_library_recall` recall entry.
- **Capability check mode**: install and smoke tests can use `mode=capability_check` to verify Skill / MCP / read-only status without running recall or returning source text.
- **Shared local memory base**: OpenClaw, Hermes, and Codex can benefit from the same original records while their agents and windows remain scoped.
- **Incremental and resumable reading**: growing session files continue from saved offsets, and older source lookup can resume in segments.
- **Traceable experience**: preference and work-experience records can carry catalog ids, lifecycle status, and source anchors.
- **Clearer work-experience wording**: the work-experience layer is documented as the layer that turns prior work into reviewable next steps.
- **Local gateway hardening**: the read-only recall gateway explicitly accepts loopback clients only and guards cursor-state writes from platform config folders.

### 2026.5.28

- **Lighter memory entry**: `/memory`, `/memory`, `/recall`, `/continue`, and natural phrases such as `catch me up` can express the intent to continue with local memory.
- **Initial archive catalog**: preference records gain stable catalog ids, archive cards, source-aware evidence output, and an archivist-style prompt.
- **Work experience**: the work-experience layer turns previous work, failures, corrections, and checks into reviewable next steps.
- **Experience is not a skill library**: The preference shelf keeps preference and intent experience, while the work-experience shelf keeps source-backed work experience that cannot be reduced to a callable function.
- **Platform-neutral Skill / MCP**: includes the `time-library-memory` skill package and a read-only `time_library_recall` recall entry.
- **Original words remain the highest fact**: saved content is not redacted, rewritten, or replaced by hash-only records; summaries and experience help navigation but do not replace source text.
- **Local gateway hardening**: the raw gateway rejects non-loopback clients and guards cursor-state writes from platform config folders.

### 2026.5.27

- **Codex local sessions enter memory**: Codex local sessions can be discovered and preserved as raw memory.
- **Codex records become traceable experience**: Codex records can be organized into source-backed experience with source references.
- **Shared local raw base**: OpenClaw, Hermes, and Codex share the same local raw memory base while keeping each platform and conversation window separate.
- **Incremental capture**: growing session files are captured from saved offsets.
- **Raw evidence lookup**: evidence lookup can jump to byte offsets, with resumable segmented fallback for older records.
- **Hermes reads in read-only mode**: Hermes can consume the shared local memory base without writing platform memory by default.
