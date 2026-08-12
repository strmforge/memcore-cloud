---
name: time-library
version: 2026.8.7
prompt_version: 6
description: >-
  Use when the user refers to previous decisions, corrections, forgotten
  context, already-built work, install/test/release status, source-backed
  evidence, or next steps in ongoing work. Treat Time Library as a
  standing active memory routing rule: call time_library_recall before answering
  memory-dependent prompts. Also trigger on /time-library, /memory, /recall,
  /continue, "you forgot", "not the first time", "previous decision", "we
  already corrected this", "already built", "forgotten", "next step", "what
  else", "then what", "之前", "定论", "纠错", "边界", "忘了", "还有吗", "然后呢",
  "接下来呢", or "下一步".
argument-hint: "time library recall previous decision | time library check what was already built | time library next step in this project"
---

# Time Library

## Role

Use Time Library as a local archivist, not as an imagination layer.
It helps an AI client continue from local, source-backed memory: raw records,
preferences, work experience, toolbooks, and errata. It is not a chatbot
persona, not a generic search box, and not a cloud summary.
The same rule can be used by Claude, Codex, OpenClaw, Hermes, or another local
agent that can call the Time Library MCP/tool connection.

## When To Use

Call `time_library_recall` before answering when the user asks about:

- continuing an ongoing project, deciding the next step, or checking what was
  already done;
- previous decisions, corrections, rejected approaches, or boundaries;
- installed, tested, released, synchronized, or written status;
- source/evidence questions, especially when the user asks what was said before;
- short ongoing-work prompts such as "next", "what else", "then what",
  "下一步", "接下来呢", "还有吗", or "然后呢".

Use a narrow query built from the user's words. Prefer `limit=3` and compact
source-backed excerpts. If the current window/session is available, pass it.
Default active recall reads current window/session first, then same
project/workspace, same workstream/task, then stable preferences/tool facts.
Treat raw-pool/global as explicit only.

## Default Contract

For task-like continuation, correction, status, or "what next" prompts, prefer:

```json
{"query":"...","mode":"preflight","memory_scope":"active","limit":3}
```

For install checks, smoke tests, or "can this client see Time Library?", do not
run normal recall. Use capability check:

```json
{"query":"capability check","mode":"capability_check"}
```

Capability check must report only service/tool/read-only availability. It must
not query real memory or return raw excerpts.

## Platform-Neutral Connection

Installation and connection are capability-driven. The host agent must inspect
and report its own MCP, skill/custom-instruction, configuration, and optional
prompt/preflight-hook surfaces. The host report is authoritative; a product
name inferred from metadata is only a hint. Use only configuration paths owned
and documented by the host. Do not request or create a product-name adapter.

During installation, stop after the safe capability check. A capability check
is not connection proof and must not trigger real recall. Complete the generic
connection handshake only when a later user request genuinely needs prior
context and therefore authorizes a real recall:

1. Call `time_library_recall` for that user request and retain a returned
   `ZX-*` `library_id`.
2. In the same initialized MCP session, call `time_library_reading_area` with
   `action=self_report_connect`. Self-report the stable `source_system`, current
   `canonical_window_id` or `session_id`, truthful `skill_surface_status` and
   `config_write_authority`, one truthful reading-area/project/series scope, and
   set `proof_library_id` to the returned `library_id`.
3. If any required fact or proof is missing, leave connection verification
   pending. Never invent host capabilities, scope, identity, or proof.
4. Repeat the authorized recall through the verified connection. Acknowledge a
   delivery challenge only after the host model actually received and used the
   cited refs.

This delayed handshake is the same for every capable host. Never recall private
memory merely to prove installation, and never require a native history parser
before the host can connect as a memory consumer.

Normal recall never changes raw records or any memory shelf. For a recognized
host, the MCP may append derived Delivery Spine audit metadata under local
runtime state so `selected`, `delivered`, `used`, and `unknown` remain separate.
Set `delivery_tracking=false` when a strictly zero-write recall is required.
If a recall returns a one-time `delivery_runtime.challenge`, call
`time_library_delivery_ack` only after the host model has actually received the
selected refs and composed a response that uses the echoed refs. Never claim
`helped` without user feedback, task outcome evidence, or controlled A/B proof.

If explicit `memory_scope=window` returns `scope_missing=true` or
`recall_status=window_identity_required`, say the current window/session is not
bound yet. Do not say there is no memory. With default active recall, a missing
window/session is not the same as no memory.

If `time_library_recall` is not available, try the legacy alias `zhiyi_recall`
during the migration cycle. If neither tool is available, say plainly:
"MCP/tool connection is missing." Do not pretend the skill alone can read
memory.

## Authority Boundary

Time Library steadies the host agent; it does not take over the host agent by
default.

- `passive`: record or observe only.
- `recall_only`: return source-backed evidence and context to the caller.
- `context_inject`: inject compact context, but do not produce the final answer.
- `direct_answer`: answer as Time Library only through an explicit
  `/time-library`-style entry.
- `platform_act`: click, send, abort, write, or mutate a host platform only
  after separate explicit platform-action authorization.

Do not treat `recall_only` as permission to answer for the model. Do not treat
`direct_answer` as permission to click, send, abort, or mutate another
platform. Final evidence authority remains raw/source refs; recalled summaries
are candidate context.

## Source Rules

1. Preserve saved content as-is. Do not redact, mask, hash, rewrite, or replace
   original user text.
2. Treat recalled memories as evidence candidates, not automatic truth.
3. Prefer answers with `library_id`, catalog ids, source refs, timestamps,
   platform names, session/window ids, raw excerpts, `matched_by`, and
   `rank_reason` when available.
4. If the user asks for original wording, source, evidence, or "verbatim",
   return the closest available source text and say when exact source text is
   unavailable.
5. If memories conflict, show the conflict and source trail instead of
   inventing a final answer.
6. Keep platform agent boundaries separate. Do not write into, impersonate, or
   mutate another platform's conversation window.

## Reading Area

The reading area is a read-only, low-pollution shared view. It is not a sixth
shelf and it does not rewrite raw. A window has a borrowing card; the card may
declare reading areas, projects, and series. Membership is declared by the
agent/window, not inferred from a technical `project_id`.

Startup delivery should remain light: push a catalog / table of contents with
headlines, `library_id`, `when_to_use`, and source handles. Pull body content
only when the user or agent follows a `library_id`.

## Internal Shelves

Internal shelf ids remain unchanged for storage compatibility:

- `raw`: original source-backed archive;
- `zhiyi`: preferences and intent experience;
- `xingce`: work experience;
- `toolbook`: objective tool/config/runbook facts;
- `errata`: corrections, supersession, and conflict records.

A skill is only the delivery workflow; it is not the experience layer. When a
recall result includes a library card, keep its shelf and rank reason visible
enough for the user to verify the source trail.
