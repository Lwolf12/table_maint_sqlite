# table_maint_sqlite

General-purpose **SQLite table maintenance** for Windows: browse, sort, add, edit, and delete rows in **any** table using a **dynamic schema** (no hard-coded columns).

## What you get

- **List window** — a main grid with every column visible, default sort by the table’s key column(s), and **multi-column sorting** (click headers; Ctrl+click for compound order).
- **Detail window** — a separate, non-modal **record editor** where fields are laid out **vertically** (one control per column, driven by the live table schema). Nullable columns include an explicit **NULL** option so you can clear values where SQLite allows it.
- **Recent databases & session restore** — a **most-recently-used (MRU)** list of database file paths (with a history dropdown), plus **last-session** recall of the database path and table name so you are not retyping paths every time. Storage details are in **`Project_spec.txt`** §9.2.

The two views share the same database and table context, so you can move between browsing and editing without losing your place.

## Stack

**Python 3** and **PySide6 (Qt)**. Designed for **Windows 11**; usable as a **standalone app** or **embedded** in another Python program that already runs a Qt event loop.

## Quick start

```text
python -m table_maint              # main list (optional: -d database -t table -r id)
python main.py                     # same entry point as above
python -m table_maint -w edit      # editor / small launcher shell
```

For composite primary keys, repeat `-r` once per key column, in key order.

## Specification

Authoritative behavior, CLI options, NULL/NOT NULL rules, and record-key detection are documented in **`Project_spec.txt`**. For developers, **`CLAUDE.md`** maps those requirements to the main Python modules.
