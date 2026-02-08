"""Centralized FastAPI dependencies for use with Depends()."""

from app.db.session import get_db_session

__all__ = ["get_db_session"]
