import sqlite3
import unittest

from src.db.models import SCHEMA
from src.ingestion.edgar_sync import map_companyfacts, sync_edgar_market


class FakeEdgarClient:
    def is_configured(self):
        return True

    def close(self):
        pass

    def fetch_company_tickers(self):
        return [
            {
                "ticker": "AAPL",
                "cik": 320193,
                "name": "Apple Inc.",
                "exchange": "Nasdaq",
            }
        ]

    def fetch_companyfacts(self, cik):
        def fact(value, concept_unit="USD", fy=2025, end="2025-09-27"):
            return {concept_unit: [{"fy": fy, "fp": "FY", "form": "10-K", "end": end, "filed": "2025-10-31", "val": value}]}

        return {
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": fact(391000000000)},
                    "OperatingIncomeLoss": {"units": fact(123000000000)},
                    "NetIncomeLoss": {"units": fact(94000000000)},
                    "EarningsPerShareDiluted": {"units": fact(6.12, concept_unit="USD/shares")},
                    "Assets": {"units": fact(364000000000)},
                    "Liabilities": {"units": fact(302000000000)},
                    "StockholdersEquity": {"units": fact(62000000000)},
                    "CashAndCashEquivalentsAtCarryingValue": {"units": fact(67000000000)},
                    "LongTermDebtCurrent": {"units": fact(11000000000)},
                    "LongTermDebtNoncurrent": {"units": fact(85000000000)},
                    "NetCashProvidedByUsedInOperatingActivities": {"units": fact(118000000000)},
                    "NetCashProvidedByUsedInInvestingActivities": {"units": fact(-9000000000)},
                    "NetCashProvidedByUsedInFinancingActivities": {"units": fact(-121000000000)},
                    "PaymentsToAcquirePropertyPlantAndEquipment": {"units": fact(10000000000)},
                    "WeightedAverageNumberOfDilutedSharesOutstanding": {"units": fact(15350000000, concept_unit="shares")},
                }
            }
        }

    def fetch_submissions(self, cik):
        return {
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-25-000079"],
                    "form": ["10-K"],
                    "filingDate": ["2025-10-31"],
                    "reportDate": ["2025-09-27"],
                    "primaryDocument": ["aapl-20250927.htm"],
                }
            }
        }


class FakePriceClient:
    def fetch_ohlc(self, ticker, start_date=None, end_date=None):
        return [
            {
                "date": "2026-01-02",
                "open": 190.0,
                "high": 198.0,
                "low": 189.0,
                "close": 196.5,
                "adjusted_close": 196.5,
                "volume": 58000000,
            }
        ]

    def fetch_dividends(self, ticker):
        return [{"date": "2026-02-14", "amount": 0.26}]


class EdgarSyncTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        for statement in SCHEMA:
            self.conn.execute(statement)

    def tearDown(self):
        self.conn.close()

    def test_companyfacts_are_mapped_to_financial_rows(self):
        rows = map_companyfacts(FakeEdgarClient().fetch_companyfacts(320193))
        self.assertEqual(rows[0]["fiscal_year"], 2025)
        self.assertEqual(rows[0]["free_cash_flow"], 108000000000.0)
        self.assertEqual(rows[0]["interest_bearing_debt"], 96000000000.0)

    def test_sync_edgar_market_inserts_company_financials_prices_and_filings(self):
        result = sync_edgar_market(
            self.conn,
            edgar_client=FakeEdgarClient(),
            price_client=FakePriceClient(),
            tickers="AAPL",
        )
        self.assertEqual(result["updated_companies"], 1)
        self.assertEqual(result["inserted_financials"], 1)
        self.assertEqual(result["inserted_prices"], 1)
        self.assertEqual(result["inserted_filings"], 1)
        self.assertEqual(result["inserted_actions"], 1)

        company = self.conn.execute("SELECT * FROM company_master WHERE ticker = 'AAPL'").fetchone()
        self.assertEqual(company["market"], "us")
        self.assertEqual(company["cik"], "320193")

        financial = self.conn.execute("SELECT * FROM financial_facts WHERE source = 'edgar'").fetchone()
        self.assertEqual(financial["currency"], "USD")

        filing = self.conn.execute("SELECT * FROM filings WHERE source = 'edgar'").fetchone()
        self.assertEqual(filing["document_type"], "10-K")


if __name__ == "__main__":
    unittest.main()
