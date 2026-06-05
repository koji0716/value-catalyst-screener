import unittest

from src.analysis.scoring import recommendation_label, screen_companies
from src.db.migrations import init_db
from src.db.session import get_connection
from src.ingestion.sample_data import seed_sample_data


class ScoringWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        conn = get_connection()
        try:
            seed_sample_data(conn, reset=True)
        finally:
            conn.close()

    def test_recommendation_labels(self):
        self.assertEqual(recommendation_label(90), "Strong Candidate")
        self.assertEqual(recommendation_label(70), "Candidate")
        self.assertEqual(recommendation_label(55), "Watch")
        self.assertEqual(recommendation_label(40), "Weak")
        self.assertEqual(recommendation_label(39), "Exclude")

    def test_balanced_screen_returns_candidates(self):
        results, run_id = screen_companies("balanced", market="jp", save=True)
        self.assertTrue(run_id)
        self.assertGreater(len(results), 0)
        self.assertIn("total_score", results[0])


if __name__ == "__main__":
    unittest.main()
