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
            return self._frame_to_rows(data)
        return []

    def fetch_ohlc_batch(self, tickers, start_date=None, end_date=None):
        symbols = [str(ticker).strip() for ticker in tickers or [] if str(ticker).strip()]
        if not symbols:
            return {}
        if self.provider != "yfinance":
            return {symbol: [] for symbol in symbols}
        try:
            import yfinance as yf  # type: ignore
        except Exception:
            return {symbol: [] for symbol in symbols}

        data = yf.download(
            symbols if len(symbols) > 1 else symbols[0],
            start=start_date,
            end=end_date,
            progress=False,
            auto_adjust=False,
            group_by="ticker",
            threads=True,
        )
        if data is None or data.empty:
            return {symbol: [] for symbol in symbols}
        if not hasattr(data.columns, "nlevels") or data.columns.nlevels == 1:
            return {symbols[0]: self._frame_to_rows(data)}

        rows_by_symbol = {}
        level0 = set(str(value) for value in data.columns.get_level_values(0))
        level1 = set(str(value) for value in data.columns.get_level_values(1))
        for symbol in symbols:
            if symbol in level0:
                frame = data[symbol]
            elif symbol in level1:
                frame = data.xs(symbol, axis=1, level=1)
            else:
                rows_by_symbol[symbol] = []
                continue
            rows_by_symbol[symbol] = self._frame_to_rows(frame)
        return rows_by_symbol

    def _frame_to_rows(self, data):
        if hasattr(data.columns, "nlevels") and data.columns.nlevels > 1:
            data = data.copy()
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
