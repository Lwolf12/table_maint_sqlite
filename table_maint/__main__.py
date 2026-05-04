"""Single entry: ``python -m table_maint`` dispatches to list or edit UI."""

from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication

from table_maint.window_show import show_smoothly


def _cli_record_key(raw_parts: list[str] | None) -> object | None:
    """Build API record key from CLI parts (one -r per key column)."""
    if not raw_parts:
        return None
    if len(raw_parts) == 1:
        try:
            return int(raw_parts[0])
        except ValueError:
            return raw_parts[0]
    return tuple(raw_parts)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="SQLite table maintenance: main list or record editor.",
    )
    parser.add_argument("--database", "-d", default=None, help="SQLite database file")
    parser.add_argument("--table", "-t", default=None, help="Table name")
    parser.add_argument(
        "-r",
        "--record",
        "--id",
        dest="record_parts",
        action="append",
        default=None,
        metavar="PART",
        help=(
            "Record key: pass once per key column (e.g. -r 1 -r 2 for a composite key). "
            "List scrolls to the row; edit loads the row (omit for a new row). "
            "If --window is omitted and -d/-t/-r are all set, edit opens when that key exists."
        ),
    )
    parser.add_argument(
        "-w",
        "--window",
        choices=("list", "edit"),
        default=argparse.SUPPRESS,
        help=(
            "Which UI: list=main grid, edit=add/edit form. "
            "If omitted, use -d/-t/-r to choose edit (row exists) vs list."
        ),
    )
    args = parser.parse_args(argv)

    record_key = _cli_record_key(args.record_parts)
    window = getattr(args, "window", None)

    app = QApplication([])

    from table_maint.edit_window import (
        StandaloneEditShell,
        launch_record_editor,
        record_exists_for_id,
    )
    from table_maint.main_window import TableMaintMainWindow

    if window == "edit":
        if not args.database or not args.table:
            shell = StandaloneEditShell()
            show_smoothly(shell)
            return app.exec()

        try:
            win = launch_record_editor(
                args.database,
                args.table,
                record_id=record_key,
                parent=None,
            )
        except Exception as e:  # noqa: BLE001 — CLI error path
            print(f"table_maint: {e}", file=sys.stderr)
            return 1

        show_smoothly(win, raise_=True, activate=True)
        return app.exec()

    if window == "list":
        win = TableMaintMainWindow(
            database_path=args.database,
            table_name=args.table,
            record_id=record_key,
        )
        show_smoothly(win)
        return app.exec()

    # --window omitted: optional edit when ID exists
    if args.database and args.table and record_key is not None:
        try:
            if record_exists_for_id(args.database, args.table, record_key):
                win = launch_record_editor(
                    args.database,
                    args.table,
                    record_id=record_key,
                    parent=None,
                )
                show_smoothly(win, raise_=True, activate=True)
                return app.exec()
        except Exception as e:  # noqa: BLE001 — fall back to list
            print(f"table_maint: {e}", file=sys.stderr)

    win = TableMaintMainWindow(
        database_path=args.database,
        table_name=args.table,
        record_id=record_key,
    )
    show_smoothly(win)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
