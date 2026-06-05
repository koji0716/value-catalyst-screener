import os


class JQuantsClient:
    BASE_URL = "https://api.jquants.com/v1"

    def __init__(self, email=None, password=None, refresh_token=None):
        self.email = email or os.environ.get("JQUANTS_EMAIL")
        self.password = password or os.environ.get("JQUANTS_PASSWORD")
        self.refresh_token = refresh_token or os.environ.get("JQUANTS_REFRESH_TOKEN")

    def is_configured(self):
        return bool(self.refresh_token or (self.email and self.password))

    def authenticate(self):
        if not self.is_configured():
            return None
        raise NotImplementedError("J-Quants authentication is planned for MVP 2.")

    def fetch_listed_info(self):
        return []

    def fetch_prices(self, code, start_date=None, end_date=None):
        return []

    def fetch_financial_statements(self, code):
        return []

    def fetch_dividends(self, code):
        return []

    def fetch_earnings_calendar(self):
        return []

