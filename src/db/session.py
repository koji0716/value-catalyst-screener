import sqlite3

from src.utils.file_utils import ensure_runtime_dirs, get_db_path


def get_connection(db_path=None):
    ensure_runtime_dirs()
    path = db_path or get_db_path()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

