# -*- coding: utf-8 -*-
"""
VIX定投策略更新脚本 V1.2
买卖：每两周周二
收益：每日更新
"""

import argparse
import json
import csv
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "08-决策追踪" / "vix_dca_strategy"

CONFIG_FILE = STRATEGY_DIR / "strategy_config.json"
TRADES_FILE = STRATEGY_DIR / "trades.csv"
SNAPSHOT_FILE = STRATEGY_DIR / "daily_snapshot.csv"
STATE_FILE = STRATEGY_DIR / "state.json"


def main():
    parser = argparse.ArgumentParser(description='VIX定投策略更新')
    parser.add_argument('--date', required=True, help='日期')
    parser.add_argument('--vix', type=float, required=True, help='VIX')
    parser.add_argument('--price', type=float, required=True, help='价格')
    parser.add_argument('--dry-run', action='store_true', help='试运行')
    args = parser.parse_args()
    
    # 加载数据
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        state = json.load(f)
    
    vix, price, date = args.vix, args.price, args.date
    
    # 判断是否为定投日
    dt = datetime.strptime(date, '%Y-%m-%d')
    is_trading = (dt.weekday() == 1 and date in ['2026-04-07', '2026-04-21', '2026-05-05', '2026-05-19'])
    reason = "定投日" if is_trading else "非定投日"
    
    print(f"=== VIX定投策略更新 ({date}) ===")
    print(f"VIX: {vix}, 价格: {price}, 类型: {reason}")
    print()
    
    # 获取前一日收益
    prev_unrealized = state['position'].get('unrealized_pnl', 0)
    
    if is_trading:
        print("===== 定投日：执行买卖 =====")
        # 买入逻辑
        buy_amount = 0
        if vix >= 30:
            buy_amount = 6000
            label = "加倍定投"
        elif vix >= 25:
            buy_amount = 4500
            label = "加大定投"
        elif vix >= 20:
            buy_amount = 3000
            label = "标准定投"
        
        if buy_amount > 0:
            print(f"[买入] {label}: {buy_amount}元")
            cash_before = state['account']['cash']
            fee = max(0.01, buy_amount * 0.0001)
            actual = buy_amount - fee
            shares = int(actual / price)
            total_cost = shares * price + fee
            cash_after = cash_before - total_cost
            
            print(f"  买入{shares}份 @ {price}元")
            
            state['position']['shares'] += shares
            state['position']['total_cost'] += total_cost
            state['position']['avg_cost'] = state['position']['total_cost'] / state['position']['shares']
            state['account']['cash'] = cash_after
            state['statistics']['cumulative_buy'] += buy_amount
            state['statistics']['buy_count'] += 1
            
            # 记录交易
            if not args.dry_run:
                with open(TRADES_FILE, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    net_value = state['position']['shares'] * price + cash_after
                    writer.writerow([date, vix, get_vix_zone(vix), "BUY", buy_amount, shares, 
                                   price, fee, total_cost, cash_before, cash_after, net_value, label])
        else:
            print("[持有] VIX<20，暂停定投")
    else:
        print("===== 非定投日：只更新收益 =====")
    
    # ========== 每日更新收益（无论是否定投日）==========
    print()
    print("===== 更新收益 =====")
    
    pos = state['position']
    acc = state['account']
    
    # 计算收益
    position_value = pos['shares'] * price
    net_value = position_value + acc['cash']
    total_cost = pos['total_cost']
    unrealized = position_value - total_cost if total_cost > 0 else 0
    return_pct = (unrealized / total_cost * 100) if total_cost > 0 else 0
    daily_pnl = unrealized - prev_unrealized
    
    print(f"持仓: {pos['shares']}份")
    print(f"市值: {position_value:.2f}元")
    print(f"成本: {total_cost:.2f}元")
    print(f"收益: {unrealized:+.2f}元 ({return_pct:+.2f}%)")
    print(f"当日: {daily_pnl:+.2f}元")
    
    # 更新状态
    pos['current_price'] = price
    pos['market_value'] = position_value
    pos['unrealized_pnl'] = unrealized
    pos['return_pct'] = return_pct
    
    state['daily_performance'] = {
        'date': date,
        'vix': vix,
        'daily_pnl': daily_pnl,
        'total_pnl': unrealized,
        'total_return_pct': (net_value - 100000) / 100000 * 100
    }
    
    # 更新快照（每日都记录）
    if not args.dry_run:
        with open(SNAPSHOT_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            note = f"VIX{vix},持仓{pos['shares']}份"
            note += ",定投日" if is_trading else ",持仓不动"
            writer.writerow([date, vix, price, pos['shares'], position_value, acc['cash'], 
                           net_value, total_cost, unrealized, daily_pnl, return_pct, note])
        
        # 保存状态
        acc['last_update'] = date
        if vix > state['history'].get('vix_high', 0):
            state['history']['vix_high'] = vix
            state['history']['vix_high_date'] = date
        if vix < state['history'].get('vix_low', 999):
            state['history']['vix_low'] = vix
            state['history']['vix_low_date'] = date
        
        save_state(state)
        print()
        print("[已保存] 收益数据已更新")
    else:
        print()
        print("[试运行] 数据未保存")
    
    return 0


def get_vix_zone(vix):
    if vix >= 30: return ">=30"
    elif vix >= 25: return "25-30"
    elif vix >= 20: return "20-25"
    elif vix >= 15: return "15-20"
    elif vix >= 12: return "12-15"
    elif vix >= 10: return "10-12"
    else: return "<10"


def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    import sys
    sys.exit(main())
