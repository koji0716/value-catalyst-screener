import tempfile
import unittest
from pathlib import Path

from src.db.session import SQLITE_BUSY_TIMEOUT_MS, get_connection


class DbSessionTests(unittest.TestCase):
    def test_write_connection_uses_busy_timeout_and_wal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "session.sqlite"
            conn = get_connection(db_path)
            try:
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            finally:
                conn.close()

        self.assertEqual(journal_mode.lower(), "wal")
        self.assertEqual(busy_timeout, SQLITE_BUSY_TIMEOUT_MS)


if __name__ == "__main__":
    unittest.main()
