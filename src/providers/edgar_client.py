import os
import time

import httpx

from src.utils.file_utils import load_env, load_settings


class EdgarError(RuntimeError):
    pass


class EdgarClient:
    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK%s.json"
    COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json"
    TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

    def __init__(self, user_agent=None, timeout=30.0, rate_limit_per_sec=None):
        load_env()
        settings = load_settings()
        provider_settings = settings.get("providers") or {}
        self.user_agent = user_agent or os.environ.get("SEC_USER_AGENT")
        self.rate_limit_per_sec = rate_limit_per_sec or provider_settings.get("edgar_rate_limit_per_sec", 10)
        self._last_request_at = 0.0
        self._client = httpx.Client(timeout=timeout)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def is_configured(self):
        return bool(self.user_agent)

    def headers(self):
        return {
            "User-Agent": self.user_agent or "ValueCatalystScreener local@example.com",
            "Accept-Encoding": "gzip, deflate",
        }

    def cik10(self, cik):
        return str(cik).zfill(10)

    def submissions_url(self, cik):
        return self.SUBMISSIONS_URL % self.cik10(cik)

    def companyfacts_url(self, cik):
        return self.COMPANYFACTS_URL % self.cik10(cik)

    def fetch_company_tickers(self):
        payload = self._get(self.TICKERS_URL)
        fields = payload.get("fields", [])
        records = []
        for row in payload.get("data", []) or []:
            item = {field: row[idx] if idx < len(row) else None for idx, field in enumerate(fields)}
            records.append(item)
        return records

    def fetch_companyfacts(self, cik):
        return self._get(self.companyfacts_url(cik))

    def fetch_submissions(self, cik):
        return self._get(self.submissions_url(cik))

    def _get(self, url):
        self._wait_for_rate_limit()
        try:
            response = self._client.get(url, headers=self.headers())
        except httpx.HTTPError as exc:
            raise EdgarError("SEC EDGAR request failed: %s" % exc) from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text[:300]}
        if response.status_code >= 400:
            message = payload.get("message") or payload.get("error") or response.reason_phrase
            raise EdgarError("SEC EDGAR request failed (%s): %s" % (response.status_code, message))
        return payload

    def _wait_for_rate_limit(self):
        try:
            per_sec = float(self.rate_limit_per_sec)
        except (TypeError, ValueError):
            per_sec = 10.0
        if per_sec <= 0:
            return
        min_interval = 1.0 / per_sec
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_at = time.monotonic()
