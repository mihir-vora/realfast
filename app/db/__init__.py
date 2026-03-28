# Database configuration: engine, session factory, and base model.
# SQLite for simplicity — no external database setup required.

from app.db.base import Base, SessionLocal, engine, get_db  # noqa: F401
