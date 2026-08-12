# Native Windows And Official Codex

Time Library treats native Windows as the normal Windows install path. WSL is
for development, advanced testing, or special debugging.

## What Was Verified

Time Library 2026.6.4 was verified on a clean native Windows machine with an
official Codex install.

The important detail: official Codex may not expose `codex.exe` on `PATH`.
Time Library can still find the bundled official CLI from Codex native-host
metadata. Older installers used the official `codex mcp add` command; current
installers use a narrow, guarded merge so a local relay cannot erase the entry
with a later whole-file rewrite.

Verified result:

- Time Library installed natively under `%LOCALAPPDATA%\time-library`;
- native Python 3.12 created the local venv;
- the Codex skill was installed under `%USERPROFILE%\.codex\skills`;
- `time-library` appeared in official `codex mcp list`;
- `zhiyi_recall` capability check returned the installed Time Library version;
- the MCP response was standard JSON-RPC;
- capability check stayed read-only and did not run real recall.

## Why This Matters

Many Windows users will install desktop apps but will not configure shells,
PATH, WSL, or developer runtimes by hand.

For Codex, the reliable path is:

1. Install Time Library natively.
2. Let Time Library discover the official bundled Codex CLI.
3. Let Time Library install the Time Library skill.
4. Let Time Library register `time-library` through a narrow, guarded merge.
5. Run capability check before real recall.

The installer does not repeatedly call `codex mcp add` or `codex mcp remove`.
It owns only the Time Library MCP table and its two approval tables, then runs a
user-level guard that restores those tables if another local configuration tool
replaces the whole Codex TOML file. Provider/relay settings, credentials, and
other MCP tables remain outside the guard's ownership and are copied forward
as-is. A malformed file, duplicate Time Library table, or same-name foreign
MCP is rejected without a write.

This is a local final-consistency mechanism, not authentication or tamper
protection: another process running as the same OS user can still edit or stop
the guard. Existing Codex sessions may need a new window or host reload after
the configuration is restored; the guard cannot hot-reload a running host.

On native Windows the long-lived guard is the
`MemcoreCloudCodexMcpGuard` scheduled task. The macOS and Linux installers use
the equivalent user LaunchAgent or systemd user service. The bridge continues
to use the installed front-door discovery file rather than a fixed port.

Windows keeps desktop roles and background recovery roles separate. The tray
and logon launcher use an interactive user token because they belong to the
signed-in desktop. `MemcoreCloudGuardianHealth` and
`MemcoreCloudCodexMcpGuard` use an S4U principal for the same OS user so they
can run while that user is signed out; no account password is stored. S4U does
not provide network credentials or access to encrypted files, so these tasks
are limited to the local installed root, the user's local Codex configuration,
and loopback services. Native smoke fails closed if a background task drifts
back to an interactive-only principal. An installer run that explicitly keeps
autostart unchanged, or preserves a legacy Codex guard after Codex registration
fails, reports that task layer as not measured; normal Guardian runs and
standalone native smoke do not inherit that exception. JSON results preserve
this distinction with `measurement_status=partial`, `full_smoke=false` for
native smoke, or `full_health_check=false` for Guardian status, plus the named
`not_measured_layers`. The installer prints a partial result rather than an
unqualified smoke pass. These switches are explicit diagnostic overrides; the
repository's normal Guardian and standalone smoke entrypoints do not pass them.
When an installer explicitly preserves a legacy guard, the registered Guardian
launcher also carries the same narrow skip flag. Every later health run remains
machine-readable `partial` until a successful reinstall replaces that preserved
task; the initial S4U demand run cannot silently reinterpret the legacy
Interactive guard as healthy or fail before the installer reaches its explicit
preservation verdict.

Registration alone is not background-recovery proof. During a normal install,
the installer demand-starts `MemcoreCloudGuardianHealth` through its registered
S4U principal and waits for a completed result of zero. Guardian and native
smoke also require a recent successful health-task run (or a currently running
instance). A missing or nonzero run fails closed and points to
`SeBatchLogonRight`, `SeDenyBatchLogonRight`, and the Task Scheduler Operational
log. In particular, `0x0004131C` means the task was registered with a batch-logon
privilege problem, while `0x80070569` means the requested logon type was not
granted. Task state `Ready` by itself is never treated as execution proof.
The 20-minute check is a routine freshness signal, not proof that recovery ran
after a particular reboot. A controlled reboot acceptance run must add
`-RequireBackgroundRecoveryAfterBoot`; that mode requires each measured
background task's `LastRunTime` to be later than the operating system's
`LastBootUpTime`. A disabled Guardian health task fails both Guardian and native
smoke even if it retains an older successful result.
Both `State` and `Settings.Enabled` are required. A still-running process does
not make a disabled scheduled task healthy because it cannot be relaunched after
that process exits.
Likewise, a successful one-shot Codex configuration reconcile does not make a
failed `MemcoreCloudCodexMcpGuard` watcher healthy; the scheduled task must be
`Running` with its exact owned `--watch` process. The Operational event log is
supplemental evidence and is never enabled automatically; if it is disabled,
that event layer remains `not_measured` rather than being inferred from `Ready`.
If another Guardian already owns the single-run lock, its short JSON response is
also explicitly `partial`; native smoke propagates that nested coverage instead
of consulting an older green status file. For a completed non-concurrent run,
native smoke requires the status file's coverage fields plus a generation time
and file write time from the current invocation before using it as evidence.

## Troubleshooting

If `python`, `python3`, or `py` exists but the installer still says Python is not
usable, check whether Windows is returning a Microsoft Store alias instead of a
real Python runtime.

A real Python candidate must be able to run:

```powershell
python -c "import sys; print(sys.executable); print(sys.version)"
```

If `codex` is not found on `PATH`, that is not automatically a failure. Time Library also checks Codex native-host files such as:

```text
%USERPROFILE%\.codex\chrome-native-hosts-v2.json
%USERPROFILE%\.codex\chrome-native-hosts.json
%LOCALAPPDATA%\OpenAI\Codex\chrome-native-hosts-v2.json
%LOCALAPPDATA%\OpenAI\Codex\chrome-native-hosts.json
```

After install, the simplest verification is:

```powershell
codex mcp list
```

or, when Codex is not on PATH, use the bundled `codex.exe` found from the
native-host metadata.

The repeatable native Windows smoke check is:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\time-library\tools\windows_native_smoke.ps1"
```

For a separately authorized reboot or signed-out recovery acceptance run, use:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\time-library\tools\windows_native_smoke.ps1" -RequireBackgroundRecoveryAfterBoot
```

That switch validates post-boot task execution; it does not reboot or sign out
the machine itself.

It checks local service health, official Codex MCP registration, and a safe
`time_library_recall` capability check. It also checks that the main model setting is
present in the local console and that a model-setting dry run stores no secret
and calls no model. It also checks Agent Work Preflight so a connected agent can
ask "what do we already have?" before coding or operational work. It does not run real recall.

Expected MCP entry:

```text
time-library
```

For a configuration-only check, use the host's normal read-only inspection
surface (`codex mcp get time-library` where available) and inspect the guard
task/service. Do not repair the file with a hand-written `codex mcp add` command:
that can reintroduce the same whole-file rewrite race. If the guard reports a
malformed or conflicting configuration, preserve the file for diagnosis and
resolve the conflict explicitly.

Expected safe capability check facts:

```text
service: raw_consumption_gateway
server: time-library
version: <installed Time Library version>
read_only: true
recall_performed: false
raw_excerpt_returned: false
mcp_tools: ["zhiyi_recall"]
```

Expected Agent Work Preflight facts:

```text
mode: work_preflight
contract: agent_work_preflight.v2026.6.20
source_preflight_contract: zhixing_preflight.v2026.6.20
read_only: true
write_performed: false
model_called: false
raw_excerpt_returned: false
receipt_scope: agent_work_preflight_read_only
```

## Boundary

Installing the Skill and MCP entry proves Codex can call Time Library. It does
not mean real memory was recalled.

Real recall should still follow the active memory routing rule: a normal Codex
window should read its own bound window/session first, and broader project or
cross-window memory should be explicit.

Agent Work Preflight is a different safe path from real recall. It is meant for
the beginning of work: classify whether the request looks like an existing
feature that was forgotten, an existing feature that is miswired, a diagnostic
gap, or something actually missing. It should guide the agent into the right
repo inspection and diagnostics, not replace source-backed recall or user
approval.

## 中文

Windows 用户默认应该走原生安装，不是 WSL。WSL 只适合开发、高级测试或特殊排障。

这次已经验证：一台原生 Windows 机器上的官方 Codex，即使 `codex.exe` 不在 PATH，
Time Library也能从 Codex 的 native-host JSON 找到官方 bundled CLI。旧版曾用
官方 `codex mcp add` 注册；当前安装器改用窄合并和用户级 guard，避免中转工具
整文件重写时把 `time-library` 表抹掉。

验证结果：

- Time Library安装到 `%LOCALAPPDATA%\time-library`；
- 使用 Windows 原生 Python 3.12 创建 venv；
- Codex skill 安装到 `%USERPROFILE%\.codex\skills`；
- 官方 `codex mcp list` 能看到 `time-library`；
- capability check 返回当前安装的Time Library版本；
- MCP 返回标准 JSON-RPC；
- capability check 只读、不召回真实记忆、不返回 raw excerpt。

排障重点：

- WindowsApps 里的 `python.exe` / `python3.exe` 可能只是 Microsoft Store
  占位符，不是真 Python；
- 官方 Codex 不在 PATH 不代表没安装，要查 native-host JSON；
- 可重复的原生 Windows 验收命令是：
  `powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\time-library\tools\windows_native_smoke.ps1"`；
- 这条验收还会检查“主模型”入口是否在控制台里、模型设置 dry-run
  是否不保存密钥、不调用模型；
- 这条验收也会检查 Agent Work Preflight：agent 动手前可以先问“我们是不是已经做过了”，
  并确认该路径只读、不写入、不调用模型、不返回 raw excerpt；
- 安装后先做 capability check，再做真实 recall；
- 某些本地中转或配置管理工具会整文件重写 `~/.codex/config.toml`，把未知的
  MCP 表删掉。新版安装器用窄合并加用户级 guard 处理这个共因：只恢复
  `mcp_servers.time-library` 和两个 approval 表，保留 provider/base_url、密钥
  和其他 MCP；不再循环调用 `codex mcp add/remove`。坏 TOML、重复表、同名外部
  MCP 会拒写并保留原文件；这是最终一致性保护，不是认证，同一 OS 用户仍能停掉它；
- Windows 上检查 `MemcoreCloudCodexMcpGuard` 任务；macOS/Linux 分别检查
  `com.memcorecloud.codex-mcp-guard` LaunchAgent 或
  `time-library-codex-mcp-guard.service`。已有 Codex 窗口不会热加载，恢复后需新开
  窗口或按宿主规则重载；
- 当前窗口召回仍要遵守窗口优先的防污染规则；
- Work Preflight 不是第六层知识库，也不是替代召回；它只是开工前把“已做但忘了 / 已做但接错 /
  诊断缺口 / 真缺失”先分清楚。
