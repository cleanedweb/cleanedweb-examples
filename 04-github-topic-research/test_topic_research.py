import json
import unittest
from pathlib import Path

from topic_research import count, languages, markdown, md_link, rank, related_topics

SAMPLE = json.loads((Path(__file__).parent / "sample" / "records.json").read_text())


class TopicResearchTests(unittest.TestCase):
    def test_count(self):
        self.assertEqual(count(12), 12)
        self.assertEqual(count("1,200"), 1200)
        self.assertIsNone(count(None))
        self.assertIsNone(count("1.2k"))
        self.assertIsNone(count(True))

    def test_rank_orders_by_stars_then_forks_and_puts_unknown_last(self):
        rows = rank(SAMPLE)
        self.assertEqual([r["name"] for r in rows], ["crawlr", "scrapekit", "tiny", "no-counts"])
        self.assertEqual([r["rank"] for r in rows], [1, 2, 3, 4])
        self.assertIsNone(rows[-1]["stars"])  # unknown, not zero

    def test_duplicates_by_url_are_dropped(self):
        self.assertEqual(len(rank(SAMPLE)), 4)

    def test_related_topics_and_languages(self):
        rows = rank(SAMPLE)
        topics = dict(related_topics(rows, "web-scraping"))
        self.assertEqual(topics["python"], 2)
        self.assertEqual(topics["crawler"], 2)
        self.assertNotIn("web-scraping", topics)
        self.assertEqual(dict(languages(rows)), {"TypeScript": 1, "Python": 2})

    def test_links_only_for_http_urls(self):
        self.assertEqual(md_link("a", "javascript:alert(1)"), "a")
        self.assertEqual(md_link("a", "https://x.example/a(b)"), "[a](https://x.example/a%28b%29)")

    def test_markdown_escapes_website_text(self):
        text = markdown("web-scraping", rank(SAMPLE))
        self.assertIn("A \\| tricky &lt;b&gt;description&lt;/b&gt;", text)
        self.assertIn("unknown", text)


if __name__ == "__main__":
    unittest.main()
