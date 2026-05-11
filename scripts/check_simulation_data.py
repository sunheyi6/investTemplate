# -*- coding: utf-8 -*-
"""检查模拟持仓数据一致性"""

import json
import csv
import os

os.chdir(r'D:\product\investTemplate')

# 加载state
with open('decision-tracking/simulation_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)

# 加载trades
trades = []
with open('decision-tracking/simulation_trades.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        trades.append(row)

# 加载snapshot
snapshots = []
try:
    with open('decision-tracking/simulation_daily_snapshot.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            snapshots.append(row)
except:
    pass

initial_capital = 500000.0
state_cash = float(state['cash'])
positions = state['positions']

print('=' * 70)
print('【模拟持仓数据核查报告】')
print('=' * 70)
print()
print('初始资金: {:,.2f}'.format(initial_capital))
print('state现金: {:,.2f}'.format(state_cash))
print()

# 1. 检查trades
print('-' * 70)
print('【1. 交易记录核查 (simulation_trades.csv)】')
print('-' * 70)
total_spent = 0
issues_found = []

for t in trades:
    if t['action'] in ['INIT_BUY', 'BUY_OPEN', 'BUY_ADD']:
        ticker = t['ticker']
        name = t['name']
        price = float(t['price'])
        shares = int(t['shares'])
        amount = float(t['amount'])
        cash_after = float(t['cash_after'])
        total_spent += amount
        print()
        print('{} {}:'.format(ticker, name))
        print('  买入: {:,}股 x {} = {:,.2f}'.format(shares, price, amount))
        print('  交易后现金: {:,.2f}'.format(cash_after))
        
        # 检查与state是否一致
        if ticker in positions:
            pos = positions[ticker]
            state_shares = int(pos['shares'])
            state_cost = float(pos['avg_cost'])
            state_code = pos['code']
            trade_code = t['code']
            
            issues = []
            if state_shares != shares:
                issues.append('持股数不一致(state={})'.format(state_shares))
            if abs(state_cost - price) > 0.001:
                issues.append('成本价不一致(state={})'.format(state_cost))
            if state_code != trade_code:
                issues.append('code不一致(state={}, trade={})'.format(state_code, trade_code))
            
            if issues:
                print('  [问题] 与state不一致:', ', '.join(issues))
                issues_found.extend(issues)
            else:
                print('  [OK] 与state一致')
        else:
            print('  [问题] state中无此持仓!')
            issues_found.append('{} state中无持仓'.format(ticker))

print()
expected_cash = initial_capital - total_spent
print('累计投入: {:,.2f}'.format(total_spent))
print('应有现金: {:,.2f}'.format(expected_cash))
print('state现金: {:,.2f}'.format(state_cash))
if abs(state_cash - expected_cash) > 1:
    print('[问题] 现金差异: {:,.2f}'.format(state_cash - expected_cash))
    issues_found.append('现金差异: {}'.format(state_cash - expected_cash))
else:
    print('[OK] 现金一致')

# 2. 检查snapshot
print()
print('-' * 70)
print('【2. 每日快照核查 (simulation_daily_snapshot.csv)】')
print('-' * 70)
if snapshots:
    print('快照数量: {} 条'.format(len(snapshots)))
    print()
    
    # 按日期分组
    from collections import defaultdict
    by_date = defaultdict(list)
    for s in snapshots:
        by_date[s['date']].append(s)
    
    print('按日期查看:')
    for date in sorted(by_date.keys()):
        day_snapshots = by_date[date]
        print()
        print('{}: {} 条记录'.format(date, len(day_snapshots)))
        
        for s in day_snapshots:
            ticker = s['ticker']
            name = s['name']
            close = float(s['close'])
            shares = int(s['shares'])
            avg_cost = float(s['avg_cost'])
            market_value = float(s['market_value'])
            unrealized_pnl = float(s['unrealized_pnl'])
            cash = float(s['cash_after'])
            net_value = float(s['net_value'])
            
            # 验证市值计算
            calc_mv = shares * close
            mv_ok = abs(calc_mv - market_value) <= 1
            
            # 验证浮动盈亏
            calc_pnl = shares * (close - avg_cost)
            pnl_ok = abs(calc_pnl - unrealized_pnl) <= 1
            
            mv_status = 'OK' if mv_ok else '市值计算错误(应为{:,.2f})'.format(calc_mv)
            pnl_status = 'OK' if pnl_ok else '盈亏计算错误(应为{:,.2f})'.format(calc_pnl)
            
            if not mv_ok or not pnl_ok:
                print('  {}: 价{} x 股{} = 市值{:,.2f} [{}], 盈亏{:,.2f} [{}], 现金{:,.2f}'.format(
                    ticker, close, shares, market_value, mv_status, unrealized_pnl, pnl_status, cash))
                if not mv_ok:
                    issues_found.append('{} {} 市值计算错误'.format(date, ticker))
                if not pnl_ok:
                    issues_found.append('{} {} 盈亏计算错误'.format(date, ticker))
else:
    print('[注意] 无快照数据')

# 3. 持仓完整性检查
print()
print('-' * 70)
print('【3. 持仓完整性检查】')
print('-' * 70)
required_fields = ['name', 'code', 'ticker', 'shares', 'avg_cost', 'sell_trigger', 'lot_size']
for ticker, pos in positions.items():
    shares = int(pos.get('shares', 0))
    if shares <= 0:
        continue
    
    missing = []
    for field in required_fields:
        if field not in pos or pos[field] is None or str(pos[field]) == '':
            missing.append(field)
    
    if missing:
        print('{}: [问题] 缺少字段 {}'.format(ticker, missing))
        issues_found.append('{} 缺少字段 {}'.format(ticker, missing))
    else:
        print('{} {}: {}股 @ {} (卖出触发价: {}) [OK]'.format(
            ticker, pos['name'], shares, pos['avg_cost'], pos['sell_trigger']))

# 4. 数据问题汇总
print()
print('=' * 70)
if issues_found:
    print('【核查结果】发现 {} 个问题:'.format(len(issues_found)))
    for i, issue in enumerate(issues_found, 1):
        print('  {}. {}'.format(i, issue))
else:
    print('【核查结果】所有检查通过，数据一致性良好')
print('=' * 70)
