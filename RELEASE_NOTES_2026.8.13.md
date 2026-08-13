# Time Library 2026.8.13

2026.8.13 strengthens source-preserving record reliability, bounded
recoverability diagnostics, and unattended Guardian task handling while
retaining the fail-closed, relay-preserving Codex MCP guard and watcher from
2026.7.25.

Raw archive and canonical record paths keep source regression, missing source,
recoverability, and not-measured states distinct. Guardian status exposes
bounded, public-safe recoverability evidence without exposing raw content,
payloads, paths, secrets, or credentials. Local connectors and Windows Guardian
task roles use explicit runtime checks for unattended operation.

Codex Guardian now excludes canonical and forensic sidecars from raw-session
selection and reuses verified archive metadata across a bounded population
scan. A stat-bound witness prevents a retained raw record from being reported
as missing when a shorter Codex source differs only in `model_provider`;
ordinary appends and equal or larger rewrites continue through the existing
monotonic archive and divergence-generation paths.

## 中文

2026.8.13 强化源记录保全、有限可恢复性诊断和无人值守 Guardian 任务编排，
同时保留 2026.7.25 的 fail-closed、保留 relay/provider 的 Codex MCP 配置
守护器与 watcher。

raw 归档和 canonical 记录路径会区分源回退、源缺失、可恢复性和未测状态；
Guardian 状态只提供有界且对外安全的可恢复性证据，不暴露正文、payload、路径、
secret 或凭据。本机连接器与 Windows Guardian 任务角色使用明确的运行态检查，
支持无人值守路径的诊断。

Codex Guardian 现会把 canonical/forensic 派生侧车排除在 raw 会话候选之外，并在
有界总体扫描中复用已验证的归档元数据。若 Codex 源文件变短且仅
`model_provider` 元数据不同，绑定文件 stat 身份的 witness 会避免把已保留的 raw
误报为缺失；普通追加以及等长或更长的改写仍走原有单调归档与分歧 generation
路径。
