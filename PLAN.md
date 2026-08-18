# PLAN.md — Phase 4: IDX official annual financial statements ("IDX source")

> Phases 1–3 (DCF valuator, per-ticker whitelist, full-IDX-universe whitelist) are COMPLETE.
> This file now tracks **Phase 4: auto-fetch annual financial statements from idx.co.id**
> (the official IDX portal) to replace the manual template-filling step.

---

## 1. Problem Statement

**User problem**: Yahoo's financial statements for IDX companies are sparse (that is why the
tool today writes a pre-filled template to `data/{TICKER}.json` that the user fills **by hand**
from a browser — slow and error-prone). The user wants the "rest of the process" automated.

**Target goal**: `uv run dcf.py SIDO` automatically fetches complete **annual** financials from
IDX's official portal (free, official issuer filings) via the verified
`GetFinancialReport` API + XLSX soft-copy download, computes all required DCF fields, and only
falls back to the manual template when **both** Yahoo and IDX fail.

**Definition of success**:
- `uv run dcf.py SIDO` produces a full valuation with **zero manual input** (financials sourced
  from IDX; price/beta/shares still from Yahoo).
- Offline: fixture-based unit tests for the XLSX parser + mocked-HTTP integration tests pass;
  all existing tests (currently 40+) still pass (`uv run python -m unittest`).
- The manual template fallback still works unchanged when neither source has data.

**Verified feasibility (live, by research)**: endpoint works; XLSX downloads without auth;
workbook contains income statement, balance sheet (2 years), cash flow, depreciation movement;
units declared in-workbook (SIDO = millions of IDR).

---

## 2. Functional Scope

### Included
- **New module `idx_source.py`**:
  - `fetch_report_index(ticker, year)` → `GET https://www.idx.co.id/primary/ListedCompany/GetFinancialReport`
    with params `indexFrom=0&pageSize=12&year={Y}&reportType=rdf&EmitenType=s&periode=audit&kodeEmiten={T}` —
    returns the `Attachments` list (pick the `.xlsx` soft copy). Old `/Data/GetFinancialReport` endpoints are dead (503); do not use.
  - `download_xlsx(file_path)` → download via the `File_Path` static URL (no auth; URL-encode spaces).
  - `parse_workbook(path)` → pure function → flat normalized dict (same schema as
    `data_source.normalize_statements`), all values in **full IDR**:
    - Read the per-company **rounding multiplier** from sheet `1000000` ("Pembulatan":
      Jutaan → 1e6, Ribuan → 1e3, else 1; warn on unknown).
    - Income statement (sheet `1321000`): revenue, pre-tax income, tax expense (abs of the
      negative "Pendapatan (beban) pajak"), interest expense ("Beban bunga dan keuangan").
      **EBIT is not in the XBRL taxonomy** → compute `gross profit − selling − G&A`
      (matches reported "Laba Usaha"); fall back to `pre-tax + interest` with a warning.
    - Balance sheet (sheet `1210000`, current + prior year columns): cash, current assets,
      current liabilities, total equity, and **interest-bearing debt** via label matching
      (utang bank / obligasi / pinjaman / sewa / "jatuh tempo dalam satu tahun"): short-term
      vs long-term; if nothing matches → debt 0 with warning.
    - Cash flow (sheet `1510000`, direct method): operating cash flow total; capex =
      payments for fixed assets + advances + intangibles.
    - Depreciation (sheet `1611000`, PPE accumulated-depreciation movement: "Penambahan"
      additions) + intangibles/ROU depreciation if present.
  - **shares_outstanding is NOT in the XBRL workbook** → keep Yahoo `defaultKeyStatistics`
    (already fetched by the existing flow) when composing the final financials.
- **`dcf.py` integration**: source chain **Yahoo → IDX → manual template** (try Yahoo first —
  unchanged behaviour; if incomplete, fetch IDX; if still incomplete, write template as today).
  Report/source label shows which source was used (`--input` still wins; `--no-cache` applies).
- **Dependencies** (`pyproject.toml`): `curl_cffi` (Cloudflare-passing client; plain `requests`
  gets HTTP 403 — verified) + `openpyxl` (XLSX parsing). No `requests`, no `beautifulsoup4`
  (API returns JSON; nothing to HTML-parse).
  → **This deliberately relaxes the AGENTS.md "zero third-party packages" rule for these two
  pinned deps** (the user already approved adding scraping deps in Phase 4 kickoff).
- **Tests**: fixture XLSX (SIDO FY2025, committed under `tests/fixtures/`) for offline parser
  tests; mocked-HTTP tests for the fetch layer; live gate on SIDO.
- **AGENTS.md/README update**: document the new deps, the IDX source, and the field caveats
  (EBIT computed, debt matching, shares from Yahoo).

### Excluded (out of scope)
- Quarterly (triwulan) reports — annual (`periode=audit`) only.
- XBRL `instance.zip` parsing — the XLSX soft copy is used instead.
- shares_outstanding from IDX, auto-refresh scheduling, price/beta changes, DCF methodology changes.

---

## 3. Technical Strategy

- **HTTP client**: `curl_cffi.requests` with `impersonate="chrome"` — the only client verified
  to pass idx.co.id's Cloudflare (403 for plain requests; old endpoints 503).
- **Index lookup**: one GET per ticker for the target year; if no attachment (annual report not
  yet filed), step back one year (latest available) and warn.
- **XLSX parse**: label-driven row matching per sheet (XBRL-derived layout is
  taxonomy-standardized; SIDO row refs are the fixture baseline). Numbers in stated rounding
  unit → multiply to full IDR.
- **Caching**: downloaded XLSX cached under `data/cache/` (extend existing cache helpers);
  parsed JSON cached via the existing `_cache_get/_cache_set` pattern.
- **Offline safety**: `parse_workbook` is pure (fixture-testable); all network behind
  `fetch_*` wrappers; tests never touch the network.

### Proposed file layout (additions)
```
what-to-buy/
├── idx_source.py         # NEW: IDX GetFinancialReport fetch + XLSX parse + normalize
├── dcf.py                # MODIFIED: source chain Yahoo → IDX → manual template
├── data_source.py        # MODIFIED (minor): reuse cache helpers / shares fallback
├── tests/fixtures/       # NEW: SIDO FY2025 XLSX + report-index JSON fixture
├── test_dcf.py           # MODIFIED: new parser + integration tests
├── pyproject.toml        # MODIFIED: + curl_cffi, openpyxl
├── AGENTS.md             # MODIFIED: dependency-rule update
└── README.md             # MODIFIED: IDX source docs
```

---

## 4. Step-by-Step Task Checklist

Each task ends with a git commit (message prefix `D<n>:`). Mark `[x]` as tasks finish.

- [x] **D1 — deps + HTTP layer**: `uv add curl_cffi openpyxl`; `idx_source.py` with
      `fetch_report_index()` (GetFinancialReport, params verified) and `download_xlsx()`;
      XLSX cache dir; commit `D1`.
- [x] **D2 — XLSX parser**: pure `parse_workbook(path) -> dict` (rounding multiplier, income /
      balance / cash-flow / PPE-depreciation extraction, EBIT computation, debt matching,
      capex/OCF sums) + `normalize()` to the flat schema (millions → full IDR);
      SIDO fixture committed; commit `D2`.
- [x] **D3 — dcf.py integration**: `fetch_financials_chain()` Yahoo → IDX → template; source
      label in report; `--no-cache` respected; manual `--input` untouched; commit `D3`.
- [x] **D4 — tests + final gate**: parser unit tests on the fixture; mocked-HTTP tests;
      `python -m py_compile *.py`; `uv run python -m unittest`; live `uv run dcf.py SIDO`
      (IDX-sourced, no manual input); commit `D4`.

---

## 5. Risk & Edge Cases

| Risk | Mitigation |
|------|-----------|
| Cloudflare changes / blocks curl_cffi later | `impersonate="chrome"` verified today; manual template path remains as permanent fallback; document |
| Rounding unit differs per company | Read the `1000000` "Pembulatan" declaration per workbook; unknown → full IDR + warning |
| EBIT absent from XBRL taxonomy | Computed gross−selling−admin (SIDO baseline); fallback pre-tax+interest + warning |
| Depreciation not in income statement | From PPE accumulated-depreciation movement; ROU/intangibles handled separately if present |
| Debt lines vary by taxonomy/language | Keyword label matching (ID/EN) with SIDO baseline; no match → 0 + warning (unlevered case correct) |
| Shares outstanding missing from IDX | Yahoo `defaultKeyStatistics` (existing path) |
| Annual report not yet filed for year Y | Step back to latest available year and warn |
| Old endpoints tempting reuse | Documented dead (503); only `primary/ListedCompany/GetFinancialReport` used |
| XLSX schema drift | Fixture-based tests catch layout changes; label-driven (not row-number-driven) matching |
| AGENTS.md "zero deps" rule conflict | Explicitly documented relaxation for the two pinned deps |

---

## 6. Alternative Data Source Research (Post-Phase 4)

**Context**: Some IDX tickers (e.g. MAPI) have empty XLSX data cells from IDX, and Yahoo
returns only revenue + shares. We investigated whether a third automated source could fill
the gap.

### Sources Investigated

| Source | Data Available | Access Method | Result |
|--------|---------------|---------------|--------|
| idnfinancials.com | Full financials (IS, BS, CF) | Web scraping | **PAYWALLED** — Rp 250K/month for full data; free tier = revenue + net profit only |
| sectors.app/idx/{ticker} | Income statement flow (revenue, COGS, gross profit, operating income, selling, G&A) via Sankey JSON | HTML scraping | **PARTIAL** — no balance sheet, no cash flow, no depreciation/capex |
| OJK Open Data | Banking/insurance sector reports | REST API | **NOT APPLICABLE** — individual stock financials not available |
| Yahoo Finance (extended) | Revenue, shares for IDX tickers | API | **ALREADY IN CHAIN** — limited for IDX |
| Investing.com | Full financials | Web scraping | **CLOUDFLARE BLOCKED** — requires browser automation |
| Stockbit | Community-sourced data | Login required | **NOT AUTOMATABLE** without account |

### Recommended Path

**Accept current behavior**: The chain `Yahoo → IDX XLSX → manual template` works well for
most tickers. For edge cases like MAPI (empty XLSX + sparse Yahoo), the manual template
fallback is the correct behavior — there is no free, automated source with complete data.

**No new code required**. The system already handles this gracefully:
1. Yahoo fetches whatever it has (revenue, shares)
2. IDX fetches the XLSX (which may have empty cells for some tickers)
3. `data/MAPI.json` manual template exists as permanent fallback
4. User fills template from company IR page (e.g. map.co.id PDF annual reports)

**Future consideration**: If idnfinancials.com premium subscription is obtained, we could
build a scraper (`requests` + `beautifulsoup4`) and add it as a 4th source in the chain:
`Yahoo → IDX XLSX → idnfinancials → manual template`. This is documented but not
implemented (paywall blocks free access).

---

## 7. XLSX Format Variants & Parser Fix (Post-Phase 4)

### Root Cause Analysis

Investigated why only 5/38 tickers produce full DCF results. Two distinct issues found:

**Issue A — Different XBRL taxonomy prefixes**: IDX XLSX files use two numbering conventions:
- `1xxxxxx` (e.g. `1321000`) — General Industry taxonomy (SIDO, ADRO, ASII, etc.)
- `3xxxxxx` (e.g. `3321000`) — Infrastructure Industry taxonomy (TLKM, EXCL, ISAT, JSMR, etc.)

The parser originally hardcoded `1321000`, `1210000`, `1510000`, `1611000` → crashed with
"Worksheet 1321000 does not exist" on `3xxxxxx` tickers.

**Issue B — Empty data cells (IDX data quality)**: Most XLSX files ship with labels only,
no numeric data. This is an IDX data quality issue — the company hasn't populated the
template, or the data is behind a different filing format.

### Tested Results (38 tickers)

| Category | Tickers | Count |
|----------|---------|-------|
| ✓ Full DCF (data present) | SIDO, ADRO, ASII, ELSA, INTP, FILM | 6 |
| ✗ Empty data cells (`1xxxxxx`) | MAPI, GOTO, BUDI, TPIA, BRPT, CPIN, GGRM, HRUM, INDF, INKP, KLBF, MDKA, MIKA, PTBA, SMGR, UNVR, ARNA, EMTK, ESSA, LSIP, MNCN, PWON | 22 |
| ✗ Empty data cells (`3xxxxxx`) | TLKM, EXCL, ISAT, JSMR, MTEL, PGAS, TBIG | 7 |
| ✗ Financial sector (no IS sheet) | BBCA, BBRI, BMRI, NISP, BRIS, ARTO, BSDE, CTRA | 8 |

### Fix Applied

Added `_find_sheet(wb, suffix)` helper that dynamically finds sheets by suffix (e.g.
`"321000"` matches both `1321000` and `3321000`). Parser now gracefully raises
`IdxSourceError` for missing sheets instead of `KeyError`.

**Result**: `3xxxxxx` tickers no longer crash — they correctly fall through to the empty-data
guard and produce the expected "XLSX workbook has no usable numeric data" warning.

### Remaining Limitation

The empty-data-cell issue (Issue B) is an IDX data quality problem. No code fix possible —
these tickers require manual templates or an alternative data source.
