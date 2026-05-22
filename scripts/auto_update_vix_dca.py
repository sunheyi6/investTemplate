# -*- coding: utf-8 -*-
"""
VIX定投策略自动更新脚本 V2.0
完整策略实现：
  - 基础档位买入
  - 趋势修正（×0.7 / ×1.3 / ×1.0）
  - 封顶处理（VIX≥30时≤6000）
  - 极端风控（VIX≥35且上升：暂停买入+减仓5%）
  - 连续低VIX卖出（连续2期<15/12/10）
  - 恐慌回流（VIX重新≥25/30买回）
  - 应急补仓（盘中VIX≥32，月限1次）

自动获取VIX和ETF价格，每日更新收益。
买卖：每双周周二（根据VIX值决定买入金额）
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
    pass

import urllib.request
import ssl

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "decision-tracking" / "vix_dca_strategy"
PUBLIC_DIR = ROOT / "public" / "vix_strategy"
TEMPLATE_DIR = ROOT / "portfolio"

CONFIG_FILE = STRATEGY_DIR / "strategy_config.json"
STATE_FILE = STRATEGY_DIR / "state.json"
DASHBOARD_FILE = STRATEGY_DIR / "dashboard_data.json"
TRADES_FILE = STRATEGY_DIR / "trades.csv"
SNAPSHOT_FILE = STRATEGY_DIR / "daily_snapshot.csv"
DAILY_RETURNS_FILE = STRATEGY_DIR / "daily_returns.csv"
RETURNS_CURVE_SVG = STRATEGY_DIR / "returns_curve.svg"
RETURNS_CURVE_HTML = STRATEGY_DIR / "returns_curve.html"

# 08-决策追踪目录（数据一致性要求）
ALT_STRATEGY_DIR = ROOT / "08-决策追踪" / "vix_dca_strategy"

# ETF代码
ETF_CODE = "513110"
ETF_NAME = "纳斯达克100 ETF"

# VIX雅虎财经代码
VIX_SYMBOL = "^VIX"


# ==================== 数据获取 ====================

def get_vix_from_yfinance():
    """从yfinance获取VIX数据"""
    if not YFINANCE_AVAILABLE:
        return None
    try:
        vix = yf.Ticker(VIX_SYMBOL)
        hist = vix.history(period="5d", interval="1d")
        if hist is not None and not hist.empty:
            latest = hist.iloc[-1]
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
        qqq = yf.Ticker("QQQ")
        hist = qqq.history(period="5d", interval="1d")
        if hist is not None and not hist.empty:
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) >= 2 else latest
            change_pct = (latest['Close'] / prev['Close'] - 1) if prev['Close'] else 0
            return {
                'price': round(float(latest['Close']), 2),
                'change_pct': change_pct,
                'date': hist.index[-1].strftime('%Y-%m-%d'),
                'is_proxy': True
            }
    except Exception as e:
        print(f"[ETF] yfinance获取ETF价格失败: {e}")
    return None


def get_vix_data():
    """获取VIX数据，尝试多种数据源"""
    result = get_vix_from_yfinance()
    if result:
        print(f"[VIX] 从yfinance获取: {result['value']} ({result['date']})")
        return result['value']
    print("[VIX] 无法自动获取，请手动提供")
    return None


def get_etf_price(date_str=None):
    """获取ETF价格，尝试多种数据源"""
    target_date = date_str or datetime.now().strftime('%Y-%m-%d')
    result = get_etf_price_from_akshare(target_date)
    if result:
        print(f"[ETF] 从akshare获取: {result['price']} ({result['date']})")
        return result['price']
    
    yf_result = get_etf_price_from_yfinance()
    if yf_result:
        print(f"[ETF] yfinance QQQ参考: {yf_result['price']} (涨跌: {yf_result['change_pct']*100:.2f}%)")
        print(f"[ETF] 注意：这是QQQ价格，不是51310的实际价格")
    
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


# ==================== IO工具 ====================

def load_json(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ==================== 日期与定投日历 ====================

def is_trading_day(date_str, last_trade_date, next_trade_date):
    """判断是否为定投日（每两周周二）"""
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    if dt.weekday() != 1:  # 1 = Tuesday
        return False
    if next_trade_date:
        return date_str == next_trade_date
    if last_trade_date:
        last = datetime.strptime(last_trade_date, '%Y-%m-%d')
        days_diff = (dt - last).days
        return days_diff >= 13
    return True


def build_upcoming_trade_dates(start_date_str, count=5):
    """从给定日期开始生成未来双周二日期列表"""
    start_dt = datetime.strptime(start_date_str, '%Y-%m-%d')
    dates = []
    for i in range(count):
        dates.append((start_dt + timedelta(days=14 * i)).strftime('%Y-%m-%d'))
    return dates


def ensure_trade_schedule(state, ref_date_str):
    """确保state中的下次定投日期与日历列表完整且一致"""
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
    """定投日成交后，滚动到下一次双周二"""
    next_trade = (datetime.strptime(executed_trade_date, '%Y-%m-%d') + timedelta(days=14)).strftime('%Y-%m-%d')
    state.setdefault('statistics', {})['next_trade_date'] = next_trade
    schedule = state.setdefault('schedule', {})
    schedule['next_trade_date'] = next_trade
    schedule['upcoming_trade_dates'] = build_upcoming_trade_dates(next_trade, count=5)


def get_next_trade_date(state, ref_date_str=None):
    """兼容不同state结构，解析下次定投日；若已过期则自动滚动"""
    schedule = state.get('schedule', {})
    next_trade = schedule.get('next_trade_date')
    today = ref_date_str or datetime.now().strftime('%Y-%m-%d')
    if next_trade:
        if next_trade < today:
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


# ==================== 资产计算 ====================

def has_initial_capital_mode(state):
    mode = str(state.get('account', {}).get('capital_mode', 'dca')).lower()
    return mode in ('fixed', 'initial_capital')


def get_tracking_principal(state):
    if has_initial_capital_mode(state):
        return float(state.get('account', {}).get('initial_capital', 0) or 0)
    cumulative_buy = float(state.get('statistics', {}).get('cumulative_buy', 0) or 0)
    if cumulative_buy > 0:
        return cumulative_buy
    total_cost = float(state.get('position', {}).get('total_cost', 0) or 0)
    return total_cost


def get_total_assets_value(state, price=None):
    pos = state.get('position', {})
    market_value = float(pos.get('market_value', 0) or 0)
    if price is not None:
        market_value = float(pos.get('shares', 0) or 0) * float(price)
    if has_initial_capital_mode(state):
        cash = float(state.get('account', {}).get('cash', 0) or 0)
        return market_value + cash
    return market_value


def get_position_value(state, price=None):
    pos = state.get('position', {})
    if price is not None:
        return float(pos.get('shares', 0) or 0) * float(price)
    return float(pos.get('market_value', 0) or 0)


# ==================== 策略核心逻辑 ====================

def get_vix_zone(vix):
    if vix >= 35: return ">=35"
    elif vix >= 30: return "30-35"
    elif vix >= 25: return "25-30"
    elif vix >= 20: return "20-25"
    elif vix >= 18: return "18-20"
    elif vix >= 15: return "15-18"
    elif vix >= 12: return "12-15"
    elif vix >= 10: return "10-12"
    else: return "<10"


def get_base_buy_amount(vix, config):
    """步骤1：根据VIX区间确定基础买入金额"""
    tiers = config['buy_rules']['base_tiers']
    for tier in tiers:
        if tier['vix_min'] <= vix < tier['vix_max']:
            return tier['amount'], tier['label']
    return 0, "暂停定投"


def calculate_trend_adjustment(vix, state, config):
    """步骤2：应用趋势修正因子
    计算前两个双周周二的收盘VIX均值（不含当期），比较当期VIX与均值。
    返回: (修正乘数, 修正标签, 均值, 差值)
    注意：调用本函数时，state中的vix_log应尚未append当期记录。
    """
    adj_config = config['buy_rules'].get('trend_adjustment', {})
    if not adj_config.get('enabled', False):
        return None, None, None, None

    lookback = adj_config.get('lookback_periods', 2)
    threshold = adj_config.get('threshold', 0.5)
    multipliers = adj_config.get('multipliers', {})

    # 从state中获取双周VIX历史（调用方确保不含当期）
    vix_log = state.get('strategy_state', {}).get('biweekly_vix_log', [])
    if len(vix_log) < lookback:
        return None, None, None, None

    # 取最近lookback期历史
    recent = vix_log[-lookback:]
    mean_vix = sum(entry['vix'] for entry in recent) / lookback
    diff = vix - mean_vix

    if diff > threshold:
        mult = multipliers.get('rising', 0.7)
        label = f"趋势修正: VIX{ vix:.2f} > 均值{mean_vix:.2f}(+{diff:.2f}) → ×{mult}"
    elif diff < -threshold:
        mult = multipliers.get('falling', 1.3)
        label = f"趋势修正: VIX{vix:.2f} < 均值{mean_vix:.2f}({diff:.2f}) → ×{mult}"
    else:
        mult = multipliers.get('stable', 1.0)
        label = f"趋势修正: VIX{vix:.2f} ≈ 均值{mean_vix:.2f}(差{diff:.2f}) → ×{mult}"

    return mult, label, mean_vix, diff


def apply_cap(amount, vix, config):
    """步骤3：封顶处理
    若VIX >= 30，修正后的买入金额不得超过6000元
    """
    cap_config = config['buy_rules'].get('cap', {})
    if not cap_config.get('enabled', False):
        return amount, None
    threshold = cap_config.get('vix_threshold', 30)
    max_amount = cap_config.get('max_amount', 6000)
    if vix >= threshold and amount > max_amount:
        return max_amount, f"封顶: VIX≥{threshold}，金额从{amount:.0f}压至{max_amount}"
    return amount, None


def check_extreme_risk_control(vix, state, config):
    """步骤4：极端风控（优先于买入）
    触发条件: VIX >= 35 且 当期VIX > 前两期均值（不含当期）
    返回: (triggered: bool, message: str, sell_ratio: float or None)
    注意：调用本函数时，state中的vix_log应尚未append当期记录。
    """
    erc = config['buy_rules'].get('extreme_risk_control', {})
    if not erc.get('enabled', False):
        return False, "", None

    trigger_vix = erc.get('trigger_vix', 35)
    if vix < trigger_vix:
        # 检查是否从风控状态恢复
        ss = state.setdefault('strategy_state', {})
        if ss.get('extreme_risk', {}).get('active', False):
            ss['extreme_risk']['active'] = False
            ss['extreme_risk']['recovery_date'] = state.get('account', {}).get('last_update', '')
        return False, "", None

    # VIX >= 35，检查是否 > 前两期均值（调用方确保vix_log不含当期）
    vix_log = state.get('strategy_state', {}).get('biweekly_vix_log', [])
    lookback = config['buy_rules'].get('trend_adjustment', {}).get('lookback_periods', 2)
    if len(vix_log) < lookback:
        return False, f"极端风控: VIX≥{trigger_vix}但历史不足{lookback}期，不触发", None

    recent = vix_log[-lookback:]
    mean_vix = sum(entry['vix'] for entry in recent) / lookback
    if vix > mean_vix:
        ss = state.setdefault('strategy_state', {})
        ss.setdefault('extreme_risk', {})['active'] = True
        ss['extreme_risk']['triggered_date'] = state.get('account', {}).get('last_update', '')
        ss['extreme_risk']['trigger_vix'] = vix
        ss['extreme_risk']['mean_vix'] = mean_vix
        msg = f"极端风控触发: VIX={vix} > 均值{mean_vix:.2f}，暂停买入并减仓5%"
        return True, msg, 0.05
    return False, f"极端风控: VIX≥{trigger_vix}但未大于均值{mean_vix:.2f}，不触发", None


def check_sell_rules(vix, last_vix, state, config):
    """卖出规则：必须连续2个双周周二收盘VIX均满足区间，才执行减仓。
    返回: (sell_ratio_to_execute, label, message)
    sell_ratio_to_execute 是本次需要**新增**的减仓比例（不是累计目标）。
    last_vix: 上期双周周二的收盘VIX（由调用方提供，确保不含当期）。
    """
    sell_cfg = config.get('sell_rules', {})
    if not sell_cfg:
        return 0.0, None, ""

    if last_vix is None:
        return 0.0, None, ""

    # 检查连续两期是否满足（上期 & 本期）
    tiers = sell_cfg.get('tiers', [])
    max_reduction = sell_cfg.get('max_total_reduction', 0.40)

    # 优先级：从高到低（<10 > <12 > <15）
    target_ratio = 0.0
    matched_label = None
    for tier in tiers:
        vix_max = tier['vix_max']
        # 连续两期都 < vix_max
        if last_vix < vix_max and vix < vix_max:
            target_ratio = tier['reduce_ratio']
            matched_label = tier['label']

    if target_ratio == 0:
        return 0.0, None, ""

    # 计算实际需新增的减仓比例
    ss = state.setdefault('strategy_state', {})
    current_reduction = ss.get('cumulative_sell_ratio', 0.0)
    additional = target_ratio - current_reduction
    if additional <= 0:
        return 0.0, matched_label, f"{matched_label}: 目标累计{target_ratio*100:.0f}%已满足（当前已减{current_reduction*100:.0f}%），无需再减"

    # 检查40%上限
    if current_reduction + additional > max_reduction:
        additional = max_reduction - current_reduction
        if additional <= 0:
            return 0.0, matched_label, f"{matched_label}: 已达最大减仓上限{max_reduction*100:.0f}%，无法继续减仓"

    # 根据 matched_label 找到对应的 vix_max 用于消息
    vix_max_for_msg = None
    for tier in tiers:
        if tier['label'] == matched_label:
            vix_max_for_msg = tier['vix_max']
            break
    msg = f"{matched_label}: 连续2期VIX<{vix_max_for_msg}，新增减仓{additional*100:.1f}%（累计目标{target_ratio*100:.0f}%）"
    return additional, matched_label, msg


def check_reflow_rules(vix, state, config, last_vix):
    """回流规则：当发生过减仓后，VIX重新回升到指定阈值时，买入回补。
    返回: (reflow_amount, label, message)
    """
    reflow_cfg = config.get('reflow_rules', {})
    if not reflow_cfg.get('enabled', False):
        return 0.0, None, ""

    ss = state.setdefault('strategy_state', {})
    pool = ss.setdefault('reduction_pool', {})
    remaining = pool.get('remaining_cash', 0.0)
    if remaining <= 0:
        return 0.0, None, ""

    reflow_status = ss.get('reflow_status', 'none')
    tiers = reflow_cfg.get('tiers', [])

    # 找到30和25档
    tier_30 = next((t for t in tiers if t['vix_threshold'] == 30), None)
    tier_25 = next((t for t in tiers if t['vix_threshold'] == 25), None)

    amount = 0.0
    label = None

    # 先检查30档（如果上期为<30且本期≥30）
    if tier_30 and last_vix is not None and last_vix < 30 and vix >= 30:
        if reflow_status == 'none':
            # 直接从<30跳到≥30，买回100%
            amount = remaining
            label = "全部回流"
            ss['reflow_status'] = 'full'
        elif reflow_status == 'half':
            # 已经半流过，买回剩余
            amount = remaining
            label = "全部回流"
            ss['reflow_status'] = 'full'
        else:
            return 0.0, None, ""
        msg = f"回流触发: VIX从{last_vix:.2f}回升至{vix:.2f}（≥30），{label} {amount:.2f}元"
        return amount, label, msg

    # 再检查25档（如果上期为<25且本期≥25，且尚未半流）
    if tier_25 and last_vix is not None and last_vix < 25 and vix >= 25:
        if reflow_status == 'none':
            amount = remaining * tier_25['ratio']
            label = "半数回流"
            ss['reflow_status'] = 'half'
            msg = f"回流触发: VIX从{last_vix:.2f}回升至{vix:.2f}（≥25），{label} {amount:.2f}元"
            return amount, label, msg
        return 0.0, None, ""

    return 0.0, None, ""


def execute_buy(state, amount, price, label, date_str):
    """执行买入，更新持仓和现金"""
    if amount <= 0 or price <= 0:
        return None
    pos = state['position']
    acc = state['account']
    use_cash_account = has_initial_capital_mode(state)

    cash_before = float(acc.get('cash', 0) or 0)
    fee = max(0.01, amount * 0.0001)
    actual = amount - fee
    shares = int(actual / price)
    if shares <= 0:
        return None
    total_cost = shares * price + fee
    cash_after = cash_before - total_cost if use_cash_account else cash_before

    pos['shares'] += shares
    pos['total_cost'] += total_cost
    pos['avg_cost'] = pos['total_cost'] / pos['shares']
    if use_cash_account:
        acc['cash'] = cash_after

    state['statistics']['cumulative_buy'] = float(state['statistics'].get('cumulative_buy', 0) or 0) + amount
    state['statistics']['buy_count'] = int(state['statistics'].get('buy_count', 0) or 0) + 1
    state['statistics']['trade_count'] = int(state['statistics'].get('trade_count', 0) or 0) + 1
    state['statistics']['total_invested'] = float(state['statistics'].get('total_invested', 0) or 0) + amount
    state['statistics']['last_trade_date'] = date_str

    return {
        'date': date_str,
        'vix': state.get('daily_performance', {}).get('vix', 0),
        'action': 'BUY',
        'amount': amount,
        'shares': shares,
        'price': price,
        'label': label
    }


def execute_sell(state, sell_ratio, price, label, date_str):
    """执行减仓，更新持仓和现金，并将资金加入reduction_pool"""
    if sell_ratio <= 0 or price <= 0:
        return None, 0.0
    pos = state['position']
    acc = state['account']
    use_cash_account = has_initial_capital_mode(state)

    position_value = pos['shares'] * price
    sell_value = position_value * sell_ratio
    sell_shares = int(sell_value / price)
    if sell_shares <= 0:
        return None, 0.0

    actual_sell_value = sell_shares * price
    fee = max(0.01, actual_sell_value * 0.0001)
    net_cash = actual_sell_value - fee

    # 更新持仓
    pos['shares'] -= sell_shares
    pos['total_cost'] = pos['total_cost'] * (1 - sell_ratio)  # 近似按比例减成本
    if pos['shares'] > 0:
        pos['avg_cost'] = pos['total_cost'] / pos['shares']
    else:
        pos['avg_cost'] = 0
        pos['total_cost'] = 0

    if use_cash_account:
        acc['cash'] = float(acc.get('cash', 0) or 0) + net_cash

    # 更新累计减仓比例
    ss = state.setdefault('strategy_state', {})
    ss['cumulative_sell_ratio'] = ss.get('cumulative_sell_ratio', 0.0) + sell_ratio

    # 加入减仓资金池
    pool = ss.setdefault('reduction_pool', {})
    pool['total_cash'] = pool.get('total_cash', 0.0) + net_cash
    pool['remaining_cash'] = pool.get('remaining_cash', 0.0) + net_cash

    # 重置回流状态（新减仓发生后，可以重新回流）
    ss['reflow_status'] = 'none'

    state['statistics']['sell_count'] = int(state['statistics'].get('sell_count', 0) or 0) + 1
    state['statistics']['trade_count'] = int(state['statistics'].get('trade_count', 0) or 0) + 1
    state['statistics']['last_trade_date'] = date_str

    return {
        'date': date_str,
        'vix': state.get('daily_performance', {}).get('vix', 0),
        'action': 'SELL',
        'amount': actual_sell_value,
        'shares': sell_shares,
        'price': price,
        'label': label
    }, net_cash


def update_state(state, config, date_str, vix, price, is_trading):
    """更新状态文件（核心策略执行）"""
    prev_unrealized = state['position'].get('unrealized_pnl', 0)
    pos = state['position']
    acc = state['account']

    trades_executed = []
    trade_infos = []
    notes = []

    # 确保strategy_state存在
    ss = state.setdefault('strategy_state', {
        'biweekly_vix_log': [],
        'cumulative_sell_ratio': 0.0,
        'reduction_pool': {'total_cash': 0.0, 'remaining_cash': 0.0},
        'reflow_status': 'none',
        'extreme_risk': {'active': False}
    })

    # 获取上一期VIX（用于连续判断和回流判断）
    vix_log = ss.get('biweekly_vix_log', [])
    last_vix = vix_log[-1]['vix'] if vix_log else None

    if is_trading:
        # ===== 定投日策略执行 =====
        print(f"\n=== 定投日策略执行 ({date_str}, VIX={vix}) ===")

        # --- 步骤4：极端风控（最优先，使用纯历史VIX，不含当期） ---
        erc_triggered, erc_msg, erc_sell_ratio = check_extreme_risk_control(vix, state, config)
        print(f"[风控] {erc_msg}")

        if erc_triggered:
            # 极端风控：暂停买入，执行减仓5%
            if erc_sell_ratio and erc_sell_ratio > 0:
                trade_info, cash_added = execute_sell(state, erc_sell_ratio, price, "极端风控减仓", date_str)
                if trade_info:
                    trades_executed.append(trade_info)
                    trade_infos.append(trade_info)
                    notes.append(f"极端风控减仓5%，释放{cash_added:.2f}元至减仓资金池")
                    print(f"[交易] 极端风控减仓: 卖出{trade_info['shares']}份 @ {price}元，金额{trade_info['amount']:.2f}元")
            notes.append("极端风控激活：暂停本期定投")
            print("[交易] 极端风控激活：本期定投暂停")
            # 风控日仍滚动下次定投日
            roll_next_trade_schedule(state, date_str)
            # 记录本期VIX（风控日也要记录）
            vix_log.append({'date': date_str, 'vix': vix})
            ss['biweekly_vix_log'] = vix_log
        else:
            # --- 步骤1：基础档位 ---
            base_amount, base_label = get_base_buy_amount(vix, config)
            print(f"[买入] 基础档位: {base_label} → {base_amount}元")

            adjusted_amount = base_amount
            adjusted_label = base_label

            # --- 步骤2：趋势修正（使用纯历史VIX，不含当期） ---
            if base_amount > 0:
                mult, adj_msg, mean_vix, diff = calculate_trend_adjustment(vix, state, config)
                if mult is not None:
                    adjusted_amount = round(base_amount * mult)
                    adjusted_label = f"{base_label}(趋势修正×{mult})"
                    print(f"[买入] {adj_msg}")
                    print(f"[买入] 趋势修正后: {adjusted_amount}元")
                else:
                    print("[买入] 趋势修正: 历史不足，不修正")

            # --- 步骤3：封顶处理 ---
            capped_amount, cap_msg = apply_cap(adjusted_amount, vix, config)
            if cap_msg:
                print(f"[买入] {cap_msg}")
                adjusted_label = f"{adjusted_label}(封顶)"
            adjusted_amount = capped_amount

            # 记录本期VIX（在卖出/回流判断前写入，用于下期计算）
            # 但卖出/回流判断中的"上期"仍基于旧的vix_log[-1]
            vix_log.append({'date': date_str, 'vix': vix})
            ss['biweekly_vix_log'] = vix_log

            # --- 卖出规则 ---
            sell_ratio, sell_label, sell_msg = check_sell_rules(vix, last_vix, state, config)
            if sell_ratio > 0:
                print(f"[卖出] {sell_msg}")
                trade_info, cash_added = execute_sell(state, sell_ratio, price, sell_label, date_str)
                if trade_info:
                    trades_executed.append(trade_info)
                    trade_infos.append(trade_info)
                    notes.append(f"{sell_label}: 新增减仓{sell_ratio*100:.1f}%，释放{cash_added:.2f}元")
                    print(f"[交易] {sell_label}: 卖出{trade_info['shares']}份 @ {price}元，金额{trade_info['amount']:.2f}元")
            else:
                if sell_label:
                    print(f"[卖出] {sell_msg}")
                else:
                    print("[卖出] 连续低VIX条件不满足，不减仓")

            # --- 回流规则 ---
            reflow_amount, reflow_label, reflow_msg = check_reflow_rules(vix, state, config, last_vix)
            if reflow_amount > 0:
                print(f"[回流] {reflow_msg}")
                # 回流买入
                trade_info = execute_buy(state, reflow_amount, price, reflow_label, date_str)
                if trade_info:
                    trades_executed.append(trade_info)
                    trade_infos.append(trade_info)
                    notes.append(f"{reflow_label}: 买回{trade_info['shares']}份 @ {price}元")
                    print(f"[交易] {reflow_label}: 买入{trade_info['shares']}份 @ {price}元，金额{reflow_amount:.2f}元")
                    # 从资金池扣除
                    pool = ss['reduction_pool']
                    pool['remaining_cash'] = max(0.0, pool.get('remaining_cash', 0.0) - reflow_amount)
            else:
                pool = ss.get('reduction_pool', {})
                if pool.get('remaining_cash', 0) > 0:
                    print(f"[回流] 有回流资金{pool['remaining_cash']:.2f}元，但VIX条件未满足（上期={last_vix}, 本期={vix}）")
                else:
                    print("[回流] 无待回流资金")

            # --- 执行基础买入 ---
            if adjusted_amount > 0:
                trade_info = execute_buy(state, adjusted_amount, price, adjusted_label, date_str)
                if trade_info:
                    trades_executed.append(trade_info)
                    trade_infos.append(trade_info)
                    notes.append(f"{adjusted_label}: 买入{trade_info['shares']}份 @ {price}元")
                    print(f"[交易] {adjusted_label}: 买入{trade_info['shares']}份 @ {price}元，金额{adjusted_amount}元")
            else:
                print(f"[交易] {adjusted_label}: 本期不买入")

            # 滚动下次定投日
            roll_next_trade_schedule(state, date_str)

        # 记录本期VIX后的日志摘要
        print(f"\n[状态] 累计减仓比例: {ss.get('cumulative_sell_ratio', 0)*100:.1f}%")
        pool = ss.get('reduction_pool', {})
        print(f"[状态] 减仓资金池: 累计{pool.get('total_cash', 0):.2f}元, 剩余{pool.get('remaining_cash', 0):.2f}元")
        print(f"[状态] 回流状态: {ss.get('reflow_status', 'none')}")
        print(f"[状态] 极端风控: {'激活' if ss.get('extreme_risk', {}).get('active') else '未激活'}")
    else:
        # 非定投日：只更新收益
        print(f"\n=== 非定投日 ({date_str}) ===")
        print("[收益] 只更新持仓市值和收益，不执行交易")

    # ===== 每日收益更新（无论是否定投日） =====
    position_value = pos['shares'] * price
    net_value = get_total_assets_value(state, price=price)
    total_cost = pos['total_cost']
    unrealized = position_value - total_cost if total_cost > 0 else 0
    return_pct = (unrealized / total_cost * 100) if total_cost > 0 else 0
    daily_pnl = unrealized - prev_unrealized
    principal = get_tracking_principal(state)
    total_return_pct = ((net_value - principal) / principal * 100) if principal > 0 else 0

    pos['current_price'] = price
    pos['market_value'] = position_value
    pos['unrealized_pnl'] = unrealized
    pos['return_pct'] = round(return_pct, 2)

    state['daily_performance'] = {
        'date': date_str,
        'vix': vix,
        'daily_pnl': round(daily_pnl, 2),
        'total_pnl': round(unrealized, 2),
        'total_return_pct': round(total_return_pct, 2)
    }

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

    return trades_executed, trade_infos, {
        'daily_pnl': round(daily_pnl, 2),
        'unrealized': round(unrealized, 2),
        'return_pct': round(return_pct, 2),
        'net_value': round(net_value, 2),
        'notes': notes
    }


# ==================== Dashboard & Markdown ====================

def update_dashboard_data(dashboard, state, date_str, vix, price, trade_infos):
    """更新dashboard_data.json"""
    pos = state['position']
    acc = state['account']
    perf = state['daily_performance']
    stats = state['statistics']
    schedule = state.get('schedule', {})
    ss = state.get('strategy_state', {})
    principal = get_tracking_principal(state)
    cash = float(acc.get('cash', 0) or 0)
    total_assets = get_total_assets_value(state)
    next_trade_date = get_next_trade_date(state)
    days_until_next = None
    if next_trade_date:
        days_until_next = (datetime.strptime(next_trade_date, '%Y-%m-%d') - datetime.strptime(date_str, '%Y-%m-%d')).days

    dashboard['last_update'] = date_str
    dashboard['strategy_version'] = 'V2.0'
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
    dashboard['strategy_state'] = {
        'cumulative_sell_ratio': round(ss.get('cumulative_sell_ratio', 0.0), 4),
        'reduction_pool': {
            'total_cash': round(ss.get('reduction_pool', {}).get('total_cash', 0.0), 2),
            'remaining_cash': round(ss.get('reduction_pool', {}).get('remaining_cash', 0.0), 2)
        },
        'reflow_status': ss.get('reflow_status', 'none'),
        'extreme_risk_active': ss.get('extreme_risk', {}).get('active', False)
    }
    dashboard['schedule'] = {
        'frequency': '每双周周二',
        'last_trade_date': stats['last_trade_date'],
        'next_trade_date': next_trade_date,
        'days_until_next': days_until_next
    }

    # 添加交易记录
    if trade_infos:
        dashboard.setdefault('recent_trades', [])
        for ti in trade_infos:
            dashboard['recent_trades'].insert(0, ti)
        dashboard['recent_trades'] = dashboard['recent_trades'][:10]

    # 添加每日快照
    snaps = dashboard.get('daily_snapshots', [])
    snaps = [s for s in snaps if s.get('date') != date_str]
    snaps.insert(0, {
        'date': date_str,
        'price': price,
        'pnl': perf['total_pnl'],
        'daily_pnl': perf['daily_pnl']
    })
    dashboard['daily_snapshots'] = snaps[:10]
    return dashboard


def update_markdown_template(state, date_str, vix, price):
    """更新Markdown展示文件"""
    template_path = TEMPLATE_DIR / "vix-dca-strategy.md"
    pos = state['position']
    acc = state['account']
    perf = state['daily_performance']
    stats = state['statistics']
    principal = get_tracking_principal(state)
    cash = float(acc.get('cash', 0) or 0)
    total_assets = get_total_assets_value(state)
    ss = state.get('strategy_state', {})
    pool = ss.get('reduction_pool', {})

    dashboard = load_json(DASHBOARD_FILE)
    snapshots = dashboard.get('daily_snapshots', [])[:7]
    recent_trades = dashboard.get('recent_trades', [])[:10]

    schedule = state.get('schedule', {})
    next_trade = get_next_trade_date(state)
    days_until = (datetime.strptime(next_trade, '%Y-%m-%d') - datetime.strptime(date_str, '%Y-%m-%d')).days if next_trade else None
    upcoming_trades = schedule.get('upcoming_trade_dates', [])
    if not upcoming_trades and next_trade:
        upcoming_trades = [next_trade]
    anchor_date = schedule.get('anchor_date', '未设置')

    content = f"""# VIX定投策略 - 纳指100 ETF（**{ETF_CODE}**）

> **标的代码：{ETF_CODE}** | 策略版本：**V2.0（原策略·最终版）** | 启动日期：2026-03-24  
> **买卖执行：每双周周二** | **收益更新：每日** | 投入本金：{principal:,.2f}元  
> **双周锚点：{anchor_date}（每双周周二定投）**

---

## 当前收益（{date_str}）

| 指标 | 数值 |
|------|------|
| **持仓份额** | {pos['shares']:,}份 |
| **平均成本** | {pos['avg_cost']:.3f}元 |
| **最新收盘价** | {price:.2f}元 |
| **持仓收益** | **{pos['unrealized_pnl']:+.2f}元（{pos['return_pct']:+.2f}%）** {'✅' if pos['unrealized_pnl'] >= 0 else '⚠️'} |
| **总收益** | **{perf['total_pnl']:+.2f}元（{perf['total_return_pct']:+.2f}%）** |
| **剩余现金** | {cash:,.2f}元 |
| **总资产** | {total_assets:,.2f}元 |
| **累计减仓** | {ss.get('cumulative_sell_ratio', 0)*100:.1f}% |
| **减仓资金池** | 累计{pool.get('total_cash', 0):.2f}元 / 剩余{pool.get('remaining_cash', 0):.2f}元 |
| **回流状态** | {ss.get('reflow_status', 'none')} |
| **极端风控** | {'🔴 激活' if ss.get('extreme_risk', {}).get('active') else '🟢 未激活'} |

---

## 收益走势（最近7天）

| 日期 | 收盘价 | 当日盈亏 | 累计盈亏 | 收益率 |
|------|--------|----------|----------|--------|
"""
    for snap in snapshots:
        snap_date = snap['date']
        snap_price = snap['price']
        snap_pnl = snap['pnl']
        snap_daily = snap['daily_pnl']
        snap_return = (snap_pnl / principal * 100) if principal > 0 else 0
        marker = "**" if snap_date == date_str else ""
        content += f"| {marker}{snap_date}{marker} | {marker}{snap_price:.2f}{marker} | {marker}{snap_daily:+.2f}{marker} | {marker}{snap_pnl:+.2f}{marker} | {marker}{snap_return:+.2f}%{marker} |\n"

    content += f"""

### 收益率曲线（鼠标悬停查看详情）

<iframe src="/vix_strategy/returns_curve.html" width="100%" height="520" frameborder="0" style="border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,0.1);"></iframe>

> 更新时间：{date_str} | 累计收益率：{perf['total_return_pct']:+.2f}%

---

## 交易记录

| 日期 | VIX | 档位 | 操作 | 金额 | 持仓变化 | 价格 | 备注 |
|------|-----|------|------|------|----------|------|------|
"""
    for trade in recent_trades:
        shares_str = f"+{trade['shares']}" if trade['action'] == 'BUY' else f"-{trade['shares']}"
        content += f"| {trade['date']} | {trade['vix']:.2f} | {get_vix_zone(trade['vix'])} | {trade['action']} | {trade['amount']:,.2f}元 | {shares_str}份 | {trade['price']:.2f}元 | {trade['label']} |\n"

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
            status = "📅 计划"
            action = "双周定投"
        content += f"| {trade_date} | 周{week} | {status} | {action} |\n"

    content += """
---

## 策略说明（原策略·最终版）

### 一、基础框架
- **标的**：纳斯达克100 ETF（场内513110，逻辑跟踪QQQ）
- **操作频率**：每**双周周二**国内白天执行（参考**美国周一**的VIX收盘价）
- **资金来源**：每月约1万元，按双周分批预留（未用完现金留存）
- **禁止行为**：盘中操作、追涨杀跌、主观干预

### 二、买入规则（按顺序执行）

#### 步骤1：基础档位
| VIX区间 | 基础金额 |
|:---:|:---:|
| VIX < 15 | 0 元 |
| 15 ≤ VIX < 18 | 1,000 元 |
| 18 ≤ VIX < 20 | 1,500 元 |
| 20 ≤ VIX < 25 | 3,000 元 |
| 25 ≤ VIX < 30 | 4,500 元 |
| 30 ≤ VIX < 35 | 6,000 元 |
| VIX ≥ 35 | 6,000 元（封顶） |

#### 步骤2：趋势修正因子
- 计算**前两个双周周二**收盘VIX均值
- 当期VIX **>** 均值（恐慌加剧）→ 基础金额 × **0.7**
- 当期VIX **<** 均值（恐慌消退）→ 基础金额 × **1.3**
- 当期VIX ≈ 均值（差≤0.5）→ 基础金额 × **1.0**

#### 步骤3：封顶处理
- 若VIX ≥ 30，修正后买入金额**不得超过6,000元**

#### 步骤4：极端风控（优先于买入）
- **触发**：VIX ≥ 35 **且** 当期VIX > 前两期均值
- **操作**：暂停当期定投 + **额外减仓5%**
- **恢复**：VIX回落至<35时恢复正常买入

### 三、卖出规则
**必须连续2个双周周二**收盘VIX均满足区间：

| 条件 | 减仓比例（当前持仓市值） |
|:---|:---:|
| 连续2期 VIX < 15 | 10% |
| 连续2期 VIX < 12 | 15%（累计） |
| 连续2期 VIX < 10 | 25%（累计） |

- 累计减仓总额不超过**40%**（永远保留至少**60%底仓**）
- 减仓所得现金保留账户，用于后续回流

### 四、减仓资金回流规则
当发生过减仓，后续VIX**重新回升**到指定阈值时买回：

| 触发条件 | 买回比例 |
|:---|:---:|
| VIX **重新 ≥ 25** | 买回减仓资金的 **50%** |
| VIX **重新 ≥ 30** | 买回剩余 **50%** |

- 回流买入在双周周二与当期定投一同执行
- 回流金额**不占用**当期买入封顶额度

### 五、应急补仓（可选）
- **触发**：单周盘中VIX ≥ 32
- **操作**：本周内额外买入 **1,500元**
- **限制**：每月最多1次，不与主定投冲突

### 六、执行纪律
| 项目 | 规则 |
|:---|:---|
| 操作日 | 国内周二白天（参考美国周一收盘VIX） |
| 买入计算 | 基础档位 → 趋势修正 → 封顶 → 风控检查 |
| 卖出判断 | 连续2期VIX达标才减仓，累计≤40% |
| 回流 | VIX重新≥25和≥30时按比例买回 |
| 应急补仓 | VIX≥32可加1,500，月限1次（可选） |
| 禁止行为 | 盘中随机买卖、追涨杀跌、主观干预 |

---

*最后更新：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""

    with open(template_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"[Markdown] 已更新 {template_path}")


# ==================== 收益率曲线图 ====================

def generate_returns_curve_svg(output_path, data_rows):
    """
    生成收益率曲线SVG图（纯Python，无外部依赖）
    data_rows: list of dicts with keys: date, total_return_pct
    """
    if not data_rows:
        return

    # 图表尺寸
    width = 900
    height = 400
    margin = {'top': 40, 'right': 40, 'bottom': 60, 'left': 70}
    chart_w = width - margin['left'] - margin['right']
    chart_h = height - margin['top'] - margin['bottom']

    # 数据准备
    returns = [float(r['total_return_pct']) for r in data_rows]
    dates = [r['date'] for r in data_rows]
    n = len(returns)

    min_ret = min(returns) if returns else 0
    max_ret = max(returns) if returns else 0
    # 以0为基准，确保0线在可视范围内
    y_min = min(min_ret, 0) * 1.1
    y_max = max(max_ret, 0) * 1.1
    if abs(y_max - y_min) < 0.01:
        y_min -= 0.5
        y_max += 0.5

    def x_scale(i):
        return margin['left'] + (i / max(n - 1, 1)) * chart_w

    def y_scale(v):
        return margin['top'] + chart_h - ((v - y_min) / (y_max - y_min)) * chart_h

    # 构建折线路径
    points = []
    for i, ret in enumerate(returns):
        px = x_scale(i)
        py = y_scale(ret)
        points.append(f"{px:.1f},{py:.1f}")

    line_path = "M" + " L".join(points)

    # 区域填充路径（到零线）
    zero_y = y_scale(0)
    area_path = line_path + f" L{x_scale(n-1):.1f},{zero_y:.1f} L{x_scale(0):.1f},{zero_y:.1f} Z"

    # Y轴刻度
    y_ticks = []
    y_labels = []
    tick_count = 5
    for i in range(tick_count + 1):
        val = y_min + (y_max - y_min) * (i / tick_count)
        y_pos = y_scale(val)
        y_ticks.append(f"<line x1='{margin['left']}' y1='{y_pos:.1f}' x2='{width - margin['right']}' y2='{y_pos:.1f}' stroke='#e5e7eb' stroke-width='1' stroke-dasharray='2,2'/>")
        y_labels.append(f"<text x='{margin['left'] - 10}' y='{y_pos + 4:.1f}' text-anchor='end' font-size='11' fill='#6b7280'>{val:.1f}%</text>")

    # X轴刻度（显示约6个日期）
    x_labels = []
    step = max(1, n // 6)
    for i in range(0, n, step):
        px = x_scale(i)
        x_labels.append(f"<text x='{px:.1f}' y='{height - margin['bottom'] + 20}' text-anchor='middle' font-size='10' fill='#6b7280' transform='rotate(-30 {px:.1f},{height - margin['bottom'] + 20})'>{dates[i]}</text>")

    # 零线
    zero_line = f"<line x1='{margin['left']}' y1='{zero_y:.1f}' x2='{width - margin['right']}' y2='{zero_y:.1f}' stroke='#9ca3af' stroke-width='1.5'/>"

    # 最新收益率点
    last_px = x_scale(n - 1)
    last_py = y_scale(returns[-1])
    last_color = '#16a34a' if returns[-1] >= 0 else '#dc2626'

    # 计算每日变化用于着色
    # 正收益天数用绿色区域，负收益用红色区域
    # 简化：整体区域根据最终收益率着色，折线用渐变色

    svg_parts = [
        f"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' width='100%' height='100%'>
  <defs>
    <linearGradient id='areaGradient' x1='0' y1='0' x2='0' y2='1'>
      <stop offset='0%' stop-color='{('#16a34a' if max_ret >= 0 else '#dc2626')}' stop-opacity='0.15'/>
      <stop offset='100%' stop-color='{('#16a34a' if max_ret >= 0 else '#dc2626')}' stop-opacity='0.02'/>
    </linearGradient>
  </defs>
  <rect width='{width}' height='{height}' fill='#ffffff' rx='8'/>
  <text x='{width/2}' y='25' text-anchor='middle' font-size='16' font-weight='bold' fill='#1f2937'>VIX定投策略 — 累计收益率曲线</text>
""",
        "  <!-- Grid -->\n",
        "\n".join(y_ticks),
        "\n",
        zero_line,
        "\n",
        f"  <path d='{area_path}' fill='url(#areaGradient)' stroke='none'/>\n",
        f"  <path d='{line_path}' fill='none' stroke='{last_color}' stroke-width='2.5' stroke-linejoin='round' stroke-linecap='round'/>\n",
        f"  <circle cx='{last_px:.1f}' cy='{last_py:.1f}' r='5' fill='{last_color}' stroke='#ffffff' stroke-width='2'/>\n",
        f"  <text x='{last_px:.1f}' y='{last_py - 12:.1f}' text-anchor='middle' font-size='11' font-weight='bold' fill='{last_color}'>{returns[-1]:+.2f}%</text>\n",
        "  <!-- Axis labels -->\n",
        "\n".join(y_labels),
        "\n",
        "\n".join(x_labels),
        "\n",
        f"  <text x='{margin['left']}' y='{height - 10}' font-size='10' fill='#9ca3af'>数据来源: VIX定投策略 | 每日更新</text>",
        "</svg>"
    ]

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("".join(svg_parts))
    print(f"[图表] 已生成收益率曲线SVG: {output_path}")


def get_tracking_principal_from_state():
    """从state或dashboard获取跟踪本金"""
    try:
        dashboard = load_json(DASHBOARD_FILE)
        principal = float(dashboard.get('account', {}).get('initial_capital', 0))
        if principal > 0:
            return principal
    except Exception:
        pass
    try:
        state = load_json(STATE_FILE)
        principal = float(state.get('account', {}).get('initial_capital', 0))
        if principal > 0:
            return principal
        cumulative_buy = float(state.get('statistics', {}).get('cumulative_buy', 0))
        if cumulative_buy > 0:
            return cumulative_buy
        total_cost = float(state.get('position', {}).get('total_cost', 0))
        if total_cost > 0:
            return total_cost
    except Exception:
        pass
    return 7500.0  # 默认值


def load_daily_returns_full():
    """加载完整的每日收益率数据，合并 daily_returns.csv + dashboard_data.json daily_snapshots"""
    rows_by_date = {}

    # 1. 从 daily_returns.csv 读取（优先级最高）
    if DAILY_RETURNS_FILE.exists():
        with open(DAILY_RETURNS_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows_by_date[row['date']] = {
                    'date': row['date'],
                    'vix': row.get('vix', ''),
                    'price': row.get('price', ''),
                    'shares': row.get('shares', ''),
                    'avg_cost': row.get('avg_cost', ''),
                    'market_value': row.get('market_value', ''),
                    'total_cost': row.get('total_cost', ''),
                    'unrealized_pnl': row.get('unrealized_pnl', ''),
                    'daily_pnl': row.get('daily_pnl', ''),
                    'return_pct': row.get('return_pct', ''),
                    'total_return_pct': row.get('total_return_pct', ''),
                    'cash': row.get('cash', ''),
                    'net_value': row.get('net_value', ''),
                }

    # 2. 从 dashboard_data.json 的 daily_snapshots 补充缺失数据
    try:
        dashboard = load_json(DASHBOARD_FILE)
        principal = float(dashboard.get('account', {}).get('initial_capital', 7500.0))
        snaps = dashboard.get('daily_snapshots', [])
        for snap in snaps:
            d = snap.get('date')
            if not d:
                continue
            if d in rows_by_date:
                # 如果 daily_returns 中该日期缺少某些字段，用 snapshot 补充
                existing = rows_by_date[d]
                pnl = float(snap.get('pnl', 0))
                total_ret = (pnl / principal * 100) if principal > 0 else 0
                if not existing.get('total_return_pct'):
                    existing['total_return_pct'] = round(total_ret, 2)
                if not existing.get('price'):
                    existing['price'] = snap.get('price', '')
                if not existing.get('daily_pnl'):
                    existing['daily_pnl'] = snap.get('daily_pnl', '')
                if not existing.get('unrealized_pnl'):
                    existing['unrealized_pnl'] = snap.get('pnl', '')
            else:
                pnl = float(snap.get('pnl', 0))
                total_ret = (pnl / principal * 100) if principal > 0 else 0
                rows_by_date[d] = {
                    'date': d,
                    'vix': '',
                    'price': snap.get('price', ''),
                    'shares': '',
                    'avg_cost': '',
                    'market_value': '',
                    'total_cost': '',
                    'unrealized_pnl': snap.get('pnl', ''),
                    'daily_pnl': snap.get('daily_pnl', ''),
                    'return_pct': '',
                    'total_return_pct': round(total_ret, 2),
                    'cash': '',
                    'net_value': '',
                }
    except Exception as e:
        print(f"[警告] 从 dashboard_data.json 补充数据失败: {e}")

    # 3. 按日期排序返回
    sorted_dates = sorted(rows_by_date.keys())
    return [rows_by_date[d] for d in sorted_dates]


def generate_returns_curve_html(output_path, data_rows):
    """
    生成交互式收益率曲线HTML（ECharts，支持鼠标悬停显示详细数据 + 日/周/月/年切换）
    data_rows: list of dicts with full daily return fields
    """
    if not data_rows:
        return

    # 构建JS数据数组（原始日数据）
    raw_data = []
    for r in data_rows:
        trp = r.get('total_return_pct', '')
        try:
            trp_f = float(trp) if trp != '' else None
        except (ValueError, TypeError):
            trp_f = None

        # 如果 total_return_pct 缺失，尝试用 unrealized_pnl / principal 推算
        if trp_f is None:
            try:
                principal = get_tracking_principal_from_state()
                pnl = float(r.get('unrealized_pnl', 0) or 0)
                trp_f = (pnl / principal * 100) if principal > 0 else 0
            except Exception:
                trp_f = 0

        raw_data.append({
            'date': r['date'],
            'total_return_pct': round(trp_f, 2) if trp_f is not None else 0,
            'daily_pnl': round(float(r.get('daily_pnl', 0) or 0), 2),
            'price': round(float(r.get('price', 0) or 0), 3),
            'vix': round(float(r.get('vix', 0) or 0), 2) if r.get('vix') else None,
            'market_value': round(float(r.get('market_value', 0) or 0), 2),
            'unrealized_pnl': round(float(r.get('unrealized_pnl', 0) or 0), 2),
        })

    # 序列化为JS
    raw_data_js = json.dumps(raw_data, ensure_ascii=False)
    last = raw_data[-1]
    last_date = last['date']
    last_total = last['total_return_pct']
    last_price = last['price']
    last_vix = last['vix'] if last['vix'] is not None else '—'
    last_mv = last['market_value']
    last_pnl = last['unrealized_pnl']

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VIX定投策略 — 累计收益率曲线</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background: #f8fafc; padding: 16px; }}
  .chart-container {{ width: 100%; max-width: 960px; margin: 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 20px; }}
  .chart-header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }}
  .chart-title {{ font-size: 18px; font-weight: 600; color: #1f2937; }}
  .period-tabs {{ display: flex; gap: 4px; background: #f3f4f6; border-radius: 6px; padding: 3px; }}
  .period-tab {{ padding: 5px 14px; border: none; background: transparent; color: #6b7280; font-size: 12px; font-weight: 500; border-radius: 4px; cursor: pointer; transition: all 0.2s; }}
  .period-tab:hover {{ color: #374151; }}
  .period-tab.active {{ background: #fff; color: #1f2937; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }}
  .chart-subtitle {{ font-size: 12px; color: #9ca3af; margin-bottom: 8px; }}
  #chart {{ width: 100%; height: 400px; }}
  .stats-bar {{ display: flex; justify-content: center; gap: 24px; margin-top: 12px; padding-top: 12px; border-top: 1px solid #e5e7eb; flex-wrap: wrap; }}
  .stat-item {{ text-align: center; }}
  .stat-label {{ font-size: 11px; color: #6b7280; }}
  .stat-value {{ font-size: 14px; font-weight: 600; color: #1f2937; }}
  .stat-value.positive {{ color: #16a34a; }}
  .stat-value.negative {{ color: #dc2626; }}
</style>
</head>
<body>
<div class="chart-container">
  <div class="chart-header">
    <div class="chart-title">VIX定投策略 — 累计收益率曲线</div>
    <div class="period-tabs">
      <button class="period-tab active" data-period="day" onclick="switchPeriod('day')">日</button>
      <button class="period-tab" data-period="week" onclick="switchPeriod('week')">周</button>
      <button class="period-tab" data-period="month" onclick="switchPeriod('month')">月</button>
      <button class="period-tab" data-period="year" onclick="switchPeriod('year')">年</button>
    </div>
  </div>
  <div class="chart-subtitle">鼠标悬停查看详细数据 | 最后更新: {last_date}</div>
  <div id="truncation-notice" style="display:none; font-size:12px; color:#d97706; margin-bottom:8px; padding:6px 10px; background:#fffbeb; border-radius:4px; border:1px solid #fcd34d;"></div>
  <div id="chart"></div>
  <div class="stats-bar">
    <div class="stat-item">
      <div class="stat-label">累计收益率</div>
      <div class="stat-value {'positive' if last_total >= 0 else 'negative'}">{last_total:+.2f}%</div>
    </div>
    <div class="stat-item">
      <div class="stat-label">最新价格</div>
      <div class="stat-value">{last_price:.3f}元</div>
    </div>
    <div class="stat-item">
      <div class="stat-label">最新VIX</div>
      <div class="stat-value">{last_vix}</div>
    </div>
    <div class="stat-item">
      <div class="stat-label">持仓市值</div>
      <div class="stat-value">{last_mv:,.2f}元</div>
    </div>
    <div class="stat-item">
      <div class="stat-label">浮动盈亏</div>
      <div class="stat-value {'positive' if last_pnl >= 0 else 'negative'}">{last_pnl:+.2f}元</div>
    </div>
  </div>
</div>
<script>
  var rawData = {raw_data_js};
  var chart = echarts.init(document.getElementById('chart'));
  var currentPeriod = 'day';

  function getWeekKey(dateStr) {{
    var d = new Date(dateStr);
    var day = d.getDay();
    var diff = d.getDate() - day + (day === 0 ? -6 : 1);
    var monday = new Date(d.setDate(diff));
    return monday.getFullYear() + '-W' + String(Math.ceil((d.getDate())/7)).padStart(2,'0');
  }}

  function getYearWeek(dateStr) {{
    var d = new Date(dateStr);
    d.setHours(0,0,0,0);
    d.setDate(d.getDate() + 4 - (d.getDay() || 7));
    var yearStart = new Date(d.getFullYear(), 0, 1);
    var weekNo = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
    return d.getFullYear() + '-W' + String(weekNo).padStart(2, '0');
  }}

  // 各周期最大显示限制（超过则截断并提示）
  var PERIOD_LIMITS = {{ day: 180, week: 52, month: 24, year: Infinity }};

  function aggregateData(period) {{
    var data;
    if (period === 'day') {{
      data = rawData;
    }} else {{
      var groups = {{}};
      for (var i = 0; i < rawData.length; i++) {{
        var item = rawData[i];
        var key;
        if (period === 'week') {{
          key = getYearWeek(item.date);
        }} else if (period === 'month') {{
          key = item.date.substring(0, 7);
        }} else if (period === 'year') {{
          key = item.date.substring(0, 4);
        }}
        groups[key] = item;
      }}
      data = [];
      var sortedKeys = Object.keys(groups).sort();
      for (var k = 0; k < sortedKeys.length; k++) {{
        data.push(groups[sortedKeys[k]]);
      }}
    }}

    // 应用最大限制截断
    var limit = PERIOD_LIMITS[period];
    if (data.length > limit) {{
      return {{ data: data.slice(data.length - limit), truncated: true, total: data.length, shown: limit }};
    }}
    return {{ data: data, truncated: false, total: data.length, shown: data.length }};
  }}

  function getPeriodLabel(period) {{
    if (period === 'day') return '日';
    if (period === 'week') return '周';
    if (period === 'month') return '月';
    if (period === 'year') return '年';
    return period;
  }}

  function renderChart(period) {{
    var result = aggregateData(period);
    var data = result.data;
    var dates = data.map(function(d) {{ return d.date; }});
    var totalReturns = data.map(function(d) {{ return d.total_return_pct; }});
    var dailyPnls = data.map(function(d) {{ return d.daily_pnl; }});
    var prices = data.map(function(d) {{ return d.price; }});
    var vixs = data.map(function(d) {{ return d.vix; }});
    var marketValues = data.map(function(d) {{ return d.market_value; }});
    var unrealizedPnls = data.map(function(d) {{ return d.unrealized_pnl; }});

    // 截断提示
    var noticeEl = document.getElementById('truncation-notice');
    if (result.truncated) {{
      var nextPeriod = {{ day: '周', week: '月', month: '年' }};
      noticeEl.innerHTML = '<span style="color:#d97706;">⚠️ 数据量较大（共' + result.total + '条），当前仅显示最近' + result.shown + '条。' +
        '建议切换到 <strong>' + nextPeriod[period] + '</strong> 模式查看全部历史 →</span>';
      noticeEl.style.display = 'block';
    }} else {{
      noticeEl.style.display = 'none';
    }}

    var color = totalReturns[totalReturns.length - 1] >= 0 ? '#16a34a' : '#dc2626';
    var areaColorStart = totalReturns[totalReturns.length - 1] >= 0 ? 'rgba(22, 163, 74, 0.2)' : 'rgba(220, 38, 38, 0.2)';
    var areaColorEnd = totalReturns[totalReturns.length - 1] >= 0 ? 'rgba(22, 163, 74, 0.02)' : 'rgba(220, 38, 38, 0.02)';

    var option = {{
      tooltip: {{
        trigger: 'axis',
        backgroundColor: 'rgba(255,255,255,0.95)',
        borderColor: '#e5e7eb',
        borderWidth: 1,
        textStyle: {{ color: '#1f2937', fontSize: 12 }},
        formatter: function(params) {{
          var idx = params[0].dataIndex;
          var c = totalReturns[idx] >= 0 ? '#16a34a' : '#dc2626';
          var vixStr = vixs[idx] !== null && vixs[idx] !== undefined ? vixs[idx].toFixed(2) : '—';
          var mvStr = marketValues[idx] ? marketValues[idx].toLocaleString('zh-CN', {{minimumFractionDigits:2}}) : '—';
          return '<div style="font-weight:600;margin-bottom:6px;">' + dates[idx] + '</div>' +
            '<div style="display:grid;grid-template-columns:auto auto;gap:4px 16px;">' +
            '<span style="color:#6b7280;">累计收益率:</span> <span style="font-weight:600;color:' + c + '">' + (totalReturns[idx] >= 0 ? '+' : '') + totalReturns[idx].toFixed(2) + '%</span>' +
            '<span style="color:#6b7280;">当日盈亏:</span> <span style="font-weight:600;">' + (dailyPnls[idx] >= 0 ? '+' : '') + dailyPnls[idx].toFixed(2) + '元</span>' +
            '<span style="color:#6b7280;">ETF价格:</span> <span style="font-weight:600;">' + (prices[idx] ? prices[idx].toFixed(3) : '—') + '元</span>' +
            '<span style="color:#6b7280;">VIX:</span> <span style="font-weight:600;">' + vixStr + '</span>' +
            '<span style="color:#6b7280;">持仓市值:</span> <span style="font-weight:600;">' + mvStr + '元</span>' +
            '<span style="color:#6b7280;">浮动盈亏:</span> <span style="font-weight:600;color:' + c + '">' + (unrealizedPnls[idx] >= 0 ? '+' : '') + unrealizedPnls[idx].toFixed(2) + '元</span>' +
            '</div>';
        }}
      }},
      grid: {{ left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true }},
      xAxis: {{
        type: 'category',
        boundaryGap: false,
        data: dates,
        axisLine: {{ lineStyle: {{ color: '#e5e7eb' }} }},
        axisLabel: {{ color: '#6b7280', fontSize: 10, rotate: period === 'day' ? 30 : 0 }},
        axisTick: {{ show: false }}
      }},
      yAxis: {{
        type: 'value',
        axisLabel: {{ formatter: '{{value}}%', color: '#6b7280', fontSize: 11 }},
        axisLine: {{ show: false }},
        splitLine: {{ lineStyle: {{ color: '#f3f4f6', type: 'dashed' }} }},
        scale: true
      }},
      series: [
        {{
          name: '累计收益率',
          type: 'line',
          smooth: 0.3,
          symbol: 'circle',
          symbolSize: period === 'day' ? 4 : 7,
          showSymbol: period !== 'day',
          lineStyle: {{ width: 3, color: color }},
          itemStyle: {{ color: color, borderWidth: 2, borderColor: '#fff' }},
          areaStyle: {{
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              {{ offset: 0, color: areaColorStart }},
              {{ offset: 1, color: areaColorEnd }}
            ])
          }},
          data: totalReturns,
          markLine: {{
            silent: true,
            symbol: 'none',
            lineStyle: {{ color: '#9ca3af', type: 'solid', width: 1 }},
            data: [{{ yAxis: 0 }}],
            label: {{ show: false }}
          }}
        }}
      ],
      animationDuration: 500,
      animationEasing: 'cubicOut'
    }};

    chart.setOption(option, true);
  }}

  function switchPeriod(period) {{
    currentPeriod = period;
    document.querySelectorAll('.period-tab').forEach(function(btn) {{
      btn.classList.toggle('active', btn.dataset.period === period);
    }});
    renderChart(period);
  }}

  renderChart('day');
  window.addEventListener('resize', function() {{ chart.resize(); }});
</script>
</body>
</html>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"[图表] 已生成交互式收益率曲线HTML: {output_path}")


def record_daily_return(date_str, vix, price, state, daily_pnl, total_return_pct):
    """记录每日收益率到独立CSV文件"""
    pos = state['position']
    acc = state['account']

    # 确保文件存在并写入表头
    headers = ['date', 'vix', 'price', 'shares', 'avg_cost', 'market_value',
               'total_cost', 'unrealized_pnl', 'daily_pnl', 'return_pct',
               'total_return_pct', 'cash', 'net_value', 'note']

    file_exists = DAILY_RETURNS_FILE.exists()
    rows = []
    if file_exists:
        with open(DAILY_RETURNS_FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        # 检查是否已存在该日期
        for row in rows[1:]:
            if row and row[0] == date_str:
                print(f"[收益率] {date_str} 已存在，跳过")
                return
    else:
        # 首次创建：从 daily_snapshot.csv 导入历史数据
        if SNAPSHOT_FILE.exists():
            with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                snap_rows = list(reader)
            if snap_rows:
                with open(DAILY_RETURNS_FILE, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    for row in snap_rows:
                        ret_str = row.get('total_return_pct', '0').replace('%', '')
                        writer.writerow([
                            row['date'],
                            row.get('vix', ''),
                            row.get('etf_close', row.get('price', '')),
                            row.get('position_shares', row.get('shares', '')),
                            '',  # avg_cost
                            row.get('position_value', ''),
                            row.get('total_cost', ''),
                            row.get('unrealized_pnl', ''),
                            row.get('daily_pnl', ''),
                            '',  # return_pct
                            ret_str,
                            row.get('cash', ''),
                            row.get('net_value', ''),
                            row.get('note', '')
                        ])
                print(f"[收益率] 已从 daily_snapshot.csv 导入 {len(snap_rows)} 条历史数据")
                rows = [headers] + [[r.get(h, '') for h in headers] for r in snap_rows]

    with open(DAILY_RETURNS_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists and not rows:
            writer.writerow(headers)
        writer.writerow([
            date_str,
            vix,
            price,
            pos['shares'],
            round(pos['avg_cost'], 4),
            round(pos['market_value'], 2),
            round(pos['total_cost'], 2),
            round(pos['unrealized_pnl'], 2),
            round(daily_pnl, 2),
            pos['return_pct'],
            round(total_return_pct, 2),
            round(float(acc.get('cash', 0) or 0), 2),
            round(get_total_assets_value(state), 2),
            f"VIX{vix}"
        ])
    print(f"[收益率] 已记录 {date_str} 到 daily_returns.csv")


def load_daily_returns():
    """加载历史每日收益率数据，优先从 daily_returns.csv，不存在则从 daily_snapshot.csv 回退"""
    rows = []
    if DAILY_RETURNS_FILE.exists():
        with open(DAILY_RETURNS_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    'date': row['date'],
                    'total_return_pct': row['total_return_pct']
                })
        return rows

    # 回退：从 daily_snapshot.csv 导入历史数据
    if SNAPSHOT_FILE.exists():
        with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ret_str = row.get('total_return_pct', '0').replace('%', '')
                rows.append({
                    'date': row['date'],
                    'total_return_pct': ret_str
                })
    return rows


# ==================== 记录与同步 ====================

def record_snapshot(date_str, vix, price, state, daily_pnl, note):
    """记录每日快照到CSV"""
    pos = state['position']
    acc = state['account']
    if not SNAPSHOT_FILE.exists():
        with open(SNAPSHOT_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['date', 'vix', 'price', 'shares', 'position_value',
                           'cash', 'net_value', 'total_cost', 'unrealized_pnl',
                           'daily_pnl', 'return_pct', 'note'])
    if SNAPSHOT_FILE.exists():
        with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            existing = list(reader)
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
    print(f"[快照] 已记录 {date_str}")


def record_trades(trade_infos, state, date_str):
    """记录交易到CSV"""
    if not trade_infos:
        return
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
        for ti in trade_infos:
            fee = max(0.01, ti['amount'] * 0.0001)
            writer.writerow([
                ti['date'], ti['vix'], get_vix_zone(ti['vix']),
                ti['action'], ti['amount'], ti['shares'],
                ti['price'], fee, ti['amount'],
                cash + ti['amount'] if ti['action'] == 'BUY' else cash,
                cash, net_value, ti['label']
            ])
    print(f"[交易记录] 已记录 {len(trade_infos)} 笔交易")


def sync_to_public(state, dashboard):
    """同步数据到public目录供网页使用"""
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    public_file = PUBLIC_DIR / "dashboard_data.json"
    save_json(public_file, dashboard)
    print(f"[同步] 已同步到: {public_file}")

    # 同步收益率曲线SVG
    if RETURNS_CURVE_SVG.exists():
        public_svg = PUBLIC_DIR / "returns_curve.svg"
        with open(RETURNS_CURVE_SVG, 'r', encoding='utf-8') as src:
            with open(public_svg, 'w', encoding='utf-8') as dst:
                dst.write(src.read())
        print(f"[同步] 已同步收益率曲线SVG到: {public_svg}")

    # 同步收益率曲线HTML（交互式）
    if RETURNS_CURVE_HTML.exists():
        public_html = PUBLIC_DIR / "returns_curve.html"
        with open(RETURNS_CURVE_HTML, 'r', encoding='utf-8') as src:
            with open(public_html, 'w', encoding='utf-8') as dst:
                dst.write(src.read())
        print(f"[同步] 已同步收益率曲线HTML到: {public_html}")

    # 同步到 08-决策追踪 目录（数据一致性要求）
    if ALT_STRATEGY_DIR.exists():
        alt_dashboard = ALT_STRATEGY_DIR / "dashboard_data.json"
        save_json(alt_dashboard, dashboard)
        print(f"[同步] 已同步到: {alt_dashboard}")

        # 同步 daily_returns.csv
        alt_returns = ALT_STRATEGY_DIR / "daily_returns.csv"
        if DAILY_RETURNS_FILE.exists():
            with open(DAILY_RETURNS_FILE, 'r', encoding='utf-8') as src:
                with open(alt_returns, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())
            print(f"[同步] 已同步 daily_returns.csv 到: {alt_returns}")

        # 同步收益率曲线SVG
        alt_svg = ALT_STRATEGY_DIR / "returns_curve.svg"
        if RETURNS_CURVE_SVG.exists():
            with open(RETURNS_CURVE_SVG, 'r', encoding='utf-8') as src:
                with open(alt_svg, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())
            print(f"[同步] 已同步收益率曲线SVG到: {alt_svg}")

        # 同步收益率曲线HTML
        alt_html = ALT_STRATEGY_DIR / "returns_curve.html"
        if RETURNS_CURVE_HTML.exists():
            with open(RETURNS_CURVE_HTML, 'r', encoding='utf-8') as src:
                with open(alt_html, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())
            print(f"[同步] 已同步收益率曲线HTML到: {alt_html}")


# ==================== 主程序 ====================

def main():
    parser = argparse.ArgumentParser(description='VIX定投策略自动更新 V2.0')
    parser.add_argument('--date', help='日期 (YYYY-MM-DD)，默认今天')
    parser.add_argument('--vix', type=float, help='VIX值，默认自动获取')
    parser.add_argument('--price', type=float, help='ETF价格，默认自动获取')
    parser.add_argument('--dry-run', action='store_true', help='试运行不保存')
    parser.add_argument('--force', action='store_true', help='强制更新（即使今天已更新）')
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime('%Y-%m-%d')
    print(f"=== VIX定投策略自动更新 V2.0 ({date_str}) ===")
    print(f"数据时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    config = load_json(CONFIG_FILE)
    state = load_json(STATE_FILE)
    dashboard = load_json(DASHBOARD_FILE)
    ensure_trade_schedule(state, date_str)

    if state.get('account', {}).get('last_update') == date_str and not args.force:
        print(f"[跳过] {date_str} 已更新，使用 --force 强制更新")
        return 0

    is_trading = is_trading_day(
        date_str,
        state['statistics'].get('last_trade_date'),
        get_next_trade_date(state)
    )

    if args.vix is not None:
        vix = args.vix
        print(f"[VIX] 使用手动输入: {vix}")
    else:
        vix = get_vix_data()
        if vix is None:
            print("错误: 无法获取VIX数据，请使用 --vix 参数手动提供")
            return 1

    if args.price is not None:
        price = args.price
        print(f"[ETF] 使用手动输入: {price}")
    else:
        price = get_etf_price(date_str)
        if price is None:
            fallback = get_last_known_etf_price(state)
            if fallback and not is_trading:
                price = fallback['price']
                print(f"[ETF] 自动获取失败，非定投日改用上次价格 {price} (来源: {fallback['source']})")
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
        print(f"[定投日] 今天是定投日，将执行完整策略")
    else:
        print(f"[非定投日] 只更新收益，不执行交易")
    print()

    if args.dry_run:
        print("[试运行模式] 数据不会保存")
        print()

    trades_executed, trade_infos, pnl_data = update_state(
        state, config, date_str, vix, price, is_trading
    )

    print()
    print(f"=== 持仓摘要 ===")
    print(f"持仓: {state['position']['shares']}份")
    print(f"市值: {state['position']['market_value']:.2f}元")
    print(f"成本: {state['position']['total_cost']:.2f}元")
    print(f"收益: {state['position']['unrealized_pnl']:+.2f}元 ({state['position']['return_pct']:+.2f}%)")
    print(f"当日: {pnl_data['daily_pnl']:+.2f}元")
    for note in pnl_data.get('notes', []):
        print(f"备注: {note}")
    print()

    if not args.dry_run:
        save_json(STATE_FILE, state)
        print("[保存] state.json")

        dashboard = update_dashboard_data(dashboard, state, date_str, vix, price, trade_infos)
        save_json(DASHBOARD_FILE, dashboard)
        print("[保存] dashboard_data.json")

        note = f"VIX{vix}," + ("; ".join(pnl_data.get('notes', [])) if pnl_data.get('notes') else ("定投日" if is_trading else "持仓不动"))
        record_snapshot(date_str, vix, price, state, pnl_data['daily_pnl'], note)

        # 记录每日收益率到新文件
        record_daily_return(date_str, vix, price, state, pnl_data['daily_pnl'],
                           state['daily_performance']['total_return_pct'])

        # 生成收益率曲线图
        returns_history = load_daily_returns()
        if returns_history:
            generate_returns_curve_svg(RETURNS_CURVE_SVG, returns_history)

        # 生成交互式HTML图表（支持鼠标悬停）
        returns_history_full = load_daily_returns_full()
        if returns_history_full:
            generate_returns_curve_html(RETURNS_CURVE_HTML, returns_history_full)

        if trade_infos:
            record_trades(trade_infos, state, date_str)

        update_markdown_template(state, date_str, vix, price)
        sync_to_public(state, dashboard)

        print()
        print(f"=== 更新完成 ({date_str}) ===")
    else:
        print("[试运行] 数据未保存")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
