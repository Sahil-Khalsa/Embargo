from datetime import datetime

from embargo.models import Crossing, Fact, FactState, MaterialityLevel, Message
from embargo.prefilter import candidate_facts


def _fact(fact_id="F047", entities=None, aliases=None):
    return Fact(
        fact_id=fact_id,
        summary="Acme is acquiring Beta",
        entities=entities or [],
        aliases=aliases or [],
        state=FactState.PRIVATE,
        recorded_at=datetime(2026, 1, 1),
        materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
    )


def _message(body="hi", sender="alice", recipients=None, timestamp=datetime(2026, 6, 1)):
    return Message(
        message_id="M001",
        sender=sender,
        recipients=recipients or ["bob"],
        timestamp=timestamp,
        body=body,
    )


def test_candidate_when_entity_appears_in_body():
    fact = _fact(entities=["ACME"])
    message = _message(body="did you see the ACME news?")

    candidates = candidate_facts(message, [fact], [])

    assert [c.fact for c in candidates] == [fact]
    # Also picked up by similarity_candidates: "ACME" is a shared, rare
    # token between the fact text and the (short) message body.
    assert candidates[0].reasons == {"entity_match", "semantic_match"}


def test_candidate_when_alias_appears_in_body():
    fact = _fact(aliases=["Project Falcon"])
    message = _message(body="any update on Project Falcon?")

    candidates = candidate_facts(message, [fact], [])

    assert candidates[0].reasons == {"alias_match", "semantic_match"}


def test_no_false_positive_on_substring_match():
    fact = _fact(entities=["ACME"])
    message = _message(body="ACMEWIDGETS just IPO'd, unrelated")

    assert candidate_facts(message, [fact], []) == []


def test_keyword_matching_is_case_insensitive():
    fact = _fact(entities=["ACME"])
    message = _message(body="acme is doing fine")

    candidates = candidate_facts(message, [fact], [])

    assert [c.fact for c in candidates] == [fact]


def test_candidate_via_party_authorization_with_no_keyword_hit():
    fact = _fact(entities=["ACME"], aliases=[])
    message = _message(
        body="the thing from the other day is moving forward",
        sender="alice",
        recipients=["bob"],
        timestamp=datetime(2026, 6, 1),
    )
    crossing = Crossing(
        party_id="alice", fact_id="F047", effective_from=datetime(2026, 1, 1)
    )

    candidates = candidate_facts(message, [fact], [crossing])

    assert [c.fact for c in candidates] == [fact]
    assert candidates[0].reasons == {"party_authorization"}


def test_authorization_checked_for_recipients_too_not_only_sender():
    fact = _fact(entities=["ACME"])
    message = _message(
        body="the thing from the other day",
        sender="alice",
        recipients=["bob"],
        timestamp=datetime(2026, 6, 1),
    )
    crossing = Crossing(party_id="bob", fact_id="F047", effective_from=datetime(2026, 1, 1))

    candidates = candidate_facts(message, [fact], [crossing])

    assert [c.fact for c in candidates] == [fact]


def test_not_a_candidate_when_no_keyword_and_no_authorization():
    fact = _fact(entities=["ACME"])
    message = _message(body="completely unrelated chatter", sender="alice", recipients=["bob"])

    assert candidate_facts(message, [fact], []) == []


def test_candidate_reasons_union_when_both_keyword_and_authorization_hit():
    fact = _fact(entities=["ACME"])
    message = _message(body="ACME news", sender="alice", recipients=["bob"], timestamp=datetime(2026, 6, 1))
    crossing = Crossing(party_id="alice", fact_id="F047", effective_from=datetime(2026, 1, 1))

    candidates = candidate_facts(message, [fact], [crossing])

    assert candidates[0].reasons == {"entity_match", "party_authorization", "semantic_match"}


def test_candidate_reports_both_entity_and_alias_match_when_both_present():
    fact = _fact(entities=["ACME"], aliases=["Project Falcon"])
    message = _message(body="ACME and Project Falcon are related")

    candidates = candidate_facts(message, [fact], [])

    assert candidates[0].reasons == {"entity_match", "alias_match", "semantic_match"}
