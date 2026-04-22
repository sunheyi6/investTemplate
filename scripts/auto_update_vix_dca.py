# -*- coding: utf-8 -*-
"""
VIX定投策略自动更新脚本 V1.0
自动获取VIX和ETF价格，每日更新收益
买卖：每两周周二（根据VIX值决定买入金额）
收益：每日更新（A股收盘后自动执行）
"""

import json
import csv
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

# 尝试导入数据获取库
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

try:
    import pandas as pd
except ImportError:
    # pandas是必须的
    pass

import urllib.request
import ssl

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "08-决策追踪" / "vix_dca_strategy"
PUBLIC_DIR = ROOT / "public" / "vix_strategy"
TEMPLATE_DIR = ROOT / "模拟持仓"

CONFIG_FILE = STRATEGY_DIR / "strategy_config.json"
STATE_FILE = STRATEGY_DIR / "state.json"
DASHBOARD_FILE = STRATEGY_DIR / "dashboard_data.json"
TRADES_FILE = STRATEGY_DIR / "trades.csv"
SNAPSHOT_FILE = STRATEGY_DIR / "daily_snapshot.csv"

# ETF代码
ETF_CODE = "513110"
ETF_NAME = "纳斯达克100 ETF"

# VIX雅虎财经代码
VIX_SYMBOL = "^VIX"


def get_vix_from_yfinance():
    """从yfinance获取VIX数据"""
    if not YFINANCE_AVAILABLE:
        return None
    try:
        vix = yf.Ticker(VIX_SYMBOL)
        # 获取最近5天数据，确保有数据返回
        hist = vix.history(period="5d", interval="1d")
        if hist is not None and not hist.empty:
            latest = hist.iloc[-1]
            # 获取实际日期
            date_str = pd.Timestamp(hist.index[-1]).strftime('%Y-%m-%d') if hasattr(hist.index[-1], 'strftime') else str(hist.index[-1])[:10]
            return {
                'value': round(float(latest['Close']), 2),
                'date': date_str
            }
    except Exception as e:
        print(f"[VIX] yfinance获取失败: {e}")
    return None


def get_etf_price_from_akshare(date_str=None):
    """从akshare获取ETF价格"""
    if not AKSHARE_AVAILABLE:
        return None
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            if date_str:
                df = ak.fund_etf_hist_em(symbol=ETF_CODE, period="daily",
                                          start_date=date_str.replace('-', ''),
                                          end_date=date_str.replace('-', ''), adjust='qfq')
            else:
                # 获取最近5天数据
                df = ak.fund_etf_hist_em(symbol=ETF_CODE, period="daily", adjust='qfq')
            
            if not df.empty:
                latest = df.iloc[-1]
                return {
                    'price': round(float(latest['收盘']), 3),
                    'date': latest['日期'] if '日期' in latest else date_str
                }
        except Exception as e:
            print(f"akshare获取ETF价格失败 (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(attempt)
    return None


def get_etf_price_from_yfinance():
    """从yfinance获取ETF价格（通过QQQ近似）"""
    if not YFINANCE_AVAILABLE:
        return None
    try:
        # 使用QQQ作为纳指100的参考（1份513110 ≈ 1/1000份QQQ，价格不同但走势一致）
        qqq = yf.Ticker("QQQ")
        hist = qqq.history(period="5d", interval="1d")
        if hist is not None and not hist.empty:
            latest = hist.iloc[-1]
            # QQQ和513110走势一致，但价格不同，这里仅用于获取涨跌幅度
            # 实际价格还是用A股收盘价
            prev = hist.iloc[-2] if len(hist) >= 2 else latest
            change_pct = (latest['Close'] / prev['Close'] - 1) if prev['Close'] else 0
            return {
                'price': round(float(latest['Close']), 2),
                'change_pct': change_pct,
                'date': hist.index[-1].strftime('%Y-%m-%d'),
                'is_proxy': True  # 标记为代理数据
            }
    except Exception as e:
        print(f"[ETF] yfinance获取ETF价格失败: {e}")
    return None


def get_vix_data():
    """获取VIX数据，尝试多种数据源"""
    # 尝试yfinance
    result = get_vix_from_yfinance()
    if result:
        print(f"[VIX] 从yfinance获取: {result['value']} ({result['date']})")
        return result['value']
    
    print("[VIX] 无法自动获取，请手动提供")
    return None


def get_etf_price(date_str=None):
    """获取ETF价格，尝试多种数据源"""
    target_date = date_str or datetime.now().strftime('%Y-%m-%d')
    
    # 优先尝试akshare fund_etf_spot_em（实时行情）
    result = get_etf_price_from_akshare(target_date)
    if result:
        print(f"[ETF] 从akshare spot获取: {result['price']} ({result['date']})")
        return result['price']
    
    # 尝试yfinance获取QQQ作为参考（虽然不能直接用价格，但可以用于验证）
    yf_result = get_etf_price_from_yfinance()
    if yf_result:
        print(f"[ETF] yfinance QQQ参考: {yf_result['price']} (涨跌: {yf_result['change_pct']*100:.2f}%)")
        print(f"[ETF] 注意：这是QQQ价格，不是513110的实际价格")
    
    print("[ETF] 无法自动获取513110的A股价格，请手动提供 --price 参数")
    return None


def get_last_known_etf_price(state):
    """Fallback: use last confirmed close from local state/snapshot."""
    try:
        current_price = float(state.get('position', {}).get('current_price', 0))
        if current_price > 0:
            return {
                'price': round(current_price, 3),
                'source': 'state.position.current_price',
                'date': state.get('account', {}).get('last_update', 'unknown')
            }
    except Exception:
        pass

    if SNAPSHOT_FILE.exists():
        try:
            with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
                rows = list(csv.reader(f))
            if len(rows) > 1:
                last = rows[-1]
                return {
                    'price': round(float(last[2]), 3),
                    'source': 'daily_snapshot.csv',
                    'date': last[0]
                }
        except Exception:
            pass

    return None


def load_json(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def is_trading_day(date_str, last_trade_date, next_trade_date):
    """判断是否为定投日（每两周周二）"""
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    
    # 必须是周二
    if dt.weekday() != 1:  # 1 = Tuesday
        return False

    # 若已配置next_trade_date，则仅在该日执行交易
    if next_trade_date:
        return date_str == next_trade_date
    
    # 回退逻辑：距离上次交易日约两周
    if last_trade_date:
        last = datetime.strptime(last_trade_date, '%Y-%m-%d')
        days_diff = (dt - last).days
        return days_diff >= 13  # 约两周
    
    return True


def build_upcoming_trade_dates(start_date_str, count=5):
    """从给定日期开始生成未来双周二日期列表。"""
    start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
    dates = []
    for i in range(count):
        dates.append((start_dt + timedelta(days=14 * i)).strftime('%Y-%m-%d'))
    return dates


def ensure_trade_schedule(state, ref_date_str):
    """确保state中的下次定投日期与日历列表完整且一致。"""
    stats = state.setdefault('statistics', {})
    schedule = state.setdefault('schedule', {})

    next_trade = get_next_trade_date(state)
    if not next_trade:
        ref_dt = datetime.strptime(ref_date_str, '%Y-%m-%d')
        days = (1 - ref_dt.weekday()) % 7
        if days == 0:
            days = 14
        next_trade = (ref_dt + timedelta(days=days)).strftime('%Y-%m-%d')

    stats['next_trade_date'] = next_trade
    schedule['next_trade_date'] = next_trade
    schedule['upcoming_trade_dates'] = build_upcoming_trade_dates(next_trade, count=5)


def roll_next_trade_schedule(state, executed_trade_date):
    """定投日成交后，滚动到下一次双周二。"""
    next_trade = (datetime.strptime(executed_trade_date, '%Y-%m-%d') + timedelta(days=14)).strftime('%Y-%m-%d')
    state.setdefault('statistics', {})['next_trade_date'] = next_trade
    schedule = state.setdefault('schedule', {})
    schedule['next_trade_date'] = next_trade
    schedule['upcoming_trade_dates'] = build_upcoming_trade_dates(next_trade, count=5)


def get_next_trade_date(state, ref_date_str=None):
    """兼容不同state结构，解析下次定投日；若已过期则自动滚动。"""
    schedule = state.get('schedule', {})
    next_trade = schedule.get('next_trade_date')

    today = ref_date_str or datetime.now().strftime('%Y-%m-%d')

    if next_trade:
        if next_trade < today:
            # 已过期，从过期日期开始不断加14天直到超过今天
            dt = datetime.strptime(next_trade, '%Y-%m-%d')
            while dt.strftime('%Y-%m-%d') <= today:
                dt += timedelta(days=14)
            next_trade = dt.strftime('%Y-%m-%d')
            schedule['next_trade_date'] = next_trade
            schedule['upcoming_trade_dates'] = build_upcoming_trade_dates(next_trade, count=5)
        return next_trade

    upcoming = schedule.get('upcoming_trade_dates', [])
    if isinstance(upcoming, list) and upcoming:
        return upcoming[0]

    return state.get('statistics', {}).get('next_trade_date')


def has_initial_capital_mode(state):
    """是否启用初始资金账户模式（默认关闭，按定投口径统计）。"""
    mode = str(state.get('account', {}).get('capital_mode', 'dca')).lower()
    return mode in ('fixed', 'initial_capital')


def get_tracking_principal(state):
    """收益率分母：有初始资金用初始资金，否则用累计投入本金。"""
    if has_initial_capital_mode(state):
        return float(state.get('account', {}).get('initial_capital', 0) or 0)

    # 定投口径：优先使用策略启动以来累计投入（从 start_date 开始累计）
    cumulative_buy = float(state.get('statistics', {}).get('cumulative_buy', 0) or 0)
    if cumulative_buy > 0:
        return cumulative_buy

    # 兼容历史数据：如果旧数据缺失 cumulative_buy，再退回当前持仓成本
    total_cost = float(state.get('position', {}).get('total_cost', 0) or 0)
    return total_cost


def get_total_assets_value(state, price=None):
    """总资产：持仓市值 + 现金（若存在初始资金账户）。"""
    pos = state.get('position', {})
    market_value = float(pos.get('market_value', 0) or 0)
    if price is not None:
        market_value = float(pos.get('shares', 0) or 0) * float(price)

    if has_initial_capital_mode(state):
        cash = float(state.get('account', {}).get('cash', 0) or 0)
        return market_value + cash

    return market_value


def get_vix_zone(vix):
    if vix >= 30: return ">=30"
    elif vix >= 25: return "25-30"
    elif vix >= 20: return "20-25"
    elif vix >= 15: return "15-20"
    elif vix >= 12: return "12-15"
    elif vix >= 10: return "10-12"
    else: return "<10"


def get_buy_amount(vix, config):
    """根据VIX值获取买入金额"""
    tiers = config['buy_rules']['tiers']
    for tier in tiers:
        if tier['vix_min'] <= vix < tier['vix_max']:
            return tier['amount'], tier['label']
    return 0, "持有不动"


def update_state(state, config, date_str, vix, price, is_trading):
    """更新状态文件"""
    prev_unrealized = state['position'].get('unrealized_pnl', 0)
    
    pos = state['position']
    acc = state['account']
    use_cash_account = has_initial_capital_mode(state)
    
    trade_executed = False
    trade_info = None
    
    if is_trading:
        buy_amount, label = get_buy_amount(vix, config)
        
        if buy_amount > 0:
            cash_before = float(acc.get('cash', 0) or 0)
            fee = max(0.01, buy_amount * 0.0001)
            actual = buy_amount - fee
            shares = int(actual / price)
            total_cost = shares * price + fee
            cash_after = cash_before - total_cost if use_cash_account else cash_before
            
            # 更新持仓
            pos['shares'] += shares
            pos['total_cost'] += total_cost
            pos['avg_cost'] = pos['total_cost'] / pos['shares']
            if use_cash_account:
                acc['cash'] = cash_after
            
            # 更新统计
            state['statistics']['cumulative_buy'] = float(state['statistics'].get('cumulative_buy', 0) or 0) + buy_amount
            state['statistics']['buy_count'] = int(state['statistics'].get('buy_count', 0) or 0) + 1
            state['statistics']['trade_count'] = int(state['statistics'].get('trade_count', 0) or 0) + 1
            state['statistics']['total_invested'] = float(state['statistics'].get('total_invested', 0) or 0) + buy_amount
            state['statistics']['last_trade_date'] = date_str
            roll_next_trade_schedule(state, date_str)
            
            trade_executed = True
            trade_info = {
                'date': date_str,
                'vix': vix,
                'action': 'BUY',
                'amount': buy_amount,
                'shares': shares,
                'price': price,
                'label': label
            }
            print(f"[交易] {label}: 买入{shares}份 @ {price}元，金额{buy_amount}元")
        else:
            print(f"[交易] VIX={vix} < 20，暂停定投")
            # 即使暂停定投，也要滚动下次定投日，否则日历会卡住
            roll_next_trade_schedule(state, date_str)
    
    # 更新每日收益（无论是否交易）
    position_value = pos['shares'] * price
    net_value = get_total_assets_value(state, price=price)
    total_cost = pos['total_cost']
    unrealized = position_value - total_cost if total_cost > 0 else 0
    return_pct = (unrealized / total_cost * 100) if total_cost > 0 else 0
    daily_pnl = unrealized - prev_unrealized
    principal = get_tracking_principal(state)
    total_return_pct = ((net_value - principal) / principal * 100) if principal > 0 else 0
    
    # 更新持仓数据
    pos['current_price'] = price
    pos['market_value'] = position_value
    pos['unrealized_pnl'] = unrealized
    pos['return_pct'] = round(return_pct, 2)
    
    # 更新每日表现
    state['daily_performance'] = {
        'date': date_str,
        'vix': vix,
        'daily_pnl': round(daily_pnl, 2),
        'total_pnl': round(unrealized, 2),
        'total_return_pct': round(total_return_pct, 2)
    }
    
    # 更新时间
    acc['last_update'] = date_str
    
    # 更新历史极值
    if vix > state['history'].get('vix_high', 0):
        state['history']['vix_high'] = vix
        state['history']['vix_high_date'] = date_str
    if vix < state['history'].get('vix_low', 999):
        state['history']['vix_low'] = vix
        state['history']['vix_low_date'] = date_str
    if unrealized > state['history'].get('max_unrealized_pnl', -999999):
        state['history']['max_unrealized_pnl'] = unrealized
        state['history']['max_unrealized_date'] = date_str
    
    return trade_executed, trade_info, {
        'daily_pnl': round(daily_pnl, 2),
        'unrealized': round(unrealized, 2),
        'return_pct': round(return_pct, 2),
        'net_value': round(net_value, 2)
    }


def update_dashboard_data(dashboard, state, date_str, vix, price, trade_info):
    """更新dashboard_data.json"""
    pos = state['position']
    acc = state['account']
    perf = state['daily_performance']
    stats = state['statistics']
    schedule = state.get('schedule', {})
    principal = get_tracking_principal(state)
    cash = float(acc.get('cash', 0) or 0)
    total_assets = get_total_assets_value(state)
    anchor_date = schedule.get('anchor_date', '未设置')
    next_trade_date = get_next_trade_date(state)
    days_until_next = None
    if next_trade_date:
        days_until_next = (datetime.strptime(next_trade_date, '%Y-%m-%d') - datetime.strptime(date_str, '%Y-%m-%d')).days
    
    dashboard['last_update'] = date_str
    dashboard['account'] = {
        'initial_capital': round(principal, 2),
        'cash': round(cash, 2),
        'total_assets': round(total_assets, 2)
    }
    dashboard['position'] = {
        'etf_code': ETF_CODE,
        'etf_name': ETF_NAME,
        'shares': pos['shares'],
        'avg_cost': round(pos['avg_cost'], 3),
        'current_price': price,
        'market_value': round(pos['market_value'], 2),
        'total_cost': round(pos['total_cost'], 2),
        'unrealized_pnl': round(pos['unrealized_pnl'], 2),
        'return_pct': pos['return_pct']
    }
    dashboard['performance'] = {
        'total_pnl': perf['total_pnl'],
        'total_return_pct': perf['total_return_pct'],
        'daily_pnl': perf['daily_pnl'],
        'vix': vix,
        'date': date_str
    }
    
    # 更新日历
    dashboard['schedule'] = {
        'frequency': '每两周周二',
        'last_trade_date': stats['last_trade_date'],
        'next_trade_date': next_trade_date,
        'days_until_next': days_until_next
    }
    
    # 添加交易记录
    if trade_info:
        dashboard['recent_trades'].insert(0, trade_info)
        dashboard['recent_trades'] = dashboard['recent_trades'][:5]  # 保留最近5条
    
    # 添加每日快照（去重：若当天已存在则替换）
    snaps = dashboard.get('daily_snapshots', [])
    snaps = [s for s in snaps if s.get('date') != date_str]
    snaps.insert(0, {
        'date': date_str,
        'price': price,
        'pnl': perf['total_pnl'],
        'daily_pnl': perf['daily_pnl']
    })
    dashboard['daily_snapshots'] = snaps[:5]  # 保留最近5天
    
    return dashboard


def update_markdown_template(state, date_str, vix, price):
    """更新Markdown展示文件"""
    template_path = TEMPLATE_DIR / "VIX定投策略.md"
    
    pos = state['position']
    acc = state['account']
    perf = state['daily_performance']
    stats = state['statistics']
    principal = get_tracking_principal(state)
    cash = float(acc.get('cash', 0) or 0)
    total_assets = get_total_assets_value(state)
    
    # 生成收益走势表格（最近5天）
    dashboard = load_json(DASHBOARD_FILE)
    snapshots = dashboard.get('daily_snapshots', [])
    if len(snapshots) > 5:
        snapshots = snapshots[:5]
    
    schedule = state.get('schedule', {})
    # 计算下次定投日
    next_trade = get_next_trade_date(state)
    days_until = (datetime.strptime(next_trade, '%Y-%m-%d') - datetime.strptime(date_str, '%Y-%m-%d')).days if next_trade else None
    upcoming_trades = schedule.get('upcoming_trade_dates', [])
    if not upcoming_trades and next_trade:
        upcoming_trades = [next_trade]
    anchor_date = schedule.get('anchor_date', '未设置')
    
    content = f"""# VIX定投策略 - 纳指100 ETF（**{ETF_CODE}**）

> **标的代码：{ETF_CODE}** | 策略版本：V1.0 | 启动日期：2026-03-24  
> **买卖执行：每两周周二** | **收益更新：每日** | 投入本金：{principal:,.2f}元
> **双周锚点：{anchor_date}（每双周周二定投）**

---

## 当前收益（{date_str}）

| 指标 | 数值 |
|------|------|
| **持仓份额** | {pos['shares']:,}份 |
| **平均成本** | {pos['avg_cost']:.3f}元 |
| **最新收盘价** | {price:.2f}元 |
| **持仓收益** | **{pos['unrealized_pnl']:+.2f}元 ({pos['return_pct']:+.2f}%)** {'✅' if pos['unrealized_pnl'] >= 0 else '⚠️'} |
| **总收益** | **{perf['total_pnl']:+.2f}元 ({perf['total_return_pct']:+.2f}%)** |
| **剩余现金** | {cash:,.2f}元 |
| **总资产** | {total_assets:,.2f}元 |

---

## 收益走势（最近5天）

| 日期 | 收盘价 | 当日盈亏 | 累计盈亏 | 收益率 |
|------|--------|----------|----------|--------|
"""
    
    # 添加历史数据行
    for snap in snapshots:
        snap_date = snap['date']
        snap_price = snap['price']
        snap_pnl = snap['pnl']
        snap_daily = snap['daily_pnl']
        snap_return = (snap_pnl / principal * 100) if principal > 0 else 0
        marker = "**" if snap_date == date_str else ""
        content += f"| {marker}{snap_date}{marker} | {marker}{snap_price:.2f}{marker} | {marker}{snap_daily:+.2f}{marker} | {marker}{snap_pnl:+.2f}{marker} | {marker}{snap_return:+.2f}%{marker} |\n"
    
    content += f"""
---

## 交易记录

| 日期 | VIX | 档位 | 操作 | 金额 | 持仓变化 | 价格 | 备注 |
|------|-----|------|------|------|----------|------|------|
"""
    
    # 添加交易记录（从dashboard获取）
    dashboard = load_json(DASHBOARD_FILE)
    for trade in dashboard.get('recent_trades', []):
        content += f"| {trade['date']} | {trade['vix']:.2f} | {get_vix_zone(trade['vix'])} | {trade['action']} | {trade['amount']:,}元 | +{trade['shares']}份 | {trade['price']:.2f}元 | {trade['label']} |\n"
    
    content += f"""
---

## 定投日历

| 日期 | 星期 | 状态 | 预计操作 |
|------|------|------|----------|
"""

    for trade_date in upcoming_trades[:5]:
        week = ['一', '二', '三', '四', '五', '六', '日'][datetime.strptime(trade_date, '%Y-%m-%d').weekday()]
        if trade_date == next_trade:
            status = "⏳ 等待"
            action = f"下次定投（{days_until}天后）" if days_until is not None else "待配置"
        else:
            status = "📅 计划中"
            action = "双周定投"
        content += f"| {trade_date} | {week} | {status} | {action} |\n"

    content += f"""

---

## 策略说明

**买入规则（定投日执行）：**
- VIX ≥ 30：加倍定投 6,000元
- 25 ≤ VIX < 30：加大定投 4,500元  
- 20 ≤ VIX < 25：标准定投 3,000元
- VIX < 20：暂停定投，持有观察

**卖出规则（VIX低位减仓）：**
- VIX < 10：大幅减仓 25%
- VIX < 12：中度减仓 15%
- VIX < 15：小幅减仓 10%

---

*最后更新：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    
    with open(template_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"[Markdown] 已更新: {template_path}")


def record_snapshot(date_str, vix, price, state, daily_pnl, note):
    """记录每日快照到CSV"""
    pos = state['position']
    acc = state['account']
    
    # 如果文件不存在，创建表头
    if not SNAPSHOT_FILE.exists():
        with open(SNAPSHOT_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['date', 'vix', 'price', 'shares', 'position_value', 
                           'cash', 'net_value', 'total_cost', 'unrealized_pnl', 
                           'daily_pnl', 'return_pct', 'note'])
    
    # 检查是否已存在
    existing = []
    if SNAPSHOT_FILE.exists():
        with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            existing = list(reader)
            # 检查日期是否已存在（跳过表头）
            for row in existing[1:]:
                if row and row[0] == date_str:
                    print(f"[快照] {date_str} 已存在，跳过")
                    return
    
    with open(SNAPSHOT_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        cash = float(acc.get('cash', 0) or 0)
        writer.writerow([
            date_str, vix, price, pos['shares'], pos['market_value'],
            cash, get_total_assets_value(state), pos['total_cost'],
            pos['unrealized_pnl'], daily_pnl, pos['return_pct'], note
        ])
    print(f"[快照] 已记录: {date_str}")


def record_trade(trade_info, state, date_str):
    """记录交易到CSV"""
    if not trade_info:
        return
    
    # 如果文件不存在，创建表头
    if not TRADES_FILE.exists():
        with open(TRADES_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['date', 'vix', 'vix_zone', 'action', 'amount', 
                           'shares', 'price', 'fee', 'total_cost', 
                           'cash_before', 'cash_after', 'net_value', 'label'])
    
    acc = state['account']
    cash = float(acc.get('cash', 0) or 0)
    net_value = get_total_assets_value(state)
    
    with open(TRADES_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            trade_info['date'], trade_info['vix'], get_vix_zone(trade_info['vix']),
            trade_info['action'], trade_info['amount'], trade_info['shares'],
            trade_info['price'], max(0.01, trade_info['amount'] * 0.0001),
            trade_info['amount'], cash + trade_info['amount'], cash,
            net_value, trade_info['label']
        ])
    print(f"[交易记录] 已记录: {date_str}")


def sync_to_public(state, dashboard):
    """同步数据到public目录供网页使用"""
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    public_file = PUBLIC_DIR / "dashboard_data.json"
    
    # 直接复制dashboard_data
    save_json(public_file, dashboard)
    print(f"[同步] 已同步到: {public_file}")


def main():
    parser = argparse.ArgumentParser(description='VIX定投策略自动更新')
    parser.add_argument('--date', help='日期 (YYYY-MM-DD)，默认今天')
    parser.add_argument('--vix', type=float, help='VIX值，默认自动获取')
    parser.add_argument('--price', type=float, help='ETF价格，默认自动获取')
    parser.add_argument('--dry-run', action='store_true', help='试运行不保存')
    parser.add_argument('--force', action='store_true', help='强制更新（即使今天已更新）')
    args = parser.parse_args()
    
    # 确定日期
    if args.date:
        date_str = args.date
    else:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    print(f"=== VIX定投策略自动更新 ({date_str}) ===")
    print(f"数据时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 加载配置和状态
    config = load_json(CONFIG_FILE)
    state = load_json(STATE_FILE)
    dashboard = load_json(DASHBOARD_FILE)
    ensure_trade_schedule(state, date_str)
    
    # 检查是否已更新
    if state.get('account', {}).get('last_update') == date_str and not args.force:
        print(f"[跳过] {date_str} 已更新，使用 --force 强制更新")
        return 0

    # 提前判断是否为定投日，供价格获取失败时决定是否允许兜底
    is_trading = is_trading_day(
        date_str,
        state['statistics'].get('last_trade_date'),
        get_next_trade_date(state)
    )
    
    # 获取VIX数据
    if args.vix is not None:
        vix = args.vix
        print(f"[VIX] 使用手动输入: {vix}")
    else:
        vix = get_vix_data()
        if vix is None:
            print("错误: 无法获取VIX数据，请使用 --vix 参数手动提供")
            return 1
    
    # 获取ETF价格
    if args.price is not None:
        price = args.price
        print(f"[ETF] 使用手动输入: {price}")
    else:
        price = get_etf_price(date_str)
        if price is None:
            fallback = get_last_known_etf_price(state)
            if fallback and not is_trading:
                price = fallback['price']
                print(f"[ETF] 自动获取失败，非定投日改用上次价格: {price} (来源: {fallback['source']}, 日期: {fallback['date']})")
            else:
                print("错误: 无法获取ETF价格，请使用 --price 参数手动提供")
                return 1
    
    print()
    print(f"=== 更新数据 ===")
    print(f"日期: {date_str}")
    print(f"VIX: {vix}")
    print(f"ETF价格: {price}")
    print()
    
    if is_trading:
        print(f"[定投日] 今天是定投日，将执行买入判断")
    else:
        print(f"[非定投日] 只更新收益，不执行交易")
    
    print()
    
    if args.dry_run:
        print("[试运行模式] 数据不会保存")
        print()
    
    # 更新状态
    trade_executed, trade_info, pnl_data = update_state(
        state, config, date_str, vix, price, is_trading
    )
    
    print(f"持仓: {state['position']['shares']}份")
    print(f"市值: {state['position']['market_value']:.2f}元")
    print(f"成本: {state['position']['total_cost']:.2f}元")
    print(f"收益: {state['position']['unrealized_pnl']:+.2f}元 ({state['position']['return_pct']:+.2f}%)")
    print(f"当日: {pnl_data['daily_pnl']:+.2f}元")
    print()
    
    if not args.dry_run:
        # 保存state.json
        save_json(STATE_FILE, state)
        print("[保存] state.json")
        
        # 更新dashboard
        dashboard = update_dashboard_data(dashboard, state, date_str, vix, price, trade_info)
        save_json(DASHBOARD_FILE, dashboard)
        print("[保存] dashboard_data.json")
        
        # 记录快照
        note = f"VIX{vix},定投日" if is_trading else f"VIX{vix},持仓不动"
        record_snapshot(date_str, vix, price, state, pnl_data['daily_pnl'], note)
        
        # 记录交易
        if trade_info:
            record_trade(trade_info, state, date_str)
        
        # 更新Markdown
        update_markdown_template(state, date_str, vix, price)
        
        # 同步到public目录
        sync_to_public(state, dashboard)
        
        print()
        print(f"=== 更新完成 ({date_str}) ===")
    else:
        print("[试运行] 数据未保存")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
