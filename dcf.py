"""What-to-Buy: FCFF DCF CLI for Indonesian (IDX) listed non-financial stocks.

Run:  uv run dcf.py SIDO
"""

import argparse
import os
import sys

import data_source as ds
import dcf_core as core

DEFAULTS = {
    "risk_free": 0.065,
    "erp": 0.04,
    "terminal_growth": 0.025,
    "horizon": 5,
    "growth": 0.08,
}

RANGES = {
    "risk_free": (0.05, 0.09),
    "erp": (0.03, 0.10),
    "terminal_growth": (0.00, 0.06),
    "horizon": (5, 10),
    "growth": (0.00, 0.30),
    "beta": (0.00, 3.00),
}


def _float_in_range(name, lo, hi):
    def check(value):
        try:
            number = float(value)
        except ValueError:
            raise argparse.ArgumentTypeError("{} must be a number".format(name))
        if not lo <= number <= hi:
            raise argparse.ArgumentTypeError(
                "{} must be between {} and {}".format(name, lo, hi))
        return number
    return check


def build_parser():
    parser = argparse.ArgumentParser(
        prog="dcf.py",
        description="FCFF DCF valuation for Indonesian (IDX) non-financial stocks.")
    parser.add_argument("ticker", help="IDX ticker code, e.g. SIDO, TPIA, MAPI")
    parser.add_argument(
        "--risk-free", type=_float_in_range("risk-free", *RANGES["risk_free"]),
        default=DEFAULTS["risk_free"], metavar="RATE",
        help="risk-free rate, e.g. 0.065")
    parser.add_argument(
        "--erp", type=_float_in_range("erp", *RANGES["erp"]),
        default=DEFAULTS["erp"], metavar="RATE",
        help="equity risk premium, e.g. 0.04")
    parser.add_argument(
        "--growth", type=_float_in_range("growth", *RANGES["growth"]),
        default=None, metavar="RATE",
        help="near-term FCFF growth before fading")
    parser.add_argument(
        "--terminal-growth", type=_float_in_range("terminal-growth", *RANGES["terminal_growth"]),
        default=DEFAULTS["terminal_growth"], metavar="RATE",
        help="terminal (Gordon) growth")
    parser.add_argument(
        "--horizon", type=int, choices=range(5, 11),
        default=DEFAULTS["horizon"], metavar="YEARS",
        help="forecast horizon in years, 5-10 (default 5)")
    parser.add_argument(
        "--beta", type=_float_in_range("beta", *RANGES["beta"]), default=None,
        metavar="BETA", help="override the estimated beta")
    parser.add_argument(
        "--input", metavar="FILE.json",
        help="manual financials JSON (data/{TICKER}.json after first run)")
    parser.add_argument(
        "--mid-year", action="store_true",
        help="use the mid-year discounting convention")
    parser.add_argument(
        "--no-cache", action="store_true",
        help="bypass the local data cache")
    return parser


def build_context(args):
    """Fetch data and compute the full valuation chain. Returns a context dict."""
    warnings = []
    ticker = args.ticker.upper()
    use_cache = not args.no_cache

    if args.input:
        financials = ds.load_financials_json(args.input)
    else:
        financials = ds.fetch_financials(ticker, use_cache)
        missing = ds.missing_fields(financials)
        if missing:
            os.makedirs("data", exist_ok=True)
            path = os.path.join("data", ticker + ".json")
            financials["ticker"] = ticker
            ds.write_template(financials, path)
            raise ds.DataSourceError(
                "statements for {} are incomplete (missing: {}).\n"
                "  A pre-filled template was written to {}.\n"
                "  Fill it from the company's published financials, then re-run:\n"
                "    uv run dcf.py {} --input {}".format(
                    ticker, ", ".join(missing), path, ticker, path))
    financials.setdefault("ticker", ticker)

    missing = ds.missing_fields(financials)
    if missing:
        raise ds.DataSourceError(
            "financials missing required fields: {}.\n"
            "  Provide them via --input (see data/{}.json).".format(", ".join(missing), ticker))

    price = financials.get("price")
    if price is None:
        try:
            price = ds.fetch_price(ticker, use_cache)
        except ds.DataSourceError as exc:
            raise ds.DataSourceError(
                "could not fetch price for {}: {}\n"
                "  Add \"price\" to your --input file to run offline.".format(ticker, exc))

    beta = args.beta if args.beta is not None else financials.get("beta")
    if beta is None:
        try:
            beta = ds.fetch_beta(ticker, use_cache)
        except ds.DataSourceError:
            beta = None
        if beta is None:
            beta = 1.0
            warnings.append("beta estimate unavailable; using 1.0 (override with --beta)")

    shares = financials["shares_outstanding"]
    market_cap = price * shares
    risk_free = args.risk_free
    erp = args.erp
    terminal_growth = args.terminal_growth
    horizon = args.horizon
    mid_year = args.mid_year
    growth = args.growth if args.growth is not None else DEFAULTS["growth"]

    cost_equity = core.cost_of_equity(risk_free, beta, erp)

    debt = (financials.get("short_term_debt") or 0) + (financials.get("long_term_debt") or 0)
    if debt > 0 and financials.get("interest_expense"):
        cost_debt = financials["interest_expense"] / debt
    elif debt > 0:
        cost_debt = risk_free + 0.02
        warnings.append(
            "interest expense missing; assuming cost of debt = Rf + 2% ({:.2%})".format(cost_debt))
    else:
        cost_debt = 0.0

    if financials.get("tax_expense") is None or financials.get("pre_tax_income") is None:
        tax_rate = core.MAX_TAX_RATE
        warnings.append("tax inputs missing; using statutory {:.0%}".format(tax_rate))
    else:
        tax_rate = core.effective_tax_rate(financials["tax_expense"], financials["pre_tax_income"])
        if tax_rate == 0 and financials["pre_tax_income"] > 0:
            warnings.append("effective tax rate is 0% (loss year or missing tax data)")

    wacc = core.wacc(market_cap, debt, cost_equity, cost_debt, tax_rate)

    nwc_curr = financials["current_assets"] - financials["current_liabilities"]
    if (financials.get("current_assets_prev") is not None
            and financials.get("current_liabilities_prev") is not None):
        nwc_prev = financials["current_assets_prev"] - financials["current_liabilities_prev"]
    else:
        nwc_prev = nwc_curr
        warnings.append("prior-year working capital missing; treating working-capital change as 0")

    base_fcff = core.fcff(
        financials["ebit"], tax_rate, financials["depreciation"], financials["capex"],
        nwc_prev, nwc_curr)

    projected = core.project_fcff(base_fcff, growth, terminal_growth, horizon)
    valuation = core.dcf_valuation(projected, wacc, terminal_growth, mid_year)
    net_debt = debt - (financials.get("cash") or 0)
    equity = core.equity_value(valuation["enterprise_value"], net_debt)
    fair_value = core.fair_value_per_share(equity, shares)
    upside = core.upside(fair_value, price)

    return {
        "ticker": ticker,
        "source": financials.get("source"),
        "fiscal_year": financials.get("fiscal_year"),
        "revenue": financials.get("revenue"),
        "price": price,
        "shares": shares,
        "market_cap": market_cap,
        "beta": beta,
        "risk_free": risk_free,
        "erp": erp,
        "cost_equity": cost_equity,
        "cost_debt": cost_debt,
        "tax_rate": tax_rate,
        "wacc": wacc,
        "growth": growth,
        "terminal_growth": terminal_growth,
        "horizon": horizon,
        "mid_year": mid_year,
        "debt": debt,
        "net_debt": net_debt,
        "base_fcff": base_fcff,
        "projected": projected,
        "valuation": valuation,
        "equity": equity,
        "fair_value": fair_value,
        "upside": upside,
        "warnings": warnings,
    }


def _fmt_idr(value):
    """Compact IDR formatting: triliun (T) / miliar (B) / juta (M)."""
    if value is None:
        return "-"
    magnitude = abs(value)
    for suffix, divisor in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if magnitude >= divisor:
            return "{:,.1f}{}".format(value / divisor, suffix)
    return "{:,.0f}".format(value)


def _verdict(upside):
    if upside > 0.15:
        return "UNDERVALUED"
    if upside < -0.15:
        return "OVERVALUED"
    return "FAIRLY VALUED"


def print_projection(ctx):
    """Year-by-year FCFF projection with PV at WACC."""
    print("\nFCFF projection (IDR)")
    print("  {:>3}  {:>7}  {:>12}  {:>12}".format("Yr", "Growth", "FCFF", "PV"))
    for i, (growth, fcff, pv) in enumerate(
            zip(core.growth_schedule(ctx["growth"], ctx["terminal_growth"], ctx["horizon"]),
                ctx["projected"], ctx["valuation"]["pv_years"]), start=1):
        print("  {:>3}  {:>7.2%}  {:>12}  {:>12}".format(
            i, growth, _fmt_idr(fcff), _fmt_idr(pv)))


def print_sensitivity(ctx):
    """Fair value per share across a WACC x terminal-growth grid."""
    wacc_labels, growth_labels, rows = core.sensitivity_grid(
        ctx["base_fcff"], ctx["growth"], ctx["horizon"], ctx["net_debt"], ctx["shares"],
        ctx["wacc"], 0.01, ctx["terminal_growth"], 0.005, steps=3)
    print("\nSensitivity: fair value / share (IDR)")
    header = "  WACC \\ g  | " + " | ".join("{:>10}".format("{:.2%}".format(g)) for g in growth_labels)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for wacc, row in zip(wacc_labels, rows):
        cells = " | ".join(
            "{:>10}".format("-" if value is None else "{:,.0f}".format(value)) for value in row)
        print("  {:>9} | {}".format("{:.2%}".format(wacc), cells))


def print_report(ctx):
    """Print the market data, assumptions, valuation chain, and verdict."""
    label = ctx["ticker"]
    if ctx.get("fiscal_year"):
        label += " (FY {})".format(ctx["fiscal_year"][:4])
    print("")
    print("=" * 60)
    print("What-to-Buy DCF | {}".format(label))
    print("=" * 60)

    print("\nMarket data")
    print("  {:<26}: {:>20}".format("Price (IDR)", "{:,.2f}".format(ctx["price"])))
    print("  {:<26}: {:>20}".format("Shares outstanding", _fmt_idr(ctx["shares"])))
    print("  {:<26}: {:>20}".format("Market cap", _fmt_idr(ctx["market_cap"])))
    print("  {:<26}: {:>20}".format("Beta (vs IHSG)", "{:.2f}".format(ctx["beta"])))

    print("\nAssumptions")
    print("  {:<26}: {:>20}".format("Risk-free rate", "{:.2%}".format(ctx["risk_free"])))
    print("  {:<26}: {:>20}".format("Equity risk premium", "{:.2%}".format(ctx["erp"])))
    print("  {:<26}: {:>20}".format("Cost of equity (Re)", "{:.2%}".format(ctx["cost_equity"])))
    print("  {:<26}: {:>20}".format("Cost of debt (Rd)", "{:.2%}".format(ctx["cost_debt"])))
    print("  {:<26}: {:>20}".format("Effective tax rate", "{:.2%}".format(ctx["tax_rate"])))
    print("  {:<26}: {:>20}".format("WACC", "{:.2%}".format(ctx["wacc"])))
    print("  {:<26}: {:>20}".format("Near-term growth", "{:.2%}".format(ctx["growth"])))
    print("  {:<26}: {:>20}".format("Terminal growth", "{:.2%}".format(ctx["terminal_growth"])))
    print("  {:<26}: {:>20}".format("Forecast horizon", "{} yr".format(ctx["horizon"])))

    print_projection(ctx)

    v = ctx["valuation"]
    print("\nValuation chain")
    print("  {:<26}: {:>20}".format("PV of projected FCFF", _fmt_idr(sum(v["pv_years"]))))
    print("  {:<26}: {:>20}".format("Terminal value", _fmt_idr(v["terminal_value"])))
    print("  {:<26}: {:>20}".format("PV of terminal value", _fmt_idr(v["terminal_pv"])))
    print("  {:<26}: {:>20}".format("Enterprise value", _fmt_idr(v["enterprise_value"])))
    print("  {:<26}: {:>20}".format("Net debt", _fmt_idr(ctx["net_debt"])))
    print("  {:<26}: {:>20}".format("Equity value", _fmt_idr(ctx["equity"])))
    print("")
    print("  {:<26}: {:>20}".format("Fair value / share", "{:,.2f}".format(ctx["fair_value"])))
    print("  {:<26}: {:>20}".format("Current price", "{:,.2f}".format(ctx["price"])))
    print("  {:<26}: {:>20}".format("Upside / downside", "{:+.2%}".format(ctx["upside"])))
    print("  {:<26}: {:>20}".format("Verdict", _verdict(ctx["upside"])))

    print_sensitivity(ctx)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        context = build_context(args)
    except ds.DataSourceError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1
    print_report(context)
    for warning in context["warnings"]:
        print("\nwarning: {}".format(warning), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
