"""Shared database path, table name, and recent-database history controls."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from table_maint import core
from table_maint import history as history_store
from table_maint.messages import show_warning


class DatabaseTableControls(QWidget):
    """
    Database path (with file picker), table name (combo of DB tables + optional typing),
    and recent-database history dropdown.
    Emits context_changed when path or table should reload data.
    """

    context_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Only emit context_changed when path/table actually change. Otherwise
        # editingFinished on the table combo (e.g. user clicks the ID field)
        # would rebuild the edit form mid-focus and can crash Qt on Windows.
        self._context_snapshot: tuple[str, str] = ("", "")
        self._db_path = QLineEdit()
        self._db_path.setPlaceholderText("Database file path")
        self._browse = QPushButton("Browse…")
        self._table = QComboBox()
        self._table.setEditable(True)
        self._table.setMinimumWidth(200)
        self._table.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        le = self._table.lineEdit()
        if le is not None:
            le.setPlaceholderText("Select or type table name")

        self._history = QComboBox()
        self._history.setMinimumWidth(220)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Database:"))
        row1.addWidget(self._db_path, 1)
        row1.addWidget(self._browse)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Table:"))
        row2.addWidget(self._table, 1)
        row2.addWidget(QLabel("History:"))
        row2.addWidget(self._history)

        outer = QVBoxLayout(self)
        outer.addLayout(row1)
        outer.addLayout(row2)

        self._browse.clicked.connect(self._on_browse)
        self._db_path.editingFinished.connect(self._on_database_path_finished)
        self._table.activated.connect(self._on_table_activated)
        if le is not None:
            le.editingFinished.connect(self._emit_if_context_changed)
        self._history.activated.connect(self._on_history_activated)
        self._refresh_history_combo()
        self._capture_context_snapshot()

    def _current_context_snapshot(self) -> tuple[str, str]:
        return (self.database_path(), self.table_name())

    def _capture_context_snapshot(self) -> None:
        self._context_snapshot = self._current_context_snapshot()

    def _emit_if_context_changed(self) -> None:
        snap = self._current_context_snapshot()
        if snap == self._context_snapshot:
            return
        self._context_snapshot = snap
        self.context_changed.emit()

    def _on_table_activated(self, _index: int) -> None:
        self._emit_if_context_changed()

    def set_database_path(self, path: str) -> None:
        self._db_path.setText(path)
        self._reload_table_combo_preserving_selection()
        self._capture_context_snapshot()

    def set_table_name(self, name: str) -> None:
        self._table.blockSignals(True)
        n = name.strip()
        if not n:
            self._table.setCurrentIndex(-1)
            self._table.setEditText("")
        else:
            idx = self._table.findText(n, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                self._table.setCurrentIndex(idx)
            else:
                self._table.setCurrentIndex(-1)
                self._table.setEditText(n)
        self._table.blockSignals(False)
        self._capture_context_snapshot()

    def database_path(self) -> str:
        return self._db_path.text().strip()

    def table_name(self) -> str:
        return self._table.currentText().strip()

    def _reload_table_combo_preserving_selection(self) -> None:
        previous = self.table_name()
        self._table.blockSignals(True)
        self._table.clear()
        p = self.database_path().strip()
        if p and Path(p).is_file():
            try:
                conn = sqlite3.connect(p)
                try:
                    tables = core.list_user_tables(conn)
                finally:
                    conn.close()
                self._table.addItems(tables)
            except (OSError, sqlite3.Error):
                pass
        if previous:
            idx = self._table.findText(previous, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                self._table.setCurrentIndex(idx)
            else:
                self._table.setEditText(previous)
        else:
            self._table.setCurrentIndex(-1)
        self._table.blockSignals(False)

    def _on_database_path_finished(self) -> None:
        self._reload_table_combo_preserving_selection()
        self._emit_if_context_changed()

    def _refresh_history_combo(self) -> None:
        self._history.blockSignals(True)
        self._history.clear()
        for p in history_store.get_database_history():
            self._history.addItem(p, p)
        self._history.blockSignals(False)

    def refresh_history(self) -> None:
        """Reload the recent-databases dropdown from storage."""
        self._refresh_history_combo()

    def _on_history_activated(self, index: int) -> None:
        if index < 0:
            return
        path = self._history.itemData(index)
        if not path:
            path = self._history.itemText(index)
        if path and path != self._db_path.text():
            self._db_path.setText(path)
            self._reload_table_combo_preserving_selection()
        self._emit_if_context_changed()

    def _on_browse(self) -> None:
        start = self._db_path.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open SQLite database",
            start,
            "SQLite databases (*.db *.sqlite *.sqlite3);;All files (*.*)",
        )
        if path:
            self._db_path.setText(path)
            history_store.remember_database_path(path)
            self._refresh_history_combo()
            self._reload_table_combo_preserving_selection()
            self._emit_if_context_changed()

    def remember_current_path(self) -> None:
        """Call after a successful table load (saves DB + table in session)."""
        t = self.table_name()
        p = self.database_path()
        if p and t:
            history_store.remember_loaded_table(p, t)
        elif p:
            history_store.remember_database_path(p)

    def show_error(self, title: str, message: str) -> None:
        show_warning(self, title, message)
