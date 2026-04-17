import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Integer, MetaData, create_engine, insert, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.sql.sqltypes import JSON

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from database import Base


def build_engine(url: str) -> Engine:
    is_sqlite = url.startswith("sqlite")
    return create_engine(
        url,
        connect_args={"check_same_thread": False} if is_sqlite else {},
        pool_pre_ping=not is_sqlite,
    )


def ensure_valid_target(postgres_url: str) -> None:
    if not postgres_url.startswith("postgresql"):
        raise ValueError("Target DATABASE_URL must be a PostgreSQL URL starting with 'postgresql'.")


def normalize_value(column, value):
    if value is None:
        return None

    if isinstance(column.type, (JSON, JSONB)) and isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    if isinstance(column.type, DateTime) and isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return value

    if isinstance(column.type, Boolean) and isinstance(value, int):
        return bool(value)

    return value


def table_has_rows(engine: Engine, table_name: str) -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(text(f'SELECT 1 FROM "{table_name}" LIMIT 1')).scalar())


def reset_sequence(conn, table_name: str, pk_column: str) -> None:
    conn.execute(
        text(
            f"""
            SELECT setval(
                pg_get_serial_sequence('public.{table_name}', '{pk_column}'),
                COALESCE((SELECT MAX("{pk_column}") FROM "{table_name}"), 1),
                (SELECT COUNT(*) > 0 FROM "{table_name}")
            )
            """
        )
    )


def migrate_table(source_conn, target_conn, source_table, target_table, batch_size: int) -> int:
    inserted = 0
    batch = []

    result = source_conn.execution_options(stream_results=True).execute(select(source_table)).mappings()
    for row in result:
        payload = {
            column.name: normalize_value(target_table.c[column.name], row[column.name])
            for column in target_table.columns
            if column.name in row
        }
        batch.append(payload)

        if len(batch) >= batch_size:
            target_conn.execute(insert(target_table), batch)
            inserted += len(batch)
            batch = []

    if batch:
        target_conn.execute(insert(target_table), batch)
        inserted += len(batch)

    return inserted


def main():
    parser = argparse.ArgumentParser(description="Copy ERP AI app data from SQLite into PostgreSQL.")
    parser.add_argument(
        "--sqlite-path",
        default="erp_ai_memory.db",
        help="Path to the source SQLite database file.",
    )
    parser.add_argument(
        "--postgres-url",
        required=True,
        help="Target PostgreSQL SQLAlchemy URL, for example postgresql+psycopg://user:pass@127.0.0.1:5432/erp_ai",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="How many rows to insert per batch.",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_path).resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")

    ensure_valid_target(args.postgres_url)

    source_engine = build_engine(f"sqlite:///{sqlite_path.as_posix()}")
    target_engine = build_engine(args.postgres_url)

    Base.metadata.create_all(bind=target_engine)

    source_meta = MetaData()
    source_meta.reflect(bind=source_engine)
    target_meta = MetaData()
    target_meta.reflect(bind=target_engine)

    ordered_table_names = [table.name for table in Base.metadata.sorted_tables]
    source_tables = set(inspect(source_engine).get_table_names())
    target_tables = set(inspect(target_engine).get_table_names())

    missing_in_source = [name for name in ordered_table_names if name not in source_tables]
    if missing_in_source:
        print(f"Skipping tables not present in source SQLite DB: {', '.join(missing_in_source)}")

    existing_target_tables = [name for name in ordered_table_names if name in target_tables and table_has_rows(target_engine, name)]
    if existing_target_tables:
        raise RuntimeError(
            "Target PostgreSQL database already has data in these tables: "
            + ", ".join(existing_target_tables)
            + ". Use an empty database for the first migration."
        )

    copied_counts = {}
    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        for table_name in ordered_table_names:
            if table_name not in source_tables or table_name not in target_tables:
                continue

            source_table = source_meta.tables[table_name]
            target_table = target_meta.tables[table_name]
            copied_counts[table_name] = migrate_table(
                source_conn,
                target_conn,
                source_table,
                target_table,
                batch_size=args.batch_size,
            )

        for table_name in ordered_table_names:
            if table_name not in target_tables:
                continue

            table = target_meta.tables[table_name]
            pk_columns = list(table.primary_key.columns)
            if len(pk_columns) != 1:
                continue
            if not isinstance(pk_columns[0].type, Integer):
                continue

            reset_sequence(target_conn, table_name, pk_columns[0].name)

    print("SQLite to PostgreSQL migration completed successfully.")
    for table_name, count in copied_counts.items():
        print(f"- {table_name}: {count} row(s) copied")


if __name__ == "__main__":
    main()
