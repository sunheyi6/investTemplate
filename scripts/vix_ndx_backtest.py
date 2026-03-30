# -*- coding: utf-8 -*-
"""
VIX-纳斯达克100定投回测脚本 V3.0（同总投入口径）
基于投资模板 V5.5.13 标准自动回测

核心口径：
1) 普通固定定投：每月固定投入（默认 1000 USD）
2) 精细6档 VIX 等额定投：按VIX档位动态调整月投入，但总投入与普通定投严格相同
3) 一次性满仓：在首个定投日一次性投入同等总资金

输出维度：总投入、期末资产、总收益率、复合年化(IRR)、最大回撤
"""

import warnings
warnings.filterwarnings('ignore')

from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

try:
    import matplotlib.pyplot as plt
    HAS_MPL = True
except Exception:
    HAS_MPL = False


# 路径配置
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "05-策略框架" / "VIX-纳斯达克100定投策略"
CHARTS_DIR = OUTPUT_DIR / "charts"
REPORT_FILE = OUTPUT_DIR / "backtest_report.md"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CHARTS_DIR.mkdir(parents=True, exist_ok=True)


BACKTEST_CONFIG = {
    'start_date': '2015-01-01',
    'symbol': 'QQQ',
    'vix_symbol': '^VIX',
    'investment_day': 1,               # 每月第1个交易日
    'fixed_monthly_investment': 1000,  # 普通定投每月固定投入
    'transaction_cost': 0.0,
    # 精细6档（可按需求微调）
    # (low, high, multiplier, label)
    'vix_rules': [
        (0, 15, 1.0, '正常'),
        (15, 20, 1.5, '轻度偏高'),
        (20, 25, 2.0, '中度恐慌'),
        (25, 30, 3.0, '高度恐慌'),
        (30, 40, 5.0, '极度恐慌'),
        (40, 999, 8.0, '罕见恐慌'),
    ],
}


def get_multiplier(vix_value: float):
    """根据VIX值返回对应倍数和标签"""
    for low, high, mult, label in BACKTEST_CONFIG['vix_rules']:
        if low <= vix_value < high:
            return mult, label
    return 1.0, '正常'


def xirr(cashflows_df: pd.DataFrame):
    """计算XIRR（年化内部收益率）。输入列: date, cashflow"""
    cf = cashflows_df.sort_values('date').copy()
    if cf.empty:
        return np.nan
    if not ((cf['cashflow'] < 0).any() and (cf['cashflow'] > 0).any()):
        return np.nan

    t0 = cf['date'].iloc[0]
    years = (cf['date'] - t0).dt.days / 365.25

    def npv(rate):
        return np.sum(cf['cashflow'].values / np.power(1 + rate, years.values))

    def d_npv(rate):
        return np.sum(-years.values * cf['cashflow'].values / np.power(1 + rate, years.values + 1))

    rate = 0.15
    for _ in range(200):
        f = npv(rate)
        df = d_npv(rate)
        if abs(df) < 1e-12:
            break
        new_rate = rate - f / df
        if new_rate <= -0.999999:
            new_rate = (rate - 0.999999) / 2
        if abs(new_rate - rate) < 1e-10:
            rate = new_rate
            break
        rate = new_rate

    return rate


def download_data(retries: int = 5):
    """下载QQQ和VIX历史数据"""
    start = BACKTEST_CONFIG['start_date']
    end = datetime.now().strftime('%Y-%m-%d')

    for i in range(retries):
        qqq = yf.download(BACKTEST_CONFIG['symbol'], start=start, end=end, progress=False, auto_adjust=True, threads=False)
        vix = yf.download(BACKTEST_CONFIG['vix_symbol'], start=start, end=end, progress=False, auto_adjust=True, threads=False)
        if len(qqq) > 0 and len(vix) > 0:
            if isinstance(qqq.columns, pd.MultiIndex):
                qqq.columns = qqq.columns.get_level_values(0)
            if isinstance(vix.columns, pd.MultiIndex):
                vix.columns = vix.columns.get_level_values(0)

            df = pd.DataFrame({
                'QQQ': qqq['Close'].squeeze(),
                'VIX': vix['Close'].squeeze(),
            }).dropna()
            if not df.empty:
                print(f"数据下载成功（尝试 {i+1}/{retries}）：{df.index[0].strftime('%Y-%m-%d')} -> {df.index[-1].strftime('%Y-%m-%d')}, 共{len(df)}个交易日")
                return df

    raise RuntimeError('下载QQQ/VIX数据失败，请稍后重试')


def get_investment_dates(df: pd.DataFrame):
    """每月第N个交易日"""
    temp = df.copy()
    temp['year_month'] = temp.index.to_period('M')
    n = BACKTEST_CONFIG['investment_day']
    dates = []
    for _, g in temp.groupby('year_month'):
        if len(g) >= n:
            dates.append(g.index[n - 1])
    return pd.DatetimeIndex(dates)


def build_monthly_signals(df: pd.DataFrame, dates: pd.DatetimeIndex):
    """构建每月信号（价格、前日VIX、倍数）"""
    rows = []
    for d in dates:
        idx = df.index.get_loc(d)
        prev_date = df.index[max(0, idx - 1)]
        vix_value = float(df.loc[prev_date, 'VIX'])
        mult, label = get_multiplier(vix_value)
        price = float(df.loc[d, 'QQQ'])
        rows.append({
            'date': d,
            'price': price,
            'vix': vix_value,
            'multiplier': mult,
            'label': label,
        })
    return pd.DataFrame(rows)


def run_strategy(monthly_df: pd.DataFrame, investments: pd.Series, name: str):
    """按给定月投入序列回测策略"""
    tx_cost = BACKTEST_CONFIG['transaction_cost']

    total_shares = 0.0
    cumulative_invested = 0.0
    records = []

    for _, row in monthly_df.iterrows():
        d = row['date']
        price = float(row['price'])
        invest = float(investments.loc[d])
        buy_amount = max(0.0, invest - tx_cost)
        shares = buy_amount / price if price > 0 else 0.0

        total_shares += shares
        cumulative_invested += invest
        portfolio_value = total_shares * price

        records.append({
            'date': d,
            'strategy': name,
            'price': price,
            'vix': row.get('vix', np.nan),
            'multiplier': row.get('multiplier', np.nan),
            'label': row.get('label', ''),
            'investment': invest,
            'shares': shares,
            'total_shares': total_shares,
            'total_invested': cumulative_invested,
            'portfolio_value': portfolio_value,
        })

    return pd.DataFrame(records)


def build_investment_plans(monthly_df: pd.DataFrame):
    """构建三种策略的月投入计划（同总投入）"""
    n_months = len(monthly_df)
    fixed = BACKTEST_CONFIG['fixed_monthly_investment']
    total_target = fixed * n_months

    # 1) 普通固定定投
    plan_plain = pd.Series(fixed, index=monthly_df['date'])

    # 2) VIX 6档等额定投：总额固定，按倍数分配
    weights = monthly_df['multiplier'].astype(float)
    unit = total_target / weights.sum()
    plan_vix = pd.Series(unit * weights.values, index=monthly_df['date'])

    # 3) 一次性满仓
    lump = pd.Series(0.0, index=monthly_df['date'])
    lump.iloc[0] = total_target

    return plan_plain, plan_vix, lump, total_target, unit


def calculate_metrics(records_df: pd.DataFrame):
    """计算核心绩效指标"""
    rec = records_df.copy().sort_values('date')

    total_invested = float(rec['investment'].sum())
    final_assets = float(rec['portfolio_value'].iloc[-1])
    total_return = (final_assets / total_invested - 1) * 100 if total_invested > 0 else np.nan

    # IRR口径复合年化
    cf = pd.DataFrame({
        'date': rec['date'],
        'cashflow': -rec['investment'].values,
    })
    cf = pd.concat([
        cf,
        pd.DataFrame([{'date': rec['date'].iloc[-1], 'cashflow': final_assets}])
    ], ignore_index=True)
    irr = xirr(cf)

    # 传统CAGR（非现金流口径，便于参考）
    years = (rec['date'].iloc[-1] - rec['date'].iloc[0]).days / 365.25
    cagr = ((final_assets / total_invested) ** (1 / years) - 1) * 100 if years > 0 and total_invested > 0 else np.nan

    # 最大回撤（月度净值）
    nav = rec['portfolio_value'] / rec['investment'].sum() * len(rec) if rec['investment'].sum() > 0 else rec['portfolio_value']
    # 用资产曲线直接算回撤，和排名表口径一致（越小越好）
    running_max = rec['portfolio_value'].cummax()
    drawdown = (rec['portfolio_value'] - running_max) / running_max
    max_dd = float(drawdown.min() * 100)

    return {
        'months': len(rec),
        'total_invested': total_invested,
        'final_assets': final_assets,
        'total_return_pct': float(total_return),
        'irr_pct': float(irr * 100) if pd.notna(irr) else np.nan,
        'cagr_pct': float(cagr),
        'max_drawdown_pct': max_dd,
    }


def generate_charts(df_plain, df_vix, df_lump):
    """生成图表（可选）"""
    if not HAS_MPL:
        print('未检测到 matplotlib，跳过图表生成')
        return

    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False

    # 1) 资产曲线
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(df_plain['date'], df_plain['portfolio_value'], label='普通固定定投', linewidth=2.2, color='#1f77b4')
    ax.plot(df_vix['date'], df_vix['portfolio_value'], label='精细6档 VIX 等额定投', linewidth=2.2, color='#d62728')
    ax.plot(df_lump['date'], df_lump['portfolio_value'], label='一次性满仓', linewidth=2.2, color='#2ca02c', linestyle='--')
    ax.set_title('三策略资产曲线对比')
    ax.set_xlabel('日期')
    ax.set_ylabel('资产 (USD)')
    ax.grid(alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / 'total_assets_comparison.png', dpi=150)
    plt.close()

    # 2) 回撤曲线
    fig, ax = plt.subplots(figsize=(14, 6))
    for name, df, color in [
        ('普通固定定投', df_plain, '#1f77b4'),
        ('精细6档 VIX 等额定投', df_vix, '#d62728'),
        ('一次性满仓', df_lump, '#2ca02c'),
    ]:
        dd = (df['portfolio_value'] / df['portfolio_value'].cummax() - 1) * 100
        ax.plot(df['date'], dd, label=name, linewidth=2.0, color=color)
    ax.set_title('三策略回撤曲线')
    ax.set_xlabel('日期')
    ax.set_ylabel('回撤(%)')
    ax.grid(alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / 'drawdown_comparison.png', dpi=150)
    plt.close()

    # 3) VIX等额定投月投入
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.bar(df_vix['date'], df_vix['investment'], width=20, color='#d62728', alpha=0.8)
    ax.set_title('精细6档 VIX 等额定投：月投入金额')
    ax.set_xlabel('日期')
    ax.set_ylabel('投入金额 (USD)')
    ax.grid(alpha=0.25, axis='y')
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / 'monthly_investment.png', dpi=150)
    plt.close()

    print(f'图表已保存到: {CHARTS_DIR}')


def generate_report(metrics_plain, metrics_vix, metrics_lump, total_target, unit_amount, df_vix):
    """生成Markdown报告"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    # 按总收益率排序
    ranking = [
        ('普通固定定投', metrics_plain),
        ('精细 6 档 VIX 等额定投', metrics_vix),
        ('一次性满仓', metrics_lump),
    ]

    lines = [
        '# VIX-纳斯达克100定投策略回测报告（同总投入口径）',
        '',
        f'> **生成时间**: {now}',
        f"> **数据范围**: {BACKTEST_CONFIG['start_date']} 至今",
        f"> **标的**: {BACKTEST_CONFIG['symbol']} (Invesco QQQ Trust - 纳斯达克100 ETF)",
        f"> **恐慌指数**: {BACKTEST_CONFIG['vix_symbol']} (CBOE Volatility Index)",
        '',
        '---',
        '',
        '## 回测前提（关键）',
        '',
        f"- 三种策略 **总投入严格一致**：`${total_target:,.0f}`",
        f"- 普通定投：每月固定 `${BACKTEST_CONFIG['fixed_monthly_investment']:,.0f}`",
        f"- VIX等额定投：按6档倍数分配，单位投入约 `${unit_amount:,.2f}`，总额仍为 `${total_target:,.0f}`",
        '- 一次性满仓：首月一次性投入全部资金',
        '',
        '## 排名维度参考',
        '',
        '| 策略 | 总投入 | 期末资产 | 总收益率 | 复合年化(IRR) | 最大回撤 |',
        '|------|--------|----------|----------|---------------|----------|',
        f"| 普通固定定投 | ${metrics_plain['total_invested']:,.0f} | ${metrics_plain['final_assets']:,.2f} | {metrics_plain['total_return_pct']:.2f}% | {metrics_plain['irr_pct']:.2f}% | {abs(metrics_plain['max_drawdown_pct']):.2f}% |",
        f"| 精细 6 档 VIX 等额定投 | ${metrics_vix['total_invested']:,.0f} | ${metrics_vix['final_assets']:,.2f} | {metrics_vix['total_return_pct']:.2f}% | {metrics_vix['irr_pct']:.2f}% | {abs(metrics_vix['max_drawdown_pct']):.2f}% |",
        f"| 一次性满仓 | ${metrics_lump['total_invested']:,.0f} | ${metrics_lump['final_assets']:,.2f} | {metrics_lump['total_return_pct']:.2f}% | {metrics_lump['irr_pct']:.2f}% | {abs(metrics_lump['max_drawdown_pct']):.2f}% |",
        '',
        '## VIX 6档规则',
        '',
        '| VIX区间 | 倍数 | 标签 |',
        '|---------|------|------|',
    ]

    for low, high, mult, label in BACKTEST_CONFIG['vix_rules']:
        if high >= 999:
            scope = f">= {low}"
        else:
            scope = f"{low}-{high}"
        lines.append(f'| {scope} | {mult:.1f}x | {label} |')

    lines.extend([
        '',
        '### 执行统计',
        f"- 定投月数：{len(df_vix)}",
        f"- 触发加仓月数（>1x）：{int((df_vix['multiplier'] > 1).sum())}",
        f"- 高恐慌月数（>=5x）：{int((df_vix['multiplier'] >= 5).sum())}",
        '',
        '## 图表',
        '',
        '![总资产对比](./charts/total_assets_comparison.png)',
        '',
        '![回撤对比](./charts/drawdown_comparison.png)',
        '',
        '![VIX月投入](./charts/monthly_investment.png)',
        '',
        '---',
        '',
        '*报告由 `scripts/vix_ndx_backtest.py` 自动生成*',
    ])

    REPORT_FILE.write_text('\n'.join(lines), encoding='utf-8')
    print(f'报告已生成: {REPORT_FILE}')


def main():
    print('=' * 72)
    print('VIX-纳斯达克100回测 V3.0（同总投入、无现金留存）')
    print(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print('=' * 72)

    df = download_data()
    dates = get_investment_dates(df)
    monthly = build_monthly_signals(df, dates)

    plan_plain, plan_vix, plan_lump, total_target, unit_amount = build_investment_plans(monthly)

    df_plain = run_strategy(monthly, plan_plain, '普通固定定投')
    df_vix = run_strategy(monthly, plan_vix, '精细 6 档 VIX 等额定投')
    df_lump = run_strategy(monthly, plan_lump, '一次性满仓')

    m_plain = calculate_metrics(df_plain)
    m_vix = calculate_metrics(df_vix)
    m_lump = calculate_metrics(df_lump)

    print('\n排名维度参考\t总投入\t期末资产\t总收益率\t复合年化(IRR)\t最大回撤')
    print(f"① 普通固定定投\t${m_plain['total_invested']:.0f}\t${m_plain['final_assets']:.0f}\t{m_plain['total_return_pct']:.2f}%\t{m_plain['irr_pct']:.2f}%\t{abs(m_plain['max_drawdown_pct']):.2f}%")
    print(f"② 精细6档 VIX 等额定投\t${m_vix['total_invested']:.0f}\t${m_vix['final_assets']:.0f}\t{m_vix['total_return_pct']:.2f}%\t{m_vix['irr_pct']:.2f}%\t{abs(m_vix['max_drawdown_pct']):.2f}%")
    print(f"③ 一次性满仓\t${m_lump['total_invested']:.0f}\t${m_lump['final_assets']:.0f}\t{m_lump['total_return_pct']:.2f}%\t{m_lump['irr_pct']:.2f}%\t{abs(m_lump['max_drawdown_pct']):.2f}%")

    generate_charts(df_plain, df_vix, df_lump)
    generate_report(m_plain, m_vix, m_lump, total_target, unit_amount, df_vix)


if __name__ == '__main__':
    main()
