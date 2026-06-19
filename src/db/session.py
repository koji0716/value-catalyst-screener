import sqlite3
from pathlib import Path

from src.utils.file_utils import ensure_runtime_dirs, get_db_path


SQLITE_TIMEOUT_SEC = 30.0
SQLITE_BUSY_TIMEOUT_MS = int(SQLITE_TIMEOUT_SEC * 1000)


def get_connection(db_path=None, read_only=False):
    path = Path(db_path or get_db_path()).resolve()
    if read_only:
        if not path.exists():
            raise FileNotFoundError("Database not found: %s" % path)
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=SQLITE_TIMEOUT_SEC)
        conn.execute("PRAGMA query_only = ON")
    else:
        ensure_runtime_dirs()
        conn = sqlite3.connect(str(path), timeout=SQLITE_TIMEOUT_SEC)
        conn.execute("PRAGMA busy_timeout = %d" % SQLITE_BUSY_TIMEOUT_MS)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            # A concurrently active writer can block switching modes. The longer
            # busy timeout still applies, and the next clean write connection can
            # enable WAL.
            pass
        conn.execute("PRAGMA synchronous = NORMAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = %d" % SQLITE_BUSY_TIMEOUT_MS)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
