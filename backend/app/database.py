from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after a table first shipped. This project has no Alembic —
# Base.metadata.create_all() creates missing *tables* but never alters an
# existing one, and the dev/demo databases hold data worth keeping (orders,
# agents, audit history). SQLite supports ADD COLUMN for nullable columns and
# for NOT NULL columns with a constant default, which is all of these.
#
# Keep every entry idempotent and additive. Never put a rename, a drop, or a
# type change here: this runs on every startup, against a database that may be
# at any prior version, with no down-migration and no ordering guarantees
# beyond "the column either exists or it does not".
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    # Layer 7 — conversation history. See app/models/agent_session.py.
    "agent_sessions": {
        "credential_id": "VARCHAR(64)",
        "title": "VARCHAR(120)",
        "archived": "BOOLEAN NOT NULL DEFAULT 0",
        "message_count": "INTEGER NOT NULL DEFAULT 0",
        "last_active_at": "DATETIME",
    },
}


def ensure_schema() -> None:
    """Add any missing columns listed in _ADDED_COLUMNS. Safe to call on every
    startup and on a brand-new database, where create_all() has already made
    the columns and every check below is a no-op."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all() will build it complete
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name in present:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))

        # Both tables must already exist: ensure_schema() also runs against a
        # brand-new database, where create_all() has not built them yet and
        # this would otherwise fail at import with "no such table".
        if {"agent_sessions", "agent_messages"} <= existing_tables:
            _backfill_conversation_counters(conn)


def _backfill_conversation_counters(conn) -> None:
    """Populate Layer 7's denormalised counters for conversations that
    predate them.

    ADD COLUMN gives every existing row message_count = 0, and the history
    list hides conversations with no messages — so without this, the exact
    conversations a buyer wants to resume (the ones that already existed) are
    the ones that would be invisible.

    Idempotent: only touches rows still sitting at the default, and derives
    both values from agent_messages, which is the source of truth either way.
    """
    conn.execute(
        text(
            """
            UPDATE agent_sessions
               SET message_count = (
                     SELECT COUNT(*) FROM agent_messages m
                      WHERE m.session_id = agent_sessions.session_id
                   ),
                   last_active_at = COALESCE(
                     last_active_at,
                     (SELECT MAX(m.created_at) FROM agent_messages m
                       WHERE m.session_id = agent_sessions.session_id),
                     updated_at
                   )
             WHERE COALESCE(message_count, 0) = 0
               AND EXISTS (
                     SELECT 1 FROM agent_messages m
                      WHERE m.session_id = agent_sessions.session_id
                   )
            """
        )
    )
