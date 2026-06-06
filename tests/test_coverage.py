import json
import sqlite3
import unittest
from datetime import date

from src.db.models import SCHEMA
from src.ingestion.coverage import data_coverage_rows, market_data_coverage


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        for statement in SCHEMA:
            self.conn.execute(statement)
        self.conn.executemany(
            """
            INSERT INTO company_master (id, market, ticker, company_name)
            VALUES (?, ?, ?, ?)
            """,
            [
                (1, "jp", "1301", "JP One"),
                (2, "jp", "1305", "JP Two"),
                (3, "jp", "7203", "JP Three"),
                (4, "us", "AAPL", "Apple"),
            ],
        )
        self.conn.execute(
            """
            INSERT INTO sync_jobs (job_type, market, source, mode, status, params_json, result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "bulk_sync",
                "jp",
                "jquants",
                "bulk",
                "warning",
                json.dumps({"include_prices": False, "include_financials": False}),
                json.dumps({"available_records": 5, "next_offset": 5}),
            ),
        )
        self.conn.execute(
            """
            INSERT INTO sync_jobs (job_type, market, source, mode, status, params_json, result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "bulk_sync",
                "jp",
                "jquants",
                "bulk",
                "warning",
                json.dumps({"include_prices": True, "include_financials": True}),
                json.dumps({"available_records": 5, "next_offset": 2}),
            ),
        )
        self.conn.execute(
            """
            INSERT INTO sync_jobs (job_type, market, source, mode, status, params_json, result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "bulk_sync",
                "us",
                "edgar",
                "bulk",
                "success",
                json.dumps({"include_prices": False, "include_financials": False}),
                json.dumps({"available_records": 4, "next_offset": 4}),
            ),
        )
        self.conn.execute(
            """
            INSERT INTO prices (company_id, trade_date, close, adjusted_close, source)
            VALUES (1, '2026-06-02', 100, 100, 'jquants')
            """
        )
        self.conn.executemany(
            """
            INSERT INTO financial_facts (company_id, source, period_end, revenue)
            VALUES (?, ?, ?, ?)
            """,
            [
                (1, "jquants", "2026-03-31", 1000),
                (2, "jquants", "2023-03-31", 900),
            ],
        )
        self.conn.execute(
            """
            INSERT INTO filings (company_id, source, document_id, filing_date)
            VALUES (1, 'edinetdb', 'doc-1', '2026-05-01')
            """
        )
        self.conn.execute(
            """
            INSERT INTO corporate_actions (company_id, action_type, announced_date, source)
            VALUES (1, 'dividend', '2026-04-01', 'jquants')
            """
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_market_data_coverage_calculates_master_detail_and_freshness(self):
        row = market_data_coverage(self.conn, "jp", as_of=date(2026, 6, 6))

        self.assertEqual(row["universe_records"], 5)
        self.assertEqual(row["company_count"], 3)
        self.assertEqual(row["master_next_offset"], 5)
        self.assertEqual(row["master_progress_pct"], 100.0)
        self.assertEqual(row["master_coverage_pct"], 60.0)
        self.assertEqual(row["detail_next_offset"], 2)
        self.assertEqual(row["detail_progress_pct"], 40.0)
        self.assertEqual(row["price_coverage_pct"], 33.3)
        self.assertEqual(row["financial_coverage_pct"], 66.7)
        self.assertEqual(row["filing_coverage_pct"], 33.3)
        self.assertEqual(row["action_coverage_pct"], 33.3)
        self.assertEqual(row["price_freshness_pct"], 33.3)
        self.assertEqual(row["financial_freshness_pct"], 33.3)
        self.assertEqual(row["latest_price_date"], "2026-06-02")

    def test_data_coverage_rows_returns_jp_and_us(self):
        rows = data_coverage_rows(self.conn, as_of=date(2026, 6, 6))

        self.assertEqual([row["market"] for row in rows], ["jp", "us"])
        self.assertEqual(rows[1]["universe_records"], 4)
        self.assertEqual(rows[1]["company_count"], 1)
        self.assertEqual(rows[1]["master_coverage_pct"], 25.0)


if __name__ == "__main__":
    unittest.main()
