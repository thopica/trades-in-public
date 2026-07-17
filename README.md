# Public Trades Tracker

Fetches and displays publicly disclosed US insider stock trades, read directly
from the official [SEC EDGAR](https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&owner=include&count=40&output=atom)
"latest filings" feed for Form 4. Each filing's ownership XML is parsed
server-side into normalized JSON — no third-party scraper, so it keeps working
from serverless hosts that other sites tend to block.

## Project structure

```
api/index.py    Flask app: serves the frontend + GET /api/trades (SEC EDGAR)
index.html      Frontend markup
css/style.css   Custom styles (Tailwind via CDN handles the rest)
js/app.js       Fetch + render logic
requirements.txt
vercel.json     Function config (the Flask app owns all routing on Vercel)
```

## Configuration

The SEC asks API clients to send a descriptive `User-Agent` with contact
details. A sensible default is used, but you can override it by setting the
`SEC_CONTACT` environment variable (e.g. `"Your Name your@email.com"`).

## Local development

```
pip install -r requirements.txt
python api/index.py
```

Then open http://127.0.0.1:5000

## Deploying to Vercel

```
vercel
```

No environment variables or API keys are required.

## Disclaimer

Data is for informational and educational purposes only, not investment advice.
Verify against official SEC EDGAR filings before making decisions.
