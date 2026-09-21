# STATUS

Tracks what's actually built against `EMBARGO_SPEC.md`. Update this whenever a checkbox changes state —
this file, not memory or chat history, is the record of where the build stands.

Last updated: 2026-09-19

## Current tier: V2 — §14.1–§14.4 all built; acceptance criteria 1, 3, 4 met, criterion 2 partial (by user decision)

Repo: https://github.com/Sahil-Khalsa/Embargo. V0, V1 and V2 are all complete, committed and pushed
(`8b53fa3` V0, `048cfd2` §13.1, `bff4fcf` §13.2–§13.5, `6db77ad` V2). The only spec item not met is a live
model backend (V2 criterion 2, below), by explicit decision. The push credential problem that blocked
every earlier attempt cleared on its own by the time of the V2 push (a 20s-timeout `git push` succeeded).

V2 build order follows spec §10/§14 (within a tier, build in the order the sections are written):
§14.1 Packaging → §14.2 Pluggable model backend → §14.3 Reviewer UI → §14.4 Batch/service mode.

**Two V2 scope decisions made with the user before coding (not mine to decide unilaterally):**
- V2 acceptance criterion 2 ("two different model backends run the eval, selected by config with no
  code change") — user chose to build the config-driven backend-selection machinery only, with no
  backend actually making a live model call (no API key, no local model server available in this
  environment). This is a **partial** satisfaction of criterion 2, called out explicitly here and in
  §14.2's own notes rather than quietly claimed as done.
- §14.3's reviewer UI — user chose stdlib `http.server` over adding Flask, keeping the zero-framework
  discipline consistent with the rest of the stack.

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

**V0 full suite: 104 tests, all passing** (`python -m pytest -q`).

## V1 — in progress (spec §13)

### §13.1 — Re-screening when a fact is recorded late — COMPLETE
- [x] Prerequisite bug fix (found by the advisor before this section started): `resolver.py`'s
      `_validate_resolutions()` (renamed from `_reject_non_verbatim_spans`) now also rejects any resolution
      whose `fact_id` isn't among the `candidates` it was given, not just a non-verbatim `span`. Without this,
      the very re-screening scenario this section exists for — a fact not yet in the ledger, so prefilter
      surfaces zero candidates, but `FakeResolver` ignores its `candidates` argument and returns the fixture
      entry anyway — would crash `decide()` with `KeyError` instead of correctly resolving to `clean`.
- [x] `embargo/models.py` — `Fact.valid_from: datetime | None = None`, defaulted to `recorded_at` in
      `__post_init__` when omitted. This default is exactly what keeps all 104 V0 tests and the 23-fact
      corpus green with zero edits — but note it also means `valid_from == recorded_at` unless explicitly set
      earlier, so re-screening only ever finds anything to do for backdated facts.
- [x] `embargo/ledger.py` — `valid_from` column persisted; shared `ledger_version` counter (a
      `ledger_version` table, `ensure_version_table`/`bump_version`/`read_version` free functions,
      `Ledger.current_version()`). Every `add_fact`/`transition` bumps it by 1. **V0-era `embargo.db` files
      need to be recreated for V1** — `CREATE TABLE IF NOT EXISTS` doesn't add a column to an existing table,
      and real migrations are explicitly V2 scope (§14.1), not handled here.
- [x] `embargo/access.py` — `Access.add_crossing` bumps the *same* shared counter (imported from
      `ledger.py`) so it only actually shares state when `Ledger` and `Access` point at the same file path
      (proven with a `tmp_path`-backed test — `:memory:` databases are per-connection and would not share
      state, which the first draft of this test got wrong).
- [x] `embargo/trace.py` — `trace_id` is a SHA-256 content hash over the record's canonical JSON (sorted
      keys, excluding `trace_id` itself), not a random id: two screenings with identical content get the same
      id, which both anticipates §13.4's hash-chain identity and doesn't fight V2 §14.5's byte-identical-
      traces criterion the way a `uuid4` would have. `supersedes: str | None` added alongside it.
- [x] `embargo/pipeline.py` — new module. `screen_message()` was extracted out of `cli.py` into here because
      `rescreen.py` needs it and `cli.py` needs `rescreen.py` (auto-trigger on `ledger add`); the two-way
      dependency would otherwise be a circular import. Pure refactor, no behavior change — full suite stayed
      green (124 passed) immediately after the move.
- [x] `embargo/rescreen.py` — new module. `current_traces()` selects non-superseded records (a trace is
      current iff no other record's `supersedes` equals its `trace_id`). `rescreen_stale_traces()` re-screens
      every current trace with `ledger_version < max_version` (optionally also filtered to
      `timestamp >= timestamp_from`, used only for the single-fact auto-trigger), reconstructing the
      `Message` directly from the trace record's own stored effective sender/recipients/timestamp/body —
      which is also what makes a prior `--as-of`/`--recipients` override survive a re-screen automatically,
      with no extra plumbing. Writes a new superseding trace for **every** affected message, but only
      *returns* (and the CLI only reports) the ones whose verdict actually changed — read literally, spec's
      "produces superseding traces with changed verdicts where appropriate" doesn't force a choice here, so
      this is the flagged interpretation: completeness of the audit trail over a smaller trace file.
- [x] `embargo/cli.py` — `ledger add` gained `--valid-from` (defaults to `--recorded-at`), `--trace-file`,
      `--fixtures`, and now auto-triggers `rescreen_stale_traces()` after every add (a no-op if the trace
      file has no history yet). New `embargo rescreen --since <version>` command. **Flagged ambiguity,
      resolved and not relitigated further:** "`--since <version>`" is read plainly as "re-screen every
      current trace recorded at `ledger_version < <version>`" — a batch/catch-up operation, not tied to one
      specific fact the way the automatic trigger is.
      Also fixed while wiring this up: `cmd_ledger_add` was anchoring the fact's initial materiality entry at
      `recorded_at` unconditionally; for a backdated fact (`valid_from` earlier than `recorded_at`) that left
      a gap where `materiality_at()` had nothing to look up for messages sent in between, and re-screening
      such a message crashed with `ValueError`. Materiality is now anchored at `valid_from`.

**§13.1 acceptance criterion 1 verified directly, end-to-end, through the real CLI**
(`tests/test_cli_rescreen.py::test_ledger_add_auto_rescreens_affected_messages`): a message mentioning a
not-yet-ledgered fact screens `clean` (nothing to convey yet); the fact is then entered via `ledger add` with
`--valid-from` predating the message; the add's own output reports `M100: clean -> violation_upstream_leak`;
the trace file has two records for that message, the second `supersedes` the first. The manual
`embargo rescreen --since` path is verified separately in the same file.

**V1 full suite so far: 126 tests, all passing.**

### §13.2 — Calibration tooling — COMPLETE
- [x] `eval/calibrate.py` — new module. `CalibrationPoint` (threshold, resolver_precision, resolver_recall,
      review_share, verdict_accuracy). `sweep_thresholds()` runs `DEFAULT_THRESHOLDS` (0.0–1.0 step 0.05, or a
      custom list) over the corpus. **Key reinterpretation, confirmed with the advisor before coding:**
      precision/recall here must be threshold-*dependent* or "at each point" in the spec text is meaningless —
      a fact counts as correctly identified only when `mode == conveys AND confidence >= threshold` (i.e. it
      actually clears the gate), not merely `mode == conveys` as in the plain V0 eval. `review_share` is the
      fraction of *messages* whose message-level verdict is `review` (not a fraction of resolutions).
- [x] `best_threshold_for_budget(points, budget)` — among thresholds with `review_share <= budget`, picks max
      `resolver_recall`, ties broken toward the *lower* threshold; returns `None` (reported explicitly, never
      silently substituted) if no threshold fits. Recall is weighted over precision per spec's own rationale
      ("a missed leak costs more than a message a human glances at").
- [x] `embargo calibrate [--budget <fraction>]` wired into `cli.py`.
- [x] Verified: recall is monotonically non-increasing and review_share monotonically non-decreasing across
      the sweep (`tests/test_calibrate.py`) — the check the advisor specifically flagged to catch an
      accidentally-threshold-independent implementation. Also ran against the real V0 corpus by hand: recall
      drops from 1.000 to 0.000 and review_share climbs from 0.000 to 0.900 across the full 0.0–1.0 sweep,
      with the single `review`-ground-truth message (M015, 0.35 confidence) driving the middle of the curve.

### §13.3 — Adversarial eval cases — COMPLETE
- [x] `corpus/adversarial/{facts,crossings,messages}.yaml` + `eval/fixtures/adversarial.json` — a second,
      disjoint corpus (6 facts, 8 messages) covering all six required categories: misdirection, a fact split
      across a two-message reply thread with no single conveying message, an entity name colliding with a
      common word ("Current"), an alias that's also an innocent internal document name ("Blue Horizon"), a
      near-identical qualifier pair (adds one clause), and a fact conveyed only inside quoted reply text.
- [x] **The fixtures are deliberately imperfect**, not hand-tuned to pass — per the advisor's explicit warning
      that a corpus scoring 1.000 "proves nothing." Each fixture encodes a specific, reasoned failure: the
      misdirection case gets a false-positive low-confidence read; the thread-split fact is never surfaced to
      the resolver at all (zero crossings for that fact, no entity text in the completing message — a genuine
      *prefilter* miss, not a resolver miss); the alias case gets a false-positive from literal span-matching;
      the near-identical pair gets a conveys/mentions confusion; only the quoted-reply case and the
      common-word-collision case are handled correctly, showing the system isn't hopeless, just degraded.
      Result on this corpus: precision 0.333, recall 0.333, verdict accuracy 0.750 — genuinely worse than
      V0's 1.000/1.000/1.000, never merged into the same report.
- [x] `embargo eval --adversarial` — convenience flag on the existing `eval` command swaps in the adversarial
      corpus's default paths; explicit `--facts`/etc. still override. No new report format was needed since
      `run_eval()` already produces one report per invocation — running it against two different corpora
      *is* "reporting separately," so no merging logic exists to accidentally combine them.

### §13.4 — Tamper-evident trace store — COMPLETE
- [x] `embargo/trace.py` — `write_trace()` now reads the last raw line in the file (if any), stores
      `sha256(prev_line)` as `record["prev_hash"]` (`None` for the first record), then appends the record
      canonically serialized (`sort_keys=True, separators=(",", ":")`) — same canonical form `trace_id`
      already used, so the two hashing schemes agree on what "the bytes of a record" means.
      `trace_id` (content hash, computed by `_finalize()` before `prev_hash` exists) and `prev_hash`
      (chain position, added at write time) stay deliberately independent — a record's identity doesn't
      depend on where it landed in the file.
- [x] All file reads/writes for chain purposes use `open(..., newline="")`, both directions, so a Windows
      autocrlf checkout can never silently turn `\n` into `\r\n` under the hasher and produce a false "tamper"
      report — the advisor flagged this as the specific trap here.
- [x] `verify_chain(path) -> ChainVerification(ok, broken_at_line)` walks the file and reports the first
      record whose stored `prev_hash` doesn't match the SHA-256 of the immediately preceding raw line.
      `embargo trace verify [--trace-file]` prints `chain intact` or `chain broken at line N`.
- [x] Re-screens already only ever append (established in §13.1) — no change needed for that requirement.
- [x] **Acceptance criterion 4 verified directly**: `tests/test_trace_chain.py::test_verify_chain_detects_hand_edited_record`
      writes three records, literally rewrites the middle record's raw bytes on disk, and asserts
      `verify_chain` reports `broken_at_line == 3` — the first point verification actually fails (the record
      *after* the edited one, since that's whose `prev_hash` claim no longer matches).
- [x] Changing `write_trace`'s byte output (default → canonical separators, plus the new field) broke one
      existing round-trip equality test (`test_trace.py::test_write_trace_then_read_traces_round_trips`),
      fixed by comparing against `dict(record, prev_hash=None)` instead of the bare record — a real behavior
      change, not a regression. Ran the full suite immediately after this change per the advisor's sequencing
      note, before starting §13.5.

### §13.5 — Semantic prefilter — COMPLETE
- [x] `embargo/prefilter.py` — `similarity_candidates()`: bag-of-words cosine similarity (stdlib `Counter` +
      `math.sqrt`, no external dependency) between the message body and each fact's `summary + entities +
      aliases` text, threshold 0.3 by default. **Deliberate spec-§0 SHOULD deviation, documented in the
      function's own docstring**: no ML dependency, no network embedding call — a real embedding backend can
      replace the function body without touching any caller, since the signature (message + facts in, fact_id
      set out) stays the same either way. Named honestly as "similarity", not "embedding", per the advisor's
      explicit note not to overclaim what a bag-of-words method actually does (literal vocabulary overlap
      only, not paraphrase/true semantic matching).
- [x] `candidate_facts()` unions a third `semantic_match` reason alongside `entity_match`/`alias_match`/
      `party_authorization`; entity/alias matching is unchanged and still fires independently (spec's MUST).
- [x] **Tuning-trap guard (per the advisor's specific warning)**: checked the real V0 corpus by hand — average
      candidates per message is ~16/23 facts either way, entirely from the pre-existing `party_authorization`
      mechanism (verified by re-running with the similarity threshold effectively disabled: identical
      average). The new semantic layer adds **zero** new candidates anywhere in the V0 corpus and only two
      (both already-`entity_match`ed) in the adversarial corpus — it is not silently inflating candidate sets.
      `tests/test_prefilter_semantic.py` also asserts directly against the real corpus's M024 ("lunch plans")
      message: no fact is surfaced by similarity alone.
- [x] Five existing `test_prefilter.py`/`test_trace.py` assertions on exact `reasons` sets started failing
      once the semantic layer was added, because their fixtures reuse the entity name between the fact and a
      very short message body — cosine similarity on short texts is naturally high when they share even one
      rare/distinctive token. Updated the expected sets to include `semantic_match` rather than re-engineering
      the fixtures to dodge it; this is honest behavior, not a bug.
- [x] `eval/run_eval.py` — new `EvalReport.prefilter_recall` field, computed purely from `candidate_facts()`
      output (never from resolutions): of all `expected_fact_ids` across the corpus, the fraction that
      actually reached the resolver as a candidate at all. V0 corpus: 1.000 (everything keyword-matches).
      Adversarial corpus: 0.667 (the thread-split case's total prefilter miss pulls it down) — **this is
      exactly the "invisible clean verdict" failure mode spec §13.5 warns about**, now visible as its own
      number instead of being masked by resolver or verdict-accuracy metrics.
- [x] **Acceptance criterion 5 verified directly**: `tests/test_prefilter_recall_metric.py` — a fact expected
      on two messages, keyword-matched on one and mentioned nowhere in the other, asserts `prefilter_recall
      == 0.5`, independent of what any fixture claims the resolver returned.

**V1 full suite: 159 tests, all passing. All five V1 acceptance criteria (§13.6) verified directly:**
1. Auto-rescreen on late fact entry — `test_cli_rescreen.py` (§13.1)
2. `embargo calibrate` sweep table — `test_cli_calibrate.py` (§13.2)
3. Adversarial corpus runs and reports separately — `test_adversarial_eval.py`, `test_cli_eval_adversarial.py` (§13.3)
4. `embargo trace verify` detects a hand-edited record — `test_trace_chain.py`, `test_cli_trace_verify.py` (§13.4)
5. Prefilter recall reported as its own metric — `test_prefilter_recall_metric.py` (§13.5)

**Per the user's explicit instruction ("complete coding first then we will commit and push together"), all
of §13.2–§13.5 was committed together** as `bff4fcf`, after the advisor caught and this session fixed a
real bug in `best_threshold_for_budget` (see the §13.2 entry above) — nothing was committed with a known
defect. V1 is fully complete and committed.

## V2 — in progress (spec §14)

### §14.1 — Packaging — COMPLETE
- [x] `embargo/migrations.py` — new module. `migrate(conn)` checks whether an already-open connection's
      `facts` table predates `valid_from` (a real, already-documented trigger from §13.1: `CREATE TABLE IF
      NOT EXISTS` never adds a column to an existing table) and, if so, adds it via `ALTER TABLE` and
      backfills every existing row from `recorded_at` — the same default `Fact.__post_init__` uses for a
      fact constructed without an explicit `valid_from`. A brand-new database has no `facts` table yet, so
      there's nothing to migrate; `Ledger`'s own schema script creates it in the current shape. Wired into
      `Ledger.__init__`, called before the schema script runs. **Tested against a genuinely V0-shaped
      database** built by hand with raw `sqlite3` (not a synthetic shortcut) — proves `Ledger()` opens it
      without crashing, backfills correctly, and is idempotent on a second open.
- [x] `embargo/config.py` — new module. `Config` (frozen dataclass: `threshold`, `digestion_window_days`,
      `backend`, `db_path`) + `load_config(path)` reading an optional TOML file via stdlib `tomllib`
      (Python 3.11+, no new dependency). A missing path or missing file is not an error — falls back to
      built-in defaults, consistent with every other optional CLI setting in this project.
      **`digestion_window_days` is read but deliberately never auto-applied anywhere** — spec §12 flags
      "fixed policy vs. per-event" as an open question not to be decided unilaterally; the field exists so
      a future decision has somewhere to live, the same pattern V0 used for `recorded_at`/`ledger_version`.
- [x] **Threshold de-duplication**: `DEFAULT_THRESHOLD` previously existed as one canonical constant in
      `pipeline.py` but was *also* independently hardcoded as a bare `0.6` in `decision.py`, `rescreen.py`,
      and `eval/run_eval.py` (twice). All four now import `DEFAULT_THRESHOLD` from `embargo/config.py`
      (with `pipeline.py` re-exporting it, so `cli.py`'s existing import keeps working unchanged). This
      was flagged by the advisor specifically: "if config and DEFAULT_THRESHOLD can disagree, the traces
      stop being reproducible." Verified as a pure, behavior-preserving refactor — full suite unchanged
      before/after.
- [x] `embargo/cli.py` — new top-level `--config <path>` flag (must precede the subcommand, e.g. `embargo
      --config embargo.toml screen ...`). `--threshold`/`--db` on every subcommand that had a fixed default
      now default to `None`; new `_resolve_threshold()`/`_resolve_db()` helpers implement the precedence
      explicit CLI flag > config file value > built-in default. Verified directly: configured threshold
      changes a screening's verdict when no `--threshold` flag is given, an explicit `--threshold` flag
      overrides the config value, and a configured `db_path` is used when no `--db` flag is given.
- [x] **Real bug found and fixed via manually running the README demo, not just writing tests for it**:
      `ledger add`'s auto-rescreen step (§13.1) unconditionally called `FakeResolver.from_file(args.fixtures)`
      even when no trace file existed yet to rescreen anything from — crashing a brand-new `ledger add` in
      any fresh directory with `FileNotFoundError` on the *default* fixtures path. Every existing test
      happened to run from the repo root, where that default path genuinely exists, so nothing caught this
      until the demo was run from a truly clean directory. Fixed by skipping the rescreen machinery
      entirely (not merely treating it as a no-op) when `Path(args.trace_file).exists()` is false. Regression
      test added in `tests/test_cli_ledger_add_clean_dir.py`, using `monkeypatch.chdir` to a genuinely empty
      `tmp_path` rather than relying on the repo's own fixture files being present.
- [x] `pyproject.toml` — `embargo-screen` distribution name, `embargo` import package and console command
      (`embargo.cli:main`), `requires-python = ">=3.11"`, single dependency `PyYAML`.
- [x] `README.md` — setup (pip install), the full V0 demo (§9's three-verdicts-one-message scenario,
      reproduced as copy-pasteable commands), `embargo eval`/`--adversarial`/`calibrate` pointers, the new
      config file format, and spec §11's known limitations **verbatim**.
- [x] **Acceptance criterion 1 verified for real, not just asserted**: built a genuinely clean venv
      (`python -m venv`, no dev dependencies), ran `pip install -e .` into it, then ran the README's demo
      commands *verbatim* end to end (`ledger add` → `transition` → three `cross add` → three `screen`
      calls at different `--as-of`/`--recipients` → `trace show`/`trace verify`) with no modification. Got
      exactly the three documented verdicts (`violation_upstream_leak`, `clean`, `violation_disclosure`)
      and a `chain intact` trace verification. This is also what caught the `ledger add` bug above — it
      would not have been caught by any existing test, all of which run from the repo root.

**V2 full suite so far: 173 tests, all passing.**

### §14.2 — Pluggable model backend — COMPLETE (selection machinery; no live call, by user decision)
- [x] `ModelResolver` gained `backend_name`/`model_version` constructor kwargs (default `"unknown"`),
      stored as plain public attributes — not part of the `Resolver` Protocol's formal shape (spec §7:
      "MUST NOT change its shape"), just duck-typed extras concrete resolvers happen to carry.
      `FakeResolver` gained matching class attributes (`backend_name = "fake"`, `model_version =
      "fixtures"`).
- [x] `embargo/trace.py` — `build_trace()`/`build_resolver_failure_trace()` gained `backend`/
      `model_version` fields (default `"unknown"`), included in every trace record.
- [x] `embargo/pipeline.py` — `screen_message()` derives `backend`/`model_version` from the resolver it's
      given via `getattr(resolver, "backend_name"/"model_version", "unknown")` and threads them into the
      trace. **No new parameters needed on `screen_message()` itself** — every caller (`cli.py`,
      `rescreen.py`) already passes a `resolver` instance, so this needed zero changes at any call site.
- [x] `embargo/backends.py` — new module. `BACKEND_FACTORIES = {"fake": ..., "hosted": ..., "self_hosted":
      ...}` + `build_resolver(config, fixtures_path) -> Resolver`. `"fake"` returns a genuinely working
      `FakeResolver`. `"hosted"`/`"self_hosted"` return a correctly-labeled `ModelResolver` whose
      `model_call` raises `NotImplementedError` naming exactly why (no API key / local model server in
      this environment) the moment it's actually invoked — selectable and structurally correct, never
      silently fabricating a resolution. An unknown backend name raises `ValueError` naming the bad value
      and the valid choices.
- [x] `embargo/cli.py` — every place that used to hardcode `FakeResolver.from_file(args.fixtures)`
      (`cmd_ledger_add`'s auto-rescreen, `cmd_screen`, `cmd_rescreen`) now calls
      `build_resolver(args.config_obj, fixtures_path=args.fixtures)` instead. Selecting `backend =
      "hosted"` in a config file changes what these commands do with **zero code change** — exactly
      criterion 2's wording — even though "what they do" is currently "raise `NotImplementedError`
      loudly," which is the honest, correct behavior given no real backend is wired up.
- [x] `eval/run_eval.py` / `eval/calibrate.py` — `run_eval()`/`sweep_thresholds()` gained an optional
      `resolver=None` parameter; when given, it's used instead of internally building `FakeResolver` from
      `fixtures_path`. `cmd_eval`/`cmd_calibrate` now pass `build_resolver(args.config_obj, ...)` through.
      This is what makes criterion 2's literal wording — "two different model backends **run the eval**" —
      actually true of `embargo eval`, not just `embargo screen`.
- [x] **Acceptance criterion 2 verified directly, end to end, and honestly**: a CLI test runs `embargo
      --config fake.toml eval` (succeeds, `messages evaluated: 30`) and `embargo --config hosted.toml eval`
      (same command, same code, only the config file differs) and asserts it raises `NotImplementedError`
      — proving the selection is real and config-driven while being explicit that criterion 2 is only
      **partially** satisfied here, per the user's explicit choice recorded above: no live network/local
      model call exists in this build.

**V2 full suite so far: 191 tests, all passing.**

### §14.3 — Reviewer UI — COMPLETE
- [x] **Record shape decided before any UI code** (advisor's point: the integration is the risk, not the
      HTML). The trace file now holds two record types discriminated by `record_type`: `screening` (every
      `build_trace`/`build_resolver_failure_trace` record now carries it) and `reviewer_action`
      (`trace.build_reviewer_action`: `message_id`, `trace_id_referenced`, `action` in
      confirm/dismiss/escalate, `reviewer`, `at`, `reason`; invalid actions raise). A reviewer action goes
      through the same `write_trace`, so it gets a `prev_hash` and is covered by the hash chain — it
      appends, and `verify_chain` still passes afterward. A record with no `record_type` is an old
      screening, for backward compatibility.
- [x] **Reproduced-then-fixed crash**: `rescreen.current_traces()` indexed `ledger_version`/`timestamp`
      on every record, so one reviewer action in the file made the next `embargo rescreen` `KeyError`.
      It now filters to screenings first. Same class of bug found and fixed later in `cmd_trace_show`
      (see below).
- [x] `embargo/reviewer.py` — HTTP-free business logic: `build_queue` (current, non-superseded, non-clean
      screenings, most severe first, deterministic tie-break by `trace_id`, using `Verdict`'s own
      ordering), `get_finding`, `build_evidence_chain`, `record_reviewer_action`. Authorization is
      surfaced from the per-fact checks already stored in the trace rather than recomputed, so the page
      shows what the decision layer actually saw.
- [x] `embargo/reviewer_server.py` — stdlib `http.server` (user decision), real requests tested against a
      real server on an OS-assigned port. The finding page renders: the message body with resolved spans
      highlighted in `<mark>` (HTML-escaped; overlapping spans merged; a missing span can't crash it);
      the resolver's backend/model_version/ledger_version; what surfaced each candidate; per fact the
      resolver output (mode, confidence, span, whether it passed the gate and why not) followed by every
      deterministic check in `decision.py`'s order with inputs and result and the per-fact verdict; each
      fact's state, timeline, and materiality series; the authorization lookup per party; prior reviewer
      actions; and the confirm/dismiss/escalate form. The trace viewer lists every record and shows chain
      status, with no form (read-only).
- [x] **First version fell short of the spec and was fixed before calling this done**: the initial page
      listed spans and facts but did not highlight the span in the body, did not show the checks with
      their inputs/results, and the trace viewer showed only a chain status. Caught by re-reading §14.3
      against the page; tests written first (7 red), then the rendering rewritten.
- [x] `embargo review [--db] [--trace-file] [--host] [--port 8000]`.
- [x] **Latent bug fixed**: `embargo trace show` indexed `record['verdict']` on every record of a
      message, so it crashed with `KeyError` on any message a reviewer had acted on. Now shows screenings
      and prints reviewer actions as their own lines. Test reproduces the crash first.

### §14.4 — Batch and service mode — COMPLETE
- [x] `embargo/pipeline.py::screen_and_write()` — the single place that pairs `screen_message()` with
      `write_trace()`. `cli.py`'s old local helper is now a thin adapter over it; the HTTP endpoint calls
      it directly. Extracted as a behavior-preserving refactor (full suite unchanged) before the endpoint
      existed, so the endpoint was never a fourth path.
- [x] `embargo screen --batch <file>` — screens every message in a messages file, prints a per-verdict
      summary. `--message` and `--batch` are mutually exclusive (exactly one required; exit 2 otherwise).
- [x] `embargo/screen_server.py` + `embargo serve` — `POST /screen` takes one message as JSON and returns
      `{"verdict", "trace_id"}`; malformed JSON or a missing field returns 400. Uses `build_resolver` so
      the configured backend applies here too.
- [x] **Criterion 4 tested at both boundaries**: `--message` vs `--batch` and `--message` vs the HTTP
      endpoint each produce records equal field by field (`prev_hash` excluded — it legitimately differs
      between two separate files) with identical `trace_id`. A separate test proves a run with no
      `--config` and one with an explicit `backend = "fake"` produce the same `trace_id` (advisor's check:
      §14.2 put `backend`/`model_version` inside the hashed record).

### §14.5 — V2 acceptance criteria
1. **Installs via pip into a clean environment and runs the demo from the README alone — MET.** Built a
   fresh venv, did a *non-editable* `pip install` from a copy of the source tree (so packaging metadata,
   not the working tree, is what's tested), ran the README demo commands verbatim (three verdicts:
   `violation_upstream_leak`, `clean`, `violation_disclosure`), then `screen --batch`, then real
   `embargo review` and `embargo serve` processes driven over HTTP.
2. **Two backends run the eval, selected by config, no code change — PARTIAL, by explicit user decision.**
   Selection is real and tested end to end (`embargo --config fake.toml eval` succeeds; the same command
   with `hosted.toml` raises), but only `fake` makes a working call. `hosted`/`self_hosted` raise
   `NotImplementedError` because no API key or local model server exists in this environment. Not claimed
   as met anywhere, including the README. To close it: implement a real `model_call` for one backend in
   `embargo/backends.py` (the `Resolver` Protocol, trace fields, config, and eval plumbing are already in
   place) and run `embargo eval` under it.
3. **Reviewer UI shows the complete evidence chain and records actions to the trace chain — MET.**
   Verified in the clean-venv run above against real processes: highlighted span, checks, fact timeline,
   backend/model, authorization lookup all present on the page; a POSTed dismissal appeared on the page,
   was appended as a `reviewer_action` record, and `embargo trace verify` reported `chain intact`
   afterward; `embargo rescreen` then ran without crashing.
4. **Batch and single-message screening produce byte-identical traces — MET** (see §14.4; also holds for
   the HTTP endpoint).

**V2 full suite: 245 tests, all passing** (237 at the V2 commit, +8 for queue status).

### Known gaps and follow-ups (not blocking, stated so they aren't lost)
- Criterion 2's live backend (above).
- `hosted`/`self_hosted` report `model_version = "unconfigured"`; a real backend should report the model id.
- The reviewer UI and `embargo serve` have no authentication and bind to `127.0.0.1` by default. The spec
  calls the UI "a local web UI" and defines no credential model, so none was invented; exposing either
  beyond localhost is a deployment prerequisite that needs auth first.
- Migrations cover the one real schema change so far (`valid_from`); there is no general version table.
  The next schema change should add one rather than another ad-hoc column check.
- `write_trace` reads the last line and appends without a cross-process lock, so two writers appending to
  the same trace file at the same instant could both chain to the same predecessor (which `trace verify`
  would report as a break). Not in the spec; a single `embargo serve` process handles requests serially.
  Worth a lock if several processes ever share one trace file.
- The installed package exposes a top-level `eval` package (spec §5's layout puts `eval/` at the repo
  root, and `embargo eval` imports it). A future rename to `embargo.evaluation` would avoid that name in
  site-packages, at the cost of departing from the spec's layout.
- Not published to PyPI (needs the owner's PyPI account); the README says `pip install .` from a clone.
  The wheel does not bundle `corpus/` or `eval/fixtures/`, so `embargo eval` runs from a clone.
- **Resolved after V2 landed:** reviewer actions now drive queue status. A confirmed or dismissed finding
  leaves the default queue (`/?all=1` shows it), escalated stays open, and the scope is the *trace*, not the
  message — a re-screen writes a new trace_id and that finding returns as open. Tested including the
  dismiss → re-screen → reappears case.

## Open questions (spec §12)
Unresolved, flag to the user if implementation forces a choice — do not decide unilaterally:
- Materiality assessment: how much can be model-assisted
- Digestion window: fixed policy vs. per-event
- Number of materiality levels and who may change them post-intake

## Known follow-up — RESOLVED during §13.1
- ~~If a resolver ever returns a `fact_id` that wasn't among the candidates it was given...~~ Fixed:
  `resolver._validate_resolutions()` now rejects (and logs) any resolution whose `fact_id` isn't among the
  candidates passed to `resolve()`, the same way it already rejected a non-verbatim `span`. This turned out
  not to be optional — §13.1's own re-screening scenario hits exactly this path (a fact not yet in the
  ledger has zero real candidates, but a fixture/model may still name it), so the guard became a prerequisite
  rather than a deferred nice-to-have.

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
- 2026-09-18 — §13.1 (re-screening) built via TDD and committed (`048cfd2`, 126 tests). User then said
  "complete coding first then we will commit and push together" — workflow changed from per-section
  commit/push to one combined commit+push at the end of all V1 coding.
- 2026-09-18 — Consulted advisor before §13.2–§13.5: confirmed the threshold-dependent precision/recall
  reinterpretation for calibration, the budget/tie-break semantics, the stdlib bag-of-words stand-in for
  "embedding-based retrieval" (named honestly, not as "embedding"), the hash-chain design (canonical
  serialization + raw-line hashing + `newline=""` to dodge a CRLF false-tamper trap), and the requirement
  that the adversarial corpus's fixtures encode real, reasoned mistakes rather than a hand-tuned 1.000.
- 2026-09-18 — `eval/calibrate.py` built via TDD (9 tests): threshold sweep, `best_threshold_for_budget()`,
  `embargo calibrate [--budget]`. Verified monotonicity (recall non-increasing, review_share non-decreasing)
  on both a hand-verifiable synthetic corpus and the real V0 corpus. **136 tests passing.**
- 2026-09-18 — Adversarial corpus built (6 facts, 8 messages, all six required categories) with deliberately
  imperfect fixtures; `embargo eval --adversarial` added. Hand-computed expected metrics (precision/recall
  0.333, accuracy 0.750) matched the actual `run_eval()` output on the first run. **142 tests passing.**
- 2026-09-18 — Hash chain added to `trace.py` (`write_trace` now stores `prev_hash`; new `verify_chain()`),
  `embargo trace verify` wired into the CLI. One pre-existing round-trip test updated for the new field (a
  real behavior change). Full suite re-run immediately after, before starting §13.5, per the advisor's
  sequencing note. **150 tests passing.**
- 2026-09-18 — Semantic prefilter (`similarity_candidates()`) added via TDD, RED-first (had to revert one
  premature implementation attempt written before its test — caught by re-reading the TDD skill's Iron Law —
  and redo it test-first). Verified against the real corpus that it adds zero new candidates on V0 and only
  two (already `entity_match`ed) on the adversarial corpus, so the "tuning trap" the advisor warned about
  did not materialize. Five existing tests' exact `reasons` assertions updated to include `semantic_match`
  where short-text cosine similarity genuinely (if narrowly) crosses the 0.3 threshold. `EvalReport` gained
  `prefilter_recall`, computed purely from prefilter output. **157 tests passing.**
- 2026-09-18 — Consulted advisor before declaring V1 coding complete; it caught a real bug:
  `best_threshold_for_budget` always returns the smallest threshold in the sweep for any non-negative
  budget, because `resolver_recall(t)` is monotone non-increasing in `t` (TP(t) only shrinks as the gate
  tightens) and `review_share(0.0)` is always `0.0` — confirmed both mathematically and empirically
  (`--budget 0.0/0.05/0.3/0.9` all recommended `0.00`). This isn't a coding mistake so much as the metric
  definition making the "budget" never bind; spec's own line ("make the tradeoff explicit... rather than
  picking a threshold silently") means the report has to say so rather than print one number that looks
  authoritative. Fixed by adding `best_threshold_for_accuracy()` (verdict accuracy is *not* monotone in
  threshold, since it reflects the decision layer's authorization checks too) and an explicit note in
  `format_calibration_report()`. Also fixed two test files that relied on the ambient cwd being the repo
  root (`monkeypatch.chdir` / `Path(__file__).parent.parent`, matching the existing `test_corpus_eval.py`
  pattern) and one contradictory STATUS.md sentence. **V1 coding complete: 159 tests passing.**
- 2026-09-18 — Committed V1 §13.2–§13.5 as `bff4fcf` (no co-author trailer, per standing instruction) and
  attempted `git push`; it hung again on the same credential-manager prompt from V0 (confirmed with a
  15s-timeout guard: exit 124). 5 commits now queued locally, unpushed.
- 2026-09-18 — User: "lets start with v2." Consulted advisor before coding: confirmed build order
  (14.1→14.2→14.3→14.4) and flagged two decisions as the user's to make, not the advisor's or mine —
  answered via AskUserQuestion (see the two bullets under "Current tier" above). Advisor also flagged the
  push was left unresolved when the user moved on; noted to the user in one line rather than blocking on it.
- 2026-09-18 — §14.1 built via TDD: `migrations.py` (tested against a hand-built genuinely V0-shaped
  database), `config.py` (TOML via stdlib `tomllib`), threshold de-duplication across
  `decision.py`/`rescreen.py`/`run_eval.py` onto `embargo.config.DEFAULT_THRESHOLD`, `--config` CLI
  integration with explicit-flag > config > default precedence, `pyproject.toml`, `README.md`. Verified
  acceptance criterion 1 for real: fresh venv, `pip install -e .`, ran the README demo verbatim end to end.
  That run caught a real bug (`ledger add` crashing in a clean directory on its default `--fixtures` path
  even with no trace file to rescreen) that no existing test had caught, because every existing test
  happened to run from the repo root where the default fixtures file exists. Fixed with a regression test
  using `monkeypatch.chdir` to a genuinely empty directory. **173 tests passing.**
- 2026-09-18 — §14.2 built via TDD (`backends.py` registry, `backend`/`model_version` in every trace,
  `eval`/`calibrate` accept a resolver). Advisor then flagged that §14.2 made criterion 4 a live risk
  (`backend`/`model_version` feed the hashed `trace_id`) and that reviewer actions in the same trace file
  would crash `rescreen`. Wrote the no-config vs `backend = "fake"` `trace_id` equality test first
  (passes), then reproduced the `rescreen` `KeyError`, then fixed it via a `record_type` discriminator.
- 2026-09-18 — §14.3 reviewer logic (`reviewer.py`) and server (`reviewer_server.py`), §14.4 batch mode,
  `pipeline.screen_and_write` extraction, and `screen_server.py`. **222 tests, then 227.** Session
  context was compacted here with the reviewer UI's evidence chain and `embargo serve` unfinished.
- 2026-09-19 — Picked back up at "what is left." Finished: `trace show` crash on reviewer actions
  (reproduced first), the reviewer UI's missing evidence-chain pieces (span highlight, per-check inputs and
  results, fact timeline, model provenance, real trace viewer; 7 tests red first), `embargo serve`, and
  the docs (README, CLAUDE.md, this file). Verified V2 end to end in a clean non-editable venv against real
  `review`/`serve` processes. **237 tests passing.** Criterion 2 remains partial by user decision.
- 2026-09-20 — "Complete everything except the API and model." Scoped against the spec and STATUS follow-ups
  rather than by inventing features: fixed the README install line (`embargo-screen` is not on PyPI, so
  `pip install .`), corrected the stale push/uncommitted claims in this file, and made reviewer actions drive
  queue status (8 tests red first, including the dismiss → re-screen → reappears case that decides whether a
  dismissal is scoped to a trace or a message; trace-scoped, since a re-screen recomputes the verdict).
  Re-verified against a real `embargo review` process. **245 tests passing.** Deliberately *not* built, and
  recorded under Known gaps instead: reviewer-UI authentication (spec defines no credential model), a
  general migrations version table (one schema change so far), cross-process trace locking, PyPI publishing
  (needs the owner's account), and a live backend / model id (the excluded API-and-model work).
