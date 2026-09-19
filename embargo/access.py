import sqlite3
from datetime import datetime

from embargo.models import Crossing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS crossings (
    party_id TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_until TEXT
);
"""


def authorized(crossings: list[Crossing], party_id: str, fact_id: str, at: datetime) -> bool:
    return any(
        c.party_id == party_id
        and c.fact_id == fact_id
        and c.effective_from <= at
        and (c.effective_until is None or at < c.effective_until)
        for c in crossings
    )


class Access:
    def __init__(self, path: str = ":memory:"):
        self._conn = sqlite3.connect(path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add_crossing(self, crossing: Crossing) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO crossings (party_id, fact_id, effective_from, effective_until)
                VALUES (?, ?, ?, ?)
                """,
                (
                    crossing.party_id,
                    crossing.fact_id,
                    crossing.effective_from.isoformat(),
                    crossing.effective_until.isoformat() if crossing.effective_until else None,
                ),
            )

    def list_crossings(self) -> list[Crossing]:
        rows = self._conn.execute(
            "SELECT party_id, fact_id, effective_from, effective_until FROM crossings"
        ).fetchall()
        return [self._row_to_crossing(row) for row in rows]

    def authorized(self, party_id: str, fact_id: str, at: datetime) -> bool:
        rows = self._conn.execute(
            "SELECT party_id, fact_id, effective_from, effective_until FROM crossings "
            "WHERE party_id = ? AND fact_id = ?",
            (party_id, fact_id),
        ).fetchall()
        crossings = [self._row_to_crossing(row) for row in rows]
        return authorized(crossings, party_id, fact_id, at)

    def _row_to_crossing(self, row) -> Crossing:
        party_id, fact_id, effective_from, effective_until = row
        return Crossing(
            party_id=party_id,
            fact_id=fact_id,
            effective_from=datetime.fromisoformat(effective_from),
            effective_until=datetime.fromisoformat(effective_until) if effective_until else None,
        )
