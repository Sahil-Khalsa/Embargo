from datetime import datetime

from embargo.models import Fact, FactState, MaterialityLevel, Message
from embargo.prefilter import candidate_facts, similarity_candidates

FACT = Fact(
    fact_id="F900",
    summary="Acme Corp is being acquired by Beta Holdings in a merger",
    entities=["Acme"],
    aliases=[],
    state=FactState.ANNOUNCED,
    recorded_at=datetime(2026, 1, 1),
    materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
    announced_at=datetime(2026, 1, 1),
)


def _message(body: str) -> Message:
    return Message(
        message_id="M1", sender="alice", recipients=["bob"],
        timestamp=datetime(2026, 6, 1), body=body,
    )


def test_similarity_candidates_matches_vocabulary_overlap_without_entity_name():
    # Shares "merger"/"acquired"/"Beta Holdings"-style vocabulary with the
    # fact's summary but never says "Acme" -- keyword matching alone would
    # miss this fact entirely.
    message = _message("Heard the Beta Holdings merger and acquisition is moving forward.")

    matches = similarity_candidates(message, [FACT], threshold=0.3)

    assert "F900" in matches


def test_similarity_candidates_does_not_match_unrelated_message():
    message = _message("Just checking in about lunch plans for Friday, no rush.")

    matches = similarity_candidates(message, [FACT], threshold=0.3)

    assert matches == set()


def test_candidate_facts_includes_semantic_match_reason():
    message = _message("Heard the Beta Holdings merger and acquisition is moving forward.")

    candidates = candidate_facts(message, [FACT], [])

    assert len(candidates) == 1
    assert "semantic_match" in candidates[0].reasons


def test_candidate_facts_unrelated_message_surfaces_no_candidates():
    message = _message("Just checking in about lunch plans for Friday, no rush.")

    candidates = candidate_facts(message, [FACT], [])

    assert candidates == []


def test_real_corpus_lunch_message_has_no_semantic_match():
    """Guards against the tuning trap: a permissive cutoff would surface
    nearly every fact for every message on a small, short corpus."""
    from pathlib import Path

    from eval.run_eval import load_facts

    facts_path = Path(__file__).parent.parent / "corpus" / "facts.yaml"
    facts = load_facts(facts_path)
    message = _message("Just checking in about lunch plans for Friday, no rush.")

    matches = similarity_candidates(message, facts)

    assert matches == set()
