"""IDX eligibility whitelist for the What-to-Buy valuator.

A ticker qualifies for the DCF methodology only when it is a non-financial
(bank) IDX stock listed for more than MIN_AGE_YEARS years. screen.py builds
data/eligible_tickers.json from Yahoo sector/industry + first trade date so
dcf.py can skip ineligible tickers with a fast local file read.

Pure functions here are side-effect free for offline unit testing.
"""

import json
import os
import time

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
    if years < MIN_AGE_YEARS:
        return False, "listed {:.1f} years (< {})".format(years, MIN_AGE_YEARS)
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
