"""SQLite schema introspection, ID column resolution, and safe SQL identifiers."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Sequence

_VALID_TABLE_RE = re.compile(r"^[A-Za-z0-9_]+$")


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def validate_table_name(name: str) -> None:
    if not name or not _VALID_TABLE_RE.match(name):
        raise ValueError(
            "Table name must contain only letters, digits, and underscores."
        )


def list_user_tables(conn: sqlite3.Connection) -> list[str]:
    """User table names from sqlite_master (excludes internal sqlite_* tables)."""
    cur = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite%'
        ORDER BY name COLLATE NOCASE
        """
    )
    return [row[0] for row in cur.fetchall()]


@dataclass(frozen=True)
class ColumnInfo:
    cid: int
    name: str
    type_name: str
    notnull: bool
    default_value: Any
    pk: int  # 0 if not PK, 1-based position in PK for composite


def fetch_columns(conn: sqlite3.Connection, table: str) -> list[ColumnInfo]:
    validate_table_name(table)
    q = quote_ident(table)
    cur = conn.execute(f"PRAGMA table_info({q})")
    rows = cur.fetchall()
    out: list[ColumnInfo] = []
    for cid, name, ctype, notnull, dflt, pk in rows:
        out.append(
            ColumnInfo(
                cid=cid,
                name=name,
                type_name=(ctype or "").upper(),
                notnull=bool(notnull),
                default_value=dflt,
                pk=int(pk),
            )
        )
    return out


def _single_column_unique_indexes(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    """Map column name -> index name for unique indexes that cover exactly one column."""
    validate_table_name(table)
    q = quote_ident(table)
    cur = conn.execute(f"PRAGMA index_list({q})")
    index_rows = cur.fetchall()
    result: dict[str, str] = {}
    for seq, name, unique, *_ in index_rows:
        if not unique:
            continue
        info_cur = conn.execute(f"PRAGMA index_info({quote_ident(name)})")
        parts = info_cur.fetchall()
        if len(parts) != 1:
            continue
        col_name = parts[0][2]
        if col_name not in result:
            result[col_name] = name
    return result


def _unique_indexes_ordered_columns(
    conn: sqlite3.Connection, table: str
) -> list[tuple[str, tuple[str, ...]]]:
    """Unique indexes as (index_name, column_names_in_index_order), sorted by index name."""
    validate_table_name(table)
    q = quote_ident(table)
    cur = conn.execute(f"PRAGMA index_list({q})")
    out: list[tuple[str, tuple[str, ...]]] = []
    for _seq, name, unique, *_ in cur.fetchall():
        if not unique:
            continue
        info_cur = conn.execute(f"PRAGMA index_info({quote_ident(name)})")
        parts = sorted(info_cur.fetchall(), key=lambda r: int(r[0]))
        col_names = tuple(str(p[2]) for p in parts if p[2] is not None)
        if col_names:
            out.append((name, col_names))
    out.sort(key=lambda t: t[0].lower())
    return out


def sql_key_where(key_columns: Sequence[str]) -> str:
    """``col1 = ? AND col2 = ?`` for bound parameters."""
    return " AND ".join(f"{quote_ident(c)} = ?" for c in key_columns)


def resolve_key_columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    """
    Columns that identify a row, in order:

    - All PRIMARY KEY columns (composite allowed), in PK order from ``PRAGMA table_info``
    - Else the first single-column UNIQUE in table column order (same as before)
    - Else the first multi-column UNIQUE index (SQLite index name order)
    """
    cols = fetch_columns(conn, table)
    if not cols:
        raise ValueError(f"Table {table!r} has no columns.")

    pk_cols = [c for c in cols if c.pk > 0]
    if pk_cols:
        pk_cols.sort(key=lambda c: c.pk)
        return tuple(c.name for c in pk_cols)

    unique_map = _single_column_unique_indexes(conn, table)
    for c in cols:
        if c.name in unique_map:
            return (c.name,)

    for _idx_name, col_names in _unique_indexes_ordered_columns(conn, table):
        if len(col_names) > 1:
            return col_names

    raise ValueError(
        f"Table {table!r} has no primary key and no UNIQUE constraint; "
        "cannot determine a record key."
    )


def resolve_id_column(conn: sqlite3.Connection, table: str) -> str:
    """Backward-compatible: single-column key only; raises if the key is composite."""
    key = resolve_key_columns(conn, table)
    if len(key) != 1:
        raise ValueError(
            "This table uses a composite record key; use resolve_key_columns() "
            "or pass a tuple of key values where supported."
        )
    return key[0]


def column_by_name(columns: Sequence[ColumnInfo], name: str) -> ColumnInfo | None:
    for c in columns:
        if c.name == name:
            return c
    return None


def parse_record_key(
    raw: Any,
    key_columns: Sequence[str],
    columns: Sequence[ColumnInfo],
) -> tuple[Any, ...] | None:
    """
    Parse a user/API record key (scalar or sequence) into a tuple aligned with
    ``key_columns``. Returns ``None`` if parsing fails or shapes mismatch.
    """
    if raw is None:
        return None
    if len(key_columns) == 1:
        if isinstance(raw, (list, tuple)) and len(raw) == 1:
            raw = raw[0]
        ci = column_by_name(columns, key_columns[0])
        if not ci:
            return None
        try:
            v = parse_input_for_column(str(raw).strip(), ci, allow_null=False)
            return (v,)
        except ValueError:
            return None
    if isinstance(raw, (list, tuple)) and len(raw) == len(key_columns):
        out: list[Any] = []
        for i, name in enumerate(key_columns):
            ci = column_by_name(columns, name)
            if not ci:
                return None
            try:
                out.append(
                    parse_input_for_column(str(raw[i]).strip(), ci, allow_null=False)
                )
            except ValueError:
                return None
        return tuple(out)
    return None


def omit_column_for_sqlite_default(
    col: ColumnInfo, *, is_id_column: bool, text_empty: bool
) -> bool:
    """
    When true, the editor value is left out of INSERT/UPDATE so SQLite applies DEFAULT.

    Used for NOT NULL columns with an explicit schema default (PRAGMA table_info dflt_value);
    never for the application ID column, which must always be supplied (spec §5.2).
    """
    if is_id_column or not text_empty:
        return False
    return col.notnull and col.default_value is not None


def format_cell_display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        n = len(value)
        if n == 0:
            return "<BLOB empty>"
        preview = value[:24]
        hex_preview = preview.hex()
        if n > 24:
            hex_preview += "…"
        return f"<BLOB {n} bytes> {hex_preview}"
    return str(value)


def value_as_line_edit_text(value: Any) -> str:
    """Single-line text for editors and clipboard ID copy; BLOB as full hex."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, bytes):
        return "X'" + value.hex() + "'"
    s = str(value)
    return "'" + s.replace("'", "''") + "'"


def values_equal(a: Any, b: Any) -> bool:
    if a == b:
        return True
    try:
        if int(a) == int(b):  # type: ignore[arg-type]
            return True
    except (TypeError, ValueError):
        pass
    try:
        if float(a) == float(b):  # type: ignore[arg-type]
            return True
    except (TypeError, ValueError):
        pass
    return str(a) == str(b)


def parse_input_for_column(
    text: str, col: ColumnInfo, *, allow_null: bool
) -> Any | None:
    """Parse user text into a Python/SQLite value. Returns None for NULL when allowed."""
    stripped = text.strip()
    if stripped == "" and allow_null:
        return None
    if stripped == "" and not allow_null:
        raise ValueError(f"Column {col.name!r} cannot be NULL.")

    t = col.type_name
    if "INT" in t:
        return int(stripped)
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return float(stripped)
    if "BLOB" in t:
        s = stripped
        if s.startswith("0x") or s.startswith("0X"):
            return bytes.fromhex(s[2:])
        return stripped.encode("utf-8", errors="surrogateescape")

    return stripped
