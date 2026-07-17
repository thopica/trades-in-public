"""
Vercel Flask app for the Public Trades Tracker.

On Vercel a Flask app is deployed as a single function that receives *all*
requests, so this module serves both the static frontend (index.html, css, js)
and the JSON API.

The trades endpoint reads directly from SEC EDGAR (the authoritative source for
US insider trades) instead of a third-party scraper: it pulls the "latest
filings" feed for Form 4 and parses each filing's ownership XML. SEC EDGAR is
served from a public CDN that does not IP-block well-behaved clients, so this
works reliably from serverless hosts like Vercel.
"""
import concurrent.futures
import os
import re
import time
import xml.etree.ElementTree as ET

from flask import Flask, jsonify, send_from_directory
import requests

app = Flask(__name__)

# The static frontend lives one level up from this api/ file. Vercel bundles
# these files with the function, so serving them from here works in production
# and in local dev alike.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# SEC asks clients to send a descriptive User-Agent with contact info and to
# stay under 10 requests/second. Override the contact via the SEC_CONTACT env
# var if you want your own address in the header.
SEC_CONTACT = os.environ.get("SEC_CONTACT", "Public Trades Tracker (trades-tracker@example.com)")
REQUEST_HEADERS = {"User-Agent": SEC_CONTACT, "Accept-Encoding": "gzip, deflate"}

FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=4&company=&dateb=&owner=include&count=200&output=atom"
)
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

REQUEST_TIMEOUT_SECONDS = 10
CACHE_TTL_SECONDS = 120
MAX_FILINGS = 90   # unique filings fetched/parsed per refresh
MAX_TRADES = 50    # rows returned to the client
FETCH_WORKERS = 5

# We only surface open-market purchases and sales — the transactions where an
# insider actually chooses to buy or sell with their own money. The rest of the
# Form 4 codes (option exercises, grants, tax withholding, gifts, etc.) are
# compensation mechanics that aren't useful trading signal, so we skip them.
TRANSACTION_LABELS = {
    "P": "P - Purchase",
    "S": "S - Sale",
}

_cache = {"trades": None, "fetched_at": 0}


def classify_trade(trade_type: str) -> str:
    normalized = trade_type.strip().upper()
    if normalized.startswith("P"):
        return "buy"
    if normalized.startswith("S"):
        return "sell"
    return "neutral"


def _format_qty(shares: str) -> str:
    try:
        return f"{int(round(float(shares))):,}"
    except (TypeError, ValueError):
        return shares or ""


def _format_price(price: str) -> str:
    try:
        return f"${float(price):,.2f}"
    except (TypeError, ValueError):
        return price or ""


def _format_value(shares: str, price: str) -> str:
    try:
        return f"${float(shares) * float(price):,.0f}"
    except (TypeError, ValueError):
        return ""


def _node_value(element, path):
    """Return the text of an element, unwrapping the SEC <value> wrapper."""
    found = element.find(path)
    if found is None:
        return ""
    wrapped = found.find("value")
    node = wrapped if wrapped is not None else found
    return (node.text or "").strip() if node.text else ""


def _fetch_feed_filings():
    """Return unique (accession, submission_txt_url) pairs, newest first."""
    response = requests.get(FEED_URL, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    feed = ET.fromstring(response.content)

    filings = []
    seen = set()
    for entry in feed.findall("a:entry", ATOM_NS):
        link = entry.find("a:link", ATOM_NS)
        href = link.get("href") if link is not None else ""
        if not href or "-index.htm" not in href:
            continue
        # The same filing is listed once per reporting owner (each under a
        # different CIK), so dedupe by accession number to avoid fetching and
        # parsing the same Form 4 several times.
        accession = href.rsplit("/", 1)[-1].replace("-index.htm", "")
        if accession in seen:
            continue
        seen.add(accession)
        # The full submission text file sits next to the index page and holds
        # the ownership XML inline, so we avoid a second directory lookup.
        filings.append(href.replace("-index.htm", ".txt"))
        if len(filings) >= MAX_FILINGS:
            break
    return filings


def _parse_filing(raw_submission: str):
    """Parse one Form 4 submission into a list of normalized trade rows."""
    match = re.search(r"<ownershipDocument>.*?</ownershipDocument>", raw_submission, re.S)
    if not match:
        return []
    try:
        root = ET.fromstring(match.group(0))
    except ET.ParseError:
        return []

    issuer = root.find("issuer")
    if issuer is None:
        return []
    company = _node_value(issuer, "issuerName")
    ticker = _node_value(issuer, "issuerTradingSymbol")
    if not ticker:
        return []

    owner = root.find("reportingOwner")
    insider = _node_value(owner, "reportingOwnerId/rptOwnerName") if owner is not None else ""
    titles = []
    relationship = owner.find("reportingOwnerRelationship") if owner is not None else None
    if relationship is not None:
        if _node_value(relationship, "isDirector") in ("1", "true"):
            titles.append("Dir")
        if _node_value(relationship, "isOfficer") in ("1", "true"):
            titles.append(_node_value(relationship, "officerTitle") or "Officer")
        if _node_value(relationship, "isTenPercentOwner") in ("1", "true"):
            titles.append("10% Owner")
    title = ", ".join(t for t in titles if t)

    filed_date = _node_value(root, "periodOfReport")

    table = root.find("nonDerivativeTable")
    if table is None:
        return []

    rows = []
    for transaction in table.findall("nonDerivativeTransaction"):
        code = _node_value(transaction, "transactionCoding/transactionCode").upper()
        # Keep only open-market purchases (P) and sales (S); skip the rest.
        if code not in TRANSACTION_LABELS:
            continue
        shares = _node_value(transaction, "transactionAmounts/transactionShares")
        price = _node_value(transaction, "transactionAmounts/transactionPricePerShare")
        trade_date = _node_value(transaction, "transactionDate") or filed_date
        trade_label = TRANSACTION_LABELS[code]
        rows.append({
            "filingDate": trade_date,
            "tradeDate": trade_date,
            "ticker": ticker,
            "company": company,
            "insider": insider,
            "title": title,
            "tradeType": trade_label,
            "typeClass": classify_trade(trade_label),
            "price": _format_price(price),
            "qty": _format_qty(shares),
            "value": _format_value(shares, price),
        })
    return rows


def scrape_trades():
    filings = _fetch_feed_filings()

    def load(txt_url):
        try:
            resp = requests.get(txt_url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
            resp.raise_for_status()
            return txt_url, _parse_filing(resp.text)
        except Exception:
            return txt_url, []

    parsed_by_url = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        for txt_url, rows in pool.map(load, filings):
            parsed_by_url[txt_url] = rows

    # Preserve the feed's newest-first ordering.
    trades = []
    for txt_url in filings:
        trades.extend(parsed_by_url.get(txt_url, []))
        if len(trades) >= MAX_TRADES:
            break

    if not trades:
        raise ValueError("No Form 4 transactions could be parsed from the SEC feed")
    return trades[:MAX_TRADES]


# Match any path under /api/ (rather than only /api/trades) so the endpoint
# keeps working regardless of how the request path is presented to the app,
# and so requests like /api/index.py never fall through to the static handler.
@app.route("/api/", defaults={"path": ""})
@app.route("/api/<path:path>")
def get_trades(path=""):
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


@app.route("/")
def serve_index():
    return send_from_directory(PROJECT_ROOT, "index.html")


@app.route("/favicon.ico")
def favicon():
    # No favicon asset; return 204 so browsers stop logging a 404 in the console.
    return ("", 204)


@app.route("/css/<path:filename>")
def serve_css(filename):
    return send_from_directory(os.path.join(PROJECT_ROOT, "css"), filename)


@app.route("/js/<path:filename>")
def serve_js(filename):
    return send_from_directory(os.path.join(PROJECT_ROOT, "js"), filename)


if __name__ == "__main__":
    print("Starting Public Trades Tracker (local dev) at http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
