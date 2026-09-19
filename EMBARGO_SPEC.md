# Embargo — Implementation Spec

A screening layer for material non-public information (MNPI), built on information state rather than message content.

The name is the thesis: a fact is under embargo until its release time. What a message says matters far less than whether the facts it conveys had been released yet, and to whom.

This file is the build brief. It is self-contained: everything needed to implement the system is here. Where it says MUST, treat it as a hard requirement — several of these are the whole point of the design. Where it says SHOULD, deviate if there's a good reason and note the reason in the code.

**Scope of this build:** V0 is the milestone that must land, and it stands alone as a working system. V1 and V2 are in scope too, and are specified here in enough detail to build. Work them in order — V0 complete and passing its acceptance criteria (§9) before V1 starts, V1 before V2 — but treat the whole document as the target, not just §1–9.

---

## 1. The core idea, and why the design looks like this

MNPI is not a property of a message. It is a property of a **fact**, and it changes over time. "Acme is acquiring Beta" is MNPI before the press release and ordinary news once the release has been absorbed by the market. The identical sentence is a violation or a nothing depending on *when* it was sent and *who* sent and received it.

So Embargo does not classify messages as violations. It maintains a ledger of facts and screens a message by asking which facts the message conveys. The model answers that one question. Deterministic logic decides everything else.

Two consequences that MUST hold at every tier:

1. **The model's output never contains a verdict.** It returns fact IDs, a conveys/mentions mode, a confidence, and a text span. Nothing else. The decision layer never reads model prose.
2. **The decision layer is pure and testable without a model.** Given resolutions plus ledger state, the verdict is a deterministic function. It MUST be unit-testable with no network access.

---

## 2. Stack

- Python 3.11+
- SQLite via stdlib `sqlite3` for the ledger and access graph
- Model access behind a single interface with a fake implementation for tests (§7)
- `pytest` for tests
- Stdlib `argparse` for the CLI
- Dependencies kept minimal; no framework

Top-level package is `embargo`. The CLI command is `embargo`. Note the PyPI name `embargo` is already taken by an unrelated, unmaintained project, so the distribution name is `embargo-screen` (§14.1) — this affects packaging only, not imports or the command.

---

## 3. Data model

### 3.1 Fact

The system of record. A fact is a discrete piece of information that may or may not be public.

| Field | Type | Notes |
|---|---|---|
| `fact_id` | str | Primary key |
| `summary` | str | Human-readable, for traces and the resolver prompt |
| `entities` | list[str] | Canonical tickers or names this fact concerns |
| `aliases` | list[str] | Codenames and internal names, e.g. "Project Falcon". Used by the prefilter. |
| `state` | enum | `private`, `announced`, `cleared`, `abandoned` |
| `announced_at` | datetime \| null | Filing, press release, or earnings call time |
| `cleared_at` | datetime \| null | `announced_at` + digestion window |
| `recorded_at` | datetime | When the ledger learned about this fact |
| `materiality` | list[(datetime, level)] | Level in effect from each timestamp. Level is `high`, `medium`, `low`, or `none`. |

**State machine.** Allowed transitions, and nothing else:

```
private   -> announced    (requires announced_at set)
private   -> abandoned
announced -> cleared      (requires cleared_at set, and now >= cleared_at)
abandoned -> cleared      (manual compliance action only; see below)
```

`abandoned` means the event never happened and was never announced. An abandoned fact stays non-public indefinitely — the embargo never lifts on its own. The only exit is an explicit compliance action. Implement that as an explicit method, not as a scheduled job.

**Materiality is a time series, not a scalar.** A deal in early talks is less material than a signed one. Store `(effective_from, level)` entries and look up the level in effect at the message timestamp. Do not re-assess materiality per message; it is set at the fact level and updated as the fact develops.

**`recorded_at` vs. the fact's real start.** Ledger intake lags reality, so a message may have been screened against a ledger that did not yet contain the fact. V0 only stores `recorded_at`; V1 uses it to re-screen (§13.1). Storing it from the start avoids a migration.

### 3.2 Access graph

Who has been wall-crossed onto which fact, and when.

| Field | Type | Notes |
|---|---|---|
| `party_id` | str | Person or address |
| `fact_id` | str | |
| `effective_from` | datetime | |
| `effective_until` | datetime \| null | Null means open-ended |

A party is authorized on a fact at time T if an entry exists with `effective_from <= T` and (`effective_until` is null or `T < effective_until`).

**Crossing is not transitive.** If an authorized person tells someone who hasn't been crossed, that is the violation the system exists to catch, not a new authorization. Do not implement any inference that grants authorization.

### 3.3 Message

| Field | Type |
|---|---|
| `message_id` | str |
| `sender` | str (party_id) |
| `recipients` | list[str] (party_id) |
| `timestamp` | datetime |
| `body` | str |

### 3.4 Resolution — the only thing the model returns

```json
{"fact_id": "F047", "mode": "conveys", "confidence": 0.82, "span": "the thing from the other day"}
```

- `mode` is `conveys` or `mentions`. `mentions` means the message names an entity or topic the fact concerns but does not communicate the fact itself.
- `span` is the exact substring of the message body that triggered the resolution. It MUST appear verbatim in the body; reject and log a resolution where it does not.

---

## 4. Pipeline

```
message
  -> prefilter   (deterministic)  -> candidate facts
  -> resolver    (model)          -> resolutions
  -> gate        (deterministic)  -> resolutions that proceed
  -> decision    (deterministic)  -> verdict
  -> trace       (deterministic)  -> record
```

### 4.1 Prefilter — deterministic

Selects the candidate facts the resolver sees. Union of:

1. Facts where any `entity` or `alias` appears in the message body (case-insensitive, word-boundary match)
2. Facts that **any party to the message** (sender or any recipient) is wall-crossed onto at the message timestamp

Set 2 is essential: it's what lets an oblique reference between two deal-team members reach the resolver with no keyword hit. Without it the euphemism cases fail.

Do not send the full ledger to the model. Aside from scale, the prompt would contain the firm's most sensitive data.

### 4.2 Resolver — the model's only job

Prompt: the message plus the candidate facts (id, summary, entities, aliases). Ask which facts the message conveys, and for each whether it conveys or merely mentions.

Constraints:
- Output MUST be JSON matching §3.4. Validate it. On invalid output, retry once, then emit a `review` verdict with reason `resolver_output_invalid`.
- The prompt MUST NOT ask about materiality, seriousness, or whether something is a violation. Materiality is settled at the fact level; a verdict is not the model's job.
- Never pass a fact's `state`, `announced_at`, or `cleared_at` to the model. Those belong to the decision layer, and including them invites the model to pre-judge.

### 4.3 Gate — deterministic

| Resolution | Action |
|---|---|
| `mode: conveys`, confidence >= threshold | Proceeds to decision |
| `mode: conveys`, confidence < threshold | Verdict `review`, reason `low_confidence` |
| `mode: mentions` | Logged in the trace, does not proceed |

Threshold default 0.6, configurable. This is the **only** threshold in the system. It decides what reaches the decision step, never what the verdict is.

Low-confidence resolutions go to human review — they are never silently dropped.

### 4.4 Decision — pure logic

For each resolution that proceeds, against fact F and message M:

```
1. is_cleared(F, M.timestamp):
     F.state == "cleared" and F.cleared_at is not None and M.timestamp >= F.cleared_at
     (abandoned is never cleared)
   -> if cleared: CLEAN

2. materiality_at(F, M.timestamp) == "none"
   -> if so: CLEAN

3. authorized(M.sender, F, M.timestamp) is False
   -> VIOLATION_UPSTREAM_LEAK

4. any recipient r where authorized(r, F, M.timestamp) is False
   -> VIOLATION_DISCLOSURE

5. otherwise: CLEAN
```

Check the sender before the recipients. An unauthorized sender is the stronger finding: the fact escaped the wall before this message was written.

Note step 1 compares against `cleared_at`, not `announced_at`. The window between announcement and market absorption is still under embargo.

**Message-level verdict** when a message resolves to several facts: the most severe across all resolutions, by

```
violation_upstream_leak > violation_disclosure > review > clean
```

The per-fact verdicts MUST all be retained in the trace.

### 4.5 Trace

One record per screened message. MUST contain enough to reconstruct the decision without re-running anything:

- message id, timestamp, sender, recipients
- candidate fact ids and why each was a candidate (entity match, alias match, or party authorization)
- every resolution returned, including `mentions` and below-threshold ones
- per-fact: each check that ran and its inputs (fact state, `cleared_at`, materiality level in effect, authorization lookup per party) and result
- per-fact verdict and message-level verdict
- `ledger_version` — see §13.1; V0 may write a placeholder, but the field MUST exist from the start

The target is an auditor sentence: *this message conveyed this fact, which was under embargo until this date, and this party was not authorized as of that date.*

Write traces as one JSON object per line (JSONL).

---

## 5. Module layout

```
embargo/
  models.py       # dataclasses: Fact, Crossing, Message, Resolution, Verdict
  ledger.py       # SQLite store, state transitions, materiality_at()
  access.py       # access graph, authorized()
  prefilter.py    # candidate selection
  resolver.py     # ModelResolver + FakeResolver behind one Protocol
  decision.py     # pure verdict logic, no I/O
  trace.py        # trace record construction and JSONL writer
  cli.py
corpus/
  facts.yaml
  crossings.yaml
  messages.yaml   # each with expected_verdict and expected_fact_ids
eval/
  run_eval.py
  fixtures/       # recorded resolver outputs, for running eval without a live model
tests/
```

`decision.py` MUST NOT import `resolver.py`. It takes resolutions as plain data.

V1 and V2 add to this layout; see §13 and §14.

---

## 6. CLI

```
embargo screen --message <id> [--as-of <ts>] [--recipients <a,b>]
embargo ledger add|list|show|transition
embargo cross add|list
embargo eval [--fixtures]
embargo trace show <message_id>
```

`screen` MUST support `--as-of` and `--recipients` overrides. They are what make the demo (§9) a single command run three times.

---

## 7. Resolver interface

```python
class Resolver(Protocol):
    def resolve(self, message: Message, candidates: list[Fact]) -> list[Resolution]: ...
```

Two implementations:
- `ModelResolver` — real model call
- `FakeResolver` — returns resolutions from a fixture file keyed by message id

Every test other than the resolver's own MUST run against `FakeResolver`, with no network access. The eval harness MUST support both a live run and a fixture run.

Keep this Protocol stable. V2 adds backends behind it (§14.2) and MUST NOT change its shape.

---

## 8. Corpus and eval

30–40 handwritten messages with expected verdicts and expected fact ids.

**Order of work matters here.** Write the corpus and expected verdicts *first*, commit them, and do not edit them once the resolver prompt is being written. A corpus authored alongside the prompt scores near-perfect and tells you nothing.

### 8.1 Required hard cases

| Case | Expected |
|---|---|
| Public info about a name still on a restricted list | clean |
| Fact referenced via euphemism, no entity named | violation (resolver test) |
| Chatty message naming a restricted entity, disclosing nothing | clean, via `mentions` |
| Same fact referenced before and after `cleared_at` | violation, then clean |
| Recipient wall-crossed *after* the message was sent | violation |
| One message referencing two facts in different states | most severe wins |
| Abandoned deal referenced after it fell through | violation if any party uncrossed |
| Sender not wall-crossed | violation_upstream_leak |
| Fact conveyed after `announced_at` but before `cleared_at` | violation if any party uncrossed |

### 8.2 Metrics — report separately

1. **Resolver precision and recall** against expected fact ids, with conveys/mentions confusion counted separately
2. **End-to-end verdict accuracy**, with a confusion matrix over the four verdicts

Reporting these separately is what makes the architecture pay off: the decision layer is deterministic, so every end-to-end error traces to either the resolver or the ledger. Do not collapse them into one accuracy number.

---

## 9. V0 — acceptance criteria

The demo, and the reason to build this at all: the *same message* screened at different timestamps and against different recipients, producing different correct verdicts. One screen of output.

V0 is done when:

1. `embargo screen` on one message with three different `--as-of` / `--recipients` combinations yields three different correct verdicts
2. All nine hard cases in §8.1 pass
3. `decision.py` has full unit test coverage with no model in the loop
4. Every screened message produces a trace that reconstructs its decision
5. The eval runs from fixtures with no network access

Do not start V1 until all five hold.

---

## 10. Build order

| Tier | Contains | Gate to proceed |
|---|---|---|
| V0 | §1–9 | The five criteria in §9 |
| V1 | §13 | The criteria in §13.6 |
| V2 | §14 | The criteria in §14.5 |

Within a tier, build in the order the sections are written. Do not pull a V1 or V2 feature forward into V0 even if it looks easy — the V0 acceptance criteria are what prove the architecture, and every added moving part makes a failure harder to attribute.

The one exception is schema. Fields that later tiers need are specified in V0 (`recorded_at`, `ledger_version` in the trace) precisely so no migration is needed later. Include them from the start, unused.

---

## 11. Known limitations, to be stated in the README

These are design boundaries, not bugs. Naming them reads as competence.

- **Embargo cannot catch a leak about a fact that was never entered in the ledger.** If nobody logged the deal, there is nothing to resolve against. Covering that requires a separate discovery path — anomaly detection over communication patterns, or sampling for human review — which is a different system with different economics. It is out of scope at every tier here.
- Resolver false negatives on sufficiently oblique references.
- Resolver misjudging conveys vs. mentions.
- Ledger intake is a human bottleneck and a single point of failure. Messages sent before a fact was recorded were screened against an incomplete ledger. V1 detects these after the fact (§13.1); it does not remove the bottleneck.
- Access graph accuracy depends on wall-crossing being recorded at the time, not reconstructed after.
- The ledger is the most sensitive dataset the firm holds. Sending candidate facts to a model provider makes hosting and data residency first-order deployment constraints. V2 addresses this (§14.2).

---

## 12. Open questions — do not decide these unilaterally

Flag them if the implementation forces a choice.

- How much of materiality assessment can be model-assisted without recreating the problem this design avoids?
- Digestion window: one fixed policy, or set per event?
- How many materiality levels, and who may change them after intake?

Already settled, do not relitigate:
- Low-confidence resolutions route to human review, never dropped.
- Wall-crossing is not transitive.
- The model never emits a verdict.

---

## 13. V1

V1 makes the system honest about time and about its own accuracy. Everything here assumes V0 is passing.

### 13.1 Re-screening when a fact is recorded late

The problem `recorded_at` exists for. A message screened before the ledger knew about a fact was cleared against an incomplete ledger, and that clean verdict is not trustworthy.

Implement:
- `ledger_version` — a monotonic counter incremented on every ledger or access-graph write. Every trace records the version it was screened against.
- On a new fact entry, find every trace with `message.timestamp >= fact.valid_from` (add `valid_from` to Fact: when the fact became true in the world, distinct from `recorded_at`) that was screened at a version predating the entry, and re-screen those messages against the current ledger.
- A re-screen writes a **new** trace linked to the original by `supersedes`. Original traces are never mutated.
- `embargo rescreen --since <version>` and a report of verdicts that changed.

This is the difference between "was this a violation?" and "what did the system know at the time?" Both questions need answers, and they are not the same question.

### 13.2 Calibration tooling

Sweep the gate threshold from 0.0 to 1.0 over the eval corpus and report, at each point: resolver precision, resolver recall, share of messages routed to `review`, and end-to-end verdict accuracy.

Output a table and the threshold that maximizes recall subject to a review-volume budget. Recall matters more than precision here: a missed leak costs more than a message a human glances at. Make that tradeoff explicit in the report rather than picking a threshold silently.

`embargo calibrate [--budget <fraction>]`

### 13.3 Adversarial eval cases

A second corpus, held separate from the V0 one, built to break the resolver:

- Deliberate misdirection ("nothing going on with Acme, by the way")
- References split across a message thread, where no single message conveys the fact
- Entity names that collide with common words
- Aliases that appear innocently (a codename that is also a real place or product)
- Near-identical messages differing only in one qualifier, one conveying and one not
- A fact conveyed in a quoted reply chain rather than in the new text

Report V0-corpus and adversarial metrics separately. Never merge them into one number — the adversarial set is meant to look bad.

### 13.4 Tamper-evident trace store

Traces are the audit artifact, so they need to be provably unmodified.

- Append-only JSONL, with each record carrying the SHA-256 of the previous record (a hash chain)
- `embargo trace verify` walks the chain and reports the first break
- Re-screens append, never rewrite — consistent with §13.1

Full cryptographic notarization is out of scope. A hash chain plus append-only writes is the right weight here.

### 13.5 Semantic prefilter

Add embedding-based candidate retrieval alongside entity and alias matching. The union of all three becomes the candidate set.

Requirements:
- Entity and alias matching MUST remain. Embeddings supplement, never replace, the deterministic path.
- The trace records which mechanism surfaced each candidate.
- Report prefilter recall as its own metric: how often the correct fact reached the resolver at all. A prefilter miss is invisible in resolver metrics and looks like a clean verdict, which is the worst failure mode in the system.

### 13.6 V1 acceptance criteria

1. A fact entered after the fact re-screens affected messages and produces superseding traces with changed verdicts where appropriate
2. `embargo calibrate` produces a threshold sweep table
3. The adversarial corpus runs and reports separately from the V0 corpus
4. `embargo trace verify` detects a hand-edited trace record
5. Prefilter recall is reported as its own metric

---

## 14. V2

V2 makes it something someone else can install, run, and review findings in.

### 14.1 Packaging

- pip-installable, `pyproject.toml`, console entry point for `embargo`
- Distribution name `embargo-screen` on PyPI; the import package and CLI command stay `embargo`
- Config file rather than hardcoded values: threshold, digestion window, model backend, database path
- Ledger migrations, so a schema change doesn't require rebuilding the database
- README covering setup, the demo case, and §11 verbatim

### 14.2 Pluggable model backend

Multiple implementations behind the unchanged `Resolver` Protocol (§7): hosted API, self-hosted or local, and the fake.

Backend choice is config, not code. This is a deployment requirement, not a preference: a compliance buyer may be unable to send ledger contents to a third-party provider, and that question comes up early. The self-hosted path existing at all is what keeps the conversation going.

Record which backend and model version produced each resolution, in the trace.

### 14.3 Reviewer UI

A local web UI for the humans who work the queue.

- Queue of `review` and violation verdicts, sorted by severity
- Per finding, the full evidence chain: the message with the resolved span highlighted, the fact, its state and timeline, the authorization lookup for every party, and each check with its inputs and result
- Reviewer action: confirm, dismiss with reason, escalate. Actions append to the trace chain, never overwrite.
- A read-only trace viewer with chain verification status

The evidence chain is the point. A reviewer should be able to reconstruct the verdict without reading any code, and should be able to see when the model was the weak link rather than the ledger.

### 14.4 Batch and service mode

- `embargo screen --batch <file>` for bulk screening with a summary report
- Optional HTTP endpoint accepting one message and returning a verdict plus trace id, for wiring into a real message pipeline

Keep the same code path as the CLI. Divergence between batch and single screening is how audit inconsistencies get in.

### 14.5 V2 acceptance criteria

1. Installs via pip into a clean environment and runs the demo from the README alone
2. Two different model backends run the eval, selected by config with no code change
3. The reviewer UI shows the complete evidence chain for every finding and records reviewer actions to the trace chain
4. Batch mode and single-message screening produce byte-identical traces for the same input
