# 时间图书馆

<p align="center">
  <img src="assets/brand/time-library-logo-zh.png" alt="时间图书馆" width="220"/>
</p>

<p align="center">
  <strong>给本机 AI agent 的记忆层——带得出证据。</strong>
</p>

<p align="center">
  时间图书馆保留<em>原话出处</em>和时间，让一台机器上的多个 agent 共读同一块可回源记忆，你不用在中间当人肉传话。送达与使用回执已经接入，但模型真正收到并使用的证明仍在按平台逐一补齐。
</p>

产品名是 **时间图书馆 / Time Library**。。

时间图书馆是一套给本机 AI agent 使用的本地记忆层：捕获来源记录，带 source refs 召回，基于证据回答，安装长期 agent 规则，并在真实召回前检查健康状态。

最容易理解的入口是五步：

```text
捕获 -> 召回 -> 基于证据回答 -> 安装 agent 规则 -> 健康检查
```

它不是云聊天，也不是把聊天摘要塞进向量库。时间图书馆先守住本机原始记录，默认返回 source refs，需要原文时再展开有界摘录；同时给本机 agent 一条长期规则：什么时候该先查记忆，再回答或动手。

## 为什么是时间图书馆（不只是又一个记忆库）

三件大多数记忆库不做的事：

- **回源，不是转述。** 每张记忆卡都能回到原话的 byte 级出处。摘要是导航，原始记录才是权威。不是“我好像记得”，而是“原话在这，第几行”。
- **它保存时间，不只保存文字。** 有序时间戳与 raw → 日 → 摘要沉积，为历史视图保留地基；当前版本还没有对外可用的 as-of / 时间旅行查询入口。
- **多 agent 共读一块低污染池，免人肉转达。** 一台机器上，Codex / Claude / OpenClaw / Hermes 共读一块只读、可回源的项目记忆。开局只推**书单**（地图），不往你窗口里灌正文，召回低污染——你也不用再当在工具之间重复上下文的中间人。

**为什么不直接用 Cognee（或 Mem0）？** 设计重点不同：时间图书馆保留原话出处与时间，让多个 agent 共读同一块本机池，并携带送达/使用回执字段；这些字段目前还不能证明所有平台上的模型都已真正收到。回源不是装饰：本项目消融实验里，去掉双层/回源路径要掉 13.31 分。

## 核心流程

- **捕获来源记录**：保存原始对话、工具输出、来源工具、设备和时间线。摘要只帮助浏览，原始记录仍然是最高事实。
- **带 source refs 召回**：问旧决定、偏好、修复办法、项目边界或下一步时，默认返回精简来源线索、馆藏身份、命中理由和可选的有界原文摘录。
- **基于证据回答**：配置模型后，可以让模型只基于提供的 source evidence 回答并引用 supporting refs；证据不足就返回 `UNKNOWN`。
- **安装 agent 规则**：把 Time Library / 时间图书馆 skill/指令或 `time-library` MCP 工具装进 Codex、Claude、OpenClaw、Hermes、Cursor 类工具和其他本机 agent，让它们知道什么时候该先召回。
- **先检查健康再信任**：用 capability check、记录医生、preflight doctor 和分开的评测入口，避免安装检查、日常召回、回归测试和离线跑分混成一条路。

## 高级能力

- **跨工具本机上下文**：Claude Desktop、Claude Code CLI、Codex、OpenClaw、Hermes、Cursor 类工具和常见开源 agent 可以共用同一个本机记录底座。
- **preference and work-experience shelves**：偏好层保存偏好、纠正、习惯和项目边界；经验层保存修复路径、排障顺序、验收步骤、踩坑记录和工作方法。经验层不是技能库。
- **给所有本机 agent 接入经验**：通过通用 skill、自定义指令、MCP 和 `work_preflight`，让本机 agent 在动手前读取同一套有来源的经验层经验。
- **Hermes 技能经验进化**：Hermes skill 可以和时间图书馆的经验层经验做只读对比，生成新经验候选或升级候选，再进入有来源、有验收、有回滚的采编链路。
- **本机 agent 权限更安全**：记忆默认被动；召回上下文不能偷偷升级成直接回答，直接回答也不能偷偷升级成平台动作。
- **本地控制台**：浏览器里查看已识别工具、最近记录健康、安全能力检查和新 raw 记录保存位置。
- **评测入口分开**：日常召回、定向回归、离线跑分分开走，并记录资源账，避免跑分路径拖垮日常使用。
- **安装更直接**：支持一条命令、PowerShell，也支持 release zip 里的 macOS / Windows 双击安装入口。

## 阅读室与白板

阅读室是一台机器上多个 agent 的共享协作空间；里面那块进度流程图叫**白板**。项目状态、在飞任务、二签边界都留在同一张图上，新来的 agent 一眼看到项目到哪了，而不用回头问你。

## 送到了、用上了，不只是存着

库里有卡 ≠ agent 看见了。时间图书馆可以记录浮现回执和借阅评语——有用、没用、还是误导——再喂进下一轮经验候选。回执路径已经存在，但目前 7 个登记平台的模型内送达证明仍是 `0/7`；**产 → 用**是验收目标，不是已经完成的宣传结论。

## Hermes：自主经验升级

受控 run-once 已证明核心 Hermes 路径：新 raw 通过门控后，Hermes 自己写 skill，时间图书馆再生成只读、可回源的经验候选。系统调度器、每小时唤醒、24h 最小间隔和每日 1 次预算已经实现并通过 source/test；本版本不声称已经独立观察到无人值守后台 tick 点完整条链，也不声称候选会自动采纳进生产经验。

## 快速体验

安装后打开本地控制台：

```text
http://127.0.0.1:9850
```

先做安全能力检查：

```json
{"query":"capability check","mode":"capability_check"}
```

健康结果会显示只读、没有真实召回、没有返回原文。之后再问真实问题，例如：

```text
我们上次对这个项目定了什么边界？
```

时间图书馆默认先给来源线索；只有你明确需要原文时，才展开原始证据。

如果你要让 agent 改代码、安装、同步或排障，可以先让它查本机上下文。理想行为很简单：先告诉你这件事更像已经做过、接线错了、缺诊断，还是真的缺功能；然后再查仓库、测试和工具，最后才动手。

## 它记什么

AI 工具很聪明，但经常忘掉你已经说过的细节：你喜欢怎样表达、项目哪里不能动、上次怎么修好的、哪个坑不要再踩、某件事做到哪里了。

时间图书馆做的事很朴素：把这些线索留在本机，并且尽量带着来源。它不是云聊天，也不是把原话压成几句摘要的仓库。原始记录仍然是最高事实，整理出来的preference and work-experience shelves都应该能回到来源。

## 经验怎么进化

经验会进化，但不黑箱。时间图书馆现在支持的是**有证据、有验收、有回执的采编进化**。

经验更像图书馆采编：

```text
原始记录
→ 经验候选
→ 评审队列
→ 来源 / 原文 / 验收条件检查
→ 授权采纳或拒绝
→ 回滚、废弃或升级回执
```

一次做成过的修复路径，可以进入经验层；证据不足的经验会留在评审里；错误经验可以进入勘误或被回滚。现在支持的是“可审计的采编进化”，不是无人值守自动改写自己。

## 实际会得到什么

- **多个 AI 工具共享本机上下文**：Claude Desktop、Claude Code CLI、Codex、OpenClaw、Hermes、Cursor 类工具和正在流行的开源 agent 可以接到同一个本机记录底座。
- **做成过的办法可以跨窗口继续用**：偏好保持可用，做成过的办法沉淀成下一次可参考的路径。
- **喜好和经验分开管理**：偏好层保存偏好、纠正、习惯和边界；经验层保存修复路径、验证步骤和工作方法。
- **经验可以跨平台介入**：经验层不是某个工具的私有 skill；支持 skill、自定义指令或 MCP 的本机 agent，都可以在开工前读取同一套经验候选、避坑记录和验收步骤。
- **少重复修同一个问题**：agent 动手前可以先查你是不是已经做过这个功能、测过这条路径，或者踩过同一个接线坑。
- **记忆有来源**：召回不是凭感觉说“我记得”，而是尽量带来源线索、原始摘录、命中理由。
- **原话不被摘要替代**：摘要可以帮助浏览，但不能替代已保存的原始内容。
- **工具边界不混读**：Claude Desktop 和 Claude Code CLI 分开看待；官方登录、中转服务、CLI 运行时产生的记录会保留归属边界。
- **第一步可以安全测试**：capability check 只验证本机只读链路，不召回真实记忆、不返回原文。
- **安装一次，自动找到本机工具**：OpenCode、Goose、Aider、OpenHands 这类开源 agent 也会进入识别范围；可用的本机 AI 工具入口会自动接入，新的记忆源按设备优先归档。
- **新工具也能更快认出来**：如果你配置了模型，或本机已有可复用的 AI 模型设置，Time Library会根据本机元数据识别陌生 AI 工具；如果没配置，本地规则也能继续工作。

## 把这段发给本机 AI agent

如果你正在使用 Codex、OpenClaw、Hermes、Claude Code CLI 或其他能操作本机终端的 AI agent，可以直接把下面这段话发给它：

```text
你正在帮我在这台机器安装 Time Library。
仓库：https://github.com/strmforge/time-library

请先检查这台机器上的 Time Library 是否已经安装并在运行。先读取 `<TIME_LIBRARY_ROOT>/runtime/front_door_port` 并探测发现的门面，也检查你已知的本地安装标记。如果已经安装且可达，就不要重装；如果没装，再安装并启动 Time Library。无论哪种情况，都只按宿主真实自报的能力接入，不要让 Time Library 按产品名新增适配器。

然后把 Time Library 安装成这个 agent 的长期记忆规则，不只是一次性安装说明。修改宿主配置前，先检查并自报宿主支持哪些能力；宿主自报是权威，按产品名推断只能作提示。只使用宿主自己提供的、可回滚的正式配置路径。支持 MCP 就注册名为 time-library 的 MCP 工具，通过发现文件连接门面的 /mcp?startup_catalog=deferred；支持 skill 或自定义指令就添加 Time Library skill/指令；支持 prompt/preflight hook 就按宿主正式方式把它接到本机 Time Library preflight，且发现文件不可读时必须静默软失败，不能刷屏、不能卡 prompt。如实记录 source_system、当前窗口或 session 身份、skill_surface_status、config_write_authority，以及当前 reading-area/project/series 范围；不支持的能力明确保留为不支持。

安装完成后，只做一次安全能力检查：
{"query":"capability check","mode":"capability_check"}
先不要召回我的真实记忆。

capability check 不是接通证明。以后只有当我的真实问题确实依赖旧上下文、因而授权真实召回时，才调用 time_library_recall，并保留返回的 ZX-* library_id。在同一个已 initialize 的 MCP session 中调用 time_library_reading_area，action 使用 self_report_connect，如实填写宿主自报的 source_system、当前 canonical_window_id 或 session_id、skill_surface_status、config_write_authority、一个真实的 reading_area/declared_project_ids/declared_series_ids 范围，并把 proof_library_id 设为刚才返回的 library_id。缺任何必需事实或证明时都保持待验证，不得编造。随后通过已验证连接重放这次获授权的召回；只有宿主模型真正收到并使用了引用来源后，才处理 delivery challenge。不得为了证明安装成功而擅自召回私有记忆。

以后请持续遵守这条规则。凡是我的问题依赖旧上下文，请先调用 time_library_recall，默认结合 source_refs 回答；只有我明确需要原文证据时，才请求 raw_excerpt。触发词包括：之前、定论、纠错、边界、忘了、安装/测试/发布状态，以及持续项目里的“下一步/接下来呢/还有吗/然后呢”。默认使用 active 召回：当前窗口/session 优先，然后同项目/同工作区、同工作流/同任务、稳定偏好/工具事实。只有我明确要求更宽视图时，才使用 raw-pool/global。如果显式 window-only 召回提示当前窗口/session 还没绑定，请直接说明这个绑定缺口；不要说没有记忆。如果 skill 已安装但 time_library_recall 不可用，请告诉我 MCP/工具连接还没接上，不要凭印象猜。

写代码、安装、同步、发版准备或远端排障前，先做只读的开工前检查：
{"query":"<准备做的事>","mode":"work_preflight"}
用它先判断这件事更像已经做了但忘了、已经做了但接线错了、缺诊断入口，还是真的缺功能。这个结果只是起点；动手前仍然要查仓库、测试、工具和文档。
```

安装器会在支持 skill 或自定义指令的平台加入 Time Library，并在支持 MCP 的平台注册 `time-library`；改动本机配置时会留下备份和回执。

## 直接安装

2026.8.13 是当前正式发布版本。请使用下面的版本化安装地址。

macOS / Linux：

```bash
curl -fL -o time-library-install.sh https://github.com/strmforge/time-library/releases/download/v2026.8.13/install.sh
bash time-library-install.sh
```

Windows PowerShell：

```powershell
iwr https://github.com/strmforge/time-library/releases/download/v2026.8.13/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

如果下载了 release zip，也可以直接使用解压目录里的 Windows 安装入口或 macOS 安装入口。

Windows 默认安装到 `%LOCALAPPDATA%\time-library`。如果要自己选安装路径，
先设置路径再执行安装：

```powershell
$env:TIME_LIBRARY_INSTALL_DIR = "D:\Apps\time-library"
iwr https://github.com/strmforge/time-library/releases/download/v2026.8.13/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

如果已经下载了仓库，也可以直接运行：

```powershell
.\install.ps1 -Dir "D:\Apps\time-library"
```

WSL 只适合开发或高级测试。普通 Windows 用户请使用上面的 Windows
PowerShell 安装命令。

Windows 安装后会有 Time Library 托盘图标；macOS 安装后会有 Time Library 菜单栏图标。它们都可以直接打开本地控制台、查看健康状态，或者立刻补扫漏掉的记录。

也可以直接打开本地控制台：

```text
http://127.0.0.1:9850
```

## 安全第一步

安装或冒烟测试时，不要先用旧入口词。它可能真的召回本机记忆。请让客户端调用 `time_library_recall` 并带上：

```json
{"query":"capability check","mode":"capability_check"}
```

成功结果应该包含：

```text
read_only: true
recall_performed: false
raw_excerpt_returned: false
mcp_tools: ["time_library_recall"]
```

只有你明确决定测试记忆召回之后，才进入真实 recall。

## 记录医生

测试真实召回之前，可以先跑一键自检：

```bash
python3 tools/record_doctor.py
```

它会给出源记录、raw 镜像、所有会话底座、记忆与经验链路的只读报告；不会召回、不会回填、不会调用模型，也不会改平台配置。

## 本地诊断

诊断有意义，但不能和日常使用混在一起。Time Library把健康检查、记录检查和排障报告从日常召回里分开，避免诊断任务拖住正在使用的工作机。

先看记录医生和本地健康页面。更重的评测工作应该放到维护者自己的独立工作区里，不作为普通用户功能，也不当作公开榜单声明。

## 本地页面能看什么

打开 `http://127.0.0.1:9850` 可以看到：

- 这台机器上有哪些 AI 工具；
- 哪些可以先做安全能力检查；
- 哪些已经接入或可以接入本机 AI 工具入口；
- 源记录、raw 镜像、所有会话底座、记忆与经验链路是否守住；
- 某个工具最近是否还在用；
- 新的 raw 记忆按什么目录保存。

Windows 和 macOS 上都不用记端口，托盘/菜单栏图标就是入口。本机 watcher 会保持运行，并在重启或修复安装后补扫漏掉的记录。

可用的本机 AI 工具入口可以自动接入。对话进入记忆依赖已验证的本地格式采集器；能力检查仍然是无召回，只有 agent 明确调用 recall 才会读取真实记忆。

## preference and work-experience shelves

偏好层更靠近“理解你”：偏好、表达习惯、纠偏、背景和意图。

经验层更靠近“下次怎么做”：排障顺序、项目边界、踩坑记录、验收方法和工作经验。

开工前检查是一条只读入口：它让 agent 先查已有记录，再决定是不是应该继续动手。这样已经完成的功能不会因为下一个窗口忘了，就被重复设计一遍。

不同工具留下来的线索不一样。Time Library会把它们汇进同一条“时间长河”：先守住原始记录，再按来源、时间、馆藏身份、证据和生命周期沉淀成偏好层、经验层、工具书或勘误。你以后问起旧事，它应该能沿着时间和来源找回去，而不是只给一段没出处的摘要。

经验不是可调用函数，经验层不是技能库。偏好由偏好层记住，做事路径由经验层沉淀；如果某个偏好会影响工作，经验层可以引用它，但不会把偏好改名成经验层。

Time Library的底线是：你说过的话本身就是最高事实。任何替代原文的压缩，都是污染。

记录医生会用一键自检展示源记录、raw 镜像、所有会话底座、记忆与经验链路是否守住；记录链路页展示的是“记录怎么被守住”，不是炫技记忆墙。

## 当前发布版本

当前正式发布版本是 **2026.8.13**。这一版强化源记录保全、有限可恢复性诊断和
无人值守 Guardian 任务编排，同时保留 2026.7.25 的 fail-closed、保留
relay/provider 的 Codex MCP 配置守护器与 watcher；2026.7.18 已有的本机
安装、单前门、归档保全和透明账本边界继续保留。旧 `memcore-cloud` 目录仍作为
迁移源和卸载兜底保留，避免老用户数据丢失；本机 AI 工具接入边界、开工前
上下文检查、记录医生、可回源召回，以及证据绑定回答路径继续保留。

发布说明见 [RELEASE_NOTES_2026.8.13.md](RELEASE_NOTES_2026.8.13.md)，完整历史更新见 [UPDATE_HISTORY.md](UPDATE_HISTORY.md)，更底层变更见 [CHANGELOG.md](CHANGELOG.md)。

## AI 工具入口

- **Claude Desktop**：可通过本机 MCP / Desktop Extension 使用Time Library；来源记录走已验证的本地格式采集器。
- **Claude Code CLI**：可通过 MCP 使用Time Library，并与 Claude Desktop 分开管理。
- **Codex**：可使用通用 skill 和 MCP，本机会话也可以成为可回源记录。
- **OpenClaw**：可通过本机入口获得记忆辅助，但普通聊天默认不会被Time Library接管。
- **Hermes**：可读取 raw/source refs 路径指针并保留 Hermes 自己的反馈边界。
- **其他本机 AI 工具**：可以从本机设置、应用目录、包管理器和工作区痕迹里识别；可用入口会自动接入，本地格式验证后可成为记忆来源。

## 诚实边界（做到什么、不声称什么）

我们宁可少承诺。今天已证：可回源逐字召回、混合检索、多 agent 阅读室、借阅记录、开局注书单、以及一个能切默认召回路由的模型开关。

我们**不**声称：

- 跨机同步已完成——目前是设计审计 / 部分远端源；
- Hermes 会自动把经验采纳进生产，或无人值守后台 tick 已被观察到点完整条链——受控 run-once 已证、受限调度器已实现，但生产采纳仍是另一道默认关闭的硬门；
- 某个向量模型普遍更好——开关能改变默认召回路由；当前 Granite 只有本机影子评测，不是公开 benchmark；
- 全自动自我训练——经验进化是可审计的采编，有评审有回执。

每次改动都分层签署——source/test、本地预览、installed runtime、跨机、release 分开签，不把“能点”当“已生效”。

## 更新

打开 `http://127.0.0.1:9850`，进入“设置与更新”，点击“检查更新”和“一键更新”。如果本地页面打不开，可以重新运行安装命令做修复安装。

## 卸载

macOS / Linux：

```bash
~/Library/Application Support/time-library/uninstall.sh
```

Windows：

```powershell
.\uninstall.ps1
```

卸载只移除软件本体，`memory/`、`raw/`、`config/`、`logs/` 等本地数据会保留。
