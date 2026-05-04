"""Launch the table_maint UI. Same CLI as ``python -m table_maint``."""

from __future__ import annotations

import sys

from table_maint.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
