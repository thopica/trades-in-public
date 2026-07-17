#!/usr/bin/env python3
"""
Collect recent US congressional stock trades from the official government
disclosure systems and write them to data/congress_trades.json.

This runs on a schedule in CI (see .github/workflows/congress.yml), NOT inside
the web app — the parsing is too slow and rate-limited to do on every request.
The web app just reads the JSON this produces.

Two sources, both free and official:

  * House  — disclosures-clerk.house.gov publishes an annual ZIP indexing every
             filing; Periodic Transaction Reports (type "P") are individual
             PDFs whose text we parse. Electronic (e-filed) PDFs are text-based;
             the occasional scanned/paper filing is skipped.
  * Senate — efdsearch.senate.gov requires accepting terms (a session + CSRF
             token), then exposes a JSON report list; each electronic report is
             an HTML page with a transactions table we parse. Paper filings
             (PDF links) are skipped.

The script is defensive: each chamber is fetched independently, network calls
retry with backoff, and if a chamber yields nothing (e.g. transient rate
limiting) its previously-saved trades are kept rather than overwritten.
"""
import datetime as dt
import html as htmllib
import io
import json
import os
import re
import sys
import time
import zipfile

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
BASE_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 30
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "congress_trades.json")

# How many recent filings/reports to parse per run, and how many trades to keep.
HOUSE_MAX_FILINGS = 60
SENATE_MAX_REPORTS = 60
MAX_STORED = 300


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
def classify(trade_type):
    t = (trade_type or "").strip().lower()
    if t.startswith("p") or "purchase" in t:
        return "buy"
    if t.startswith("s") or "sale" in t or "sold" in t:
        return "sell"
    return "neutral"


def iso_date(mmddyyyy):
    """Convert 'M/D/YYYY' to 'YYYY-MM-DD'; pass through anything else."""
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", mmddyyyy or "")
    if not m:
        return (mmddyyyy or "").strip()
    month, day, year = m.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def collapse(text):
    return re.sub(r"\s+", " ", (text or "").replace("\x00", "")).strip()


def get_with_retry(session, method, url, *, tries=4, backoff=3, **kwargs):
    """HTTP with retry/backoff for the flaky, rate-limited government hosts."""
    last = None
    for attempt in range(tries):
        try:
            resp = session.request(method, url, timeout=TIMEOUT, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {resp.status_code}"
            else:
                return resp
        except requests.RequestException as exc:
            last = str(exc)
        time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"request failed after {tries} tries ({last}): {url}")


# --------------------------------------------------------------------------
# House of Representatives
# --------------------------------------------------------------------------
HOUSE_TX_RE = re.compile(
    r"\(([A-Z][A-Z0-9.\-]{0,6})\)\s*"        # ticker
    r"\[([A-Z]{1,3})\]\s*"                    # asset type code (ST = stock)
    r"([PSE])(\s*\((?:partial|full)\))?\s*"   # transaction type: P / S / E (+ partial/full)
    r"(\d{1,2}/\d{1,2}/\d{4})\s*"             # transaction date
    r"\d{1,2}/\d{1,2}/\d{4}\s*"               # notification date (ignored)
    r"(\$[\d,]+\s*-\s*\$[\d,]+)",              # amount range
    re.S,
)


def house_filing_index(session, year):
    url = f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
    resp = get_with_retry(session, "GET", url)
    resp.raise_for_status()
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    txt_name = next(n for n in archive.namelist() if n.endswith(".txt"))
    lines = archive.read(txt_name).decode("latin-1").splitlines()
    filings = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < 9 or parts[4] != "P":  # keep Periodic Transaction Reports
            continue
        prefix, last, first, suffix, _ftype, state_dst, yr, filed, doc_id = parts[:9]
        if not doc_id.strip():
            continue
        filings.append({
            "name": collapse(f"{first} {last} {suffix}"),
            "state": state_dst.strip(),
            "filed": filed.strip(),
            "doc_id": doc_id.strip(),
            "year": year,
        })
    # Newest first by filing date.
    filings.sort(key=lambda f: iso_date(f["filed"]), reverse=True)
    return filings


def parse_house_pdf(pdf_bytes):
    from pdfminer.high_level import extract_text
    text = extract_text(io.BytesIO(pdf_bytes))
    trades, seen = [], set()
    for match in HOUSE_TX_RE.finditer(text):
        ticker, code, type_base, type_qual, tdate, amount = match.groups()
        if code != "ST":  # stocks only
            continue
        # Normalize to the same labels the Senate table uses.
        qual = (type_qual or "").strip().strip("()").capitalize()
        base = {"P": "Purchase", "S": "Sale", "E": "Exchange"}.get(type_base, type_base)
        ttype = f"{base} ({qual})" if qual else base
        amount = collapse(amount)
        # House PDFs carry a duplicate text layer; collapse identical hits.
        key = (ticker, ttype, tdate, amount)
        if key in seen:
            continue
        seen.add(key)
        trades.append({"ticker": ticker, "type": ttype, "date": tdate, "amount": amount})
    return trades


def fetch_house(session):
    year = dt.date.today().year
    filings = house_filing_index(session, year)
    # Early in a new year, also reach back into last year's filings.
    if len(filings) < HOUSE_MAX_FILINGS:
        try:
            filings += house_filing_index(session, year - 1)
        except Exception:
            pass

    rows = []
    for filing in filings[:HOUSE_MAX_FILINGS]:
        url = (f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/"
               f"{filing['year']}/{filing['doc_id']}.pdf")
        try:
            resp = get_with_retry(session, "GET", url)
            if resp.status_code != 200 or not resp.content:
                continue
            transactions = parse_house_pdf(resp.content)
        except Exception:
            continue  # scanned/unparseable filing — skip
        for tx in transactions:
            rows.append({
                "source": "congress",
                "chamber": "House",
                "date": iso_date(tx["date"]),
                "ticker": tx["ticker"],
                "company": "",
                "person": filing["name"],
                "role": "House" + (f" · {filing['state']}" if filing["state"] else ""),
                "tradeType": tx["type"],
                "typeClass": classify(tx["type"]),
                "price": "",
                "qty": "",
                "value": tx["amount"],
            })
        time.sleep(0.2)
    return rows


# --------------------------------------------------------------------------
# Senate
# --------------------------------------------------------------------------
SENATE_BASE = "https://efdsearch.senate.gov"


def senate_session():
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    home = get_with_retry(session, "GET", SENATE_BASE + "/search/home/")
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', home.text)
    if not token:
        raise RuntimeError("could not read Senate CSRF token")
    time.sleep(1)
    get_with_retry(session, "POST", SENATE_BASE + "/search/home/",
                   headers={"Referer": SENATE_BASE + "/search/home/"},
                   data={"prohibition_agreement": "1", "csrfmiddlewaretoken": token.group(1)})
    time.sleep(1)
    return session


def senate_report_list(session, start_date):
    csrf = session.cookies.get("csrftoken")
    resp = get_with_retry(
        session, "POST", SENATE_BASE + "/search/report/data/",
        headers={"Referer": SENATE_BASE + "/search/",
                 "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": csrf},
        data={"draw": "1", "start": "0", "length": str(SENATE_MAX_REPORTS),
              "report_types": "[11]", "filer_types": "[]",
              "submitted_start_date": start_date, "submitted_end_date": "",
              "candidate_state": "", "senator_state": "", "office_id": "",
              "first_name": "", "last_name": "", "csrfmiddlewaretoken": csrf})
    if "json" not in (resp.headers.get("content-type") or ""):
        raise RuntimeError(f"Senate report list not JSON (HTTP {resp.status_code})")
    return resp.json().get("data", [])


def _strip_tags(value):
    return htmllib.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def parse_senate_report(html_text, person, state):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S):
        cells = [_strip_tags(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        # #, Transaction Date, Owner, Ticker, Asset Name, Asset Type, Type, Amount, Comment
        if len(cells) < 8 or not re.match(r"^\d+$", cells[0]):
            continue
        ticker, asset_type, ttype, amount = cells[3], cells[5], cells[6], cells[7]
        if "stock" not in asset_type.lower():
            continue
        if not ticker or ticker in ("--", "N/A"):
            continue
        owner = cells[2]
        role = "Senate" + (f" · {state}" if state else "")
        if owner and owner.lower() not in ("--", "self", ""):
            role += f" ({owner})"
        rows.append({
            "source": "congress",
            "chamber": "Senate",
            "date": iso_date(cells[1]),
            "ticker": ticker,
            "company": collapse(cells[4]),
            "person": person,
            "role": role,
            "tradeType": ttype,
            "typeClass": classify(ttype),
            "price": "",
            "qty": "",
            "value": amount,
        })
    return rows


def fetch_senate(session, start_date):
    reports = senate_report_list(session, start_date)
    rows = []
    for report in reports:
        # report = [first, last, "Name (Senator)", "<a href=...>PTR ...</a>", date]
        person = collapse(f"{report[0]} {report[1]}")
        state_match = re.search(r"\(([A-Z]{2})\)", report[2] or "")
        state = state_match.group(1) if state_match else ""
        link = re.search(r'href="([^"]+)"', report[3] or "")
        if not link:
            continue
        href = link.group(1)
        if "/view/paper/" in href:  # paper filing — skip (electronic only)
            continue
        try:
            resp = get_with_retry(session, "GET", SENATE_BASE + href)
            if "/view/paper/" in resp.url or resp.url.lower().endswith(".pdf"):
                continue
            rows += parse_senate_report(resp.text, person, state)
        except Exception:
            continue
        time.sleep(0.5)
    return rows


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def load_existing():
    try:
        with open(OUTPUT_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"generated_at": None, "trades": []}


def dedupe(trades):
    seen, out = set(), []
    for t in trades:
        key = (t.get("chamber"), t.get("person"), t.get("ticker"),
               t.get("date"), t.get("tradeType"), t.get("value"))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def main():
    existing = load_existing()
    prior = existing.get("trades", [])
    prior_house = [t for t in prior if t.get("chamber") == "House"]
    prior_senate = [t for t in prior if t.get("chamber") == "Senate"]

    # Look back ~120 days so we always have a healthy recent window.
    lookback = (dt.date.today() - dt.timedelta(days=120)).strftime("%m/%d/%Y") + " 00:00:00"

    session = requests.Session()
    session.headers.update(BASE_HEADERS)

    # House
    try:
        house = fetch_house(session)
        print(f"House: parsed {len(house)} trades", file=sys.stderr)
    except Exception as exc:
        house = []
        print(f"House: FAILED ({exc})", file=sys.stderr)
    if not house:
        house = prior_house  # keep last-known rather than blanking the chamber

    # Senate
    try:
        ssession = senate_session()
        senate = fetch_senate(ssession, lookback)
        print(f"Senate: parsed {len(senate)} trades", file=sys.stderr)
    except Exception as exc:
        senate = []
        print(f"Senate: FAILED ({exc})", file=sys.stderr)
    if not senate:
        senate = prior_senate

    combined = dedupe(house + senate)
    combined.sort(key=lambda t: t.get("date", ""), reverse=True)
    combined = combined[:MAX_STORED]

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "counts": {
            "house": sum(1 for t in combined if t["chamber"] == "House"),
            "senate": sum(1 for t in combined if t["chamber"] == "Senate"),
        },
        "trades": combined,
    }
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {len(combined)} trades "
          f"(House {payload['counts']['house']}, Senate {payload['counts']['senate']}) "
          f"to {os.path.relpath(OUTPUT_PATH)}", file=sys.stderr)


if __name__ == "__main__":
    main()
