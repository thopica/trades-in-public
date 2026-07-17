"""
Vercel Python serverless function exposing GET /api/trades.

Scrapes OpenInsider's latest-insider-trading page server-side (avoids
browser CORS restrictions entirely) and returns normalized JSON.
"""
import time
from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

SOURCE_URL = "https://openinsider.com/latest-insider-trading"
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PublicTradesTracker/1.0)"}
REQUEST_TIMEOUT_SECONDS = 10
CACHE_TTL_SECONDS = 60
MAX_TRADES = 50

# Maps normalized header text -> field name. Matched against the table's own
# <th> labels instead of hardcoded column indices, so parsing survives minor
# markup/column-order changes on the source site.
HEADER_FIELD_MAP = {
    "filing date": "filing_date",
    "trade date": "trade_date",
    "ticker": "ticker",
    "company name": "company",
    "insider name": "insider",
    "title": "title",
    "trade type": "trade_type",
    "price": "price",
    "qty": "qty",
    "value": "value",
}

_cache = {"trades": None, "fetched_at": 0}


def classify_trade(trade_type: str) -> str:
    normalized = trade_type.strip().upper()
    if normalized.startswith("P"):
        return "buy"
    if normalized.startswith("S"):
        return "sell"
    return "neutral"


def scrape_trades():
    response = requests.get(SOURCE_URL, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    table = soup.select_one("table.tinytable") or soup.select_one("table")
    if table is None:
        raise ValueError("Could not locate trades table in source page")

    header_cells = table.select("thead th") or table.select("tr:first-child th")
    column_fields = []
    for cell in header_cells:
        label = cell.get_text(strip=True).lower()
        column_fields.append(HEADER_FIELD_MAP.get(label))

    if not any(column_fields):
        raise ValueError("Could not map any known columns from source table headers")

    trades = []
    body_rows = table.select("tbody tr") or table.select("tr")[1:]

    for row in body_rows:
        cells = row.find_all("td")
        if len(cells) != len(column_fields):
            continue

        record = {}
        ticker_link = None
        for field, cell in zip(column_fields, cells):
            if field is None:
                continue
            if field == "ticker":
                ticker_link = cell.find("a")
            record[field] = cell.get_text(strip=True)

        if not record.get("ticker") or not record.get("insider"):
            continue

        trade_type = record.get("trade_type", "")
        trades.append({
            "filingDate": record.get("filing_date", ""),
            "tradeDate": record.get("trade_date", ""),
            "ticker": record["ticker"],
            "company": record.get("company", ""),
            "insider": record["insider"],
            "title": record.get("title", ""),
            "tradeType": trade_type,
            "typeClass": classify_trade(trade_type),
            "price": record.get("price", ""),
            "qty": record.get("qty", ""),
            "value": record.get("value", ""),
        })

        if len(trades) >= MAX_TRADES:
            break

    return trades


@app.route("/api/trades")
def get_trades():
    now = time.time()
    if _cache["trades"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL_SECONDS:
        return jsonify({"trades": _cache["trades"], "cached": True})

    try:
        trades = scrape_trades()
    except Exception as exc:
        # Serve stale cache rather than a hard failure if we have one.
        if _cache["trades"] is not None:
            return jsonify({"trades": _cache["trades"], "cached": True, "warning": str(exc)})
        return jsonify({"error": str(exc)}), 502

    _cache["trades"] = trades
    _cache["fetched_at"] = now
    return jsonify({"trades": trades, "cached": False})


if __name__ == "__main__":
    # Local-only static file serving so `python api/index.py` mirrors how
    # Vercel serves the frontend in production. Vercel imports `app` directly
    # and never executes this block.
    import os
    from flask import send_from_directory

    PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")

    @app.route("/")
    def _serve_index():
        return send_from_directory(PROJECT_ROOT, "index.html")

    @app.route("/<path:filename>")
    def _serve_static(filename):
        return send_from_directory(PROJECT_ROOT, filename)

    print("Starting Public Trades Tracker (local dev) at http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
