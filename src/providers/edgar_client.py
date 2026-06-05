import os


class EdgarClient:
    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK%s.json"
    COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json"
    TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

    def __init__(self, user_agent=None):
        self.user_agent = user_agent or os.environ.get("SEC_USER_AGENT")

    def is_configured(self):
        return bool(self.user_agent)

    def headers(self):
        return {"User-Agent": self.user_agent or "ValueCatalystScreener local@example.com"}

    def cik10(self, cik):
        return str(cik).zfill(10)

    def submissions_url(self, cik):
        return self.SUBMISSIONS_URL % self.cik10(cik)

    def companyfacts_url(self, cik):
        return self.COMPANYFACTS_URL % self.cik10(cik)

    def fetch_company_tickers(self):
        raise NotImplementedError("SEC EDGAR integration is planned for MVP 5.")

    def fetch_companyfacts(self, cik):
        raise NotImplementedError("SEC EDGAR integration is planned for MVP 5.")

