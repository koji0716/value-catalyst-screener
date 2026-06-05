import sqlite3
import unittest

from src.db.models import SCHEMA
from src.ingestion.jquants_sync import (
    ensure_company_for_code,
    sync_jquants_earnings_events,
    parse_code_list,
    sync_jquants_prices,
    upsert_dividend_from_summary,
    upsert_company_from_jquants,
    upsert_statement,
)
from src.providers.jquants_client import normalize_issue_code, to_float


class FakeJQuantsClient:
    def fetch_prices(self, code, start_date=None, end_date=None):
        return [
            {
                "Date": "20260105",
                "Code": "%s0" % code,
                "O": "2500",
                "H": "2600",
                "L": "2490",
                "C": "2550",
                "AdjC": "2550",
                "AdjVo": "1000000",
            }
        ]

    def fetch_earnings_calendar(self):
        return [
            {"Date": "20260630", "Code": "72030", "CompanyName": "トヨタ自動車", "FiscalQuarter": "FY"},
            {"Date": "20260630", "Code": "94320", "CompanyName": "NTT", "FiscalQuarter": "FY"},
        ]


class JQuantsSyncTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        for statement in SCHEMA:
            self.conn.execute(statement)

    def tearDown(self):
        self.conn.close()

    def test_normalizes_issue_codes(self):
        self.assertEqual(normalize_issue_code("72030"), "7203")
        self.assertEqual(normalize_issue_code("7203"), "7203")
        self.assertEqual(parse_code_list("72030, 9432"), ["7203", "9432"])

    def test_to_float_handles_empty_values(self):
        self.assertEqual(to_float("1,234.5"), 1234.5)
        self.assertIsNone(to_float(""))
        self.assertIsNone(to_float("-"))

    def test_upserts_company_from_jquants_record(self):
        company_id = upsert_company_from_jquants(
            self.conn,
            {
                "Code": "72030",
                "CompanyName": "トヨタ自動車",
                "MarketCodeName": "Prime",
                "Sector33CodeName": "輸送用機器",
                "Sector17CodeName": "自動車・輸送機",
            },
        )
        row = self.conn.execute("SELECT * FROM company_master WHERE id = ?", (company_id,)).fetchone()
        self.assertEqual(row["ticker"], "7203")
        self.assertEqual(row["company_name"], "トヨタ自動車")

    def test_upserts_statement_into_financial_facts(self):
        company_id = ensure_company_for_code(self.conn, "7203")
        inserted = upsert_statement(
            self.conn,
            company_id,
            {
                "CurPerEn": "2026-03-31",
                "CurPerType": "FY",
                "Sales": "48000000000000",
                "OP": "4800000000000",
                "NP": "4760000000000",
                "EPS": "359.56",
                "TA": "93600000000000",
                "Eq": "35900000000000",
                "CashEq": "8980000000000",
                "CFO": "3700000000000",
                "CFI": "-4190000000000",
                "BPS": "2600",
            },
        )
        self.assertTrue(inserted)
        row = self.conn.execute("SELECT * FROM financial_facts WHERE company_id = ?", (company_id,)).fetchone()
        self.assertEqual(row["period_type"], "annual")
        self.assertEqual(row["free_cash_flow"], -490000000000.0)
        self.assertGreater(row["shares_outstanding"], 0)

    def test_upserts_dividend_from_summary(self):
        company_id = ensure_company_for_code(self.conn, "7203")
        inserted = upsert_dividend_from_summary(
            self.conn,
            company_id,
            {
                "DiscDate": "2026-05-08",
                "CurPerEn": "2026-03-31",
                "DivAnn": "75.0",
            },
        )
        self.assertTrue(inserted)
        row = self.conn.execute("SELECT * FROM corporate_actions WHERE company_id = ?", (company_id,)).fetchone()
        self.assertEqual(row["action_type"], "dividend")
        self.assertEqual(row["amount"], 75.0)

    def test_sync_prices_inserts_daily_quotes(self):
        company_id = ensure_company_for_code(self.conn, "7203")
        count = sync_jquants_prices(self.conn, FakeJQuantsClient(), ["7203"])
        self.assertEqual(count, 1)
        row = self.conn.execute("SELECT * FROM prices WHERE company_id = ?", (company_id,)).fetchone()
        self.assertEqual(row["trade_date"], "2026-01-05")
        self.assertEqual(row["adjusted_close"], 2550)

    def test_earnings_events_are_filtered_by_code(self):
        ensure_company_for_code(self.conn, "7203")
        count = sync_jquants_earnings_events(self.conn, FakeJQuantsClient(), codes=["7203"])
        self.assertEqual(count, 1)
        rows = self.conn.execute(
            """
            SELECT c.security_code, e.event_type
            FROM events e
            JOIN company_master c ON c.id = e.company_id
            """
        ).fetchall()
        self.assertEqual([dict(row) for row in rows], [{"security_code": "7203", "event_type": "earnings_date_soon"}])


if __name__ == "__main__":
    unittest.main()
