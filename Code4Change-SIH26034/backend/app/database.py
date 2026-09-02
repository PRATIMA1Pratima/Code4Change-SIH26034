"""
database.py – SQLite database abstraction layer.

Uses the standard library sqlite3 module directly so there are no
heavy ORM dependencies in Phase 1.  The connection helper and schema
initialisation live here; all query logic belongs in the API/service
layers that import these utilities.

Switching to PostgreSQL or MySQL later only requires replacing the
connection factory and the handful of SQLite-specific pragmas.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from app.config import DATABASE_URL

# ── Resolve the physical file path from the sqlite:/// URL ────────────────────
_DB_PATH: Path = Path(DATABASE_URL.replace("sqlite:///", ""))


# ── Connection factory ────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """Return a new SQLite connection with sensible defaults."""
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row          # rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrent read performance
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a connection and commits/rolls back."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema ────────────────────────────────────────────────────────────────────

CREATE_INSPECTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS inspections (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp             TEXT    NOT NULL,
    image_path            TEXT    NOT NULL,
    extracted_text        TEXT    NOT NULL DEFAULT '',
    detected_declarations TEXT    NOT NULL DEFAULT '{}',   -- JSON object
    declaration_status    TEXT    NOT NULL DEFAULT '{}',   -- JSON object (Phase 7)
    compliance_score      REAL    NOT NULL DEFAULT 0.0,
    status                TEXT    NOT NULL DEFAULT 'UNKNOWN',
    violations            TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    report_path           TEXT             DEFAULT NULL
);
"""


def _migrate_db(conn: sqlite3.Connection) -> None:
    """Apply incremental schema migrations on an existing database.

    Each migration is guarded by a column-existence check so it is
    idempotent — safe to call on every startup.
    """
    existing_cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(inspections)").fetchall()
    }

    # Phase 7: add declaration_status column if missing
    if "declaration_status" not in existing_cols:
        conn.execute(
            "ALTER TABLE inspections ADD COLUMN "
            "declaration_status TEXT NOT NULL DEFAULT '{}'"
        )
        print("[DB] Migration applied: added declaration_status column")


def init_db() -> None:
    """Create tables if they do not already exist, then run migrations.

    Called once at application startup from main.py.
    """
    with get_db() as conn:
        conn.execute(CREATE_INSPECTIONS_TABLE)
        _migrate_db(conn)
    print(f"[DB] Database ready at {_DB_PATH}")


# ── Helpers used by the API layer ─────────────────────────────────────────────

def row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain Python dict."""
    d = dict(row)
    # Deserialise JSON columns
    for col in ("detected_declarations", "declaration_status", "violations"):
        if col in d and isinstance(d[col], str):
            try:
                d[col] = json.loads(d[col])
            except json.JSONDecodeError:
                pass  # leave as raw string if parsing fails
    return d
