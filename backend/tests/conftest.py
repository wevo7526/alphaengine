"""Shared pytest setup for the Phase 1 provenance suite.

Forces the SQLite local fallback so DB-backed tests never touch a real
Postgres, and keeps the backend importable from the tests directory.
"""

import os
import sys
from pathlib import Path

# Run against the local SQLite fallback, isolated to a temp-ish file.
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("ENV", "development")

# Make `backend/` importable (provenance, pipeline, db, ...).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
