from datetime import datetime

from embargo.pipeline import screen_message
from embargo.models import Crossing, Fact, FactState, MaterialityLevel, Message, Verdict
from embargo.resolver import FakeResolver, ResolverOutputInvalid

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


def _message(sender="alice", recipients=("bob",), timestamp=datetime(2026, 6, 1)):
    return Message(
        message_id="M001",
        sender=sender,
        recipients=list(recipients),
        timestamp=timestamp,
        body="ACME news",
    )


def _resolver():
    return FakeResolver(
        {"M001": [{"fact_id": "F047", "mode": "conveys", "confidence": 0.9, "span": "ACME news"}]}
    )


def test_screen_message_returns_trace_record_and_verdict():
    crossings = [
        Crossing(party_id="alice", fact_id="F047", effective_from=datetime(2026, 1, 1)),
        Crossing(party_id="bob", fact_id="F047", effective_from=datetime(2026, 1, 1)),
    ]
    record, verdict = screen_message(_message(), [FACT], crossings, _resolver())

    assert verdict == Verdict.CLEAN
    assert record["verdict"] == "clean"
    assert record["message_id"] == "M001"


def test_screen_message_unauthorized_sender_is_violation_upstream_leak():
    crossings = [Crossing(party_id="bob", fact_id="F047", effective_from=datetime(2026, 1, 1))]
    record, verdict = screen_message(_message(), [FACT], crossings, _resolver())

    assert verdict == Verdict.VIOLATION_UPSTREAM_LEAK


def test_screen_message_records_as_of_and_recipients_overrides():
    crossings = [
        Crossing(party_id="alice", fact_id="F047", effective_from=datetime(2026, 1, 1)),
        Crossing(party_id="carol", fact_id="F047", effective_from=datetime(2026, 1, 1)),
    ]
    record, verdict = screen_message(
        _message(recipients=["carol"]),
        [FACT],
        crossings,
        _resolver(),
        as_of_override=datetime(2026, 7, 1),
        recipients_override=["carol"],
    )

    assert record["as_of_override"] == "2026-07-01T00:00:00"
    assert record["recipients_override"] == ["carol"]
    assert verdict == Verdict.CLEAN


def test_screen_message_resolver_failure_produces_review_trace():
    class RaisingResolver:
        def resolve(self, message, candidates):
            raise ResolverOutputInvalid(message.message_id)

    record, verdict = screen_message(_message(), [FACT], [], RaisingResolver())

    assert verdict == Verdict.REVIEW
    assert record["reason"] == "resolver_output_invalid"


def test_screen_message_records_ledger_version_and_supersedes():
    record, verdict = screen_message(
        _message(), [FACT], [], _resolver(), ledger_version=5, supersedes="abc123"
    )

    assert record["ledger_version"] == 5
    assert record["supersedes"] == "abc123"


def test_screen_message_no_candidates_is_clean():
    unrelated = Message(
        message_id="M002", sender="alice", recipients=["bob"],
        timestamp=datetime(2026, 6, 1), body="completely unrelated chatter",
    )
    record, verdict = screen_message(unrelated, [FACT], [], FakeResolver({}))

    assert verdict == Verdict.CLEAN
    assert record["candidates"] == []
    assert record["fact_results"] == []
