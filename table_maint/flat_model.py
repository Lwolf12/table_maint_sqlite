"""Read-only table model for SQLite result grids."""

from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from table_maint.core import format_cell_display


class FlatTableModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.headers: list[str] = []
        self.rows: list[list[Any]] = []

    def set_data(self, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
        self.beginResetModel()
        self.headers = list(headers)
        self.rows = [list(r) for r in rows]
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = index.column()
        if col >= len(row):
            return None
        value = row[col]
        if role == Qt.ItemDataRole.DisplayRole:
            return format_cell_display(value)
        if role == Qt.ItemDataRole.UserRole:
            return value
        return None

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.headers):
            return self.headers[section]
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return None
