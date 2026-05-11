# -*- coding: utf-8 -*-
"""修正模拟持仓数据 - 按3月26日收盘价重新计算"""

import json
import csv
import os
from pathlib import Path

os.chdir(r'D:\product\investTemplate')

# 3月26日收盘价（用户确认）
CLOSE_0326 = {
    '1522.HK': {'name': '京投交通科技', 'code': '01522', 'close': 0.295},
    '87001.HK': {'name': '汇贤产业信托', 'code': '87001', 'close': 0.432},  # 人民币
    '0882.HK': {'name': '天津发展', 'code': '00882', 'close': 2.55},
    '3320.HK': {'name': '华润医药', 'code': '03320', 'close': 5.33},
}

INITIAL_CAPITAL = 500000.0

# 持仓配置（股数保持不变）
POSITIONS_CONFIG = {
    '1522.HK': {'shares': 342000, 'lot_size': 1000, 'position_type': '核心', 'sell_trigger': 0.6},
    '87001.HK': {'shares': 250000, 'lot_size': 1000, 'position_type': '核心', 'sell_trigger': 1.0},
    '0882.HK': {'shares': 40000, 'lot_size': 1000, 'position_type': '核心', 'sell_trigger': 4.5},
    '3320.HK': {'shares': 15000, 'lot_size': 1000, 'position_type': '卫星', 'sell_trigger': 9.0},
}

print('=' * 70)
print('【修正模拟持仓数据】')
print('按3月26日收盘价重新计算成本')
print('=' * 70)
print()

# 1. 重新生成 trades.csv
print('1. 重新生成 simulation_trades.csv')
trades = []
total_spent = 0
cash_remaining = INITIAL_CAPITAL

for ticker, config in POSITIONS_CONFIG.items():
    close_price = CLOSE_0326[ticker]['close']
    shares = config['shares']
    name = CLOSE_0326[ticker]['name']
    code = CLOSE_0326[ticker]['code']
    amount = shares * close_price
    total_spent += amount
    cash_remaining -= amount
    
    trades.append({
        'date': '2026-03-26',
        'ticker': ticker,
        'name': name,
        'code': code,
        'action': 'INIT_BUY',
        'price': close_price,
        'shares': shares,
        'amount': amount,
        'cash_after': cash_remaining,
        'reason': '初始建仓（3月26日收盘价）'
    })
    
    print('  {}: {:,}股 @ {} = {:,.2f}'.format(ticker, shares, close_price, amount))

print()
print('  累计投入: {:,.2f}'.format(total_spent))
print('  剩余现金: {:,.2f}'.format(cash_remaining))

# 写入 trades.csv
with open('decision-tracking/simulation_trades.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['date', 'ticker', 'name', 'code', 'action', 'price', 'shares', 'amount', 'cash_after', 'reason'])
    writer.writeheader()
    writer.writerows(trades)
print('  [OK] trades.csv 已更新')
print()

# 2. 重新生成 state.json
print('2. 重新生成 simulation_state.json')

positions = {}
for ticker, config in POSITIONS_CONFIG.items():
    close_price = CLOSE_0326[ticker]['close']
    positions[ticker] = {
        'name': CLOSE_0326[ticker]['name'],
        'code': CLOSE_0326[ticker]['code'],
        'ticker': ticker,
        'shares': config['shares'],
        'avg_cost': close_price,  # 修正为收盘价
        'sell_trigger': config['sell_trigger'],
        'lot_size': config['lot_size'],
        'position_type': config['position_type'],
        'realized_pnl': 0.0
    }
    print('  {}: 成本价 {} -> {}'.format(ticker, close_price, close_price))

# 添加空仓标的（用于监控）
watchlist = {
    '0696.HK': {'name': '中国民航信息网络', 'code': '00696', 'sell_trigger': 0, 'target_buy': None},
    '2669.HK': {'name': '中海物业', 'code': '02669', 'sell_trigger': 0, 'target_buy': None},
    '6049.HK': {'name': '保利物业', 'code': '06049', 'sell_trigger': 0, 'target_buy': None},
    '002027.SZ': {'name': '分众传媒', 'code': '002027', 'sell_trigger': 8.37, 'target_buy': 6.2},
    '3613.HK': {'name': '同仁堂国药', 'code': '03613', 'sell_trigger': 0, 'target_buy': None},
    '6862.HK': {'name': '海底捞', 'code': '06862', 'sell_trigger': 13.5, 'target_buy': 10.0},
    '002714.SZ': {'name': '牧原股份', 'code': '002714', 'sell_trigger': 60.426, 'target_buy': 44.76},
    '2869.HK': {'name': '绿城服务', 'code': '02869', 'sell_trigger': 0, 'target_buy': None},
    '2319.HK': {'name': '蒙牛乳业', 'code': '02319', 'sell_trigger': 22.0, 'target_buy': 11.0},
    '1502.HK': {'name': '金融街物业', 'code': '01502', 'sell_trigger': 0, 'target_buy': None},
    '600600.SS': {'name': '青岛啤酒', 'code': '600600', 'sell_trigger': 70.2, 'target_buy': 52.0},
}

for ticker, info in watchlist.items():
    lot_size = 100 if '.SZ' in ticker or '.SS' in ticker else 1000
    positions[ticker] = {
        'name': info['name'],
        'code': info['code'],
        'ticker': ticker,
        'shares': 0,
        'avg_cost': 0.0,
        'sell_trigger': info['sell_trigger'],
        'target_buy': info['target_buy'],
        'lot_size': lot_size,
        'realized_pnl': 0.0
    }

state = {
    'template_version': 'V5.5.12',
    'engine_version': 'V3.0',
    'initial_capital': INITIAL_CAPITAL,
    'cash': cash_remaining,
    'last_trade_date': '2026-03-26',
    'positions': positions
}

with open('decision-tracking/simulation_state.json', 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)
print('  [OK] state.json 已更新')
print()

# 3. 重新生成 snapshot.csv
print('3. 重新生成 simulation_daily_snapshot.csv')

snapshots = []
for ticker, config in POSITIONS_CONFIG.items():
    close_price = CLOSE_0326[ticker]['close']
    shares = config['shares']
    name = CLOSE_0326[ticker]['name']
    code = CLOSE_0326[ticker]['code']
    market_value = shares * close_price
    
    snapshots.append({
        'date': '2026-03-26',
        'ticker': ticker,
        'name': name,
        'code': code,
        'close': close_price,
        'prev_close': close_price,
        'change_pct': 0.0,
        'shares': shares,
        'avg_cost': close_price,
        'action': 'INIT',
        'action_shares': 0,
        'action_price': 0.0,
        'action_amount': 0.0,
        'market_value': market_value,
        'unrealized_pnl': 0.0,
        'cash_after': cash_remaining,
        'net_value': total_spent + cash_remaining,
        'total_return_pct': 0.0
    })

with open('decision-tracking/simulation_daily_snapshot.csv', 'w', newline='', encoding='utf-8') as f:
    fieldnames = ['date', 'ticker', 'name', 'code', 'close', 'prev_close', 'change_pct', 
                  'shares', 'avg_cost', 'action', 'action_shares', 'action_price', 
                  'action_amount', 'market_value', 'unrealized_pnl', 'cash_after', 
                  'net_value', 'total_return_pct']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(snapshots)
print('  [OK] snapshot.csv 已更新')
print()

print('=' * 70)
print('【修正完成】')
print('=' * 70)
print()
print('新的持仓成本（按3月26日收盘价）:')
for ticker in POSITIONS_CONFIG:
    name = CLOSE_0326[ticker]['name']
    price = CLOSE_0326[ticker]['close']
    shares = POSITIONS_CONFIG[ticker]['shares']
    print('  {} {}: {:,}股 @ {} = {:,.2f}'.format(ticker, name, shares, price, shares*price))
print()
print('初始净值: {:,.2f}'.format(INITIAL_CAPITAL))
print('剩余现金: {:,.2f}'.format(cash_remaining))
