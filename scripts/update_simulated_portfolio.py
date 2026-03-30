# -*- coding: utf-8 -*-
"""
模拟投资组合自动决策引擎 V2.1（报告池动态筛选 + Dashboard 整合版）

核心功能：
1. 报告池动态筛选（07-分析输出/*_投资分析报告.md）
2. 持仓与报告池自动同步
3. 卖出触发 / 回撤5%加仓 / 动态开仓
4. Akshare + yfinance 双源股价获取
5. Dashboard 快照生成（public/dashboard/dashboard_snapshot.json）
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any

import pandas as pd
import yfinance as yf

# 尝试导入 akshare，如果失败则标记
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

INITIAL_CAPITAL = 500000.0
START_DATE = "2026-03-26"
START_CASH = 52500.0

# V2.0 风控参数
MIN_CASH_RESERVE = INITIAL_CAPITAL * 0.10
POSITION_CAP = 0.15  # 单仓上限 15%

# Akshare 缓存
HK_SPOT_CACHE: pd.DataFrame | None = None
A_SPOT_CACHE: pd.DataFrame | None = None
AK_HK_FAILED = False
AK_A_FAILED = False

INITIAL_POSITIONS = [
    {
        "name": "京投交通科技",
        "code": "01522",
        "ticker": "1522.HK",
        "lot_size": 2000,
        "shares": 342000,
        "avg_cost": 0.365,
        "initial_investment": 124830.0,
        "sell_trigger": 0.60,
        "max_weight": POSITION_CAP,
        "position_type": "核心",
    },
    {
        "name": "汇贤产业信托",
        "code": "87001",
        "ticker": "87001.HK",
        "lot_size": 1000,
        "shares": 250000,
        "avg_cost": 0.50,
        "initial_investment": 125000.0,
        "sell_trigger": 1.00,
        "max_weight": POSITION_CAP,
        "position_type": "核心",
    },
    {
        "name": "天津发展",
        "code": "00882",
        "ticker": "882.HK",
        "lot_size": 1000,
        "shares": 40000,
        "avg_cost": 2.50,
        "initial_investment": 100000.0,
        "sell_trigger": 4.50,
        "max_weight": POSITION_CAP,
        "position_type": "核心",
    },
    {
        "name": "华润医药",
        "code": "03320",
        "ticker": "3320.HK",
        "lot_size": 500,
        "shares": 15000,
        "avg_cost": 6.50,
        "initial_investment": 97500.0,
        "sell_trigger": 9.00,
        "max_weight": POSITION_CAP,
        "position_type": "卫星",
    },
]


@dataclass
class PricePoint:
    close: float
    prev_close: float
    trade_date: str


def normalize_hk_ticker(code: str, ticker: str | None = None) -> str:
    """标准化港股 ticker 为 yfinance 可识别格式（去前导 0）。"""
    if ticker and ticker.endswith(".HK"):
        raw = ticker[:-3]
    else:
        raw = str(code).strip()
    try:
        num = int(raw)
        if num <= 9999:
            return f"{num:04d}.HK"
        return f"{num}.HK"
    except ValueError:
        return f"{raw}.HK"


def build_ticker(code: str) -> str:
    """从股票代码构建 ticker（V2.0 兼容）。"""
    if len(code) == 5:
        return f"{int(code)}.HK"
    if code.startswith("6"):
        return f"{code}.SS"
    return f"{code}.SZ"


def default_lot_size(code: str) -> int:
    """默认每手股数。"""
    return 1000 if len(code) == 5 else 100


def normalize_state_positions(positions: Dict[str, Dict]) -> Tuple[Dict[str, Dict], bool]:
    """兼容迁移旧版 5 位港股 ticker 键。"""
    normalized: Dict[str, Dict] = {}
    changed = False
    for old_key, pos in positions.items():
        code = str(pos.get("code", ""))
        new_key = normalize_hk_ticker(code, str(pos.get("ticker", old_key)))
        if new_key != old_key:
            changed = True
        pos["ticker"] = new_key
        normalized[new_key] = pos
    return normalized, changed


def parse_report_pool() -> Dict[str, Dict]:
    """V2.0: 从分析报告中解析报告池。"""
    pool: Dict[str, Dict] = {}
    for report in REPORT_POOL_DIR.glob("*_投资分析报告.md"):
        m = re.match(r"(.+?)_(\d+)_投资分析报告", report.stem)
        if not m:
            continue
        name, code = m.group(1), m.group(2)
        ticker = build_ticker(code)
        try:
            content = report.read_text(encoding="utf-8")
        except Exception:
            continue

        buy_prices = []
        for line in content.splitlines():
            if "买点" in line and ("元" in line or "港元" in line):
                pm = re.search(r"(\d+(?:\.\d+)?)\s*[元港]", line)
                if pm:
                    buy_prices.append(float(pm.group(1)))
        target_buy = max(buy_prices) if buy_prices else None

        sm = re.search(r"卖出触发(?:价|条件)?[^\d]{0,10}(\d+(?:\.\d+)?)", content)
        sell_trigger = float(sm.group(1)) if sm else (target_buy * 1.35 if target_buy else 0.0)

        lm = re.search(r"每手数量[^\d]{0,10}([\d,]+)\s*股", content)
        lot_size = int(lm.group(1).replace(",", "")) if lm else default_lot_size(code)

        status = "观望"
        if "可建仓" in content or "买入" in content:
            status = "可买入"
        if "回避" in content:
            status = "回避"

        pool[ticker] = {
            "name": name,
            "code": code,
            "ticker": ticker,
            "target_buy": target_buy,
            "sell_trigger": sell_trigger,
            "lot_size": lot_size,
            "status": status,
            "max_weight": POSITION_CAP,
        }
    return pool


def sync_positions_with_pool(state: Dict, pool: Dict[str, Dict]) -> Dict:
    """V2.0: 同步持仓状态与报告池。"""
    positions = state.get("positions", {})
    
    # 先标准化已有持仓
    positions, _ = normalize_state_positions(positions)
    
    # 添加报告池中的新标的
    for ticker, info in pool.items():
        if ticker not in positions:
            positions[ticker] = {
                "name": info["name"],
                "code": info["code"],
                "ticker": ticker,
                "shares": 0,
                "avg_cost": 0.0,
                "sell_trigger": info["sell_trigger"],
                "target_buy": info["target_buy"],
                "lot_size": info["lot_size"],
                "max_weight": POSITION_CAP,
                "added_cost_total": 0.0,
                "realized_pnl": 0.0,
            }
        else:
            # 更新已有持仓的配置
            p = positions[ticker]
            p["name"] = info["name"]
            p["code"] = info["code"]
            p["lot_size"] = info["lot_size"]
            p["sell_trigger"] = info["sell_trigger"] or p.get("sell_trigger", 0.0)
            p["target_buy"] = info["target_buy"] if info["target_buy"] else p.get("target_buy")
            p["max_weight"] = POSITION_CAP
    
    # 清理无持仓且不在报告池中的标的
    active_tickers = set(pool.keys())
    to_drop = [t for t, p in positions.items() if t not in active_tickers and int(p.get("shares", 0)) == 0]
    for t in to_drop:
        positions.pop(t, None)
    
    state["positions"] = positions
    return state


def seed_state() -> Dict:
    """V2.0: 从 INITIAL_POSITIONS 初始化状态。"""
    positions: Dict[str, Dict] = {}
    for row in INITIAL_POSITIONS:
        ticker = normalize_hk_ticker(row["code"], row["ticker"])
        positions[ticker] = {
            **row,
            "ticker": ticker,
            "added_cost_total": 0.0,
            "realized_pnl": 0.0,
        }
    
    return {
        "template_version": "V5.5.12",
        "engine_version": "V2.1",
        "initial_capital": INITIAL_CAPITAL,
        "cash": START_CASH,
        "last_trade_date": START_DATE,
        "positions": positions,
    }


def ensure_state() -> Dict:
    """初始化或加载状态文件。"""
    TRACK_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        positions, changed = normalize_state_positions(state.get("positions", {}))
        if changed:
            state["positions"] = positions
            STATE_FILE.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        seed_baseline_files(state)
        return state

    state = seed_state()
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    seed_baseline_files(state)
    return state


def seed_baseline_files(state: Dict) -> None:
    """首次初始化时写入建仓日基线记录。"""
    initial_map = {}
    for row in INITIAL_POSITIONS:
        tk = normalize_hk_ticker(row["code"], row["ticker"])
        initial_map[tk] = row

    if not TRADES_FILE.exists():
        records = []
        for tk, p in state["positions"].items():
            base = initial_map.get(tk, p)
            if int(base.get("shares", 0)) > 0:
                records.append({
                    "date": START_DATE,
                    "ticker": p["ticker"],
                    "name": p["name"],
                    "action": "INIT_BUY",
                    "price": base["avg_cost"],
                    "shares": base["shares"],
                    "amount": round(base["shares"] * base["avg_cost"], 2),
                    "cash_after": START_CASH,
                    "reason": "初始建仓",
                })
        if records:
            pd.DataFrame(records).to_csv(TRADES_FILE, index=False, encoding="utf-8-sig")

    if DAILY_FILE.exists():
        return

    market_value = 0.0
    rows = []
    for tk, p in state["positions"].items():
        base = initial_map.get(tk, p)
        shares = int(base.get("shares", 0))
        if shares == 0:
            continue
        mv = shares * base["avg_cost"]
        market_value += mv
        rows.append({
            "date": START_DATE,
            "ticker": p["ticker"],
            "name": p["name"],
            "code": p["code"],
            "close": base["avg_cost"],
            "prev_close": base["avg_cost"],
            "change_pct": 0.0,
            "shares": shares,
            "avg_cost": base["avg_cost"],
            "action": "INIT",
            "action_shares": 0,
            "action_price": 0.0,
            "action_amount": 0.0,
            "market_value": mv,
            "unrealized_pnl": 0.0,
            "cash_after": START_CASH,
            "net_value": market_value + START_CASH,
            "total_return_pct": ((market_value + START_CASH) / INITIAL_CAPITAL - 1) * 100,
        })
    if rows:
        pd.DataFrame(rows).to_csv(DAILY_FILE, index=False, encoding="utf-8-sig")


# ========== 股价获取（Akshare + yfinance 双源）==========

def load_hk_spot() -> pd.DataFrame:
    """加载港股实时行情（Akshare）。"""
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


def load_a_spot() -> pd.DataFrame:
    """加载A股实时行情（Akshare）。"""
    global A_SPOT_CACHE, AK_A_FAILED
    if AK_A_FAILED or not AKSHARE_AVAILABLE:
        return pd.DataFrame()
    if A_SPOT_CACHE is None:
        try:
            A_SPOT_CACHE = ak.stock_zh_a_spot_em()
        except Exception:
            AK_A_FAILED = True
            return pd.DataFrame()
    return A_SPOT_CACHE


def parse_float(v) -> float | None:
    """解析数值。"""
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
    """从 Akshare 获取股价。"""
    if not AKSHARE_AVAILABLE:
        return None
    try:
        if len(code) == 5:  # 港股
            df = load_hk_spot()
            if df.empty or "代码" not in df.columns:
                return None
            code5 = str(code).zfill(5)
            cand = df[df["代码"].astype(str).str.zfill(5) == code5]
        else:  # A股
            df = load_a_spot()
            if df.empty or "代码" not in df.columns:
                return None
            code6 = str(code).zfill(6)
            cand = df[df["代码"].astype(str).str.zfill(6) == code6]

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


def fetch_price_point_with_fallback(ticker: str, code: str = "") -> PricePoint | None:
    """获取股价，Akshare 优先，失败则用 yfinance。"""
    # 先尝试 Akshare
    if code:
        ak_pp = fetch_price_from_akshare(code)
        if ak_pp:
            return ak_pp

    # yfinance 兜底
    candidates = [ticker]
    if len(code) == 5:
        candidates = []
        if code.startswith("0"):
            candidates.extend([
                f"{code[1:]}.HK",
                f"{code}.HK",
                f"{int(code)}.HK",
            ])
        else:
            candidates.extend([f"{code}.HK", f"{int(code)}.HK"])
    
    for tk in candidates:
        try:
            hist = yf.Ticker(tk).history(period="7d", interval="1d", auto_adjust=False)
            if hist is None or hist.empty:
                continue
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) >= 2 else latest
            return PricePoint(
                close=float(latest["Close"]),
                prev_close=float(prev["Close"]),
                trade_date=pd.Timestamp(hist.index[-1]).strftime("%Y-%m-%d"),
            )
        except Exception:
            continue
    return None


# ========== 交易决策 ==========

def choose_trade_date(price_map: Dict[str, PricePoint]) -> str:
    """选择本次决策使用的交易日（取多数日期）。"""
    date_count: Dict[str, int] = {}
    for pp in price_map.values():
        date_count[pp.trade_date] = date_count.get(pp.trade_date, 0) + 1
    return sorted(date_count.items(), key=lambda x: (-x[1], x[0]))[0][0]


def maybe_sell(position: Dict, price: float) -> Tuple[str, int, float, float, str]:
    """卖出规则：达到目标价即全仓卖出。"""
    shares = int(position["shares"])
    if shares <= 0:
        return ("HOLD", 0, 0.0, 0.0, "无持仓")
    if price >= float(position["sell_trigger"]):
        amount = shares * price
        return ("SELL", shares, price, amount, f"达到卖出触发价 {position['sell_trigger']}")
    return ("HOLD", 0, 0.0, 0.0, "未达到卖出条件")


def maybe_open(position: Dict, price: float, cash: float) -> Tuple[str, int, float, float, str]:
    """V2.0: 开仓规则：到达买点且未持仓时开仓。"""
    shares = int(position.get("shares", 0))
    if shares > 0:
        return ("HOLD", 0, 0.0, 0.0, "已有持仓")

    target_buy = position.get("target_buy")
    if not target_buy or price > float(target_buy):
        return ("WATCH", 0, 0.0, 0.0, "未到买点")

    available_cash = max(0.0, cash - MIN_CASH_RESERVE)
    if available_cash <= 0:
        return ("WATCH", 0, 0.0, 0.0, "保留现金不足")

    max_value = INITIAL_CAPITAL * POSITION_CAP
    budget = min(max_value, available_cash)
    lot_size = int(position.get("lot_size", 1000))
    lot_cost = lot_size * price
    if lot_cost <= 0:
        return ("WATCH", 0, 0.0, 0.0, "手数异常")
    
    buy_lots = int(budget // lot_cost)
    buy_shares = buy_lots * lot_size
    if buy_shares <= 0:
        return ("WATCH", 0, 0.0, 0.0, "预算不足一手")

    amount = buy_shares * price
    return ("BUY_OPEN", buy_shares, price, amount, "到达买点自动开仓")


def maybe_add(position: Dict, price: float, cash: float) -> Tuple[str, int, float, float, str]:
    """加仓规则：回撤5%且不超过仓位上限。"""
    shares = int(position["shares"])
    if shares <= 0:
        return ("HOLD", 0, 0.0, 0.0, "已清仓，不加仓")

    avg_cost = float(position["avg_cost"])
    if price > avg_cost * 0.95:
        return ("HOLD", 0, 0.0, 0.0, "未达到回撤5%加仓线")

    max_value = INITIAL_CAPITAL * POSITION_CAP
    current_value = shares * price
    remain_weight_budget = max(0.0, max_value - current_value)
    remain_add_budget = max(0.0, float(position.get("initial_investment", 0)) * 0.30 - float(position.get("added_cost_total", 0)))
    budget = min(remain_weight_budget, remain_add_budget, cash)

    lot_size = int(position["lot_size"])
    lot_cost = lot_size * price
    if lot_cost <= 0:
        return ("HOLD", 0, 0.0, 0.0, "手数配置异常")

    buy_lots = int(budget // lot_cost)
    buy_shares = buy_lots * lot_size
    if buy_shares <= 0:
        return ("HOLD", 0, 0.0, 0.0, "现金或仓位上限不足")

    amount = buy_shares * price
    return ("BUY_ADD", buy_shares, price, amount, "触发回撤5%自动加仓")


# ========== 数据持久化 ==========

def append_trade_records(records: List[Dict]) -> None:
    if not records:
        return
    if TRADES_FILE.exists():
        old = pd.read_csv(TRADES_FILE, encoding="utf-8-sig")
        new_df = pd.concat([old, pd.DataFrame(records)], ignore_index=True)
    else:
        new_df = pd.DataFrame(records)
    new_df.to_csv(TRADES_FILE, index=False, encoding="utf-8-sig")


def append_daily_rows(rows: List[Dict]) -> None:
    if DAILY_FILE.exists():
        old = pd.read_csv(DAILY_FILE, encoding="utf-8-sig")
        new_df = pd.concat([old, pd.DataFrame(rows)], ignore_index=True)
    else:
        new_df = pd.DataFrame(rows)
    new_df.to_csv(DAILY_FILE, index=False, encoding="utf-8-sig")


# ========== Dashboard 功能 ==========

def build_trade_summary(latest_date: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """返回今日操作和最近操作流水。"""
    if not TRADES_FILE.exists():
        return ([], [])
    trades_df = pd.read_csv(TRADES_FILE, encoding="utf-8-sig")
    if trades_df.empty:
        return ([], [])
    trades_df = trades_df.sort_values(["date", "ticker"], ascending=[False, True])
    today_ops = trades_df[
        (trades_df["date"] == latest_date)
        & (trades_df["action"].isin(["BUY_OPEN", "BUY_ADD", "SELL"]))
    ]
    recent_ops = trades_df.head(20)
    return (today_ops.to_dict("records"), recent_ops.to_dict("records"))


def parse_ai_decision_summary() -> Dict[str, Any]:
    """读取 AI决策记录.md 摘要，供仪表盘只读展示。"""
    if not AI_RECORD_FILE.exists():
        return {
            "title": "AI决策记录与追踪",
            "raw_excerpt": "未找到 AI决策记录.md",
            "table_rows": [],
        }

    content = AI_RECORD_FILE.read_text(encoding="utf-8")
    lines = content.splitlines()
    excerpt = "\n".join(lines[:120]).strip()

    table_rows: List[Dict[str, str]] = []
    in_table = False
    for line in lines:
        if line.startswith("| 日期 |") and "标的" in line and "操作" in line:
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 9:
                table_rows.append({
                    "date": cells[0],
                    "name": cells[1],
                    "code": cells[2],
                    "action": cells[3],
                    "suggest_price": cells[4],
                    "current_price": cells[5],
                    "yield_rate": cells[6],
                    "reason": cells[7],
                    "status": cells[8],
                })
            continue
        if in_table and line.strip() == "":
            break

    return {
        "title": "AI决策记录与追踪",
        "raw_excerpt": excerpt,
        "table_rows": table_rows,
    }


def build_dashboard_snapshot(price_map: Dict[str, PricePoint] | None = None) -> Dict[str, Any]:
    """生成仪表盘快照，作为唯一展示数据源。"""
    state = ensure_state()
    latest_date = str(state.get("last_trade_date", START_DATE))
    cash = float(state.get("cash", START_CASH))

    positions: List[Dict[str, Any]] = []
    total_market_value = 0.0
    for ticker, pos in state["positions"].items():
        shares = int(pos["shares"])
        avg_cost = float(pos["avg_cost"])
        pp = (price_map or {}).get(ticker)
        close_price = float(pp.close) if pp else avg_cost
        prev_close = float(pp.prev_close) if pp else close_price
        change_pct = ((close_price / prev_close - 1) * 100) if prev_close else 0.0
        market_value = shares * close_price
        unrealized = (close_price - avg_cost) * shares
        total_market_value += market_value
        positions.append({
            "name": pos["name"],
            "code": str(pos["code"]).zfill(5),
            "ticker": ticker,
            "shares": shares,
            "avg_cost": round(avg_cost, 6),
            "close": round(close_price, 4),
            "change_pct": round(change_pct, 4),
            "market_value": round(market_value, 2),
            "unrealized": round(unrealized, 2),
            "sell_trigger": float(pos.get("sell_trigger", 0)),
            "status": "实时" if pp else "占位",
        })

    positions.sort(key=lambda x: x["code"])
    net_value = total_market_value + cash
    total_return_pct = (net_value / INITIAL_CAPITAL - 1) * 100
    for p in positions:
        p["weight_pct"] = round((float(p["market_value"]) / net_value) * 100, 4) if net_value else 0.0
    
    today_ops, recent_ops = build_trade_summary(latest_date)
    ai_summary = parse_ai_decision_summary()

    snapshot = {
        "meta": {
            "template_version": "V5.5.12",
            "engine_version": "V2.1",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "latest_trade_date": latest_date,
            "source": [
                "simulation_state.json",
                "simulation_trades.csv",
                "simulation_daily_snapshot.csv",
                "AI决策记录.md",
            ],
        },
        "portfolio": {
            "initial_capital": INITIAL_CAPITAL,
            "cash": round(cash, 2),
            "market_value": round(total_market_value, 2),
            "net_value": round(net_value, 2),
            "total_return_pct": round(total_return_pct, 4),
            "position_ratio_pct": round((total_market_value / INITIAL_CAPITAL) * 100, 4),
            "positions": positions,
        },
        "today_actions": today_ops,
        "recent_actions": recent_ops,
        "ai_decisions": ai_summary,
    }
    snapshot_text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    SNAPSHOT_FILE.write_text(snapshot_text, encoding="utf-8")
    PUBLIC_SNAPSHOT_FILE.write_text(snapshot_text, encoding="utf-8")
    return snapshot


# ========== 主运行逻辑 ==========

def run() -> int:
    """主运行函数。"""
    state = ensure_state()
    
    # 解析报告池并同步持仓
    pool = parse_report_pool()
    state = sync_positions_with_pool(state, pool)
    
    # 保存同步后的状态
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    # 拉行情
    price_map: Dict[str, PricePoint] = {}
    for ticker in state["positions"].keys():
        code = str(state["positions"][ticker].get("code", ""))
        pp = fetch_price_point_with_fallback(ticker, code)
        if pp:
            price_map[ticker] = pp

    if not price_map:
        print("[WARN] 未获取到任何行情，生成占位报告。")
        build_dashboard_snapshot(price_map=None)
        return 0

    trade_date = choose_trade_date(price_map)
    if trade_date <= str(state.get("last_trade_date", "")):
        print(f"[INFO] 最新交易日 {trade_date} 未超过已处理日期 {state.get('last_trade_date')}，仅刷新报告。")
        build_dashboard_snapshot(price_map=price_map)
        return 0

    cash = float(state["cash"])
    daily_rows: List[Dict] = []
    trade_records: List[Dict] = []

    # 先卖后买，确保现金先回流
    ordered_tickers = sorted(state["positions"].keys())
    
    # 1. 卖出
    for ticker in ordered_tickers:
        pos = state["positions"][ticker]
        pp = price_map.get(ticker)
        if not pp or pp.trade_date != trade_date:
            continue
        action, action_shares, action_price, action_amount, reason = maybe_sell(pos, pp.close)
        if action == "SELL":
            old_shares = int(pos["shares"])
            realized = (pp.close - float(pos["avg_cost"])) * old_shares
            pos["shares"] = 0
            pos["realized_pnl"] = float(pos.get("realized_pnl", 0.0)) + realized
            cash += action_amount
            trade_records.append({
                "date": trade_date,
                "ticker": ticker,
                "name": pos["name"],
                "action": action,
                "price": round(action_price, 4),
                "shares": int(action_shares),
                "amount": round(action_amount, 2),
                "cash_after": round(cash, 2),
                "reason": reason,
            })

    # 2. 开仓 / 加仓
    for ticker in ordered_tickers:
        pos = state["positions"][ticker]
        pp = price_map.get(ticker)
        if not pp or pp.trade_date != trade_date:
            continue

        action = "HOLD"
        action_shares = 0
        action_price = 0.0
        action_amount = 0.0

        if int(pos["shares"]) == 0:
            # 尝试开仓
            open_action, open_shares, open_price, open_amount, reason = maybe_open(pos, pp.close, cash)
            if open_action == "BUY_OPEN":
                pos["shares"] = int(open_shares)
                pos["avg_cost"] = float(open_price)
                pos["initial_investment"] = open_amount
                cash -= open_amount
                action = open_action
                action_shares = int(open_shares)
                action_price = float(open_price)
                action_amount = float(open_amount)
                trade_records.append({
                    "date": trade_date,
                    "ticker": ticker,
                    "name": pos["name"],
                    "action": action,
                    "price": round(action_price, 4),
                    "shares": int(action_shares),
                    "amount": round(action_amount, 2),
                    "cash_after": round(cash, 2),
                    "reason": reason,
                })
        else:
            # 尝试加仓
            add_action, add_shares, add_price, add_amount, reason = maybe_add(pos, pp.close, cash)
            if add_action == "BUY_ADD":
                old_shares = int(pos["shares"])
                old_cost = float(pos["avg_cost"])
                new_shares = old_shares + int(add_shares)
                new_avg_cost = (old_shares * old_cost + add_amount) / new_shares
                pos["shares"] = new_shares
                pos["avg_cost"] = new_avg_cost
                pos["added_cost_total"] = float(pos.get("added_cost_total", 0.0)) + add_amount
                cash -= add_amount
                action = add_action
                action_shares = int(add_shares)
                action_price = float(add_price)
                action_amount = float(add_amount)
                trade_records.append({
                    "date": trade_date,
                    "ticker": ticker,
                    "name": pos["name"],
                    "action": action,
                    "price": round(action_price, 4),
                    "shares": int(action_shares),
                    "amount": round(action_amount, 2),
                    "cash_after": round(cash, 2),
                    "reason": reason,
                })

        market_value = int(pos["shares"]) * float(pp.close)
        unrealized = (float(pp.close) - float(pos["avg_cost"])) * int(pos["shares"])

        daily_rows.append({
            "date": trade_date,
            "ticker": ticker,
            "name": pos["name"],
            "code": pos["code"],
            "close": round(pp.close, 4),
            "prev_close": round(pp.prev_close, 4),
            "change_pct": round((pp.close / pp.prev_close - 1) * 100 if pp.prev_close else 0.0, 4),
            "shares": int(pos["shares"]),
            "avg_cost": round(float(pos["avg_cost"]), 6),
            "action": action,
            "action_shares": int(action_shares),
            "action_price": round(action_price, 4),
            "action_amount": round(action_amount, 2),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized, 2),
            "cash_after": round(cash, 2),
            "net_value": 0.0,
            "total_return_pct": 0.0,
        })

    total_market_value = sum(float(r["market_value"]) for r in daily_rows)
    net_value = total_market_value + cash
    total_return_pct = (net_value / INITIAL_CAPITAL - 1) * 100
    for r in daily_rows:
        r["net_value"] = round(net_value, 2)
        r["total_return_pct"] = round(total_return_pct, 4)
        r["cash_after"] = round(cash, 2)

    state["cash"] = round(cash, 2)
    state["last_trade_date"] = trade_date
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    append_trade_records(trade_records)
    append_daily_rows(daily_rows)
    build_dashboard_snapshot(price_map=price_map)

    print(f"[OK] 模拟组合已更新，交易日: {trade_date}")
    print(f"[OK] 报告池标的数量: {len(pool)}")
    print(f"[OK] 持仓数量: {len([p for p in state['positions'].values() if int(p.get('shares', 0)) > 0])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
