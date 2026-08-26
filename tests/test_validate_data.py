import unittest

from scripts.validate_data import DataValidator


def make_valuation_fixture():
    """构造一个币种统一、半年披露TTM可复核的最小估值样例。"""
    return {
        "schema_version": "V5.5.24.3",
        "analysis_metadata": {
            "valuation_policy": {
                "primary_method": "PE",
                "pe_applicable": True,
                "price_as_of": "2026-08-20",
                "fx_as_of": "2026-08-20",
                "calculation_currency": "RMB",
                "share_price_to_calculation_currency_rate": 0.9,
                "fx_source": "official_fx_source",
                "ttm_period": "2025-07-01/2026-06-30",
                "ttm_method": "ANNUAL_PLUS_INTERIM",
                "ttm_unavailable_reason": "",
            }
        },
        "core_financial_data": {
            "cash_and_bank_balances": {"value": 100, "unit": "RMB"},
            "cash_and_cash_equivalents": {"value": 80, "unit": "RMB"},
            "related_financial_institution_deposits": {
                "value": 5,
                "included_in_cash_and_cash_equivalents": True,
            },
            "other_low_liquidity_cash": {"value": 2},
            "restricted_cash": {"value": 10},
            "interest_bearing_debt": {
                "short_term": {"value": 10},
                "long_term": {"value": 5},
                "bonds": {"value": 0},
                "lease_liabilities": {"value": 5},
            },
            "revenue": {"value": 500, "unit": "RMB"},
            "net_profit": {"value": 95, "unit": "RMB"},
            "net_profit_attributable": {"value": 90, "unit": "RMB"},
            "operating_cash_flow": {"value": 150, "unit": "RMB"},
            "capex": {"value": 50, "unit": "RMB"},
            "total_shares": {"value": 100},
            "share_price": {"value": 10, "currency": "HKD"},
            "dividend_per_share_for_yield": {"value": 0.5, "currency": "HKD"},
            "market_cap": {"value": 900, "unit": "RMB"},
            "ttm_components": [
                {
                    "role": "latest_annual",
                    "period": "2025FY",
                    "operator": 1,
                    "value": 90,
                    "unit": "RMB",
                    "source": "annual_report",
                    "page_number": 10,
                },
                {
                    "role": "current_interim",
                    "period": "2026H1",
                    "operator": 1,
                    "value": 50,
                    "unit": "RMB",
                    "source": "interim_report",
                    "page_number": 8,
                },
                {
                    "role": "prior_interim",
                    "period": "2025H1",
                    "operator": -1,
                    "value": 40,
                    "unit": "RMB",
                    "source": "interim_report",
                    "page_number": 8,
                },
            ],
            "calculated_metrics": {
                "immediate_net_cash": {"value": 50, "market_cap_ratio": 50 / 900, "notes": "需保留营运资金"},
                "conservative_immediate_net_cash": {"value": 43, "market_cap_ratio": 43 / 900},
                "net_cash": {"value": 70, "market_cap_ratio": 70 / 900},
                "fcf": {"value": 100},
                "fcf_yield": {"value": 100 / 900},
                "fcf_multiple_market": {"value": 9},
                "fcf_multiple_ex_cash": {"value": 8.3},
                "multi_period_fcf": {
                    "method": "TWO_YEAR_AVERAGE",
                    "periods": [{"period": "2024FY", "value": 90}, {"period": "2025FY", "value": 100}],
                    "average_value": 95,
                    "market_cap_yield": 95 / 900,
                },
                "dividend_yield": {"value": 0.05},
                "static_pe": {"value": 10},
                "ttm_net_profit": {"value": 100},
                "ttm_pe": {"value": 9},
            },
        },
    }


class DataValidatorValuationTests(unittest.TestCase):
    def test_rejects_legacy_schema(self):
        validator = DataValidator({"analysis_metadata": {}, "core_financial_data": {}})
        self.assertFalse(validator._validate_schema_compatibility())
        self.assertTrue(any(error.startswith("[SCHEMA]") for error in validator.errors))

    def test_accepts_half_year_ttm_and_fx_conversion(self):
        validator = DataValidator(make_valuation_fixture())
        validator._validate_valuation_data()
        validator._validate_calculated_metrics()
        self.assertEqual([], validator.errors)

    def test_detects_wrong_static_pe(self):
        data = make_valuation_fixture()
        data["core_financial_data"]["calculated_metrics"]["static_pe"]["value"] = 8
        validator = DataValidator(data)
        validator._validate_calculated_metrics()
        self.assertTrue(any("静态PE错误" in error for error in validator.errors))

    def test_zero_or_negative_metrics_cannot_bypass_presence_check(self):
        data = make_valuation_fixture()
        del data["core_financial_data"]["calculated_metrics"]["net_cash"]["value"]
        validator = DataValidator(data)
        validator._validate_calculated_metrics()
        self.assertTrue(any("必须填写net_cash.value" in error for error in validator.errors))

    def test_cross_currency_rate_cannot_be_one(self):
        data = make_valuation_fixture()
        data["analysis_metadata"]["valuation_policy"]["share_price_to_calculation_currency_rate"] = 1
        validator = DataValidator(data)
        validator._validate_valuation_data()
        self.assertTrue(any("汇率不能填1" in error for error in validator.errors))

    def test_not_available_ttm_requires_reason_and_null_metrics(self):
        data = make_valuation_fixture()
        policy = data["analysis_metadata"]["valuation_policy"]
        policy["ttm_method"] = "NOT_AVAILABLE"
        policy["ttm_unavailable_reason"] = "发行人仅披露年度数据"
        metrics = data["core_financial_data"]["calculated_metrics"]
        metrics["ttm_net_profit"]["value"] = None
        metrics["ttm_pe"]["value"] = None
        validator = DataValidator(data)
        validator._validate_valuation_data()
        self.assertEqual([], validator.errors)

    def test_reit_can_mark_generic_fcf_not_applicable(self):
        data = make_valuation_fixture()
        policy = data["analysis_metadata"]["valuation_policy"]
        policy["fcf_applicable"] = False
        policy["fcf_unavailable_reason"] = "REIT使用DPU/可分派收入和NAV估值"
        core = data["core_financial_data"]
        core["operating_cash_flow"]["value"] = None
        core["capex"]["value"] = None
        metrics = core["calculated_metrics"]
        metrics["fcf"]["value"] = None
        metrics["fcf_yield"]["value"] = None
        metrics["fcf_multiple_market"]["value"] = None
        metrics["fcf_multiple_ex_cash"]["value"] = None
        metrics["multi_period_fcf"] = {
            "method": "NOT_AVAILABLE",
            "unavailable_reason": policy["fcf_unavailable_reason"],
        }
        validator = DataValidator(data)
        validator._validate_cashflow_data()
        validator._validate_calculated_metrics()
        self.assertEqual([], validator.errors)

    def test_large_goodwill_impairment_requires_profit_bridge(self):
        data = make_valuation_fixture()
        data["core_financial_data"]["impairment_breakdown"] = {
            "total": {"value": 20},
            "direction_flip_after_adjustment": True,
            "items": [{"type": "goodwill", "amount": 20}],
        }
        validator = DataValidator(data)
        validator._validate_profit_quality()
        self.assertTrue(any("bridge_required" in error for error in validator.errors))

    def test_inventory_impairment_cannot_be_added_back(self):
        data = make_valuation_fixture()
        core = data["core_financial_data"]
        core["impairment_breakdown"] = {
            "total": {"value": 20},
            "items": [{
                "type": "inventory", "amount": 20,
                "source": "interim_report", "page_number": 20,
            }],
        }
        core["profit_quality"] = {
            "bridge_required": True,
            "reported_profit": {"value": 90},
            "normalized_profit": {"value": 110},
            "normalized_ttm_profit": {"value": 120},
            "normalized_ttm_pe": {"value": 7.5},
            "adjustment_items": [{
                "type": "inventory", "amount": 20, "after_tax_amount": 20,
                "attributable_amount": 20, "cash_impact": "future_risk",
                "recurring": True, "add_back_allowed": True,
                "rationale": "非现金", "remaining_exposure": "仍有库存",
                "source": "interim_report", "page_number": 20,
            }],
            "conclusion": "错误示例",
        }
        validator = DataValidator(data)
        validator._validate_profit_quality()
        self.assertTrue(any("inventory" in error for error in validator.errors))

    def test_credit_chain_requires_base_and_downside_scenarios(self):
        data = make_valuation_fixture()
        data["credit_chain"] = {
            "triggered": True,
            "related_party_loans": {
                "value": 100, "direction": "outbound",
                "source": "annual_report", "page_number": 30,
            },
            "implicit_support": {"exists": True, "rationale": "维持控制权"},
            "funding_cost_assessment": "融资成本较低",
            "solvency_and_cutoff_assessment": "不能无损切割",
            "stress_test_completed": True,
            "stress_scenarios": [{
                "scenario": "base", "expected_support_loss": 10,
                "impact_on_net_cash_fcf_dividend": "可由一期FCF覆盖",
            }],
            "conclusion": "存在连带经营风险",
        }
        validator = DataValidator(data)
        validator._validate_credit_chain()
        self.assertTrue(any("downside" in error for error in validator.errors))


if __name__ == "__main__":
    unittest.main()
