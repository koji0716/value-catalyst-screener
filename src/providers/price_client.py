import os

from src.utils.file_utils import load_env


class PriceClient:
    def __init__(self, provider=None):
        load_env()
        self.provider = provider or os.environ.get("PRICE_PROVIDER", "yfinance")

    def fetch_ohlc(self, ticker, start_date=None, end_date=None):
        if self.provider == "yfinance":
            try:
                import yfinance as yf  # type: ignore
            except Exception:
                return []
            data = yf.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=False)
            if data is None or data.empty:
                return []
            if hasattr(data.columns, "nlevels") and data.columns.nlevels > 1:
                data.columns = [col[0] for col in data.columns]
            rows = []
            for record in data.reset_index().to_dict("records"):
                rows.append(
                    {
                        "date": record.get("Date") or record.get("Datetime"),
                        "open": record.get("Open"),
                        "high": record.get("High"),
                        "low": record.get("Low"),
                        "close": record.get("Close"),
                        "adjusted_close": record.get("Adj Close") or record.get("Close"),
                        "volume": record.get("Volume"),
                    }
                )
            return rows
        return []

    def fetch_dividends(self, ticker):
        if self.provider == "yfinance":
            try:
                import yfinance as yf  # type: ignore
            except Exception:
                return []
            series = yf.Ticker(ticker).dividends
            if series is None or series.empty:
                return []
            return [{"date": idx.date().isoformat(), "amount": float(value)} for idx, value in series.items()]
        return []

    def fetch_splits(self, ticker):
        if self.provider == "yfinance":
            try:
                import yfinance as yf  # type: ignore
            except Exception:
                return []
            series = yf.Ticker(ticker).splits
            if series is None or series.empty:
                return []
            return [{"date": idx.date().isoformat(), "ratio": float(value)} for idx, value in series.items()]
        return []
