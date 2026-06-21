import copy
import unittest
from pathlib import Path

import evaluate_system


ROOT = Path(__file__).resolve().parents[1]


class EvaluationRunnerTests(unittest.TestCase):
    def test_default_dataset_validates(self):
        metadata, items = evaluate_system.validate_dataset(
            evaluate_system.load_json(ROOT / "eval_dataset.json")
        )
        self.assertEqual(metadata["dataset_type"], "smoke")
        self.assertGreaterEqual(len(items), 20)

    def test_duplicate_ids_fail_validation(self):
        dataset = evaluate_system.load_json(ROOT / "eval_dataset.json")
        duplicate = copy.deepcopy(dataset)
        duplicate["items"][1]["id"] = duplicate["items"][0]["id"]
        with self.assertRaises(evaluate_system.EvaluationError):
            evaluate_system.validate_dataset(duplicate)

    def test_rule_judge_scores_english_refusal(self):
        item = {
            "id": "unit-en",
            "question": "What is not in the sources?",
            "language": "en",
            "category": "missing",
            "ground_truth_answer": "Should refuse.",
            "expected_behavior": "refusal",
        }
        scores = evaluate_system.rule_judge(
            item,
            "Information unavailable in the current sources. Contact: 00963116990200",
            [],
        )
        self.assertEqual(scores["correctness"], 2)
        self.assertEqual(scores["refusal"], 2)
        self.assertEqual(scores["language"], 2)

    def test_rule_judge_scores_arabic_refusal(self):
        item = {
            "id": "unit-ar",
            "question": "ما المعلومة غير المتوفرة؟",
            "language": "ar",
            "category": "missing",
            "ground_truth_answer": "يجب الرفض.",
            "expected_behavior": "refusal",
        }
        scores = evaluate_system.rule_judge(
            item,
            "المعلومة غير متوفرة في المصادر الحالية. للاستفسار: 00963116990200",
            [],
        )
        self.assertEqual(scores["correctness"], 2)
        self.assertEqual(scores["refusal"], 2)
        self.assertEqual(scores["language"], 2)

    def test_threshold_application_marks_failure(self):
        report = {
            "overall": {"correctness": 0.5},
        }
        updated = evaluate_system.apply_thresholds(report, {"correctness": 0.95})
        self.assertFalse(updated["thresholds"]["passed"])


if __name__ == "__main__":
    unittest.main()
