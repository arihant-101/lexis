"""
Run Alembic migrations at startup.

`run_migrations()` returns True if Alembic applied migrations, False otherwise
(e.g. Alembic not installed). Callers fall back to `init_db()` so the app still
boots in environments without the migration toolchain.
"""

import os

from observability.logger import log

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_migrations() -> bool:
    try:
        from alembic.config import Config
        from alembic import command
    except ModuleNotFoundError:
        log("migrations_skipped", reason="alembic_not_installed")
        return False

    try:
        cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
        cfg.set_main_option("sqlalchemy.url", os.environ.get(
            "DATABASE_URL", "postgresql://lexis:lexis@localhost:5432/lexis"))
        command.upgrade(cfg, "head")
        log("migrations_applied", target="head")
        return True
    except Exception as exc:
        log("migrations_failed", error=str(exc))
        return False
