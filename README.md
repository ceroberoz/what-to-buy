# What-to-Buy

A terminal-first **FCFF DCF valuator** for Indonesian (IDX) listed, non-financial stocks.

Given a ticker (e.g. `SIDO`, `TPIA`, `MAPI`), it computes an intrinsic (fair) value per
share by discounting **Free Cash Flow to Firm (FCFF)** at a **WACC**, then compares it
with the current price to show potential upside — so you can decide "what to buy".

Built with **only the Python standard library** (zero third-party packages).

---

## Use case example

Suppose you want to know whether `SIDO` (Sido Muncul, an IDX consumer-goods company) is
fairly priced today. Run:

```bash
uv run dcf.py SIDO
```

On first run the tool fetches the current price and beta from Yahoo Finance and, since IDX
financial statements aren't available from free terminal-accessible APIs, writes a pre-filled
template to `data/SIDO.json`. Fill the template from the company's published financials
(e.g. via idnfinancials.com in a browser), then re-run:

```bash
uv run dcf.py SIDO --input data/SIDO.json
```

You get a report like this (synthetic sample):

```
What-to-Buy DCF | SAMPLE (FY 2025)

Market data
  Price (IDR)               :             1,000.00
  Market cap                :                 1.0B
  Beta (vs IHSG)            :                 1.00

Valuation chain
  Enterprise value          :                 2.0B
  Equity value              :                 2.0B
  Fair value / share        :             1,994.19
  Current price             :             1,000.00
  Upside / downside         :              +99.42%
  Verdict                   :          UNDERVALUED
```

The report also includes a WACC × terminal-growth **sensitivity grid** so you can see how
the fair value reacts to assumption changes.

---

## How to run

### Requirements

- Python 3.9+
- Optional but recommended: [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

### Run a valuation

```bash
# Preferred (uv):
uv run dcf.py SIDO --input data/SIDO.json

# Fallback (plain Python — no dependencies):
python3 dcf.py SIDO --input data/SIDO.json
```

### Adjust assumptions

| Flag | Default | Meaning |
|------|---------|---------|
| `--risk-free` | `0.065` | Risk-free rate |
| `--erp` | `0.04` | Equity risk premium |
| `--terminal-growth` | `0.025` | Long-run FCFF growth |
| `--horizon` | `5` | Forecast horizon (years, 5–10) |
| `--growth` | auto | Near-term FCFF growth |
| `--beta` | auto | Override estimated beta |
| `--mid-year` | off | Mid-year discounting convention |
| `--input FILE.json` | – | Manual financials JSON |
| `--no-cache` | off | Bypass the local data cache |

```bash
uv run dcf.py TPIA --risk-free 0.065 --erp 0.04 --terminal-growth 0.03
uv run dcf.py MAPI --horizon 8 --beta 1.2
```

### Run the tests

```bash
uv run python -m unittest        # or: python3 -m unittest
```

---

## How it works

1. **Price**: Yahoo Finance chart API (`{TICKER}.JK`).
2. **Financials (IDR)**: auto-attempted from Yahoo; when sparse (typical for IDX), the tool
   writes a pre-filled template for manual completion, used via `--input`.
3. **Beta**: regression of monthly stock returns against IHSG (`^JKSE`); falls back to 1.0.
4. **WACC**: `Re = Rf + β×ERP`, `Rd = interest expense / debt`, `WACC = E/V·Re + D/V·Rd·(1−t)`.
5. **FCFF**: `EBIT·(1−t) + D&A − CAPEX − ΔNWC`.
6. **Projection**: near-term growth fades linearly to terminal growth over the horizon.
7. **Terminal value**: Gordon growth `FCFF_N·(1+g)/(WACC−g)`.
8. **Per share**: equity value = EV − net debt; fair value = equity / shares outstanding.

## Project layout

```
what-to-buy/
├── dcf.py           # CLI entry point
├── dcf_core.py      # pure DCF math (WACC, FCFF, terminal value, sensitivity)
├── data_source.py   # Yahoo chart/fundamentals fetch, cache, manual-input helpers
├── test_dcf.py      # stdlib unittest
├── data/sample.json # schema reference for the manual financials input
└── pyproject.toml   # minimal metadata (no dependencies)
```

---

## Disclaimer

For educational and investment-research purposes only. Figures are best-effort reconstructions
from public sources and are **not investment advice**. Financial-sector stocks (banks, insurers)
are out of scope and will produce misleading values.
