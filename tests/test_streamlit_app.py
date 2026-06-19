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


if __name__ == "__main__":
    unittest.main()
