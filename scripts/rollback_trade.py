# -*- coding: utf-8 -*-
"""
交易回滚工具 V1.0

功能：
1. 删除 trades.csv 中最近 N 笔交易
2. 从 trades.csv 重建 state.json
3. 重新生成 dashboard_snapshot.json
4. 同步 public/dashboard/

使用方式：
    python scripts/rollback_trade.py --last N
    python scripts/rollback_trade.py --to-date YYYY-MM-DD

警告：回滚会修改核心数据文件，执行前会自动备份。
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACK_DIR = ROOT / "decision-tracking"
PUBLIC_DIR = ROOT / "public" / "dashboard"

STATE_FILE = TRACK_DIR / "simulation_state.json"
TRADES_FILE = TRACK_DIR / "simulation_trades.csv"
SNAPSHOT_FILE = TRACK_DIR / "dashboard_snapshot.json"
PUBLIC_SNAPSHOT_FILE = PUBLIC_DIR / "dashboard_snapshot.json"

INITIAL_CAPITAL = 500_000.0


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def backup_before_rollback():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = TRACK_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    for src in [STATE_FILE, TRADES_FILE, SNAPSHOT_FILE]:
        if src.exists():
            dst = backup_dir / f"{src.stem}_rollback_{ts}{src.suffix}"
            shutil.copy2(src, dst)
            log(f"[BACKUP] {src.name} -> {dst.name}")


def load_trades() -> list[dict]:
    if not TRADES_FILE.exists():
        return []
    with open(TRADES_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def save_trades(trades: list[dict]):
    fieldnames = ["date", "ticker", "name", "code", "action", "price", "shares", "amount", "cash_after", "reason"]
    with open(TRADES_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in trades:
            writer.writerow({k: t.get(k, "") for k in fieldnames})


def rebuild_state_from_trades(trades: list[dict]) -> dict:
    """从交易记录重建 state"""
    positions: dict[str, dict] = {}
    cash = INITIAL_CAPITAL
    last_trade_date = ""

    for t in trades:
        ticker = t["ticker"]
        action = t["action"]
        price = float(t["price"])
        shares = int(t["shares"])
        amount = float(t["amount"])
        date = t["date"]
        code = str(t.get("code", ""))
        name = t.get("name", "")

        if date > last_trade_date:
            last_trade_date = date

        # 初始化持仓记录（如果不存在）
        if ticker not in positions:
            positions[ticker] = {
                "name": name,
                "code": code,
                "ticker": ticker,
                "shares": 0,
                "avg_cost": 0.0,
                "sell_trigger": 0,
                "lot_size": 1000 if len(code) == 5 else 100,
                "position_type": "核心",
                "realized_pnl": 0.0,
            }

        pos = positions[ticker]
        old_shares = int(pos["shares"])
        old_cost = float(pos["avg_cost"])

        if action in ("INIT_BUY", "BUY_OPEN", "BUY_ADD"):
            new_shares = old_shares + shares
            if new_shares > 0:
                new_cost = (old_shares * old_cost + amount) / new_shares
            else:
                new_cost = price
            pos["shares"] = new_shares
            pos["avg_cost"] = round(new_cost, 6)
            cash -= amount

        elif action in ("SELL", "SELL_CLOSE", "REDUCE"):
            if old_shares > 0:
                realized = (price - old_cost) * shares
                pos["realized_pnl"] = float(pos.get("realized_pnl", 0)) + realized
            new_shares = max(0, old_shares - shares)
            pos["shares"] = new_shares
            if new_shares == 0:
                pos["avg_cost"] = 0.0
            cash += amount

    return {
        "template_version": "V5.5.22",
        "engine_version": "V3.1",
        "initial_capital": INITIAL_CAPITAL,
        "cash": round(cash, 2),
        "last_trade_date": last_trade_date,
        "positions": positions,
    }


def build_dashboard_from_state(state: dict):
    """从 state 重建简单的 dashboard_snapshot"""
    cash = float(state.get("cash", 0))
    positions = []
    total_mv = 0.0

    for ticker, pos in sorted(state["positions"].items()):
        shares = int(pos.get("shares", 0))
        if shares <= 0:
            continue
        avg_cost = float(pos.get("avg_cost", 0))
        # 回滚时不知道当前价格，用成本价占位
        close = avg_cost
        mv = shares * close
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
            "change_pct": 0.0,
            "market_value": round(mv, 2),
            "unrealized": 0.0,
            "sell_trigger": float(pos.get("sell_trigger", 0) or 0),
            "weight_pct": 0.0,
            "status": "占位",
        })

    net_value = total_mv + cash
    for p in positions:
        p["weight_pct"] = round((p["market_value"] / net_value) * 100, 4) if net_value else 0.0

    snapshot = {
        "meta": {
            "template_version": "V5.5.22",
            "engine_version": "V3.1",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "latest_trade_date": state.get("last_trade_date", ""),
        },
        "portfolio": {
            "initial_capital": INITIAL_CAPITAL,
            "cash": round(cash, 2),
            "market_value": round(total_mv, 2),
            "net_value": round(net_value, 2),
            "total_return_pct": round((net_value / INITIAL_CAPITAL - 1) * 100, 4),
            "position_ratio_pct": round((total_mv / INITIAL_CAPITAL) * 100, 4),
            "positions": positions,
        },
        "today_actions": [],
        "recent_actions": [],
    }

    text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    SNAPSHOT_FILE.write_text(text, encoding="utf-8")
    PUBLIC_SNAPSHOT_FILE.write_text(text, encoding="utf-8")
    log("[DASHBOARD] 已重建并同步")


def rollback_last_n(n: int):
    trades = load_trades()
    if len(trades) < n:
        log(f"[ERROR] 交易记录只有 {len(trades)} 条，无法回滚 {n} 条")
        return 1

    log(f"[ROLLBACK] 准备回滚最近 {n} 笔交易...")
    for t in trades[-n:]:
        log(f"  - {t['date']} {t['ticker']} {t['action']} {t['shares']}股 @ {t['price']}")

    remaining = trades[:-n]
    save_trades(remaining)
    log(f"[OK] 已删除 {n} 笔交易，剩余 {len(remaining)} 笔")

    state = rebuild_state_from_trades(remaining)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[OK] state.json 已重建")
    log(f"  - 现金: {state['cash']:.2f}")
    log(f"  - 持仓: {len([p for p in state['positions'].values() if int(p['shares']) > 0])} 只")

    build_dashboard_from_state(state)
    return 0


def rollback_to_date(target_date: str):
    try:
        target = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        log("[ERROR] 日期格式错误，请使用 YYYY-MM-DD")
        return 1

    trades = load_trades()
    remaining = [t for t in trades if datetime.strptime(t["date"], "%Y-%m-%d").date() <= target]
    removed = len(trades) - len(remaining)

    if removed == 0:
        log(f"[INFO] 无需要回滚的交易（目标日期 {target_date} 之后没有交易）")
        return 0

    log(f"[ROLLBACK] 准备回滚到 {target_date}，将删除 {removed} 笔交易...")
    for t in trades:
        if datetime.strptime(t["date"], "%Y-%m-%d").date() > target:
            log(f"  - {t['date']} {t['ticker']} {t['action']} {t['shares']}股 @ {t['price']}")

    save_trades(remaining)
    log(f"[OK] 已删除 {removed} 笔交易，剩余 {len(remaining)} 笔")

    state = rebuild_state_from_trades(remaining)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[OK] state.json 已重建")
    log(f"  - 现金: {state['cash']:.2f}")
    log(f"  - 持仓: {len([p for p in state['positions'].values() if int(p['shares']) > 0])} 只")

    build_dashboard_from_state(state)
    return 0


def main():
    parser = argparse.ArgumentParser(description="交易回滚工具")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--last", type=int, metavar="N", help="回滚最近 N 笔交易")
    group.add_argument("--to-date", type=str, metavar="YYYY-MM-DD", help="回滚到指定日期（含）")
    args = parser.parse_args()

    log("=" * 60)
    log("[START] 交易回滚工具 V1.0")
    log("=" * 60)

    backup_before_rollback()

    if args.last is not None:
        rc = rollback_last_n(args.last)
    else:
        rc = rollback_to_date(args.to_date)

    log("=" * 60)
    if rc == 0:
        log("[DONE] 回滚完成")
    else:
        log("[FAIL] 回滚失败")
    log("=" * 60)
    sys.exit(rc)


if __name__ == "__main__":
    main()
