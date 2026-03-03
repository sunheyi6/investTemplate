#!/usr/bin/env python3
import yfinance as yf

# 保利物业
stock = yf.Ticker('6049.HK')
info = stock.info
hist = stock.history(period='1mo')

print('=== 保利物业 (06049.HK) 基础数据 ===')
print(f"股票名称: {info.get('longName', '保利物业')}")
price = info.get('currentPrice') or info.get('previousClose') or 0
print(f"当前股价: {price:.2f} 港元")
print(f"市值: {info.get('marketCap', 0)/1e8:.2f} 亿港元")
print(f"PE-TTM: {info.get('trailingPE', 0):.2f}")
print(f"PB: {info.get('priceToBook', 0):.2f}")
div_yield = info.get('dividendYield') or 0
print(f"股息率: {div_yield*100:.2f}%")

# 计算日均成交
if not hist.empty:
    avg_volume_hkd = (hist['Volume'] * hist['Close']).mean()
    print(f"日均成交: {avg_volume_hkd/1e4:.2f} 万港元")
