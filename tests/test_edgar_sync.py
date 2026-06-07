import sqlite3
import unittest

from src.db.models import SCHEMA
from src.ingestion.edgar_sync import filtered_ticker_records, map_companyfacts, sync_edgar_bulk_market, sync_edgar_market
from src.providers.edgar_client import EdgarError


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
            },
            {
                "ticker": "GM",
                "cik": 1467858,
                "name": "General Motors Company",
                "exchange": "NYSE",
            },
            {
                "ticker": "OTCM",
                "cik": 999999,
                "name": "OTC Markets Group Inc.",
                "exchange": "OTC",
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

    def fetch_ohlc_batch(self, tickers, start_date=None, end_date=None):
        return {ticker: self.fetch_ohlc(ticker, start_date=start_date, end_date=end_date) for ticker in tickers}

    def fetch_dividends(self, ticker):
        return [{"date": "2026-02-14", "amount": 0.26}]


class MissingFactsEdgarClient(FakeEdgarClient):
    def fetch_companyfacts(self, cik):
        raise EdgarError("SEC EDGAR request failed (404): NoSuchKey")


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

    def test_filtered_ticker_records_support_exchange_offset_and_limit(self):
        rows, available = filtered_ticker_records(
            FakeEdgarClient().fetch_company_tickers(),
            exchanges="nasdaq,nyse",
            offset=1,
            limit=1,
        )
        self.assertEqual(available, 2)
        self.assertEqual([row["ticker"] for row in rows], ["GM"])

    def test_sync_edgar_bulk_market_can_import_master_only_and_resume(self):
        result = sync_edgar_bulk_market(
            self.conn,
            edgar_client=FakeEdgarClient(),
            price_client=FakePriceClient(),
            exchanges="Nasdaq,NYSE",
            limit=2,
            include_prices=False,
            include_financials=False,
            include_filings=False,
            include_dividends=False,
        )
        self.assertEqual(result["available_records"], 2)
        self.assertEqual(result["selected_records"], 2)
        self.assertEqual(result["inserted_companies"], 2)
        self.assertEqual(result["processed_tickers"], ["AAPL", "GM"])

        second = sync_edgar_bulk_market(
            self.conn,
            edgar_client=FakeEdgarClient(),
            price_client=FakePriceClient(),
            exchanges="Nasdaq,NYSE",
            limit=2,
            include_prices=False,
            include_financials=False,
            include_filings=False,
            include_dividends=False,
        )
        self.assertEqual(second["skipped_existing"], 2)
        self.assertEqual(second["processed_tickers"], [])

    def test_sync_edgar_bulk_market_records_permanent_missing_financials(self):
        result = sync_edgar_bulk_market(
            self.conn,
            edgar_client=MissingFactsEdgarClient(),
            price_client=FakePriceClient(),
            exchanges="Nasdaq",
            limit=1,
            include_prices=False,
            include_financials=True,
            include_filings=False,
            include_dividends=False,
        )
        self.assertEqual(result["processed_tickers"], ["AAPL"])
        self.assertEqual(result["skipped_unavailable"], 0)
        row = self.conn.execute(
            """
            SELECT market, source, data_type, identifier, attempts
            FROM unavailable_data
            WHERE market = 'us' AND source = 'edgar' AND data_type = 'financials'
            """
        ).fetchone()
        self.assertEqual(row["identifier"], "320193")

        second = sync_edgar_bulk_market(
            self.conn,
            edgar_client=MissingFactsEdgarClient(),
            price_client=FakePriceClient(),
            exchanges="Nasdaq",
            limit=1,
            include_prices=False,
            include_financials=True,
            include_filings=False,
            include_dividends=False,
        )
        self.assertEqual(second["skipped_existing"], 1)


if __name__ == "__main__":
    unittest.main()
