import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Services" / "QA_Chatting"))

from telemetry import estimate_openai_cost, openai_usage_to_dict


class TelemetryTests(unittest.TestCase):
    def test_openai_usage_parser_handles_cached_tokens(self):
        usage = openai_usage_to_dict(
            {
                "input_tokens": 1200,
                "output_tokens": 300,
                "input_tokens_details": {"cached_tokens": 500},
            }
        )
        self.assertEqual(usage["input_tokens"], 1200)
        self.assertEqual(usage["cached_input_tokens"], 500)
        self.assertEqual(usage["uncached_input_tokens"], 700)
        self.assertEqual(usage["output_tokens"], 300)
        self.assertEqual(usage["total_tokens"], 1500)

    def test_openai_usage_parser_handles_legacy_names(self):
        usage = openai_usage_to_dict(
            {
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "prompt_tokens_details": {"cached_tokens": 25},
            }
        )
        self.assertEqual(usage["input_tokens"], 100)
        self.assertEqual(usage["output_tokens"], 40)
        self.assertEqual(usage["cached_input_tokens"], 25)

    def test_cost_estimation_separates_cached_and_uncached_input(self):
        cost = estimate_openai_cost(
            {
                "uncached_input_tokens": 750_000,
                "cached_input_tokens": 250_000,
                "output_tokens": 100_000,
            },
            input_price_per_1m=1.0,
            cached_input_price_per_1m=0.25,
            output_price_per_1m=4.0,
        )
        self.assertEqual(cost["input_usd"], 0.75)
        self.assertEqual(cost["cached_input_usd"], 0.0625)
        self.assertEqual(cost["output_usd"], 0.4)
        self.assertEqual(cost["total_usd"], 1.2125)

    def test_cost_estimation_is_optional_without_prices(self):
        self.assertIsNone(estimate_openai_cost({"input_tokens": 10}, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
