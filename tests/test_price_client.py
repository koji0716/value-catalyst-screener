import sys
import types
import unittest

import pandas as pd

from src.providers.price_client import PriceClient


class PriceClientTests(unittest.TestCase):
    def setUp(self):
        self.original_yfinance = sys.modules.get("yfinance")
        fake = types.SimpleNamespace()

        def download(ticker, start=None, end=None, progress=False, auto_adjust=False, group_by=None, threads=True):
            if isinstance(ticker, list):
                index = pd.to_datetime(["2026-01-02"])
                data = pd.DataFrame(
                    {
                        ("AAPL", "Open"): [190.0],
                        ("AAPL", "High"): [198.0],
                        ("AAPL", "Low"): [189.0],
                        ("AAPL", "Close"): [196.5],
                        ("AAPL", "Adj Close"): [196.1],
                        ("AAPL", "Volume"): [58000000],
                        ("MSFT", "Open"): [410.0],
                        ("MSFT", "High"): [420.0],
                        ("MSFT", "Low"): [409.0],
                        ("MSFT", "Close"): [418.0],
                        ("MSFT", "Adj Close"): [417.5],
                        ("MSFT", "Volume"): [22000000],
                    },
                    index=index,
                )
                data.index.name = "Date"
                data.columns = pd.MultiIndex.from_tuples(data.columns)
                return data
            data = pd.DataFrame(
                {
                    "Open": [190.0],
                    "High": [198.0],
                    "Low": [189.0],
                    "Close": [196.5],
                    "Adj Close": [196.1],
                    "Volume": [58000000],
                },
                index=pd.to_datetime(["2026-01-02"]),
            )
            data.index.name = "Date"
            return data

        class FakeTicker:
            def __init__(self, ticker):
                self.ticker = ticker
                self.dividends = pd.Series([0.26], index=pd.to_datetime(["2026-02-14"]))
                self.splits = pd.Series([4.0], index=pd.to_datetime(["2026-03-01"]))

        fake.download = download
        fake.Ticker = FakeTicker
        sys.modules["yfinance"] = fake

    def tearDown(self):
        if self.original_yfinance is None:
            sys.modules.pop("yfinance", None)
        else:
            sys.modules["yfinance"] = self.original_yfinance

    def test_fetch_ohlc_normalizes_yfinance_rows(self):
        rows = PriceClient(provider="yfinance").fetch_ohlc("AAPL", start_date="2026-01-01")
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0]["date"])[:10], "2026-01-02")
        self.assertEqual(rows[0]["adjusted_close"], 196.1)
        self.assertEqual(rows[0]["volume"], 58000000)

    def test_fetch_ohlc_batch_normalizes_multi_ticker_download(self):
        rows = PriceClient(provider="yfinance").fetch_ohlc_batch(["AAPL", "MSFT"], start_date="2026-01-01")
        self.assertEqual(rows["AAPL"][0]["close"], 196.5)
        self.assertEqual(rows["MSFT"][0]["adjusted_close"], 417.5)

    def test_fetch_dividends_and_splits_normalize_series(self):
        client = PriceClient(provider="yfinance")
        self.assertEqual(client.fetch_dividends("AAPL"), [{"date": "2026-02-14", "amount": 0.26}])
        self.assertEqual(client.fetch_splits("AAPL"), [{"date": "2026-03-01", "ratio": 4.0}])


if __name__ == "__main__":
    unittest.main()
