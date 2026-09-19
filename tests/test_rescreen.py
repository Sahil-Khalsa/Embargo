from datetime import datetime

from embargo.models import Crossing, Fact, FactState, MaterialityLevel, Message
from embargo.resolver import FakeResolver
from embargo.rescreen import current_traces, rescreen_stale_traces
from embargo.trace import build_trace, write_trace
from embargo.decision import decide
from embargo.prefilter import candidate_facts


def _old_trace_record(**overrides):
    """A trace as if screened when F_ZYLO didn't exist in the ledger yet:
    zero candidates, zero resolutions, verdict clean by omission."""
    message = Message(
        message_id="M100", sender="alice", recipients=["bob"],
        timestamp=datetime(2026, 6, 1), body="Heads up on the Zylo situation.",
    )
    decision = decide(message, [], {}, [])
    record = build_trace(message, [], [], decision, ledger_version=0)
    record.update(overrides)
    return record


def test_current_traces_excludes_superseded_records():
    original = _old_trace_record()
    superseding = dict(original)
    superseding["trace_id"] = "new-id"
    superseding["supersedes"] = original["trace_id"]
    unrelated = dict(original)
    unrelated["trace_id"] = "unrelated-id"
    unrelated["message_id"] = "M999"
    unrelated["supersedes"] = None

    result = current_traces([original, superseding, unrelated])

    assert {r["trace_id"] for r in result} == {"new-id", "unrelated-id"}


def test_rescreen_stale_traces_writes_superseding_trace_with_changed_verdict(tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    old_record = _old_trace_record()
    write_trace(trace_path, old_record)

    # Now F_ZYLO has been entered: recipient bob is not authorized.
    fact = Fact(
        fact_id="F_ZYLO", summary="Zylo situation", entities=["Zylo"], aliases=[],
        state=FactState.ANNOUNCED, recorded_at=datetime(2026, 7, 1),
        announced_at=datetime(2026, 1, 1),
        materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
        valid_from=datetime(2026, 1, 1),
    )
    crossings = [Crossing(party_id="alice", fact_id="F_ZYLO", effective_from=datetime(2026, 1, 1))]
    resolver = FakeResolver({
        "M100": [{"fact_id": "F_ZYLO", "mode": "conveys", "confidence": 0.9, "span": "Zylo situation"}]
    })

    changes = rescreen_stale_traces(
        trace_path, [fact], crossings, resolver,
        max_version=1, current_version=1,
    )

    assert len(changes) == 1
    assert changes[0].message_id == "M100"
    assert changes[0].old_verdict == "clean"
    assert changes[0].new_verdict == "violation_disclosure"

    from embargo.trace import read_traces
    records = read_traces(trace_path, message_id="M100")
    assert len(records) == 2
    assert records[1]["supersedes"] == old_record["trace_id"]
    assert records[1]["verdict"] == "violation_disclosure"
    assert records[1]["ledger_version"] == 1


def test_rescreen_stale_traces_skips_traces_at_or_above_max_version(tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    write_trace(trace_path, _old_trace_record(ledger_version=5))

    changes = rescreen_stale_traces(trace_path, [], [], FakeResolver({}), max_version=5, current_version=5)

    assert changes == []
    from embargo.trace import read_traces
    assert len(read_traces(trace_path)) == 1  # nothing new written


def test_rescreen_stale_traces_respects_timestamp_from_filter(tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    write_trace(trace_path, _old_trace_record())  # message timestamp 2026-06-01

    changes = rescreen_stale_traces(
        trace_path, [], [], FakeResolver({}),
        max_version=1, current_version=1, timestamp_from=datetime(2026, 7, 1),
    )

    assert changes == []
    from embargo.trace import read_traces
    assert len(read_traces(trace_path)) == 1


def test_rescreen_stale_traces_writes_trace_even_when_verdict_unchanged(tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    old_record = _old_trace_record()
    write_trace(trace_path, old_record)

    # No fact ever surfaces "Zylo" as a candidate -- verdict stays clean.
    changes = rescreen_stale_traces(trace_path, [], [], FakeResolver({}), max_version=1, current_version=1)

    assert changes == []  # nothing to report
    from embargo.trace import read_traces
    records = read_traces(trace_path, message_id="M100")
    assert len(records) == 2  # but a superseding trace was still written
    assert records[1]["supersedes"] == old_record["trace_id"]
    assert records[1]["verdict"] == "clean"
