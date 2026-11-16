import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from backend.config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

def get_db_path(override_path: Optional[Path] = None) -> Path:
    return override_path if override_path is not None else settings.db_path

@contextmanager
def get_connection(override_path: Optional[Path] = None) -> Generator[sqlite3.Connection, None, None]:
    db_file = get_db_path(override_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()

def init_db(override_path: Optional[Path] = None) -> None:
    db_file = get_db_path(override_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Run all migrations in sorted order
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    with get_connection(db_file) as conn:
        for m_file in migration_files:
            sql_script = m_file.read_text(encoding="utf-8")
            conn.executescript(sql_script)

        # Ensure schema migrations for existing tables
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
        if "tokens_used" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN tokens_used INTEGER NOT NULL DEFAULT 0")
        if "latency_ms" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN latency_ms REAL NOT NULL DEFAULT 0.0")

        conn.commit()

def get_db() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI dependency for database connection."""
    with get_connection() as conn:
        yield conn
