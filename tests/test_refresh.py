import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.db.models import SCHEMA
from src.ingestion.refresh import refresh_until_current


class RefreshUntilCurrentTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "refresh.sqlite"
        conn = sqlite3.connect(self.db_path)
        try:
            for statement in SCHEMA:
                conn.execute(statement)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.tmpdir.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def insert_bulk_job(self, params, result, status="success"):
        conn = self.connect()
        try:
            conn.execute(
                """
                INSERT INTO sync_jobs (job_type, market, source, mode, status, params_json, result_json)
                VALUES ('bulk_sync', 'jp', 'jquants', 'bulk', ?, ?, ?)
                """,
                (status, json.dumps(params, sort_keys=True), json.dumps(result, sort_keys=True)),
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_company(self, conn, code):
        row = conn.execute(
            "SELECT id FROM company_master WHERE market = 'jp' AND ticker = ?",
            (code,),
        ).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            """
            INSERT INTO company_master (market, ticker, security_code, company_name, country, currency)
            VALUES ('jp', ?, ?, ?, 'JP', 'JPY')
            """,
            (code, code, "Company %s" % code),
        )
        return cur.lastrowid

    def fake_jp_sync(self, **kwargs):
        offset = int(kwargs.get("offset") or 0)
        limit = int(kwargs.get("limit") or 2)
        include_detail = any(
            kwargs.get(key)
            for key in ["include_prices", "include_financials", "include_dividends", "include_events"]
        )
        available = 4
        selected = max(0, min(limit, available - offset))
        next_offset = offset + selected
        codes = ["10%02d" % idx for idx in range(offset, next_offset)]

        conn = self.connect()
        try:
            for code in codes:
                company_id = self.upsert_company(conn, code)
                if include_detail:
                    conn.execute(
                        """
                        INSERT INTO prices (company_id, trade_date, close, adjusted_close, source)
                        VALUES (?, '2026-06-05', 100, 100, 'jquants')
                        """,
                        (company_id,),
                    )
                    conn.execute(
                        """
                        INSERT INTO financial_facts (company_id, source, period_end, revenue)
                        VALUES (?, 'jquants', '2026-03-31', 1000)
                        """,
                        (company_id,),
                    )
                    conn.execute(
                        """
                        INSERT INTO filings (company_id, source, document_id, filing_date)
                        VALUES (?, 'edinetdb', ?, '2026-06-01')
                        """,
                        (company_id, "doc-%s" % code),
                    )
            conn.commit()
        finally:
            conn.close()

        params = {
            "include_prices": bool(kwargs.get("include_prices")),
            "include_financials": bool(kwargs.get("include_financials")),
            "include_dividends": bool(kwargs.get("include_dividends")),
            "include_events": bool(kwargs.get("include_events")),
        }
        result = {
            "market": "jp",
            "source": "jquants",
            "mode": "bulk",
            "offset": offset,
            "limit": limit,
            "available_records": available,
            "selected_records": selected,
            "processed_codes": codes,
            "inserted_companies": selected if not include_detail else 0,
            "updated_companies": selected if include_detail else 0,
            "inserted_prices": selected if include_detail else 0,
            "inserted_financials": selected if include_detail else 0,
            "inserted_filings": selected if include_detail else 0,
            "next_offset": next_offset,
            "rate_limited": False,
            "warnings": [],
        }
        self.insert_bulk_job(params, result)
        return result

    def test_refresh_runs_master_then_detail_until_complete(self):
        result = refresh_until_current(
            market="jp",
            batch_limit=2,
            max_batches=10,
            db_path=self.db_path,
            sync_jp_func=self.fake_jp_sync,
            sleep_func=lambda _: None,
        )

        self.assertEqual(result["stopped_reason"], "complete")
        self.assertEqual(result["batches_run"], 4)
        jp_after = result["coverage_after"]["jp"]
        self.assertEqual(jp_after["master_progress_pct"], 100.0)
        self.assertEqual(jp_after["detail_progress_pct"], 100.0)
        self.assertEqual(jp_after["price_coverage_pct"], 100.0)
        self.assertEqual(jp_after["financial_coverage_pct"], 100.0)

        conn = self.connect()
        try:
            state = conn.execute(
                """
                SELECT status, message
                FROM sync_state
                WHERE source = 'refresh' AND mode = 'until_current' AND market = 'jp'
                """
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(state["status"], "success")
        self.assertIn("完了", state["message"])

    def test_refresh_stops_on_rate_limit_and_records_warning(self):
        for idx in range(3):
            conn = self.connect()
            try:
                self.upsert_company(conn, "20%02d" % idx)
                conn.commit()
            finally:
                conn.close()
        self.insert_bulk_job(
            {"include_prices": False, "include_financials": False},
            {"available_records": 3, "selected_records": 3, "next_offset": 3},
        )

        def rate_limited_sync(**kwargs):
            result = {
                "market": "jp",
                "source": "jquants",
                "mode": "bulk",
                "offset": kwargs.get("offset") or 0,
                "limit": kwargs.get("limit") or 10,
                "available_records": 3,
                "selected_records": 1,
                "processed_codes": ["2000"],
                "next_offset": kwargs.get("offset") or 0,
                "rate_limited": True,
                "warnings": ["2000: 429 Rate limit"],
            }
            self.insert_bulk_job(
                {"include_prices": True, "include_financials": True},
                result,
                status="warning",
            )
            return result

        result = refresh_until_current(
            market="jp",
            batch_limit=1,
            max_batches=5,
            db_path=self.db_path,
            sync_jp_func=rate_limited_sync,
            sleep_func=lambda _: None,
        )

        self.assertEqual(result["stopped_reason"], "rate_limited")
        self.assertEqual(result["batches_run"], 1)
        self.assertIn("API制限", result["next_action"])


if __name__ == "__main__":
    unittest.main()
