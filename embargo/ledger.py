import json
import sqlite3
from datetime import datetime

from embargo.models import Fact, FactState, MaterialityLevel

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    fact_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    entities TEXT NOT NULL,
    aliases TEXT NOT NULL,
    state TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    announced_at TEXT,
    cleared_at TEXT,
    valid_from TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materiality (
    fact_id TEXT NOT NULL REFERENCES facts(fact_id),
    effective_from TEXT NOT NULL,
    level TEXT NOT NULL,
    PRIMARY KEY (fact_id, effective_from)
);
"""

# Shared with access.py: both point at the same db file (in real use) and
# each write -- fact or crossing -- bumps this one counter (spec §13.1).
# V1 assumes a fresh database; adding this column to an existing V0-era
# embargo.db is a V2 migrations concern (spec §14.1), not handled here.
_VERSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO ledger_version (id, version) VALUES (1, 0);
"""


def ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.executescript(_VERSION_SCHEMA)
    conn.commit()


def bump_version(conn: sqlite3.Connection) -> int:
    ensure_version_table(conn)
    conn.execute("UPDATE ledger_version SET version = version + 1 WHERE id = 1")
    return read_version(conn)


def read_version(conn: sqlite3.Connection) -> int:
    ensure_version_table(conn)
    return conn.execute("SELECT version FROM ledger_version WHERE id = 1").fetchone()[0]


def materiality_at(fact: Fact, at: datetime) -> MaterialityLevel:
    in_effect = [entry for entry in fact.materiality if entry[0] <= at]
    if not in_effect:
        raise ValueError(
            f"fact {fact.fact_id!r} has no materiality entry in effect at {at!r}"
        )
    return max(in_effect, key=lambda entry: entry[0])[1]


class Ledger:
    def __init__(self, path: str = ":memory:"):
        self._conn = sqlite3.connect(path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        ensure_version_table(self._conn)

    def current_version(self) -> int:
        return read_version(self._conn)

    def add_fact(self, fact: Fact) -> None:
        if fact.state != FactState.PRIVATE:
            raise ValueError(
                f"facts must enter the ledger as {FactState.PRIVATE.value!r}, "
                f"got {fact.state.value!r}"
            )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO facts
                    (fact_id, summary, entities, aliases, state,
                     recorded_at, announced_at, cleared_at, valid_from)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact.fact_id,
                    fact.summary,
                    json.dumps(fact.entities),
                    json.dumps(fact.aliases),
                    fact.state.value,
                    fact.recorded_at.isoformat(),
                    fact.announced_at.isoformat() if fact.announced_at else None,
                    fact.cleared_at.isoformat() if fact.cleared_at else None,
                    fact.valid_from.isoformat(),
                ),
            )
            self._conn.executemany(
                "INSERT INTO materiality (fact_id, effective_from, level) VALUES (?, ?, ?)",
                [
                    (fact.fact_id, effective_from.isoformat(), level.value)
                    for effective_from, level in fact.materiality
                ],
            )
            bump_version(self._conn)

    def transition(
        self,
        fact_id: str,
        target: FactState,
        *,
        announced_at: datetime | None = None,
        cleared_at: datetime | None = None,
        now: datetime | None = None,
    ) -> Fact:
        fact = self.get_fact(fact_id)

        if fact.state == FactState.PRIVATE and target == FactState.ANNOUNCED:
            if announced_at is None:
                raise ValueError("transitioning to announced requires announced_at")
            self._update_state(fact_id, target, announced_at=announced_at)

        elif fact.state == FactState.PRIVATE and target == FactState.ABANDONED:
            self._update_state(fact_id, target)

        elif fact.state == FactState.ANNOUNCED and target == FactState.CLEARED:
            if cleared_at is None:
                raise ValueError("transitioning to cleared requires cleared_at")
            if (now or datetime.now()) < cleared_at:
                raise ValueError(
                    "cannot clear before cleared_at: the digestion window has not elapsed"
                )
            self._update_state(fact_id, target, cleared_at=cleared_at)

        elif fact.state == FactState.ABANDONED and target == FactState.CLEARED:
            # No elapsed-time gate here: this path exists only for an explicit,
            # manual compliance action overriding an embargo that never lifts on its own.
            if cleared_at is None:
                raise ValueError("transitioning to cleared requires cleared_at")
            self._update_state(fact_id, target, cleared_at=cleared_at)

        else:
            raise ValueError(
                f"illegal transition: {fact.state.value!r} -> {target.value!r}"
            )

        with self._conn:
            bump_version(self._conn)

        return self.get_fact(fact_id)

    def _update_state(
        self,
        fact_id: str,
        state: FactState,
        *,
        announced_at: datetime | None = None,
        cleared_at: datetime | None = None,
    ) -> None:
        with self._conn:
            if announced_at is not None:
                self._conn.execute(
                    "UPDATE facts SET state = ?, announced_at = ? WHERE fact_id = ?",
                    (state.value, announced_at.isoformat(), fact_id),
                )
            elif cleared_at is not None:
                self._conn.execute(
                    "UPDATE facts SET state = ?, cleared_at = ? WHERE fact_id = ?",
                    (state.value, cleared_at.isoformat(), fact_id),
                )
            else:
                self._conn.execute(
                    "UPDATE facts SET state = ? WHERE fact_id = ?",
                    (state.value, fact_id),
                )

    def get_fact(self, fact_id: str) -> Fact:
        row = self._conn.execute(
            """
            SELECT fact_id, summary, entities, aliases, state,
                   recorded_at, announced_at, cleared_at, valid_from
            FROM facts WHERE fact_id = ?
            """,
            (fact_id,),
        ).fetchone()
        if row is None:
            raise KeyError(fact_id)
        return self._row_to_fact(row)

    def list_facts(self) -> list[Fact]:
        rows = self._conn.execute(
            """
            SELECT fact_id, summary, entities, aliases, state,
                   recorded_at, announced_at, cleared_at, valid_from
            FROM facts
            """
        ).fetchall()
        return [self._row_to_fact(row) for row in rows]

    def _row_to_fact(self, row) -> Fact:
        (
            fact_id,
            summary,
            entities,
            aliases,
            state,
            recorded_at,
            announced_at,
            cleared_at,
            valid_from,
        ) = row
        materiality_rows = self._conn.execute(
            "SELECT effective_from, level FROM materiality WHERE fact_id = ? ORDER BY effective_from",
            (fact_id,),
        ).fetchall()
        return Fact(
            fact_id=fact_id,
            summary=summary,
            entities=json.loads(entities),
            aliases=json.loads(aliases),
            state=FactState(state),
            recorded_at=datetime.fromisoformat(recorded_at),
            materiality=[
                (datetime.fromisoformat(effective_from), MaterialityLevel(level))
                for effective_from, level in materiality_rows
            ],
            announced_at=datetime.fromisoformat(announced_at) if announced_at else None,
            cleared_at=datetime.fromisoformat(cleared_at) if cleared_at else None,
            valid_from=datetime.fromisoformat(valid_from),
        )
