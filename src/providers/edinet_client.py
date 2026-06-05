import os
from urllib.parse import urlencode

import httpx

from src.utils.file_utils import load_env


class EdinetError(RuntimeError):
    pass


class EdinetClient:
    """Official EDINET API v2 helper for raw document downloads."""

    BASE_URL = "https://api.edinet-fsa.go.jp/api/v2"

    def __init__(self, api_key=None):
        load_env()
        self.api_key = api_key or os.environ.get("EDINET_API_KEY")

    def is_configured(self):
        return bool(self.api_key)

    def documents_url(self, target_date, doc_type=2):
        params = {"date": target_date, "type": doc_type}
        if self.api_key:
            params["Subscription-Key"] = self.api_key
        return "%s/documents.json?%s" % (self.BASE_URL, urlencode(params))

    def document_download_url(self, document_id, doc_type=5):
        params = {"type": doc_type}
        if self.api_key:
            params["Subscription-Key"] = self.api_key
        return "%s/documents/%s?%s" % (self.BASE_URL, document_id, urlencode(params))

    def fetch_documents(self, target_date, doc_type=2):
        if not self.is_configured():
            return []
        with httpx.Client(timeout=30.0) as client:
            response = client.get(self.documents_url(target_date, doc_type=doc_type))
            response.raise_for_status()
            return response.json().get("results", []) or []

    def fetch_xbrl_csv_zip(self, document_id):
        if not self.is_configured():
            return None
        with httpx.Client(timeout=60.0) as client:
            response = client.get(self.document_download_url(document_id, doc_type=5))
            response.raise_for_status()
            return response.content


def _clean_api_key(value):
    if not value:
        return None
    text = str(value).strip()
    if text.lower().startswith("bearer "):
        return text.split(" ", 1)[1].strip()
    return text


class EdinetDbClient:
    """EDINET DB REST API helper for structured listed-company data."""

    BASE_URL = "https://edinetdb.jp/v1"

    def __init__(self, api_key=None, base_url=None, timeout=30.0):
        load_env()
        self.api_key = _clean_api_key(
            api_key
            or os.environ.get("EDINETDB_API_KEY")
            or os.environ.get("EDINET_DB_API_KEY")
            or os.environ.get("EDINETDB_AUTH")
        )
        self.base_url = (base_url or os.environ.get("EDINETDB_BASE_URL") or self.BASE_URL).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def is_configured(self):
        return bool(self.api_key)

    def headers(self):
        if not self.api_key:
            return {}
        return {"X-API-Key": self.api_key, "Authorization": "Bearer %s" % self.api_key}

    def search_companies(self, query, limit=10):
        payload = self._get("/search", params={"q": query, "limit": limit})
        return _records(payload, "companies", "results", "data")

    def get_company(self, edinet_code, fields=None):
        params = {}
        if fields:
            params["fields"] = ",".join(fields) if isinstance(fields, (list, tuple)) else fields
        return self._get("/companies/%s" % edinet_code, params=params)

    def get_financials(self, edinet_code, years=6, period="annual"):
        payload = self._get(
            "/companies/%s/financials" % edinet_code,
            params={"years": years, "period": period},
        )
        return _records(payload, "financials", "data", "results")

    def get_disclosures(self, edinet_code, since=None, until=None, types=None):
        params = {}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if types:
            params["types"] = ",".join(types) if isinstance(types, (list, tuple)) else types
        payload = self._get("/companies/%s/disclosures" % edinet_code, params=params)
        return _records(payload, "disclosures", "data", "results")

    def get_text_blocks(self, edinet_code, fiscal_year=None, element_type=None):
        params = {}
        if fiscal_year:
            params["fiscal_year"] = fiscal_year
        if element_type:
            params["element_type"] = element_type
        payload = self._get("/companies/%s/text-blocks" % edinet_code, params=params)
        return _records(payload, "text_blocks", "blocks", "data", "results")

    def get_red_flags(self, edinet_code, years_lookback=3):
        payload = self._get(
            "/queries/red-flags",
            params={"company": edinet_code, "years_lookback": years_lookback},
        )
        return _records(payload, "flags", "data", "results")

    def _get(self, path, params=None):
        try:
            response = self._client.get(path, params=params, headers=self.headers())
        except httpx.HTTPError as exc:
            raise EdinetError("EDINET DB request failed: %s" % exc) from exc
        return self._json_or_error(response)

    def _json_or_error(self, response):
        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text[:300]}
        if response.status_code >= 400:
            message = payload.get("message") or payload.get("error") or response.reason_phrase
            raise EdinetError("EDINET DB request failed (%s): %s" % (response.status_code, message))
        return payload


def _records(payload, *keys):
    if isinstance(payload, list):
        return payload
    for key in keys:
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _records(value, *keys)
            if nested:
                return nested
    return []
