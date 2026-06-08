# -*- coding: utf-8 -*-
"""
VIX定投策略数据一致性校验脚本 V1.0
运行方式: python scripts/validate_vix_dca.py

校验项：
1. state.json / dashboard_data.json 关键字段一致性
2. daily_returns.csv 收益率计算正确性
3. daily_snapshot.csv 数据完整性
4. returns_curve.html rawData 与数据源一致性
5. decision-tracking/ 与 08-决策追踪/ 目录同步
6. 收益率口径一致性（防止基于不同 principal 的跳变）
"""

import json
import csv
import re
import sys
import io
from pathlib import Path

# Windows 终端编码兼容
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "decision-tracking" / "vix_dca_strategy"
PUBLIC_DIR = ROOT / "public" / "vix_strategy"
ALT_DIR = ROOT / "08-决策追踪" / "vix_dca_strategy"

ERRORS = []
WARNINGS = []


def error(msg):
    ERRORS.append(msg)
    print(f"  ❌ [错误] {msg}")


def warn(msg):
    WARNINGS.append(msg)
    print(f"  ⚠️  [警告] {msg}")


def ok(msg):
    print(f"  ✅ {msg}")


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_csv_rows(path):
    with open(path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        return list(reader)


def check_state_dashboard_consistency():
    """校验1: state.json 与 dashboard_data.json / public/dashboard_data.json 一致性"""
    print("\n【校验1】state.json ↔ dashboard_data.json 一致性")

    state = load_json(STRATEGY_DIR / "state.json")
    db = load_json(STRATEGY_DIR / "dashboard_data.json")
    pub_db = load_json(PUBLIC_DIR / "dashboard_data.json")

    pos = state.get('position', {})
    perf = state.get('daily_performance', {})

    checks = [
        ("持仓份额", pos.get('shares'), db['position'].get('shares')),
        ("平均成本", round(pos.get('avg_cost', 0), 3), db['position'].get('avg_cost')),
        ("最新价格", pos.get('current_price'), db['position'].get('current_price')),
        ("持仓市值", round(pos.get('market_value', 0), 2), db['position'].get('market_value')),
        ("总成本", round(pos.get('total_cost', 0), 2), db['position'].get('total_cost')),
        ("浮动盈亏", round(pos.get('unrealized_pnl', 0), 2), db['position'].get('unrealized_pnl')),
        ("持仓收益率", pos.get('return_pct'), db['position'].get('return_pct')),
        ("总收益额", round(perf.get('total_pnl', 0), 2), db['performance'].get('total_pnl')),
        ("总收益率", perf.get('total_return_pct'), db['performance'].get('total_return_pct')),
    ]

    for name, s_val, d_val in checks:
        if s_val != d_val:
            error(f"state.json 与 dashboard_data.json 不一致: {name} (state={s_val}, db={d_val})")

    # public 同步检查
    pub_checks = [
        ("持仓份额", db['position'].get('shares'), pub_db['position'].get('shares')),
        ("最新价格", db['position'].get('current_price'), pub_db['position'].get('current_price')),
        ("总收益率", db['performance'].get('total_return_pct'), pub_db['performance'].get('total_return_pct')),
    ]
    for name, d_val, p_val in pub_checks:
        if d_val != p_val:
            error(f"dashboard_data.json 未同步到 public/: {name} (db={d_val}, public={p_val})")

    if not ERRORS:
        ok("state.json ↔ dashboard_data.json ↔ public/ 数据一致")


def check_daily_returns():
    """校验2: daily_returns.csv 收益率计算正确性 + 口径一致性"""
    print("\n【校验2】daily_returns.csv 收益率计算与口径一致性")

    rows = load_csv_rows(STRATEGY_DIR / "daily_returns.csv")
    if not rows:
        error("daily_returns.csv 为空")
        return

    # 重建 cumulative_buy 历史
    state = load_json(STRATEGY_DIR / "state.json")
    trades = []
    alt_trades = load_csv_rows(ALT_DIR / "trades.csv") if (ALT_DIR / "trades.csv").exists() else []

    # 从 dashboard 读取交易记录
    db = load_json(STRATEGY_DIR / "dashboard_data.json")
    for t in db.get('recent_trades', []):
        if t.get('action') == 'BUY':
            trades.append(t)

    cumulative_buy = 0.0
    cum_history = {}
    for row in rows:
        date = row['date']
        # 检查是否有当日买入
        buy_amount = sum(t['amount'] for t in trades if t['date'] == date)
        if buy_amount == 0 and alt_trades:
            buy_amount = sum(float(t['amount']) for t in alt_trades if t['date'] == date)
        cumulative_buy += buy_amount
        cum_history[date] = cumulative_buy

    prev_return_pct = None
    for i, row in enumerate(rows):
        date = row['date']
        mv = float(row['market_value'])
        tc = float(row['total_cost'])
        unreal = float(row['unrealized_pnl'])
        daily_pnl = float(row['daily_pnl'])
        return_pct = float(row['return_pct'])
        total_return_pct = float(row['total_return_pct'])
        net_value = float(row['net_value'])

        # 校验 unrealized = mv - total_cost
        expected_unreal = round(mv - tc, 2)
        if abs(unreal - expected_unreal) > 0.1:
            error(f"{date} unrealized_pnl 计算错误: 记录={unreal}, 预期={expected_unreal}")

        # 校验 return_pct = unrealized / total_cost * 100
        if tc > 0:
            expected_return_pct = round(unreal / tc * 100, 2)
            if abs(return_pct - expected_return_pct) > 0.1:
                error(f"{date} return_pct 计算错误: 记录={return_pct}, 预期={expected_return_pct}")

        # 校验 net_value = market_value（当前口径）
        if abs(net_value - mv) > 0.1:
            error(f"{date} net_value 应等于 market_value: net_value={net_value}, mv={mv}")

        # 校验 total_return_pct 口径一致性：应基于 cumulative_buy
        cb = cum_history.get(date, 0)
        if cb > 0:
            expected_total = round((mv - cb) / cb * 100, 2)
            if abs(total_return_pct - expected_total) > 0.15:
                error(f"{date} total_return_pct 口径异常: 记录={total_return_pct}, "
                      f"预期(基于累计投入{cb})={expected_total}。可能使用了错误的 principal!")

        # 校验 daily_pnl 连续性（非首日）
        if i > 0:
            prev_unreal = float(rows[i-1]['unrealized_pnl'])
            expected_daily = round(unreal - prev_unreal, 2)
            if abs(daily_pnl - expected_daily) > 0.1:
                error(f"{date} daily_pnl 不连续: 记录={daily_pnl}, 预期={expected_daily}")

        prev_return_pct = total_return_pct

    if not any(e for e in ERRORS if 'daily_returns.csv' in e or '口径异常' in e):
        ok("daily_returns.csv 收益率计算正确且口径统一")


def check_daily_snapshot():
    """校验3: daily_snapshot.csv 数据完整性"""
    print("\n【校验3】daily_snapshot.csv 数据完整性")

    snapshot_path = STRATEGY_DIR / "daily_snapshot.csv"
    if not snapshot_path.exists():
        error(f"缺少必需文件: {snapshot_path.relative_to(ROOT)}")
        return

    snap_rows = load_csv_rows(snapshot_path)
    ret_rows = load_csv_rows(STRATEGY_DIR / "daily_returns.csv")

    if len(snap_rows) < len(ret_rows):
        warn(f"daily_snapshot.csv 记录数({len(snap_rows)})少于 daily_returns.csv({len(ret_rows)})")

    snap_dates = {r['date'] for r in snap_rows}
    ret_dates = {r['date'] for r in ret_rows}

    missing = ret_dates - snap_dates
    if missing:
        error(f"daily_snapshot.csv 缺少日期: {sorted(missing)}")

    # 检查字段一致性
    for srow in snap_rows:
        date = srow['date']
        ret_row = next((r for r in ret_rows if r['date'] == date), None)
        if not ret_row:
            continue
        checks = [
            ("shares", srow.get('shares'), ret_row.get('shares')),
            ("price", srow.get('price'), ret_row.get('price')),
            ("unrealized_pnl", srow.get('unrealized_pnl'), ret_row.get('unrealized_pnl')),
        ]
        for name, s_val, r_val in checks:
            if s_val != r_val:
                error(f"{date} daily_snapshot 与 daily_returns 不一致: {name} (snap={s_val}, ret={r_val})")

    if not any('daily_snapshot.csv' in e for e in ERRORS):
        ok("daily_snapshot.csv 数据完整且一致")


def check_returns_curve():
    """校验4: returns_curve.html rawData 与数据源一致性"""
    print("\n【校验4】returns_curve.html rawData 一致性")

    html_path = PUBLIC_DIR / "returns_curve.html"
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()

    # 提取 rawData
    m = re.search(r'var rawData = (\[.*?\]);', html, re.DOTALL)
    if not m:
        error("returns_curve.html 中未找到 rawData")
        return

    try:
        raw_data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        error(f"returns_curve.html rawData JSON 解析失败: {e}")
        return

    ret_rows = load_csv_rows(STRATEGY_DIR / "daily_returns.csv")
    ret_map = {r['date']: r for r in ret_rows}

    for item in raw_data:
        date = item['date']
        if date not in ret_map:
            warn(f"returns_curve.html 包含数据源中不存在的日期: {date}")
            continue
        ret = ret_map[date]

        # 检查关键字段
        checks = [
            ("price", item.get('price'), float(ret['price'])),
            ("market_value", item.get('market_value'), float(ret['market_value'])),
            ("unrealized_pnl", item.get('unrealized_pnl'), float(ret['unrealized_pnl'])),
            ("total_return_pct", item.get('total_return_pct'), float(ret['total_return_pct'])),
        ]
        for name, h_val, r_val in checks:
            if h_val is not None and r_val is not None and abs(h_val - r_val) > 0.05:
                error(f"returns_curve.html {date} {name} 不一致: html={h_val}, csv={r_val}")

    # 检查收益率跳变（相邻日期差异不应超过合理范围）
    for i in range(1, len(raw_data)):
        prev = raw_data[i-1]
        curr = raw_data[i]
        diff = abs(curr['total_return_pct'] - prev['total_return_pct'])
        # 正常单日跳变不应超过 5%（除特殊交易日外）
        if diff > 8:
            warn(f"returns_curve.html 收益率跳变过大: {prev['date']}({prev['total_return_pct']}%) → "
                 f"{curr['date']}({curr['total_return_pct']}%), 差异={diff:.2f}%")

    if not any('returns_curve.html' in e for e in ERRORS):
        ok("returns_curve.html rawData 与数据源一致")


def check_alt_dir_sync():
    """校验5: decision-tracking/ 与 08-决策追踪/ 目录同步"""
    print("\n【校验5】decision-tracking/ ↔ 08-决策追踪/ 目录同步")

    files_to_check = ['state.json', 'daily_snapshot.csv', 'dashboard_data.json']
    has_sync_issue = False
    for fname in files_to_check:
        main_path = STRATEGY_DIR / fname
        alt_path = ALT_DIR / fname
        if not main_path.exists():
            has_sync_issue = True
            error(f"decision-tracking/ 缺少文件: {fname}")
            continue
        if not alt_path.exists():
            has_sync_issue = True
            warn(f"08-决策追踪/ 缺少文件: {fname}")
            continue
        if fname.endswith('.json'):
            main_data = load_json(main_path)
            alt_data = load_json(alt_path)
            # 简化比较：只比较关键字段
            if fname == 'state.json':
                keys = [('position.shares', main_data.get('position', {}).get('shares'), alt_data.get('position', {}).get('shares')),
                        ('position.current_price', main_data.get('position', {}).get('current_price'), alt_data.get('position', {}).get('current_price'))]
            else:
                keys = []
            for k, m, a in keys:
                if m != a:
                    has_sync_issue = True
                    error(f"{fname} 不同步: {k} (主={m}, 旧={a})")
        else:
            with open(main_path, 'r', encoding='utf-8') as f:
                main_content = f.read()
            with open(alt_path, 'r', encoding='utf-8') as f:
                alt_content = f.read()
            if main_content != alt_content:
                has_sync_issue = True
                error(f"{fname} 内容不同步")

    if not has_sync_issue:
        ok("decision-tracking/ 与 08-决策追踪/ 数据同步")


def check_capital_mode():
    """校验6: state.json 中 capital_mode 必须存在且一致"""
    print("\n【校验6】capital_mode 配置检查")

    state = load_json(STRATEGY_DIR / "state.json")
    capital_mode = state.get('account', {}).get('capital_mode')
    if not capital_mode:
        error("state.json 缺少 account.capital_mode 字段，可能导致收益率口径混乱！")
    elif capital_mode.lower() != 'dca':
        warn(f"state.json capital_mode='{capital_mode}'，确认是否为预期值（建议'dca'）")
    else:
        ok(f"capital_mode='{capital_mode}'，收益率将基于累计投入计算")


def main():
    print("=" * 60)
    print("VIX定投策略数据一致性校验")
    print("=" * 60)

    check_state_dashboard_consistency()
    check_daily_returns()
    check_daily_snapshot()
    check_returns_curve()
    check_alt_dir_sync()
    check_capital_mode()

    print("\n" + "=" * 60)
    print(f"校验完成: 错误 {len(ERRORS)} 个, 警告 {len(WARNINGS)} 个")
    print("=" * 60)

    if ERRORS:
        print("\n❌ 发现错误，请修复后再更新数据！")
        return 1
    elif WARNINGS:
        print("\n⚠️  发现警告，建议检查但不阻止更新。")
        return 0
    else:
        print("\n✅ 所有校验通过，数据一致！")
        return 0


if __name__ == "__main__":
    sys.exit(main())
