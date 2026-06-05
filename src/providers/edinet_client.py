import os
from urllib.parse import urlencode


class EdinetClient:
    BASE_URL = "https://api.edinet-fsa.go.jp/api/v2"

    def __init__(self, api_key=None):
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
        raise NotImplementedError("EDINET fetch is planned for MVP 3.")

    def fetch_xbrl_csv_zip(self, document_id):
        if not self.is_configured():
            return None
        raise NotImplementedError("EDINET XBRL parsing is planned for MVP 3.")

