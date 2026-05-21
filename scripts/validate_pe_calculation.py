#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PE计算验证脚本 (V5.5.20新增)

功能：验证手动计算的PE/市值是否与主流金融软件一致
用途：防止H股公司市值误算（如保利物业误用H股股本导致PE虚低）

作者: investTemplate
版本: 1.0
日期: 2026-05-21
"""

import sys
import argparse
import urllib.request
import urllib.error
import json
import re
import os
import ssl

# Windows PowerShell GBK编码兼容
if sys.platform == "win32":
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass

# 处理SSL证书验证失败（Windows环境常见）
try:
    _create_unverified_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_context


def parse_args():
    parser = argparse.ArgumentParser(
        description="验证PE计算是否正确，与东方财富交叉验证",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python validate_pe_calculation.py 06049 --price 30.56 --shares 5.5333 --profit 15.50 --currency CNY
  python validate_pe_calculation.py 002027 --price 6.85 --shares 144.42 --profit 58.3 --currency CNY

注意:
  --shares 必须填总股本（亿股），不能填H股流通股本
  --profit 必须填归母净利润（亿人民币）
        """
    )
    parser.add_argument("code", help="股票代码（如 06049, 002027）")
    parser.add_argument("--price", "-p", type=float, required=True, help="当前股价（港元或人民币）")
    parser.add_argument("--shares", "-s", type=float, required=True, help="总股本（亿股）")
    parser.add_argument("--profit", "-f", type=float, required=True, help="归母净利润（亿人民币）")
    parser.add_argument("--currency", "-c", choices=["HKD", "CNY"], default="HKD",
                        help="股价币种（HKD=港元, CNY=人民币），默认HKD")
    parser.add_argument("--exchange-rate", "-e", type=float, default=0.92,
                        help="港元兑人民币汇率（默认0.92）")
    parser.add_argument("--name", "-n", default="", help="公司名称（可选）")
    return parser.parse_args()


def fetch_eastmoney_data(code: str) -> dict:
    """
    从东方财富获取股票市值和PE数据
    港股代码格式: 116.06049
    A股代码格式: 0.002027 (深市) 或 1.600048 (沪市)
    """
    result = {"market_cap": None, "pe": None, "shares": None, "source": None}

    # 判断市场
    if len(code) == 5 and code.isdigit():
        # 港股
        eastmoney_code = f"116.{code}"
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={eastmoney_code}&fields=f57,f58,f60,f84,f85,f162,f167,f170"
    elif len(code) == 6 and code.isdigit():
        # A股
        if code.startswith(("6", "5")):
            eastmoney_code = f"1.{code}"  # 沪市
        else:
            eastmoney_code = f"0.{code}"  # 深市
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={eastmoney_code}&fields=f57,f58,f60,f84,f85,f162,f167,f170"
    else:
        return result

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        if data.get("data"):
            d = data["data"]
            # f84=总股本(股), f85=流通股本(股), f162=市盈率(静), f167=市净率
            # 东方财富API返回的单位是"股"，需要除以1亿转为"亿股"
            result["shares"] = float(d.get("f84", 0)) / 100000000  # 股 -> 亿股
            result["float_shares"] = float(d.get("f85", 0)) / 100000000  # 流通股本
            result["pe"] = float(d.get("f162", 0)) if d.get("f162") else None
            result["pb"] = float(d.get("f167", 0)) if d.get("f167") else None
            result["name"] = d.get("f58", "")
            result["source"] = "东方财富"

            # 计算市值（万股 * 股价 / 10000 = 亿元）
            price = float(d.get("f60", 0))
            if price > 0 and result["shares"] > 0:
                result["market_cap"] = result["shares"] * price

    except Exception as e:
        result["error"] = str(e)

    return result


def validate_calculation(args, eastmoney: dict) -> list:
    """验证计算是否正确，返回问题列表"""
    issues = []

    # 1. 计算手动市值
    manual_market_cap_hkd = args.price * args.shares  # 亿港元
    if args.currency == "HKD":
        manual_market_cap_cny = manual_market_cap_hkd * args.exchange_rate
    else:
        manual_market_cap_cny = manual_market_cap_hkd
        manual_market_cap_hkd = manual_market_cap_cny / args.exchange_rate

    # 2. 计算手动PE
    manual_pe = manual_market_cap_cny / args.profit

    # 3. 检查总股本 vs 流通股本（港股公司关键检查）
    if eastmoney.get("shares") and eastmoney.get("float_shares"):
        total = eastmoney["shares"]
        float_shares = eastmoney["float_shares"]
        if total > float_shares * 1.05:  # 差异>5%
            diff_pct = (total - float_shares) / total * 100
            issues.append({
                "level": "CRITICAL",
                "title": "⚠️ 股本结构警告",
                "msg": f"总股本({total:.4f}亿) > 流通股本({float_shares:.4f}亿)，差异{diff_pct:.1f}%。"
                        f"\n   这是H股/内资股结构！市值必须用总股本计算，不能用流通股本。"
                        f"\n   【保利物业教训】误用流通股本会导致PE虚低约{diff_pct:.0f}%！"
            })

    # 4. 检查手动输入的总股本是否与东方财富一致
    if eastmoney.get("shares"):
        em_shares = eastmoney["shares"]
        share_diff = abs(args.shares - em_shares) / em_shares * 100
        if share_diff > 2:
            issues.append({
                "level": "ERROR",
                "title": "❌ 总股本不一致",
                "msg": f"输入总股本: {args.shares}亿股，东方财富: {em_shares:.4f}亿股，差异{share_diff:.1f}%"
                        f"\n   请确认使用的是最新年报数据，并检查是否有增发/回购/转股"
            })

    # 5. 检查市值与东方财富是否一致
    if eastmoney.get("market_cap"):
        em_cap = eastmoney["market_cap"]
        cap_diff = abs(manual_market_cap_hkd - em_cap) / em_cap * 100
        if cap_diff > 5:
            issues.append({
                "level": "ERROR",
                "title": "❌ 市值计算不一致",
                "msg": f"手动计算市值: {manual_market_cap_hkd:.2f}亿港元，"
                        f"东方财富: {em_cap:.2f}亿港元，差异{cap_diff:.1f}%"
                        f"\n   可能原因: (1)股价时点不同 (2)股本数据不同 (3)计算错误"
            })

    # 6. 检查PE与东方财富是否一致
    if eastmoney.get("pe"):
        em_pe = eastmoney["pe"]
        pe_diff = abs(manual_pe - em_pe) / em_pe * 100
        if pe_diff > 10:  # PE允许10%差异（因净利润口径/TTM差异）
            issues.append({
                "level": "WARNING",
                "title": "⚠️ PE计算差异较大",
                "msg": f"手动计算PE: {manual_pe:.2f}倍，东方财富: {em_pe:.2f}倍，差异{pe_diff:.1f}%"
                        f"\n   可能原因: (1)净利润口径不同（TTM vs 年度）(2)市值计算错误 (3)汇率差异"
                        f"\n   【注意】若差异>20%，极可能是市值计算错误！"
            })

    return issues, manual_pe, manual_market_cap_cny, manual_market_cap_hkd


def print_report(args, eastmoney: dict, issues: list, manual_pe: float,
                 manual_cap_cny: float, manual_cap_hkd: float):
    """打印验证报告"""
    name = args.name or eastmoney.get("name", args.code)
    print("=" * 70)
    print(f"PE计算验证报告: {name} ({args.code})")
    print("=" * 70)

    # 基础数据
    print(f"\n输入参数:")
    print(f"   股价: {args.price} {args.currency}")
    print(f"   总股本: {args.shares} 亿股")
    print(f"   归母净利润: {args.profit} 亿人民币")
    if args.currency == "HKD":
        print(f"   汇率: 1 HKD = {args.exchange_rate} CNY")

    # 手动计算结果
    print(f"\n手动计算结果:")
    if args.currency == "HKD":
        print(f"   市值(HKD): {manual_cap_hkd:.2f} 亿港元")
    print(f"   市值(CNY): {manual_cap_cny:.2f} 亿人民币")
    print(f"   表面PE: {manual_pe:.2f} 倍")

    # 东方财富数据
    has_network_data = eastmoney.get("source") is not None
    if has_network_data:
        print(f"\n东方财富参考数据:")
        print(f"   公司名称: {eastmoney.get('name', 'N/A')}")
        print(f"   总股本: {eastmoney.get('shares', 'N/A')} 亿股")
        if eastmoney.get("float_shares"):
            print(f"   流通股本: {eastmoney['float_shares']:.4f} 亿股")
        print(f"   市值: {eastmoney.get('market_cap', 'N/A')} 亿港元")
        print(f"   PE(静): {eastmoney.get('pe', 'N/A')} 倍")
        print(f"   PB: {eastmoney.get('pb', 'N/A')} 倍")
    else:
        print(f"\n东方财富数据: 获取失败 ({eastmoney.get('error', '网络连接问题')})")

    # 问题列表
    print(f"\n{'=' * 70}")
    if not issues and has_network_data:
        print("验证通过！未发现明显问题。")
    elif not issues and not has_network_data:
        print("[!] 无法自动验证（网络失败）- 请手动核对以下项目：")
        print("   1. 手动计算的市值与同花顺/东方财富显示的市值差异<5%")
        print("   2. 手动计算的PE与同花顺/东方财富显示的PE差异<10%")
        print("   3. 港股公司：确认市值=股价x总股本（不是H股流通股本）")
    else:
        critical = sum(1 for i in issues if i["level"] == "CRITICAL")
        errors = sum(1 for i in issues if i["level"] == "ERROR")
        warnings = sum(1 for i in issues if i["level"] == "WARNING")

        if critical > 0:
            print(f"[!] 发现 {critical} 个严重问题（必须修正）")
        if errors > 0:
            print(f"[!] 发现 {errors} 个错误（必须修正）")
        if warnings > 0:
            print(f"[!] 发现 {warnings} 个警告（建议复核）")

        for issue in issues:
            print(f"\n{issue['title']}")
            print(f"   {issue['msg']}")

    # V5.5.20硬约束检查
    print(f"\n{'=' * 70}")
    print("V5.5.20硬约束检查:")
    if manual_pe < 10:
        print(f"   表面PE {manual_pe:.2f}倍 < 10倍 [通过]")
    elif manual_pe < 12:
        print(f"   表面PE {manual_pe:.2f}倍 [处于边界，建议<10倍]")
    else:
        print(f"   表面PE {manual_pe:.2f}倍 [超出硬约束，必须<10倍]")

    print(f"\n{'=' * 70}")


def main():
    args = parse_args()

    print(f"正在获取 {args.code} 的东方财富数据...")
    eastmoney = fetch_eastmoney_data(args.code)

    issues, manual_pe, manual_cap_cny, manual_cap_hkd = validate_calculation(
        args, eastmoney
    )

    print_report(args, eastmoney, issues, manual_pe, manual_cap_cny, manual_cap_hkd)

    # 返回码: 0=通过, 1=有错误/严重问题, 2=仅警告
    has_critical = any(i["level"] == "CRITICAL" for i in issues)
    has_error = any(i["level"] == "ERROR" for i in issues)

    if has_critical or has_error:
        sys.exit(1)
    elif issues:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
