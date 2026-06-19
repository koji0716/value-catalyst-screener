import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.db.models import SCHEMA
from src.ingestion.us_stale_refresh import refresh_stale_us_prices, select_stale_us_price_rows


class UsStaleRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "stale.sqlite"
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            for statement in SCHEMA:
                conn.execute(statement)
            self.old_id = self.insert_company(conn, "OLD", "Old Co")
            self.fresh_id = self.insert_company(conn, "FRESH", "Fresh Co")
            self.no_price_id = self.insert_company(conn, "NOPR", "No Price Co")
            conn.execute(
                "INSERT INTO prices (company_id, trade_date, close, adjusted_close, source) VALUES (?, '2026-06-05', 10, 10, 'yfinance')",
                (self.old_id,),
            )
            conn.execute(
                "INSERT INTO prices (company_id, trade_date, close, adjusted_close, source) VALUES (?, '2026-06-18', 20, 20, 'yfinance')",
                (self.fresh_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.tmpdir.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def insert_company(self, conn, ticker, name):
        cur = conn.execute(
            """
            INSERT INTO company_master (market, ticker, company_name, exchange, country, currency)
            VALUES ('us', ?, ?, 'NYSE', 'US', 'USD')
            """,
            (ticker, name),
        )
        return cur.lastrowid

    def fake_sync(self, conn, tickers, start_date=None, end_date=None, **kwargs):
        price_date = end_date or "2026-06-18"
        for ticker in tickers:
            row = conn.execute(
                "SELECT id FROM company_master WHERE market = 'us' AND ticker = ?",
                (ticker,),
            ).fetchone()
            conn.execute("DELETE FROM prices WHERE company_id = ? AND trade_date = ?", (row["id"], price_date))
            conn.execute(
                "INSERT INTO prices (company_id, trade_date, close, adjusted_close, source) VALUES (?, ?, 30, 30, 'yfinance')",
                (row["id"], price_date),
            )
        conn.commit()
        return {
            "target_codes": list(tickers),
            "updated_companies": len(tickers),
            "inserted_prices": len(tickers),
            "inserted_financials": 0,
            "inserted_filings": 0,
            "inserted_actions": 0,
            "warnings": [],
        }

    def test_selects_only_companies_with_stale_or_missing_prices(self):
        conn = self.connect()
        try:
            rows = select_stale_us_price_rows(conn, stale_before="2026-06-10", limit=10)
        finally:
            conn.close()

        self.assertEqual([row["ticker"] for row in rows], ["NOPR", "OLD"])

    def test_refreshes_stale_prices_and_records_state(self):
        result = refresh_stale_us_prices(
            stale_before="2026-06-10",
            end_date="2026-06-18",
            batch_limit=10,
            max_batches=2,
            db_path=self.db_path,
            sync_func=self.fake_sync,
            sleep_func=lambda _: None,
        )

        self.assertEqual(result["stopped_reason"], "complete")
        self.assertEqual(result["selected_records"], 2)
        self.assertEqual(result["processed_tickers"], ["NOPR", "OLD"])
        self.assertEqual(result["remaining_stale_before"], 2)
        self.assertEqual(result["remaining_stale_after"], 0)

        conn = self.connect()
        try:
            state = conn.execute(
                """
                SELECT status, message
                FROM sync_state
                WHERE market = 'us' AND source = 'edgar' AND mode = 'stale_prices'
                """
            ).fetchone()
            locks = conn.execute("SELECT COUNT(*) FROM sync_locks").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(state["status"], "success")
        self.assertIn("完了", state["message"])
        self.assertEqual(locks, 0)

    def test_refresh_rejects_existing_writer_lock(self):
        conn = self.connect()
        try:
            conn.execute(
                """
                INSERT INTO sync_locks (lock_key, owner, expires_at)
                VALUES ('sync:writer', 'test-owner', datetime(CURRENT_TIMESTAMP, '+5 minutes'))
                """
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaisesRegex(RuntimeError, "別のデータ取得"):
            refresh_stale_us_prices(
                stale_before="2026-06-10",
                end_date="2026-06-18",
                batch_limit=10,
                max_batches=1,
                db_path=self.db_path,
                sync_func=self.fake_sync,
                sleep_func=lambda _: None,
            )


if __name__ == "__main__":
    unittest.main()
