from datetime import datetime

from embargo.decision import decide
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

FACT_ID = "F047"
TS = datetime(2026, 6, 1)


def _fact(state=FactState.ANNOUNCED, cleared_at=None, materiality=MaterialityLevel.HIGH):
    return Fact(
        fact_id=FACT_ID,
        summary="Acme is acquiring Beta",
        entities=["ACME"],
        aliases=[],
        state=state,
        recorded_at=datetime(2026, 1, 1),
        materiality=[(datetime(2026, 1, 1), materiality)],
        announced_at=datetime(2026, 1, 1),
        cleared_at=cleared_at,
    )


def _message(sender="alice", recipients=("bob",), timestamp=TS):
    return Message(
        message_id="M001",
        sender=sender,
        recipients=list(recipients),
        timestamp=timestamp,
        body="the thing from the other day",
    )


def _resolution(mode=ResolutionMode.CONVEYS, confidence=0.9):
    return Resolution(fact_id=FACT_ID, mode=mode, confidence=confidence, span="the thing from the other day")


def _crossing(party_id, effective_from=datetime(2026, 1, 1), effective_until=None):
    return Crossing(party_id=party_id, fact_id=FACT_ID, effective_from=effective_from, effective_until=effective_until)


def _decide(fact, message, resolutions, crossings, threshold=0.6):
    return decide(message, resolutions, {FACT_ID: fact}, crossings, threshold=threshold)


# --- per-fact checks (spec §4.4) --------------------------------------------


def test_cleared_fact_is_clean_regardless_of_authorization():
    fact = _fact(state=FactState.CLEARED, cleared_at=datetime(2026, 3, 1))
    result = _decide(fact, _message(), [_resolution()], crossings=[])  # nobody authorized

    fd = result.fact_decisions[0]
    assert fd.verdict == Verdict.CLEAN
    assert fd.checks.is_cleared is True


def test_materiality_none_is_clean_regardless_of_authorization():
    fact = _fact(materiality=MaterialityLevel.NONE)
    result = _decide(fact, _message(), [_resolution()], crossings=[])

    fd = result.fact_decisions[0]
    assert fd.verdict == Verdict.CLEAN
    assert fd.checks.materiality == MaterialityLevel.NONE


def test_unauthorized_sender_is_violation_upstream_leak():
    fact = _fact()
    crossings = [_crossing("bob")]  # recipient authorized, sender is not
    result = _decide(fact, _message(sender="alice", recipients=["bob"]), [_resolution()], crossings)

    fd = result.fact_decisions[0]
    assert fd.verdict == Verdict.VIOLATION_UPSTREAM_LEAK
    assert fd.checks.sender_authorized is False
    assert fd.checks.recipient_authorized == {"bob": True}


def test_unauthorized_recipient_is_violation_disclosure():
    fact = _fact()
    crossings = [_crossing("alice")]  # sender authorized, recipient is not
    result = _decide(fact, _message(sender="alice", recipients=["bob"]), [_resolution()], crossings)

    fd = result.fact_decisions[0]
    assert fd.verdict == Verdict.VIOLATION_DISCLOSURE
    assert fd.checks.sender_authorized is True
    assert fd.checks.recipient_authorized == {"bob": False}


def test_recipient_checks_computed_for_every_recipient_not_short_circuited():
    fact = _fact()
    crossings = [_crossing("alice"), _crossing("bob")]  # carol left unauthorized
    result = _decide(
        fact, _message(sender="alice", recipients=["bob", "carol"]), [_resolution()], crossings
    )

    fd = result.fact_decisions[0]
    assert fd.checks.recipient_authorized == {"bob": True, "carol": False}
    assert fd.verdict == Verdict.VIOLATION_DISCLOSURE


def test_fully_authorized_and_material_and_not_cleared_is_clean():
    fact = _fact()
    crossings = [_crossing("alice"), _crossing("bob")]
    result = _decide(fact, _message(sender="alice", recipients=["bob"]), [_resolution()], crossings)

    assert result.fact_decisions[0].verdict == Verdict.CLEAN


# --- gate (spec §4.3) --------------------------------------------------------


def test_low_confidence_conveys_routes_to_review_without_running_checks():
    fact = _fact()
    result = _decide(fact, _message(), [_resolution(confidence=0.3)], crossings=[])

    fd = result.fact_decisions[0]
    assert fd.verdict == Verdict.REVIEW
    assert fd.reason == "low_confidence"
    assert fd.checks is None


def test_confidence_exactly_at_threshold_proceeds():
    fact = _fact()
    crossings = [_crossing("alice"), _crossing("bob")]
    result = _decide(
        fact, _message(sender="alice", recipients=["bob"]), [_resolution(confidence=0.6)], crossings, threshold=0.6
    )

    assert result.fact_decisions[0].verdict == Verdict.CLEAN
    assert result.fact_decisions[0].checks is not None


def test_mentions_does_not_proceed_and_has_no_verdict():
    fact = _fact()
    result = _decide(fact, _message(), [_resolution(mode=ResolutionMode.MENTIONS)], crossings=[])

    fd = result.fact_decisions[0]
    assert fd.proceeded is False
    assert fd.verdict is None
    assert fd.checks is None


# --- message-level severity (spec §4.4) -------------------------------------


def test_message_verdict_is_clean_when_no_contributing_verdicts():
    fact = _fact()
    result = _decide(fact, _message(), [_resolution(mode=ResolutionMode.MENTIONS)], crossings=[])

    assert result.verdict == Verdict.CLEAN


def test_message_verdict_is_most_severe_across_facts():
    fact_a = Fact(
        fact_id="A", summary="a", entities=["A"], aliases=[], state=FactState.ANNOUNCED,
        recorded_at=datetime(2026, 1, 1), materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
        announced_at=datetime(2026, 1, 1),
    )
    fact_b = Fact(
        fact_id="B", summary="b", entities=["B"], aliases=[], state=FactState.ANNOUNCED,
        recorded_at=datetime(2026, 1, 1), materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
        announced_at=datetime(2026, 1, 1),
    )
    message = _message(sender="alice", recipients=["bob"])
    # A: fully authorized -> clean. B: sender unauthorized -> violation_upstream_leak.
    crossings = [
        Crossing(party_id="alice", fact_id="A", effective_from=datetime(2026, 1, 1)),
        Crossing(party_id="bob", fact_id="A", effective_from=datetime(2026, 1, 1)),
        Crossing(party_id="bob", fact_id="B", effective_from=datetime(2026, 1, 1)),
    ]
    resolutions = [
        Resolution(fact_id="A", mode=ResolutionMode.CONVEYS, confidence=0.9, span="the thing from the other day"),
        Resolution(fact_id="B", mode=ResolutionMode.CONVEYS, confidence=0.9, span="the thing from the other day"),
    ]

    result = decide(message, resolutions, {"A": fact_a, "B": fact_b}, crossings)

    assert result.verdict == Verdict.VIOLATION_UPSTREAM_LEAK


def test_decision_module_does_not_import_resolver():
    import inspect

    import embargo.decision as decision_module

    source = inspect.getsource(decision_module)
    assert "resolver" not in source.lower()
