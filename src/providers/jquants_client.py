import json
import os
import time
from datetime import date

import httpx

from src.utils.file_utils import load_env


class JQuantsError(RuntimeError):
    pass


class JQuantsAuthError(JQuantsError):
    pass


def normalize_issue_code(value):
    if value is None:
        return None
    code = str(value).strip()
    if len(code) == 5 and code.endswith("0"):
        return code[:4]
    return code


def jquants_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return "%s-%s-%s" % (text[:4], text[4:6], text[6:])
    return text


def jquants_query_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    return text.replace("-", "")


def to_float(value):
    if value in (None, "", "-", "－"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def first_value(record, *keys):
    for key in keys:
        value = record.get(key)
        if value not in (None, "", "-", "－"):
            return value
    return None


class JQuantsClient:
    BASE_URL = "https://api.jquants.com/v2"

    def __init__(
        self,
        email=None,
        password=None,
        refresh_token=None,
        id_token=None,
        base_url=None,
        timeout=30.0,
        sleep_seconds=0.2,
    ):
        load_env()
        self.email = email or os.environ.get("JQUANTS_EMAIL")
        self.password = password or os.environ.get("JQUANTS_PASSWORD")
        self.api_key = (
            os.environ.get("JQUANTS_API_KEY")
            or refresh_token
            or os.environ.get("JQUANTS_REFRESH_TOKEN")
        )
        self.refresh_token = (
            refresh_token
            or os.environ.get("JQUANTS_REFRESH_TOKEN")
        )
        self.id_token = id_token or os.environ.get("JQUANTS_ID_TOKEN")
        self.base_url = (base_url or os.environ.get("JQUANTS_BASE_URL") or self.BASE_URL).rstrip("/")
        self.sleep_seconds = sleep_seconds
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def is_configured(self):
        return bool(self.api_key or self.id_token or self.refresh_token or (self.email and self.password))

    def authenticate(self, force=False):
        if self.id_token and not force:
            return self.id_token
        if not self.refresh_token:
            self.refresh_token = self.fetch_refresh_token()
        if not self.refresh_token:
            raise JQuantsAuthError("J-Quants refresh token is not configured.")

        response = self._client.post(
            "/token/auth_refresh",
            params={"refreshtoken": self.refresh_token},
        )
        payload = self._json_or_error(response)
        token = payload.get("idToken")
        if not token:
            raise JQuantsAuthError("J-Quants did not return an ID token.")
        self.id_token = token
        return self.id_token

    def fetch_refresh_token(self):
        if not (self.email and self.password):
            return None
        response = self._client.post(
            "/token/auth_user",
            content=json.dumps({"mailaddress": self.email, "password": self.password}),
            headers={"Content-Type": "application/json"},
        )
        payload = self._json_or_error(response)
        token = payload.get("refreshToken")
        if not token:
            raise JQuantsAuthError("J-Quants did not return a refresh token.")
        return token

    def fetch_listed_info(self, date_value=None, code=None):
        params = {}
        if date_value:
            params["date"] = jquants_query_date(date_value)
        if code:
            params["code"] = normalize_issue_code(code)
        return self._get_paginated("/equities/master", "data", params)

    def fetch_prices(self, code, start_date=None, end_date=None, date_value=None):
        params = {"code": normalize_issue_code(code)}
        if date_value:
            params["date"] = jquants_query_date(date_value)
        else:
            if start_date:
                params["from"] = jquants_query_date(start_date)
            if end_date:
                params["to"] = jquants_query_date(end_date)
        return self._get_paginated("/equities/bars/daily", "data", params)

    def fetch_financial_statements(self, code=None, date_value=None):
        params = {}
        if code:
            params["code"] = normalize_issue_code(code)
        if date_value:
            params["date"] = jquants_query_date(date_value)
        if not params:
            raise ValueError("code or date_value is required for J-Quants statements.")
        return self._get_paginated("/fins/summary", "data", params)

    def fetch_dividends(self, code=None, date_value=None):
        params = {}
        if code:
            params["code"] = normalize_issue_code(code)
        if date_value:
            params["date"] = jquants_query_date(date_value)
        return self._get_paginated("/fins/dividend", "data", params)

    def fetch_earnings_calendar(self):
        return self._get_paginated("/equities/earnings-calendar", "data", {})

    def _headers(self):
        if self.api_key:
            return {"x-api-key": self.api_key}
        token = self.authenticate()
        return {"Authorization": "Bearer %s" % token}

    def _get_paginated(self, path, result_key, params):
        records = []
        query = {key: value for key, value in params.items() if value not in (None, "")}
        while True:
            response = self._client.get(path, params=query, headers=self._headers())
            if response.status_code == 401 and not self.api_key:
                self.authenticate(force=True)
                response = self._client.get(path, params=query, headers=self._headers())
            payload = self._json_or_error(response)
            records.extend(payload.get(result_key, []) or [])
            pagination_key = payload.get("pagination_key")
            if not pagination_key:
                break
            query["pagination_key"] = pagination_key
            if self.sleep_seconds:
                time.sleep(self.sleep_seconds)
        return records

    def _json_or_error(self, response):
        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text[:300]}
        if response.status_code >= 400:
            message = payload.get("message") or response.reason_phrase
            if response.status_code in (401, 403):
                raise JQuantsAuthError("J-Quants authentication failed: %s" % message)
            raise JQuantsError("J-Quants request failed (%s): %s" % (response.status_code, message))
        return payload
