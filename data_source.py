"""Data retrieval for the What-to-Buy valuator.

Uses only the Python standard library:
- Yahoo Finance chart API for current price and historical monthly closes.
- A JSON cache under data/cache/ to avoid repeated network calls.
"""

import json
import os
import statistics
import time
import urllib.error
import urllib.request

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cache")
YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}{suffix}"
USER_AGENT = "Mozilla/5.0"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 20
DEFAULT_TTL = 86400


class DataSourceError(Exception):
    """Raised when market data cannot be fetched or parsed."""


# --- HTTP helpers -----------------------------------------------------------

def http_get_json(url):
    """GET a URL and parse the JSON response. Raises DataSourceError on any failure."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise DataSourceError("HTTP {} for {}".format(exc.code, url)) from exc
    except urllib.error.URLError as exc:
        raise DataSourceError("network error for {}: {}".format(url, exc.reason)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise DataSourceError("invalid JSON from {}: {}".format(url, exc)) from exc


# --- Cache ------------------------------------------------------------------

def _cache_path(key):
    return os.path.join(CACHE_DIR, key.replace("/", "_").replace(":", "_") + ".json")


def _cache_get(key, ttl=DEFAULT_TTL):
    path = _cache_path(key)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            entry = json.load(fh)
        if ttl is None or time.time() - entry["fetched_at"] <= ttl:
            return entry["data"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _cache_set(key, data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as fh:
            json.dump({"fetched_at": time.time(), "data": data}, fh)
    except OSError:
        pass  # cache is best-effort; never fail the tool because of it


# --- Yahoo Finance ----------------------------------------------------------

def yahoo_chart(ticker, range_, interval, use_cache=True, ttl=DEFAULT_TTL, suffix=True):
    """Fetch a Yahoo chart API result dict for an IDX ticker (appends .JK unless suffix=False)."""
    key = "chart_{}_{}_{}".format(ticker, range_, interval)
    if use_cache:
        cached = _cache_get(key, ttl)
        if cached is not None:
            return cached
    url = YAHOO_BASE.format(ticker=ticker, suffix=".JK" if suffix else "") + "?range={}&interval={}".format(range_, interval)
    payload = http_get_json(url)
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise DataSourceError("Yahoo error for {}: {}".format(ticker, chart["error"].get("description", chart["error"])))
    result = chart.get("result")
    if not result:
        raise DataSourceError("no chart data for {} (check the ticker)".format(ticker))
    if use_cache:
        _cache_set(key, payload)
    return payload


def fetch_price(ticker, use_cache=True):
    """Latest close/regular price for an IDX ticker."""
    payload = yahoo_chart(ticker, "5d", "1d", use_cache, ttl=900)
    meta = payload["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    if price is None:
        raise DataSourceError("no regularMarketPrice for {}".format(ticker))
    return float(price)


def fetch_monthly_closes(ticker, use_cache=True, ttl=DEFAULT_TTL, suffix=True):
    """List of (unix_timestamp, close) monthly points (5y) for a ticker.

    Pass suffix=False for index tickers such as ^JKSE.
    """
    payload = yahoo_chart(ticker, "5y", "1mo", use_cache, ttl=ttl, suffix=suffix)
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    closes = result["indicators"]["quote"][0].get("close", [])
    pairs = [(ts, close) for ts, close in zip(timestamps, closes) if close is not None]
    if len(pairs) < 2:
        raise DataSourceError("insufficient price history for {}".format(ticker))
    return pairs


# --- Beta estimation --------------------------------------------------------

JCI_TICKER = "^JKSE"
MIN_BETA_POINTS = 24


def _series_returns(closes):
    """Monthly returns from an ordered list of closing prices."""
    out = []
    for prev, curr in zip(closes, closes[1:]):
        if prev > 0 and curr > 0:
            out.append(curr / prev - 1)
    return out


def estimate_beta(stock_pairs, index_pairs, min_points=MIN_BETA_POINTS):
    """Beta = cov(stock, index) / var(index) over common months.

    Returns None when there is not enough overlapping history.
    """
    stock = dict(stock_pairs)
    index = dict(index_pairs)
    common = sorted(set(stock) & set(index))
    s_ret = _series_returns([stock[t] for t in common])
    m_ret = _series_returns([index[t] for t in common])
    n = len(s_ret)
    if n < min_points or n != len(m_ret):
        return None
    mean_s = statistics.mean(s_ret)
    mean_m = statistics.mean(m_ret)
    cov = sum((a - mean_s) * (b - mean_m) for a, b in zip(s_ret, m_ret)) / n
    var_m = sum((b - mean_m) ** 2 for b in m_ret) / n
    if var_m <= 0:
        return None
    return cov / var_m


def fetch_beta(ticker, use_cache=True):
    """Estimated beta vs ^JKSE, or None if insufficient history."""
    stock = fetch_monthly_closes(ticker, use_cache)
    index = fetch_monthly_closes(JCI_TICKER, use_cache, suffix=False)
    return estimate_beta(stock, index)
