from datetime import datetime

from embargo.models import (
    Crossing,
    Fact,
    FactState,
    MaterialityLevel,
    Message,
    Resolution,
    ResolutionMode,
    Verdict,
)


def test_fact_state_values_match_spec_strings():
    assert FactState.PRIVATE.value == "private"
    assert FactState.ANNOUNCED.value == "announced"
    assert FactState.CLEARED.value == "cleared"
    assert FactState.ABANDONED.value == "abandoned"


def test_materiality_level_values_match_spec_strings():
    assert MaterialityLevel.HIGH.value == "high"
    assert MaterialityLevel.MEDIUM.value == "medium"
    assert MaterialityLevel.LOW.value == "low"
    assert MaterialityLevel.NONE.value == "none"


def test_resolution_mode_values_match_spec_strings():
    assert ResolutionMode.CONVEYS.value == "conveys"
    assert ResolutionMode.MENTIONS.value == "mentions"


def test_verdict_values_match_spec_strings():
    assert Verdict.CLEAN.value == "clean"
    assert Verdict.REVIEW.value == "review"
    assert Verdict.VIOLATION_DISCLOSURE.value == "violation_disclosure"
    assert Verdict.VIOLATION_UPSTREAM_LEAK.value == "violation_upstream_leak"


def test_verdict_severity_ordering():
    assert Verdict.VIOLATION_UPSTREAM_LEAK > Verdict.VIOLATION_DISCLOSURE
    assert Verdict.VIOLATION_DISCLOSURE > Verdict.REVIEW
    assert Verdict.REVIEW > Verdict.CLEAN


def test_fact_holds_spec_fields_with_optional_announced_and_cleared_at():
    fact = Fact(
        fact_id="F047",
        summary="Acme is acquiring Beta",
        entities=["ACME", "BETA"],
        aliases=["Project Falcon"],
        state=FactState.PRIVATE,
        recorded_at=datetime(2026, 1, 1),
        materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
    )

    assert fact.fact_id == "F047"
    assert fact.entities == ["ACME", "BETA"]
    assert fact.aliases == ["Project Falcon"]
    assert fact.state == FactState.PRIVATE
    assert fact.materiality == [(datetime(2026, 1, 1), MaterialityLevel.HIGH)]
    assert fact.announced_at is None
    assert fact.cleared_at is None


def test_fact_valid_from_defaults_to_recorded_at_when_omitted():
    fact = Fact(
        fact_id="F047",
        summary="Acme is acquiring Beta",
        entities=["ACME"],
        aliases=[],
        state=FactState.PRIVATE,
        recorded_at=datetime(2026, 3, 1),
        materiality=[(datetime(2026, 3, 1), MaterialityLevel.HIGH)],
    )

    assert fact.valid_from == datetime(2026, 3, 1)


def test_fact_valid_from_can_be_set_earlier_than_recorded_at():
    fact = Fact(
        fact_id="F047",
        summary="Acme is acquiring Beta",
        entities=["ACME"],
        aliases=[],
        state=FactState.PRIVATE,
        recorded_at=datetime(2026, 3, 1),
        materiality=[(datetime(2026, 3, 1), MaterialityLevel.HIGH)],
        valid_from=datetime(2026, 1, 1),
    )

    assert fact.valid_from == datetime(2026, 1, 1)


def test_crossing_defaults_to_open_ended_authorization():
    crossing = Crossing(
        party_id="alice",
        fact_id="F047",
        effective_from=datetime(2026, 1, 1),
    )

    assert crossing.effective_until is None


def test_message_holds_spec_fields():
    message = Message(
        message_id="M001",
        sender="alice",
        recipients=["bob", "carol"],
        timestamp=datetime(2026, 1, 2),
        body="the thing from the other day",
    )

    assert message.message_id == "M001"
    assert message.sender == "alice"
    assert message.recipients == ["bob", "carol"]
    assert message.body == "the thing from the other day"


def test_resolution_holds_spec_fields():
    resolution = Resolution(
        fact_id="F047",
        mode=ResolutionMode.CONVEYS,
        confidence=0.82,
        span="the thing from the other day",
    )

    assert resolution.fact_id == "F047"
    assert resolution.mode == ResolutionMode.CONVEYS
    assert resolution.confidence == 0.82
    assert resolution.span == "the thing from the other day"
