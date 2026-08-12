# Changelog

## [Unreleased]

- Added a Local Runtime Preview documentation lane for maintainer-machine
  evidence that is useful for review but is not yet a published release claim.
- Documented the local Reading Area project view, five-shelf startup catalog,
  Whiteboard handoff records, Project History records, automatic distillation,
  connection previews, and the explicit FTS5 recall leg with clear remaining
  boundaries for cross-machine proof, real platform apply, natural full-chain
  freshness, and the posthoc naked-window audit.
- Added working-tree release-package preview checks that verify current local
  preview files, FTS5 helpers, relay voiceprint tools, project-history tools,
  and the MCP runtime extraction are included while local runtime data, output,
  raw archives, private rules, and repository metadata stay out of the zip.
- Split MCP startup/runtime orchestration into `src/raw_gateway_mcp_runtime.py`
  so the main raw consumption gateway stays below the release-gate structure
  guard while preserving startup initialize, direct `library_id` borrowing, and
  reading-area tool dispatch behavior.
- Added explicit MCP consumer parameters for the FTS5 substring leg while
  preserving default recall behavior and keeping default vector freshness and
  natural full-chain freshness unsigned.
- Prepared 2026.6.20.2 as a safety-followup patch over the 2026.6.20 passive-first release line.
- Added `src/memcore_version.py` so runtime version reporting reads the root `VERSION` file instead of scattered hard-coded strings.
- Updated raw gateway health, MCP/server metadata, preflight surfaces, console APIs, and the local console UI to report the real package version after patch installs.
- Fixed Windows guardian and uninstall scripts so they avoid assigning to PowerShell's read-only `$PID` automatic variable.
- Added release-gate checks that reject runtime version literals in reporting/UI surfaces and reject future PowerShell `$PID` assignment regressions.
- Expanded the first-line local AI tool catalog to recognize OpenCode, Goose, Aider, and OpenHands from local app/config/workspace/package traces.
- Added storage-pattern and regression coverage for those fast-moving open-source agents while keeping discovery metadata-only: no chat bodies are read and no tool is promoted to complete conversation memory until a verified collector proves the native format.
- Added a model-source chain for unfamiliar tool recognition: user-filled or env model settings first, Memcore's own optional recognition model next, shared model identity if present, OpenClaw/Hermes inherited routes after that, and local rules when no model is available.

## [2026.8.7] - 2026-08-07

- Strengthened source-preserving raw archive and canonical record checks so
  source regression, missing source, recoverability, and not-measured states
  remain distinct instead of being collapsed into a green aggregate.
- Added bounded, public-safe Guardian recoverability diagnostics that keep raw
  content, payloads, paths, secrets, and credentials out of the status surface.
- Improved platform-neutral local connector and Windows Guardian task
  orchestration with explicit, fail-closed runtime checks for unattended paths.

## [2026.7.25] - 2026-07-25

- Added a platform-neutral Codex MCP configuration guard for hosts whose local
  configuration manager periodically replaces `config.toml`. Installers now
  reconcile only the Time Library MCP and approval tables, preserve provider/
  relay and unrelated MCP settings, fail closed on malformed or conflicting
  configuration, and keep a user-level watcher for later replacements. Failed
  or skipped registration preserves an existing owned guard. This is a host
  configuration lifecycle fix; it does not change raw, recall, event ordering,
  delivery, or authentication semantics.
- Hardened the guard's TOML section boundaries for array tables and multiline
  strings, preventing unrelated relay configuration from being swallowed during
  recovery.

## [2026.7.18] - 2026-07-18

- Unified the local console, API, MCP, and raw entry routes behind one discoverable front door that can move when the preferred port is occupied.
- Made AI-tool onboarding capability-driven so an unknown compatible client can self-report and connect without a product-name branch.
- Added append-only Delivery and adoption evidence while keeping `used`, `helped`, and production activation as separate claims.
- Added encrypted local model credentials and a local distillation transparency ledger that shows the exact request payload sent to a configured model.
- Hardened raw archive preservation across source truncation, deletion, rotation, and divergent rewrites.
- Fixed Windows repair installs so the declared mirror-copy argument array is actually passed to `robocopy`.
- Added native Windows locking for the distillation ledger and removed the PowerShell subprocess from front-door process fingerprinting.
- Replaced the POSIX-only `os.kill(pid, 0)` lock check on Windows with `OpenProcess` and `GetProcessTimes`.
- Made Windows upgrades prepare dependency wheels before service cutover, create the replacement venv at its final path, and restore program/config/state/venv/runtime after a failed upgrade transaction.
- Made `-NoStart` reject a running Windows install root instead of hot-mirroring new files under old processes.
- Preserved successful model-call results when transparency-ledger locking fails while surfacing an explicit local ledger warning.
- Made the Windows installer decode packaged JSON as UTF-8 explicitly under Windows PowerShell 5.1.

## [2026.7.11] - 2026-07-11

- Optimized several issues and improved stability.

## [2026.7.10] - 2026-07-10

- Updated the Reading Room to use the local source-backed catalog projection for project pages, Whiteboard records, Project History, and five-shelf counts while keeping local drafts separate.
- Corrected preference totals and per-service health display in the local console.
- Improved Windows watcher status reporting by accepting a recent successful guardian check when direct process inspection is unavailable.

## [2026.6.12] - 2026-06-12

- Released Memcore Cloud 2026.6.12 as a public-wording and release-gate patch over the 2026.6.11 reliability base.
- Removed the specific local relay tool from the public catalog, verified storage patterns, and watchlist so the open-source project does not present it as a public dependency or supported platform.
- Kept legacy local relay compatibility through neutral `local_relay` handling and dynamically constructed legacy strings, preserving existing personal setups without exposing those names in repository wording.
- Renamed record diagnostics toward lost reference / 遗失 semantics and away from legacy stray-record wording.
- Extended the release gate with repository-wide wording scans for removed relay names and legacy stray-record diagnostics.
- Bumped runtime-visible versions across installers, gateway health, active routing, preflight metadata, the local console, platform storage patterns, and the packaged Time Library skill.
- Hardened Windows native smoke and installer validation after real-host testing on real Windows hosts: watcher process detection now tolerates path normalization differences, Codex status JSON parsing tolerates prefixed output while preserving `raw_sync` checks, and the OpenClaw config helper handles an empty dialog-entry token without traceback noise.

## [2026.6.11] - 2026-06-11

- Released Memcore Cloud 2026.6.11 as a reliability update for checkpoint recovery, canonical session identity, active preflight recall, and runtime guards.
- Hardened P0 and P2 checkpoint handling so corrupt checkpoints are backed up and future writes use atomic replacement.
- Normalized Codex and Claude Code canonical index identity around native session ids while keeping older workspace/window hints as source refs and project clues.
- Added read-only memory preflight with explicit enter, retreat, bind-required, and skip decisions for source-backed context surfacing.
- Added a raw gateway fast path for current-window preflight from the canonical record index, including compact bridge payloads that omit raw excerpts and large fields.
- Added a Claude Code `UserPromptSubmit` preflight hook installer and three-platform installer integration.
- Tightened raw gateway health identity checks, Windows port-owner diagnostics, and dialog-entry token scoping across service commands.

## [2026.6.9] - 2026-06-09

- Released Memcore Cloud 2026.6.9 as a record-first pre-release candidate after the larger June 8-9 reliability pass.
- Promoted the Record Origin Guard, all-session canonical index, lost source / lost raw diagnostics, and raw rebuild path as the core release axis.
- Split Claude Desktop source modeling into Chat, Cowork, and Code/agent surfaces: Chat remains a `claude.ai` web-chat/cache evidence surface, while Cowork and Code/agent use verified local JSONL body candidates.
- Added bounded contracts for Time River sediment, Second Brain, material processing, external docs evidence, and context delivery compaction so they strengthen source-backed recall without replacing raw.
- Hardened release gates around installer syntax, public wording, internal direction audits, core record reliability contracts, and full pytest execution.
- Bumped runtime-visible versions, installers, raw gateway, active routing, platform storage pattern contracts, local console defaults, and the packaged Time Library skill to `2026.6.9`.

## [2026.6.6] - 2026-06-06

- Released Memcore Cloud 2026.6.6 with background desktop entry points for Windows tray and macOS menu bar use.
- Bumped runtime-visible versions, installers, raw gateway, active routing, platform storage pattern contracts, and the packaged Time Library skill to `2026.6.6`.
- Kept the public product surface focused on practical use: install once, keep local sync running, open the local console from the desktop, and let supported local AI tools connect safely.
- Unified the visible model setting around `偏好层模型`, with optional AI-assisted local-tool recognition reusing the same model route while default scans remain metadata-only.
- Verified the current direction with three-end AI-recognition smoke across local macOS, Windows relay-route testing, and clean Windows Codex testing.
- Preserved active recall routing as window-first with explicit widening for raw-pool/global use.

## [2026.6.4] - 2026-06-04

- Released Memcore Cloud 2026.6.4 with native Windows as the default Windows install path and WSL documented as development / advanced testing only.
- Verified a clean official Windows Codex install where `codex.exe` is not on `PATH`: Memcore Cloud locates the bundled official CLI through Codex native-host metadata and registers `time-library-memory` with official `codex mcp add`.
- Added and validated the Codex stdio MCP bridge for current-window recall, including `MEMCORE_WINDOW_BINDING_REGISTRY`, `MEMCORE_ROOT`, UTF-8 env setup, and standard JSON-RPC capability-check responses.
- Hardened Windows Python discovery so Microsoft Store `python` / `python3` aliases are not treated as usable runtimes unless they can execute `import sys`.
- Added a repeatable native Windows smoke script for local service health, official Codex MCP registration, and no-recall `time_library_recall` capability checks.
- Added no-recall `time_library_recall` capability checks to macOS and Linux post-install smoke so all three installers verify the local MCP read path, not only service health.
- Exposed continuous-sync status so the local service can report whether watchers are running as a continuous loop and which collectors are ready or pending.
- Added verified local assistant session collection with assistant-reply persistence checks; user-only local records stay evidence and do not count as complete conversation memory.
- Added model-assisted local tool identification as a second recognition layer: deterministic metadata and known storage patterns remain the fallback when no model provider is configured.
- Added `docs/wiki/Native-Windows-Codex.md` to preserve the Windows official Codex validation and troubleshooting path.

## [2026.6.3] - 2026-06-03

- Prepared the Time Library prompt as a standing memory rule instead of a one-time setup note, so agents are explicitly told to call `time_library_recall` before answering memory-dependent questions such as prior decisions, corrections, install/test/release status, and short "next step / what else / then what" follow-ups.
- Updated the public install prompts, local console copy prompt, Codex skill metadata, and Claude Desktop skill manifest wording to teach the same standing rule while keeping capability check read-only and no-recall.
- Verified the macOS and native Windows install roots can be upgraded in place with user data preserved, bringing both local runtimes back in line with `2026.6.3` while installing prompt v4 into Codex and Claude Desktop skill locations.
- Moved older release details into `UPDATE_HISTORY.md` so the README and release pages stay focused on public product use.
- Connected local AI tool adapter drafts into authorized auto-connect dry-run, apply-gate previews, and apply receipts, including MCP, collector, and raw-archive plan fields.
- Added regression checks that adapter-draft-driven plans keep discovery/dry-run chat-body reads disabled and preserve the 2026.6.1 computer-first raw archive layout.
- Documented and enforced the current memory-scope correction: default recall is current-window first, ordinary Hermes recall is window-scoped too, and broader project/global or Hermes skill-generation/self-review scopes must be routed explicitly.
- Documented native Windows install as the normal Windows path and WSL as development / advanced testing only.
- Added assistant-reply persistence as a verification item before claiming complete conversation memory.

## [2026.6.2] - 2026-06-02

- Released Memcore Cloud 2026.6.2 as today's published version.
- Fixed Claude Desktop recall over the local `time-library-memory` MCP bridge so capability checks and real recall can both complete cleanly.
- Added tolerant raw-text decoding for recalled excerpts and direct raw lookup, including BOM-aware UTF-8 plus Windows Chinese encodings, so Chinese `raw_excerpt` text stays readable.
- Changed the Claude Desktop stdio bridge to emit UTF-8 JSON lines and updated Claude installers to read existing config with BOM tolerance while writing config without BOM trouble.
- Covered both regular Claude Desktop config paths and Microsoft Store Claude config paths on Windows.
- Bumped the raw consumption gateway, skill metadata, installers, local console version markers, and public docs to `2026.6.2`.
- Strengthened the `time-library-memory` skill prompt so agents are told to call memory first for previous decisions, corrections, project boundaries, install/test/release status, and next-step questions.
- Improved recall ranking for decision-focused queries so project decisions and release/status notes are easier to surface.
- Added product-facing Wiki source pages for getting started, safe capability checks, AI tool boundaries, memory layout, and release-history routing.

## [2026.6.1] - 2026-06-01

- Released Memcore Cloud as the English-first product name while keeping Time Library as the Chinese name and product name.
- Added a read-only local AI tool discovery view so Memcore Cloud can show present tools, safe-check readiness, and access boundaries without silently parsing chat bodies.
- Added connection previews for local AI tools, including would-change paths, backup and rollback notes, restart needs, receipts, and capability-check payloads.
- Added bounded local settings discovery so newer AI tools can be noticed through common MCP/config patterns before deeper access is granted.
- Updated the local Platforms page to show tool presence, safe next steps, usage freshness, and whether new records are following the computer-first layout.
- Implemented the 2026.6.1 raw archive layout contract for all new installs and new raw writes: new records are grouped by computer first, then by source tool and app format. Older layouts remain readable for compatibility.
- Promoted Claude Code CLI from a boundary-only object to a connectable candidate while keeping it separate from Claude Desktop and still requiring a parser gate before reading conversation bodies.
- Added a read-only authorization gate for future platform-config changes, with required confirmations, backup and rollback readiness, receipt preview, and capability-check follow-up.

## [2026.5.31] - 2026-05-31

- Added natural-language correction routing so "this memory is wrong", "you misunderstood", and similar user feedback can become review-only errata candidates.
- Added external method-signal candidate dry-runs for turning news, repositories, audits, and practice feedback into review-only method candidates without installing or activating anything.
- Added public README prompts that users can send directly to an AI agent to install Time Library and finish with capability check mode.
- Updated the Time Library skill with a clear "local memory library" identity signal and ambient recall-before-judgment triggers for forgotten/corrected/ongoing project context.
- Clarified the Hermes raw-pointer-to-native-skill-learning chain: Time Library emits a self-review signal, provides raw/source-ref pointers, and observes Hermes native feedback, but does not directly write Hermes skills.
- Added a read-only Hermes native learning liveness check for recent `background_review`, `skill_manage`, and skill-file changes so cold learning chains are visible.
- Added Hermes self-review wake dry-run and signal receipt gating so Time Library can record that a wake signal was produced without triggering Hermes or writing Hermes skills.
- Added Hermes MemoryProvider consumption parity: `sync_turn` posts Time Library-side consumption receipts on a background thread and `queue_prefetch` warms recall without copying OpenClaw's before-dispatch interception model.
- Added a read-only Hermes skill vs experience diff dry-run that compares Hermes skill files with Time Library experience records and produces review-only adoption / upgrade candidates.
- Added Claude Desktop as a first-class source system distinct from Claude Code CLI, with local app-data sync manifest and sync-state receipt endpoints for config, IndexedDB, Local Storage, Session Storage, skill manifests, and logs. Consumer diagnostics distinguish a generic skill signal from a working Time Library MCP/Desktop Extension recall connection. Readers can aggregate all Claude surfaces under `claude_all`, while Windows relay / Claude Code related records keep dual attribution fields (`storage_owner`, `conversation_origin`, `runtime_consumer`) and isolation boundaries in manifest, sync-state, and source refs instead of being flattened into one source. Official Claude exports are treated as cold-start/backfill fallback only.
- Added read-only State Ledger / Temporal Index dry-runs for latest trusted judgment review while preserving superseded, deprecated, conflicting, and needs-review records.
- Added `context_budget_unit_candidate` dry-runs for source-backed, composable context units with explicit budget, trigger, verification, expiry/review, and no-write flags.
- Updated macOS, Linux, and Windows full installers to automatically install the Codex skill and register the `time-library-memory` Codex MCP server at `http://127.0.0.1:9851/mcp` when Codex CLI is available.
- Added a Claude Desktop stdio MCP bridge and installer registration so Claude Desktop can call the existing read-only `time_library_recall` MCP instead of only seeing generic skill instructions.
- Bumped public README version markers, installers, raw MCP server info, and skill metadata to 2026.5.31.

## [2026.5.30] - 2026-05-30

- Added a multi-case experience benchmark dry-run so real task sets can compare no memory, preference-only memory, and preference plus work-experience memory before any Replay feedback queue or adoption flow is built.
- Added a precision-first P2 preference intent gate so repairs, deictic disambiguation, creative prompts, and long relayed audit text do not become durable preferences.
- Added public-safe benchmark fixture cases for checking source-backed behavior, proactive resurfacing, toolbook facts, connector boundaries, and public-documentation boundaries.
- Bumped runtime-visible versions for the Web console, Time Library knowledge shelves, raw MCP gateway, installers, and skill metadata to 2026.5.30.
- Verified the Windows local service with health, Replay/benchmark plans, MCP initialize, OpenClaw raw query, source-ref sampling, and error-log checks.

## [2026.5.29] - 2026-05-29

- Added the Time Library knowledge shelves evidence loop: raw records remain source texts, The preference shelf keeps preference and intent experience, and The work-experience shelf keeps work experience and toolbooks.
- Added `library_id`, `library_shelf`, `library_card`, `matched_by`, `rank_reason`, and typed-graph metadata to recall and MCP gateway results.
- Expanded work-experience candidates with lifecycle status, work scenario, action strategy, avoid conditions, acceptance checks, and applicable scope.
- Added read-only Time Library knowledge shelves and replay-plan endpoints for library inspection and future no-memory / preference-only / preference-plus-work-experience evaluation.
- Extended usage receipts and Hermes context formatting so clients can explain what was recalled, why it matched, and which source refs were used.
- Added `mode=capability_check` for Skill/MCP install smoke tests, verifying availability without recall or raw excerpts.

## [2026.5.28] - 2026-05-28

- Added the first preference archive-catalog layer: stable catalog ids, archive cards, source-aware evidence output, and an archivist-style injection prompt.
- Added language-neutral memory entry aliases: `/memory` as the main command, with `/memory`, `/recall`, `/continue`, and natural English recall phrases as aliases.
- Added a platform-neutral `time-library-memory` skill package and a read-only MCP-compatible `time_library_recall` tool endpoint for AI clients that support skills, MCP, plugins, or custom system instructions.
- Expanded the public preference/work-experience wording in Chinese and English: The preference shelf keeps preference and intent experience, The work-experience shelf keeps work experience, and both stay source-backed.
- Clarified that experience is not a callable skill: The preference shelf keeps preference and intent experience, while the work-experience shelf keeps source-backed work experience.
- Hardened the local raw gateway with an explicit loopback-only request guard and safer cursor-state directory checks.

## [2026.5.27] - 2026-05-27

- Added Codex local record support. Time Library can discover local Codex sessions, preserve them as raw memory, and organize useful experience from them.
- Clarified and tested the saved-content rule: platform records, preference experience, recalled context, and usage records keep saved content without redaction, rewriting, or hash-only replacement.
- Extended the shared local memory base for OpenClaw, Hermes, and Codex while keeping each platform and conversation window separate.
- Added incremental capture for growing session files, so new conversation records are processed from saved offsets instead of rereading from the beginning.
- Added direct raw evidence lookup by byte offset, with a resumable segmented fallback for older records.
- Updated Hermes memory provider defaults to read the shared local memory base in read-only mode.
- Added tests for Codex capture, preference extraction, shared raw access, segmented resume, and offset lookup.

## [2026.5.26] - 2026-05-26

- Enabled the local one-click update flow: check, download, validate, back up app files, apply the new version, and restart local services.
- Preserved local memory, raw records, preference experience, configuration, logs, backups, and virtualenv state during update.
- Fixed the update history API so the local page can read past update records.
- Updated README and wiki guidance for install, repair install, and one-click update.

## [2026.5.25] - 2026-05-25

- First public release of Time Library.
- Added one-command installers for macOS, Linux, and Windows; WSL remains an advanced development/testing path.
- Added the local memory center page for platform status, model settings, and generated experience.
- Kept the public repository focused on the installable product.
