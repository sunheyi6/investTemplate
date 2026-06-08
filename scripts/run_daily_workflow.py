# -*- coding: utf-8 -*-
"""
模拟投资组合每日工作流 V4.0 (AI 驱动版)

每日执行流程：
    1. 数据备份
    2. 数据验证
    3. 获取行情（价格 + VHSI）
    4. 规则引擎扫描（硬约束自动执行）
    5. AI 触发检测（需要深度分析的标的）
    6. 调用 AI 决策桥接（如需要）
    7. 执行交易
    8. 更新所有数据文件
    9. 同步 public/
    10. 最终验证

使用方式：
    python scripts/run_daily_workflow.py [--dry-run] [--manual-review]

环境变量：
    AI_PROVIDER, AI_API_KEY, AI_API_BASE, AI_MODEL
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------- 配置 ----------
ROOT = Path(__file__).resolve().parents[1]
TRACK_DIR = ROOT / "decision-tracking"
PUBLIC_DIR = ROOT / "public" / "dashboard"
REPORT_POOL_DIR = ROOT / "analysis-reports"
PROMPT_DIR = ROOT / "prompts"

STATE_FILE = TRACK_DIR / "simulation_state.json"
TRADES_FILE = TRACK_DIR / "simulation_trades.csv"
DAILY_FILE = TRACK_DIR / "simulation_daily_snapshot.csv"
SNAPSHOT_FILE = TRACK_DIR / "dashboard_snapshot.json"
PUBLIC_SNAPSHOT_FILE = PUBLIC_DIR / "dashboard_snapshot.json"
AI_REQUEST_FILE = TRACK_DIR / "ai_decision_request.json"
AI_RESPONSE_FILE = TRACK_DIR / "ai_decision_response.json"
VALIDATION_SCRIPT = ROOT / "scripts" / "validate_simulation_data.py"
AI_BRIDGE_SCRIPT = ROOT / "scripts" / "ai_decision_bridge.py"

INITIAL_CAPITAL = 500_000.0
START_DATE = "2026-03-26"

# 风控参数
MIN_CASH_RESERVE = INITIAL_CAPITAL * 0.10
POSITION_CAP_BEAR = 0.10
POSITION_CAP_BULL = 0.15
VHSI_HALT_NEW_BUY = 32.0
MIN_TRADE_INTERVAL_DAYS = 3

# 数据源（优先 akshare，回退 yfinance）
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


# ---------- 数据类 ----------

@dataclass
class PricePoint:
    close: float
    prev_close: float
    trade_date: str


@dataclass
class TradeAction:
    date: str
    ticker: str
    name: str
    code: str
    action: str  # BUY_OPEN, BUY_ADD, SELL, REDUCE, HOLD
    price: float
    shares: int
    amount: float
    cash_after: float
    reason: str
    source: str = "RULE"  # RULE | AI


# ---------- 工具函数 ----------

def log(msg: str):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg))


def backup_data():
    """每日自动备份"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = TRACK_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    for src in [STATE_FILE, TRADES_FILE, SNAPSHOT_FILE]:
        if src.exists():
            dst = backup_dir / f"{src.stem}_{ts}{src.suffix}"
            shutil.copy2(src, dst)
            log(f"[BACKUP] {src.name} -> {dst.name}")


def run_validation() -> bool:
    if not VALIDATION_SCRIPT.exists():
        log("[WARN] 验证脚本不存在，跳过")
        return True
    try:
        result = subprocess.run([sys.executable, str(VALIDATION_SCRIPT)], capture_output=True, cwd=ROOT)
        stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        if stdout:
            for line in stdout.strip().splitlines():
                if "PASS" in line or "FAIL" in line:
                    log(line)
        if result.returncode != 0:
            return False
        return True
    except Exception as e:
        log(f"[WARN] 验证脚本执行失败: {e}")
        return True


def load_state() -> Dict:
    if not STATE_FILE.exists():
        raise FileNotFoundError(f"state文件不存在: {STATE_FILE}")
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: Dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_trades() -> List[Dict]:
    if not TRADES_FILE.exists():
        return []
    with open(TRADES_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def append_trade_record(record: Dict):
    fieldnames = ["date", "ticker", "name", "code", "action", "price", "shares", "amount", "cash_after", "reason"]
    exists = TRADES_FILE.exists()
    with open(TRADES_FILE, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({k: record.get(k, "") for k in fieldnames})


def append_daily_row(row: Dict):
    fieldnames = [
        "date", "ticker", "name", "code", "close", "prev_close", "change_pct",
        "shares", "avg_cost", "action", "action_shares", "action_price", "action_amount",
        "market_value", "unrealized_pnl", "cash_after", "net_value", "total_return_pct"
    ]
    exists = DAILY_FILE.exists()
    with open(DAILY_FILE, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in fieldnames})


# ---------- 行情获取 ----------

HK_SPOT_CACHE: Optional[Any] = None
AK_HK_FAILED = False


def load_hk_spot():
    global HK_SPOT_CACHE, AK_HK_FAILED
    if AK_HK_FAILED or not AKSHARE_AVAILABLE:
        return None
    if HK_SPOT_CACHE is None:
        try:
            HK_SPOT_CACHE = ak.stock_hk_spot_em()
        except Exception:
            AK_HK_FAILED = True
            return None
    return HK_SPOT_CACHE


def parse_float(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).replace(",", "").replace("%", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_price_from_akshare(code: str) -> Optional[PricePoint]:
    if not AKSHARE_AVAILABLE:
        return None
    try:
        df = load_hk_spot()
        if df is None or df.empty or "代码" not in df.columns:
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
        return PricePoint(close=float(close), prev_close=float(prev_close), trade_date=datetime.now().strftime("%Y-%m-%d"))
    except Exception:
        return None


def fetch_price_from_yf(ticker: str) -> Optional[PricePoint]:
    if not YFINANCE_AVAILABLE:
        return None
    try:
        hist = yf.Ticker(ticker).history(period="7d", interval="1d", auto_adjust=False)
        if hist is None or hist.empty:
            return None
        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else latest
        trade_date = str(hist.index[-1])[:10]
        return PricePoint(close=float(latest["Close"]), prev_close=float(prev["Close"]), trade_date=trade_date)
    except Exception:
        return None


def fetch_price(ticker: str, code: str) -> Optional[PricePoint]:
    if len(code) == 5:
        pp = fetch_price_from_akshare(code)
        if pp:
            return pp
    if YFINANCE_AVAILABLE:
        return fetch_price_from_yf(ticker)
    return None


def fetch_vhsi() -> float:
    """获取 VHSI，优先从本地文件/缓存获取，否则返回 25（中性值）"""
    vhsi_file = ROOT / "decision-tracking" / "vix_dca_strategy" / "vhsi_latest.json"
    if vhsi_file.exists():
        try:
            data = json.loads(vhsi_file.read_text(encoding="utf-8"))
            return float(data.get("vhsi", 25.0))
        except Exception:
            pass
    # 尝试通过脚本获取
    vhsi_script = ROOT / "scripts" / "fetch_vhsi.py"
    if vhsi_script.exists():
        try:
            result = subprocess.run([sys.executable, str(vhsi_script)], capture_output=True, cwd=ROOT)
            if result.returncode == 0:
                data = json.loads(result.stdout.decode("utf-8"))
                return float(data.get("vhsi", 25.0))
        except Exception:
            pass
    log("[WARN] 无法获取 VHSI，使用默认值 25.0")
    return 25.0


# ---------- 规则引擎 ----------

def rule_sell(position: Dict, price: float) -> Optional[TradeAction]:
    """卖出规则：达到卖出触发价"""
    shares = int(position.get("shares", 0))
    if shares <= 0:
        return None
    sell_trigger = position.get("sell_trigger")
    if not sell_trigger or float(sell_trigger) <= 0:
        return None
    if price >= float(sell_trigger):
        return TradeAction(
            date=datetime.now().strftime("%Y-%m-%d"),
            ticker=position.get("ticker", ""),
            name=position.get("name", ""),
            code=str(position.get("code", "")).zfill(5) if len(str(position.get("code", ""))) == 5 else position.get("code", ""),
            action="SELL",
            price=price,
            shares=shares,
            amount=shares * price,
            cash_after=0.0,  # 稍后计算
            reason=f"达到卖出触发价 {sell_trigger}",
            source="RULE",
        )
    return None


def rule_add_on_drawdown(position: Dict, price: float, cash: float) -> Optional[TradeAction]:
    """加仓规则：回撤 5%"""
    shares = int(position.get("shares", 0))
    if shares <= 0:
        return None
    avg_cost = float(position.get("avg_cost", 0))
    if avg_cost <= 0:
        return None
    if price > avg_cost * 0.95:
        return None

    max_value = INITIAL_CAPITAL * POSITION_CAP_BEAR
    current_value = shares * price
    remain_budget = max(0.0, max_value - current_value)
    budget = min(remain_budget, cash)

    lot_size = int(position.get("lot_size", 1000))
    lot_cost = lot_size * price
    if lot_cost <= 0:
        return None

    buy_lots = int(budget // lot_cost)
    buy_shares = buy_lots * lot_size
    if buy_shares <= 0:
        return None

    return TradeAction(
        date=datetime.now().strftime("%Y-%m-%d"),
        ticker=position.get("ticker", ""),
        name=position.get("name", ""),
        code=str(position.get("code", "")).zfill(5) if len(str(position.get("code", ""))) == 5 else position.get("code", ""),
        action="BUY_ADD",
        price=price,
        shares=buy_shares,
        amount=buy_shares * price,
        cash_after=0.0,
        reason="触发回撤5%加仓",
        source="RULE",
    )


def check_recent_trade(ticker: str, days: int = MIN_TRADE_INTERVAL_DAYS) -> bool:
    """检查该标的最近 N 天内是否有交易"""
    trades = load_trades()
    if not trades:
        return False
    today = datetime.now().date()
    for t in reversed(trades):
        if t.get("ticker") == ticker:
            try:
                trade_date = datetime.strptime(t["date"], "%Y-%m-%d").date()
                if (today - trade_date).days < days:
                    return True
            except Exception:
                continue
    return False


# ---------- AI 触发检测 ----------

def build_portfolio_context(state: Dict, price_map: Dict[str, PricePoint]) -> Dict:
    """构建组合上下文，用于 AI 分析"""
    positions = state.get("positions", {})
    cash = float(state.get("cash", 0))
    portfolio_positions = {}
    total_mv = 0.0

    for ticker, pos in positions.items():
        shares = int(pos.get("shares", 0))
        pp = price_map.get(ticker)
        close = pp.close if pp else float(pos.get("avg_cost", 0))
        mv = shares * close
        total_mv += mv
        portfolio_positions[ticker] = {
            "name": pos.get("name", ""),
            "code": pos.get("code", ""),
            "shares": shares,
            "avg_cost": float(pos.get("avg_cost", 0)),
            "sell_trigger": pos.get("sell_trigger", 0),
            "target_buy": pos.get("target_buy"),
            "lot_size": int(pos.get("lot_size", 1000)),
            "realized_pnl": float(pos.get("realized_pnl", 0)),
        }

    net_value = total_mv + cash
    return {
        "initial_capital": INITIAL_CAPITAL,
        "cash": cash,
        "net_value": net_value,
        "total_return_pct": round((net_value / INITIAL_CAPITAL - 1) * 100, 4),
        "positions": portfolio_positions,
    }


def generate_ai_request(
    trigger_type: str,
    ticker: str,
    position: Dict,
    price: float,
    trigger_reason: str,
    portfolio_context: Dict,
    vhsi: float,
) -> Dict:
    """生成 AI 决策请求"""
    sentiment = "平静/乐观"
    if vhsi > 40:
        sentiment = "极端恐慌"
    elif vhsi > 32:
        sentiment = "高度恐慌"
    elif vhsi > 27:
        sentiment = "明显恐慌"
    elif vhsi > 22:
        sentiment = "谨慎担忧"

    return {
        "trigger_type": trigger_type,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "subject": {
            "ticker": ticker,
            "name": position.get("name", ""),
            "code": position.get("code", ""),
            "current_price": price,
            "trigger_reason": trigger_reason,
        },
        "context": {
            "portfolio_state": portfolio_context,
            "vhsi": vhsi,
            "market_sentiment": sentiment,
        },
        "analysis_required": ["framework_selection", "valuation", "risk_assessment"],
    }


def run_ai_decision(request: Dict) -> Optional[Dict]:
    """调用 AI 决策桥接脚本"""
    AI_REQUEST_FILE.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    log("[AI] 生成请求: %s" % AI_REQUEST_FILE)

    if not AI_BRIDGE_SCRIPT.exists():
        log("[ERROR] AI 桥接脚本不存在: %s" % AI_BRIDGE_SCRIPT)
        return None

    try:
        result = subprocess.run(
            [sys.executable, str(AI_BRIDGE_SCRIPT)],
            capture_output=True,
            cwd=ROOT,
            timeout=300,
        )
        stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        for line in stdout.splitlines():
            if line.strip():
                log(f"[AI-OUT] {line}")
        if result.returncode != 0:
            log("[ERROR] AI 桥接脚本执行失败")
            if stderr:
                log(f"[AI-ERR] {stderr[:500]}")
            return None
    except subprocess.TimeoutExpired:
        log("[ERROR] AI 桥接脚本超时")
        return None
    except Exception as e:
        log(f"[ERROR] AI 桥接脚本异常: {e}")
        return None

    if not AI_RESPONSE_FILE.exists():
        log("[ERROR] AI 响应文件未生成")
        return None

    try:
        response = json.loads(AI_RESPONSE_FILE.read_text(encoding="utf-8"))
        log("[AI] 决策: %s -> %s" % (request["subject"]["ticker"], response.get("decision", "UNKNOWN")))
        return response
    except Exception as e:
        log(f"[ERROR] 解析 AI 响应失败: {e}")
        return None


# ---------- 交易执行 ----------

def execute_trade(state: Dict, action: TradeAction, dry_run: bool = False) -> float:
    """执行交易，返回更新后的现金"""
    cash = float(state.get("cash", 0))
    positions = state.get("positions", {})
    pos = positions.get(action.ticker, {})

    if action.action == "SELL":
        realized = (action.price - float(pos.get("avg_cost", 0))) * action.shares
        pos["realized_pnl"] = float(pos.get("realized_pnl", 0)) + realized
        pos["shares"] = 0
        pos["avg_cost"] = 0.0
        cash += action.amount
        log(f"[TRADE] 卖出: {action.name} {action.shares}股 @ {action.price:.3f} -> 现金+{action.amount:.2f}")

    elif action.action in ("BUY_OPEN", "BUY_ADD"):
        old_shares = int(pos.get("shares", 0))
        old_cost = float(pos.get("avg_cost", 0))
        new_shares = old_shares + action.shares
        if new_shares > 0:
            new_cost = (old_shares * old_cost + action.amount) / new_shares
        else:
            new_cost = action.price
        pos["shares"] = new_shares
        pos["avg_cost"] = round(new_cost, 6)
        cash -= action.amount
        log(f"[TRADE] 买入: {action.name} {action.shares}股 @ {action.price:.3f} -> 现金-{action.amount:.2f}")

    state["cash"] = round(cash, 2)
    action.cash_after = round(cash, 2)

    if not dry_run:
        append_trade_record({
            "date": action.date,
            "ticker": action.ticker,
            "name": action.name,
            "code": action.code,
            "action": action.action,
            "price": round(action.price, 4),
            "shares": action.shares,
            "amount": round(action.amount, 2),
            "cash_after": round(action.cash_after, 2),
            "reason": action.reason,
        })

    return cash


# ---------- Dashboard 生成 ----------

def build_dashboard(state: Dict, price_map: Dict[str, PricePoint], today_actions: List[TradeAction]):
    cash = float(state.get("cash", 0))
    positions = []
    total_mv = 0.0

    for ticker, pos in sorted(state["positions"].items()):
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
            "weight_pct": 0.0,
            "status": "实时" if pp else "占位",
        })

    net_value = total_mv + cash
    total_return = (net_value / INITIAL_CAPITAL - 1) * 100

    for p in positions:
        p["weight_pct"] = round((p["market_value"] / net_value) * 100, 4) if net_value else 0.0

    # 构建 recent_actions
    trades = load_trades()
    recent_actions = []
    for t in trades[-20:]:
        recent_actions.append({
            "date": t.get("date", ""),
            "ticker": t.get("ticker", ""),
            "name": t.get("name", ""),
            "action": t.get("action", ""),
            "price": float(t.get("price", 0)),
            "shares": int(t.get("shares", 0)),
            "amount": float(t.get("amount", 0)),
            "reason": t.get("reason", ""),
        })

    today_action_records = []
    for a in today_actions:
        today_action_records.append({
            "ticker": a.ticker,
            "name": a.name,
            "action": a.action,
            "price": a.price,
            "shares": a.shares,
            "amount": a.amount,
            "reason": a.reason,
            "source": a.source,
        })

    snapshot = {
        "meta": {
            "template_version": "V5.5.22",
            "engine_version": "V4.0",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "latest_trade_date": datetime.now().strftime("%Y-%m-%d"),
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
        "today_actions": today_action_records,
        "recent_actions": recent_actions,
        "ai_summary": {
            "ai_decisions_today": sum(1 for a in today_actions if a.source == "AI"),
            "rule_decisions_today": sum(1 for a in today_actions if a.source == "RULE"),
        },
    }

    text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    SNAPSHOT_FILE.write_text(text, encoding="utf-8")
    PUBLIC_SNAPSHOT_FILE.write_text(text, encoding="utf-8")
    log("[DASHBOARD] 已生成并同步")
    return snapshot


# ---------- 主流程 ----------

def run_daily_workflow(dry_run: bool = False, manual_review: bool = False) -> int:
    log("=" * 60)
    log("[START] 模拟投资组合每日工作流 V4.0")
    if dry_run:
        log("[MODE] --dry-run: 只分析，不执行交易")
    log("=" * 60)

    # 1. 备份
    log("[STEP 1] 数据备份...")
    backup_data()

    # 2. 验证
    log("[STEP 2] 数据验证...")
    if not run_validation():
        log("[ERROR] 数据验证失败，停止运行")
        return 1

    # 3. 加载 state
    log("[STEP 3] 加载持仓状态...")
    state = load_state()
    cash = float(state.get("cash", 0))
    active_positions = [p for p in state["positions"].values() if int(p.get("shares", 0)) > 0]
    log(f"[OK] 现金: {cash:.2f}, 持仓: {len(active_positions)} 只, 观察: {len(state['positions']) - len(active_positions)} 只")

    # 4. 获取行情
    log("[STEP 4] 获取行情...")
    price_map = {}
    for ticker, pos in state["positions"].items():
        code = str(pos.get("code", ""))
        pp = fetch_price(ticker, code)
        if pp:
            price_map[ticker] = pp
            log(f"[OK] {ticker}: {pp.close:.3f} ({pp.trade_date})")

    if not price_map:
        log("[WARN] 未获取到任何行情，今日仅刷新展示")
        build_dashboard(state, {}, [])
        return 0

    trade_date = max(pp.trade_date for pp in price_map.values())
    last_date = str(state.get("last_trade_date", ""))

    if trade_date <= last_date:
        log(f"[INFO] 日期未更新 ({trade_date})，仅刷新展示")
        build_dashboard(state, price_map, [])
        return 0

    # 5. 获取 VHSI
    log("[STEP 5] 获取 VHSI...")
    vhsi = fetch_vhsi()
    log(f"[OK] VHSI: {vhsi:.2f}")

    # 6. 规则引擎 + AI 触发扫描
    log("[STEP 6] 执行规则扫描与 AI 触发检测...")
    portfolio_context = build_portfolio_context(state, price_map)
    today_actions: List[TradeAction] = []
    ai_requests: List[Dict] = []

    for ticker, pos in state["positions"].items():
        pp = price_map.get(ticker)
        if not pp or pp.trade_date != trade_date:
            continue

        price = pp.close
        shares = int(pos.get("shares", 0))

        # 规则A: 卖出
        sell_action = rule_sell(pos, price)
        if sell_action:
            today_actions.append(sell_action)
            continue

        # 规则B: 回撤加仓
        if shares > 0:
            add_action = rule_add_on_drawdown(pos, price, cash)
            if add_action:
                # 检查最小交易间隔
                if check_recent_trade(ticker):
                    log(f"[SKIP] {ticker} 最近{MIN_TRADE_INTERVAL_DAYS}天内已有交易，跳过规则加仓")
                else:
                    today_actions.append(add_action)
                    continue

        # 规则C: 空仓观察标的触及买点 → 触发 AI 分析
        if shares == 0:
            target_buy = pos.get("target_buy")
            if target_buy and price <= float(target_buy):
                if check_recent_trade(ticker):
                    log(f"[SKIP] {ticker} 最近{MIN_TRADE_INTERVAL_DAYS}天内已有交易，跳过 AI 触发")
                else:
                    log(f"[AI-TRIGGER] {ticker} 价格 {price:.3f} 触及买点 {target_buy}，触发 AI 分析")
                    req = generate_ai_request(
                        trigger_type="NEW_BUY_SIGNAL",
                        ticker=ticker,
                        position=pos,
                        price=price,
                        trigger_reason=f"价格 {price:.3f} 触及买点 {target_buy}",
                        portfolio_context=portfolio_context,
                        vhsi=vhsi,
                    )
                    ai_requests.append(req)

    # 7. 执行 AI 决策（如需要）
    if ai_requests and not manual_review:
        log("[STEP 7] 执行 AI 深度决策...")
        for req in ai_requests:
            if dry_run:
                log(f"[DRY-RUN] AI 请求: {req['subject']['ticker']} - {req['subject']['trigger_reason']}")
                continue

            response = run_ai_decision(req)
            if response:
                decision = response.get("decision", "HOLD")
                action_shares = int(response.get("shares", 0))
                action_price = float(response.get("price", req["subject"]["current_price"]))

                if decision in ("BUY_OPEN", "BUY_ADD") and action_shares > 0:
                    today_actions.append(TradeAction(
                        date=trade_date,
                        ticker=req["subject"]["ticker"],
                        name=req["subject"]["name"],
                        code=req["subject"]["code"],
                        action=decision,
                        price=action_price,
                        shares=action_shares,
                        amount=action_shares * action_price,
                        cash_after=0.0,
                        reason=response.get("reason", "AI 决策"),
                        source="AI",
                    ))
                elif decision == "SELL":
                    pos = state["positions"].get(req["subject"]["ticker"], {})
                    existing_shares = int(pos.get("shares", 0))
                    if existing_shares > 0:
                        today_actions.append(TradeAction(
                            date=trade_date,
                            ticker=req["subject"]["ticker"],
                            name=req["subject"]["name"],
                            code=req["subject"]["code"],
                            action="SELL",
                            price=action_price,
                            shares=existing_shares,
                            amount=existing_shares * action_price,
                            cash_after=0.0,
                            reason=response.get("reason", "AI 决策卖出"),
                            source="AI",
                        ))
    elif ai_requests and manual_review:
        log("[STEP 7] AI 请求已生成（manual-review 模式，等待人工确认）")
        for req in ai_requests:
            log(f"[MANUAL] {req['subject']['ticker']}: {req['subject']['trigger_reason']}")
        log(f"[MANUAL] 请查看 {AI_REQUEST_FILE}，确认后手动运行 AI 桥接脚本")
    else:
        log("[STEP 7] 无 AI 触发条件")

    # 8. 执行交易
    log("[STEP 8] 执行交易...")
    if not today_actions:
        log("[INFO] 今日无交易")
    else:
        if dry_run:
            log("[DRY-RUN] 以下交易将被执行：")
            for a in today_actions:
                log(f"  {a.action}: {a.name} {a.shares}股 @ {a.price:.3f} ({a.source})")
        else:
            for action in today_actions:
                cash = execute_trade(state, action, dry_run=False)

    # 9. 更新 state
    if not dry_run:
        state["last_trade_date"] = trade_date
        save_state(state)
        log("[OK] state 已更新")

    # 10. 追加每日快照
    if not dry_run:
        total_mv = 0.0
        for ticker, pos in state["positions"].items():
            shares = int(pos.get("shares", 0))
            pp = price_map.get(ticker)
            close = pp.close if pp else float(pos.get("avg_cost", 0))
            mv = shares * close
            total_mv += mv
            avg_cost = float(pos.get("avg_cost", 0))
            unrealized = (close - avg_cost) * shares if shares > 0 else 0

            action_str = "HOLD"
            action_shares = 0
            action_price = 0.0
            action_amount = 0.0
            for a in today_actions:
                if a.ticker == ticker:
                    action_str = a.action
                    action_shares = a.shares
                    action_price = a.price
                    action_amount = a.amount
                    break

            prev_close = pp.prev_close if pp else close
            change_pct = round((close / prev_close - 1) * 100, 4) if prev_close else 0.0

            append_daily_row({
                "date": trade_date,
                "ticker": ticker,
                "name": pos.get("name", ""),
                "code": pos.get("code", ""),
                "close": round(close, 4),
                "prev_close": round(prev_close, 4),
                "change_pct": change_pct,
                "shares": shares,
                "avg_cost": round(avg_cost, 6),
                "action": action_str,
                "action_shares": action_shares,
                "action_price": round(action_price, 4),
                "action_amount": round(action_amount, 2),
                "market_value": round(mv, 2),
                "unrealized_pnl": round(unrealized, 2),
                "cash_after": round(cash, 2),
                "net_value": round(total_mv + cash, 2),
                "total_return_pct": round(((total_mv + cash) / INITIAL_CAPITAL - 1) * 100, 4),
            })

    # 11. 生成 Dashboard
    log("[STEP 9] 生成 Dashboard...")
    snapshot = build_dashboard(state, price_map, today_actions)

    # 12. 最终验证
    if not dry_run:
        log("[STEP 10] 最终验证...")
        if not run_validation():
            log("[WARN] 最终验证发现不一致，请检查")
        else:
            log("[OK] 最终验证通过")

    # 输出汇总
    log("")
    log("=" * 60)
    log("[DONE] 每日工作流完成")
    log("=" * 60)
    log(f"交易日: {trade_date}")
    log(f"净值: {snapshot['portfolio']['net_value']:.2f} HKD")
    log(f"收益率: {snapshot['portfolio']['total_return_pct']:.2f}%")
    log(f"今日操作: {len(today_actions)} 笔")
    log(f"  - 规则引擎: {sum(1 for a in today_actions if a.source == 'RULE')} 笔")
    log(f"  - AI 决策: {sum(1 for a in today_actions if a.source == 'AI')} 笔")
    log(f"现金储备: {snapshot['portfolio']['cash']:.2f} ({snapshot['portfolio']['cash']/INITIAL_CAPITAL*100:.1f}%)")

    return 0


def apply_ai_response() -> int:
    """读取 ai_decision_response.json 并执行交易（供 Kimi Code CLI 等外部工具调用后使用）"""
    log("=" * 60)
    log("[START] 应用 AI 决策响应")
    log("=" * 60)

    if not AI_RESPONSE_FILE.exists():
        log("[ERROR] AI 响应文件不存在: %s" % AI_RESPONSE_FILE)
        return 1

    state = load_state()
    cash = float(state.get("cash", 0))
    today_actions: List[TradeAction] = []

    try:
        response = json.loads(AI_RESPONSE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log("[ERROR] 解析 AI 响应失败: %s" % e)
        return 1

    decision = response.get("decision", "HOLD")
    ticker = response.get("ticker", "")
    action_shares = int(response.get("shares", 0))
    action_price = float(response.get("price", 0))

    if decision not in ("BUY_OPEN", "BUY_ADD", "SELL", "REDUCE"):
        log("[INFO] AI 决策为 %s，无需执行交易" % decision)
        return 0

    pos = state["positions"].get(ticker, {})
    if not pos:
        log("[ERROR] 标的 %s 不在持仓列表中" % ticker)
        return 1

    existing_shares = int(pos.get("shares", 0))

    if decision in ("BUY_OPEN", "BUY_ADD") and action_shares > 0:
        action = TradeAction(
            date=response.get("date", datetime.now().strftime("%Y-%m-%d")),
            ticker=ticker,
            name=pos.get("name", ""),
            code=str(pos.get("code", "")).zfill(5) if len(str(pos.get("code", ""))) == 5 else pos.get("code", ""),
            action=decision,
            price=action_price,
            shares=action_shares,
            amount=action_shares * action_price,
            cash_after=0.0,
            reason=response.get("reason", "AI 决策"),
            source="AI",
        )
        today_actions.append(action)

    elif decision in ("SELL", "REDUCE") and existing_shares > 0:
        sell_shares = action_shares if action_shares > 0 else existing_shares
        action = TradeAction(
            date=response.get("date", datetime.now().strftime("%Y-%m-%d")),
            ticker=ticker,
            name=pos.get("name", ""),
            code=str(pos.get("code", "")).zfill(5) if len(str(pos.get("code", ""))) == 5 else pos.get("code", ""),
            action="SELL" if sell_shares >= existing_shares else "REDUCE",
            price=action_price,
            shares=sell_shares,
            amount=sell_shares * action_price,
            cash_after=0.0,
            reason=response.get("reason", "AI 决策卖出"),
            source="AI",
        )
        today_actions.append(action)

    # 执行交易
    for action in today_actions:
        cash = execute_trade(state, action, dry_run=False)

    # 更新 state
    state["last_trade_date"] = datetime.now().strftime("%Y-%m-%d")
    save_state(state)

    # 获取最新价格用于 Dashboard（尝试从 state 中恢复，或用成本价占位）
    price_map = {}
    for t, p in state["positions"].items():
        if int(p.get("shares", 0)) > 0:
            price_map[t] = PricePoint(
                close=float(p.get("avg_cost", 0)),
                prev_close=float(p.get("avg_cost", 0)),
                trade_date=datetime.now().strftime("%Y-%m-%d"),
            )

    # 生成 Dashboard
    snapshot = build_dashboard(state, price_map, today_actions)

    # 最终验证
    run_validation()

    log("")
    log("=" * 60)
    log("[DONE] AI 决策已应用")
    log("=" * 60)
    return 0


def main():
    parser = argparse.ArgumentParser(description="模拟投资组合每日工作流")
    parser.add_argument("--dry-run", action="store_true", help="只分析，不执行交易")
    parser.add_argument("--manual-review", action="store_true", help="AI 决策等外部工具确认（生成请求后退出）")
    parser.add_argument("--apply-ai-response", action="store_true", help="读取 ai_decision_response.json 并执行交易")
    args = parser.parse_args()

    if args.apply_ai_response:
        sys.exit(apply_ai_response())
    else:
        sys.exit(run_daily_workflow(dry_run=args.dry_run, manual_review=args.manual_review))


if __name__ == "__main__":
    main()
