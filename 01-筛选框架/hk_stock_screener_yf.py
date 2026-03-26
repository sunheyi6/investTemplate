#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股金龟筛选器 V1.3 (yfinance版本)
基于V5.5.11标准，使用yfinance数据源
"""

import yfinance as yf
import pandas as pd
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 港股通成分股代码列表（简化版 - 主要候选）
HK_STOCK_UNIVERSE = [
    # 银行H股
    '1398.HK', '0939.HK', '1288.HK', '3988.HK', '2388.HK',  # 工行、建行、农行、中行、中银香港
    '3328.HK', '3968.HK', '0998.HK', '3618.HK',  # 交行、招行、中信银行、渝农商行
    
    # 公用事业
    '0270.HK', '0836.HK', '0902.HK', '0571.HK',  # 粤海投资、华润电力、华能国际、信义玻璃
    '0002.HK', '0003.HK', '0006.HK',  # 中电控股、中华煤气、电能实业
    
    # 地产/物业
    '0604.HK', '2669.HK', '3319.HK', '6049.HK',  # 深圳控股、中海物业、雅生活服务、保利物业
    '0873.HK', '1502.HK', '9928.HK',  # 世茂服务、金融街物业、时代邻里
    
    # 医药流通
    '3320.HK', '1099.HK', '2607.HK', '1515.HK',  # 华润医药、国药控股、上海医药、康哲药业
    
    # 食品饮料
    '0291.HK', '2319.HK', '322.HK',  # 华润啤酒、蒙牛、康师傅
    '3799.HK', '1117.HK', '0460.HK',  # 达利食品、中国食品、四环医药
    
    # 高速公路/基建
    '0177.HK', '0105.HK', '0548.HK',  # 江苏宁沪、捷美达、深圳高速公路
    '0390.HK', '1800.HK', '1186.HK',  # 中国中铁、中国交建、中国铁建
    
    # 其他央国企
    '0688.HK', '0386.HK', '0857.HK', '0883.HK',  # 中国海外发展、中石化、中石油、中海油
    '2628.HK', '2318.HK', '1336.HK', '1339.HK',  # 中国人寿、中国平安、新华保险、人保
    '0700.HK', '3690.HK', '9988.HK', '9999.HK',  # 腾讯、美团、阿里、网易（民营，仅参考）
]

SCREENING_CONFIG = {
    'fcf_yield_min': 0.10,  # FCF/市值 > 10% (对应FCF倍数<10)
    'fcf_yield_strong': 0.16,  # FCF/市值 > 16% (对应FCF倍数<6)
    'pb_max': 1.0,
    'pe_max': 15,
    'dividend_yield_min': 0.04,  # 股息率>4%
}

def get_stock_info(symbol):
    """获取股票基本信息"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # 提取关键指标
        market_cap = info.get('marketCap', 0)  # 市值（港元）
        pb = info.get('priceToBook', 999)
        pe = info.get('trailingPE', 999)
        dividend_yield = info.get('dividendYield', 0) or 0
        
        # 财务数据
        total_cash = info.get('totalCash', 0)
        total_debt = info.get('totalDebt', 0)
        operating_cashflow = info.get('operatingCashflow', 0)
        capital_expenditure = abs(info.get('capitalExpenditures', 0) or 0)
        
        # 计算指标
        net_cash = total_cash - total_debt if total_cash and total_debt else None
        fcf = operating_cashflow - capital_expenditure if operating_cashflow else None
        fcf_yield = fcf / market_cap if fcf and market_cap else 0
        
        return {
            'symbol': symbol,
            'name': info.get('longName', symbol),
            'sector': info.get('sector', 'Unknown'),
            'market_cap_hkd': market_cap / 1e8 if market_cap else 0,  # 亿港元
            'price': info.get('currentPrice', 0),
            'pb': pb if pb else 999,
            'pe': pe if pe else 999,
            'dividend_yield': dividend_yield,
            'total_cash_hkd': total_cash / 1e8 if total_cash else 0,
            'total_debt_hkd': total_debt / 1e8 if total_debt else 0,
            'net_cash_hkd': net_cash / 1e8 if net_cash else None,
            'ocf_hkd': operating_cashflow / 1e8 if operating_cashflow else 0,
            'capex_hkd': capital_expenditure / 1e8,
            'fcf_hkd': fcf / 1e8 if fcf else 0,
            'fcf_yield': fcf_yield,
        }
    except Exception as e:
        print(f"  ❌ {symbol}: {str(e)[:50]}")
        return None

def screen_stocks():
    """主筛选函数"""
    print("=" * 70)
    print("🚀 港股金龟筛选器 V1.3 (yfinance版本)")
    print(f"⏰ 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print(f"\n📋 扫描标的池: {len(HK_STOCK_UNIVERSE)} 只港股\n")
    
    results = []
    
    for i, symbol in enumerate(HK_STOCK_UNIVERSE, 1):
        print(f"[{i}/{len(HK_STOCK_UNIVERSE)}] 分析 {symbol}...", end=' ')
        info = get_stock_info(symbol)
        
        if info and info['market_cap_hkd'] > 0:
            print(f"✅ {info['name'][:20]:20s} FCFYield={info['fcf_yield']*100:.1f}%")
            results.append(info)
        else:
            print("跳过")
    
    if not results:
        print("\n❌ 未获取到有效数据")
        return
    
    df = pd.DataFrame(results)
    
    # 筛选条件
    print("\n" + "=" * 70)
    print("🔍 应用筛选条件")
    print("=" * 70)
    print(f"硬门槛: FCF/市值 > {SCREENING_CONFIG['fcf_yield_min']*100:.0f}% (对应FCF倍数<10)")
    print(f"强机会: FCF/市值 > {SCREENING_CONFIG['fcf_yield_strong']*100:.0f}% (对应FCF倍数<6)")
    print(f"辅助: PB < {SCREENING_CONFIG['pb_max']}, 股息率 > {SCREENING_CONFIG['dividend_yield_min']*100:.0f}%")
    
    # 分级筛选
    df['fcf_multiple'] = 1 / df['fcf_yield'] if (df['fcf_yield'] > 0).any() else 999
    
    # 强机会
    golden = df[df['fcf_yield'] >= SCREENING_CONFIG['fcf_yield_strong']].copy()
    golden = golden.sort_values('fcf_yield', ascending=False)
    
    # 研究候选
    silver = df[
        (df['fcf_yield'] >= SCREENING_CONFIG['fcf_yield_min']) & 
        (df['fcf_yield'] < SCREENING_CONFIG['fcf_yield_strong'])
    ].copy()
    silver = silver.sort_values('fcf_yield', ascending=False)
    
    # 高股息候选（FCF不足但股息率高）
    dividend = df[
        (df['fcf_yield'] < SCREENING_CONFIG['fcf_yield_min']) &
        (df['dividend_yield'] >= SCREENING_CONFIG['dividend_yield_min'])
    ].copy()
    
    # 输出结果
    print("\n" + "=" * 70)
    print(f"🏆 强机会 (FCF收益率 ≥ {SCREENING_CONFIG['fcf_yield_strong']*100:.0f}%) - {len(golden)} 只")
    print("=" * 70)
    if not golden.empty:
        display_cols = ['symbol', 'name', 'fcf_yield', 'pb', 'pe', 'dividend_yield', 'net_cash_hkd']
        print(golden[display_cols].to_string(index=False))
    else:
        print("暂无符合强机会标准的标的")
    
    print("\n" + "=" * 70)
    print(f"🥈 研究候选 ({SCREENING_CONFIG['fcf_yield_min']*100:.0f}% ≤ FCF收益率 < {SCREENING_CONFIG['fcf_yield_strong']*100:.0f}%) - {len(silver)} 只")
    print("=" * 70)
    if not silver.empty:
        display_cols = ['symbol', 'name', 'fcf_yield', 'pb', 'pe', 'dividend_yield']
        print(silver[display_cols].head(10).to_string(index=False))
    else:
        print("暂无符合研究候选标准的标的")
    
    print("\n" + "=" * 70)
    print(f"💰 高股息候选 (FCF<10%但股息率≥4%) - {len(dividend)} 只")
    print("=" * 70)
    if not dividend.empty:
        display_cols = ['symbol', 'name', 'dividend_yield', 'pb', 'pe']
        print(dividend[display_cols].head(5).to_string(index=False))
    
    # 保存结果
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"hk_screening_yf_{timestamp}.csv"
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n💾 完整数据已保存: {output_file}")
    
    return golden, silver, dividend

if __name__ == "__main__":
    screen_stocks()
