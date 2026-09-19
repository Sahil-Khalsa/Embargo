# STATUS

Tracks what's actually built against `EMBARGO_SPEC.md`. Update this whenever a checkbox changes state —
this file, not memory or chat history, is the record of where the build stands.

Last updated: 2026-09-18

## Current tier: V0 (not started)

No code exists yet. Repo currently contains only `EMBARGO_SPEC.md`, `CLAUDE.md`, `STATUS.md`, and Claude
Code project config.

## V0 — must land before V1 starts (spec §9)

### Modules (spec §5)
- [ ] `embargo/models.py` — Fact, Crossing, Message, Resolution, Verdict dataclasses
- [ ] `embargo/ledger.py` — SQLite store, state transitions, `materiality_at()`
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
