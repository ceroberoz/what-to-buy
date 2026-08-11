# PLAN.md — Phase 2: IDX Eligibility Whitelist ("stock ticker check")

> Phase 1 (the DCF valuator) and Phase 2 (per-ticker whitelist) are COMPLETE.
> This file now tracks **Phase 3: add all eligible IDX tickers to the existing whitelist**.

---

## 1. Problem Statement

**User problem**: The existing whitelist (`data/eligible_tickers.json`) only lists tickers the
user explicitly screened (SIDO, TPIA, MAPI). They want it to contain **all** eligible IDX
tickers so any ticker check in `dcf.py` is a fast local lookup.

**Target goal**: A one-shot `uv run screen.py --all` fetches the full IDX equity universe,
computes the eligible set (listed > 5 years, not Financial Services), and **merges** those
tickers into the existing `data/eligible_tickers.json` — adding missing eligible tickers while
keeping the current entries and their sector/industry detail intact.

**Definition of success**:
- After `uv run screen.py --all`, `data/eligible_tickers.json` contains the whole eligible
  universe (~515 of 839 IDX equities), existing entries (e.g. SIDO/TPIA/MAPI) unchanged.
- `uv run dcf.py BBRI` still skips instantly; any other eligible ticker passes the check.
- No per-ticker network calls (2 bulk screener queries + paging).

**Verified feasibility (live)**: Yahoo screener `exchange=JKT` returns all 839 equities with
`firstTradeDateMilliseconds`; adding `sector = Financial Services` returns 99 financial tickers
(includes BBRI). Local rule → **515 eligible**.

---

## 2. Functional Scope

### Included
- `screen.py --all` flag that:
  1. Fetches the full IDX universe (`exchange=JKT`, paged, cached) — ticker + listing date.
  2. Fetches the Financial Services subset (same screener + sector operand).
  3. Loads the existing whitelist, computes eligible = {age > 5y} − {financial}, and **merges**:
     new eligible tickers are added to `tickers`/`meta`; existing entries are preserved
     (never downgraded/removed); financial + too-young tickers recorded in `meta` with a reason.
  4. Saves back to the same `data/eligible_tickers.json`.
- A small pure helper for the merge (offline-testable).
- Screener payloads cached under `data/cache/` (`--no-cache` bypasses).

### Excluded (out of scope)
- A separate universe mode, rebuild-from-scratch, or new CLI beyond the `--all` flag.
- Fetching `summaryProfile` sector for the ~515 eligible tickers (sector is only needed to
  exclude; screener-provided eligible entries store sector/industry as `""`).
- Auto-refresh scheduling; changing the age rule, the financial exclusion, or `dcf.py`.

---

## 3. Technical Strategy

- Reuse `data_source._authenticated_opener()` / `_get_crumb()` and the JSON-cache helpers for the
  paged screener POST (same crumb handshake that already works for fundamentals).
- Page loop (`size=250`) with a short sleep between pages; `quoteType=equity`.
- Merge = union on the existing whitelist: load doc, add missing entries from the universe,
  keep everything already present, write back via the existing `save_eligible`.
- Zero new dependencies (stdlib only).

---

## 4. Step-by-Step Task Checklist

- [x] **P1 — screener fetchers**: `fetch_universe()` and `fetch_financial_symbols()` (paged,
      cached) in `screen.py`; commit `P1`.
- [x] **P2 — merge + `--all` wiring**: pure `merge_universe(entries, all_quotes,
      financial_symbols, now_ts)` (adds missing eligible/excluded entries, preserves existing);
      `--all` flag in the CLI that fetches → merges → saves; per-ticker mode untouched; commit `P2`.
- [x] **P3 — tests + final gate**: unit tests for `merge_universe` (bank excluded, young excluded,
      old non-bank added, existing entry preserved); `py_compile`; `unittest`; a live
      `screen.py --all` run verifying the whitelist grows to ~515 eligible and BBRI/BMRI/BCA are
      excluded; commit `P3`.

---

## 5. Risk & Edge Cases

| Risk | Mitigation |
|------|-----------|
| Screener pagination flakiness / rate limiting | Single authenticated session per query; page loop with delay; cache payloads; `--no-cache` retries |
| Ticker missing from the Financial Services filter (sector unset in screener) | Sanity-check known banks (BBRI/BMRI/BCA) in the live gate; document the limitation |
| Existing whitelist accidentally overwritten | Merge preserves all present entries; only missing ones are added |
| Non-common equities (REITs, warrants) in `exchange=JKT` | `quoteType=equity` filter; age/sector rules still apply |
| Eligible entries lack sector/industry detail | Accepted: only used in skip messages; per-ticker `screen.py` runs can re-add detail |

---

## 1. Problem Statement

**User problem**: Before running the FCFF DCF on an IDX ticker, the user must know whether the
stock qualifies for the tool's methodology — it must be **non-bank** and **listed > 5 years**.
Determining that per-ticker today would mean network queries (sector lookup + listing date),
which is slow. A local whitelist makes the check a fast file read, and ineligible tickers are
skipped **before any processing or network I/O**.

**Target goal**:
- A JSON config, `data/eligible_tickers.json`, holding the whitelist of IDX tickers that are
  > 5 years listed and not in the bank/financial sector, built by a new `screen.py` that
  fetches sector + listing date from a free source (Yahoo).
- `dcf.py` reads the whitelist on startup; a ticker not on it is skipped (exit 0, no network).

**Definition of success**:
- `uv run screen.py SIDO TPIA BBRI` writes `data/eligible_tickers.json` (banks / young tickers excluded).
- `uv run dcf.py BBRI` prints `skipped: not eligible (…reason…)` and exits 0 with **zero** network calls.
- `uv run dcf.py SIDO` still runs normally (fast whitelist check passes).
- `--skip-check` bypasses the whitelist (for manual/bank runs and self-tests).
- All existing 28 tests plus new tests pass (`uv run python -m unittest`).

---

## 2. Functional Scope

### Included
- **`screen.py`** (new module):
  - Fetch per ticker: `sector`/`industry` from Yahoo `summaryProfile` (via existing
    `data_source.yahoo_fundamentals`, crumb+retry already handled) and `firstTradeDate` from
    Yahoo chart `range=max` (via existing `data_source.yahoo_chart`).
  - Pure eligibility rule (testable offline):
    - Age = (now − firstTradeDate) > 5 years, else **SKIP (listed < 5 years)**.
    - Excluded if `sector == "Financial Services"` or `"bank" in industry.lower()`
      (covers banks + the insurers/brokers the project already disclaims), else **INCLUDE**.
  - Writes `data/eligible_tickers.json`: `{"updated": ISO, "tickers": ["SIDO", …],
    "meta": {"SIDO": {"sector", "industry", "listed": YYYY-MM-DD, "age_years"}}}`.
  - CLI: `uv run screen.py SIDO TPIA …` (positional) and/or `--list FILE` (one ticker/line);
    with no input, scans tickers already present in `data/*.json` templates and `data/cache/`.
  - Prints a per-ticker status line (ELIGIBLE / SKIP reason / NO_DATA) and a summary.
- **`dcf.py`** (integration):
  - Load `data/eligible_tickers.json` once at startup.
  - Ticker not in whitelist → print `skipped: {ticker} not eligible` (with reason from meta if
    available) and exit 0, before any network I/O or `--input` processing.
  - Whitelist file missing → warn once and continue (non-blocking; tool stays usable offline).
  - New flag `--skip-check` to bypass the whitelist.
- **Tests**: pure rule, whitelist I/O, and `dcf.py` skip/`--skip-check` behaviour.

### Excluded (out of scope)
- Downloading the **full** IDX ticker universe (no reliable free/terminal source — see PLAN.md
  phase 1 data-source notes; the user supplies tickers to screen).
- Auto-refresh scheduling or live sector re-checks at every run (that is the slow query this
  feature replaces).
- Changing the DCF methodology or existing CLI behaviour for eligible tickers.

---

## 3. Technical Strategy

- **Reuse, don't rebuild**: all fetching goes through existing `data_source.py`
  (`yahoo_fundamentals` with `modules=("summaryProfile",)`, `yahoo_chart` with `range="max"`).
  Verified working from the terminal: `summaryProfile` returns `sector`; chart `max` returns
  `firstTradeDate`.
- **Zero new dependencies** (stdlib only, per AGENTS.md). `screen.py` uses `json`, `time`,
  `datetime`, `argparse`, `os`.
- **Pure logic separated from I/O** so the eligibility rule is unit-testable offline.
- **Fast check path**: `dcf.py` reads a small local JSON (sub-millisecond), no network.

### Proposed file layout (additions)
```
what-to-buy/
├── screen.py              # NEW: build/refresh data/eligible_tickers.json
├── dcf.py                 # MODIFIED: whitelist check + --skip-check
├── data/eligible_tickers.json  # GENERATED whitelist (gitignored? see decision below)
└── test_dcf.py            # MODIFIED: new tests
```

### Git ignore decision
`data/eligible_tickers.json` is derived data refreshed by `screen.py`. Phase 1 already
gitignores `data/cache/`; manual financials (`data/*.json`) are committed. The whitelist is
small and cheap to refresh, so it is **committed** (like `data/*.json`), giving users a working
whitelist out of the box; `screen.py` refreshes it when needed.

---

## 4. Step-by-Step Task Checklist

Each task ends with a git commit (message prefixed `E<n>:`). Mark `[x]` as tasks finish.

- [x] **E1 — `screen.py` core**: pure `eligibility(sector, industry, first_trade_ts, now)` →
      `(eligible: bool, reason: str)`; `load_eligible(path)` / `save_eligible(path, entries)`
      for the whitelist JSON schema; commit `E1`.
- [x] **E2 — `screen.py` fetch + CLI**: `fetch_eligibility(ticker)` (summaryProfile + chart max);
      `scan(tickers)` orchestrator; `argparse` CLI (positional + `--list` + default scan of
      `data/`); status printing; commit `E2`.
- [x] **E3 — `dcf.py` integration**: load whitelist; early skip with reason (exit 0); `--skip-check`
      flag; missing-file warning; commit `E3`.
- [x] **E4 — tests + final gate**: add unit tests (rule boundaries: 5y exactly, bank excluded,
      old non-bank included; load/save round-trip; dcf.py skip path + `--skip-check`); run
      `python -m py_compile *.py`, `uv run python -m unittest`, live `screen.py` run on
      `SIDO TPIA BBRI MAPI`, and a live fast `dcf.py BBRI` skip; commit `E4`.

---

## 5. Risk & Edge Cases

| Risk | Mitigation |
|------|-----------|
| `firstTradeDate` = when Yahoo began coverage, not always the actual IPO date (may understate age) | Document the caveat in `screen.py`/README; treat age as best-effort; user can add a ticker to the whitelist manually |
| Sector string differs for some IDX banks (e.g. listed under insurers/brokers) | Exclude the whole `Financial Services` sector + `bank` keyword in industry — matches the project's existing financial-sector disclaimer |
| Ticker with no Yahoo data (typo, delisted, private) | Mark `NO_DATA`, exclude from whitelist, keep running others; clear per-ticker status |
| Whitelist file missing on first run | `dcf.py` warns once and continues (non-blocking) so offline manual `--input` runs still work |
| Whitelist staleness (new IPO, sector change) | Re-run `uv run screen.py …`; the file is committed and refreshable |
| `--input` manual runs for a skipped ticker | `--skip-check` flag overrides the whitelist |
