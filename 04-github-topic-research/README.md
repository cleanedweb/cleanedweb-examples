# 04 - Research: GitHub topic repositories to a ranked list

Rank the public repositories listed under a GitHub topic by stars, and see which languages and related topics go with them. Source: the "GitHub Topics Repositories" catalog API (github.com/topics/<topic>).

> The official `cleanedweb` SDKs for Python and JavaScript are coming. This example uses plain HTTP (`httpx`) so it does not depend on them; `cw_http.py` is the small client it uses.

## Try it without a key

```bash
pip install -r requirements.txt
python topic_research.py --sample         # synthetic records, no API run, no charge
cat out/web-scraping-ranking.md
```

## Run it for real

```bash
export CLEANEDWEB_API_KEY=...
python topic_research.py --topic web-scraping --language Python --max-items 50
python topic_research.py --topic machine-learning --max-items 100 --top 25
```

Inputs sent to the API: `topics` (the topic), `programming_language` (optional) and `sort` (the topic page's own order, default `desc_stars`). The contract's `topics` input lists example topics; read it at `https://cleanedweb.com/catalog/github-topics-repositories-api/contract.json`.

Cost: charged per record delivered (5,000 free once, then prepaid from $1 per 1,000); `--max-items` caps it (default 50).

Output in `out/` (gitignored): `<topic>-ranking.md` (a Markdown table with stars, forks, language, description, plus related topics) and `<topic>-ranking.csv`.

## Notes on the data

- **Stars and forks come from each repository's own page**, so only enriched records carry them (`enrich_records` defaults to `true`). Records without a count are ranked last and shown as "unknown", never as 0.
- The contract returns counts as text (`stargazer_count`: `"12"`) and as integers (`typed_stargazer_count`); the example prefers the integers.
- The ranking is over the records you read. With `--max-items 50` it is the top of the topic's own order, not every repository in the topic.
- Descriptions are website text: pipes, HTML and line breaks are escaped in the Markdown, and only `http(s)` URLs become links.

## Files

`topic_research.py`, `test_topic_research.py` (`python test_topic_research.py`), `cw_http.py` (copied from `../shared/`), `sample/` (synthetic records). Run protocol: [run a catalog API](https://cleanedweb.com/docs/run-catalog-api/?utm_source=github&utm_medium=cleanedweb-examples).
