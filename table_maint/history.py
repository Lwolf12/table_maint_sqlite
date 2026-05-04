"""Persist recent database paths and last-used session in local JSON storage."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_MAX_ENTRIES = 30
_LAST_SESSION_KEY = "_last_session"
_DATABASE_PATHS_KEY = "_database_paths"
_LEGACY_MIGRATED_KEY = "_legacy_paths_migrated"


def _storage_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / ".config")
    root = Path(base) / "table_maint"
    root.mkdir(parents=True, exist_ok=True)
    return root / "db_history.json"


def _load_raw() -> dict[str, Any]:
    path = _storage_path()
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_raw(data: dict[str, Any]) -> None:
    path = _storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=0)
    tmp.replace(path)


def _merge_legacy_paths_into_global(data: dict[str, Any]) -> None:
    """Merge old per-table lists into _database_paths (in memory)."""
    merged: list[str] = []
    skip = {_LAST_SESSION_KEY, _DATABASE_PATHS_KEY, _LEGACY_MIGRATED_KEY}
    for key, val in data.items():
        if key in skip:
            continue
        if isinstance(val, list):
            for x in val:
                if isinstance(x, str) and x not in merged:
                    merged.append(x)
    existing = data.get(_DATABASE_PATHS_KEY)
    if isinstance(existing, list):
        for x in existing:
            if isinstance(x, str) and x not in merged:
                merged.insert(0, x)
    data[_DATABASE_PATHS_KEY] = merged[:_MAX_ENTRIES]


def _ensure_legacy_migration() -> None:
    data = _load_raw()
    if data.get(_LEGACY_MIGRATED_KEY):
        return
    _merge_legacy_paths_into_global(data)
    data[_LEGACY_MIGRATED_KEY] = True
    _save_raw(data)


def get_database_history() -> list[str]:
    """Recent database file paths (most recent first), independent of table name."""
    _ensure_legacy_migration()
    data = _load_raw()
    raw = data.get(_DATABASE_PATHS_KEY)
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x not in out:
            out.append(x)
    return out


def get_last_database_path() -> str | None:
    _ensure_legacy_migration()
    data = _load_raw()
    raw = data.get(_LAST_SESSION_KEY)
    if isinstance(raw, dict):
        db = raw.get("database_path")
        if isinstance(db, str) and db.strip():
            return db.strip()
    hist = data.get(_DATABASE_PATHS_KEY)
    if isinstance(hist, list) and hist:
        first = hist[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    return None


def get_last_table_name() -> str | None:
    _ensure_legacy_migration()
    data = _load_raw()
    raw = data.get(_LAST_SESSION_KEY)
    if isinstance(raw, dict):
        tb = raw.get("table_name")
        if isinstance(tb, str) and tb.strip():
            return tb.strip()
    return None


def remember_database_path(database_path: str) -> None:
    """Record a database path for MRU and last-session DB path."""
    if not database_path.strip():
        return
    _ensure_legacy_migration()
    p = database_path.strip()
    data = _load_raw()
    paths = [x for x in data.get(_DATABASE_PATHS_KEY, []) if isinstance(x, str)]
    try:
        paths.remove(p)
    except ValueError:
        pass
    paths.insert(0, p)
    data[_DATABASE_PATHS_KEY] = paths[:_MAX_ENTRIES]
    sess = data.get(_LAST_SESSION_KEY)
    if not isinstance(sess, dict):
        sess = {}
    sess["database_path"] = p
    data[_LAST_SESSION_KEY] = sess
    _save_raw(data)


def remember_loaded_table(database_path: str, table_name: str) -> None:
    """After a successful grid load: MRU databases and last session includes table."""
    if not database_path.strip() or not table_name.strip():
        return
    _ensure_legacy_migration()
    p = database_path.strip()
    t = table_name.strip()
    data = _load_raw()
    paths = [x for x in data.get(_DATABASE_PATHS_KEY, []) if isinstance(x, str)]
    try:
        paths.remove(p)
    except ValueError:
        pass
    paths.insert(0, p)
    data[_DATABASE_PATHS_KEY] = paths[:_MAX_ENTRIES]
    data[_LAST_SESSION_KEY] = {
        "database_path": p,
        "table_name": t,
    }
    _save_raw(data)


def get_last_session() -> tuple[str | None, str | None]:
    """(database_path, table_name or None)."""
    return (get_last_database_path(), get_last_table_name())


def get_paths_for_table(table_name: str) -> list[str]:
    """Same as global database history (table argument ignored)."""
    return get_database_history()


def remember_path(table_name: str, database_path: str) -> None:
    """Backwards compatibility: delegates to remember_loaded_table."""
    remember_loaded_table(database_path, table_name)
