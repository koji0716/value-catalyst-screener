import tempfile
from pathlib import Path
import unittest

from src.analysis.scoring import positive_catalyst_count, recommendation_label, screen_companies
from src.db.migrations import init_db
from src.db.session import get_connection
from src.ingestion.sample_data import seed_sample_data


class ScoringWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmpdir.name) / "test_value_screener.sqlite"
        init_db(cls.db_path)
        conn = get_connection(cls.db_path)
        try:
            seed_sample_data(conn, reset=True)
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_recommendation_labels(self):
        self.assertEqual(recommendation_label(90), "Strong Candidate")
        self.assertEqual(recommendation_label(70), "Candidate")
        self.assertEqual(recommendation_label(55), "Watch")
        self.assertEqual(recommendation_label(40), "Weak")
        self.assertEqual(recommendation_label(39), "Exclude")

    def test_balanced_screen_returns_candidates(self):
        results, run_id = screen_companies("balanced", market="jp", db_path=self.db_path, save=True)
        self.assertTrue(run_id)
        self.assertGreater(len(results), 0)
        self.assertIn("total_score", results[0])

    def test_screening_can_replace_preset_filters_with_manual_conditions(self):
        results, run_id = screen_companies(
            "deep_value",
            market="jp",
            overrides={"max_per": 20},
            db_path=self.db_path,
            save=False,
            replace_filters=True,
        )
        self.assertIsNone(run_id)
        self.assertTrue(all(item["per"] is None or item["per"] <= 20 for item in results))

    def test_positive_catalyst_count_excludes_risk_events(self):
        events = [
            {"event_type": "earnings_revision_up", "catalyst_score": 25},
            {"event_type": "downward_revision", "catalyst_score": 0},
            {"event_type": "going_concern", "catalyst_score": None},
        ]
        self.assertEqual(positive_catalyst_count(events), 1)

    def test_sample_seed_can_filter_us_market(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sample_filter.sqlite"
            init_db(db_path)
            conn = get_connection(db_path)
            try:
                inserted = seed_sample_data(conn, reset=True, market="us")
                markets = [row["market"] for row in conn.execute("SELECT DISTINCT market FROM company_master").fetchall()]
            finally:
                conn.close()
            self.assertEqual(inserted, 4)
            self.assertEqual(markets, ["us"])

    def test_missing_latest_revenue_does_not_crash_screening(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "missing_revenue.sqlite"
            init_db(db_path)
            conn = get_connection(db_path)
            try:
                seed_sample_data(conn, reset=True, market="jp")
                latest = conn.execute(
                    """
                    SELECT ff.id
                    FROM financial_facts ff
                    JOIN company_master cm ON cm.id = ff.company_id
                    WHERE cm.market = 'jp'
                    ORDER BY ff.period_end DESC, ff.fiscal_year DESC
                    LIMIT 1
                    """
                ).fetchone()
                conn.execute("UPDATE financial_facts SET revenue = NULL WHERE id = ?", (latest["id"],))
                conn.commit()
            finally:
                conn.close()

            results, run_id = screen_companies("balanced", market="jp", db_path=db_path, save=False)
            self.assertIsNone(run_id)
            self.assertIsInstance(results, list)

    def test_missing_latest_price_does_not_crash_screening(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "missing_price.sqlite"
            init_db(db_path)
            conn = get_connection(db_path)
            try:
                seed_sample_data(conn, reset=True, market="jp")
                latest = conn.execute(
                    """
                    SELECT p.id
                    FROM prices p
                    JOIN company_master cm ON cm.id = p.company_id
                    WHERE cm.market = 'jp'
                    ORDER BY p.trade_date DESC
                    LIMIT 1
                    """
                ).fetchone()
                conn.execute("UPDATE prices SET close = NULL, adjusted_close = NULL WHERE id = ?", (latest["id"],))
                conn.commit()
            finally:
                conn.close()

            results, run_id = screen_companies("balanced", market="jp", db_path=db_path, save=False)
            self.assertIsNone(run_id)
            self.assertIsInstance(results, list)


if __name__ == "__main__":
    unittest.main()
