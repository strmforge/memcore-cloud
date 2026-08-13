# Getting Started

## Install

2026.8.13 is the current release candidate. The latest published release is
2026.7.18; use the published 7.18 installer URLs below until this candidate is
published.

macOS / Linux:

```bash
curl -fL -o time-library-install.sh https://github.com/strmforge/time-library/releases/download/v2026.7.18/install.sh
bash time-library-install.sh
```

Windows PowerShell:

```powershell
iwr https://github.com/strmforge/time-library/releases/download/v2026.7.18/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

If you downloaded the release zip, you can also use the Windows installer entry
or the macOS installer entry from the extracted release folder.

Windows installs default to `%LOCALAPPDATA%\time-library`. To choose a path
before the install:

```powershell
$env:TIME_LIBRARY_INSTALL_DIR = "D:\Apps\time-library"
iwr https://github.com/strmforge/time-library/releases/download/v2026.7.18/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

If you already downloaded the repo, you can also run:

```powershell
.\install.ps1 -Dir "D:\Apps\time-library"
```

WSL is only for development or advanced testing. Normal Windows installs should
use the Windows PowerShell command above.

On Windows, use the Time Library tray icon after install. On macOS, use the
Time Library menu bar icon. Both can open the local console, show health, and
catch up missed records.

You can also open the local console directly:

```text
http://127.0.0.1:9850
```

## Paste This To Your Local Agent

If you use a local AI agent that can run terminal commands, paste this:

```text
You are installing Time Library for me on this machine.
Repository: https://github.com/strmforge/time-library

First check whether Time Library is already installed and running on this machine. Read `<TIME_LIBRARY_ROOT>/runtime/front_door_port` and probe the discovered front door and any local install marker you know how to inspect. If it is already installed and reachable, do not reinstall it. If it is not installed, install and start Time Library. In either case, connect this host only through capabilities the host actually reports; do not ask Time Library for a product-name adapter.

Then install Time Library as a standing memory rule for this agent, not just a one-time setup note. Before changing host configuration, inspect what this host supports. The host report is authoritative; product-name inference is only a hint. Use the documented, reversible configuration path owned by the host. If it supports MCP, register the MCP tool named time-library through the discovered front door at /mcp?startup_catalog=deferred. If it supports a skill or custom-instruction surface, add the Time Library skill/instruction. If it exposes a prompt/preflight hook, connect that supported hook to the local Time Library preflight path; the hook must stay quiet and never block prompts when the discovery file is unavailable. Record truthful source_system, client/window or session identity, skill_surface_status, config_write_authority, and current reading-area/project/series scope. Keep unsupported capabilities explicitly unsupported.

After setup, run only a safe capability check with time_library_recall:
{"query":"capability check","mode":"capability_check"}
Do not recall my real memory yet; do not recall my real memory until I ask.

Capability check is not connection proof. Later, only when one of my questions actually needs prior context and therefore authorizes real recall, call time_library_recall and retain a returned ZX-* library_id. In the same initialized MCP session, call time_library_reading_area with action self_report_connect, using the host-reported source_system, current canonical_window_id or session_id, truthful skill_surface_status and config_write_authority, one truthful reading_area/declared_project_ids/declared_series_ids scope, and proof_library_id set to that returned library_id. If any required fact or proof is missing, leave verification pending; never invent it. Then repeat the authorized recall through the verified connection. Handle a delivery challenge only after the host model actually received and used the cited refs. Never recall private memory merely to prove installation.

Keep this rule active from now on. When my question depends on prior context, call time_library_recall before answering and use source refs by default; ask for raw excerpts only when I explicitly need original evidence text. Triggers include previous decisions, corrections, project boundaries, forgotten context, install/test/release status, and short follow-ups in ongoing work such as "next step", "what else", or "then what". Use active recall by default: current window/session first, then same project/workspace, same workstream/task, then stable preferences/tool facts. Use wider shared or global memory only when I explicitly ask for that wider view. If explicit window-only recall says the current window/session is not bound yet, say that plainly; do not claim there is no memory. If the skill is installed but time_library_recall is not available, tell me the MCP/tool connection is missing instead of guessing from memory. You may mention legacy zhiyi_recall only as a migration fallback, not as the primary instruction.
```

Chinese prompt:

```text
你正在帮我在这台机器安装 Time Library。
仓库：https://github.com/strmforge/time-library

请先检查这台机器上的 Time Library 是否已经安装并在运行。先读取 `<TIME_LIBRARY_ROOT>/runtime/front_door_port` 并探测发现的门面，也检查你已知的本地安装标记。如果已经安装且可达，就不要重装；如果没装，再安装并启动 Time Library。无论哪种情况，都只按宿主真实自报的能力接入，不要让 Time Library 按产品名新增适配器。

然后把 Time Library 安装成这个 agent 的长期记忆规则，不只是一次性安装说明。修改宿主配置前，先检查并自报宿主支持哪些能力；宿主自报是权威，按产品名推断只能作提示。只使用宿主自己提供的、可回滚的正式配置路径。支持 MCP 就注册名为 time-library 的 MCP 工具，通过发现文件连接门面的 /mcp?startup_catalog=deferred；支持 skill 或自定义指令就添加 Time Library skill/指令；支持 prompt/preflight hook 就按宿主正式方式把它接到本机 Time Library preflight，且发现文件不可读时必须静默软失败，不能刷屏、不能卡 prompt。如实记录 source_system、当前窗口或 session 身份、skill_surface_status、config_write_authority，以及当前 reading-area/project/series 范围；不支持的能力明确保留为不支持。

安装完成后，只做一次安全能力检查：
{"query":"capability check","mode":"capability_check"}
先不要召回我的真实记忆。

capability check 不是接通证明。以后只有当我的真实问题确实依赖旧上下文、因而授权真实召回时，才调用 time_library_recall，并保留返回的 ZX-* library_id。在同一个已 initialize 的 MCP session 中调用 time_library_reading_area，action 使用 self_report_connect，如实填写宿主自报的 source_system、当前 canonical_window_id 或 session_id、skill_surface_status、config_write_authority、一个真实的 reading_area/declared_project_ids/declared_series_ids 范围，并把 proof_library_id 设为刚才返回的 library_id。缺任何必需事实或证明时都保持待验证，不得编造。随后通过已验证连接重放这次获授权的召回；只有宿主模型真正收到并使用了引用来源后，才处理 delivery challenge。不得为了证明安装成功而擅自召回私有记忆。

以后请持续遵守这条规则。凡是我的问题依赖旧上下文，请先调用 time_library_recall，默认结合 source_refs 回答；只有我明确需要原文证据时，才请求 raw_excerpt。触发词包括：之前、定论、纠错、边界、忘了、安装/测试/发布状态，以及持续项目里的“下一步/接下来呢/还有吗/然后呢”。默认使用 active 召回：当前窗口/session 优先，然后同项目/同工作区、同工作流/同任务、稳定偏好/工具事实。只有我明确要求更宽视图时，才使用共享或全局记忆。如果显式 window-only 召回提示当前窗口/session 还没绑定，请直接说明这个绑定缺口；不要说没有记忆。如果 skill 已安装但 time_library_recall 不可用，请告诉我 MCP/工具连接还没接上，不要凭印象猜。`zhiyi_recall` 只能作为迁移期兼容别名，不要当主指令。
```

## First Run

1. Start the local service.
2. Open `http://127.0.0.1:9850`.
3. Let Time Library find local AI tools and connect usable local entries.
4. Run capability check before real recall.
5. Use real recall when the current question depends on prior context.

Install once, then it keeps looking for usable local AI tools. Conversation import uses verified local formats, so memory can stay tied to source records.

## What To Check Next

- [Desktop Companion And Live Sync](Desktop-Companion-And-Live-Sync.md): make sure the watcher keeps running and missed records can be caught up.
- [Local Tool Recognition](Local-Tool-Recognition.md): see how Time Library identifies local AI tools and when the main model can help.
- [AI Tool Boundaries](AI-Tool-Boundaries.md): understand why different tools and windows keep their source trails.
