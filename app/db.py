import os

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app import config

os.makedirs(os.path.dirname(config.DATABASE_PATH) or ".", exist_ok=True)
engine = create_engine(
    f"sqlite:///{config.DATABASE_PATH}", connect_args={"check_same_thread": False}
)


def _add_missing_columns() -> None:
    """Tiny migration: add columns that were added to a model after its table was created."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
                if isinstance(default, str):
                    ddl += " DEFAULT '" + default.replace("'", "''") + "'"
                elif isinstance(default, (bool, int, float)):
                    ddl += f" DEFAULT {int(default) if isinstance(default, bool) else default}"
                conn.execute(text(ddl))


def init_db() -> None:
    from app import models  # noqa: F401  register tables

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def get_session():
    with Session(engine) as session:
        yield session
