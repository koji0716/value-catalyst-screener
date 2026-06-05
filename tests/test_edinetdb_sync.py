import sqlite3
import unittest

from src.db.models import SCHEMA
from src.ingestion.edinetdb_sync import sync_edinetdb_market
from src.providers.edinet_client import _records


class FakeEdinetDbClient:
    def is_configured(self):
        return True

    def close(self):
        pass

    def search_companies(self, query, limit=10):
        return [
            {
                "edinet_code": "E02144",
                "security_code": "7203",
                "company_name": "トヨタ自動車",
            }
        ]

    def get_company(self, edinet_code, fields=None):
        return {
            "edinet_code": edinet_code,
            "security_code": "7203",
            "company_name": "トヨタ自動車",
            "industry": "輸送用機器",
        }

    def get_financials(self, edinet_code, years=6, period="annual"):
        return [
            {
                "fiscal_year": 2025,
                "period_end": "2025-03-31",
                "revenue": "48000000000000",
                "operating_income": "4800000000000",
                "net_income": "4760000000000",
                "total_assets": "93600000000000",
                "net_assets": "35900000000000",
                "cash": "8980000000000",
                "cf_operating": "3700000000000",
                "cf_investing": "-4190000000000",
                "eps": "359.56",
            }
        ]

    def get_disclosures(self, edinet_code, since=None, until=None, types=None):
        return [
            {
                "document_id": "S100TEST",
                "document_type": "yuho",
                "filing_date": "2025-06-30",
                "period_end": "2025-03-31",
                "title": "有価証券報告書",
                "url": "https://example.local/S100TEST",
            }
        ]

    def get_text_blocks(self, edinet_code, fiscal_year=None, element_type=None):
        return [
            {
                "fiscal_year": 2025,
                "element_type": "risk_items",
                "title": "事業等のリスク",
                "text": "継続企業の前提に関する重要な疑義が存在しています。",
            }
        ]


class EdinetDbSyncTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        for statement in SCHEMA:
            self.conn.execute(statement)
        self.conn.execute(
            """
            INSERT INTO company_master (
              market, ticker, security_code, company_name, country, currency, is_active
            ) VALUES ('jp', '7203', '7203', 'トヨタ自動車', 'JP', 'JPY', 1)
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_sync_edinetdb_market_inserts_financial_filings_and_risk(self):
        result = sync_edinetdb_market(self.conn, client=FakeEdinetDbClient(), codes="7203")
        self.assertEqual(result["updated_companies"], 1)
        self.assertEqual(result["inserted_financials"], 1)
        self.assertEqual(result["inserted_filings"], 1)
        self.assertEqual(result["inserted_text_blocks"], 1)
        self.assertEqual(result["inserted_risk_events"], 1)

        company = self.conn.execute("SELECT * FROM company_master WHERE security_code = '7203'").fetchone()
        self.assertEqual(company["edinet_code"], "E02144")

        financial = self.conn.execute("SELECT * FROM financial_facts WHERE source = 'edinetdb'").fetchone()
        self.assertEqual(financial["free_cash_flow"], -490000000000.0)

        filing = self.conn.execute("SELECT * FROM filings WHERE source = 'edinetdb'").fetchone()
        self.assertEqual(filing["document_id"], "S100TEST")

        event = self.conn.execute("SELECT * FROM events WHERE source = 'edinetdb'").fetchone()
        self.assertEqual(event["event_type"], "going_concern")

    def test_records_extracts_nested_data_payloads(self):
        payload = {"data": {"disclosures": [{"title": "FY2025 有価証券報告書"}]}}
        self.assertEqual(_records(payload, "disclosures", "data"), [{"title": "FY2025 有価証券報告書"}])


if __name__ == "__main__":
    unittest.main()
