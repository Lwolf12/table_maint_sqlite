"""Non-modal add/edit form with dynamic fields and shared database controls."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from table_maint import core
from table_maint import history as history_store
from table_maint.controls import DatabaseTableControls
from table_maint.messages import (
    confirm_yes_default,
    show_non_blocking,
    show_warning,
)
from table_maint.window_show import show_smoothly


def _connect_rw(path: str) -> sqlite3.Connection:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Database file not found: {path}")
    return sqlite3.connect(str(p))


def record_exists_for_id(
    database_path: str,
    table_name: str,
    record_id: Any,
) -> bool:
    """
    Return whether a row exists for the given record key (scalar for a single key
    column, or a tuple/list aligned with ``resolve_key_columns`` for composite keys).

    Returns ``False`` when the key cannot be parsed or no row matches.
    """
    core.validate_table_name(table_name)
    conn = _connect_rw(database_path)
    try:
        key_cols = core.resolve_key_columns(conn, table_name)
        cols = core.fetch_columns(conn, table_name)
        parsed = core.parse_record_key(record_id, key_cols, cols)
        if parsed is None:
            return False
        qtab = core.quote_ident(table_name)
        where_sql = core.sql_key_where(key_cols)
        cur = conn.execute(
            f"SELECT 1 FROM {qtab} WHERE {where_sql} LIMIT 1",
            parsed,
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def _editor_text_for_value(raw: Any) -> str:
    return core.value_as_line_edit_text(raw)


def launch_record_editor(
    database_path: str,
    table_name: str,
    record_id: Any | None = None,
    parent: QWidget | None = None,
) -> RecordEditWindow:
    """
    Open the add form (``record_id`` is None) or load a row by ID for update.
    """
    core.validate_table_name(table_name)
    conn = _connect_rw(database_path)
    try:
        key_cols = core.resolve_key_columns(conn, table_name)
        cols = core.fetch_columns(conn, table_name)
        qtab = core.quote_ident(table_name)
        where_sql = core.sql_key_where(key_cols)

        if record_id is None:
            return RecordEditWindow(
                database_path=database_path,
                table_name=table_name,
                key_column_names=key_cols,
                columns=cols,
                mode="insert",
                initial_values={},
                parent=parent,
            )

        parsed = core.parse_record_key(record_id, key_cols, cols)
        if parsed is None:
            raise ValueError(f"Invalid record key {record_id!r} for table {table_name!r}.")
        cur = conn.execute(
            f"SELECT * FROM {qtab} WHERE {where_sql} LIMIT 1",
            parsed,
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"No row matching key {record_id!r}.")
        names = [c.name for c in cols]
        initial = {names[i]: row[i] for i in range(len(names))}
        return RecordEditWindow(
            database_path=database_path,
            table_name=table_name,
            key_column_names=key_cols,
            columns=cols,
            mode="update",
            initial_values=initial,
            parent=parent,
        )
    finally:
        conn.close()


class RecordEditWindow(QWidget):
    """Dynamic per-column editors; supports insert and update modes."""

    record_saved = Signal()
    record_deleted = Signal()

    def __init__(
        self,
        database_path: str,
        table_name: str,
        key_column_names: tuple[str, ...],
        columns: list[core.ColumnInfo],
        mode: str,
        initial_values: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # Top-level tool window: non-modal, independent of host (spec §4.1 / §10).
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowTitle("Edit record" if mode == "update" else "Add record")
        self.resize(688, 480)

        self._seq_header_width = 46
        self._value_column_width = 280
        self._null_column_width = 72
        self._seq_muted_style = "color: #6a6a6a; font-size: 11px;"

        self._mode = mode
        self._columns: list[core.ColumnInfo] = columns
        self._key_column_names = key_column_names
        self._key_set = frozenset(key_column_names)
        self._original_key: tuple[Any, ...] | None = None
        if (
            mode == "update"
            and initial_values
            and all(k in initial_values for k in key_column_names)
        ):
            self._original_key = tuple(initial_values[k] for k in key_column_names)

        self._controls = DatabaseTableControls()
        self._controls.set_database_path(database_path)
        self._controls.set_table_name(table_name)

        self._form_host = QWidget()
        self._form_outer = QVBoxLayout(self._form_host)
        self._form_outer.setContentsMargins(0, 0, 0, 0)

        self._header_bar = QWidget()
        hdr = QHBoxLayout(self._header_bar)
        hdr.setContentsMargins(0, 0, 0, 0)
        self._btn_sort_seq = QPushButton("Seq")
        self._btn_sort_seq.setFlat(True)
        self._btn_sort_seq.setFixedWidth(self._seq_header_width)
        self._btn_sort_seq.setStyleSheet(self._seq_muted_style)
        self._btn_sort_seq.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_sort_seq.clicked.connect(self._on_sort_seq_clicked)
        self._btn_sort_name = QPushButton("Field Name")
        self._btn_sort_value = QPushButton("Value")
        for b in (self._btn_sort_name, self._btn_sort_value):
            b.setFlat(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_sort_name.clicked.connect(self._on_sort_name_clicked)
        self._btn_sort_value.clicked.connect(self._on_sort_value_clicked)

        hdr.addWidget(self._btn_sort_seq, 0, Qt.AlignmentFlag.AlignLeft)

        hdr_mid = QWidget()
        hdr_mid.setFixedWidth(self._value_column_width)
        hdr_mid_l = QHBoxLayout(hdr_mid)
        hdr_mid_l.setContentsMargins(0, 0, 0, 0)
        hdr_mid_l.addWidget(self._btn_sort_value)

        self._hdr_null_label = QLabel("NULL")
        self._hdr_null_label.setFixedWidth(self._null_column_width)
        self._hdr_null_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        hdr.addWidget(self._btn_sort_name, 1)
        hdr.addWidget(hdr_mid, 0, Qt.AlignmentFlag.AlignLeft)
        hdr.addWidget(self._hdr_null_label, 0, Qt.AlignmentFlag.AlignLeft)

        self._body_host = QWidget()
        self._body_layout = QVBoxLayout(self._body_host)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(4)

        self._form_outer.addWidget(self._header_bar)
        self._form_outer.addWidget(self._body_host, 1)

        self._body_rows: dict[str, QWidget] = {}
        self._sort_by: str | None = None
        self._sort_asc = True

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._form_host)

        self._btn_list = QPushButton("List view")
        self._btn_copy_id = QPushButton("Copy ID")
        self._btn_apply = QPushButton("Apply changes")
        self._btn_delete = QPushButton("Delete…")
        self._btn_close = QPushButton("Close")
        self._btn_delete.setEnabled(False)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_list)
        btn_row.addWidget(self._btn_copy_id)
        btn_row.addStretch(1)
        btn_row.addWidget(self._btn_apply)
        btn_row.addWidget(self._btn_delete)
        btn_row.addWidget(self._btn_close)

        outer = QVBoxLayout(self)
        outer.addWidget(self._controls)
        outer.addWidget(scroll, 1)
        outer.addLayout(btn_row)

        self._field_lines: dict[str, QLineEdit] = {}
        self._field_nulls: dict[str, QCheckBox | None] = {}
        # Retain "List view" QMainWindow instances: parent=None, else Python may GC them.
        self._list_view_windows: list[QMainWindow] = []

        self._context_reload_timer = QTimer(self)
        self._context_reload_timer.setSingleShot(True)
        self._context_reload_timer.timeout.connect(
            self._reload_form_after_context_change
        )

        self._controls.context_changed.connect(self._on_context_changed)
        self._btn_list.clicked.connect(self._open_list_view)
        self._btn_copy_id.clicked.connect(self._on_copy_id)
        self._btn_apply.clicked.connect(self._apply)
        self._btn_delete.clicked.connect(self._on_delete_record)
        self._btn_close.clicked.connect(self.close)

        self._build_fields(initial_values or {})

    def _value_sort_key(self, col: core.ColumnInfo) -> tuple:
        """
        Sort by value: only rows with NULL checked are grouped as nulls; unchecked
        fields sort by editor text together with other non-null rows.
        """
        nc = self._field_nulls.get(col.name)
        edit = self._field_lines.get(col.name)
        if nc is not None and nc.isChecked():
            return (0, "")
        text = edit.text() if edit else ""
        return (1, text.casefold())

    def _ordered_columns(self) -> list[core.ColumnInfo]:
        cols = list(self._columns)
        if self._sort_by is None:
            return cols
        if self._sort_by == "seq":
            cols.sort(key=lambda c: c.cid, reverse=not self._sort_asc)
            return cols
        if self._sort_by == "name":
            cols.sort(key=lambda c: c.name.casefold(), reverse=not self._sort_asc)
            return cols
        cols.sort(key=self._value_sort_key, reverse=not self._sort_asc)
        return cols

    def _update_sort_buttons(self) -> None:
        base_s = "Seq"
        base_n = "Field Name"
        base_v = "Value"
        if self._sort_by == "seq":
            arrow = " ▲" if self._sort_asc else " ▼"
            self._btn_sort_seq.setText(base_s + arrow)
            self._btn_sort_name.setText(base_n)
            self._btn_sort_value.setText(base_v)
        elif self._sort_by == "name":
            arrow = " ▲" if self._sort_asc else " ▼"
            self._btn_sort_seq.setText(base_s)
            self._btn_sort_name.setText(base_n + arrow)
            self._btn_sort_value.setText(base_v)
        elif self._sort_by == "value":
            arrow = " ▲" if self._sort_asc else " ▼"
            self._btn_sort_seq.setText(base_s)
            self._btn_sort_name.setText(base_n)
            self._btn_sort_value.setText(base_v + arrow)
        else:
            self._btn_sort_seq.setText(base_s)
            self._btn_sort_name.setText(base_n)
            self._btn_sort_value.setText(base_v)

    def _reorder_body_rows(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(self._body_host)
        for col in self._ordered_columns():
            row = self._body_rows.get(col.name)
            if row is not None:
                self._body_layout.addWidget(row)
        self._update_sort_buttons()

    def _on_sort_seq_clicked(self) -> None:
        if self._sort_by != "seq":
            self._sort_by = "seq"
            self._sort_asc = True
        else:
            self._sort_asc = not self._sort_asc
        self._reorder_body_rows()

    def _on_sort_name_clicked(self) -> None:
        if self._sort_by != "name":
            self._sort_by = "name"
            self._sort_asc = True
        else:
            self._sort_asc = not self._sort_asc
        self._reorder_body_rows()

    def _on_sort_value_clicked(self) -> None:
        if self._sort_by != "value":
            self._sort_by = "value"
            self._sort_asc = True
        else:
            self._sort_asc = not self._sort_asc
        self._reorder_body_rows()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._context_reload_timer.stop()
        super().closeEvent(event)

    def _on_copy_id(self) -> None:
        """Copy record key parts to clipboard, tab-separated (same as list view)."""
        if not self._key_column_names:
            show_non_blocking(self, "Copy ID", "No record key is available.")
            return
        if not all(k in self._field_lines for k in self._key_column_names):
            show_non_blocking(self, "Copy ID", "Could not read key fields.")
            return
        parts = [self._field_lines[k].text() for k in self._key_column_names]
        QApplication.clipboard().setText("\t".join(parts))

    def _open_list_view(self) -> None:
        from table_maint.main_window import TableMaintMainWindow

        path = self._controls.database_path().strip()
        table = self._controls.table_name().strip()
        rid: Any | None = None
        parts: list[Any] = []
        if all(k in self._field_lines for k in self._key_column_names):
            try:
                for name in self._key_column_names:
                    raw_txt = self._field_lines[name].text().strip()
                    col_info = core.column_by_name(self._columns, name)
                    if not col_info:
                        parts = []
                        break
                    parts.append(
                        core.parse_input_for_column(
                            raw_txt, col_info, allow_null=False
                        )
                    )
            except ValueError:
                parts = []
        if len(parts) == len(self._key_column_names):
            rid = tuple(parts)
        elif self._original_key is not None:
            rid = self._original_key
        win = TableMaintMainWindow(
            database_path=path or None,
            table_name=table or None,
            record_id=rid,
            parent=None,
        )
        self._list_view_windows.append(win)

        def _on_list_destroyed() -> None:
            try:
                self._list_view_windows.remove(win)
            except ValueError:
                pass

        win.destroyed.connect(_on_list_destroyed)
        show_smoothly(win, raise_=True, activate=True)

    def _clear_form_layout(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._body_rows.clear()
        self._field_lines.clear()
        self._field_nulls.clear()
        self._sort_by = None
        self._sort_asc = True
        self._update_sort_buttons()

    def _build_fields(self, values: dict[str, Any]) -> None:
        self._clear_form_layout()
        for col in self._columns:
            seq_cell = QWidget()
            seq_cell.setFixedWidth(self._seq_header_width)
            seq_inner = QHBoxLayout(seq_cell)
            seq_inner.setContentsMargins(0, 0, 0, 0)
            seq_inner.addStretch(1)
            seq_lbl = QLabel(str(col.cid + 1))
            seq_lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            seq_lbl.setStyleSheet(self._seq_muted_style)
            seq_inner.addWidget(seq_lbl)

            label = f"{col.name} ({col.type_name or 'ANY'})"
            name_lbl = QLabel(label)
            name_lbl.setWordWrap(True)
            name_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            edit = QLineEdit()
            null_cb: QCheckBox | None = None
            is_key = col.name in self._key_set
            if is_key:
                edit.setPlaceholderText("Key (required)")
                edit.textChanged.connect(self._update_delete_button_state)
            raw = values.get(col.name)
            if is_key:
                edit.setText(_editor_text_for_value(raw))
            elif col.notnull:
                edit.setText(_editor_text_for_value(raw))
            else:
                null_cb = QCheckBox("NULL")
                if raw is None:
                    null_cb.setChecked(True)
                    edit.setEnabled(False)
                else:
                    edit.setText(_editor_text_for_value(raw))
                null_cb.toggled.connect(
                    lambda checked, e=edit: self._null_toggled(e, checked)
                )

            edit.setFixedWidth(self._value_column_width)
            edit.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
            )

            null_cell = QWidget()
            null_cell.setFixedWidth(self._null_column_width)
            null_l = QHBoxLayout(null_cell)
            null_l.setContentsMargins(0, 0, 0, 0)
            if null_cb is not None:
                null_l.addWidget(null_cb, 0, Qt.AlignmentFlag.AlignLeft)
            else:
                null_l.addStretch(1)

            row_widget = QWidget()
            row_h = QHBoxLayout(row_widget)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.addWidget(seq_cell, 0, Qt.AlignmentFlag.AlignLeft)
            row_h.addWidget(name_lbl, 1)
            row_h.addWidget(edit, 0, Qt.AlignmentFlag.AlignLeft)
            row_h.addWidget(null_cell, 0, Qt.AlignmentFlag.AlignLeft)

            self._body_rows[col.name] = row_widget
            self._field_lines[col.name] = edit
            self._field_nulls[col.name] = null_cb

        for col in self._ordered_columns():
            self._body_layout.addWidget(self._body_rows[col.name])

        self._update_delete_button_state()
        QTimer.singleShot(0, self._focus_first_field)

    def _focus_first_field(self) -> None:
        """Focus first editable control in current display order (after show/layout)."""
        for col in self._ordered_columns():
            edit = self._field_lines.get(col.name)
            null_cb = self._field_nulls.get(col.name)
            if edit is not None and edit.isEnabled():
                edit.setFocus(Qt.FocusReason.OtherFocusReason)
                return
            if null_cb is not None:
                null_cb.setFocus(Qt.FocusReason.OtherFocusReason)
                return

    def _null_toggled(self, edit: QLineEdit, checked: bool) -> None:
        edit.setEnabled(not checked)
        if checked:
            edit.clear()

    def _on_context_changed(self) -> None:
        # Run after the current event (focus out, editingFinished, etc.) so the
        # form is not torn down synchronously during Qt input handling — avoids
        # rare native crashes on Windows. Rapid changes coalesce to one reload.
        self._context_reload_timer.start(0)

    def _reload_form_after_context_change(self) -> None:
        path = self._controls.database_path()
        table = self._controls.table_name()
        key_texts: list[str] = []
        if all(k in self._field_lines for k in self._key_column_names):
            key_texts = [self._field_lines[k].text().strip() for k in self._key_column_names]

        if not path or not table:
            self._columns = []
            self._clear_form_layout()
            self._update_delete_button_state()
            return
        conn: sqlite3.Connection | None = None
        try:
            core.validate_table_name(table)
            conn = _connect_rw(path)
            key_cols = core.resolve_key_columns(conn, table)
            cols = core.fetch_columns(conn, table)
        except (OSError, FileNotFoundError) as e:
            self._controls.show_error("Database", str(e))
            self._update_delete_button_state()
            return
        except Exception as e:  # noqa: BLE001
            self._controls.show_error("Schema", str(e))
            self._update_delete_button_state()
            return
        finally:
            if conn is not None:
                conn.close()

        self._columns = cols
        self._key_column_names = key_cols
        self._key_set = frozenset(key_cols)

        if self._mode == "insert":
            self._build_fields({})
            return

        raw_key = (
            tuple(key_texts)
            if key_texts and all(t != "" for t in key_texts)
            else None
        )
        probe = (
            core.parse_record_key(raw_key, key_cols, cols) if raw_key is not None else None
        )
        if probe is None and self._original_key is not None:
            probe = core.parse_record_key(self._original_key, key_cols, cols)

        if probe is None:
            self._original_key = None
            self._build_fields({})
            return

        conn2: sqlite3.Connection | None = None
        values: dict[str, Any] = {}
        try:
            conn2 = _connect_rw(path)
            qtab = core.quote_ident(table)
            where_sql = core.sql_key_where(key_cols)
            cur = conn2.execute(
                f"SELECT * FROM {qtab} WHERE {where_sql} LIMIT 1",
                probe,
            )
            row = cur.fetchone()
            if row:
                names = [c.name for c in cols]
                values = {names[i]: row[i] for i in range(len(names))}
                self._original_key = tuple(values[k] for k in key_cols)
            else:
                self._original_key = None
        except Exception as e:  # noqa: BLE001
            self._controls.show_error("Reload", str(e))
            values = {}
            self._original_key = None
        finally:
            if conn2 is not None:
                conn2.close()

        self._build_fields(values)

    def _can_delete_row(self) -> tuple[bool, tuple[Any, ...] | None]:
        """Whether delete is allowed and key values to use in DELETE."""
        path = self._controls.database_path().strip()
        table = self._controls.table_name().strip()
        if not path or not table or not self._columns:
            return False, None
        kc = self._key_column_names
        if not all(k in self._field_lines for k in kc):
            return False, None
        if self._mode == "update" and self._original_key is not None:
            return True, self._original_key
        vals: list[Any] = []
        for name in kc:
            col_info = core.column_by_name(self._columns, name)
            if not col_info:
                return False, None
            raw = self._field_lines[name].text().strip()
            if raw == "":
                return False, None
            try:
                vals.append(
                    core.parse_input_for_column(raw, col_info, allow_null=False)
                )
            except ValueError:
                return False, None
        tup = tuple(vals)
        if record_exists_for_id(path, table, tup):
            return True, tup
        return False, None

    def _update_delete_button_state(self) -> None:
        ok, _ = self._can_delete_row()
        self._btn_delete.setEnabled(ok)

    def _on_delete_record(self) -> None:
        ok, pk = self._can_delete_row()
        if not ok or pk is None:
            return
        path = self._controls.database_path().strip()
        table = self._controls.table_name().strip()
        if not path or not table:
            return
        if not confirm_yes_default(
            self,
            "Delete row",
            f"Delete this row from {table!r}?",
        ):
            return
        try:
            core.validate_table_name(table)
            conn = _connect_rw(path)
            qtab = core.quote_ident(table)
            where_sql = core.sql_key_where(self._key_column_names)
            conn.execute(f"DELETE FROM {qtab} WHERE {where_sql}", pk)
            conn.commit()
            conn.close()
        except (sqlite3.Error, OSError) as e:
            show_warning(self, "Delete", str(e))
            return

        self._controls.remember_current_path()
        self.record_deleted.emit()
        self.close()

    def _collect_values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for col in self._columns:
            edit = self._field_lines[col.name]
            null_cb = self._field_nulls[col.name]
            is_key = col.name in self._key_set
            if is_key:
                raw = edit.text().strip()
                if raw == "":
                    raise ValueError(f"Key column {col.name!r} must have a value.")
                out[col.name] = core.parse_input_for_column(raw, col, allow_null=False)
                continue

            if null_cb is not None and null_cb.isChecked():
                out[col.name] = None
                if col.notnull:
                    raise ValueError(f"Column {col.name!r} cannot be NULL.")
                continue

            text = edit.text()
            if core.omit_column_for_sqlite_default(
                col,
                is_id_column=False,
                text_empty=text.strip() == "",
            ):
                continue
            allow_null = not col.notnull
            out[col.name] = core.parse_input_for_column(text, col, allow_null=allow_null)
        return out

    def _apply(self) -> None:
        path = self._controls.database_path()
        table = self._controls.table_name()
        if not path or not table:
            show_non_blocking(
                self, "Apply", "Choose a database and table."
            )
            return
        try:
            core.validate_table_name(table)
            values = self._collect_values()
        except ValueError as e:
            show_warning(self, "Validation", str(e))
            return

        kc = self._key_column_names
        new_key = tuple(values[k] for k in kc)
        where_sql = core.sql_key_where(kc)

        conn: sqlite3.Connection | None = None
        try:
            conn = _connect_rw(path)
            qtab = core.quote_ident(table)

            if self._mode == "insert":
                cur = conn.execute(
                    f"SELECT 1 FROM {qtab} WHERE {where_sql} LIMIT 1",
                    new_key,
                )
                if cur.fetchone():
                    show_warning(
                        self,
                        "Key conflict",
                        "A row with this key already exists.",
                    )
                    return
                to_write = [c for c in self._columns if c.name in values]
                cols_sql = ", ".join(core.quote_ident(c.name) for c in to_write)
                placeholders = ", ".join("?" * len(to_write))
                params = [values[c.name] for c in to_write]
                conn.execute(
                    f"INSERT INTO {qtab} ({cols_sql}) VALUES ({placeholders})",
                    params,
                )
                conn.commit()
            else:
                old_key = self._original_key
                if old_key is None:
                    show_warning(self, "Edit", "Missing original record key.")
                    return

                cur = conn.execute(
                    f"SELECT 1 FROM {qtab} WHERE {where_sql} LIMIT 1",
                    new_key,
                )
                exists_new = cur.fetchone() is not None
                same = len(new_key) == len(old_key) and all(
                    core.values_equal(new_key[i], old_key[i]) for i in range(len(new_key))
                )
                if exists_new and not same:
                    show_warning(
                        self,
                        "Key conflict",
                        "Another row already uses this key.",
                    )
                    return

                to_set = [c for c in self._columns if c.name in values]
                sets = ", ".join(f"{core.quote_ident(c.name)}=?" for c in to_set)
                params = [values[c.name] for c in to_set]
                params.extend(old_key)
                conn.execute(
                    f"UPDATE {qtab} SET {sets} WHERE {where_sql}",
                    params,
                )
                conn.commit()
        except sqlite3.Error as e:
            show_warning(self, "Database", str(e))
            return
        except OSError as e:
            show_warning(self, "Database", str(e))
            return
        finally:
            if conn is not None:
                conn.close()

        self._controls.remember_current_path()
        if self._mode == "update":
            self._original_key = new_key
        self.record_saved.emit()
        self.close()


class StandaloneEditShell(QWidget):
    """Standalone entry: user sets database and table, then form loads."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowTitle("Edit record (standalone)")
        self.resize(520, 120)
        self._controls = DatabaseTableControls()
        ldb = history_store.get_last_database_path()
        if ldb:
            self._controls.set_database_path(ldb)
        ltb = history_store.get_last_table_name()
        if ltb:
            self._controls.set_table_name(ltb)
        self._btn_open = QPushButton("Open editor…")
        layout = QVBoxLayout(self)
        layout.addWidget(self._controls)
        layout.addWidget(self._btn_open)
        self._btn_open.clicked.connect(self._open_editor)
        self._open_editors: list[RecordEditWindow] = []

    def _open_editor(self) -> None:
        path = self._controls.database_path()
        table = self._controls.table_name()
        if not path or not table:
            show_non_blocking(
                self, "Open", "Enter database path and table name."
            )
            return
        try:
            core.validate_table_name(table)
            conn = _connect_rw(path)
            key_cols = core.resolve_key_columns(conn, table)
            cols = core.fetch_columns(conn, table)
            conn.close()
        except Exception as e:  # noqa: BLE001
            show_warning(self, "Open", str(e))
            return
        editor = RecordEditWindow(
            database_path=path,
            table_name=table,
            key_column_names=key_cols,
            columns=cols,
            mode="insert",
            initial_values={},
            parent=None,
        )
        self._open_editors.append(editor)

        def _on_destroyed() -> None:
            try:
                self._open_editors.remove(editor)
            except ValueError:
                pass

        editor.destroyed.connect(_on_destroyed)
        show_smoothly(editor, raise_=True, activate=True)


# Avoid broken placeholder in module-level standalone
def run_edit_standalone() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    s = StandaloneEditShell()
    show_smoothly(s)
    app.exec()


if __name__ == "__main__":
    run_edit_standalone()
