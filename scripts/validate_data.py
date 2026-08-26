#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据质量硬校验脚本（对应模板 V5.5.24-r5）
必须在生成报告前运行并通过

使用方法：
    python scripts/validate_data.py config/validation_03613.yaml
    
返回码：
    0 - 校验通过，可以生成报告
    1 - 校验失败，必须修正数据错误
    2 - 校验通过但有警告，建议复核
"""

import sys
import yaml
import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path


@dataclass
class ValidationResult:
    """校验结果"""
    passed: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class DataValidator:
    """数据硬校验器"""

    CURRENT_SCHEMA_VERSION = "V5.5.24.3"
    
    def __init__(self, data: Dict[str, Any]):
        self.data = data
        self.result = ValidationResult()
        self.errors = []
        self.warnings = []
    
    def validate_all(self) -> ValidationResult:
        """执行所有校验"""
        print("=" * 60)
        print("[VALIDATION] 开始数据质量硬校验")
        print("=" * 60)

        # 先拦截旧版/错误结构，避免后续校验出现难以理解的AttributeError
        if not self._validate_schema_compatibility():
            self.result.errors = self.errors
            self.result.warnings = self.warnings
            self.result.passed = False
            return self.result
        
        # 1. 元数据校验
        self._validate_metadata()
        
        # 2. 现金数据校验（S级）
        self._validate_cash_data()
        
        # 3. 负债数据校验（S级）
        self._validate_debt_data()
        
        # 4. 利润数据校验（S级）
        self._validate_profit_data()

        # 4.2 大额减值与正常化利润桥接（V5.5.24-r5）
        self._validate_profit_quality()

        # 4.3 关联融资与信用链压力测试（V5.5.24-r5）
        self._validate_credit_chain()

        # 4.5 估值适用性与TTM时点校验（V5.5.23延续）
        self._validate_valuation_data()
        
        # 5. 现金流数据校验（S级）
        self._validate_cashflow_data()
        
        # 6. 股本数据校验（S级）
        self._validate_share_data()

        # 6.5 股东关系、双创板边界和历史价格锚校验（V5.5.24）
        self._validate_shareholder_relationship()
        
        # 7. 计算指标校验
        self._validate_calculated_metrics()
        
        # 8. 历史对比校验
        self._validate_historical_comparison()
        
        # 9. 交叉验证
        self._validate_cross_checks()
        
        # 10. 检查清单校验
        self._validate_checklist()
        
        # 11. 确认声明校验
        self._validate_confirmation()
        
        # 汇总结果
        self.result.errors = self.errors
        self.result.warnings = self.warnings
        self.result.passed = len(self.errors) == 0
        
        return self.result

    def _validate_schema_compatibility(self) -> bool:
        """确认输入使用当前YAML结构；旧版文件给出迁移提示而不是直接崩溃。"""
        schema_version = self.data.get('schema_version')
        if schema_version != self.CURRENT_SCHEMA_VERSION:
            self.errors.append(
                f"[SCHEMA] 需要schema_version={self.CURRENT_SCHEMA_VERSION}，"
                f"当前为{schema_version or '未标注'}。请基于当前模板迁移，禁止把旧校验文件当作已通过。"
            )
            return False

        if 'analysis_metadata' not in self.data or 'core_financial_data' not in self.data:
            self.errors.append(
                "[SCHEMA] 输入文件不是当前数据校验结构。请从 "
                "config/data_validation_template.yaml 重新复制，旧版 basic_info/data_sources 需迁移。"
            )
            return False

        core = self.data.get('core_financial_data')
        if not isinstance(core, dict):
            self.errors.append("[SCHEMA] core_financial_data必须是对象")
            return False

        return True
    
    def _validate_metadata(self):
        """校验元数据"""
        print("\n[1] 元数据校验")
        
        meta = self.data.get('analysis_metadata', {})
        
        required_fields = [
            'stock_code',
            'stock_name',
            'annual_report_year',
            'listing_board',
            'workflow_status',
            'shareholder_relationship',
        ]
        for field in required_fields:
            if not meta.get(field):
                self.errors.append(f"[METADATA] 缺少必填字段: {field}")
        
        # 检查是否使用年报
        checks = meta.get('validation_checks', [])
        for check in checks:
            if not check.get('checked', False):
                self.errors.append(f"[METADATA] 未勾选确认: {check.get('check', '')}")
        
        # 时效性校验（新增）
        self._validate_data_freshness(meta)

        if not any(e for e in self.errors if e.startswith('[METADATA]')):
            print("   [PASS] 元数据校验通过")

    def _validate_shareholder_relationship(self):
        """校验资本市场养分测试、双创板调用边界和历史价格锚。"""
        print("\n[6.5] 股东关系与上市板块边界校验（V5.5.24）")

        meta = self.data.get('analysis_metadata', {})
        nutrient = self.data.get('capital_market_nutrient_test', {})
        listing_board = meta.get('listing_board', '')
        workflow_status = meta.get('workflow_status', '')
        relationship = meta.get('shareholder_relationship', '')
        valuation_policy = meta.get('valuation_policy', {})

        allowed_boards = {'港股主板', 'A股主板', '科创板', '创业板', '其他'}
        allowed_statuses = {'排除', '独立高风险研究', '标准分析'}
        allowed_relationships = {'公司养股东', '相互供养', '股东养公司', '资本退出工具'}

        if listing_board not in allowed_boards:
            self.errors.append(f"[BOARD] 不支持的上市板块: {listing_board}")
        if workflow_status not in allowed_statuses:
            self.errors.append(f"[BOARD] 不支持的流程状态: {workflow_status}")
        if relationship not in allowed_relationships:
            self.errors.append(f"[NUTRIENT] 不支持的股东关系标签: {relationship}")

        if listing_board in {'科创板', '创业板'}:
            if workflow_status == '标准分析':
                self.errors.append("[BOARD] 科创板/创业板不得进入防御型价值投资标准流程")
            if workflow_status == '独立高风险研究' and not meta.get('explicit_high_risk_request', False):
                self.errors.append("[BOARD] 双创板独立高风险研究必须有用户明确请求")
            if workflow_status == '独立高风险研究' and not nutrient.get('full_test_required', False):
                self.errors.append("[NUTRIENT] 科创板/创业板必须完成完整资本市场养分测试")

        if relationship in {'股东养公司', '资本退出工具'} and workflow_status == '标准分析':
            self.errors.append(f"[NUTRIENT] {relationship}不得进入标准分析流程")

        if nutrient.get('classification') != relationship:
            self.errors.append("[NUTRIENT] 养分测试分类与元数据股东关系标签不一致")

        if not nutrient.get('classification_basis'):
            self.errors.append("[NUTRIENT] 必须填写股东关系标签的量化判断依据classification_basis")
        if not nutrient.get('summary_source'):
            self.errors.append("[NUTRIENT] 简版养分测试也必须填写summary_source")

        if valuation_policy.get('primary_method') == 'PS' and not nutrient.get('full_test_required', False):
            self.errors.append("[NUTRIENT] 以PS为主估值方法的成长股必须完成完整资本市场养分测试")

        if nutrient.get('full_test_required', False):
            if not nutrient.get('test_period'):
                self.errors.append("[NUTRIENT] 完整养分测试必须填写统计区间")

            required_source_fields = [
                'cumulative_equity_financing',
                'cumulative_dividends_and_net_buybacks',
                'diluted_share_count_cagr',
                'cumulative_operating_cash_flow',
                'cumulative_capex',
                'incremental_roic',
                'fundraising_project_delivery_rate',
                'unlock_and_reduction_pressure',
            ]
            for field_name in required_source_fields:
                field_data = nutrient.get(field_name, {})
                if not isinstance(field_data, dict) or not field_data.get('source'):
                    self.errors.append(f"[NUTRIENT] 完整养分测试缺少来源: {field_name}")

        if not nutrient.get('historical_price_anchor_excluded', False):
            self.errors.append("[VALUATION_ANCHOR] 必须确认历史价格锚未参与内在价值计算")

        if not any(
            e for e in self.errors
            if e.startswith(('[BOARD]', '[NUTRIENT]', '[VALUATION_ANCHOR]'))
        ):
            print("   [PASS] 股东关系与上市板块边界校验通过")
    
    def _validate_data_freshness(self, meta: Dict[str, Any]):
        """校验数据时效性（强化）"""
        freshness = meta.get('data_freshness_control', {})
        report_type = meta.get('report_type', 'annual')
        is_latest_full_year = meta.get('is_latest_full_year', False)

        # 1. 检查是否使用年报
        if report_type != 'annual':
            self.warnings.append("[TIMING] 使用非年报数据（中报/季报），置信度应降级")
            # 如果是中报，检查是否明确标注
            if report_type == 'interim':
                self.warnings.append("[TIMING] [WARNING] 使用中报数据，必须降级置信度为B级")

        # 2. 检查是否是最新年报
        if not is_latest_full_year:
            self.warnings.append("[TIMING] 可能不是最新完整年度年报，请确认")

        # 3. 检查数据时效
        try:
            current_date_str = freshness.get('current_date', '2026-03-22')
            annual_report_date_str = meta.get('annual_report_date', '')

            if annual_report_date_str:
                current_date = datetime.datetime.strptime(current_date_str, '%Y-%m-%d').date()
                annual_report_date = datetime.datetime.strptime(annual_report_date_str, '%Y-%m-%d').date()

                # 计算数据时效天数
                data_age_days = (current_date - annual_report_date).days

                max_allowed = freshness.get('max_allowed_age_days', 365)
                if data_age_days > max_allowed:
                    self.errors.append(
                        f"[TIMING] 数据过时: {data_age_days}天前发布（最大允许{max_allowed}天）"
                    )
                elif data_age_days > 180:  # 超过半年
                    self.warnings.append(
                        f"[TIMING] 数据较旧: {data_age_days}天前发布（建议使用最新数据）"
                    )

                # 检查是否使用上年数据（年报发布日期应在合理范围内）
                annual_report_year = meta.get('annual_report_year', 0)
                if annual_report_year > 0:
                    current_year = current_date.year
                    if annual_report_year < current_year - 1:
                        self.errors.append(
                            f"[TIMING] 年报年份过旧: {annual_report_year}年（当前{current_year}年）"
                        )
        except Exception as e:
            self.warnings.append(f"[TIMING] 日期解析错误: {e}")

        # 4. 检查核心数据一致性（报表期）
        self._validate_report_period_consistency()

    def _validate_report_period_consistency(self):
        """校验所有核心数据的报表期是否一致"""
        core = self.data.get('core_financial_data', {})

        # 收集所有报表期
        periods = []

        cash_period = core.get('cash_and_bank_balances', {}).get('report_period')
        if cash_period:
            periods.append(("现金", cash_period))

        # 检查负债数据报表期
        debt = core.get('interest_bearing_debt', {})
        for comp in ['short_term', 'long_term', 'bonds', 'lease_liabilities']:
            comp_data = debt.get(comp, {})
            period = comp_data.get('report_period')
            if period:
                periods.append((f"负债-{comp}", period))

        # 检查利润数据报表期
        for item in ['revenue', 'net_profit', 'net_profit_attributable']:
            item_data = core.get(item, {})
            period = item_data.get('report_period')
            if period:
                periods.append((item, period))

        # 检查现金流数据报表期
        for item in ['operating_cash_flow', 'capex']:
            item_data = core.get(item, {})
            period = item_data.get('report_period')
            if period:
                periods.append((item, period))

        # 检查所有报表期是否一致
        if periods:
            unique_periods = set(period for _, period in periods)
            if len(unique_periods) > 1:
                self.errors.append(
                    f"[TIMING] 核心数据报表期不一致: {unique_periods}"
                )
            else:
                print(f"   [PASS] 核心数据报表期一致: {list(unique_periods)[0]}")

    def _validate_cash_data(self):
        """校验现金数据（S级强制）"""
        meta = self.data.get('analysis_metadata', {})
        report_type = meta.get('report_type', 'annual')
        level_label = "S级" if report_type == 'annual' else "B级"
        print(f"\n[2] 现金数据校验（{level_label}）")

        core = self.data.get('core_financial_data', {})
        cash = core.get('cash_and_bank_balances', {})
        cash_equivalents = core.get('cash_and_cash_equivalents', {})

        # 检查置信度（中报数据允许B级）
        expected_confidence = 'S' if report_type == 'annual' else 'B'
        if cash.get('confidence') != expected_confidence:
            if report_type == 'annual':
                self.errors.append("[CASH] 现金数据必须是S级（年报原文）")
            else:
                self.errors.append(f"[CASH] 中报/季报数据必须是B级（当前：{cash.get('confidence', '未标注')}）")

        # 检查来源
        source = cash.get('source', '')
        if report_type == 'annual':
            # 年报数据必须来自年报原文
            if not source or 'annual_report' not in source:
                self.errors.append("[CASH] 现金数据必须来自年报原文（source字段必须包含annual_report）")
        else:
            # 中报/季报数据必须来自相应报告
            if not source or ('interim_report' not in source and 'quarter_report' not in source):
                self.errors.append("[CASH] 非年报数据必须标注来源（source字段应包含interim_report或quarter_report）")
        
        # 检查页码
        if not cash.get('page_number') or cash.get('page_number') == 0:
            self.errors.append("[CASH] 必须标注现金数据的年报页码")
        
        # 检查单位
        if cash.get('unit') not in ['HKD', 'RMB']:
            self.errors.append("[CASH] 现金单位必须是HKD或RMB")
        
        # 检查数值合理性（避免单位错误）
        value = cash.get('value', 0)
        if value == 0:
            self.warnings.append("[CASH] 现金为0，请确认是否填写")
        elif value < 1000000:  # 小于100万
            self.warnings.append(f"[CASH] 现金数值{value}较小，请确认单位是否正确（应为元而非万元/亿元）")
        
        # 检查确认勾选
        if not cash.get('verification_checked', False):
            self.errors.append("[CASH] 必须勾选确认现金数据已核查")

        # 即时流动性口径必须与广义现金分开
        if 'value' not in cash_equivalents:
            self.errors.append("[CASH] 必须填写cash_and_cash_equivalents.value")
        if cash_equivalents.get('confidence') != expected_confidence:
            self.errors.append("[CASH] 现金及现金等价物置信度必须与报告类型匹配")
        if not cash_equivalents.get('source'):
            self.errors.append("[CASH] 现金及现金等价物必须标注来源")
        if not cash_equivalents.get('page_number'):
            self.errors.append("[CASH] 现金及现金等价物必须标注页码")
        if cash_equivalents.get('unit') not in ['HKD', 'RMB']:
            self.errors.append("[CASH] 现金及现金等价物单位必须是HKD或RMB")
        if not cash_equivalents.get('verification_checked', False):
            self.errors.append("[CASH] 必须勾选确认现金及现金等价物已核查")
        if not cash_equivalents.get('notes'):
            self.errors.append("[CASH] 必须说明现金及现金等价物是否含受限现金和关联方财务公司存款")

        for field in [
            'time_deposits_over_three_months',
            'related_financial_institution_deposits',
            'other_low_liquidity_cash',
        ]:
            if 'value' not in core.get(field, {}):
                self.errors.append(f"[CASH] 必须明确填写{field}.value，即使为0")

        # 检查报表期（新增）
        if not cash.get('report_period'):
            self.warnings.append("[CASH] 建议标注现金数据的报表期")
        
        if not any(e for e in self.errors if e.startswith('[CASH]')):
            print(f"   [PASS] 现金数据校验通过: {value:,.0f} {cash.get('unit', '')}")
    
    def _validate_debt_data(self):
        """校验负债数据（S级强制）"""
        print("\n[3] 负债数据校验（S级）")
        
        debt = self.data.get('core_financial_data', {}).get('interest_bearing_debt', {})
        
        # 检查各组成部分
        components = ['short_term', 'long_term', 'bonds', 'lease_liabilities']
        for comp in components:
            comp_data = debt.get(comp, {})
            if comp_data.get('value', 0) > 0 and not comp_data.get('source'):
                self.warnings.append(f"[DEBT] {comp}有数值但未标注来源")
        
        # 检查计算是否正确
        total_calculated = (
            debt.get('short_term', {}).get('value', 0) +
            debt.get('long_term', {}).get('value', 0) +
            debt.get('bonds', {}).get('value', 0) +
            debt.get('lease_liabilities', {}).get('value', 0)
        )
        total_recorded = debt.get('total_value', 0)
        
        if total_recorded > 0 and abs(total_calculated - total_recorded) > 0.01:
            self.errors.append(
                f"[DEBT] 有息负债计算错误: "
                f"{debt.get('short_term', {}).get('value', 0)} + "
                f"{debt.get('long_term', {}).get('value', 0)} + "
                f"{debt.get('bonds', {}).get('value', 0)} + "
                f"{debt.get('lease_liabilities', {}).get('value', 0)} = "
                f"{total_calculated}, 但填写为 {total_recorded}"
            )
        
        # 检查报表期（新增）
        components = ['short_term', 'long_term', 'bonds', 'lease_liabilities']
        for comp in components:
            comp_data = debt.get(comp, {})
            if comp_data.get('value', 0) > 0 and not comp_data.get('report_period'):
                self.warnings.append(f"[DEBT] {comp}有数值但未标注报表期")

        if not any(e for e in self.errors if e.startswith('[DEBT]')):
            print(f"   [PASS] 负债数据校验通过: 有息负债合计 {total_calculated:,.0f}")
    
    def _validate_profit_data(self):
        """校验利润数据（S级强制）"""
        print("\n[4] 利润数据校验（S级）")
        
        core = self.data.get('core_financial_data', {})
        revenue = core.get('revenue', {})
        profit = core.get('net_profit_attributable', {})
        
        # 检查必填字段
        if not revenue.get('value'):
            self.errors.append("[PROFIT] 收入数据未填写")
        if not profit.get('value'):
            self.errors.append("[PROFIT] 归母净利润未填写")
        
        # 检查报表期（新增）
        for item in [revenue, profit]:
            if item.get('value', 0) > 0 and not item.get('report_period'):
                self.warnings.append(f"[PROFIT] {item.get('display_unit', '数据')}未标注报表期")

        if not any(e for e in self.errors if e.startswith('[PROFIT]')):
            print(f"   [PASS] 利润数据校验通过")

    @staticmethod
    def _numeric_value(value: Any) -> float:
        """兼容原始数字和{value: ...}字段；空值按0处理。"""
        if isinstance(value, dict):
            value = value.get('value')
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return 0.0

    def _validate_profit_quality(self):
        """大额减值触发三层利润桥接，阻止把所有非现金减值机械加回。"""
        print("\n[4.2] 利润质量三层桥接校验")
        core = self.data.get('core_financial_data', {})
        impairment = core.get('impairment_breakdown') or {}
        items = impairment.get('items') or []
        total_impairment = abs(self._numeric_value(impairment.get('total')))
        attributable_profit = abs(self._numeric_value(core.get('net_profit_attributable')))
        trigger_types = {'goodwill', 'receivable_credit', 'guarantee', 'factoring', 'microloan'}
        item_types = {
            str(item.get('type', '')).strip().lower()
            for item in items if isinstance(item, dict) and abs(self._numeric_value(item.get('amount'))) > 0
        }
        ratio_trigger = attributable_profit > 0 and total_impairment / attributable_profit > 0.10
        triggered = bool(
            ratio_trigger
            or impairment.get('direction_flip_after_adjustment', False)
            or item_types.intersection(trigger_types)
            or ('inventory' in item_types and total_impairment > 0)
        )
        if not triggered:
            print("   [PASS] 未触发强制正常化利润桥接")
            return

        for index, item in enumerate(items, 1):
            if not item.get('source'):
                self.errors.append(f"[PROFIT_QUALITY] 第{index}项减值明细缺少source")
            if not item.get('page_number'):
                self.errors.append(f"[PROFIT_QUALITY] 第{index}项减值明细缺少page_number或公告章节")

        quality = core.get('profit_quality') or {}
        if not quality.get('bridge_required', False):
            self.errors.append("[PROFIT_QUALITY] 大额/特定减值已触发，bridge_required必须为true")
        for name in ('reported_profit', 'normalized_profit'):
            if quality.get(name, {}).get('value') is None:
                self.errors.append(f"[PROFIT_QUALITY] 触发后必须填写{name}.value")
        adjustments = quality.get('adjustment_items') or []
        if not adjustments:
            self.errors.append("[PROFIT_QUALITY] 触发后必须逐项填写adjustment_items（包括不允许加回的项目）")

        prohibited_addbacks = {'inventory', 'receivable_credit', 'guarantee', 'factoring', 'microloan'}
        required_fields = {
            'type', 'amount', 'after_tax_amount', 'attributable_amount', 'cash_impact',
            'recurring', 'add_back_allowed', 'rationale', 'remaining_exposure', 'source', 'page_number'
        }
        for index, item in enumerate(adjustments, 1):
            missing = [field for field in required_fields if field not in item or item.get(field) in ('', None)]
            if missing:
                self.errors.append(f"[PROFIT_QUALITY] 第{index}项调整缺少字段: {', '.join(missing)}")
            if not item.get('page_number'):
                self.errors.append(f"[PROFIT_QUALITY] 第{index}项调整缺少page_number或公告章节")
            item_type = str(item.get('type', '')).strip().lower()
            if item_type in prohibited_addbacks and item.get('add_back_allowed') is True:
                self.errors.append(f"[PROFIT_QUALITY] {item_type}减值原则上不得加回正常化利润")
            if item.get('add_back_allowed') is True and not item.get('rationale'):
                self.errors.append(f"[PROFIT_QUALITY] 第{index}项允许加回但未说明证据")

        if not quality.get('conclusion'):
            self.errors.append("[PROFIT_QUALITY] 触发后必须填写三层利润质量结论")

        policy = self.data.get('analysis_metadata', {}).get('valuation_policy', {})
        if policy.get('pe_applicable', False) and policy.get('ttm_method') != 'NOT_AVAILABLE':
            normalized_ttm_profit = quality.get('normalized_ttm_profit', {}).get('value')
            normalized_ttm_pe = quality.get('normalized_ttm_pe', {}).get('value')
            if normalized_ttm_profit is None:
                self.errors.append("[PROFIT_QUALITY] PE适用且TTM可得时必须填写normalized_ttm_profit.value")
            if normalized_ttm_pe is None:
                self.errors.append("[PROFIT_QUALITY] PE适用且TTM可得时必须填写normalized_ttm_pe.value")
            market_cap = self._numeric_value(core.get('market_cap'))
            if market_cap > 0 and normalized_ttm_profit and normalized_ttm_pe is not None:
                expected_pe = market_cap / normalized_ttm_profit
                if not self._approximately_equal(
                    expected_pe, normalized_ttm_pe,
                    relative_tolerance=0.01, absolute_tolerance=0.01
                ):
                    self.errors.append(
                        f"[PROFIT_QUALITY] 正常化TTM PE错误: {market_cap} / "
                        f"{normalized_ttm_profit} = {expected_pe:.4f}，但填写为{normalized_ttm_pe}"
                    )

        if not any(e for e in self.errors if e.startswith('[PROFIT_QUALITY]')):
            print(f"   [PASS] 已完成减值桥接，减值/归母利润={total_impairment / attributable_profit:.1%}")

    def _validate_credit_chain(self):
        """有信用链敞口时强制检查法律责任、隐性支持和压力损失。"""
        print("\n[4.3] 信用链压力测试校验")
        chain = self.data.get('credit_chain') or {}
        exposure_fields = (
            'legal_off_balance_obligations', 'related_party_loans', 'factoring_and_microloans',
            'finance_company_deposits', 'associate_or_subsidiary_debt'
        )
        nonzero_fields = [name for name in exposure_fields if abs(self._numeric_value(chain.get(name))) > 0]
        implicit_support = bool((chain.get('implicit_support') or {}).get('exists', False))
        triggered = bool(chain.get('triggered', False) or nonzero_fields or implicit_support)
        if not triggered:
            print("   [PASS] 未识别到信用链压力测试触发项")
            return

        if not chain.get('triggered', False):
            self.errors.append("[CREDIT_CHAIN] 已存在关联/表外敞口，triggered必须为true")
        for name in nonzero_fields:
            item = chain.get(name) or {}
            if not item.get('source'):
                self.errors.append(f"[CREDIT_CHAIN] {name}有余额但缺少source")
            if not item.get('page_number'):
                self.warnings.append(f"[CREDIT_CHAIN] {name}有余额但缺少page_number或公告章节")
        if self._numeric_value(chain.get('related_party_loans')) and not (chain.get('related_party_loans') or {}).get('direction'):
            self.errors.append("[CREDIT_CHAIN] 关联贷款必须标明资金方向direction")
        if self._numeric_value(chain.get('finance_company_deposits')) and not (chain.get('finance_company_deposits') or {}).get('direction'):
            self.errors.append("[CREDIT_CHAIN] 财务公司存款必须标明资金方向direction")
        if implicit_support and not (chain.get('implicit_support') or {}).get('rationale'):
            self.errors.append("[CREDIT_CHAIN] 存在隐性支持时必须说明rationale")
        for field in ('funding_cost_assessment', 'solvency_and_cutoff_assessment', 'conclusion'):
            if not chain.get(field):
                self.errors.append(f"[CREDIT_CHAIN] 触发后必须填写{field}")
        if not chain.get('stress_test_completed', False):
            self.errors.append("[CREDIT_CHAIN] 触发后必须完成基准/下行情景压力测试")
        scenarios = chain.get('stress_scenarios') or []
        scenario_names = {str(s.get('scenario', '')).lower() for s in scenarios if isinstance(s, dict)}
        if not {'base', 'downside'}.issubset(scenario_names):
            self.errors.append("[CREDIT_CHAIN] stress_scenarios必须同时包含base和downside")
        for index, scenario in enumerate(scenarios, 1):
            if scenario.get('expected_support_loss') is None or not scenario.get('impact_on_net_cash_fcf_dividend'):
                self.errors.append(f"[CREDIT_CHAIN] 第{index}个压力情景缺少预计损失或净现金/FCF/分红影响")

        if not any(e for e in self.errors if e.startswith('[CREDIT_CHAIN]')):
            print("   [PASS] 信用链敞口与压力情景已填写")
    
    def _validate_cashflow_data(self):
        """校验现金流数据（S级强制）"""
        meta = self.data.get('analysis_metadata', {})
        report_type = meta.get('report_type', 'annual')
        level_label = "S级" if report_type == 'annual' else "B级"
        print(f"\n[5] 现金流数据校验（{level_label}）")

        core = self.data.get('core_financial_data', {})
        ocf = core.get('operating_cash_flow', {})
        capex = core.get('capex', {})
        policy = meta.get('valuation_policy', {})

        if not policy.get('fcf_applicable', True):
            if not policy.get('fcf_unavailable_reason'):
                self.errors.append("[CASHFLOW] FCF不适用时必须填写fcf_unavailable_reason")
            if ocf.get('value') is not None or capex.get('value') is not None:
                self.errors.append("[CASHFLOW] FCF不适用时经营现金流和资本开支value必须为null，禁止填伪数字")
            if not any(e for e in self.errors if e.startswith('[CASHFLOW]')):
                print("   [PASS] FCF不适用，已记录原因并保持原始值为空")
            return

        # 检查经营现金流置信度（中报数据允许B级）
        expected_confidence = 'S' if report_type == 'annual' else 'B'
        if ocf.get('confidence') != expected_confidence:
            if report_type == 'annual':
                self.errors.append("[CASHFLOW] 经营现金流必须是S级")
            else:
                self.errors.append(f"[CASHFLOW] 中报/季报经营现金流必须是B级（当前：{ocf.get('confidence', '未标注')}）")

        if not ocf.get('verification_checked', False):
            self.errors.append("[CASHFLOW] 必须勾选确认经营现金流已核查")
        
        # 检查资本开支（即使为0也要明确）
        if 'value' not in capex:
            self.errors.append("[CASHFLOW] 必须明确填写资本开支（即使为0）")
        
        # 检查报表期（新增）
        for item in [ocf, capex]:
            if 'value' in item and not item.get('report_period'):
                self.warnings.append(f"[CASHFLOW] {'经营现金流' if item is ocf else '资本开支'}未标注报表期")

        if not any(e for e in self.errors if e.startswith('[CASHFLOW]')):
            print(f"   [PASS] 现金流数据校验通过")

    def _validate_valuation_data(self):
        """校验估值方法、统一币种和与披露频率匹配的TTM数据。"""
        print("\n[4.5] 估值适用性与TTM校验")

        meta = self.data.get('analysis_metadata', {})
        policy = meta.get('valuation_policy')
        if not policy:
            self.warnings.append("[VALUATION] 未声明valuation_policy，无法确认主估值方法和PE适用性")
            return

        primary_method = policy.get('primary_method', '')
        if primary_method not in {'PE', 'PB', 'DPU_FFO', 'MID_CYCLE', 'PS', 'PROBABILITY_WEIGHTED'}:
            self.errors.append("[VALUATION] primary_method必须是PE/PB/DPU_FFO/MID_CYCLE/PS/PROBABILITY_WEIGHTED之一")

        if not policy.get('price_as_of'):
            self.errors.append("[VALUATION] 必须填写股价基准日price_as_of")
        if not policy.get('fx_as_of'):
            self.errors.append("[VALUATION] 必须填写汇率日期fx_as_of")

        calculation_currency = policy.get('calculation_currency')
        if calculation_currency not in {'HKD', 'RMB', 'USD'}:
            self.errors.append("[VALUATION] calculation_currency必须是HKD/RMB/USD之一")

        fx_rate = policy.get('share_price_to_calculation_currency_rate')
        if not isinstance(fx_rate, (int, float)) or isinstance(fx_rate, bool) or fx_rate <= 0:
            self.errors.append("[VALUATION] 必须填写正数汇率share_price_to_calculation_currency_rate")

        core = self.data.get('core_financial_data', {})
        price_currency = core.get('share_price', {}).get('currency')
        if price_currency not in {'HKD', 'RMB', 'USD'}:
            self.errors.append("[VALUATION] 必须填写股价币种")
        if price_currency != calculation_currency and not policy.get('fx_source'):
            self.errors.append("[VALUATION] 跨币种估值必须填写fx_source")
        if price_currency != calculation_currency and fx_rate == 1:
            self.errors.append("[VALUATION] 股价币种与计算币种不同，汇率不能填1")

        for field_name in [
            'cash_and_bank_balances', 'revenue', 'net_profit',
            'net_profit_attributable', 'operating_cash_flow', 'capex'
        ]:
            field_data = core.get(field_name, {})
            field_unit = field_data.get('unit')
            if not field_unit:
                self.errors.append(f"[VALUATION] {field_name}缺少unit")
            elif calculation_currency and field_unit != calculation_currency:
                self.errors.append(
                    f"[VALUATION] {field_name}币种{field_unit}与统一计算币种"
                    f"{calculation_currency}不一致；请先换算并保留原始值说明"
                )

        if not policy.get('pe_applicable', False):
            print(f"   [PASS] PE不适用，主估值方法: {primary_method or '未填写'}")
            return

        ttm_method = policy.get('ttm_method')
        allowed_methods = {'FOUR_QUARTERS', 'ANNUAL_PLUS_INTERIM', 'NOT_AVAILABLE'}
        if ttm_method not in allowed_methods:
            self.errors.append("[VALUATION] ttm_method必须是FOUR_QUARTERS/ANNUAL_PLUS_INTERIM/NOT_AVAILABLE之一")
            return

        metrics = core.get('calculated_metrics', {})
        if ttm_method == 'NOT_AVAILABLE':
            if not policy.get('ttm_unavailable_reason'):
                self.errors.append("[VALUATION] TTM不可用时必须填写ttm_unavailable_reason")
            if metrics.get('ttm_net_profit', {}).get('value') is not None:
                self.errors.append("[VALUATION] TTM不可用时ttm_net_profit.value必须为null")
            if metrics.get('ttm_pe', {}).get('value') is not None:
                self.errors.append("[VALUATION] TTM不可用时ttm_pe.value必须为null")
            print(f"   [PASS] TTM不可可靠计算，使用年度替代口径: {policy.get('ttm_unavailable_reason', '')}")
            return

        if not policy.get('ttm_period'):
            self.errors.append("[VALUATION] TTM可计算时必须填写ttm_period")

        components = core.get('ttm_components', [])
        expected_count = 4 if ttm_method == 'FOUR_QUARTERS' else 3
        if len(components) != expected_count:
            self.errors.append(
                f"[VALUATION] {ttm_method}需要{expected_count}个TTM组成项，当前为{len(components)}个"
            )
            return

        if ttm_method == 'ANNUAL_PLUS_INTERIM':
            expected_roles = {'latest_annual', 'current_interim', 'prior_interim'}
            actual_roles = {component.get('role') for component in components}
            if actual_roles != expected_roles:
                self.errors.append(
                    f"[VALUATION] 半年披露TTM角色必须是{sorted(expected_roles)}，当前为{sorted(str(x) for x in actual_roles)}"
                )

        for index, component in enumerate(components, 1):
            if not component.get('period'):
                self.errors.append(f"[VALUATION] TTM第{index}个组成项缺少period")
            if component.get('value') is None:
                self.errors.append(f"[VALUATION] TTM第{index}个组成项缺少value")
            if component.get('operator') not in {-1, 1}:
                self.errors.append(f"[VALUATION] TTM第{index}个组成项operator只能是1或-1")
            if component.get('unit') != calculation_currency:
                self.errors.append(
                    f"[VALUATION] TTM第{index}个组成项币种必须等于{calculation_currency}"
                )
            if not component.get('source'):
                self.errors.append(f"[VALUATION] TTM第{index}个组成项缺少source")
            if not component.get('page_number'):
                self.warnings.append(f"[VALUATION] TTM第{index}个组成项缺少page_number或公告章节")

        if ttm_method == 'FOUR_QUARTERS' and any(component.get('operator') != 1 for component in components):
            self.errors.append("[VALUATION] FOUR_QUARTERS的四个operator必须全部为1")

        ttm_total = sum(
            (component.get('operator') or 0) * (component.get('value') or 0)
            for component in components
        )
        ttm_profit = metrics.get('ttm_net_profit', {}).get('value')
        if ttm_profit is None:
            self.errors.append("[VALUATION] 必须填写ttm_net_profit.value")
        elif not self._approximately_equal(ttm_total, ttm_profit):
            self.errors.append(f"[VALUATION] TTM净利润错误: 组成项合计{ttm_total}，但填写为{ttm_profit}")

        print(f"   [PASS] TTM组成项已填写，方法{ttm_method}，总额: {ttm_total:,.2f}")
    
    def _validate_share_data(self):
        """校验股本数据（S级强制）"""
        print("\n[6] 股本数据校验（S级）")
        
        core = self.data.get('core_financial_data', {})
        shares = core.get('total_shares', {})
        price = core.get('share_price', {})
        
        if not shares.get('value'):
            self.errors.append("[SHARE] 总股本未填写")
        if not price.get('value'):
            self.errors.append("[SHARE] 股价未填写")
        
        if not any(e for e in self.errors if e.startswith('[SHARE]')):
            print(f"   [PASS] 股本数据校验通过")
    
    def _validate_calculated_metrics(self):
        """校验计算指标"""
        print("\n[7] 计算指标校验")
        
        core = self.data.get('core_financial_data', {})
        metrics = core.get('calculated_metrics', {})
        
        # 获取原始数据
        cash = core.get('cash_and_bank_balances', {}).get('value', 0)
        cash_equivalents = core.get('cash_and_cash_equivalents', {}).get('value', 0)
        restricted = core.get('restricted_cash', {}).get('value', 0)
        related_cash_data = core.get('related_financial_institution_deposits', {})
        related_cash = related_cash_data.get('value', 0)
        related_cash_in_equivalents = related_cash if related_cash_data.get('included_in_cash_and_cash_equivalents', False) else 0
        other_low_liquidity_cash = core.get('other_low_liquidity_cash', {}).get('value', 0)
        debt_short = core.get('interest_bearing_debt', {}).get('short_term', {}).get('value', 0)
        debt_long = core.get('interest_bearing_debt', {}).get('long_term', {}).get('value', 0)
        debt_bonds = core.get('interest_bearing_debt', {}).get('bonds', {}).get('value', 0)
        debt_lease = core.get('interest_bearing_debt', {}).get('lease_liabilities', {}).get('value', 0)
        debt_total = debt_short + debt_long + debt_bonds + debt_lease
        
        ocf = core.get('operating_cash_flow', {}).get('value') or 0
        capex = core.get('capex', {}).get('value') or 0
        shares = core.get('total_shares', {}).get('value', 0)
        price = core.get('share_price', {}).get('value', 0)
        profit = core.get('net_profit_attributable', {}).get('value', 0)
        dividend_per_share = core.get('dividend_per_share_for_yield', {}).get('value')

        policy = self.data.get('analysis_metadata', {}).get('valuation_policy', {})
        fx_rate_raw = policy.get('share_price_to_calculation_currency_rate', 0)
        fx_rate = (
            fx_rate_raw
            if isinstance(fx_rate_raw, (int, float)) and not isinstance(fx_rate_raw, bool) and fx_rate_raw > 0
            else 0
        )
        calculation_currency = policy.get('calculation_currency')
        market_cap = shares * price * fx_rate

        market_cap_data = core.get('market_cap', {})
        if market_cap_data.get('unit') != calculation_currency:
            self.errors.append("[CALC] market_cap.unit必须等于统一计算币种")
        market_cap_recorded = market_cap_data.get('value')
        if market_cap_recorded is None:
            self.errors.append("[CALC] 必须填写market_cap.value")
        elif not self._approximately_equal(market_cap, market_cap_recorded):
            self.errors.append(
                f"[CALC] 市值计算错误: {shares} × {price} × {fx_rate} = {market_cap}, "
                f"但填写为 {market_cap_recorded}"
            )
        
        # 校验净现金计算
        net_cash_expected = cash - restricted - debt_total
        net_cash_recorded = metrics.get('net_cash', {}).get('value')
        if net_cash_recorded is None:
            self.errors.append("[CALC] 必须填写net_cash.value，净负债时允许负数")
        elif not self._approximately_equal(net_cash_expected, net_cash_recorded):
            self.errors.append(
                f"[CALC] 净现金计算错误: "
                f"{cash} - {restricted} - {debt_total} = {net_cash_expected}, "
                f"但填写为 {net_cash_recorded}"
            )

        # 校验即时净现金、审慎即时净现金及市值占比
        immediate_expected = cash_equivalents - restricted - debt_total
        immediate_metric = metrics.get('immediate_net_cash', {})
        immediate_recorded = immediate_metric.get('value')
        if immediate_recorded is None:
            self.errors.append("[CALC] 必须填写immediate_net_cash.value")
        elif not self._approximately_equal(immediate_expected, immediate_recorded):
            self.errors.append(
                f"[CALC] 即时净现金计算错误: {cash_equivalents} - {restricted} - {debt_total} = "
                f"{immediate_expected}, 但填写为 {immediate_recorded}"
            )
        if market_cap > 0:
            immediate_ratio = immediate_metric.get('market_cap_ratio')
            expected_ratio = immediate_expected / market_cap
            if immediate_ratio is None or not self._approximately_equal(expected_ratio, immediate_ratio, relative_tolerance=0.01):
                self.errors.append("[CALC] immediate_net_cash.market_cap_ratio缺失或计算错误")
        if not immediate_metric.get('notes'):
            self.errors.append("[CALC] 即时净现金必须说明能否立即动用及自由分红约束")

        conservative_expected = immediate_expected - related_cash_in_equivalents - other_low_liquidity_cash
        conservative_metric = metrics.get('conservative_immediate_net_cash', {})
        conservative_recorded = conservative_metric.get('value')
        if conservative_recorded is None:
            self.errors.append("[CALC] 必须填写conservative_immediate_net_cash.value")
        elif not self._approximately_equal(conservative_expected, conservative_recorded):
            self.errors.append(
                f"[CALC] 审慎即时净现金计算错误: {immediate_expected} - {related_cash_in_equivalents} - "
                f"{other_low_liquidity_cash} = {conservative_expected}, 但填写为 {conservative_recorded}"
            )
        if market_cap > 0:
            conservative_ratio = conservative_metric.get('market_cap_ratio')
            expected_conservative_ratio = conservative_expected / market_cap
            if conservative_ratio is None or not self._approximately_equal(
                expected_conservative_ratio, conservative_ratio, relative_tolerance=0.01
            ):
                self.errors.append("[CALC] conservative_immediate_net_cash.market_cap_ratio缺失或计算错误")

        if market_cap > 0:
            broad_ratio = metrics.get('net_cash', {}).get('market_cap_ratio')
            expected_broad_ratio = net_cash_expected / market_cap
            if broad_ratio is None or not self._approximately_equal(expected_broad_ratio, broad_ratio, relative_tolerance=0.01):
                self.errors.append("[CALC] net_cash.market_cap_ratio缺失或计算错误")

        fcf_applicable = policy.get('fcf_applicable', True)
        fcf_expected = ocf - capex
        if not fcf_applicable:
            if metrics.get('fcf', {}).get('value') is not None:
                self.errors.append("[CALC] FCF不适用时fcf.value必须为null")
            if metrics.get('fcf_yield', {}).get('value') is not None:
                self.errors.append("[CALC] FCF不适用时fcf_yield.value必须为null")
            if metrics.get('fcf_multiple_market', {}).get('value') is not None:
                self.errors.append("[CALC] FCF不适用时fcf_multiple_market.value必须为null")
            if metrics.get('multi_period_fcf', {}).get('method') != 'NOT_AVAILABLE':
                self.errors.append("[CALC] FCF不适用时multi_period_fcf.method必须为NOT_AVAILABLE")
        else:
            # 校验FCF计算
            fcf_recorded = metrics.get('fcf', {}).get('value')
            if fcf_recorded is None:
                self.errors.append("[CALC] 必须填写fcf.value，负数或零值也必须明确")
            elif not self._approximately_equal(fcf_expected, fcf_recorded):
                self.errors.append(
                    f"[CALC] FCF计算错误: {ocf} - {capex} = {fcf_expected}, 但填写为 {fcf_recorded}"
                )

            # 校验FCF/市值、市值/FCF
            if market_cap > 0:
                fcf_yield = metrics.get('fcf_yield', {}).get('value')
                expected_fcf_yield = fcf_expected / market_cap
                if fcf_yield is None or not self._approximately_equal(expected_fcf_yield, fcf_yield, relative_tolerance=0.01):
                    self.errors.append("[CALC] fcf_yield.value缺失或计算错误")
            fcf_multiple_market = metrics.get('fcf_multiple_market', {}).get('value')
            if fcf_expected > 0:
                expected_market_multiple = market_cap / fcf_expected
                if fcf_multiple_market is None or not self._approximately_equal(
                    expected_market_multiple, fcf_multiple_market, relative_tolerance=0.01
                ):
                    self.errors.append("[CALC] fcf_multiple_market.value缺失或计算错误")

            # 校验跨期平均FCF
            multi_period = metrics.get('multi_period_fcf', {})
            multi_method = multi_period.get('method')
            if multi_method == 'NOT_AVAILABLE':
                if not multi_period.get('unavailable_reason'):
                    self.errors.append("[CALC] 跨期FCF不可计算时必须填写unavailable_reason")
            elif multi_method in {'TWO_YEAR_AVERAGE', 'THREE_YEAR_AVERAGE'}:
                periods = multi_period.get('periods', [])
                required_count = 2 if multi_method == 'TWO_YEAR_AVERAGE' else 3
                if len(periods) != required_count or any('value' not in item for item in periods):
                    self.errors.append(f"[CALC] {multi_method}必须填写{required_count}个完整期间FCF")
                else:
                    expected_average = sum(item['value'] for item in periods) / required_count
                    if not self._approximately_equal(expected_average, multi_period.get('average_value', float('nan'))):
                        self.errors.append("[CALC] multi_period_fcf.average_value计算错误")
                    if market_cap > 0 and not self._approximately_equal(
                        expected_average / market_cap,
                        multi_period.get('market_cap_yield', float('nan')),
                        relative_tolerance=0.01,
                    ):
                        self.errors.append("[CALC] multi_period_fcf.market_cap_yield计算错误")
            else:
                self.errors.append("[CALC] multi_period_fcf.method必须是TWO_YEAR_AVERAGE、THREE_YEAR_AVERAGE或NOT_AVAILABLE")

        # 校验税前股息率；零派息允许为0
        dividend_data = core.get('dividend_per_share_for_yield', {})
        if dividend_per_share is None:
            self.errors.append("[CALC] 必须填写dividend_per_share_for_yield.value，零派息填0")
        elif dividend_data.get('currency') != core.get('share_price', {}).get('currency'):
            self.errors.append("[CALC] 每股股息与股价必须使用同一币种")
        elif price > 0:
            expected_dividend_yield = dividend_per_share / price
            dividend_yield = metrics.get('dividend_yield', {}).get('value')
            if dividend_yield is None or not self._approximately_equal(
                expected_dividend_yield, dividend_yield, relative_tolerance=0.01
            ):
                self.errors.append("[CALC] dividend_yield.value缺失或计算错误")
        
        # 校验FCF倍数
        fcf_multiple = metrics.get('fcf_multiple_ex_cash', {}).get('value')
        if fcf_applicable and fcf_multiple is not None and fcf_expected != 0:
            market_cap_ex_cash = market_cap - net_cash_expected
            expected_multiple = market_cap_ex_cash / fcf_expected
            if not self._approximately_equal(expected_multiple, fcf_multiple, relative_tolerance=0.01):
                self.errors.append(
                    f"[CALC] 剔除现金FCF倍数计算可能有误: "
                    f"({market_cap} - {net_cash_expected}) / {fcf_expected} = "
                    f"{expected_multiple:.2f}, 但填写为 {fcf_multiple}"
                )

        pe_applicable = policy.get('pe_applicable', False)
        if pe_applicable:
            static_pe = metrics.get('static_pe', {}).get('value')
            if profit <= 0:
                self.errors.append("[CALC] 归母净利润非正时不得声明PE适用")
            elif static_pe is None:
                self.errors.append("[CALC] PE适用时必须填写static_pe.value")
            else:
                expected_static_pe = market_cap / profit
                if not self._approximately_equal(expected_static_pe, static_pe, relative_tolerance=0.01):
                    self.errors.append(
                        f"[CALC] 静态PE错误: {market_cap} / {profit} = "
                        f"{expected_static_pe:.2f}, 但填写为 {static_pe}"
                    )

            if policy.get('ttm_method') != 'NOT_AVAILABLE':
                ttm_profit = metrics.get('ttm_net_profit', {}).get('value')
                ttm_pe = metrics.get('ttm_pe', {}).get('value')
                if ttm_profit is None or ttm_profit <= 0:
                    self.errors.append("[CALC] TTM PE适用时TTM净利润必须为正数")
                elif ttm_pe is None:
                    self.errors.append("[CALC] 必须填写ttm_pe.value")
                else:
                    expected_ttm_pe = market_cap / ttm_profit
                    if not self._approximately_equal(expected_ttm_pe, ttm_pe, relative_tolerance=0.01):
                        self.errors.append(
                            f"[CALC] TTM PE错误: {market_cap} / {ttm_profit} = "
                            f"{expected_ttm_pe:.2f}, 但填写为 {ttm_pe}"
                        )

        if not any(e for e in self.errors if e.startswith('[CALC]')):
            print(f"   [PASS] 计算指标校验通过")

    @staticmethod
    def _approximately_equal(
        expected: float,
        recorded: float,
        relative_tolerance: float = 0.001,
        absolute_tolerance: float = 0.01,
    ) -> bool:
        """同时使用相对和绝对误差，兼容元级大数与倍数小数。"""
        difference = abs(expected - recorded)
        scale = max(abs(expected), abs(recorded), 1.0)
        return difference <= max(absolute_tolerance, relative_tolerance * scale)
    
    def _validate_historical_comparison(self):
        """校验历史对比"""
        print("\n[8] 历史对比校验")
        
        hist = self.data.get('historical_comparison', {})
        years = hist.get('years', [])
        
        if len(years) < 3:
            self.warnings.append("[HIST] 历史对比少于3年，建议补充")
        
        print(f"   [PASS] 历史对比校验通过 ({len(years)}年数据)")
    
    def _validate_cross_checks(self):
        """交叉验证"""
        print("\n[9] 交叉验证")
        
        core = self.data.get('core_financial_data', {})
        cross = self.data.get('cross_validation', {})
        
        cash = core.get('cash_and_bank_balances', {}).get('value', 0)
        
        # 利息率验证
        interest = cross.get('interest_rate_check', {})
        interest_income = interest.get('interest_income', 0)
        if cash > 0 and interest_income > 0:
            rate = interest_income / cash
            if not (0.01 <= rate <= 0.05):
                self.warnings.append(
                    f"[CROSS] 利息率异常: {rate*100:.2f}% (正常范围1%-5%)"
                )
        
        print(f"   [PASS] 交叉验证通过")
    
    def _validate_checklist(self):
        """校验检查清单"""
        print("\n[10] 校验检查清单")
        
        checklist = self.data.get('validation_checklist', [])
        
        for item in checklist:
            if not item.get('checked', False):
                self.errors.append(f"[CHECKLIST] 未勾选: {item.get('item', '')}")

            # 如果变动>30%，必须解释
            if item.get('id') == 'variance' and item.get('checked', False):
                if not item.get('variance_explanation'):
                    self.warnings.append("[CHECKLIST] 数据变动>30%，建议填写解释")

            # 数据时效性检查（新增）
            if item.get('id') == 'data_freshness' and item.get('checked', False):
                # 检查是否使用非年报数据
                meta = self.data.get('analysis_metadata', {})
                report_type = meta.get('report_type', 'annual')
                if report_type != 'annual':
                    if not item.get('freshness_explanation'):
                        self.warnings.append(
                            "[CHECKLIST] 使用非年报数据（中报/季报），建议填写解释原因"
                        )
        
        if not any(e for e in self.errors if e.startswith('[CHECKLIST]')):
            print(f"   [PASS] 检查清单校验通过")
    
    def _validate_confirmation(self):
        """校验确认声明"""
        print("\n[11] 确认声明校验")
        
        confirm = self.data.get('confirmation', {})
        
        if not confirm.get('analyst_signature'):
            self.errors.append("[CONFIRM] 必须填写分析人员签名")
        
        if not confirm.get('validation_date'):
            self.errors.append("[CONFIRM] 必须填写校验完成日期")
        
        print(f"   [PASS] 确认声明校验通过")
    
    def print_report(self):
        """打印校验报告"""
        print("\n" + "=" * 60)
        print("[SUMMARY] 校验结果汇总")
        print("=" * 60)
        
        if self.result.errors:
            print(f"\n[FAIL] 发现 {len(self.result.errors)} 个错误（必须修正）：")
            for i, error in enumerate(self.result.errors, 1):
                print(f"   {i}. {error}")
        
        if self.result.warnings:
            print(f"\n[WARN] 发现 {len(self.result.warnings)} 个警告（建议复核）：")
            for i, warning in enumerate(self.result.warnings, 1):
                print(f"   {i}. {warning}")
        
        if self.result.passed and not self.result.warnings:
            print("\n[PASS] 所有校验通过，可以生成报告！")
        elif self.result.passed and self.result.warnings:
            print("\n[PASS] 校验通过但有警告，建议复核后生成报告")
        else:
            print("\n[FAIL] 校验失败，必须修正以上错误后才能生成报告")
        
        print("=" * 60)


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python scripts/validate_data.py config/validation_XXXX.yaml")
        sys.exit(1)
    
    yaml_path = Path(sys.argv[1])
    
    if not yaml_path.exists():
        print(f"❌ 文件不存在: {yaml_path}")
        sys.exit(1)
    
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"❌ YAML解析错误: {e}")
        sys.exit(1)
    
    # 执行校验
    validator = DataValidator(data)
    result = validator.validate_all()
    validator.print_report()
    
    # 返回码
    if not result.passed:
        sys.exit(1)  # 失败
    elif result.warnings:
        sys.exit(2)  # 通过但有警告
    else:
        sys.exit(0)  # 完全通过


if __name__ == "__main__":
    main()
