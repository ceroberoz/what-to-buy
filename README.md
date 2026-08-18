# What-to-Buy

A terminal-first **FCFF DCF valuator** for Indonesian (IDX) listed, non-financial stocks.

Given a ticker (e.g. `SIDO`, `TPIA`, `MAPI`), it computes an intrinsic (fair) value per
share by discounting **Free Cash Flow to Firm (FCFF)** at a **WACC**, then compares it
with the current price to show potential upside — so you can decide "what to buy".

Built with **Python standard library** + minimal dependencies (`curl-cffi`, `openpyxl`, `pdfplumber`).

---

## Tested stocks

These stocks have pre-filled data templates (`data/{TICKER}.json`):

| Ticker | Company | Sector | Notes |
|--------|---------|--------|-------|
| **SIDO** | Sido Muncul | Consumer Health | Template ready, FY 2025 |
| **MAPI** | Mitra Adiperkasa | Retail | Template ready, FY 2025 |
| **FILM** | MD Pictures | Entertainment | Template ready, FY 2024 |
| **BUDI** | Putra Mas Dian Perkasa | Consumer Goods | Template ready, FY 2011 |
| **ACST** | Acset Indonusa | Construction | Template ready, FY 2019 |

> **Note**: Templates have revenue and shares outstanding filled from Yahoo Finance.
> Other fields (EBIT, debt, equity, etc.) must be filled manually from company
> financial statements before running the valuation.

---

## Quick start

### First run — generate template

```bash
uv run dcf.py SIDO
```

This fetches current price from Yahoo Finance and creates `data/SIDO.json` template.

### Second run — fill template and value

1. Edit `data/SIDO.json` with actual financial data from the company's annual report
2. Re-run:

```bash
uv run dcf.py SIDO --input data/SIDO.json
```

### Output example

```
What-to-Buy DCF | SIDO (FY 2025)

Market data
  Price (IDR)               :           1,994.19
  Market cap                :              58.7T
  Beta (vs IHSG)            :                0.75

Valuation chain
  Enterprise value          :              73.2T
  Equity value              :              71.5T
  Fair value / share        :             2,428.53
  Current price             :             1,994.19
  Upside / downside         :              +21.79%
  Verdict                   :          UNDERVALUED

WACC sensitivity (terminal growth = 2.5%)
        WACC  8.0%  9.0%  10.0%  11.0%  12.0%
Fair     IDR 2,891 2,428  2,093  1,844  1,652
```

### Reading the output

| Field | Meaning |
|-------|---------|
| **Price** | Current market price from Yahoo Finance |
| **Market cap** | Price × shares outstanding |
| **Beta** | Stock volatility vs IHSG index (>1 = more volatile) |
| **Enterprise value** | Total firm value (equity + debt - cash) |
| **Fair value / share** | Calculated intrinsic value per share |
| **Upside / downside** | `(Fair value - Current price) / Current price × 100` |
| **Verdict** | `UNDERVALUED` if upside > 10%, `OVERVALUED` if < -10%, else `FAIRLY VALUED` |
| **Sensitivity grid** | Fair value under different WACC × terminal growth assumptions |

---

## Commands

### Single stock valuation

```bash
# Auto-fetch price, use cached data
uv run dcf.py SIDO

# Use manual financials
uv run dcf.py SIDO --input data/SIDO.json

# With custom assumptions
uv run dcf.py SIDO --risk-free 0.065 --erp 0.04 --terminal-growth 0.03

# Longer forecast horizon (8 years instead of 5)
uv run dcf.py SIDO --horizon 8

# Override beta (ignore Yahoo estimate)
uv run dcf.py SIDO --beta 1.2

# Mid-year discounting (more accurate for ongoing operations)
uv run dcf.py SIDO --mid-year
```

### All tested stocks

```bash
for ticker in SIDO MAPI FILM BUDI ACST; do
  uv run dcf.py $ticker --input data/$ticker.json
done
```

### Screen for eligible stocks

```bash
# Show all eligible IDX stocks (non-financial, listed >5 years)
uv run screen.py --all

# Screen specific tickers
uv run screen.py SIDO TPIA MAPI

# Screen from a file
uv run screen.py --list tickers.txt
```

### Run tests

```bash
uv run python -m unittest
```

---

## CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--input FILE.json` | — | Manual financials JSON (create with first run) |
| `--risk-free RATE` | `0.065` | Risk-free rate (Indonesian 10Y bond yield) |
| `--erp RATE` | `0.04` | Equity risk premium |
| `--terminal-growth RATE` | `0.025` | Long-run FCFF growth rate |
| `--horizon YEARS` | `5` | Forecast horizon (5–10 years) |
| `--growth RATE` | auto | Near-term FCFF growth override |
| `--beta BETA` | auto | Override estimated beta |
| `--mid-year` | off | Use mid-year discounting convention |
| `--no-cache` | off | Bypass local data cache |
| `--skip-check` | off | Skip eligibility whitelist check |

---

## How it works

1. **Price**: Yahoo Finance chart API (`{TICKER}.JK`).
2. **Financials**: Manual input via JSON template (auto-filled fields: revenue, shares).
3. **Beta**: Regression of monthly stock returns against IHSG (`^JKSE`); falls back to 1.0.
4. **WACC**: `Re = Rf + β×ERP`, `Rd = interest expense / debt`, `WACC = E/V·Re + D/V·Rd·(1−t)`.
5. **FCFF**: `EBIT·(1−t) + D&A − CAPEX − ΔNWC`.
6. **Projection**: Near-term growth fades linearly to terminal growth over the horizon.
7. **Terminal value**: Gordon growth `FCFF_N·(1+g)/(WACC−g)`.
8. **Per share**: Equity value = EV − net debt; fair value = equity / shares outstanding.

---

## Project layout

```
what-to-buy/
├── dcf.py              # CLI entry point
├── dcf_core.py         # Pure DCF math (WACC, FCFF, terminal value, sensitivity)
├── data_source.py      # Yahoo chart/fundamentals fetch, cache, manual-input helpers
├── screen.py           # Eligibility screener (non-financial, >5y listed)
├── test_dcf.py         # Unit tests
├── data/
│   ├── sample.json     # Schema reference for manual financials input
│   ├── eligible_tickers.json  # 515 eligible IDX tickers
│   ├── SIDO.json       # Pre-filled templates for tested stocks
│   ├── MAPI.json
│   ├── FILM.json
│   ├── BUDI.json
│   └── ACST.json
└── pyproject.toml      # Project metadata + dependencies
```

---

## Disclaimer

For educational and investment-research purposes only. Figures are best-effort reconstructions
from public sources and are **not investment advice**. Financial-sector stocks (banks, insurers)
are out of scope and will produce misleading values.
