"""IDX official-portal data retrieval for the What-to-Buy valuator.

Fetches the annual financial report index from idx.co.id's GetFinancialReport
API and downloads the XLSX soft-copy attachments. Parsing the workbook is a
separate later step (Phase 4 D2); this module only handles the HTTP layer.

Uses curl_cffi with Chrome impersonation because plain requests gets an HTTP
403 Cloudflare challenge from idx.co.id. The report index reuses the existing
JSON cache helpers from data_source (data/cache/); downloaded XLSX files are
cached under data/cache/idx/.
"""

import json
import os
import urllib.parse

from curl_cffi import requests as cffi_requests

import data_source as ds
from data_source import _cache_get, _cache_set

IDX_BASE = "https://www.idx.co.id/primary/ListedCompany/GetFinancialReport"
IDX_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cache", "idx")
TIMEOUT = 20
DEFAULT_TTL = 86400


class IdxSourceError(ds.DataSourceError):
    """Raised when IDX data cannot be fetched or downloaded."""


# --- HTTP helpers -----------------------------------------------------------

_session = None


def _get_session():
    """Lazily-created curl_cffi session with Chrome impersonation.

    idx.co.id sits behind Cloudflare and answers plain-requests clients with
    HTTP 403; browser impersonation is what passes the challenge.
    """
    global _session
    if _session is None:
        _session = cffi_requests.Session(impersonate="chrome")
    return _session


# --- IDX report index -------------------------------------------------------

def fetch_report_index(ticker, year, use_cache=True, ttl=DEFAULT_TTL):
    """List of annual report results for a ticker/year from GetFinancialReport.

    Returns the JSON "Results" array; an empty list when the annual report for
    that year has not been filed yet (no "Results" key in the response).
    """
    key = "idx_index_{}_{}".format(ticker.upper(), year)
    if use_cache:
        cached = _cache_get(key, ttl)
        if cached is not None:
            return cached
    params = urllib.parse.urlencode(
        {
            "indexFrom": 0,
            "pageSize": 12,
            "year": year,
            "reportType": "rdf",
            "EmitenType": "s",
            "periode": "audit",
            "kodeEmiten": ticker.upper(),
        }
    )
    url = IDX_BASE + "?" + params
    response = _get_session().get(url, timeout=TIMEOUT)
    if response.status_code != 200:
        raise IdxSourceError("HTTP {} fetching report index from {}".format(response.status_code, url))
    try:
        payload = json.loads(response.text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise IdxSourceError("invalid JSON from {}: {}".format(url, exc)) from exc
    results = payload.get("Results") or []
    if use_cache:
        _cache_set(key, results)
    return results


# --- XLSX attachment download -----------------------------------------------

def find_xlsx_attachment(result):
    """First attachment dict of a report result whose file name ends in .xlsx, else None."""
    for attachment in result.get("Attachments", []):
        name = attachment.get("Attachment_File", "")
        if name.lower().endswith(".xlsx"):
            return attachment
    return None


def download_xlsx(attachment, dest_dir=None, use_cache=True):
    """Download the XLSX soft copy referenced by an attachment dict to the cache dir.

    Returns the local path. The API File_Path contains raw spaces (and a double
    slash); only the spaces are URL-encoded, the rest of the URL is kept as-is.
    """
    filename = attachment.get("Attachment_File")
    if not filename:
        raise IdxSourceError("attachment has no Attachment_File: {}".format(attachment))
    file_url = attachment.get("File_Path")
    if not file_url:
        raise IdxSourceError("attachment {} has no File_Path".format(filename))
    if dest_dir is None:
        dest_dir = IDX_CACHE_DIR
    os.makedirs(dest_dir, exist_ok=True)
    local_path = os.path.join(dest_dir, filename)
    if use_cache and os.path.exists(local_path):
        return local_path
    url = file_url.replace(" ", "%20")
    response = _get_session().get(url, timeout=TIMEOUT)
    if response.status_code != 200:
        raise IdxSourceError("HTTP {} downloading {} from {}".format(response.status_code, filename, url))
    with open(local_path, "wb") as fh:
        fh.write(response.content)
    return local_path
