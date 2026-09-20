# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## State of the repo

V0, V1, and V2 are all built (V2 with one documented gap: no live model backend — see `STATUS.md` §14.2).
`EMBARGO_SPEC.md` is the complete, self-contained build brief — it is the source of truth for what to
build. `STATUS.md` tracks what has actually been built, with the reasoning and flagged interpretations
behind each section; check it before assuming anything. When the two disagree, the spec wins for *what to
build*, and `STATUS.md` wins for *what is already built*.

Read `EMBARGO_SPEC.md` in full before implementing anything — this file only orients you within it.

Working conventions that held throughout the build: test-first (write the test, watch it fail for the right
reason, then implement); verify acceptance criteria directly rather than asserting them; never commit
without an explicit ask, and no `Co-Authored-By` trailer on commits or PRs (enforced via
`.claude/settings.json`).

## What this system is

Embargo screens messages for MNPI (material non-public information). The core design decision: MNPI is a
property of a *fact* and *when it was said to whom*, not a property of message text. So the system never
asks a model "is this a violation" — it asks the model only "which known facts does this message convey,"
and a deterministic decision layer does the rest. This split is the entire point of the architecture; don't
blur it when implementing (e.g. don't let the resolver prompt see fact state/timestamps, don't let the
decision layer call the model).

## Commands (per spec §2, §6, §13, §14)

- Stack: Python 3.11+, stdlib `sqlite3` for storage, stdlib `argparse` for the CLI, stdlib `http.server`
  for the reviewer UI and screening endpoint, stdlib `tomllib` for config, `pytest` for tests, PyYAML for
  the corpus files. No framework. Dependencies kept minimal.
- Install for development: `pip install -e .`. Tests: `pytest` (run from the repo root; a few CLI tests
  pin their own cwd). Every test except the resolver's own runs against `FakeResolver` — no network
  access in the suite.
- CLI (command `embargo`; PyPI distribution `embargo-screen`, imports/command stay `embargo`). A global
  `--config <toml>` goes *before* the subcommand; precedence is explicit CLI flag > config file > default.
  - `embargo screen --message <id> [--as-of <ts>] [--recipients <a,b>]` or `--batch <file>`
  - `embargo ledger add|list|show|transition`, `embargo cross add|list`
  - `embargo rescreen --since <ledger_version>` (a `ledger add` also re-screens affected traces itself)
  - `embargo eval [--adversarial]`, `embargo calibrate [--budget <fraction>]`
  - `embargo trace show <message_id>`, `embargo trace verify`
  - `embargo review` (reviewer web UI, :8000), `embargo serve` (HTTP screening endpoint, :8001)
- Eval reports resolver metrics, prefilter recall, and end-to-end verdict accuracy as **separate**
  metrics, never collapsed into one number; the adversarial corpus is reported separately from V0's.

## Invariants added after V0 (each one was a real bug or near-miss)

- **One screening code path.** `pipeline.screen_and_write` is the only place that pairs `screen_message`
  with `write_trace`; CLI `--message`, `--batch`, and the HTTP endpoint all call it. Don't add a fourth
  path — byte-identical traces (spec §14.5) depend on there being one.
- **The threshold has one source.** `embargo.config.DEFAULT_THRESHOLD`. Don't hardcode `0.6` anywhere.
- **The trace file holds two record types**, discriminated by `record_type` (`screening`, `reviewer_action`;
  a record with no `record_type` is an old screening). Any code that reads `verdict`/`ledger_version`/
  `timestamp` must filter to screenings first (`rescreen.current_traces`, `cmd_trace_show` do).
- **`trace_id` is a content hash** that excludes `prev_hash` (the chain link, added at write time). Anything
  put in a record — including `backend`/`model_version` — feeds `trace_id`, so it must resolve identically
  on every path.
- **The `Resolver` Protocol's shape is frozen** (spec §7). `backend_name`/`model_version` are duck-typed
  extras read with `getattr`, not Protocol members.
- **Schema changes need a migration** in `embargo/migrations.py`; `CREATE TABLE IF NOT EXISTS` never adds
  a column to an existing table.

## Architecture

Pipeline (spec §4), each stage strictly deterministic except the resolver:

```
message -> prefilter (deterministic) -> resolver (model) -> gate (deterministic) -> decision (pure) -> trace
```

- **prefilter** (`prefilter.py`): candidate facts = union of (a) entity/alias string match in the message
  body, and (b) any fact that any party *to the message* (sender or recipient) is wall-crossed onto at that
  timestamp. (b) is what catches oblique references between two authorized people with no keyword hit — do
  not drop it. Never send the full ledger to the model.
- **resolver** (`resolver.py`): the model's only job is to return `Resolution` objects (`fact_id`, `mode`:
  `conveys`|`mentions`, `confidence`, verbatim `span`) — never a verdict, never materiality, never fact
  state/`announced_at`/`cleared_at`. One `Resolver` Protocol (spec §7) with `ModelResolver` and
  `FakeResolver` implementations; keep the Protocol shape stable since V2 adds more backends behind it.
- **gate** (part of decision flow, spec §4.3): the single confidence threshold in the whole system (default
  0.6). `conveys` above threshold proceeds; below threshold routes to `review` (never silently dropped);
  `mentions` is logged but does not proceed.
- **decision** (`decision.py`): pure function over resolutions + ledger state, no I/O, MUST NOT import
  `resolver.py`, and MUST be fully unit-testable with no model in the loop. Check order matters — cleared,
  then materiality-none, then sender authorization, then recipient authorization — because an unauthorized
  *sender* (`VIOLATION_UPSTREAM_LEAK`) is a stronger finding than an unauthorized recipient
  (`VIOLATION_DISCLOSURE`) and must be checked first. Message-level verdict is the most severe across all
  resolved facts, ordered `violation_upstream_leak > violation_disclosure > review > clean`.
- **trace** (`trace.py`): one JSONL record per screened message, containing everything needed to reconstruct
  the decision without re-running anything (candidate reasons, every resolution including sub-threshold and
  `mentions`, per-fact check inputs/results, `ledger_version`). This is the audit artifact — treat its
  completeness as a hard requirement, not a nice-to-have.

Data model invariants (spec §3) that constrain any change to `models.py`/`ledger.py`/`access.py`:

- Fact state machine is exactly `private -> announced -> cleared`, `private -> abandoned`,
  `abandoned -> cleared` (manual compliance action only, never automatic). `abandoned` never clears on its
  own.
- Materiality is a time series (`(effective_from, level)`), looked up at the message timestamp — never
  re-assessed per message.
- Wall-crossing (`access.py`) is explicitly **not transitive**. Do not implement any inference that grants
  authorization from someone else's authorization — that inference is the exact violation the system exists
  to catch.
- `recorded_at` (when the ledger learned a fact) is stored from V0 even though it's unused until V1's
  re-screening (§13.1) — this and `ledger_version` in the trace exist in V0 specifically to avoid a later
  migration. Don't remove them for being unused.

## Build order

Three tiers, each gated on the previous one's acceptance criteria (spec §9, §13.6, §14.5) — do not pull a
later-tier feature into an earlier tier even if it looks easy; the whole point of the tiering is that V0's
criteria prove the architecture in isolation:

1. **V0** (spec §1–9): the full pipeline above, SQLite ledger/access graph, CLI, 30–40 message eval corpus
   with the 9 required hard cases (§8.1) written and committed *before* the resolver prompt is written (a
   corpus authored alongside the prompt scores near-perfect and proves nothing).
2. **V1** (spec §13): late-fact re-screening (append-only, `supersedes` links, originals never mutated),
   threshold calibration sweep, a separate adversarial eval corpus (never merged into V0 metrics),
   hash-chained tamper-evident trace store, embedding-based prefilter as a supplement (not replacement) to
   entity/alias matching.
3. **V2** (spec §14): pip packaging, pluggable model backends behind the same `Resolver` Protocol (config
   selects backend, not code), reviewer web UI, batch/HTTP modes that share the CLI's code path exactly
   (batch and single-message screening must produce byte-identical traces for the same input).

## Things to flag rather than decide unilaterally (spec §12)

- How much of materiality assessment can be model-assisted without recreating the problem the architecture
  exists to avoid.
- Whether the digestion window (announced → cleared) is one fixed policy or set per event.
- How many materiality levels exist and who may change them post-intake.
