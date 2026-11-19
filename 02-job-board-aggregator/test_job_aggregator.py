import csv
import json
import tempfile
import unittest
from pathlib import Path

from job_aggregator import COLUMNS, aggregate, main, spreadsheet_safe

HERE = Path(__file__).parent


def sample(name):
    return json.loads((HERE / "sample" / name).read_text())


class AggregatorTests(unittest.TestCase):
    def test_normalizes_and_dedupes_by_url(self):
        rows = aggregate([("yc", sample("yc.json")), ("pph", sample("pph.json"))])
        urls = [r["url"] for r in rows]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(len(rows), 4)  # the PPH row repeating jobs.example/yc/3 is dropped
        pph = next(r for r in rows if r["source"] == "pph")
        self.assertEqual((pph["company"], pph["location"], pph["pay"]), ("Sam P.", "United Kingdom", "$120"))

    def test_keyword_filter(self):
        rows = aggregate([("yc", sample("yc.json")), ("pph", sample("pph.json"))], ["python"])
        self.assertEqual(sorted(r["url"] for r in rows), ["https://jobs.example/pph/1", "https://jobs.example/yc/1"])

    def test_hourly_is_not_a_pay_amount(self):
        rows = aggregate([("pph", [{"title": "t", "url": "u", "title_nano": "Hourly"}])])
        self.assertEqual(rows[0]["pay"], "")

    def test_formula_cells_are_marked_as_text(self):
        self.assertEqual(spreadsheet_safe('=SUM(A1)'), "'=SUM(A1)")
        self.assertEqual(spreadsheet_safe("-5"), "'-5")
        self.assertEqual(spreadsheet_safe("Engineer"), "Engineer")

    def test_sample_run_writes_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["--sample", "--out", tmp]), 0)
            with open(Path(tmp) / "jobs.csv", newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(list(rows[0].keys()), COLUMNS)
            self.assertTrue(any(r["title"].startswith("'=HYPERLINK") for r in rows))


if __name__ == "__main__":
    unittest.main()
