import unittest

from src.utils.file_utils import load_presets


class PresetTests(unittest.TestCase):
    def test_required_presets_exist(self):
        presets = load_presets()
        for name in ["balanced", "deep_value", "quality_value", "catalyst_value", "rebound_value"]:
            self.assertIn(name, presets)

    def test_balanced_weights_sum_to_one_with_risk_component(self):
        weights = load_presets()["balanced"]["weights"]
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_catalyst_preset_requires_recent_catalyst(self):
        filters = load_presets()["catalyst_value"]["filters"]
        self.assertTrue(filters["require_recent_catalyst"])


if __name__ == "__main__":
    unittest.main()

