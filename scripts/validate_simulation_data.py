# -*- coding: utf-8 -*-
"""
模拟组合数据硬约束验证脚本 V2.0 (纯标准库版)

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

import sys
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "decision-tracking" / "simulation_state.json"
TRADES_FILE = ROOT / "decision-tracking" / "simulation_trades.csv"
DASHBOARD_FILE = ROOT / "decision-tracking" / "dashboard_snapshot.json"
PUBLIC_DASHBOARD_FILE = ROOT / "public" / "dashboard" / "dashboard_snapshot.json"

INITIAL_CAPITAL = 500000.0


def load_state() -> dict:
    if not STATE_FILE.exists():
        print("[ERROR] state文件不存在: %s" % STATE_FILE)
        sys.exit(1)
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def load_trades() -> list[dict]:
    if not TRADES_FILE.exists():
        print("[ERROR] 交易记录不存在: %s" % TRADES_FILE)
        sys.exit(1)
    with open(TRADES_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def validate_trades_structure(trades: list[dict]) -> list[str]:
    errors = []
    if not trades:
        errors.append("trades.csv 为空")
        return errors
    required_cols = ["date", "ticker", "name", "code", "action", "price", "shares", "amount"]
    headers = trades[0].keys()
    for col in required_cols:
        if col not in headers:
            errors.append("trades.csv缺少必要列: %s" % col)
    return errors


def validate_init_trades(trades: list[dict]) -> list[str]:
    errors = []
    init_trades = [t for t in trades if t.get("action") == "INIT_BUY"]
    expected_tickers = {"1522.HK", "87001.HK", "0882.HK", "3320.HK"}
    actual_tickers = {t["ticker"] for t in init_trades}
    
    for ticker in expected_tickers:
        if ticker not in actual_tickers:
            errors.append("缺少初始交易记录: %s" % ticker)
    
    for row in init_trades:
        code = str(row.get("code", ""))
        if not code:
            errors.append("交易记录缺少code: %s" % row.get("ticker"))
    
    return errors


def validate_state_trades_consistency(state: dict, trades: list[dict]) -> list[str]:
    errors = []
    positions = state.get("positions", {})
    init_trades = [t for t in trades if t.get("action") == "INIT_BUY"]
    
    for row in init_trades:
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
        
        if abs(state_price - trade_price) > 0.01:
            errors.append(
                "成本价不一致: %s state=%.3f, trades=%.3f" % (ticker, state_price, trade_price)
            )
        
        if state_shares != trade_shares:
            errors.append(
                "持股数不一致: %s state=%d, trades=%d" % (ticker, state_shares, trade_shares)
            )
        
        if state_code != trade_code:
            errors.append(
                "code不一致: %s state=%s, trades=%s" % (ticker, state_code, trade_code)
            )
    
    return errors


def validate_cash_calculation(state: dict, trades: list[dict]) -> list[str]:
    errors = []
    state_cash = float(state.get("cash", 0))
    
    buy_actions = {"INIT_BUY", "BUY_OPEN", "BUY_ADD"}
    total_spent = sum(
        float(t["amount"]) for t in trades if t.get("action") in buy_actions
    )
    sell_actions = {"SELL", "SELL_CLOSE"}
    total_received = sum(
        float(t["amount"]) for t in trades if t.get("action") in sell_actions
    )
    
    expected_cash = INITIAL_CAPITAL - total_spent + total_received
    
    if abs(state_cash - expected_cash) > 1:
        errors.append(
            "现金计算错误: state=%.2f, 应为 %.2f (投入 %.2f, 回收 %.2f)" % 
            (state_cash, expected_cash, total_spent, total_received)
        )
    
    return errors


def validate_position_completeness(state: dict) -> list[str]:
    errors = []
    positions = state.get("positions", {})
    required_fields = ["name", "code", "ticker", "shares", "avg_cost", "sell_trigger", "lot_size"]
    
    for ticker, pos in positions.items():
        if int(pos.get("shares", 0)) <= 0:
            continue
        
        for field in required_fields:
            val = pos.get(field)
            if val is None or str(val) == "":
                errors.append("持仓字段缺失: %s 缺少 %s" % (ticker, field))
    
    return errors


def validate_dashboard_sync() -> list[str]:
    errors = []
    if not DASHBOARD_FILE.exists():
        errors.append("dashboard_snapshot.json 不存在")
        return errors
    if not PUBLIC_DASHBOARD_FILE.exists():
        errors.append("public/dashboard/dashboard_snapshot.json 不存在 ⭐易遗漏")
        return errors
    
    dashboard_content = DASHBOARD_FILE.read_text(encoding="utf-8")
    public_content = PUBLIC_DASHBOARD_FILE.read_text(encoding="utf-8")
    
    if dashboard_content != public_content:
        errors.append("dashboard_snapshot.json 与 public/dashboard/ 不同步 ⭐易遗漏")
    
    if "recent_actions" not in dashboard_content:
        errors.append("dashboard_snapshot.json 缺少 recent_actions 字段")
    
    return errors


def run_validation() -> int:
    print("=" * 60)
    print("[验证] 模拟组合数据硬约束验证 V2.0")
    print("=" * 60)
    
    state = load_state()
    trades = load_trades()
    
    print("[OK] 数据加载成功")
    print("   - 持仓数量: %d" % len(state.get("positions", {})))
    print("   - 交易记录: %d 条" % len(trades))
    print()
    
    all_errors = []
    checks = [
        ("trades.csv结构检查", validate_trades_structure(trades)),
        ("初始交易记录检查", validate_init_trades(trades)),
        ("state与trades一致性检查", validate_state_trades_consistency(state, trades)),
        ("现金计算检查", validate_cash_calculation(state, trades)),
        ("持仓字段完整性检查", validate_position_completeness(state)),
        ("Dashboard同步检查", validate_dashboard_sync()),
    ]
    
    print("[检查] 执行数据一致性检查...")
    for name, errors in checks:
        all_errors.extend(errors)
        if errors:
            print("   [FAIL] %s失败" % name)
            for e in errors:
                print("          - %s" % e)
        else:
            print("   [OK] %s通过" % name)
    
    print()
    
    if all_errors:
        print("=" * 60)
        print("[FAIL] 发现 %d 个数据问题，需要人工修复" % len(all_errors))
        print("=" * 60)
        return 1
    
    print("=" * 60)
    print("[PASS] 所有检查通过，数据一致性良好")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(run_validation())
