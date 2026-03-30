# -*- coding: utf-8 -*-
"""
模拟投资组合自动决策引擎 V3.1 (稳定版)

核心变更（V3.1）：
1. 稳定性优先：不再自动重建state，只读取现有state进行更新
2. 验证优先：每次运行前强制执行数据验证
3. 增量更新：只更新价格和执行交易，不修改历史数据
4. 备份机制：修改state前先创建备份

使用方式：
    python scripts/update_simulated_portfolio.py
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any

import pandas as pd
import yfinance as yf

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False


ROOT = Path(__file__).resolve().parents[1]
REPORT_POOL_DIR = ROOT / "07-分析输出"
TRACK_DIR = ROOT / "08-决策追踪"
PUBLIC_DIR = ROOT / "public" / "dashboard"
STATE_FILE = TRACK_DIR / "simulation_state.json"
TRADES_FILE = TRACK_DIR / "simulation_trades.csv"
DAILY_FILE = TRACK_DIR / "simulation_daily_snapshot.csv"
SNAPSHOT_FILE = TRACK_DIR / "dashboard_snapshot.json"
PUBLIC_SNAPSHOT_FILE = PUBLIC_DIR / "dashboard_snapshot.json"
AI_RECORD_FILE = TRACK_DIR / "AI决策记录.md"
VALIDATION_SCRIPT = ROOT / "scripts" / "validate_simulation_data.py"

INITIAL_CAPITAL = 500000.0
START_DATE = "2026-03-26"

# 风控参数
MIN_CASH_RESERVE = INITIAL_CAPITAL * 0.10
POSITION_CAP = 0.15

# Akshare缓存
HK_SPOT_CACHE: pd.DataFrame | None = None
A_SPOT_CACHE: pd.DataFrame | None = None
AK_HK_FAILED = False
AK_A_FAILED = False


@dataclass
class PricePoint:
    close: float
    prev_close: float
    trade_date: str


def run_data_validation() -> bool:
    """运行数据验证脚本"""
    print("[STEP] 执行数据硬约束验证...")
    
    if not VALIDATION_SCRIPT.exists():
        print("[WARN] 验证脚本不存在，跳过验证")
        return True
    
    try:
        result = subprocess.run(
            [sys.executable, str(VALIDATION_SCRIPT)],
            capture_output=True,
            cwd=ROOT
        )
        
        # 打印输出
        stdout = result.stdout.decode('utf-8', errors='replace') if result.stdout else ""
        stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ""
        if stdout:
            print(stdout)
        if stderr:
            print(stderr, file=sys.stderr)
        
        return result.returncode == 0
            
    except Exception as e:
        print("[WARN] 验证脚本执行失败: %s" % e)
        return True


def backup_state():
    """备份state文件"""
    if STATE_FILE.exists():
        backup_path = STATE_FILE.with_suffix(".json.%s.bak" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(STATE_FILE, backup_path)
        print("[BACKUP] 已备份state文件: %s" % backup_path.name)


def load_state() -> Dict:
    """加载state文件"""
    if not STATE_FILE.exists():
        raise FileNotFoundError("state文件不存在: %s" % STATE_FILE)
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: Dict):
    """保存state文件"""
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def parse_report_pool() -> Dict[str, Dict]:
    """从分析报告中解析报告池"""
    pool: Dict[str, Dict] = {}
    for report in REPORT_POOL_DIR.glob("*_投资分析报告.md"):
        m = re.match(r"(.+?)_(\d+)_投资分析报告", report.stem)
        if not m:
            continue
        name, code = m.group(1), m.group(2)
        
        # 标准化ticker
        if len(code) == 5:
            ticker = "%04d.HK" % int(code)
        elif code.startswith("6"):
            ticker = "%s.SS" % code
        else:
            ticker = "%s.SZ" % code
            
        try:
            content = report.read_text(encoding="utf-8")
        except Exception:
            continue

        # 解析买点
        buy_prices = []
        for line in content.splitlines():
            if "买点" in line and ("元" in line or "港元" in line):
                pm = re.search(r"(\d+(?:\.\d+)?)\s*[元港]", line)
                if pm:
                    buy_prices.append(float(pm.group(1)))
        target_buy = max(buy_prices) if buy_prices else None

        # 解析卖出触发价
        sm = re.search(r"卖出触发(?:价|条件)?[^\d]{0,10}(\d+(?:\.\d+)?)", content)
        sell_trigger = float(sm.group(1)) if sm else (target_buy * 1.35 if target_buy else 0.0)

        # 解析每手数量
        lm = re.search(r"每手数量[^\d]{0,10}([\d,]+)\s*股", content)
        lot_size = int(lm.group(1).replace(",", "")) if lm else (1000 if len(code) == 5 else 100)

        pool[ticker] = {
            "name": name,
            "code": code,
            "ticker": ticker,
            "target_buy": target_buy,
            "sell_trigger": sell_trigger,
            "lot_size": lot_size,
        }
    return pool


def sync_positions_with_pool(state: Dict, pool: Dict[str, Dict]):
    """同步持仓与报告池，只更新配置信息"""
    positions = state.get("positions", {})
    
    for ticker, info in pool.items():
        if ticker in positions:
            # 更新配置，不修改成本和持股数
            p = positions[ticker]
            p["name"] = info["name"]
            p["code"] = info["code"]
            p["lot_size"] = info["lot_size"]
            # 只在未设置时更新卖出触发价
            if info["sell_trigger"] and not p.get("sell_trigger"):
                p["sell_trigger"] = info["sell_trigger"]
            if info["target_buy"] and not p.get("target_buy"):
                p["target_buy"] = info["target_buy"]
        else:
            # 新标的：添加配置但持仓为0
            positions[ticker] = {
                "name": info["name"],
                "code": info["code"],
                "ticker": ticker,
                "shares": 0,
                "avg_cost": 0.0,
                "sell_trigger": info["sell_trigger"],
                "target_buy": info["target_buy"],
                "lot_size": info["lot_size"],
                "realized_pnl": 0.0,
            }
    
    state["positions"] = positions


# ========== 股价获取 ==========

def load_hk_spot() -> pd.DataFrame:
    global HK_SPOT_CACHE, AK_HK_FAILED
    if AK_HK_FAILED or not AKSHARE_AVAILABLE:
        return pd.DataFrame()
    if HK_SPOT_CACHE is None:
        try:
            HK_SPOT_CACHE = ak.stock_hk_spot_em()
        except Exception:
            AK_HK_FAILED = True
            return pd.DataFrame()
    return HK_SPOT_CACHE


def parse_float(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).replace(",", "").replace("%", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_price_from_akshare(code: str) -> PricePoint | None:
    if not AKSHARE_AVAILABLE:
        return None
    try:
        df = load_hk_spot()
        if df.empty or "代码" not in df.columns:
            return None
        code5 = str(code).zfill(5)
        cand = df[df["代码"].astype(str).str.zfill(5) == code5]
        
        if cand.empty:
            return None
        row = cand.iloc[0]
        close = parse_float(row.get("最新价"))
        change_pct = parse_float(row.get("涨跌幅"))
        if close is None:
            return None
        if change_pct is None:
            prev_close = close
        else:
            prev_close = close / (1 + change_pct / 100) if change_pct != -100 else close
        return PricePoint(
            close=float(close),
            prev_close=float(prev_close),
            trade_date=datetime.now().strftime("%Y-%m-%d"),
        )
    except Exception:
        return None


def fetch_price_from_yf(ticker: str) -> PricePoint | None:
    try:
        hist = yf.Ticker(ticker).history(period="7d", interval="1d", auto_adjust=False)
        if hist is None or hist.empty:
            return None
        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else latest
        return PricePoint(
            close=float(latest["Close"]),
            prev_close=float(prev["Close"]),
            trade_date=pd.Timestamp(hist.index[-1]).strftime("%Y-%m-%d"),
        )
    except Exception:
        return None


def fetch_price(ticker: str, code: str) -> PricePoint | None:
    """获取股价，优先akshare，失败用yfinance"""
    # 先尝试akshare
    if len(code) == 5:
        pp = fetch_price_from_akshare(code)
        if pp:
            return pp
    
    # yfinance兜底
    return fetch_price_from_yf(ticker)


# ========== 交易决策 ==========

def maybe_sell(position: Dict, price: float) -> Tuple[str, int, float, float, str]:
    """卖出规则"""
    shares = int(position.get("shares", 0))
    if shares <= 0:
        return ("HOLD", 0, 0.0, 0.0, "无持仓")
    
    sell_trigger = position.get("sell_trigger")
    if not sell_trigger or float(sell_trigger) <= 0:
        return ("HOLD", 0, 0.0, 0.0, "未设置卖出价")
    
    if price >= float(sell_trigger):
        amount = shares * price
        return ("SELL", shares, price, amount, "达到卖出触发价 %s" % sell_trigger)
    return ("HOLD", 0, 0.0, 0.0, "未达到卖出条件")


def maybe_add(position: Dict, price: float, cash: float) -> Tuple[str, int, float, float, str]:
    """加仓规则：回撤5%"""
    shares = int(position.get("shares", 0))
    if shares <= 0:
        return ("HOLD", 0, 0.0, 0.0, "无持仓")
    
    avg_cost = float(position.get("avg_cost", 0))
    if avg_cost <= 0:
        return ("HOLD", 0, 0.0, 0.0, "成本异常")
    
    if price > avg_cost * 0.95:
        return ("HOLD", 0, 0.0, 0.0, "未达到回撤5%线")
    
    max_value = INITIAL_CAPITAL * POSITION_CAP
    current_value = shares * price
    remain_budget = max(0.0, max_value - current_value)
    budget = min(remain_budget, cash)
    
    lot_size = int(position.get("lot_size", 1000))
    lot_cost = lot_size * price
    if lot_cost <= 0:
        return ("HOLD", 0, 0.0, 0.0, "手数异常")
    
    buy_lots = int(budget // lot_cost)
    buy_shares = buy_lots * lot_size
    if buy_shares <= 0:
        return ("HOLD", 0, 0.0, 0.0, "预算不足")
    
    amount = buy_shares * price
    return ("BUY_ADD", buy_shares, price, amount, "触发回撤5%加仓")


# ========== 数据持久化 ==========

def append_trade_record(record: Dict):
    """追加交易记录"""
    if TRADES_FILE.exists():
        df = pd.read_csv(TRADES_FILE, encoding="utf-8-sig")
        df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
    else:
        df = pd.DataFrame([record])
    df.to_csv(TRADES_FILE, index=False, encoding="utf-8-sig")


def append_daily_row(row: Dict):
    """追加每日快照"""
    if DAILY_FILE.exists():
        df = pd.read_csv(DAILY_FILE, encoding="utf-8-sig")
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])
    df.to_csv(DAILY_FILE, index=False, encoding="utf-8-sig")


# ========== Dashboard ==========

def build_dashboard_snapshot(state: Dict, price_map: Dict[str, PricePoint]):
    """生成Dashboard快照"""
    cash = float(state.get("cash", 0))
    
    positions = []
    total_mv = 0.0
    for ticker, pos in state["positions"].items():
        shares = int(pos.get("shares", 0))
        if shares <= 0:
            continue
        
        avg_cost = float(pos.get("avg_cost", 0))
        pp = price_map.get(ticker)
        close = pp.close if pp else avg_cost
        prev = pp.prev_close if pp else close
        change = ((close / prev - 1) * 100) if prev else 0.0
        mv = shares * close
        unrealized = (close - avg_cost) * shares
        total_mv += mv
        
        code = str(pos.get("code", ""))
        if len(code) == 5:
            code = code.zfill(5)
        
        positions.append({
            "name": pos.get("name", ""),
            "code": code,
            "ticker": ticker,
            "shares": shares,
            "avg_cost": round(avg_cost, 6),
            "close": round(close, 4),
            "change_pct": round(change, 4),
            "market_value": round(mv, 2),
            "unrealized": round(unrealized, 2),
            "sell_trigger": float(pos.get("sell_trigger", 0) or 0),
            "weight_pct": 0.0,  # 稍后计算
            "status": "实时" if pp else "占位",
        })
    
    positions.sort(key=lambda x: x["code"])
    net_value = total_mv + cash
    total_return = (net_value / INITIAL_CAPITAL - 1) * 100
    
    for p in positions:
        p["weight_pct"] = round((p["market_value"] / net_value) * 100, 4) if net_value else 0.0
    
    snapshot = {
        "meta": {
            "template_version": "V5.5.12",
            "engine_version": "V3.1",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "latest_trade_date": state.get("last_trade_date", START_DATE),
        },
        "portfolio": {
            "initial_capital": INITIAL_CAPITAL,
            "cash": round(cash, 2),
            "market_value": round(total_mv, 2),
            "net_value": round(net_value, 2),
            "total_return_pct": round(total_return, 4),
            "position_ratio_pct": round((total_mv / INITIAL_CAPITAL) * 100, 4),
            "positions": positions,
        },
        "today_actions": [],
    }
    
    text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    SNAPSHOT_FILE.write_text(text, encoding="utf-8")
    PUBLIC_SNAPSHOT_FILE.write_text(text, encoding="utf-8")
    
    return snapshot


# ========== 主运行逻辑 ==========

def run() -> int:
    print("=" * 60)
    print("[START] 模拟投资组合决策引擎 V3.1")
    print("=" * 60)
    print()
    
    # 步骤1：数据验证
    if not run_data_validation():
        print("[ERROR] 数据验证失败，请修复后再运行")
        return 1
    print()
    
    # 步骤2：加载state
    print("[STEP] 加载state...")
    try:
        state = load_state()
    except FileNotFoundError as e:
        print("[ERROR] %s" % e)
        return 1
    
    cash = float(state.get("cash", 0))
    print("[OK] 现金: %.2f HKD" % cash)
    print("[OK] 持仓: %d 只标的" % len([p for p in state["positions"].values() if int(p.get("shares", 0)) > 0]))
    print()
    
    # 步骤3：同步报告池
    print("[STEP] 同步报告池...")
    pool = parse_report_pool()
    sync_positions_with_pool(state, pool)
    print("[OK] 报告池标的: %d" % len(pool))
    print()
    
    # 步骤4：获取行情
    print("[STEP] 获取行情...")
    price_map = {}
    for ticker, pos in list(state["positions"].items())[:10]:  # 限制前10个
        code = str(pos.get("code", ""))
        pp = fetch_price(ticker, code)
        if pp:
            price_map[ticker] = pp
            print("[OK] %s: %.3f" % (ticker, pp.close))
    
    if not price_map:
        print("[WARN] 未获取到行情")
        return 0
    
    # 确定交易日期
    trade_date = max(pp.trade_date for pp in price_map.values())
    last_date = str(state.get("last_trade_date", ""))
    
    if trade_date <= last_date:
        print("[INFO] 日期未更新 (%s)，仅刷新报告" % trade_date)
        build_dashboard_snapshot(state, price_map)
        return 0
    
    print()
    print("[STEP] 执行交易决策 (%s)..." % trade_date)
    
    # 备份state
    backup_state()
    
    # 执行交易
    daily_rows = []
    has_trade = False
    
    for ticker in sorted(state["positions"].keys()):
        pos = state["positions"][ticker]
        pp = price_map.get(ticker)
        if not pp or pp.trade_date != trade_date:
            continue
        
        shares = int(pos.get("shares", 0))
        avg_cost = float(pos.get("avg_cost", 0))
        action = "HOLD"
        action_shares = 0
        action_price = 0.0
        action_amount = 0.0
        
        # 先尝试卖出
        sell_result = maybe_sell(pos, pp.close)
        if sell_result[0] == "SELL":
            action, action_shares, action_price, action_amount, reason = sell_result
            realized = (action_price - avg_cost) * action_shares
            pos["realized_pnl"] = float(pos.get("realized_pnl", 0)) + realized
            pos["shares"] = 0
            cash += action_amount
            has_trade = True
            
            append_trade_record({
                "date": trade_date,
                "ticker": ticker,
                "name": pos.get("name", ""),
                "code": pos.get("code", ""),
                "action": action,
                "price": round(action_price, 4),
                "shares": int(action_shares),
                "amount": round(action_amount, 2),
                "cash_after": round(cash, 2),
                "reason": reason,
            })
            print("[ALERT] 卖出: %s %d股 @ %.3f" % (pos.get("name"), action_shares, action_price))
        
        # 再尝试加仓
        elif shares > 0:
            add_result = maybe_add(pos, pp.close, cash)
            if add_result[0] == "BUY_ADD":
                action, action_shares, action_price, action_amount, reason = add_result
                new_shares = shares + action_shares
                new_cost = (shares * avg_cost + action_amount) / new_shares
                pos["shares"] = new_shares
                pos["avg_cost"] = round(new_cost, 6)
                cash -= action_amount
                has_trade = True
                
                append_trade_record({
                    "date": trade_date,
                    "ticker": ticker,
                    "name": pos.get("name", ""),
                    "code": pos.get("code", ""),
                    "action": action,
                    "price": round(action_price, 4),
                    "shares": int(action_shares),
                    "amount": round(action_amount, 2),
                    "cash_after": round(cash, 2),
                    "reason": reason,
                })
                print("[ALERT] 加仓: %s %d股 @ %.3f" % (pos.get("name"), action_shares, action_price))
        
        # 记录每日快照
        mv = int(pos.get("shares", 0)) * pp.close
        unrealized = (pp.close - avg_cost) * int(pos.get("shares", 0)) if shares > 0 else 0
        daily_rows.append({
            "date": trade_date,
            "ticker": ticker,
            "name": pos.get("name", ""),
            "code": pos.get("code", ""),
            "close": round(pp.close, 4),
            "prev_close": round(pp.prev_close, 4),
            "change_pct": round((pp.close / pp.prev_close - 1) * 100 if pp.prev_close else 0, 4),
            "shares": int(pos.get("shares", 0)),
            "avg_cost": round(float(pos.get("avg_cost", 0)), 6),
            "action": action,
            "action_shares": int(action_shares),
            "action_price": round(action_price, 4),
            "action_amount": round(action_amount, 2),
            "market_value": round(mv, 2),
            "unrealized_pnl": round(unrealized, 2),
            "cash_after": round(cash, 2),
        })
    
    # 更新state
    state["cash"] = round(cash, 2)
    state["last_trade_date"] = trade_date
    save_state(state)
    
    # 保存每日快照
    total_mv = sum(r["market_value"] for r in daily_rows)
    net_value = total_mv + cash
    total_return = (net_value / INITIAL_CAPITAL - 1) * 100
    for r in daily_rows:
        r["net_value"] = round(net_value, 2)
        r["total_return_pct"] = round(total_return, 4)
        append_daily_row(r)
    
    # 生成Dashboard
    snapshot = build_dashboard_snapshot(state, price_map)
    
    print()
    print("=" * 60)
    print("[DONE] 更新完成")
    print("=" * 60)
    print("交易日: %s" % trade_date)
    print("净值: %.2f HKD" % snapshot["portfolio"]["net_value"])
    print("收益率: %.2f%%" % snapshot["portfolio"]["total_return_pct"])
    if has_trade:
        print("今日操作: 有")
    else:
        print("今日操作: 无")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
