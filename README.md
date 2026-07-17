# Public Trades Tracker

Fetches and displays publicly disclosed US stock trades from two independent
disclosure systems, in one merged feed that labels each trade by source:

- **🏢 Insider trades** — corporate officers, directors and 10%+ owners filing
  **SEC Form 4**. Read live from the official
  [SEC EDGAR](https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&owner=include&count=40&output=atom)
  "latest filings" feed and parsed on each request. Only open-market purchases
  (P) and sales (S) are shown.
- **🏛️ Congressional trades** — US House & Senate members filing **STOCK Act**
  reports. Collected from the official government disclosure systems
  ([House](https://disclosures-clerk.house.gov/) PTR filings and the
  [Senate EFD](https://efdsearch.senate.gov/search/)) by a scheduled job and
  served from a committed data file. No API keys, no paid services.

## Why congressional data is collected out-of-band

The House publishes transactions as PDFs and the Senate behind a session-gated
search portal — both too slow and rate-limited to scrape on every page load. So
a scheduled **GitHub Action** runs `scripts/fetch_congress.py`, which parses the
official filings into `data/congress_trades.json` and commits it. The web app
just reads that file, so pages stay fast and the feed refreshes daily. Only
electronic (machine-readable) filings are parsed; the occasional scanned/paper
filing is skipped.

## Project structure

```
api/index.py               Flask app: serves the frontend + GET /api/trades
index.html                 Frontend markup
css/style.css              Custom styles (Tailwind via CDN handles the rest)
js/app.js                  Fetch + render + client-side source/direction filters
requirements.txt           Web app deps (Flask + requests)
data/congress_trades.json  Pre-collected congressional trades (committed)
scripts/fetch_congress.py  House + Senate collector (run in CI)
scripts/requirements.txt   Collector deps (requests + pdfminer.six)
.github/workflows/congress.yml   Daily job that refreshes the data file
vercel.json                Function config (the Flask app owns all routing)
```

## Configuration

No API keys are required. One optional environment variable:

| Variable | Purpose |
| --- | --- |
| `SEC_CONTACT` | Descriptive `User-Agent` the SEC asks clients to send, e.g. `"Your Name your@email.com"`. A sensible default is used otherwise. |

## Local development

```
pip install -r requirements.txt
python api/index.py
```

Then open http://127.0.0.1:5000. Congressional trades come from the committed
`data/congress_trades.json`. To refresh it locally:

```
pip install -r scripts/requirements.txt
python scripts/fetch_congress.py
```

## Deploying to Vercel

```
vercel
```

The daily GitHub Action commits fresh congressional data to the repo, which
triggers a redeploy so the app always serves recent trades.

## Disclaimer

Data is for informational and educational purposes only, not investment advice.
Congressional filings disclose dollar **ranges**, not exact amounts, and are
reported with a delay. Verify against official SEC EDGAR and House/Senate
filings before making decisions.
