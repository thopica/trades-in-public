# Public Trades Tracker

Fetches and displays publicly disclosed US insider stock trades (SEC Form 4),
scraped from [OpenInsider](https://openinsider.com/latest-insider-trading).

## Project structure

```
api/index.py    Flask serverless function -> GET /api/trades
index.html      Frontend markup
css/style.css   Custom styles (Tailwind via CDN handles the rest)
js/app.js       Fetch + render logic
requirements.txt
vercel.json     Routes /api/* to the Python function; everything else is static
```

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
