from datetime import datetime

from embargo.access import Access, authorized
from embargo.ledger import Ledger
from embargo.models import Crossing, Fact, FactState, MaterialityLevel


def _crossing(party_id="alice", fact_id="F047", effective_from=datetime(2026, 1, 1), effective_until=None):
    return Crossing(
        party_id=party_id,
        fact_id=fact_id,
        effective_from=effective_from,
        effective_until=effective_until,
    )


def test_authorized_true_when_crossed_and_open_ended():
    crossings = [_crossing(effective_from=datetime(2026, 1, 1))]

    assert authorized(crossings, "alice", "F047", datetime(2026, 6, 1)) is True


def test_authorized_false_before_effective_from():
    crossings = [_crossing(effective_from=datetime(2026, 1, 1))]

    assert authorized(crossings, "alice", "F047", datetime(2025, 12, 31)) is False


def test_authorized_false_at_or_after_effective_until():
    crossings = [
        _crossing(effective_from=datetime(2026, 1, 1), effective_until=datetime(2026, 2, 1))
    ]

    assert authorized(crossings, "alice", "F047", datetime(2026, 2, 1)) is False
    assert authorized(crossings, "alice", "F047", datetime(2026, 3, 1)) is False


def test_authorized_true_just_before_effective_until():
    crossings = [
        _crossing(effective_from=datetime(2026, 1, 1), effective_until=datetime(2026, 2, 1))
    ]

    assert authorized(crossings, "alice", "F047", datetime(2026, 1, 31)) is True


def test_authorized_false_for_uncrossed_party():
    crossings = [_crossing(party_id="alice", effective_from=datetime(2026, 1, 1))]

    # Not transitive: bob isn't authorized just because alice is.
    assert authorized(crossings, "bob", "F047", datetime(2026, 6, 1)) is False


def test_authorized_false_for_different_fact():
    crossings = [_crossing(fact_id="F047", effective_from=datetime(2026, 1, 1))]

    assert authorized(crossings, "alice", "F999", datetime(2026, 6, 1)) is False


def test_add_crossing_then_list_crossings_round_trips():
    access = Access(":memory:")
    crossing = _crossing(effective_from=datetime(2026, 1, 1))

    access.add_crossing(crossing)

    assert access.list_crossings() == [crossing]


def test_add_crossing_persists_open_ended_effective_until():
    access = Access(":memory:")
    access.add_crossing(_crossing(effective_from=datetime(2026, 1, 1), effective_until=None))

    assert access.list_crossings()[0].effective_until is None


def test_access_authorized_method_matches_pure_function_via_db_round_trip():
    access = Access(":memory:")
    access.add_crossing(
        _crossing(effective_from=datetime(2026, 1, 1), effective_until=datetime(2026, 2, 1))
    )

    assert access.authorized("alice", "F047", datetime(2026, 1, 15)) is True
    assert access.authorized("alice", "F047", datetime(2026, 2, 1)) is False
    assert access.authorized("bob", "F047", datetime(2026, 1, 15)) is False


def test_add_crossing_bumps_version(tmp_path):
    db = str(tmp_path / "embargo.db")
    access = Access(db)

    access.add_crossing(_crossing(effective_from=datetime(2026, 1, 1)))

    assert access.current_version() == 1


def test_version_is_shared_between_ledger_and_access(tmp_path):
    db = str(tmp_path / "embargo.db")
    ledger = Ledger(db)
    access = Access(db)

    ledger.add_fact(
        Fact(
            fact_id="F047", summary="x", entities=[], aliases=[], state=FactState.PRIVATE,
            recorded_at=datetime(2026, 1, 1),
            materiality=[(datetime(2026, 1, 1), MaterialityLevel.HIGH)],
        )
    )
    access.add_crossing(_crossing(effective_from=datetime(2026, 1, 1)))

    assert ledger.current_version() == 2
    assert access.current_version() == 2
