from datetime import datetime

import pytest

from embargo.ledger import Ledger, materiality_at
from embargo.models import Fact, FactState, MaterialityLevel


def _fact_with_materiality(materiality):
    return Fact(
        fact_id="F047",
        summary="Acme is acquiring Beta",
        entities=["ACME", "BETA"],
        aliases=[],
        state=FactState.PRIVATE,
        recorded_at=datetime(2026, 1, 1),
        materiality=materiality,
    )


def test_materiality_at_returns_level_in_effect_at_timestamp():
    fact = _fact_with_materiality(
        [
            (datetime(2026, 1, 1), MaterialityLevel.LOW),
            (datetime(2026, 2, 1), MaterialityLevel.HIGH),
        ]
    )

    assert materiality_at(fact, datetime(2026, 1, 15)) == MaterialityLevel.LOW
    assert materiality_at(fact, datetime(2026, 2, 15)) == MaterialityLevel.HIGH


def test_materiality_at_uses_most_recent_entry_not_closest():
    fact = _fact_with_materiality(
        [
            (datetime(2026, 1, 1), MaterialityLevel.LOW),
            (datetime(2026, 1, 10), MaterialityLevel.MEDIUM),
            (datetime(2026, 2, 1), MaterialityLevel.HIGH),
        ]
    )

    assert materiality_at(fact, datetime(2026, 1, 20)) == MaterialityLevel.MEDIUM


def test_materiality_at_raises_before_any_entry_takes_effect():
    fact = _fact_with_materiality([(datetime(2026, 1, 1), MaterialityLevel.LOW)])

    with pytest.raises(ValueError):
        materiality_at(fact, datetime(2025, 12, 31))


def test_add_fact_then_get_fact_round_trips_all_fields():
    ledger = Ledger(":memory:")
    fact = Fact(
        fact_id="F047",
        summary="Acme is acquiring Beta",
        entities=["ACME", "BETA"],
        aliases=["Project Falcon"],
        state=FactState.PRIVATE,
        recorded_at=datetime(2026, 1, 1, 9, 0),
        materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
    )

    ledger.add_fact(fact)
    retrieved = ledger.get_fact("F047")

    assert retrieved == fact


def test_add_fact_rejects_non_private_initial_state():
    ledger = Ledger(":memory:")
    fact = Fact(
        fact_id="F047",
        summary="Acme is acquiring Beta",
        entities=["ACME"],
        aliases=[],
        state=FactState.ANNOUNCED,
        recorded_at=datetime(2026, 1, 1),
        materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
        announced_at=datetime(2026, 1, 1),
    )

    with pytest.raises(ValueError):
        ledger.add_fact(fact)


def test_get_fact_raises_for_unknown_id():
    ledger = Ledger(":memory:")

    with pytest.raises(KeyError):
        ledger.get_fact("no-such-fact")


def test_list_facts_returns_every_added_fact():
    ledger = Ledger(":memory:")
    fact_a = Fact(
        fact_id="F001",
        summary="A",
        entities=["A"],
        aliases=[],
        state=FactState.PRIVATE,
        recorded_at=datetime(2026, 1, 1),
        materiality=[(datetime(2026, 1, 1), MaterialityLevel.LOW)],
    )
    fact_b = Fact(
        fact_id="F002",
        summary="B",
        entities=["B"],
        aliases=[],
        state=FactState.PRIVATE,
        recorded_at=datetime(2026, 1, 1),
        materiality=[(datetime(2026, 1, 1), MaterialityLevel.LOW)],
    )
    ledger.add_fact(fact_a)
    ledger.add_fact(fact_b)

    assert {f.fact_id for f in ledger.list_facts()} == {"F001", "F002"}


def _private_ledger_with_fact(fact_id="F047"):
    ledger = Ledger(":memory:")
    ledger.add_fact(
        Fact(
            fact_id=fact_id,
            summary="Acme is acquiring Beta",
            entities=["ACME"],
            aliases=[],
            state=FactState.PRIVATE,
            recorded_at=datetime(2026, 1, 1),
            materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
        )
    )
    return ledger


def test_transition_private_to_announced_requires_announced_at():
    ledger = _private_ledger_with_fact()

    with pytest.raises(ValueError):
        ledger.transition("F047", FactState.ANNOUNCED)


def test_transition_private_to_announced_sets_state_and_timestamp():
    ledger = _private_ledger_with_fact()

    updated = ledger.transition(
        "F047", FactState.ANNOUNCED, announced_at=datetime(2026, 2, 1)
    )

    assert updated.state == FactState.ANNOUNCED
    assert updated.announced_at == datetime(2026, 2, 1)
    assert ledger.get_fact("F047").state == FactState.ANNOUNCED


def test_transition_private_to_abandoned():
    ledger = _private_ledger_with_fact()

    updated = ledger.transition("F047", FactState.ABANDONED)

    assert updated.state == FactState.ABANDONED


def test_transition_announced_to_cleared_requires_cleared_at():
    ledger = _private_ledger_with_fact()
    ledger.transition("F047", FactState.ANNOUNCED, announced_at=datetime(2026, 2, 1))

    with pytest.raises(ValueError):
        ledger.transition("F047", FactState.CLEARED, now=datetime(2026, 3, 1))


def test_transition_announced_to_cleared_rejected_before_cleared_at_elapses():
    ledger = _private_ledger_with_fact()
    ledger.transition("F047", FactState.ANNOUNCED, announced_at=datetime(2026, 2, 1))

    with pytest.raises(ValueError):
        ledger.transition(
            "F047",
            FactState.CLEARED,
            cleared_at=datetime(2026, 3, 1),
            now=datetime(2026, 2, 15),
        )


def test_transition_announced_to_cleared_succeeds_once_elapsed():
    ledger = _private_ledger_with_fact()
    ledger.transition("F047", FactState.ANNOUNCED, announced_at=datetime(2026, 2, 1))

    updated = ledger.transition(
        "F047",
        FactState.CLEARED,
        cleared_at=datetime(2026, 3, 1),
        now=datetime(2026, 3, 1),
    )

    assert updated.state == FactState.CLEARED
    assert updated.cleared_at == datetime(2026, 3, 1)


def test_transition_abandoned_to_cleared_is_manual_compliance_action():
    ledger = _private_ledger_with_fact()
    ledger.transition("F047", FactState.ABANDONED)

    updated = ledger.transition(
        "F047", FactState.CLEARED, cleared_at=datetime(2026, 2, 1)
    )

    assert updated.state == FactState.CLEARED


def test_transition_rejects_disallowed_paths():
    ledger = _private_ledger_with_fact()

    with pytest.raises(ValueError):
        ledger.transition("F047", FactState.CLEARED, cleared_at=datetime(2026, 2, 1))


def test_add_fact_persists_valid_from_distinct_from_recorded_at():
    ledger = Ledger(":memory:")
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

    ledger.add_fact(fact)
    retrieved = ledger.get_fact("F047")

    assert retrieved.valid_from == datetime(2026, 1, 1)
    assert retrieved.recorded_at == datetime(2026, 3, 1)


def test_current_version_starts_at_zero():
    ledger = Ledger(":memory:")

    assert ledger.current_version() == 0


def test_add_fact_bumps_version():
    ledger = Ledger(":memory:")
    ledger.add_fact(
        Fact(
            fact_id="F047", summary="x", entities=[], aliases=[], state=FactState.PRIVATE,
            recorded_at=datetime(2026, 1, 1),
            materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
        )
    )

    assert ledger.current_version() == 1


def test_transition_also_bumps_version():
    ledger = _private_ledger_with_fact()
    version_after_add = ledger.current_version()

    ledger.transition("F047", FactState.ABANDONED)

    assert ledger.current_version() == version_after_add + 1


def test_transition_out_of_cleared_is_always_rejected():
    ledger = _private_ledger_with_fact()
    ledger.transition("F047", FactState.ANNOUNCED, announced_at=datetime(2026, 2, 1))
    ledger.transition(
        "F047", FactState.CLEARED, cleared_at=datetime(2026, 3, 1), now=datetime(2026, 3, 1)
    )

    with pytest.raises(ValueError):
        ledger.transition("F047", FactState.ABANDONED)
