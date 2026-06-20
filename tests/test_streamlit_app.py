import unittest
from unittest.mock import patch

from src.ui import streamlit_app


class StreamlitAppTests(unittest.TestCase):
    def test_stale_us_price_update_returns_status_key(self):
        with patch.object(
            streamlit_app,
            "refresh_stale_us_prices",
            return_value={"stopped_reason": "complete", "inserted_prices": 1},
        ):
            result = streamlit_app.run_stale_us_price_update(
                stale_before="2026-06-10",
                end_date=None,
                batch_limit=10,
                max_batches=1,
                sleep_sec=0,
            )

        self.assertEqual(result["status"], "success")
        self.assertNotIn("overall", result)
        self.assertEqual(result["runs"][0]["status"], "success")

    def test_status_message_accepts_legacy_overall_key(self):
        with patch.object(streamlit_app.st, "warning") as warning:
            streamlit_app.render_status_message(
                {
                    "overall": "warning",
                    "message": "legacy result",
                }
            )

        warning.assert_called_once_with("legacy result")

    def test_price_only_update_uses_stale_us_price_refresh(self):
        with patch.object(
            streamlit_app,
            "refresh_stale_us_prices",
            return_value={"stopped_reason": "complete", "inserted_prices": 3},
        ) as refresh:
            result = streamlit_app.run_price_only_update(
                target="us",
                stale_before="2026-06-10",
                start_date="2025-01-01",
                end_date=None,
                batch_limit=100,
                max_batches=20,
                sleep_sec=1,
            )

        self.assertEqual(result["status"], "success")
        refresh.assert_called_once()
        kwargs = refresh.call_args.kwargs
        self.assertTrue(kwargs["include_no_price"])
        self.assertFalse(kwargs["include_financials"])
        self.assertFalse(kwargs["include_filings"])
        self.assertFalse(kwargs["include_dividends"])

    def test_non_price_update_excludes_prices_for_us_refresh(self):
        with patch.object(
            streamlit_app,
            "refresh_until_current",
            return_value={"stopped_reason": "complete"},
        ) as refresh:
            result = streamlit_app.run_non_price_update(
                target="us",
                start_date="2025-01-01",
                end_date=None,
                batch_limit=100,
                max_batches=20,
                sleep_sec=1,
            )

        self.assertEqual(result["status"], "success")
        refresh.assert_called_once()
        kwargs = refresh.call_args.kwargs
        self.assertFalse(kwargs["include_prices"])
        self.assertTrue(kwargs["include_financials"])
        self.assertTrue(kwargs["include_filings"])
        self.assertTrue(kwargs["include_dividends"])


if __name__ == "__main__":
    unittest.main()
