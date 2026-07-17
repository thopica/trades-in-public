# Public Trades Tracker

Fetches and displays publicly disclosed US stock trades from two independent
disclosure systems, in one merged feed that labels each trade by source:

- **🏢 Insider trades** — corporate officers, directors and 10%+ owners filing
  **SEC Form 4**. Read directly from the official
  [SEC EDGAR](https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&owner=include&count=40&output=atom)
  "latest filings" feed and parsed server-side — no third-party scraper, so it
  keeps working from serverless hosts that other sites tend to block. Only
  open-market purchases (P) and sales (S) are shown.
- **🏛️ Congressional trades** — US House & Senate members filing **STOCK Act**
  reports. Read from [Financial Modeling Prep](https://financialmodelingprep.com/),
  which aggregates the official House and Senate disclosures into clean JSON.

## Project structure

```
api/index.py    Flask app: serves the frontend + GET /api/trades (merged feed)
index.html      Frontend markup
css/style.css   Custom styles (Tailwind via CDN handles the rest)
js/app.js       Fetch + render + client-side source/direction filters
requirements.txt
vercel.json     Function config (the Flask app owns all routing on Vercel)
```

## Configuration

Set these as environment variables (locally, or in the Vercel project settings):

| Variable | Required | Purpose |
| --- | --- | --- |
| `FMP_API_KEY` | For congressional trades | Free API key from [financialmodelingprep.com](https://site.financialmodelingprep.com/developer/docs). Without it the app still runs and shows insider trades only. |
| `SEC_CONTACT` | Optional | Descriptive `User-Agent` the SEC asks clients to send, e.g. `"Your Name your@email.com"`. A sensible default is used otherwise. |

### Getting a free FMP API key

1. Create a free account at
   [site.financialmodelingprep.com](https://site.financialmodelingprep.com/register).
2. Copy your API key from the dashboard.
3. Add it to Vercel: **Project → Settings → Environment Variables →**
   `FMP_API_KEY = <your key>`, then redeploy.

## Local development

```
pip install -r requirements.txt
export FMP_API_KEY=your_key_here   # optional; omit for insider-only
python api/index.py
```

Then open http://127.0.0.1:5000

## Deploying to Vercel

```
vercel
```

Add `FMP_API_KEY` in the project's environment variables to enable the
congressional feed.

## Disclaimer

Data is for informational and educational purposes only, not investment advice.
Congressional filings disclose dollar **ranges**, not exact amounts. Verify
against official SEC EDGAR and House/Senate filings before making decisions.
