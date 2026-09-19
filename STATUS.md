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
- [ ] `embargo/access.py` — access graph, `authorized()`
- [ ] `embargo/prefilter.py` — candidate selection
- [ ] `embargo/resolver.py` — `Resolver` Protocol, `ModelResolver`, `FakeResolver`
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
