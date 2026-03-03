#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险管理验证工具 (V5.3.2)
自动检查持仓是否符合风控规则
"""

import yaml
import sys
from dataclasses import dataclass, field
from typing import List, Dict
from pathlib import Path


@dataclass
class Position:
    """持仓数据结构"""
    code: str
    name: str
    strategy: str  # 纯硬收息型/烟蒂股型/价值发现型/关联方资源型
    market_value: float  # 市值
    cost: float  # 成本
    current_price: float  # 当前价格
    
    @property
    def pnl_pct(self) -> float:
        """盈亏比例"""
        if self.cost == 0:
            return 0.0
        return (self.current_price - self.cost) / self.cost * 100


@dataclass
class Portfolio:
    """投资组合"""
    total_assets: float  # 总资产
    positions: List[Position] = field(default_factory=list)
    
    @property
    def total_market_value(self) -> float:
        """总持仓市值"""
        return sum(p.market_value for p in self.positions)
    
    @property
    def cash_ratio(self) -> float:
        """现金比例"""
        if self.total_assets == 0:
            return 0.0
        return (self.total_assets - self.total_market_value) / self.total_assets


class RiskValidator:
    """风险验证器"""
    
    def __init__(self, config_path: str = "config/risk_management.yaml"):
        """
        初始化
        :param config_path: 风控配置文件路径
        """
        self.config = self._load_config(config_path)
        self.warnings = []
        self.errors = []
    
    def _load_config(self, path: str) -> Dict:
        """加载配置文件"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"警告: 无法加载配置文件 {path}: {e}")
            print("使用默认配置")
            return self._default_config()
    
    def _default_config(self) -> Dict:
        """默认配置"""
        return {
            'position_limits': {
                '纯硬收息型': {'single_stock_max': 0.15, 'sector_max': 0.30},
                '烟蒂股型': {'single_stock_max': 0.05, 'sector_max': 0.20},
                '价值发现型': {'single_stock_max': 0.10, 'sector_max': 0.25},
                '关联方资源型': {'single_stock_max': 0.08, 'sector_max': 0.15},
            },
            'liquidity_limits': {'最小日均成交': 1000000},
            'market_risk': {'总仓位上限': 0.90, '现金储备下限': 0.10}
        }
    
    def validate(self, portfolio: Portfolio) -> bool:
        """
        验证投资组合
        :param portfolio: 投资组合
        :return: 是否通过验证
        """
        self.warnings = []
        self.errors = []
        
        print(f"\n开始风控检查...")
        print(f"总资产: {portfolio.total_assets:,.0f}")
        print(f"持仓市值: {portfolio.total_market_value:,.0f}")
        print(f"现金比例: {portfolio.cash_ratio*100:.1f}%")
        print("-" * 60)
        
        # 检查单标仓位
        self._check_position_limits(portfolio)
        
        # 检查整体仓位
        self._check_total_position(portfolio)
        
        # 检查现金储备
        self._check_cash_reserve(portfolio)
        
        # 输出结果
        print("\n" + "=" * 60)
        if self.errors:
            print(f"❌ 发现 {len(self.errors)} 个严重违规:")
            for err in self.errors:
                print(f"   [错误] {err}")
        
        if self.warnings:
            print(f"⚠️  发现 {len(self.warnings)} 个警告:")
            for warn in self.warnings:
                print(f"   [警告] {warn}")
        
        if not self.errors and not self.warnings:
            print("✅ 所有风控检查通过！")
        
        print("=" * 60)
        
        return len(self.errors) == 0
    
    def _check_position_limits(self, portfolio: Portfolio):
        """检查单标仓位限制"""
        limits = self.config.get('position_limits', {})
        
        for pos in portfolio.positions:
            position_ratio = pos.market_value / portfolio.total_assets
            strategy = pos.strategy
            
            if strategy in limits:
                max_limit = limits[strategy].get('single_stock_max', 0.10)
                
                if position_ratio > max_limit:
                    self.errors.append(
                        f"{pos.name}({pos.code}) 仓位 {position_ratio*100:.1f}% "
                        f"超过 {strategy} 限制 {max_limit*100:.1f}%"
                    )
                elif position_ratio > max_limit * 0.9:
                    self.warnings.append(
                        f"{pos.name}({pos.code}) 仓位 {position_ratio*100:.1f}% "
                        f"接近 {strategy} 限制 {max_limit*100:.1f}%"
                    )
    
    def _check_total_position(self, portfolio: Portfolio):
        """检查总仓位"""
        total_ratio = portfolio.total_market_value / portfolio.total_assets
        max_total = self.config.get('market_risk', {}).get('总仓位上限', 0.90)
        
        if total_ratio > max_total:
            self.errors.append(
                f"总仓位 {total_ratio*100:.1f}% 超过上限 {max_total*100:.1f}%"
            )
    
    def _check_cash_reserve(self, portfolio: Portfolio):
        """检查现金储备"""
        min_cash = self.config.get('market_risk', {}).get('现金储备下限', 0.10)
        
        if portfolio.cash_ratio < min_cash:
            self.errors.append(
                f"现金比例 {portfolio.cash_ratio*100:.1f}% 低于下限 {min_cash*100:.1f}%"
            )
    
    def check_stop_loss(self, position: Position) -> List[str]:
        """
        检查止损条件
        :param position: 持仓
        :return: 触发条件列表
        """
        triggers = []
        
        # 烟蒂股止损
        if position.strategy == "烟蒂股型":
            if position.pnl_pct < -15:
                triggers.append(f"亏损 {position.pnl_pct:.1f}% > -15%，建议评估止损")
        
        # 通用止损
        if position.pnl_pct < -20:
            triggers.append(f"亏损 {position.pnl_pct:.1f}% > -20%，触发硬止损")
        
        return triggers


def demo():
    """演示用例"""
    # 创建示例持仓
    portfolio = Portfolio(
        total_assets=150000,  # 15万总资产
        positions=[
            Position("1288.HK", "农业银行", "纯硬收息型", 70000, 3.0, 3.25),
            Position("1122.HK", "庆铃汽车", "烟蒂股型", 7500, 0.55, 0.50),
            Position("3988.HK", "中国银行", "纯硬收息型", 30000, 2.8, 3.0),
        ]
    )
    
    # 运行验证
    validator = RiskValidator()
    validator.validate(portfolio)
    
    # 检查止损
    print("\n止损检查:")
    for pos in portfolio.positions:
        triggers = validator.check_stop_loss(pos)
        if triggers:
            print(f"  {pos.name}: {triggers}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        demo()
    else:
        print("用法: python risk_validator.py --demo")
        print("运行演示用例查看功能")
        demo()
