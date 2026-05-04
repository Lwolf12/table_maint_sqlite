"""SQLite table lookup and maintenance UI (PySide6)."""

from table_maint.main_window import TableMaintMainWindow

__all__ = ["TableMaintMainWindow", "open_table_maint"]


def open_table_maint(
    database_path: str | None = None,
    table_name: str | None = None,
    record_id: object | None = None,
    parent=None,
) -> TableMaintMainWindow:
    """
    Open the main table maintenance window (non-blocking).

    If no QApplication exists yet, create one and call ``exec()`` yourself, or use
    ``python -m table_maint`` for a standalone process that runs the event loop.
    """
    w = TableMaintMainWindow(database_path, table_name, record_id, parent)
    w.show()
    return w
