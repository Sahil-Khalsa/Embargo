# embargo

MNPI (material non-public information) screening with a deterministic decision layer and
model-assisted fact resolution.

The core design decision: MNPI is a property of a *fact* and *when it was said to whom*, not a
property of message text. Embargo never asks a model "is this a violation" — it asks only "which
known facts does this message convey," and a deterministic decision layer does the rest.

```
message -> prefilter (deterministic) -> resolver (model) -> gate (deterministic) -> decision (pure) -> trace
```

## Install

From a clone of this repository:

```
pip install .
```

(Or `pip install -e .` for development.) The distribution name is `embargo-screen`, but it is not
published to PyPI, so `pip install embargo-screen` will not work yet; the import package and the
command are both `embargo`.

Requires Python 3.11+. The only runtime dependency is PyYAML (used to read the corpus/config file
formats).

## Demo

This is the reason to build this at all: **the same message, screened at different timestamps and
against different recipients, produces different correct verdicts.** Run these commands from the
root of a clone of this repository (or any directory — adjust the `--db`/file paths as needed).

Set up a fact and an access graph:

```
embargo ledger add --id F001 --summary "Acme is being acquired by Beta" \
  --entities Acme --recorded-at 2026-01-01T00:00:00 --materiality high --db demo.db

embargo ledger transition F001 announced --announced-at 2026-01-02T00:00:00 --db demo.db

embargo cross add --party alice --fact F001 --effective-from 2026-03-01T00:00:00 --db demo.db
embargo cross add --party bob   --fact F001 --effective-from 2026-01-01T00:00:00 --db demo.db
embargo cross add --party carol --fact F001 --effective-from 2026-01-01T00:00:00 --db demo.db
```

`alice` (the sender below) is only wall-crossed starting 2026-03-01. `bob` and `carol` are crossed
from day one. `dave` is never crossed.

Write one message and a fixture standing in for the model's resolution of it:

```
cat > demo_messages.yaml << 'EOF'
- message_id: M001
  sender: alice
  recipients: ["bob"]
  timestamp: "2026-06-01T00:00:00"
  body: "ACME news"
EOF

cat > demo_fixtures.json << 'EOF'
{"M001": [{"fact_id": "F001", "mode": "conveys", "confidence": 0.9, "span": "ACME news"}]}
EOF
```

Now screen the *same message* three different ways:

```
# 1. As of before alice was ever crossed -- an unauthorized sender is a
#    stronger finding than an unauthorized recipient (checked first).
embargo screen --message M001 --as-of 2026-02-01T00:00:00 \
  --db demo.db --messages demo_messages.yaml --fixtures demo_fixtures.json
# -> violation_upstream_leak

# 2. As of after alice is crossed, recipient overridden to carol (also crossed).
embargo screen --message M001 --as-of 2026-06-01T00:00:00 --recipients carol \
  --db demo.db --messages demo_messages.yaml --fixtures demo_fixtures.json
# -> clean

# 3. As of after alice is crossed, recipient overridden to dave (never crossed).
embargo screen --message M001 --as-of 2026-06-01T00:00:00 --recipients dave \
  --db demo.db --messages demo_messages.yaml --fixtures demo_fixtures.json
# -> violation_disclosure
```

Three screenings of the identical message text, three different — and each individually correct —
verdicts, depending only on what the ledger and access graph knew at the time asked about. Every
screening also appends a full audit record; inspect it with:

```
embargo trace show M001 --trace-file traces/trace.jsonl
embargo trace verify --trace-file traces/trace.jsonl
```

Run the full evaluation corpus (30 messages with expected verdicts, shipped in this repo):

```
embargo eval
embargo eval --adversarial   # a second, deliberately harder corpus, reported separately
embargo calibrate --budget 0.2
```

## Batch and service mode

Bulk-screen every message in a file and get a summary:

```
embargo screen --batch demo_messages.yaml --db demo.db --fixtures demo_fixtures.json
# screened 1 message(s):
#   clean: 1
```

Or run a small HTTP endpoint that accepts one message and returns a verdict and trace id, for
wiring into a message pipeline:

```
embargo serve --db demo.db --fixtures demo_fixtures.json --port 8001

curl -X POST http://127.0.0.1:8001/screen -d '{"message_id": "M001", "sender": "alice",
  "recipients": ["bob"], "timestamp": "2026-06-01T00:00:00", "body": "ACME news"}'
# {"verdict": "clean", "trace_id": "..."}
```

`screen --message`, `screen --batch`, and the endpoint all go through the same function
(`embargo.pipeline.screen_and_write`), so the same input produces the same trace from any of them.
This is tested, not just intended: the traces are compared field by field.

## Reviewer UI

```
embargo review --db demo.db --trace-file traces/trace.jsonl   # http://127.0.0.1:8000/
```

A local web UI for the people who work the queue (standard library only, no framework):

- **Queue** of `review` and violation verdicts, most severe first, each with a status (open,
  escalated, confirmed, dismissed). Confirmed and dismissed findings leave the default view
  (`/?all=1` shows them). A dismissal applies to that one trace, not the message: if a re-screen
  recomputes the verdict, the new finding comes back as open.
- **Per finding, the full evidence chain**: the message with the resolved span highlighted; what
  surfaced each candidate fact; the resolver's output (mode, confidence, span) next to its
  backend and model version; every deterministic check in the order it runs, with its inputs and
  result; each fact's state, timeline, and materiality series; and the authorization lookup for
  every party. A reviewer can tell a model error from a ledger fact without reading code.
- **Actions**: confirm, dismiss (with a reason), escalate. Each one is appended to the same
  hash-chained trace file as the screenings. Nothing is overwritten, and `embargo trace verify`
  still passes afterward.
- **Trace viewer**: a read-only listing of every record with the chain verification status.

## Configuration

Rather than hardcoding values, `embargo` reads an optional TOML config file (`--config path.toml`
before the subcommand, e.g. `embargo --config embargo.toml screen ...`). CLI flags always override
the config file, which in turn overrides built-in defaults:

```toml
threshold = 0.6            # gate confidence threshold
digestion_window_days = 30 # currently unused -- see below
backend = "fake"           # "fake" | "hosted" | "self_hosted" -- see Model backends
db_path = "embargo.db"
```

`digestion_window_days` is read but not yet applied anywhere: whether the digestion window
(announced -> cleared) is one fixed policy or set per event is an explicit open question (spec
§12) this project has not decided unilaterally. The field exists so that decision has somewhere to
live once someone does.

Existing databases upgrade in place: opening a database created before V1 adds the missing
`valid_from` column and backfills it, rather than requiring a rebuild.

## Model backends

The resolver sits behind one interface, and `backend` in the config file selects the
implementation for `screen`, `serve`, `rescreen`, `eval`, and `calibrate`, with no code change.
Every trace records which backend and model version produced its resolutions.

**Status, stated plainly:** only `fake` (fixtures, no network) makes a working call in this
build. `hosted` and `self_hosted` are selectable and correctly labeled in the trace, but
their model call raises `NotImplementedError`, because no API key or local model server was
available to wire them to. The selection machinery is real and tested; a live model call is
the missing piece, and it is the one part of V2's "two backends run the eval" criterion that
is not met. Selecting an unwired backend fails loudly rather than falling back to `fake`.

## Known limitations

These are design boundaries, not bugs. (Verbatim from the build spec, §11.)

- **Embargo cannot catch a leak about a fact that was never entered in the ledger.** If nobody logged the deal, there is nothing to resolve against. Covering that requires a separate discovery path — anomaly detection over communication patterns, or sampling for human review — which is a different system with different economics. It is out of scope at every tier here.
- Resolver false negatives on sufficiently oblique references.
- Resolver misjudging conveys vs. mentions.
- Ledger intake is a human bottleneck and a single point of failure. Messages sent before a fact was recorded were screened against an incomplete ledger. V1 detects these after the fact (§13.1); it does not remove the bottleneck.
- Access graph accuracy depends on wall-crossing being recorded at the time, not reconstructed after.
- The ledger is the most sensitive dataset the firm holds. Sending candidate facts to a model provider makes hosting and data residency first-order deployment constraints. V2 addresses this (§14.2).

## Development

```
pytest
```

Every test except the resolver's own runs against `FakeResolver` — no network access anywhere in
the suite. See `EMBARGO_SPEC.md` for the full build brief and `STATUS.md` for what's actually built
against it.
