import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from summarize_diff import compare, md, render

SCRIPT = Path(__file__).parent / "summarize_diff.py"


class SummarizeTests(unittest.TestCase):
    def test_compare(self):
        old = [{"url": "a", "title": "A", "n": 1}, {"url": "b", "title": "B"}]
        new = [{"url": "a", "title": "A", "n": 2}, {"url": "c", "title": "C"}]
        diff = compare(old, new, "url")
        self.assertEqual([r["url"] for r in diff["added"]], ["c"])
        self.assertEqual([r["url"] for r in diff["gone"]], ["b"])
        self.assertEqual(diff["changed"][0][1], ["n"])

    def test_render_escapes_website_text(self):
        text = render("d.json", [], [{"url": "x", "title": "[click](http://evil.example) <script>\n@everyone"}], "url", "title")
        self.assertNotIn("[click](", text)
        self.assertNotIn("<script>", text)
        self.assertEqual(md("a\x00b"), "a b")

    def test_first_snapshot(self):
        self.assertIn("First snapshot: 1 records", render("d.json", None, [{"url": "x"}], "url", "title"))

    def test_against_a_real_git_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            def git(*a):
                subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=tmp, check=True, capture_output=True)
            git("init", "-q")
            data = Path(tmp) / "data.json"
            data.write_text(json.dumps([{"url": "a", "title": "Old"}]))
            git("add", "."); git("commit", "-qm", "one")
            data.write_text(json.dumps([{"url": "a", "title": "Old"}, {"url": "b", "title": "Fresh"}]))
            git("add", "."); git("commit", "-qm", "two")
            out = subprocess.run(["python3", str(SCRIPT), "data.json"], cwd=tmp, capture_output=True, text=True, check=True).stdout
            self.assertIn("1 new", out)
            self.assertIn("- Fresh", out)


if __name__ == "__main__":
    unittest.main()
