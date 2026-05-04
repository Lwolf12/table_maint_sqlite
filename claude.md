# table_maint_sqlite — AI / contributor orientation

Use this file together with **`Project_spec.txt`**, which is the authoritative functional specification. When behavior or UX is unclear, prefer reading the referenced source modules over guessing.

## What this is

A **PySide6 (Qt)** desktop tool to **browse, sort, add, edit, and delete** rows in **any SQLite table**, using **dynamic schema** (no hard-coded columns). Target platform: **Windows 11**; implementation: **Python 3**.

## How to run

- List (main grid): `python -m table_maint` or `python main.py` — optional `-d`, `-t`, `-r` (repeat `-r` once per key column for composite keys).
- Edit window / launcher: `python -m table_maint -w edit` (with `-d`/`-t` opens the form directly).
- Package entry re-exports CLI via `table_maint.__main__.main`.

CLI details: `table_maint/__main__.py`.

## Layout (important files)

| Path | Role |
|------|------|
| `table_maint/main_window.py` | **TableMaintMainWindow** — list view, sorting, Add/Edit/Delete, opens **RecordEditWindow**. |
| `table_maint/edit_window.py` | **RecordEditWindow** — dynamic per-column form; insert vs update; **DatabaseTableControls** in the header. |
| `table_maint/core.py` | Schema helpers: **`resolve_key_columns`** (composite PK supported), quoting, SQL helpers, parsing, NULL/default rules for SQL generation. |
| `table_maint/controls.py` | **DatabaseTableControls** — shared DB path, table name, browse, history. |
| `table_maint/flat_model.py` | **FlatTableModel** — headers + rows for `QTableView`. |
| `table_maint/history.py` | MRU DB paths and last session (see spec §9.2). |
| `table_maint/messages.py` | Non-blocking confirmations / warnings where possible. |

## Record key (“ID”)

- The app supports **composite primary keys** via `resolve_key_columns` — a tuple of column names in PK order.
- **List positioning** and CLI: pass one `-r` value per key column, in that order.
- **Copy ID** / clipboard uses tab-separated key parts.

## Add vs Edit (critical semantics)

- **Edit…** / double-click: opens **update** mode with values loaded from DB (or from the selected row’s display values in the grid).
- **Add…** opens **insert** mode.
  - **With row selection:** fields pre-fill from the **topmost selected row** (minimum row index among selected rows). Still **insert** — user must change keys if they would duplicate an existing row. **`_original_key` is not set in insert mode**, so Delete does not treat the form as editing an existing row.
  - **No selection:** empty form per spec: NULLable columns use NULL checkbox; keys and required NOT NULL fields follow validation in `RecordEditWindow._collect_values` / `core.omit_column_for_sqlite_default`.

Implementation touchpoints: `TableMaintMainWindow._on_add`, `RecordEditWindow.__init__` (`_original_key` only for `mode == "update"`).

## UI philosophy

- **Non-modal** editors and routine feedback (avoid blocking the whole app for ordinary messages).
- Main list and edit windows both embed the same **database/table controls**; changing context reloads schema/form where implemented (`_reload_form_after_context_change` in edit window).

## Dependencies

- **PySide6** (Qt for Python). A project venv may exist under `.venv`.

## Testing / verification

There is no automated test suite called out here; manual checks: open a DB, load a table, sort, Add with/without selection, Edit, Delete, composite key table if available.
