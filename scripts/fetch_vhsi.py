# -*- coding: utf-8 -*-
"""
港股恒指波幅指数(VHSI)抓取脚本 V1.0 (V5.5.13版)
每日抓取 ^VHSI 收盘价，作为港股情绪主锚
"""
import yfinance as yf
from datetime import datetime
import json
import os

VHSI_SYMBOL = "^VHSI"  # Yahoo Finance 代码
OUTPUT_FILE = "08-决策追踪/vhsi_monitoring.json"


def fetch_vhsi():
    ticker = yf.Ticker(VHSI_SYMBOL)
    hist = ticker.history(period="5d")
    if hist.empty:
        raise ValueError("Failed to fetch VHSI data")

    latest = hist.iloc[-1]
    vhsi = round(float(latest["Close"]), 2)

    data = {
        "date": hist.index[-1].strftime("%Y-%m-%d"),
        "vhsi_close": vhsi,
        "level": get_vhsi_level(vhsi),
        "timestamp": datetime.now().isoformat(),
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"VHSI: {data['vhsi_close']} ({data['level']})")
    return data


def get_vhsi_level(vhsi):
    if vhsi < 22:
        return "平静期"
    if vhsi < 27:
        return "谨慎期"
    if vhsi < 32:
        return "恐慌期"
    if vhsi < 40:
        return "高度恐慌期"
    return "极端恐慌期"


if __name__ == "__main__":
    fetch_vhsi()
