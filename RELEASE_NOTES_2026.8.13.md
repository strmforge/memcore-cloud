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

## 中文

2026.8.13 强化源记录保全、有限可恢复性诊断和无人值守 Guardian 任务编排，
同时保留 2026.7.25 的 fail-closed、保留 relay/provider 的 Codex MCP 配置
守护器与 watcher。

raw 归档和 canonical 记录路径会区分源回退、源缺失、可恢复性和未测状态；
Guardian 状态只提供有界且对外安全的可恢复性证据，不暴露正文、payload、路径、
secret 或凭据。本机连接器与 Windows Guardian 任务角色使用明确的运行态检查，
支持无人值守路径的诊断。
