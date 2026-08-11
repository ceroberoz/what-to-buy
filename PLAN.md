# PLAN.md — "What-to-Buy": DCF Valuator for Indonesian Listed Stocks (Non-Financials)

> Status: **COMPLETE** — all tasks executed and committed (see git log).

---

## 1. Problem Statement

**User problem**: Investors want a quick, defensible estimate of the fair value of an Indonesian
(IDX-listed) non-financial stock to decide whether it is undervalued ("what to buy").
Estimating intrinsic value by hand is error-prone and time-consuming.

**Target goal**: A terminal-first CLI tool that takes an IDX ticker (e.g. `SIDO`, `TPIA`, `MAPI`),
computes a **Free Cash Flow to Firm (FCFF)** valuation discounted at a **WACC**, and prints a
per-share fair value vs. current price comparison with adjustable core assumptions.

**Definition of success**:
- One command: `uv run dcf.py SIDO` returns a clear report: fair value/share, current price, upside %, and a sensitivity grid.
- All core assumptions are user-adjustable flags with the specified defaults.
- Runs with **only the Python standard library** (zero third-party packages), per AGENTS.md.
- Runs via **`uv`** (`uv run dcf.py ...` / `uv run python -m unittest`) thanks to a minimal `pyproject.toml`; also runs directly with `python3` since there are no dependencies.
- Local **git** repository tracks progress feature-by-feature, one commit per PLAN.md task.

---

## 2. Functional Scope

### Included
- Ticker → current price lookup for IDX stocks (`.JK` suffix on Yahoo Finance).
- Historical financial statement retrieval (income statement, balance sheet, cash flow) in IDR.
- FCFF computation: `EBIT × (1 − tax) + D&A − capex − ΔNWC`.
- WACC computation: `Re = Rf + β·ERP`, `Rd = interest expense / interest-bearing debt`,
  `WACC = E/V·Re + D/V·Rd·(1−tax)`, with `V = E + D`.
- β (beta) estimated from stock vs. IHSG (`^JKSE`) historical returns via regression.
- FCFF projection: near-term growth that linearly fades to terminal growth over the forecast horizon.
- Terminal value via Gordon growth model, discounted at WACC.
- Equity value = Enterprise value − net debt; fair value/share = equity value / shares outstanding.
- Sensitivity analysis: fair value/share grid across discount rate × terminal growth (and risk-free × ERP).
- Local JSON cache to avoid re-fetching; manual data fallback via JSON input file.
- Unit tests for pure DCF math using stdlib `unittest`.

### Excluded (out of scope)
- Financial-sector stocks (banks, insurers, brokers) — user responsibility; tool does not screen them.
- Real-time market data subscriptions, watchlists, portfolio tracking, or a GUI/web app.
- Audited-accuracy guarantee; figures are best-effort from public sources and should be sanity-checked.
- Adjustments for pension liabilities, off-balance-sheet items, or hybrid securities.

---

## 3. Technical Strategy

### Language & constraints
- **Python 3** (stdlib only: `urllib.request`, `json`, `html.parser`, `argparse`, `statistics`, `unittest`).
  Target `requires-python >= 3.9` (system Python here is 3.9.6); avoid newer syntax.
- Single-purpose modules, plain functions, no classes/abstractions beyond necessity (AGENTS.md).
- **uv** is the preferred runner. `pyproject.toml` (no external deps) lets `uv run` resolve an
  interpreter automatically; `python3` direct execution remains a fallback.

### Proposed file layout
```
what-to-buy/
├── AGENTS.md
├── PLAN.md
├── README.md            # usage + methodology + disclaimer
├── pyproject.toml       # minimal uv/project metadata (no dependencies, requires-python >=3.9)
├── dcf.py               # CLI entry point: parse args, orchestrate, print report
├── dcf_core.py          # pure math: WACC, FCFF, discount, terminal value, sensitivity
├── data_source.py       # Yahoo chart+fundamentals, crumb auth, JSON cache, manual-input helpers
└── test_dcf.py          # stdlib unittest for dcf_core + sample end-to-end
```

### Data sources (verified working → fallback)
> Field-verified Aug 2026: `idnfinancials.com` and `idx.co.id` are Cloudflare/WAF-blocked from
> terminals; Yahoo's IDX **fundamentals** coverage is essentially empty (revenue/shares only).
> Price + beta via Yahoo chart are reliable. Statements therefore default to manual JSON input,
> with an auto-attempt that emits a pre-filled template.

1. **Current price & historical returns**: Yahoo Finance chart API
   `https://query1.finance.yahoo.com/v8/finance/chart/{TICKER}.JK` — no auth, JSON, **verified 200 OK**.
   (Short `User-Agent: Mozilla/5.0` + `Accept: */*` required; long UA strings get 429.)
2. **Financial statements (IDR)**: auto-attempt via Yahoo quoteSummary fundamentals API
   (cookie `A3` + crumb handshake, retries across `query1`/`query2`). For IDX this is sparse, so
   when critical fields are missing the tool prints exactly which are missing, writes a
   pre-filled template to `data/{ticker}.json`, and exits instructing the user to fill it and
   re-run with `--input data/{ticker}.json`.
3. **Beta**: OLS/regression of stock monthly returns vs `^JKSE` monthly returns from the same Yahoo
   chart API. Fallback to β=1.0 with a warning if insufficient data. **Verified** (SIDO ≈ 0.34).
4. **Manual fallback**: user-supplied JSON (same normalized schema as the template).

### Calculation methodology
- **WACC**: `Re = Rf + β·ERP`; `Rd = interest expense / interest-bearing debt` (cap if missing);
  weights from market cap (price × shares) and book interest-bearing debt; `WACC = E/V·Re + D/V·Rd·(1−t)`.
- **Tax**: effective rate = income tax / EBT, floored at 0, capped at Indonesian statutory 22%; warning if 0.
- **FCFF (latest year)**: `EBIT·(1−t) + D&A − CAPEX − ΔNWC`.
- **Projection**: for years `1..N` (N = forecast horizon, default 5), FCFF grows from
  `--growth` (near-term, default derived from historical FCFF CAGR if available, else 8%) fading
  linearly to `--terminal-growth` (default 2.5%) at year N.
- **Terminal value** at year N: `FCFF_N × (1+g) / (WACC − g)`, valid only when `g < WACC`.
- **Discounting**: PV at WACC, mid-year convention optional (default end-of-year, flag `--mid-year`).
- **Report**: FCFF projection table, PV of each year, EV, net debt, equity value, fair value/share,
  current price, upside %, and a WACC×terminal-growth sensitivity grid.

### CLI sketch
```
uv run dcf.py SIDO [--risk-free 0.065] [--erp 0.04] [--growth 0.08] \
                   [--terminal-growth 0.025] [--horizon 5] [--beta 0.9] \
                   [--input data.json] [--no-cache]
```
Defaults: risk-free **6.5%**, ERP **4.00%**, terminal growth **2.5%**, horizon **5 years**.
Validated ranges: risk-free 5–9%, ERP 3–10%, terminal growth 0–6%, horizon 5–10.

Tests: `uv run python -m unittest` (stdlib `unittest` only).

### Git & version control (feature tracking via PLAN.md)
- Initialize a **local git repository** at project root (`.gitignore`: `__pycache__/`, `.venv/`, `data/cache/`, `*.pyc`).
- Work is tracked **one commit per PLAN.md task** (T1, T2, …). After a task passes its checks,
  commit with a message prefixed by the task id, e.g. `T2: implement WACC/FCFF/terminal math in dcf_core`.
- Before each commit: `git status` + `git diff` to confirm only intended files are staged; never stage
  secrets/caches. No pushes (local-only repo unless the user later asks to add a remote).

---

## 4. Step-by-Step Task Checklist

Each task ends with a git commit (message prefixed `T<n>:`). Mark `[x]` in PLAN.md as tasks finish.

- [x] **T1 — Repo bootstrap**: `git init` + `.gitignore`; create `README.md` (usage, methodology, disclaimer) and minimal `pyproject.toml`; commit `T1: repo bootstrap (git init, .gitignore, README, pyproject)`.
- [x] **T2 — `dcf_core.py`**: implement pure functions with formulas + docstrings:
      `wacc`, `fcff`, `terminal_value`, `discount_fcf`, `project_fcff`, `fair_value_per_share`, `sensitivity_grid`; commit `T2`.
- [x] **T3 — `data_source.py` price+returns**: Yahoo chart API fetch (price, monthly closes), JSON cache, graceful network errors; commit `T3`.
- [x] **T4 — `data_source.py` beta**: regression of stock vs `^JKSE` monthly returns; fallback β=1.0 + warning; commit `T4`.
- [x] **T5 — `data_source.py` statements**: auto-attempt Yahoo fundamentals (cookie+crumb), normalize to flat schema, manual JSON fallback + template writer; commit `T5`.
- [x] **T6 — `dcf.py` CLI**: `argparse` with adjustable flags, defaults, and range validation; wire fetch→compute→report; commit `T6`.
- [x] **T7 — Report printing**: FCFF projection table, EV→equity→per-share chain, upside %, sensitivity grid; commit `T7`.
- [x] **T8 — `test_dcf.py`**: `unittest` for all `dcf_core` functions (known-value cases) + end-to-end with fixed sample JSON; commit `T8`.
- [x] **T9 — Final gate**: `python -m py_compile *.py`, `uv run python -m unittest`, and a live sanity run on `SIDO`; mark remaining tasks `[x]`; final commit `T9: final gate`.

---

## 5. Risk & Edge Cases

| Risk | Mitigation |
|------|-----------|
| IDX statements providers blocked/sparse (`idnfinancials`/`idx.co.id` Cloudflare+WAF, Yahoo fundamentals empty for IDX) | Auto-attempt Yahoo fundamentals; on missing fields write a pre-filled template and require `--input data/{ticker}.json`; clear list of missing fields |
| Network failure / ticker typo / delisted ticker | Clear exit codes + message; use cached data when available |
| Negative FCFF (loss-makers, high growth) | Warn and still value; user can override `--growth`/`--input` |
| Negative or zero book equity | Fall back to market-value weights; warn |
| Zero-debt companies (common on IDX) | D/V = 0, WACC = Re; handle divide-by-zero |
| Effective tax ≤ 0 (loss year) | Use 0 and warn; cap at 22% statutory |
| `g ≥ WACC` (terminal growth too high) | Reject with explanatory error |
| Insufficient return history for beta | Fallback β=1.0 with visible warning |
| Shares outstanding missing from sources | Require it in manual JSON; error message otherwise |
| IDR/large-number precision | Compute in raw IDR, present in IDR billions |
| Financials ticker misused (bank, etc.) | README disclaimer; no automated screening (out of scope) |
