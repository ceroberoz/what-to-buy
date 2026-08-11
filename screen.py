"""IDX eligibility whitelist for the What-to-Buy valuator.

A ticker qualifies for the DCF methodology only when it is a non-financial
(bank) IDX stock listed for more than MIN_AGE_YEARS years. screen.py builds
data/eligible_tickers.json from Yahoo sector/industry + first trade date so
dcf.py can skip ineligible tickers with a fast local file read.

Pure functions here are side-effect free for offline unit testing.
"""

import argparse
import json
import os
import sys
import time

import data_source as ds

ELIGIBLE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "eligible_tickers.json")

MIN_AGE_YEARS = 5
DAYS_PER_YEAR = 365.25
EXCLUDED_SECTORS = ("financial services",)
EXCLUDED_INDUSTRY_WORDS = ("bank",)


def _ts_to_date(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def age_years(first_trade_ts, now_ts):
    """Years (float) between the first trade date and now."""
    return (now_ts - first_trade_ts) / (DAYS_PER_YEAR * 86400)


def eligibility(sector, industry, first_trade_ts, now_ts):
    """(eligible: bool, reason: str) for a single ticker.

    Excluded when the sector is financial (banks/insurers/brokers) or the
    industry names a bank, or when the stock was listed < MIN_AGE_YEARS ago.
    """
    sector_norm = (sector or "").strip().lower()
    if sector_norm in EXCLUDED_SECTORS:
        return False, "financial sector: {}".format(sector)
    industry_norm = (industry or "").strip().lower()
    if any(word in industry_norm for word in EXCLUDED_INDUSTRY_WORDS):
        return False, "bank industry: {}".format(industry)
    years = age_years(first_trade_ts, now_ts)
    if years <= MIN_AGE_YEARS:
        return False, "listed {:.1f} years (needs > {})".format(years, MIN_AGE_YEARS)
    return True, ""


def _entry_from_fetch(ticker, sector, industry, first_trade_ts, now_ts):
    """Full meta entry for a fetched ticker (eligible or not)."""
    listed = _ts_to_date(first_trade_ts)
    years = age_years(first_trade_ts, now_ts)
    ok, reason = eligibility(sector, industry, first_trade_ts, now_ts)
    return {
        "sector": sector,
        "industry": industry,
        "listed": listed,
        "age_years": round(years, 1),
        "status": "eligible" if ok else "excluded",
        "reason": reason,
    }


def load_eligible(path=ELIGIBLE_FILE):
    """Whitelist doc {updated, tickers, meta} or None when absent/corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("tickers"), list):
        return None
    return doc


def save_eligible(entries, path=ELIGIBLE_FILE):
    """Write the whitelist doc, sorted by ticker, from a ticker -> entry map."""
    tickers = sorted(ticker for ticker, entry in entries.items()
                     if entry.get("status") == "eligible")
    doc = {
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tickers": tickers,
        "meta": {ticker: entries[ticker] for ticker in sorted(entries)},
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


# --- Fetching (network, via data_source) ------------------------------------

def fetch_eligibility(ticker, use_cache=True):
    """(sector, industry, first_trade_ts) for an IDX ticker via Yahoo.

    sector/industry come from the summaryProfile module; the first trade date
    comes from the chart API with a max range. Raises DataSourceError on failure.
    """
    raw = ds.yahoo_fundamentals(ticker, modules=("summaryProfile",), use_cache=use_cache)
    profile = raw["summaryProfile"]
    chart = ds.yahoo_chart(ticker, "max", "1mo", use_cache, suffix=True)
    first_trade = chart["chart"]["result"][0]["meta"].get("firstTradeDate")
    if first_trade is None:
        raise ds.DataSourceError("no firstTradeDate for {}".format(ticker))
    return profile.get("sector"), profile.get("industry"), int(first_trade)


def discovered_tickers():
    """IDX tickers hinted at by local data: templates and Yahoo cache keys."""
    tickers = set()
    data_dir = os.path.dirname(ELIGIBLE_FILE)
    for name in os.listdir(data_dir):
        if name.endswith(".json") and name not in ("sample.json", os.path.basename(ELIGIBLE_FILE)):
            tickers.add(name[:-len(".json")].upper())
    cache_dir = os.path.join(data_dir, "cache")
    for name in os.listdir(cache_dir):
        parts = name.split("_")
        if len(parts) >= 2 and parts[0] in ("fund", "chart") and parts[1].isalnum():
            tickers.add(parts[1].upper())
    return sorted(tickers)


def scan(tickers, use_cache=True):
    """Fetch eligibility for each ticker and return a ticker -> entry map."""
    entries = {}
    now_ts = int(time.time())
    for ticker in tickers:
        ticker = ticker.strip().upper()
        if not ticker:
            continue
        try:
            sector, industry, first_trade = fetch_eligibility(ticker, use_cache)
        except ds.DataSourceError as exc:
            entries[ticker] = {"status": "no_data", "reason": str(exc)}
            print("  {:<6} NO_DATA  {}".format(ticker, exc))
            continue
        entry = _entry_from_fetch(ticker, sector, industry, first_trade, now_ts)
        entries[ticker] = entry
        if entry["status"] == "eligible":
            print("  {:<6} ELIGIBLE {} / {} ({}y)".format(
                ticker, entry["sector"], entry["industry"], entry["age_years"]))
        else:
            print("  {:<6} EXCLUDED {}".format(ticker, entry["reason"]))
    return entries


def build_parser():
    parser = argparse.ArgumentParser(
        prog="screen.py",
        description="Build the IDX eligibility whitelist (>5y listed, non-financial).")
    parser.add_argument("tickers", nargs="*", help="IDX tickers to screen "
                        "(default: scan tickers already present under data/)")
    parser.add_argument("--list", metavar="FILE", help="file with one ticker per line")
    parser.add_argument("--no-cache", action="store_true", help="bypass the local data cache")
    parser.add_argument("--output", metavar="FILE.json", default=ELIGIBLE_FILE,
                        help="whitelist path (default {})".format(ELIGIBLE_FILE))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    tickers = list(args.tickers)
    if args.list:
        try:
            with open(args.list, "r", encoding="utf-8") as fh:
                tickers += [line.strip() for line in fh if line.strip()]
        except OSError as exc:
            print("error: cannot read {}: {}".format(args.list, exc), file=sys.stderr)
            return 1
    if not tickers:
        tickers = discovered_tickers()
    if not tickers:
        print("error: no tickers given and none found under data/", file=sys.stderr)
        return 1
    print("Screening {} ticker(s) ...".format(len(tickers)))
    entries = scan(tickers, use_cache=not args.no_cache)
    path = save_eligible(entries, args.output)
    eligible = [t for t, e in entries.items() if e.get("status") == "eligible"]
    excluded = [t for t, e in entries.items() if e.get("status") == "excluded"]
    no_data = [t for t, e in entries.items() if e.get("status") == "no_data"]
    print("\n{} eligible, {} excluded, {} no data -> {}".format(
        len(eligible), len(excluded), len(no_data), path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
