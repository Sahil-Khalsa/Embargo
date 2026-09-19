# STATUS

Tracks what's actually built against `EMBARGO_SPEC.md`. Update this whenever a checkbox changes state —
this file, not memory or chat history, is the record of where the build stands.

Last updated: 2026-09-18

## Current tier: V0 (in progress)

Repo has a git history now (pushed to https://github.com/Sahil-Khalsa/Embargo). `embargo/models.py` is the
first module built; everything else in the module list is still to do.

## V0 — must land before V1 starts (spec §9)

### Modules (spec §5)
- [x] `embargo/models.py` — FactState, MaterialityLevel, ResolutionMode, Verdict enums (Verdict carries
      spec §4.4 severity ordering) + Fact, Crossing, Message, Resolution dataclasses. TDD'd in
      `tests/test_models.py` (9 tests, all passing). No state-machine or materiality-lookup logic here by
      design — that's `ledger.py`'s job per spec §5.
- [x] `embargo/ledger.py` — `Ledger` class (SQLite-backed, tables for facts + materiality history) with
      `add_fact`/`get_fact`/`list_facts`, plus `transition()` enforcing exactly the four allowed paths from
      spec §3.1 (private→announced requires `announced_at`; private→abandoned; announced→cleared requires
      `cleared_at` AND real elapsed time ≥ it; abandoned→cleared is the unconditional manual-compliance
      path, no elapsed-time gate). Everything else raises `ValueError`. Standalone `materiality_at(fact, at)`
      pure function alongside it. TDD'd in `tests/test_ledger.py` (16 tests, all passing).
- [x] `embargo/access.py` — `Access` class (SQLite-backed `crossings` table) with `add_crossing`/
      `list_crossings`, plus a pure `authorized(crossings, party_id, fact_id, at)` function (mirrors
      `ledger.materiality_at`'s pure-function-over-in-memory-data pattern). No transitivity: `authorized()`
      only ever checks a direct `Crossing` row for that exact party — nothing infers access from someone
      else's. TDD'd in `tests/test_access.py` (9 tests, all passing).
- [x] `embargo/prefilter.py` — `candidate_facts(message, facts, crossings)` returning `Candidate(fact, reasons)`
      records, `reasons` a set drawn from `{entity_match, alias_match, party_authorization}` (union, not
      first-match — a fact can hit more than one). Word-boundary, case-insensitive keyword matching against
      entities/aliases; party-authorization check runs `access.authorized()` for sender and every recipient
      against each fact, which is what catches an oblique reference with no keyword hit (spec §4.1's
      "essential" case). Reasons are carried through for the trace's candidate-selection record (§4.5), not
      recomputed later. TDD'd in `tests/test_prefilter.py` (9 tests, all passing).
- [x] `embargo/resolver.py` — `Resolver` Protocol; `FakeResolver` (fixture dict or `.from_file()`, JSON keyed
      by message id); `ModelResolver` (injected `model_call: Callable[[str], str]` — no vendor SDK wired in
      yet, keeps this testable and unopinionated about which model backend V2 eventually plugs in). Prompt
      sends only candidate id/summary/entities/aliases — never `state`/`announced_at`/`cleared_at`, and never
      asks about materiality/violation. One retry on invalid JSON, then raises `ResolverOutputInvalid`
      (caller — the pipeline, not yet built — turns that into the `review`/`resolver_output_invalid` verdict
      per spec §4.2; the resolver itself never emits a verdict). Both resolvers reject-and-log any resolution
      whose `span` isn't verbatim in the message body (spec §3.4). TDD'd in `tests/test_resolver.py`
      (10 tests, all passing — including ModelResolver's own tests, which per spec §7 are the one place a
      non-FakeResolver test is allowed, using an injected fake `model_call` rather than real network access).
- [ ] `embargo/decision.py` — pure verdict logic, no I/O, no import of `resolver.py`
- [ ] `embargo/trace.py` — trace record construction + JSONL writer
- [ ] `embargo/cli.py` — `screen`, `ledger`, `cross`, `eval`, `trace` subcommands

### Corpus & eval (spec §8)
- [ ] `corpus/facts.yaml`, `corpus/crossings.yaml`, `corpus/messages.yaml` (30–40 messages)
- [ ] Corpus committed *before* the resolver prompt is written
- [ ] `eval/run_eval.py` + `eval/fixtures/`
- [ ] All 9 required hard cases (§8.1) present in the corpus
- [ ] Resolver precision/recall and end-to-end verdict accuracy reported separately

### Acceptance criteria (spec §9) — all five required
- [ ] 1. Same message, three `--as-of`/`--recipients` combos → three different correct verdicts
- [ ] 2. All nine hard cases (§8.1) pass
- [ ] 3. `decision.py` has full unit test coverage, no model in the loop
- [ ] 4. Every screened message produces a trace that reconstructs its decision
- [ ] 5. Eval runs from fixtures with no network access

## V1 — blocked on V0 (spec §13)
Not started. Criteria: spec §13.6.

## V2 — blocked on V1 (spec §14)
Not started. Criteria: spec §14.5.

## Open questions (spec §12)
Unresolved, flag to the user if implementation forces a choice — do not decide unilaterally:
- Materiality assessment: how much can be model-assisted
- Digestion window: fixed policy vs. per-event
- Number of materiality levels and who may change them post-intake

## Log
- 2026-09-18 — Repo initialized: `EMBARGO_SPEC.md` (pre-existing), `CLAUDE.md`, `STATUS.md` added.
- 2026-09-18 — Git repo created, pushed to https://github.com/Sahil-Khalsa/Embargo.
- 2026-09-18 — `embargo/models.py` built via TDD: enums + Fact/Crossing/Message/Resolution dataclasses.
- 2026-09-18 — `embargo/ledger.py` built via TDD: SQLite `Ledger`, state transitions, `materiality_at()`.
- 2026-09-18 — `embargo/access.py` built via TDD: SQLite `Access` class + pure `authorized()`.
- 2026-09-18 — `embargo/prefilter.py` built via TDD: `candidate_facts()` with keyword + authorization
  matching, both reported as reasons.
- 2026-09-18 — `embargo/resolver.py` built via TDD: `Resolver` Protocol, `FakeResolver`, `ModelResolver`
  (injected model_call, retry-then-raise, span verbatim-check).
