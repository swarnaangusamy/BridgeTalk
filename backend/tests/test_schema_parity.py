"""Guards against `database/schema.sql` drifting from the SQLAlchemy models.

Two independent descriptions of the same tables exist in this project:

* `database/schema.sql` — what you actually run in MySQL Workbench
* `backend/app/models/` — what the application reads and writes

Nothing forces them to agree. A column added to one and forgotten in the other
produces a confusing runtime error ("Unknown column 'x' in field list") far away
from the change that caused it. This test makes that drift a failing test
instead.

It compares table names, column names and ENUM value sets — the parts that
break code. It deliberately does not compare types, index plans or engine
options, because SQLite and MySQL legitimately spell those differently.
"""

import re
from pathlib import Path

import pytest
from sqlalchemy import Enum as SAEnum

from app.database import Base
from app import models  # noqa: F401  (import registers every table on Base.metadata)

SCHEMA_SQL = Path(__file__).resolve().parents[2] / "database" / "schema.sql"

# Lines inside a CREATE TABLE body that define constraints/indexes rather than
# columns. Everything else in the body is treated as a column definition.
_NON_COLUMN_PREFIXES = (
    "primary key",
    "unique key",
    "unique",
    "key ",
    "index ",
    "constraint",
    "foreign key",
)


def _strip_sql_comments(sql: str) -> str:
    """Remove `-- …` line comments so they cannot be mistaken for columns."""
    return re.sub(r"--[^\n]*", "", sql)


def _parse_schema_sql() -> dict[str, set[str]]:
    """Return {table_name: {column_name, …}} as declared in schema.sql."""
    sql = _strip_sql_comments(SCHEMA_SQL.read_text(encoding="utf-8"))

    tables: dict[str, set[str]] = {}
    # Match `CREATE TABLE IF NOT EXISTS name ( … )` up to the closing paren that
    # is followed by ENGINE=, which is how every table in our file terminates.
    pattern = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?\s*\((.*?)\)\s*ENGINE=",
        re.IGNORECASE | re.DOTALL,
    )

    for table_name, body in pattern.findall(sql):
        columns: set[str] = set()
        depth = 0
        current = ""
        # Split the body on top-level commas only. A naive split(",") would cut
        # ENUM('deaf','hearing') in half.
        for char in body:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1

            if char == "," and depth == 0:
                columns.add(current)
                current = ""
            else:
                current += char
        columns.add(current)

        parsed = set()
        for definition in columns:
            cleaned = definition.strip()
            if not cleaned:
                continue
            if cleaned.lower().startswith(_NON_COLUMN_PREFIXES):
                continue
            parsed.add(cleaned.split()[0].strip("`"))

        tables[table_name] = parsed

    return tables


def _parse_schema_enums() -> dict[tuple[str, str], set[str]]:
    """Return {(table, column): {enum value, …}} as declared in schema.sql."""
    sql = _strip_sql_comments(SCHEMA_SQL.read_text(encoding="utf-8"))
    enums: dict[tuple[str, str], set[str]] = {}

    table_pattern = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?\s*\((.*?)\)\s*ENGINE=",
        re.IGNORECASE | re.DOTALL,
    )
    enum_pattern = re.compile(r"`?(\w+)`?\s+ENUM\s*\(([^)]*)\)", re.IGNORECASE)

    for table_name, body in table_pattern.findall(sql):
        for column_name, values in enum_pattern.findall(body):
            enums[(table_name, column_name)] = {
                value.strip().strip("'\"") for value in values.split(",")
            }

    return enums


@pytest.fixture(scope="module")
def sql_tables() -> dict[str, set[str]]:
    tables = _parse_schema_sql()
    assert tables, f"Parsed no tables out of {SCHEMA_SQL} — has the file moved or changed shape?"
    return tables


def test_schema_sql_file_exists():
    assert SCHEMA_SQL.is_file(), f"Missing {SCHEMA_SQL}"


def test_same_tables_in_both_places(sql_tables):
    orm_tables = set(Base.metadata.tables)
    assert orm_tables == set(sql_tables), (
        "database/schema.sql and backend/app/models/ describe different tables.\n"
        f"  only in models:     {sorted(orm_tables - set(sql_tables))}\n"
        f"  only in schema.sql: {sorted(set(sql_tables) - orm_tables)}"
    )


def test_same_columns_in_every_table(sql_tables):
    for table_name, table in Base.metadata.tables.items():
        orm_columns = {column.name for column in table.columns}
        sql_columns = sql_tables[table_name]
        assert orm_columns == sql_columns, (
            f"Column mismatch in '{table_name}'.\n"
            f"  only in models:     {sorted(orm_columns - sql_columns)}\n"
            f"  only in schema.sql: {sorted(sql_columns - orm_columns)}"
        )


def test_enum_values_match():
    """ENUM value sets must agree exactly.

    This is the specific failure the `values_callable` argument on our ORM enum
    columns exists to prevent: without it SQLAlchemy would write 'DEAF' where
    schema.sql declares 'deaf', and rows created by the API would not match
    rows created by seed.sql.
    """
    sql_enums = _parse_schema_enums()
    assert sql_enums, "Parsed no ENUM columns out of schema.sql"

    for table_name, table in Base.metadata.tables.items():
        for column in table.columns:
            if not isinstance(column.type, SAEnum):
                continue

            key = (table_name, column.name)
            assert key in sql_enums, f"{table_name}.{column.name} is an ENUM in the ORM only"

            orm_values = set(column.type.enums)
            assert orm_values == sql_enums[key], (
                f"ENUM values differ for {table_name}.{column.name}.\n"
                f"  models:     {sorted(orm_values)}\n"
                f"  schema.sql: {sorted(sql_enums[key])}"
            )
