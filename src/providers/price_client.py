import os


class PriceClient:
    def __init__(self, provider=None):
        self.provider = provider or os.environ.get("PRICE_PROVIDER", "yfinance")

    def fetch_ohlc(self, ticker, start_date=None, end_date=None):
        if self.provider == "yfinance":
            try:
                import yfinance as yf  # type: ignore
            except Exception:
                return []
            data = yf.download(ticker, start=start_date, end=end_date, progress=False)
            return data.reset_index().to_dict("records")
        return []

    def fetch_dividends(self, ticker):
        return []

    def fetch_splits(self, ticker):
        return []

