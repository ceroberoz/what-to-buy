# What-to-Buy

A terminal-first FCFF DCF valuator for **Indonesian (IDX) listed, non-financial stocks**.

Given a ticker (e.g. `SIDO`, `TPIA`, `MAPI`), it computes an intrinsic value per share by
discounting **Free Cash Flow to Firm (FCFF)** at a **WACC**, and compares it with the current
price to show potential upside.

Built with **only the Python standard library** (zero third-party packages).

> **Disclaimer**: For educational/investment-research purposes only. Figures are best-effort
> reconstructions from public sources. Not investment advice. Financial-sector stocks (banks,
> insurers) are out of scope and will produce misleading values.

---

## Requirements

- Python 3.9+
- Optional: [uv](https://docs.astral.sh/uv/) (preferred runner)

## Usage

```bash
# Preferred (uv):
uv run dcf.py SIDO

# Fallback (plain Python):
python3 dcf.py SIDO
```

### Adjustable assumptions (with defaults)

| Flag | Default | Allowed range | Meaning |
|------|---------|---------------|---------|
| `--risk-free` | `0.065` | 0.05 – 0.09 | Risk-free rate |
| `--erp` | `0.04` | 0.03 – 0.10 | Equity risk premium |
| `--terminal-growth` | `0.025` | 0.00 – 0.06 | Long-run FCFF growth (Gordon g) |
| `--horizon` | `5` | 5 – 10 | Forecast horizon (years) |
| `--growth` | auto | 0 – 0.30 | Near-term FCFF growth (default: historical CAGR) |
| `--beta` | auto | 0 – 3 | Override estimated beta |
| `--mid-year` | off | – | Mid-year discounting convention |
| `--input FILE.json` | – | – | Manual data file (fallback when scraping fails) |
| `--no-cache` | off | – | Bypass the local data cache |

### Examples

```bash
uv run dcf.py TPIA --risk-free 0.065 --erp 0.04 --terminal-growth 0.03
uv run dcf.py MAPI --horizon 8 --beta 1.2
uv run dcf.py SIDO --input data/sido.json
```

### Tests

```bash
uv run python -m unittest
```

---

## Methodology

1. **Current price**: Yahoo Finance chart API (`{TICKER}.JK`).
2. **Financials (IDR)**: scraped from `idnfinancials.com` (income / balance / cash-flow),
   falling back to a user-supplied JSON file.
3. **Beta**: regression of monthly stock returns against IHSG (`^JKSE`); defaults to 1.0 with a
   warning if insufficient history.
4. **WACC**:
   - `Re = Rf + β × ERP`
   - `Rd = interest expense / interest-bearing debt`
   - `WACC = (E/V)·Re + (D/V)·Rd·(1 − tax)`, with market-cap and book-debt weights
5. **FCFF**: `EBIT·(1 − tax) + D&A − CAPEX − ΔNWC`, tax capped at the 22% Indonesian statutory rate.
6. **Projection**: near-term `--growth` fades linearly to `--terminal-growth` over the horizon.
7. **Terminal value**: Gordon growth `FCFF_N·(1+g)/(WACC−g)`.
8. **Per share**: equity value = EV − net debt; fair value = equity / shares outstanding.

## Project layout

```
what-to-buy/
├── PLAN.md          # feature-tracking plan (one commit per task)
├── README.md
├── pyproject.toml
├── dcf.py           # CLI entry point
├── dcf_core.py      # pure DCF math
├── data_source.py   # Yahoo + idnfinancials retrieval
└── test_dcf.py      # stdlib unittest
```

Progress is tracked task-by-task in `PLAN.md`, with one git commit per task.
