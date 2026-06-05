class TdnetClient:
    def __init__(self, api_key=None):
        self.api_key = api_key

    def is_configured(self):
        return bool(self.api_key)

    def fetch_disclosures(self, start_date=None, end_date=None):
        return []

    def classify_event(self, title):
        text = title or ""
        if "上方修正" in text:
            return "earnings_revision_up"
        if "増配" in text:
            return "dividend_increase"
        if "自己株" in text:
            return "share_buyback"
        if "資本提携" in text or "買収" in text:
            return "ma_or_capital_alliance"
        return "other"

