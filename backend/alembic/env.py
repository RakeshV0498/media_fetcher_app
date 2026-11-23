from alembic import context

from app import models  # noqa: F401
from app.db import Base, engine

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with engine.connect() as conn:
        is_sqlite = conn.dialect.name == "sqlite"
        if is_sqlite:
            # Batch migrations rebuild tables (create tmp -> copy -> drop -> rename). With foreign keys enforced,
            # dropping a table that other tables reference fails. Must be set outside a transaction.
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            # A previous run that died mid-rebuild leaves `_alembic_tmp_*` behind, which blocks every retry.
            for (name,) in conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '\\_alembic\\_tmp\\_%' ESCAPE '\\'"
            ).fetchall():
                conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{name}"')
            conn.commit()
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        if is_sqlite:
            conn.commit()
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")


run_migrations_online()
