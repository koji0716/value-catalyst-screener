import unittest

from src.ui.glossary import GLOSSARY, GLOSSARY_ORDER, term_help, term_rows


class GlossaryTests(unittest.TestCase):
    def test_core_terms_have_plain_explanations_and_cautions(self):
        for term in [
            "PER",
            "PBR",
            "ROE",
            "自己資本比率",
            "カタリスト",
            "next_offset",
            "Strong Candidate",
            "Candidate",
            "Watch",
            "Weak",
            "Exclude",
        ]:
            self.assertIn(term, GLOSSARY)
            self.assertTrue(GLOSSARY[term]["plain"])
            self.assertTrue(GLOSSARY[term]["watch"])
            self.assertIn("注意点", term_help(term))

    def test_term_rows_follow_glossary_order(self):
        rows = term_rows(["PER", "PBR"])

        self.assertEqual([row["用語"] for row in rows], ["PER", "PBR"])
        self.assertEqual(GLOSSARY_ORDER[0], "PER")

    def test_unknown_term_returns_fallback(self):
        self.assertIn("まだ登録", term_help("UNKNOWN"))


if __name__ == "__main__":
    unittest.main()
