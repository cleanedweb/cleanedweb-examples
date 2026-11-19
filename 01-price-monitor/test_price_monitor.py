import json
import unittest
from pathlib import Path

from price_monitor import diff_snapshots, format_report, normalize, to_price

HERE = Path(__file__).parent
FIELDS = ("url", ["brand", "item_name"], "price", "currency")


def load(name):
    return normalize(json.loads((HERE / "sample" / name).read_text()), *FIELDS)


class PriceMonitorTests(unittest.TestCase):
    def test_to_price(self):
        self.assertEqual(to_price(12), 12.0)
        self.assertEqual(to_price("132,00"), 132.0)
        self.assertEqual(to_price("1,299.50 EUR"), 1299.5)
        self.assertEqual(to_price("1.299,50"), 1299.5)
        self.assertIsNone(to_price(None))
        self.assertIsNone(to_price(True))
        self.assertIsNone(to_price("call us"))

    def test_missing_price_is_skipped_not_zero(self):
        day1 = load("day1.json")
        self.assertNotIn("https://shop.example/p/4", day1)
        self.assertEqual(len(day1), 3)

    def test_diff(self):
        changes = diff_snapshots(load("day1.json"), load("day2.json"))
        self.assertEqual([c[0] for c in changes["drops"]], ["https://shop.example/p/1"])
        self.assertEqual([c[0] for c in changes["rises"]], ["https://shop.example/p/3"])
        self.assertEqual([c[0] for c in changes["new"]], ["https://shop.example/p/5"])
        self.assertEqual(changes["not_seen"], [])  # unchanged price (p/2) is neither

    def test_threshold_and_not_seen(self):
        day1, day2 = load("day1.json"), load("day2.json")
        self.assertEqual(diff_snapshots(day1, day2, min_change_pct=50)["drops"], [])
        later = {k: v for k, v in day2.items() if k != "https://shop.example/p/1"}
        seen = diff_snapshots(day1, later)["not_seen"]
        self.assertEqual([k for k, _ in seen], ["https://shop.example/p/1"])
        self.assertIn("not a removal", format_report(diff_snapshots(day1, later)))

    def test_report_text(self):
        report = format_report(diff_snapshots(load("day1.json"), load("day2.json")))
        self.assertIn("Soprano Uke: 59.00 EUR -> 49.00 EUR (-16.9%)", report)
        self.assertIn("Price rises (1)", report)


if __name__ == "__main__":
    unittest.main()
