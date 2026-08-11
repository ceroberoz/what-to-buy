"""Pure DCF math for the What-to-Buy valuator.

Every function here is side-effect free so it can be unit-tested without a
network. Units are raw IDR unless noted.
"""

MAX_TAX_RATE = 0.22  # Indonesian statutory corporate income tax rate


def cost_of_equity(risk_free, beta, erp):
    """Capital Asset Pricing Model cost of equity: Re = Rf + beta * ERP."""
    return risk_free + beta * erp


def wacc(equity_value, debt_value, cost_equity, cost_debt, tax_rate):
    """Weighted average cost of capital.

    WACC = E/V * Re + D/V * Rd * (1 - tax), with V = E + D.
    Uses market-value equity and book interest-bearing debt.
    """
    total = equity_value + debt_value
    if total <= 0:
        raise ValueError("equity_value + debt_value must be positive")
    if equity_value < 0 or debt_value < 0:
        raise ValueError("equity_value and debt_value must be non-negative")
    we = equity_value / total
    wd = debt_value / total
    return we * cost_equity + wd * cost_debt * (1 - tax_rate)


def effective_tax_rate(tax_expense, pre_tax_income):
    """Effective tax rate, floored at 0 and capped at the statutory 22%."""
    if pre_tax_income <= 0:
        return 0.0
    rate = tax_expense / pre_tax_income
    return max(0.0, min(rate, MAX_TAX_RATE))


def fcff(ebit, tax_rate, depreciation, capex, nwc_prev, nwc_curr):
    """Free cash flow to firm.

    FCFF = EBIT * (1 - tax) + D&A - CAPEX - (NWC_curr - NWC_prev).
    """
    return ebit * (1 - tax_rate) + depreciation - capex - (nwc_curr - nwc_prev)


def project_fcff(base_fcff, near_growth, terminal_growth, horizon):
    """Project FCFF over the forecast horizon.

    Growth starts at near_growth in year 1 and fades linearly to
    terminal_growth in the final year. Returns a list of `horizon` values.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    out = []
    value = base_fcff
    for i in range(1, horizon + 1):
        if horizon == 1:
            growth = near_growth
        else:
            growth = near_growth + (terminal_growth - near_growth) * (i - 1) / (horizon - 1)
        value = value * (1 + growth)
        out.append(value)
    return out


def discount_factor(wacc, year, mid_year=False):
    """PV factor 1/(1+wacc)^t; t = year - 0.5 under the mid-year convention."""
    if wacc < 0:
        raise ValueError("wacc must be non-negative")
    if year < 1:
        raise ValueError("year must be >= 1")
    t = year - 0.5 if mid_year else year
    return (1 + wacc) ** -t


def terminal_value(terminal_fcff, terminal_growth, wacc):
    """Gordon growth terminal value; requires g < WACC."""
    if terminal_growth >= wacc:
        raise ValueError("terminal_growth must be < wacc for a finite terminal value")
    return terminal_fcff * (1 + terminal_growth) / (wacc - terminal_growth)


def dcf_valuation(projected_fcff, wacc, terminal_growth, mid_year=False):
    """Discount projected FCFF plus Gordon terminal value at WACC.

    Returns a dict: pv_years (list), terminal_value, terminal_pv,
    enterprise_value.
    """
    years = list(range(1, len(projected_fcff) + 1))
    pv_years = [v * discount_factor(wacc, y, mid_year) for v, y in zip(projected_fcff, years)]
    tv = terminal_value(projected_fcff[-1], terminal_growth, wacc)
    tv_pv = tv * discount_factor(wacc, len(projected_fcff), mid_year)
    return {
        "pv_years": pv_years,
        "terminal_value": tv,
        "terminal_pv": tv_pv,
        "enterprise_value": sum(pv_years) + tv_pv,
    }


def equity_value(enterprise_value, net_debt):
    """Equity = EV - net debt, where net debt = interest-bearing debt - cash."""
    return enterprise_value - net_debt


def fair_value_per_share(equity, shares_outstanding):
    if shares_outstanding <= 0:
        raise ValueError("shares_outstanding must be positive")
    return equity / shares_outstanding


def upside(fair_value, current_price):
    """Upside/downside vs current price; positive means undervalued."""
    if current_price <= 0:
        raise ValueError("current_price must be positive")
    return fair_value / current_price - 1


def sensitivity_grid(base_fcff, near_growth, horizon, net_debt, shares,
                     wacc_center, wacc_step, g_center, g_step, steps=3):
    """Fair value per share across a WACC x terminal-growth grid.

    Returns (wacc_labels, growth_labels, rows) where rows[i][j] is the fair
    value per share at wacc_labels[i] and growth_labels[j].
    """
    wacc_labels = [wacc_center + i * wacc_step for i in range(-steps, steps + 1)]
    growth_labels = [g_center + j * g_step for j in range(-steps, steps + 1)]
    rows = []
    for w in wacc_labels:
        row = []
        for g in growth_labels:
            try:
                proj = project_fcff(base_fcff, near_growth, g, horizon)
                ev = dcf_valuation(proj, w, g, mid_year=False)["enterprise_value"]
                row.append(fair_value_per_share(equity_value(ev, net_debt), shares))
            except ValueError:
                row.append(None)  # g >= wacc has no finite terminal value
        rows.append(row)
    return wacc_labels, growth_labels, rows
