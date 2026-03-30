# -*- coding: utf-8 -*-
"""
模拟组合数据硬约束验证脚本 V1.1 (只读版)

核心原则：
1. 只读验证：不修改任何数据，只检测问题并报告
2. 失败即停：发现严重问题时返回非0退出码
3. 人工修复：所有问题都需要人工确认后修复

使用方式：
    python scripts/validate_simulation_data.py
    
返回码：
    0 - 验证通过
    1 - 发现错误，需要人工修复
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "08-决策追踪" / "simulation_state.json"
TRADES_FILE = ROOT / "08-决策追踪" / "simulation_trades.csv"

INITIAL_CAPITAL = 500000.0


def load_state() -> Dict:
    """加载state文件"""
    if not STATE_FILE.exists():
        print("[ERROR] state文件不存在: %s" % STATE_FILE)
        sys.exit(1)
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def load_trades() -> pd.DataFrame:
    """加载交易记录"""
    if not TRADES_FILE.exists():
        print("[ERROR] 交易记录不存在: %s" % TRADES_FILE)
        sys.exit(1)
    return pd.read_csv(TRADES_FILE, encoding="utf-8", dtype={'code': str})


def validate_trades_structure(trades: pd.DataFrame) -> List[str]:
    """验证trades.csv结构正确"""
    errors = []
    required_cols = ["date", "ticker", "name", "code", "action", "price", "shares", "amount"]
    for col in required_cols:
        if col not in trades.columns:
            errors.append("trades.csv缺少必要列: %s" % col)
    return errors


def validate_init_trades(trades: pd.DataFrame) -> List[str]:
    """验证初始交易记录完整"""
    errors = []
    init_trades = trades[trades["action"] == "INIT_BUY"]
    
    expected_tickers = ["1522.HK", "87001.HK", "0882.HK", "3320.HK"]
    actual_tickers = init_trades["ticker"].tolist()
    
    for ticker in expected_tickers:
        if ticker not in actual_tickers:
            errors.append("缺少初始交易记录: %s" % ticker)
    
    # 验证code列不为空
    for _, row in init_trades.iterrows():
        if pd.isna(row.get("code")) or str(row.get("code")) == "":
            errors.append("交易记录缺少code: %s" % row["ticker"])
    
    return errors


def validate_state_trades_consistency(state: Dict, trades: pd.DataFrame) -> List[str]:
    """验证state与trades一致性"""
    errors = []
    positions = state.get("positions", {})
    init_trades = trades[trades["action"] == "INIT_BUY"]
    
    for _, row in init_trades.iterrows():
        ticker = row["ticker"]
        trade_price = float(row["price"])
        trade_shares = int(row["shares"])
        trade_code = str(row["code"])
        
        if ticker not in positions:
            errors.append("持仓缺失: %s 有交易记录但不在state中" % ticker)
            continue
        
        pos = positions[ticker]
        state_price = float(pos.get("avg_cost", 0))
        state_shares = int(pos.get("shares", 0))
        state_code = str(pos.get("code", ""))
        
        # 检查成本价
        if abs(state_price - trade_price) > 0.01:
            errors.append(
                "成本价不一致: %s state=%.3f, trades=%.3f" % (ticker, state_price, trade_price)
            )
        
        # 检查持股数
        if state_shares != trade_shares:
            errors.append(
                "持股数不一致: %s state=%d, trades=%d" % (ticker, state_shares, trade_shares)
            )
        
        # 检查code
        if state_code != trade_code:
            errors.append(
                "code不一致: %s state=%s, trades=%s" % (ticker, state_code, trade_code)
            )
    
    return errors


def validate_cash_calculation(state: Dict, trades: pd.DataFrame) -> List[str]:
    """验证现金计算正确"""
    errors = []
    state_cash = float(state.get("cash", 0))
    
    buy_trades = trades[trades["action"].isin(["INIT_BUY", "BUY_OPEN", "BUY_ADD"])]
    total_spent = buy_trades["amount"].sum()
    
    expected_cash = INITIAL_CAPITAL - total_spent
    
    if abs(state_cash - expected_cash) > 1:
        errors.append(
            "现金计算错误: state=%.2f, 应为 %.2f (已投入 %.2f)" % 
            (state_cash, expected_cash, total_spent)
        )
    
    return errors


def validate_position_completeness(state: Dict) -> List[str]:
    """验证持仓字段完整"""
    errors = []
    positions = state.get("positions", {})
    
    required_fields = ["name", "code", "ticker", "shares", "avg_cost", "sell_trigger", "lot_size"]
    
    for ticker, pos in positions.items():
        if int(pos.get("shares", 0)) <= 0:
            continue  # 跳过无持仓的
        
        for field in required_fields:
            if field not in pos or pos[field] is None or str(pos[field]) == "":
                errors.append("持仓字段缺失: %s 缺少 %s" % (ticker, field))
    
    return errors


def run_validation() -> int:
    """主验证函数"""
    print("=" * 60)
    print("[验证] 模拟组合数据硬约束验证 V1.1")
    print("=" * 60)
    
    # 加载数据
    state = load_state()
    trades = load_trades()
    
    print("[OK] 数据加载成功")
    print("   - 持仓数量: %d" % len(state.get("positions", {})))
    print("   - 交易记录: %d 条" % len(trades))
    print()
    
    # 执行所有验证
    all_errors = []
    
    print("[检查] 执行数据一致性检查...")
    
    errors = validate_trades_structure(trades)
    all_errors.extend(errors)
    if errors:
        print("   [FAIL] trades.csv结构检查失败")
    else:
        print("   [OK] trades.csv结构检查通过")
    
    errors = validate_init_trades(trades)
    all_errors.extend(errors)
    if errors:
        print("   [FAIL] 初始交易记录检查失败")
    else:
        print("   [OK] 初始交易记录检查通过")
    
    errors = validate_state_trades_consistency(state, trades)
    all_errors.extend(errors)
    if errors:
        print("   [FAIL] state与trades一致性检查失败")
    else:
        print("   [OK] state与trades一致性检查通过")
    
    errors = validate_cash_calculation(state, trades)
    all_errors.extend(errors)
    if errors:
        print("   [FAIL] 现金计算检查失败")
    else:
        print("   [OK] 现金计算检查通过")
    
    errors = validate_position_completeness(state)
    all_errors.extend(errors)
    if errors:
        print("   [FAIL] 持仓字段完整性检查失败")
    else:
        print("   [OK] 持仓字段完整性检查通过")
    
    print()
    
    # 输出结果
    if all_errors:
        print("=" * 60)
        print("[FAIL] 发现 %d 个数据问题，需要人工修复:" % len(all_errors))
        print("=" * 60)
        for i, e in enumerate(all_errors, 1):
            print("  %d. %s" % (i, e))
        print()
        print("[提示] 请修复上述问题后再运行主脚本")
        return 1
    
    print("=" * 60)
    print("[PASS] 所有检查通过，数据一致性良好")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(run_validation())
