import sqlite3
import unittest

from src.db.models import SCHEMA
from src.ingestion.jp_bulk_sync import filtered_jp_records, sync_jp_bulk_market


class FakeBulkJQuantsClient:
    def is_configured(self):
        return True

    def close(self):
        pass

    def fetch_listed_info(self, date_value=None, code=None):
        records = [
            {"Code": "72030", "CompanyName": "トヨタ自動車", "MarketCodeName": "プライム"},
            {"Code": "94320", "CompanyName": "NTT", "MarketCodeName": "プライム"},
            {"Code": "44780", "CompanyName": "フリー", "MarketCodeName": "グロース"},
        ]
        if code:
            normalized = str(code).strip().rstrip("0")
            return [record for record in records if str(record["Code"]).startswith(normalized)]
        return records

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

    def fetch_financial_statements(self, code=None, date_value=None):
        return [
            {
                "DisclosedDate": "2026-01-31",
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
                "DivAnn": "75.0",
            }
        ]

    def fetch_earnings_calendar(self):
        return [{"Date": "20260630", "Code": "72030", "CompanyName": "トヨタ自動車", "FiscalQuarter": "FY"}]


class JpBulkSyncTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        for statement in SCHEMA:
            self.conn.execute(statement)

    def tearDown(self):
        self.conn.close()

    def test_filtered_jp_records_support_section_offset_and_limit(self):
        rows, available = filtered_jp_records(
            FakeBulkJQuantsClient().fetch_listed_info(),
            sections="Prime",
            offset=1,
            limit=1,
        )
        self.assertEqual(available, 2)
        self.assertEqual([row["Code"] for row in rows], ["94320"])

    def test_sync_jp_bulk_market_imports_master_only_and_resumes(self):
        client = FakeBulkJQuantsClient()
        result = sync_jp_bulk_market(
            self.conn,
            client=client,
            sections="Prime",
            limit=2,
            include_prices=False,
            include_financials=False,
            include_dividends=False,
            include_events=False,
        )
        self.assertEqual(result["available_records"], 2)
        self.assertEqual(result["selected_records"], 2)
        self.assertEqual(result["inserted_companies"], 2)
        self.assertEqual(result["processed_codes"], ["7203", "9432"])
        self.assertEqual(result["next_offset"], 2)

        second = sync_jp_bulk_market(
            self.conn,
            client=client,
            sections="Prime",
            limit=2,
            include_prices=False,
            include_financials=False,
            include_dividends=False,
            include_events=False,
        )
        self.assertEqual(second["skipped_existing"], 2)
        self.assertEqual(second["processed_codes"], [])

    def test_sync_jp_bulk_market_can_import_company_data(self):
        result = sync_jp_bulk_market(
            self.conn,
            client=FakeBulkJQuantsClient(),
            sections="Prime",
            limit=1,
            include_prices=True,
            include_financials=True,
            include_dividends=True,
            include_events=True,
        )
        self.assertEqual(result["inserted_companies"], 1)
        self.assertEqual(result["inserted_prices"], 1)
        self.assertEqual(result["inserted_financials"], 1)
        self.assertEqual(result["inserted_dividends"], 1)
        self.assertGreaterEqual(result["inserted_events"], 1)


if __name__ == "__main__":
    unittest.main()
