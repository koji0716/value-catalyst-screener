import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.db.models import SCHEMA
from src.ingestion.us_stale_refresh import (
    refresh_stale_us_prices,
    run_selected_us_price_tickers,
    select_stale_us_price_rows,
)


class FakeBatchPriceClient:
    def fetch_ohlc_batch(self, tickers, start_date=None, end_date=None):
        rows = {}
        for ticker in tickers:
            if ticker == "OLD":
                rows[ticker] = [
                    {
                        "date": end_date or "2026-06-18",
                        "open": 30,
                        "high": 31,
                        "low": 29,
                        "close": 30,
                        "adjusted_close": 30,
                        "volume": 1000,
                    }
                ]
            else:
                rows[ticker] = []
        return rows


class EmptyProbePriceClient:
    def fetch_ohlc_batch(self, tickers, start_date=None, end_date=None):
        return {ticker: [] for ticker in tickers}

    def fetch_ohlc(self, ticker, start_date=None, end_date=None):
        return []


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

    def fake_partial_sync(self, conn, tickers, start_date=None, end_date=None, **kwargs):
        price_date = end_date or "2026-06-18"
        inserted = 0
        for ticker in tickers:
            if ticker != "OLD":
                continue
            row = conn.execute(
                "SELECT id FROM company_master WHERE market = 'us' AND ticker = ?",
                (ticker,),
            ).fetchone()
            conn.execute("DELETE FROM prices WHERE company_id = ? AND trade_date = ?", (row["id"], price_date))
            conn.execute(
                "INSERT INTO prices (company_id, trade_date, close, adjusted_close, source) VALUES (?, ?, 30, 30, 'yfinance')",
                (row["id"], price_date),
            )
            inserted += 1
        conn.commit()
        return {
            "target_codes": list(tickers),
            "updated_companies": len(tickers),
            "inserted_prices": inserted,
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

    def test_select_skips_recent_price_unavailable_rows(self):
        conn = self.connect()
        try:
            conn.execute(
                """
                INSERT INTO unavailable_data (market, source, data_type, identifier, reason)
                VALUES ('us', 'yfinance', 'prices', 'NOPR', 'no prices')
                """
            )
            conn.commit()
            rows = select_stale_us_price_rows(conn, stale_before="2026-06-10", limit=10)
        finally:
            conn.close()

        self.assertEqual([row["ticker"] for row in rows], ["OLD"])

    def test_price_only_runner_updates_without_sec_lookup(self):
        conn = self.connect()
        try:
            result = run_selected_us_price_tickers(
                conn,
                ["OLD", "NOPR"],
                end_date="2026-06-18",
                price_client=FakeBatchPriceClient(),
            )
            latest_old = conn.execute(
                "SELECT MAX(trade_date) FROM prices WHERE company_id = ?",
                (self.old_id,),
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(result["inserted_prices"], 1)
        self.assertEqual(result["no_price_tickers"], ["NOPR"])
        self.assertEqual(latest_old, "2026-06-18")

    def test_price_only_runner_rejects_provider_wide_empty_response(self):
        conn = self.connect()
        try:
            with self.assertRaisesRegex(RuntimeError, "AAPL probe"):
                run_selected_us_price_tickers(
                    conn,
                    ["NOPR"],
                    end_date="2026-06-18",
                    price_client=EmptyProbePriceClient(),
                )
        finally:
            conn.close()

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

    def test_refresh_marks_no_price_ticker_and_continues(self):
        result = refresh_stale_us_prices(
            stale_before="2026-06-10",
            end_date="2026-06-18",
            batch_limit=1,
            max_batches=3,
            db_path=self.db_path,
            sync_func=self.fake_partial_sync,
            sleep_func=lambda _: None,
        )

        self.assertEqual(result["stopped_reason"], "complete")
        self.assertEqual(result["processed_tickers"], ["NOPR", "OLD"])
        self.assertEqual(result["marked_unavailable_prices"], 1)
        self.assertEqual(result["marked_unavailable_tickers"], ["NOPR"])
        self.assertEqual(result["remaining_stale_after"], 0)

        conn = self.connect()
        try:
            unavailable = conn.execute(
                """
                SELECT identifier
                FROM unavailable_data
                WHERE market = 'us' AND source = 'yfinance' AND data_type = 'prices'
                """
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual([row["identifier"] for row in unavailable], ["NOPR"])

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
