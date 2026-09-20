"""A real trigger, not a synthetic one: a V0-era embargo.db was created
before `valid_from` existed on the facts table. `CREATE TABLE IF NOT EXISTS`
never adds a column to an existing table (documented in STATUS.md during
§13.1), so opening such a database with the current Ledger crashes without
a migration. This builds a genuinely V0-shaped database by hand and proves
Ledger() upgrades it in place."""

import sqlite3

from embargo.ledger import Ledger


def _build_v0_shaped_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE facts (
            fact_id TEXT PRIMARY KEY,
            summary TEXT NOT NULL,
            entities TEXT NOT NULL,
            aliases TEXT NOT NULL,
            state TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            announced_at TEXT,
            cleared_at TEXT
        );

        CREATE TABLE materiality (
            fact_id TEXT NOT NULL REFERENCES facts(fact_id),
            effective_from TEXT NOT NULL,
            level TEXT NOT NULL,
            PRIMARY KEY (fact_id, effective_from)
        );
        """
    )
    conn.execute(
        """
        INSERT INTO facts (fact_id, summary, entities, aliases, state, recorded_at, announced_at, cleared_at)
        VALUES ('F001', 'Acme deal', '["Acme"]', '[]', 'announced', '2026-01-01T00:00:00', '2026-01-02T00:00:00', NULL)
        """
    )
    conn.execute(
        "INSERT INTO materiality (fact_id, effective_from, level) VALUES ('F001', '2026-01-01T00:00:00', 'high')"
    )
    conn.commit()
    conn.close()


def test_ledger_opens_v0_shaped_database_without_crashing(tmp_path):
    db_path = str(tmp_path / "embargo.db")
    _build_v0_shaped_db(db_path)

    ledger = Ledger(db_path)
    fact = ledger.get_fact("F001")

    assert fact.fact_id == "F001"


def test_migration_backfills_valid_from_from_recorded_at(tmp_path):
    db_path = str(tmp_path / "embargo.db")
    _build_v0_shaped_db(db_path)

    ledger = Ledger(db_path)
    fact = ledger.get_fact("F001")

    assert fact.valid_from.isoformat() == "2026-01-01T00:00:00"


def test_migration_is_idempotent_on_second_open(tmp_path):
    db_path = str(tmp_path / "embargo.db")
    _build_v0_shaped_db(db_path)

    Ledger(db_path)
    # Second open must not error (no "duplicate column" from re-running ALTER TABLE).
    ledger2 = Ledger(db_path)
    fact = ledger2.get_fact("F001")

    assert fact.valid_from.isoformat() == "2026-01-01T00:00:00"


def test_fresh_database_is_unaffected_by_migration_check(tmp_path):
    db_path = str(tmp_path / "embargo.db")

    ledger = Ledger(db_path)

    assert ledger.list_facts() == []
