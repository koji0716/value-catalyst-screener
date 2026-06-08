import sqlite3
from pathlib import Path

from src.utils.file_utils import ensure_runtime_dirs, get_db_path


def get_connection(db_path=None, read_only=False):
    path = Path(db_path or get_db_path()).resolve()
    if read_only:
        if not path.exists():
            raise FileNotFoundError("Database not found: %s" % path)
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        conn.execute("PRAGMA query_only = ON")
    else:
        ensure_runtime_dirs()
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
