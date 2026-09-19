# STATUS

Tracks what's actually built against `EMBARGO_SPEC.md`. Update this whenever a checkbox changes state —
this file, not memory or chat history, is the record of where the build stands.

Last updated: 2026-09-18

## Current tier: V0 — COMPLETE, all five acceptance criteria verified

Repo has a git history (https://github.com/Sahil-Khalsa/Embargo, though the latest commits are currently
stuck locally — see the push note in the log below). Every module, the corpus, and the eval harness are
built and passing. V1 has not been started; do not pull any V1/V2 feature forward without discussing it.

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
- [x] `embargo/decision.py` — `decide(message, resolutions, facts, crossings, threshold=0.6) -> MessageDecision`.
      Implements gate (§4.3: mentions don't proceed and get no verdict; low-confidence conveys → `REVIEW`
      reason `low_confidence` without touching ledger state at all) and per-fact decision (§4.4: is_cleared →
      materiality none → sender authorized → recipient authorized → clean, in that order). Per advisor
      review: all party-authorization lookups are computed unconditionally (never short-circuited) so the
      trace can show every check even when the verdict was decided by an earlier one. Message-level verdict
      is `max()` over contributing per-fact verdicts using `Verdict`'s built-in severity ordering; no
      contributing verdicts (all `mentions`, or empty) defaults to `CLEAN`. Imports `access.authorized` and
      `ledger.materiality_at` (deterministic, allowed) but never `resolver` (asserted by a source-scan test).
      TDD'd in `tests/test_decision.py` (12 tests, all passing).
- [x] `embargo/trace.py` — `build_trace()` joins candidates (with reasons), every resolution (including
      `mentions`/below-threshold, span included) with its `FactDecision` check details, plus message-level
      verdict and a `ledger_version` placeholder (§13.1 wires this up for real later). Separate
      `build_resolver_failure_trace()` for the §4.2 resolver-exhausted-retries path (`review` /
      `resolver_output_invalid`), since `decision.py` can't know about resolver failures. Records
      `as_of_override`/`recipients_override` alongside the effective values actually used, so a `--as-of`/
      `--recipients` override is visible in the trace, not just its effect. `write_trace`/`read_traces` do
      JSONL append/read; `read_traces(path, message_id=...)` returns **every** record for that id, in write
      order — needed because the V0 demo screens one message three ways. TDD'd in `tests/test_trace.py`
      (10 tests, all passing).
- [x] `embargo/cli.py` — `screen_message()` is the testable pipeline core (prefilter → resolver → decide →
      trace record, resolver-failure path included) used by both `embargo screen` and its own unit tests
      (via a raising stub resolver, keeping "other tests use FakeResolver" honest for the default path).
      argparse wiring for all five spec §6 subcommands (`ledger add/list/show/transition`, `cross add/list`,
      `screen`, `eval`, `trace show`). `screen` builds the effective message via `dataclasses.replace`
      (overridden timestamp/recipients) and passes overrides through to the trace. `trace show` prints every
      record for a message id (not just the latest). `eval` delegates to `eval/run_eval.py`. TDD'd in
      `tests/test_cli_screen.py` (5 tests) and `tests/test_cli_main.py` (6 tests, including a direct
      end-to-end proof of acceptance criterion 1: one message, three `--as-of`/`--recipients` combinations,
      three different correct verdicts) — 11 tests, all passing.

### Corpus & eval (spec §8)
- [x] `corpus/facts.yaml` (23 facts), `corpus/crossings.yaml`, `corpus/messages.yaml` (30 messages).
      All fictional companies (Acme, Beta, Gamma, ... plus distinctive coined names like Muvex/Sigmatek for
      padding, chosen specifically to avoid word-boundary keyword collisions with each other or common
      English words). M001–M010 are the nine required hard cases (M004/M005 are the two halves of the
      before/after-`cleared_at` case); M011–M023 are one padding message per remaining fact; M024–M030 add
      contrast cases (no-candidate message, same fact/different parties, sender-authorized contrast, two
      facts in one message, mentions-only).
- [x] Corpus deviates from the letter of "commit corpus before writing the resolver prompt" — `resolver.py`
      was already built (spec §7's prompt has no corpus to overfit to, since none existed yet). Noted here
      per spec's own instruction to flag the deviation; the resolver prompt must not be edited now that the
      corpus exists, which preserves the rule's actual purpose.
- [x] `eval/run_eval.py` — YAML/JSON loaders, `run_eval()` computing both metric families, `format_report()`,
      standalone-runnable (`python -m eval.run_eval`). `eval/fixtures/resolutions.json` holds hand-authored
      "correct" resolutions for all 30 messages (spans verified as exact substrings of each body — required
      by spec §3.4). TDD'd against a small synthetic 4-message corpus in `tests/test_run_eval.py` (isolates
      one case each of true-positive, conveys/mentions confusion, false-positive, and total-miss, with the
      expected precision/recall/confusion-matrix values hand-computed and checked) — 4 tests, all passing.
- [x] All 9 required hard cases (§8.1) present, and individually verified (not just via aggregate accuracy)
      in `tests/test_corpus_eval.py` — 10 case-specific tests (one per hard case, 2 for the before/after-clear
      case) plus 4 corpus-health tests (≥30 messages, all four verdicts represented, perfect resolver
      metrics, perfect end-to-end accuracy on this corpus) — 14 tests, all passing.
- [x] Resolver precision/recall (with conveys/mentions confusion as its own count) and end-to-end verdict
      accuracy (with a full 4×4 confusion matrix) are reported as two separate metric families — see
      `EvalReport`/`format_report()` in `eval/run_eval.py`. Running `python -m eval.run_eval` against the
      real corpus currently reports 1.000 on every metric.

### Acceptance criteria (spec §9) — all five verified
- [x] 1. Same message, three `--as-of`/`--recipients` combos → three different correct verdicts. Proven
      directly by `tests/test_cli_main.py::test_screen_same_message_three_ways_yields_three_different_verdicts`
      (violation_upstream_leak, clean, violation_disclosure from one message + one fact, varying only ledger/
      access state via the CLI overrides — the advisor's flagged "clean by vacuum" trap was checked and
      avoided: at every `--as-of`, the message actually reaches the resolver, either the sender or a
      recipient is genuinely crossed).
- [x] 2. All nine hard cases (§8.1) pass — verified individually in `tests/test_corpus_eval.py`, not just via
      an aggregate accuracy number.
- [x] 3. `decision.py` has full unit test coverage, no model in the loop — confirmed with
      `pytest tests/test_decision.py --cov=embargo.decision`: **100% line coverage**, 12 tests, none of which
      touch `resolver.py` or any model.
- [x] 4. Every screened message produces a trace that reconstructs its decision — `screen_message()` always
      returns a trace record (both the normal and resolver-failure paths), `cmd_screen` always calls
      `write_trace()`, and `trace show` prints every recorded screening. Covered in `tests/test_trace.py` and
      `tests/test_cli_main.py`.
- [x] 5. The eval runs from fixtures with no network access — confirmed by grep: no networking library
      (`requests`/`urllib`/`http.client`/`socket`) appears anywhere in `embargo/` or `eval/`, and
      `ModelResolver` is never referenced by `eval/run_eval.py` or `embargo/cli.py` — only `FakeResolver` is
      wired into the eval and screen paths in V0.

**Full suite: 104 tests, all passing** (`python -m pytest -q`).

## V1 — blocked on V0 (spec §13)
Not started. Criteria: spec §13.6.

## V2 — blocked on V1 (spec §14)
Not started. Criteria: spec §14.5.

## Open questions (spec §12)
Unresolved, flag to the user if implementation forces a choice — do not decide unilaterally:
- Materiality assessment: how much can be model-assisted
- Digestion window: fixed policy vs. per-event
- Number of materiality levels and who may change them post-intake

## Known follow-up (not spec-mandated, noted rather than fixed to avoid V0 scope creep)
- If a resolver ever returns a `fact_id` that wasn't among the candidates it was given (a hallucination,
  for a real model backend), `decide()` will raise `KeyError` rather than rejecting it gracefully the way
  `resolver.py` already rejects a non-verbatim `span`. Every hand-authored fixture in this corpus only
  returns fact ids that are genuine candidates, so this never triggers in V0. Worth a
  reject-and-log guard in `resolver.py` (same layer, same pattern as span validation) before `ModelResolver`
  is ever pointed at a real model in V2.

## Dependencies
- `PyYAML` (see `requirements.txt`) — needed for `corpus/*.yaml` per spec §5's module layout; confirmed
  available and used deliberately (not framework bloat, spec's own file layout requires a YAML parser).
  Not yet formalized into `pyproject.toml` since that's explicitly a V2 packaging concern (§14.1).

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
- 2026-09-18 — Consulted advisor before decision.py/trace.py/cli.py: return per-fact check records (not a
  bare Verdict) so the trace can reconstruct every check; watch for the criterion-1 "clean by vacuum" trap
  where no candidates reach the resolver at an --as-of timestamp; report resolver and end-to-end metrics
  separately; verified PyYAML is available for corpus/*.yaml.
- 2026-09-18 — `embargo/decision.py` built via TDD: `decide()` — gate + per-fact checks (unconditionally
  computed) + message-level severity via Verdict ordering.
- 2026-09-18 — `embargo/trace.py` built via TDD: `build_trace()`/`build_resolver_failure_trace()` +
  JSONL `write_trace()`/`read_traces()`.
- 2026-09-18 — `embargo/cli.py` built via TDD: `screen_message()` core + all five argparse subcommands.
  Acceptance criterion 1 directly proven by `test_screen_same_message_three_ways_yields_three_different_verdicts`.
- 2026-09-18 — `git push` started hanging on a credential-manager prompt (network to GitHub itself is fine —
  `curl` succeeds; `GIT_TERMINAL_PROMPT=0` push fails with "terminal prompts disabled", confirming the
  credential helper needs interactive re-auth). Continuing to build/commit locally; push needs the user to
  re-authenticate in an interactive terminal.
- 2026-09-18 — `eval/run_eval.py` built via TDD against a synthetic 4-message corpus (4 tests) isolating one
  case each of TP/confusion/FP/miss with hand-computed expected metrics.
- 2026-09-18 — Corpus built: 23 facts, 30 messages (9 hard cases = 10 messages, 13 one-per-fact padding
  messages, 7 contrast/variety messages), fixtures for all 30. `python -m eval.run_eval` against the real
  corpus: 1.000 precision/recall/accuracy on the first run after fixing corpus construction.
- 2026-09-18 — All five V0 acceptance criteria (§9) explicitly verified: criterion 1 by a dedicated CLI test,
  criterion 2 by 10 individual hard-case tests, criterion 3 by `--cov=embargo.decision` showing 100%,
  criterion 4 by trace tests, criterion 5 by grepping for networking libraries and `ModelResolver` references
  (none found in the eval/screen path). **V0 is complete: 104 tests passing.**
