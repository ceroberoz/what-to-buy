"""Unit tests for What-to-Buy (stdlib unittest, no network).

Run:  uv run python -m unittest
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest

import dcf
import dcf_core as core
import data_source as ds
import screen

SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sample.json")


def assert_almost_list(test_case, actual, expected, places=6):
    test_case.assertEqual(len(actual), len(expected))
    for got, want in zip(actual, expected):
        test_case.assertAlmostEqual(got, want, places=places)


class TestCostOfEquity(unittest.TestCase):
    def test_capm(self):
        self.assertAlmostEqual(core.cost_of_equity(0.065, 1.0, 0.04), 0.105)
        self.assertAlmostEqual(core.cost_of_equity(0.05, 2.0, 0.10), 0.25)


class TestWacc(unittest.TestCase):
    def test_mixed_capital(self):
        self.assertAlmostEqual(core.wacc(800, 200, 0.10, 0.06, 0.22), 0.08936)

    def test_all_equity(self):
        self.assertAlmostEqual(core.wacc(1000, 0, 0.10, 0.06, 0.22), 0.10)

    def test_invalid_weights(self):
        with self.assertRaises(ValueError):
            core.wacc(0, 0, 0.1, 0.06, 0.22)
        with self.assertRaises(ValueError):
            core.wacc(-5, 10, 0.1, 0.06, 0.22)


class TestEffectiveTaxRate(unittest.TestCase):
    def test_normal(self):
        self.assertAlmostEqual(core.effective_tax_rate(100, 1000), 0.10)

    def test_capped_at_statutory(self):
        self.assertAlmostEqual(core.effective_tax_rate(300, 1000), 0.22)

    def test_negative_tax_floored(self):
        self.assertEqual(core.effective_tax_rate(-100, 1000), 0.0)

    def test_loss_year(self):
        self.assertEqual(core.effective_tax_rate(100, -50), 0.0)


class TestFcff(unittest.TestCase):
    def test_formula(self):
        result = core.fcff(1000, 0.22, 100, 150, nwc_prev=200, nwc_curr=250)
        self.assertAlmostEqual(result, 680.0)


class TestGrowthSchedule(unittest.TestCase):
    def test_linear_fade(self):
        assert_almost_list(self, core.growth_schedule(0.08, 0.025, 5),
                           [0.08, 0.06625, 0.0525, 0.03875, 0.025])

    def test_horizon_one(self):
        self.assertEqual(core.growth_schedule(0.08, 0.025, 1), [0.08])

    def test_invalid_horizon(self):
        with self.assertRaises(ValueError):
            core.growth_schedule(0.08, 0.025, 0)


class TestProjectFcff(unittest.TestCase):
    def test_projection(self):
        assert_almost_list(self, core.project_fcff(100, 0.10, 0.0, 3),
                           [110.0, 115.5, 115.5])


class TestDiscountFactor(unittest.TestCase):
    def test_end_year(self):
        self.assertAlmostEqual(core.discount_factor(0.10, 1), 1 / 1.1, places=6)

    def test_mid_year(self):
        self.assertAlmostEqual(core.discount_factor(0.10, 1, mid_year=True), 1.1 ** -0.5, places=6)


class TestTerminalValue(unittest.TestCase):
    def test_gordon(self):
        self.assertAlmostEqual(core.terminal_value(100, 0.03, 0.10), 100 * 1.03 / 0.07)

    def test_g_ge_wacc_rejected(self):
        with self.assertRaises(ValueError):
            core.terminal_value(100, 0.10, 0.10)
        with self.assertRaises(ValueError):
            core.terminal_value(100, 0.12, 0.10)


class TestDcfValuation(unittest.TestCase):
    def test_known_case(self):
        result = core.dcf_valuation([110.0, 115.5, 115.5], 0.10, 0.03)
        expected_pv = 110 / 1.1 + 115.5 / 1.21 + 115.5 / 1.331
        expected_tv = 115.5 * 1.03 / 0.07
        self.assertAlmostEqual(sum(result["pv_years"]), expected_pv, places=6)
        self.assertAlmostEqual(result["terminal_value"], expected_tv, places=6)
        self.assertAlmostEqual(result["terminal_pv"], expected_tv / 1.331, places=6)
        self.assertAlmostEqual(result["enterprise_value"], expected_pv + expected_tv / 1.331, places=6)


class TestEquityValuation(unittest.TestCase):
    def test_equity_value(self):
        self.assertEqual(core.equity_value(2013.0, 20.0), 1993.0)

    def test_fair_value_per_share(self):
        self.assertAlmostEqual(core.fair_value_per_share(100.0, 10.0), 10.0)
        with self.assertRaises(ValueError):
            core.fair_value_per_share(100.0, 0.0)

    def test_upside(self):
        self.assertAlmostEqual(core.upside(110.0, 100.0), 0.10)
        self.assertAlmostEqual(core.upside(90.0, 100.0), -0.10)
        with self.assertRaises(ValueError):
            core.upside(110.0, 0.0)


class TestSensitivityGrid(unittest.TestCase):
    def test_cell_consistency(self):
        labels, growth, rows = core.sensitivity_grid(
            100, 0.05, 3, net_debt=0, shares=10,
            wacc_center=0.10, wacc_step=0.02, g_center=0.04, g_step=0.01, steps=1)
        assert_almost_list(self, labels, [0.08, 0.10, 0.12])
        assert_almost_list(self, growth, [0.03, 0.04, 0.05])
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(len(row) == 3 for row in rows))
        self.assertTrue(all(v is not None for row in rows for v in row))

    def test_none_when_g_ge_wacc(self):
        labels, growth, rows = core.sensitivity_grid(
            100, 0.05, 3, net_debt=0, shares=10,
            wacc_center=0.05, wacc_step=0.01, g_center=0.05, g_step=0.02, steps=1)
        flattened = [v for row in rows for v in row]
        self.assertIn(None, flattened)


class TestMissingFields(unittest.TestCase):
    def test_complete(self):
        complete = {key: 1 for key in ds.REQUIRED_FIELDS}
        self.assertEqual(ds.missing_fields(complete), [])

    def test_missing(self):
        partial = {key: 1 for key in ds.REQUIRED_FIELDS}
        del partial["ebit"]
        partial["depreciation"] = None
        self.assertEqual(ds.missing_fields(partial), ["ebit", "depreciation"])


class TestCliValidation(unittest.TestCase):
    def test_out_of_range_rejected(self):
        with self.assertRaises(SystemExit):
            dcf.build_parser().parse_args(["SIDO", "--risk-free", "0.11"])
        with self.assertRaises(SystemExit):
            dcf.build_parser().parse_args(["SIDO", "--horizon", "12"])


class TestEndToEnd(unittest.TestCase):
    def test_sample_fixture(self):
        args = dcf.build_parser().parse_args([
            "SAMPLE", "--input", SAMPLE,
            "--risk-free", "0.06", "--erp", "0.05",
            "--growth", "0.08", "--terminal-growth", "0.03",
        ])
        ctx = dcf.build_context(args)
        self.assertAlmostEqual(ctx["wacc"], 0.104363636, places=6)
        self.assertAlmostEqual(ctx["base_fcff"], 130000000, places=0)
        self.assertAlmostEqual(ctx["fair_value"], 1993.1762, places=1)
        self.assertAlmostEqual(ctx["upside"], 0.9931762, places=3)

    def test_report_output(self):
        args = dcf.build_parser().parse_args(["SAMPLE", "--input", SAMPLE])
        ctx = dcf.build_context(args)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            dcf.print_report(ctx)
        output = buffer.getvalue()
        self.assertIn("What-to-Buy DCF", output)
        self.assertIn("FCFF projection", output)
        self.assertIn("Sensitivity", output)
        self.assertIn("Verdict", output)


class TestEligibilityRule(unittest.TestCase):
    T0 = 1_000_000_000  # 2001-09-09
    NOW_OLD = T0 + int(10 * 365.25 * 86400)

    def test_old_non_bank_eligible(self):
        ok, reason = screen.eligibility(
            "Consumer Defensive", "Packaged Foods", self.T0, self.NOW_OLD)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_financial_sector_excluded(self):
        ok, reason = screen.eligibility(
            "Financial Services", "Banks - Regional", self.T0, self.NOW_OLD)
        self.assertFalse(ok)
        self.assertIn("Financial Services", reason)

    def test_bank_keyword_in_industry(self):
        ok, reason = screen.eligibility(
            "Consumer Cyclical", "Money Center Banks", self.T0, self.NOW_OLD)
        self.assertFalse(ok)
        self.assertIn("bank", reason.lower())

    def test_listed_under_five_years_excluded(self):
        now = self.T0 + int(4 * 365.25 * 86400)
        ok, reason = screen.eligibility("Consumer Defensive", "Packaged Foods", self.T0, now)
        self.assertFalse(ok)
        self.assertIn("needs > 5", reason)

    def test_exactly_five_years_excluded(self):
        now = self.T0 + int(5 * 365.25 * 86400)
        ok, _ = screen.eligibility("Consumer Defensive", "Packaged Foods", self.T0, now)
        self.assertFalse(ok)


class TestEligibilityWhitelistIO(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.path = os.path.join(self.tmpdir, "eligible.json")

    def test_save_load_round_trip(self):
        entries = {
            "SIDO": {"status": "eligible", "reason": "", "sector": "Consumer Defensive",
                     "industry": "Packaged Foods", "listed": "2013-12-18", "age_years": 12.6},
            "BBRI": {"status": "excluded", "reason": "financial sector: Financial Services",
                     "sector": "Financial Services", "industry": "Banks - Regional",
                     "listed": "2003-11-10", "age_years": 22.8},
        }
        screen.save_eligible(entries, self.path)
        doc = screen.load_eligible(self.path)
        self.assertEqual(doc["tickers"], ["SIDO"])
        self.assertEqual(doc["meta"]["BBRI"]["status"], "excluded")
        self.assertEqual(doc["meta"]["SIDO"]["sector"], "Consumer Defensive")

    def test_load_missing_returns_none(self):
        self.assertIsNone(screen.load_eligible(self.path))


class TestEligibilityCheck(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.path = os.path.join(self.tmpdir, "eligible.json")
        entries = {
            "SIDO": {"status": "eligible", "reason": "", "sector": "Consumer Defensive",
                     "industry": "Packaged Foods", "listed": "2013-12-18", "age_years": 12.6},
            "BBRI": {"status": "excluded", "reason": "financial sector: Financial Services",
                     "sector": "Financial Services", "industry": "Banks - Regional",
                     "listed": "2003-11-10", "age_years": 22.8},
        }
        screen.save_eligible(entries, self.path)
        self._orig_file = screen.ELIGIBLE_FILE
        screen.ELIGIBLE_FILE = self.path

    def tearDown(self):
        screen.ELIGIBLE_FILE = self._orig_file

    def test_eligible_passes(self):
        self.assertIsNone(dcf.eligibility_message("SIDO", screen.load_eligible()))

    def test_excluded_reports_reason(self):
        msg = dcf.eligibility_message("BBRI", screen.load_eligible())
        self.assertIn("skipped: BBRI", msg)
        self.assertIn("Financial Services", msg)

    def test_unknown_ticker_generic_reason(self):
        msg = dcf.eligibility_message("ZZZZ", screen.load_eligible())
        self.assertIn("not on the eligible list", msg)

    def test_main_skips_bank_without_network(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = dcf.main(["BBRI"])
        self.assertEqual(rc, 0)
        self.assertIn("skipped: BBRI", buffer.getvalue())


class TestUniverseMerge(unittest.TestCase):
    T0 = 1_000_000_000  # 2001-09-09
    NOW = T0 + int(10 * 365.25 * 86400)

    def _quote(self, symbol, ts=None):
        quote = {"symbol": symbol}
        if ts is not None:
            quote["firstTradeDateMilliseconds"] = int(ts * 1000)
        return quote

    def test_eligible_added(self):
        merged, added = screen.merge_universe(
            {}, [self._quote("AADI.JK", self.T0)], set(), self.NOW)
        self.assertEqual(added, ["AADI"])
        self.assertEqual(merged["AADI"]["status"], "eligible")
        self.assertEqual(merged["AADI"]["listed"], "2001-09-09")

    def test_bank_excluded(self):
        merged, added = screen.merge_universe(
            {}, [self._quote("BBRI.JK", self.T0)], {"BBRI.JK"}, self.NOW)
        self.assertEqual(added, ["BBRI"])
        self.assertEqual(merged["BBRI"]["status"], "excluded")
        self.assertIn("Financial Services", merged["BBRI"]["reason"])

    def test_young_excluded(self):
        young_ts = self.NOW - int(2 * 365.25 * 86400)
        merged, _ = screen.merge_universe(
            {}, [self._quote("AADI.JK", young_ts)], set(), self.NOW)
        self.assertEqual(merged["AADI"]["status"], "excluded")
        self.assertIn("needs > 5", merged["AADI"]["reason"])

    def test_missing_first_trade_is_no_data(self):
        merged, _ = screen.merge_universe({}, [self._quote("XXXX.JK")], set(), self.NOW)
        self.assertEqual(merged["XXXX"]["status"], "no_data")

    def test_existing_entry_preserved(self):
        existing = {"SIDO": {"status": "eligible", "reason": "",
                             "sector": "Consumer Defensive", "industry": "Packaged Foods",
                             "listed": "2013-12-18", "age_years": 12.6}}
        quotes = [self._quote("SIDO.JK", self.T0), self._quote("TPIA.JK", self.T0)]
        merged, added = screen.merge_universe(existing, quotes, set(), self.NOW)
        self.assertEqual(merged["SIDO"], existing["SIDO"])
        self.assertEqual(added, ["TPIA"])
        self.assertEqual(merged["TPIA"]["status"], "eligible")

    def test_empty_universe(self):
        merged, added = screen.merge_universe({"SIDO": {"status": "eligible"}}, [], set(), self.NOW)
        self.assertEqual(merged, {"SIDO": {"status": "eligible"}})
        self.assertEqual(added, [])


if __name__ == "__main__":
    unittest.main()
