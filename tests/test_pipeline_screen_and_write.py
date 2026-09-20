"""screen_and_write() is the single code path every screening entry point
(CLI --message, --batch, the HTTP endpoint) must go through -- spec §14.4's
byte-identical-traces requirement depends on there being exactly one such
path, not several that happen to agree."""

from datetime import datetime

from embargo.models import Crossing, Fact, FactState, MaterialityLevel, Message, Verdict
from embargo.pipeline import screen_and_write
from embargo.resolver import FakeResolver
from embargo.trace import read_traces

FACT = Fact(
    fact_id="F047",
    summary="Acme is acquiring Beta",
    entities=["ACME"],
    aliases=[],
    state=FactState.ANNOUNCED,
    recorded_at=datetime(2026, 1, 1),
    materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
    announced_at=datetime(2026, 1, 1),
)


def _message():
    return Message(
        message_id="M001", sender="alice", recipients=["bob"],
        timestamp=datetime(2026, 6, 1), body="ACME news",
    )


def _resolver():
    return FakeResolver(
        {"M001": [{"fact_id": "F047", "mode": "conveys", "confidence": 0.9, "span": "ACME news"}]}
    )


def test_screen_and_write_writes_a_trace_record_and_returns_verdict(tmp_path):
    trace_path = tmp_path / "traces.jsonl"
    crossings = [
        Crossing(party_id="alice", fact_id="F047", effective_from=datetime(2026, 1, 1)),
        Crossing(party_id="bob", fact_id="F047", effective_from=datetime(2026, 1, 1)),
    ]

    record, verdict = screen_and_write(
        _message(), [FACT], crossings, _resolver(), threshold=0.6, trace_file=trace_path,
    )

    assert verdict == Verdict.CLEAN
    written = read_traces(trace_path, message_id="M001")
    assert len(written) == 1
    assert written[0]["trace_id"] == record["trace_id"]


def test_screen_and_write_creates_parent_directory(tmp_path):
    trace_path = tmp_path / "nested" / "dir" / "traces.jsonl"

    screen_and_write(_message(), [FACT], [], _resolver(), threshold=0.6, trace_file=trace_path)

    assert trace_path.exists()
