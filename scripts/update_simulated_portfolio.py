# -*- coding: utf-8 -*-
"""
模拟投资组合自动决策引擎 V1.0（对应模板 V5.5.12）

功能：
1. 拉取模拟组合标的最新收盘价（yfinance）
2. 按规则执行自动决策（卖出触发 / 回撤加仓）
3. 更新持仓状态、现金余额、组合净值、收益率
4. 生成统一仪表盘快照（public/dashboard/dashboard_snapshot.json）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
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


@dataclass
class PricePoint:
    close: float
    prev_close: float
    trade_date: str


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
        "max_weight": 0.25,
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
        "max_weight": 0.25,
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
        "max_weight": 0.20,
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
        "max_weight": 0.20,
        "position_type": "卫星",
    },
]


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


def ensure_state() -> Dict:
    """初始化状态文件。"""
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
        # 兼容老版本：即使状态文件已存在，也补齐交易/快照基线文件
        seed_baseline_files(state)
        return state

    positions: Dict[str, Dict] = {}
    for row in INITIAL_POSITIONS:
        ticker = normalize_hk_ticker(row["code"], row["ticker"])
        positions[ticker] = {
            **row,
            "ticker": ticker,
            "added_cost_total": 0.0,
            "realized_pnl": 0.0,
        }

    state = {
        "template_version": "V5.5.12",
        "engine_version": "V1.0",
        "initial_capital": INITIAL_CAPITAL,
        "cash": START_CASH,
        "last_trade_date": START_DATE,
        "positions": positions,
    }

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
            records.append(
                {
                    "date": START_DATE,
                    "ticker": p["ticker"],
                    "name": p["name"],
                    "action": "INIT_BUY",
                    "price": base["avg_cost"],
                    "shares": base["shares"],
                    "amount": round(base["shares"] * base["avg_cost"], 2),
                    "cash_after": START_CASH,
                    "reason": "初始建仓",
                }
            )
        pd.DataFrame(records).to_csv(TRADES_FILE, index=False, encoding="utf-8-sig")

    if DAILY_FILE.exists():
        return

    market_value = 0.0
    rows = []
    for tk, p in state["positions"].items():
        base = initial_map.get(tk, p)
        mv = base["shares"] * base["avg_cost"]
        market_value += mv
        rows.append(
            {
                "date": START_DATE,
                "ticker": p["ticker"],
                "name": p["name"],
                "code": p["code"],
                "close": base["avg_cost"],
                "prev_close": base["avg_cost"],
                "change_pct": 0.0,
                "shares": base["shares"],
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
            }
        )
    pd.DataFrame(rows).to_csv(DAILY_FILE, index=False, encoding="utf-8-sig")


def fetch_price_point(ticker: str) -> PricePoint | None:
    """获取最新收盘价和前收盘价。"""
    try:
        hist = yf.Ticker(ticker).history(period="7d", interval="1d", auto_adjust=False)
        if hist is None or hist.empty:
            return None
        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else latest
        trade_date = pd.Timestamp(hist.index[-1]).strftime("%Y-%m-%d")
        return PricePoint(
            close=float(latest["Close"]),
            prev_close=float(prev["Close"]),
            trade_date=trade_date,
        )
    except Exception as exc:  # pragma: no cover
        print(f"[WARN] 获取 {ticker} 行情失败: {exc}")
        return None


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
        realized = (price - float(position["avg_cost"])) * shares
        return ("SELL", shares, price, amount, f"达到卖出触发价 {position['sell_trigger']}")
    return ("HOLD", 0, 0.0, 0.0, "未达到卖出条件")


def maybe_add(position: Dict, price: float, cash: float) -> Tuple[str, int, float, float, str]:
    """
    加仓规则：
    1) 当前价 <= 成本价*95%
    2) 单标总仓位不超过 max_weight
    3) 累计加仓金额不超过初始投入的30%
    4) 必须按每手整数买入
    """
    shares = int(position["shares"])
    if shares <= 0:
        return ("HOLD", 0, 0.0, 0.0, "已清仓，不加仓")

    avg_cost = float(position["avg_cost"])
    if price > avg_cost * 0.95:
        return ("HOLD", 0, 0.0, 0.0, "未达到回撤5%加仓线")

    max_value = INITIAL_CAPITAL * float(position["max_weight"])
    current_value = shares * price
    remain_weight_budget = max(0.0, max_value - current_value)
    remain_add_budget = max(0.0, float(position["initial_investment"]) * 0.30 - float(position["added_cost_total"]))
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
        & (trades_df["action"].isin(["BUY_ADD", "SELL"]))
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
                table_rows.append(
                    {
                        "date": cells[0],
                        "name": cells[1],
                        "code": cells[2],
                        "action": cells[3],
                        "suggest_price": cells[4],
                        "current_price": cells[5],
                        "yield_rate": cells[6],
                        "reason": cells[7],
                        "status": cells[8],
                    }
                )
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
        positions.append(
            {
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
            }
        )

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


def run() -> int:
    state = ensure_state()

    # 拉行情
    price_map: Dict[str, PricePoint] = {}
    for ticker in state["positions"].keys():
        pp = fetch_price_point(ticker)
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
            pos["added_cost_total"] = float(pos.get("added_cost_total", 0.0))
            pos["realized_pnl"] = float(pos.get("realized_pnl", 0.0)) + realized
            cash += action_amount
            trade_records.append(
                {
                    "date": trade_date,
                    "ticker": ticker,
                    "name": pos["name"],
                    "action": action,
                    "price": round(action_price, 4),
                    "shares": int(action_shares),
                    "amount": round(action_amount, 2),
                    "cash_after": round(cash, 2),
                    "reason": reason,
                }
            )

    for ticker in ordered_tickers:
        pos = state["positions"][ticker]
        pp = price_map.get(ticker)
        if not pp or pp.trade_date != trade_date:
            continue

        action = "HOLD"
        action_shares = 0
        action_price = 0.0
        action_amount = 0.0

        if int(pos["shares"]) > 0:
            add_action, add_shares, add_price, add_amount, add_reason = maybe_add(pos, pp.close, cash)
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
                trade_records.append(
                    {
                        "date": trade_date,
                        "ticker": ticker,
                        "name": pos["name"],
                        "action": action,
                        "price": round(action_price, 4),
                        "shares": int(action_shares),
                        "amount": round(action_amount, 2),
                        "cash_after": round(cash, 2),
                        "reason": add_reason,
                    }
                )

        market_value = int(pos["shares"]) * float(pp.close)
        unrealized = (float(pp.close) - float(pos["avg_cost"])) * int(pos["shares"])

        daily_rows.append(
            {
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
            }
        )

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
    print(f"[OK] 组合净值: {net_value:,.2f} HKD，累计收益率: {total_return_pct:+.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
