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

    def test_positive_catalyst_count_excludes_risk_events(self):
        events = [
            {"event_type": "earnings_revision_up", "catalyst_score": 25},
            {"event_type": "downward_revision", "catalyst_score": 0},
            {"event_type": "going_concern", "catalyst_score": None},
        ]
        self.assertEqual(positive_catalyst_count(events), 1)


if __name__ == "__main__":
    unittest.main()
