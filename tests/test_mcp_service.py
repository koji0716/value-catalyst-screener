import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.db.migrations import init_db
from src.db.session import get_connection
from src.ingestion.sample_data import seed_sample_data
from src.mcp_server.service import ValueCatalystService


class McpServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmpdir.name) / "mcp_test.sqlite"
        init_db(cls.db_path)
        conn = get_connection(cls.db_path)
        try:
            seed_sample_data(conn, reset=True)
        finally:
            conn.close()
        cls.service = ValueCatalystService(cls.db_path)

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_read_only_connection_rejects_writes(self):
        conn = get_connection(self.db_path, read_only=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute(
                    "INSERT INTO company_master (market, ticker, company_name) VALUES ('jp', '9999', 'Blocked')"
                )
        finally:
            conn.close()

    def test_search_companies_finds_security_code(self):
        result = self.service.search_companies("7203", market="jp", limit=5)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["companies"][0]["company_name"], "トヨタ自動車")

    def test_analyze_company_reuses_existing_scoring(self):
        result = self.service.analyze_company("7203", preset="balanced")

        self.assertEqual(result["analysis"]["ticker"], "7203")
        self.assertIn("total_score", result["analysis"])
        self.assertIn("explanation", result)

    def test_screen_stocks_does_not_save_results(self):
        before = self.service.read_query("SELECT COUNT(*) FROM screening_results")["rows"][0][0]

        result = self.service.screen_stocks(market="jp", preset="balanced", limit=3)

        after = self.service.read_query("SELECT COUNT(*) FROM screening_results")["rows"][0][0]
        self.assertLessEqual(result["count"], 3)
        self.assertFalse(result["saved"])
        self.assertEqual(after, before)

    def test_read_query_rejects_mutation_and_pragma(self):
        with self.assertRaisesRegex(ValueError, "Only SELECT or WITH"):
            self.service.read_query("DELETE FROM company_master")
        with self.assertRaisesRegex(ValueError, "not allowed"):
            self.service.read_query("WITH values_cte AS (SELECT 1) SELECT load_extension('blocked')")

    def test_read_query_applies_row_limit(self):
        result = self.service.read_query(
            "SELECT ticker FROM company_master ORDER BY ticker",
            max_rows=2,
        )

        self.assertEqual(result["row_count"], 2)
        self.assertTrue(result["truncated"])

    def test_price_and_financial_history(self):
        prices = self.service.price_history("7203", limit=5)
        financials = self.service.financial_history("7203", limit=3)

        self.assertEqual(prices["company"]["ticker"], "7203")
        self.assertEqual(len(prices["prices"]), 5)
        self.assertEqual(financials["company"]["ticker"], "7203")
        self.assertGreater(len(financials["financials"]), 0)


if __name__ == "__main__":
    unittest.main()
