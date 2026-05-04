"""Main list view: browse SQLite tables with sorting and non-modal edit."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from table_maint import core
from table_maint import history as history_store
from table_maint.controls import DatabaseTableControls
from table_maint.edit_window import RecordEditWindow
from table_maint.flat_model import FlatTableModel
from table_maint.messages import confirm_yes_default, show_non_blocking, show_warning


def _connect(path: str) -> sqlite3.Connection:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Database file not found: {path}")
    conn = sqlite3.connect(str(p))
    return conn


class TableMaintMainWindow(QMainWindow):
    def __init__(
        self,
        database_path: str | None = None,
        table_name: str | None = None,
        record_id: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowTitle("SQLite table maintenance")
        self.resize(960, 560)

        self._pending_record_key_raw: Any | None = record_id
        self._sort_keys: list[tuple[int, Qt.SortOrder]] = []
        self._key_columns: tuple[str, ...] | None = None
        self._key_column_indexes: list[int] = []
        self._schema_columns: list[core.ColumnInfo] | None = None
        # parent=None editors must be retained here; else Python GC closes them.
        self._open_edit_windows: list[RecordEditWindow] = []

        self._controls = DatabaseTableControls()
        self._table = QTableView()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self._table.setSortingEnabled(False)
        self._model = FlatTableModel()
        self._table.setModel(self._model)

        hdr = self._table.horizontalHeader()
        hdr.setSectionsClickable(True)
        hdr.sectionClicked.connect(self._on_header_clicked)

        self._status = QLabel("")
        self._status.setMinimumWidth(240)

        btn_row = QHBoxLayout()
        self._btn_refresh = QPushButton("Refresh")
        self._btn_add = QPushButton("Add…")
        self._btn_edit = QPushButton("Edit…")
        self._btn_delete = QPushButton("Delete…")
        self._btn_copy_id = QPushButton("Copy ID")
        btn_row.addWidget(self._btn_refresh)
        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_edit)
        btn_row.addWidget(self._btn_delete)
        btn_row.addWidget(self._btn_copy_id)
        btn_row.addStretch(1)
        btn_row.addWidget(self._status)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self._controls)
        layout.addWidget(self._table, 1)
        layout.addLayout(btn_row)
        self.setCentralWidget(central)

        self._controls.context_changed.connect(self.reload_from_controls)
        self._btn_refresh.clicked.connect(self.reload_from_controls)
        self._btn_add.clicked.connect(self._on_add)
        self._btn_edit.clicked.connect(self._on_edit)
        self._btn_delete.clicked.connect(self._on_delete_selected)
        self._btn_copy_id.clicked.connect(self._on_copy_id)
        self._table.doubleClicked.connect(self._on_table_double_clicked)

        if database_path is not None:
            self._controls.set_database_path(database_path)
        else:
            ldb = history_store.get_last_database_path()
            if ldb:
                self._controls.set_database_path(ldb)

        if table_name is not None:
            self._controls.set_table_name(table_name)
        else:
            ltb = history_store.get_last_table_name()
            if ltb:
                self._controls.set_table_name(ltb)

        self._controls.refresh_history()
        self.reload_from_controls()

    def _retain_edit_window(self, w: RecordEditWindow) -> None:
        self._open_edit_windows.append(w)

        def _on_destroyed() -> None:
            try:
                self._open_edit_windows.remove(w)
            except ValueError:
                pass

        w.destroyed.connect(_on_destroyed)

    def _on_header_clicked(self, section: int) -> None:
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            self._add_sort_column(section)
        else:
            self._set_single_sort(section)

    def _set_single_sort(self, section: int) -> None:
        if (
            len(self._sort_keys) == 1
            and self._sort_keys[0][0] == section
        ):
            col, order = self._sort_keys[0]
            new_order = (
                Qt.SortOrder.DescendingOrder
                if order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
            self._sort_keys = [(section, new_order)]
        else:
            self._sort_keys = [(section, Qt.SortOrder.AscendingOrder)]
        self._reload_data()

    def _add_sort_column(self, section: int) -> None:
        filtered = [x for x in self._sort_keys if x[0] != section]
        self._sort_keys = filtered + [(section, Qt.SortOrder.AscendingOrder)]
        self._reload_data()

    def reload_from_controls(self) -> None:
        self._reload_data()

    def _reload_data(self) -> None:
        path = self._controls.database_path().strip()
        table = self._controls.table_name().strip()
        self._status.setStyleSheet("")
        self._status.setText("")

        if not path:
            self._model.set_data([], [])
            self._key_columns = None
            self._key_column_indexes = []
            self._schema_columns = None
            return

        db_file = Path(path)
        if not db_file.is_file():
            self._status.setStyleSheet("color: #b00020;")
            self._status.setText(f"Database file not found: {path}")
            self._model.set_data([], [])
            self._key_columns = None
            self._key_column_indexes = []
            self._schema_columns = None
            return

        if not table:
            self._model.set_data([], [])
            self._key_columns = None
            self._key_column_indexes = []
            self._schema_columns = None
            history_store.remember_database_path(path)
            return

        try:
            core.validate_table_name(table)
        except ValueError:
            self._model.set_data([], [])
            self._key_columns = None
            self._key_column_indexes = []
            self._schema_columns = None
            history_store.remember_database_path(path)
            return

        conn: sqlite3.Connection | None = None
        try:
            conn = _connect(path)
        except (OSError, FileNotFoundError) as e:
            self._status.setStyleSheet("color: #b00020;")
            self._status.setText(str(e))
            self._model.set_data([], [])
            self._key_columns = None
            self._key_column_indexes = []
            history_store.remember_database_path(path)
            return

        try:
            key_cols = core.resolve_key_columns(conn, table)
            cols = core.fetch_columns(conn, table)
            headers = [c.name for c in cols]
            self._key_columns = key_cols
            self._key_column_indexes = [headers.index(c) for c in key_cols]

            order_parts: list[str] = []
            for col_idx, order in self._sort_keys:
                if 0 <= col_idx < len(headers):
                    name = headers[col_idx]
                    dire = "ASC" if order == Qt.SortOrder.AscendingOrder else "DESC"
                    order_parts.append(f"{core.quote_ident(name)} {dire}")
            if not order_parts:
                for kc in key_cols:
                    order_parts.append(f"{core.quote_ident(kc)} ASC")

            qtab = core.quote_ident(table)
            sql = f"SELECT * FROM {qtab} ORDER BY " + ", ".join(order_parts)
            cur = conn.execute(sql)
            rows = [list(r) for r in cur.fetchall()]
        except Exception:  # noqa: BLE001 — invalid table for DB, schema issues, etc.
            self._model.set_data([], [])
            self._key_columns = None
            self._key_column_indexes = []
            self._schema_columns = None
            history_store.remember_database_path(path)
            return
        finally:
            if conn is not None:
                conn.close()

        self._model.set_data(headers, rows)
        self._schema_columns = cols
        self._controls.remember_current_path()

        self._apply_pending_scroll()
        hint = f"{len(rows)} row(s)"
        if self._sort_keys:
            hint += f" · sort: {len(self._sort_keys)} key(s)"
        self._status.setStyleSheet("")
        self._status.setText(hint)

    def _apply_pending_scroll(self) -> None:
        raw = self._pending_record_key_raw
        kc = self._key_columns
        cols = self._schema_columns
        if raw is None or not self._model.rows or not kc or not cols:
            return
        parsed = core.parse_record_key(raw, kc, cols)
        if parsed is None:
            return
        idxs = self._key_column_indexes
        if len(parsed) != len(idxs):
            return
        target_row = None
        for i, row in enumerate(self._model.rows):
            if any(ix >= len(row) for ix in idxs):
                continue
            if all(
                core.values_equal(row[idxs[j]], parsed[j]) for j in range(len(idxs))
            ):
                target_row = i
                break
        if target_row is None:
            return
        self._pending_record_key_raw = None
        index = self._model.index(target_row, 0)
        self._table.setCurrentIndex(index)
        self._table.scrollTo(index)

    def _selected_row_indexes(self) -> list[int]:
        sm = self._table.selectionModel()
        if sm is None:
            return []
        return sorted({ix.row() for ix in sm.selectedRows()})

    def _on_table_double_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        self._open_edit_windows_for_rows([index.row()])

    def _open_edit_windows_for_rows(self, row_indexes: list[int]) -> None:
        path = self._controls.database_path()
        table = self._controls.table_name()
        if not path or not table:
            show_non_blocking(self, "Edit", "Choose a database and table first.")
            return
        if not row_indexes:
            show_non_blocking(self, "Edit", "Select at least one row.")
            return
        try:
            core.validate_table_name(table)
            conn = _connect(path)
            key_cols = core.resolve_key_columns(conn, table)
            cols = core.fetch_columns(conn, table)
            conn.close()
        except Exception as e:  # noqa: BLE001
            show_warning(self, "Edit", str(e))
            return

        headers = self._model.headers
        for r in row_indexes:
            if r < 0 or r >= len(self._model.rows):
                continue
            row = self._model.rows[r]
            values = {headers[i]: row[i] for i in range(len(headers))}
            w = RecordEditWindow(
                database_path=path,
                table_name=table,
                key_column_names=key_cols,
                columns=cols,
                mode="update",
                initial_values=values,
                parent=None,
            )
            w.record_saved.connect(self._reload_data)
            w.record_deleted.connect(self._reload_data)
            self._retain_edit_window(w)
            w.show()
            w.raise_()
            w.activateWindow()

    def _on_delete_selected(self) -> None:
        path = self._controls.database_path().strip()
        table = self._controls.table_name().strip()
        if not path or not table:
            show_non_blocking(self, "Delete", "Choose a database and table first.")
            return
        rows = self._selected_row_indexes()
        if not rows:
            show_non_blocking(self, "Delete", "Select one or more rows to delete.")
            return
        key_cols = self._key_columns
        idxs = self._key_column_indexes
        if not key_cols or not idxs or not self._model.headers:
            show_non_blocking(self, "Delete", "Load a table first.")
            return

        keys: list[tuple[Any, ...]] = []
        seen: set[tuple[tuple[str, str], ...]] = set()
        for r in rows:
            if r >= len(self._model.rows):
                continue
            row = self._model.rows[r]
            if any(ix >= len(row) for ix in idxs):
                continue
            tup = tuple(row[ix] for ix in idxs)
            sig = tuple((type(v).__name__, str(v)) for v in tup)
            if sig in seen:
                continue
            seen.add(sig)
            keys.append(tup)

        if not keys:
            show_non_blocking(self, "Delete", "Could not read key values for the selection.")
            return

        n = len(keys)
        msg = (
            f"Delete {n} row(s) from {table!r}?"
            if n > 1
            else f"Delete this row from {table!r}?"
        )
        if not confirm_yes_default(self, "Delete rows", msg):
            return

        try:
            core.validate_table_name(table)
            conn = _connect(path)
            qtab = core.quote_ident(table)
            where_sql = core.sql_key_where(key_cols)
            for tup in keys:
                conn.execute(f"DELETE FROM {qtab} WHERE {where_sql}", tup)
            conn.commit()
            conn.close()
        except (sqlite3.Error, OSError) as e:
            show_warning(self, "Delete", str(e))
            return

        self._reload_data()

    def _on_add(self) -> None:
        path = self._controls.database_path()
        table = self._controls.table_name()
        if not path or not table:
            show_non_blocking(self, "Add", "Choose a database and table first.")
            return
        try:
            core.validate_table_name(table)
            conn = _connect(path)
            key_cols = core.resolve_key_columns(conn, table)
            cols = core.fetch_columns(conn, table)
            conn.close()
        except Exception as e:  # noqa: BLE001
            show_warning(self, "Add", str(e))
            return

        initial: dict[str, Any] = {}
        headers = self._model.headers
        sel = self._selected_row_indexes()
        if (
            sel
            and headers
            and self._model.rows
        ):
            r = sel[0]
            if 0 <= r < len(self._model.rows):
                row = self._model.rows[r]
                initial = {headers[i]: row[i] for i in range(len(headers))}

        w = RecordEditWindow(
            database_path=path,
            table_name=table,
            key_column_names=key_cols,
            columns=cols,
            mode="insert",
            initial_values=initial,
            parent=None,
        )
        w.record_saved.connect(self._reload_data)
        w.record_deleted.connect(self._reload_data)
        self._retain_edit_window(w)
        w.show()
        w.raise_()
        w.activateWindow()

    def _on_edit(self) -> None:
        self._open_edit_windows_for_rows(self._selected_row_indexes())

    def _on_copy_id(self) -> None:
        if not self._key_columns or not self._model.rows:
            show_non_blocking(self, "Copy ID", "Load a table with data first.")
            return
        row_indexes = self._selected_row_indexes()
        if not row_indexes:
            show_non_blocking(self, "Copy ID", "Select a row first.")
            return
        r = row_indexes[0]
        idxs = self._key_column_indexes
        if r < 0 or r >= len(self._model.rows):
            show_non_blocking(self, "Copy ID", "Invalid selection.")
            return
        row = self._model.rows[r]
        if any(ix >= len(row) for ix in idxs):
            show_non_blocking(self, "Copy ID", "Could not read key columns.")
            return
        parts = [core.value_as_line_edit_text(row[ix]) for ix in idxs]
        text = "\t".join(parts)
        QApplication.clipboard().setText(text)
        if any(parts):
            self._status.setText("Record key copied to clipboard")
        else:
            self._status.setText("Copied empty key to clipboard")
