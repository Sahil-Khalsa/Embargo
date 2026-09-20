import sqlite3


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Applies any pending schema migrations to an already-open connection,
    idempotently. Returns the names of migrations actually applied (empty
    if the schema was already current, including a brand new database --
    Ledger's own CREATE TABLE IF NOT EXISTS handles that case correctly on
    its own).

    A fresh database has no `facts` table yet, so there is nothing here to
    migrate -- Ledger's schema script creates it in the current shape.
    """
    applied = []

    if _table_exists(conn, "facts") and not _has_column(conn, "facts", "valid_from"):
        # V0-era facts table predates valid_from (added in V1, spec 13.1).
        # Backfill from recorded_at, matching Fact.__post_init__'s own
        # default for a fact constructed without an explicit valid_from.
        conn.execute("ALTER TABLE facts ADD COLUMN valid_from TEXT")
        conn.execute("UPDATE facts SET valid_from = recorded_at WHERE valid_from IS NULL")
        conn.commit()
        applied.append("add valid_from to facts, backfilled from recorded_at")

    return applied
