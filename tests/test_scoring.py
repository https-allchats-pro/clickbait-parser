from __future__ import annotations

import unittest

from domain.scoring import (
    ScoringConfig,
    ScoringMode,
    compute_post_scoring,
    default_mode_for_model,
)


class ScoringConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = ScoringConfig()
        self.assertEqual(cfg.rules_weight, 0.3)
        self.assertEqual(cfg.ml_weight, 0.7)
        self.assertEqual(cfg.threshold, 0.70)

    def test_invalid_weight(self) -> None:
        with self.assertRaises(ValueError):
            ScoringConfig(rules_weight=1.5)


class ComputePostScoringTests(unittest.TestCase):
    def test_rules_only(self) -> None:
        s = compute_post_scoring(
            rules_score=0.72,
            ml_score=0.91,
            mode=ScoringMode.RULES,
        )
        self.assertAlmostEqual(s.final_score, 0.72)
        self.assertFalse(s.used_ml)
        self.assertTrue(s.is_clickbait)  # 0.72 >= 0.70

    def test_ml_only(self) -> None:
        s = compute_post_scoring(
            rules_score=0.72,
            ml_score=0.91,
            mode=ScoringMode.ML,
        )
        self.assertAlmostEqual(s.final_score, 0.91)
        self.assertTrue(s.used_ml)

    def test_hybrid_blend(self) -> None:
        s = compute_post_scoring(
            rules_score=0.72,
            ml_score=0.91,
            mode=ScoringMode.RULES_ML,
            config=ScoringConfig(rules_weight=0.3, ml_weight=0.7, threshold=0.70),
        )
        expected = 0.72 * 0.3 + 0.91 * 0.7
        self.assertAlmostEqual(s.final_score, expected, places=5)
        self.assertTrue(s.is_clickbait)

    def test_hybrid_falls_back_without_ml(self) -> None:
        s = compute_post_scoring(
            rules_score=0.40,
            ml_score=None,
            mode=ScoringMode.RULES_ML,
        )
        self.assertAlmostEqual(s.final_score, 0.40)
        self.assertFalse(s.used_ml)
        self.assertFalse(s.ml_available)
        self.assertFalse(s.is_clickbait)

    def test_ml_mode_falls_back_without_model(self) -> None:
        s = compute_post_scoring(
            rules_score=0.55,
            ml_score=None,
            mode=ScoringMode.ML,
        )
        self.assertAlmostEqual(s.final_score, 0.55)
        self.assertEqual(s.effective_mode, ScoringMode.RULES)

    def test_threshold_boundary(self) -> None:
        low = compute_post_scoring(
            rules_score=0.69,
            ml_score=None,
            mode=ScoringMode.RULES,
            config=ScoringConfig(threshold=0.70),
        )
        high = compute_post_scoring(
            rules_score=0.70,
            ml_score=None,
            mode=ScoringMode.RULES,
            config=ScoringConfig(threshold=0.70),
        )
        self.assertFalse(low.is_clickbait)
        self.assertTrue(high.is_clickbait)

    def test_default_mode(self) -> None:
        self.assertEqual(default_mode_for_model(model_ready=False), ScoringMode.RULES)
        self.assertEqual(default_mode_for_model(model_ready=True), ScoringMode.RULES)


if __name__ == "__main__":
    unittest.main()
