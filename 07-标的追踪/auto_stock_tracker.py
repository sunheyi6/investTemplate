#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股标的自动追踪系统
- 每天自动获取收盘价
- 生成追踪报告
- 达到目标买点时发送提醒
"""

import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

# 标的配置
STOCKS = {
    # 内银股
    '1398.HK': {'name': '工商银行', 'target_drop': 10, 'category': '内银股', 'base_price': None},
    '3988.HK': {'name': '中国银行', 'target_drop': 10, 'category': '内银股', 'base_price': None},
    '0939.HK': {'name': '建设银行', 'target_drop': 10, 'category': '内银股', 'base_price': None},
    '1288.HK': {'name': '农业银行', 'target_drop': 10, 'category': '内银股', 'base_price': None},
    
    # 能源股
    '1088.HK': {'name': '中国神华', 'target_drop': 15, 'category': '能源股', 'base_price': None},
    '1898.HK': {'name': '中煤能源', 'target_drop': 15, 'category': '能源股', 'base_price': None},
    '0386.HK': {'name': '中国石油', 'target_drop': 15, 'category': '能源股', 'base_price': None},
    '0857.HK': {'name': '中国石油股份', 'target_drop': 15, 'category': '能源股', 'base_price': None},
    
    # 公用事业
    '0836.HK': {'name': '华润电力', 'target_drop': 15, 'category': '公用事业', 'base_price': None},
    '0902.HK': {'name': '华能国际', 'target_drop': 15, 'category': '公用事业', 'base_price': None},
    '2380.HK': {'name': '中国电力', 'target_drop': 15, 'category': '公用事业', 'base_price': None},
    
    # 基建/地产
    '3311.HK': {'name': '中国建筑国际', 'target_drop': 15, 'category': '基建', 'base_price': None},
    '0960.HK': {'name': '龙湖集团', 'target_drop': 20, 'category': '地产', 'base_price': None},
    
    # 烟蒂股
    '0882.HK': {'name': '天津发展', 'target_drop': 5, 'category': '烟蒂股', 'base_price': None},
    '3320.HK': {'name': '华润医药', 'target_drop': 10, 'category': '烟蒂股', 'base_price': None},
    '0363.HK': {'name': '同仁堂国药', 'target_drop': 15, 'category': '烟蒂股', 'base_price': None},
}

class AutoStockTracker:
    def __init__(self, data_dir='stock_data'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.data_file = self.data_dir / 'tracking_data.json'
        self.report_file = self.data_dir / 'daily_report.md'
        self.data = self.load_data()
        
    def load_data(self):
        """加载历史数据"""
        if self.data_file.exists():
            with open(self.data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        # 初始化数据
        return {code: {
            'name': info['name'],
            'category': info['category'],
            'target_drop': info['target_drop'],
            'base_price': None,
            'prices': []
        } for code, info in STOCKS.items()}
    
    def save_data(self):
        """保存数据"""
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def fetch_price(self, code):
        """从Yahoo Finance获取股价"""
        try:
            # Yahoo Finance格式：1398.HK -> 1398.HK
            ticker = yf.Ticker(code)
            hist = ticker.history(period='1d')
            if not hist.empty:
                return round(hist['Close'].iloc[-1], 2)
            return None
        except Exception as e:
            print(f"获取 {code} 价格失败: {e}")
            return None
    
    def update_all_prices(self):
        """更新所有标的价格"""
        today = datetime.now().strftime('%Y-%m-%d')
        print(f"\n=== 更新日期: {today} ===\n")
        
        for code, info in STOCKS.items():
            price = self.fetch_price(code)
            if price:
                self.add_price(code, price, today)
                print(f"✅ {info['name']} ({code}): {price}")
            else:
                print(f"❌ {info['name']} ({code}): 获取失败")
        
        self.save_data()
        print(f"\n数据已保存到: {self.data_file}")
    
    def add_price(self, code, price, date):
        """添加价格记录"""
        if code not in self.data:
            return
        
        # 设置基准价格（第一次记录时）
        if self.data[code]['base_price'] is None:
            self.data[code]['base_price'] = price
        
        # 计算涨跌幅
        base = self.data[code]['base_price']
        change_pct = round((price - base) / base * 100, 2) if base else 0
        
        # 检查是否已存在该日期的记录
        existing = [p for p in self.data[code]['prices'] if p['date'] == date]
        if existing:
            # 更新现有记录
            existing[0]['price'] = price
            existing[0]['change_pct'] = change_pct
        else:
            # 添加新记录
            self.data[code]['prices'].append({
                'date': date,
                'price': price,
                'change_pct': change_pct
            })
    
    def generate_report(self):
        """生成每日追踪报告"""
        today = datetime.now().strftime('%Y-%m-%d')
        
        report_lines = [
            f"# 每日标的追踪报告 ({today})",
            "",
            "> **生成时间**: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "",
            "---",
            "",
        ]
        
        # 可买标的提醒
        buy_signals = []
        
        # 追踪表格
        report_lines.extend([
            "## 📊 追踪概览",
            "",
            "| 代码 | 名称 | 分类 | 基准价格 | 当前价格 | 累计涨跌 | 目标跌幅 | 目标价格 | 距离目标 | 状态 |",
            "|------|------|------|----------|----------|----------|----------|----------|----------|------|",
        ])
        
        for code, info in self.data.items():
            if not info['prices']:
                continue
            
            latest = info['prices'][-1]
            base = info['base_price'] or latest['price']
            target_price = round(base * (1 - info['target_drop']/100), 2)
            current = latest['price']
            change_pct = latest['change_pct']
            
            # 判断是否可买
            if change_pct <= -info['target_drop']:
                status = "🔴 **可买**"
                buy_signals.append({
                    'code': code,
                    'name': info['name'],
                    'current': current,
                    'drop': abs(change_pct),
                    'target': target_price
                })
            else:
                status = "⚪ 观察"
            
            distance = round((current - target_price) / target_price * 100, 1) if target_price else 0
            
            report_lines.append(
                f"| {code} | {info['name']} | {info['category']} | {base} | {current} | "
                f"{change_pct}% | {info['target_drop']}% | {target_price} | {distance}% | {status} |"
            )
        
        report_lines.extend([
            "",
            "---",
            "",
        ])
        
        # 买入提醒
        if buy_signals:
            report_lines.extend([
                "## 🔔 买入提醒",
                "",
                "以下标的已达到目标买点，建议深度分析后考虑买入：",
                "",
            ])
            for signal in buy_signals:
                report_lines.extend([
                    f"### {signal['name']} ({signal['code']})",
                    "",
                    f"- **当前价格**: {signal['current']}",
                    f"- **累计跌幅**: {signal['drop']:.1f}%",
                    f"- **目标价格**: {signal['target']}",
                    f"- **建议**: 使用V4.7模板进行深度分析",
                    "",
                ])
        else:
            report_lines.extend([
                "## 🔔 买入提醒",
                "",
                "暂无标的达到目标买点，继续耐心等待。",
                "",
            ])
        
        report_lines.extend([
            "---",
            "",
            "## 📈 下一步操作",
            "",
            "1. **检查可买标的**：对🔴标记的标的进行深度分析",
            "2. **更新基准价格**：如需调整目标，可重置基准价格",
            "3. **记录决策**：买入/不买入的原因都要记录",
            "",
            "---",
            "",
            f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])
        
        # 保存报告
        report_content = '\n'.join(report_lines)
        with open(self.report_file, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        print(f"\n✅ 报告已生成: {self.report_file}")
        return report_content
    
    def plot_charts(self):
        """生成价格走势图"""
        charts_dir = self.data_dir / 'charts'
        charts_dir.mkdir(exist_ok=True)
        
        for code, info in self.data.items():
            if len(info['prices']) < 2:
                continue
            
            df = pd.DataFrame(info['prices'])
            df['date'] = pd.to_datetime(df['date'])
            
            plt.figure(figsize=(10, 6))
            plt.plot(df['date'], df['price'], marker='o', linewidth=2, markersize=4)
            
            # 添加基准线
            if info['base_price']:
                plt.axhline(y=info['base_price'], color='gray', linestyle='--', alpha=0.5, label='基准价格')
                target = info['base_price'] * (1 - info['target_drop']/100)
                plt.axhline(y=target, color='red', linestyle='--', alpha=0.5, label=f'目标价格({info["target_drop"]}%)')
            
            plt.title(f"{info['name']} ({code}) 价格走势", fontsize=14)
            plt.xlabel('日期', fontsize=12)
            plt.ylabel('价格 (HKD)', fontsize=12)
            plt.grid(True, alpha=0.3)
            plt.legend()
            plt.xticks(rotation=45)
            plt.tight_layout()
            
            chart_file = charts_dir / f"{code.replace('.HK', '')}.png"
            plt.savefig(chart_file, dpi=150)
            plt.close()
            
            print(f"📊 图表已生成: {chart_file}")
    
    def run_daily(self):
        """运行每日追踪"""
        print("=" * 60)
        print("🚀 港股标的自动追踪系统")
        print("=" * 60)
        
        # 1. 更新价格
        self.update_all_prices()
        
        # 2. 生成报告
        report = self.generate_report()
        print("\n" + "=" * 60)
        print("📋 追踪报告预览:")
        print("=" * 60)
        print(report[:1000] + "..." if len(report) > 1000 else report)
        
        # 3. 生成图表（如果有足够数据）
        if any(len(info['prices']) > 1 for info in self.data.values()):
            print("\n📈 正在生成图表...")
            self.plot_charts()
        
        print("\n" + "=" * 60)
        print("✅ 每日追踪完成！")
        print("=" * 60)

def main():
    """主函数"""
    tracker = AutoStockTracker()
    tracker.run_daily()

if __name__ == '__main__':
    main()
