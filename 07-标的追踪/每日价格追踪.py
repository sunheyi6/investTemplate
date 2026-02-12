#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股标的每日价格追踪脚本
用于记录标的的价格走势，生成报告
"""

import pandas as pd
import json
from datetime import datetime, timedelta
import os

# 标的配置
STOCKS = {
    # 内银股
    '1398.HK': {'name': '工商银行', 'target_drop': 10, 'category': '内银股'},
    '3988.HK': {'name': '中国银行', 'target_drop': 10, 'category': '内银股'},
    '0939.HK': {'name': '建设银行', 'target_drop': 10, 'category': '内银股'},
    '1288.HK': {'name': '农业银行', 'target_drop': 10, 'category': '内银股'},
    
    # 能源股
    '1088.HK': {'name': '中国神华', 'target_drop': 15, 'category': '能源股'},
    '1898.HK': {'name': '中煤能源', 'target_drop': 15, 'category': '能源股'},
    '0386.HK': {'name': '中国石油', 'target_drop': 15, 'category': '能源股'},
    '0857.HK': {'name': '中国石油股份', 'target_drop': 15, 'category': '能源股'},
    
    # 公用事业
    '0836.HK': {'name': '华润电力', 'target_drop': 15, 'category': '公用事业'},
    '0902.HK': {'name': '华能国际', 'target_drop': 15, 'category': '公用事业'},
    '2380.HK': {'name': '中国电力', 'target_drop': 15, 'category': '公用事业'},
    
    # 基建/地产
    '3311.HK': {'name': '中国建筑国际', 'target_drop': 15, 'category': '基建'},
    '0960.HK': {'name': '龙湖集团', 'target_drop': 20, 'category': '地产'},
    
    # 烟蒂股
    '0882.HK': {'name': '天津发展', 'target_drop': 5, 'category': '烟蒂股'},
    '3320.HK': {'name': '华润医药', 'target_drop': 10, 'category': '烟蒂股'},
    '0363.HK': {'name': '同仁堂国药', 'target_drop': 15, 'category': '烟蒂股'},
}

class StockTracker:
    def __init__(self, data_file='stock_data.json'):
        self.data_file = data_file
        self.data = self.load_data()
        
    def load_data(self):
        """加载历史数据"""
        if os.path.exists(self.data_file):
            with open(self.data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def save_data(self):
        """保存数据"""
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def add_price(self, code, price, date=None):
        """添加价格记录"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        if code not in self.data:
            self.data[code] = {
                'name': STOCKS.get(code, {}).get('name', 'Unknown'),
                'category': STOCKS.get(code, {}).get('category', 'Unknown'),
                'target_drop': STOCKS.get(code, {}).get('target_drop', 10),
                'base_price': price,  # 基准价格
                'prices': []
            }
        
        self.data[code]['prices'].append({
            'date': date,
            'price': price,
            'change_pct': self._calc_change(code, price)
        })
        
        self.save_data()
    
    def _calc_change(self, code, current_price):
        """计算相对基准价格的变化"""
        if code in self.data and self.data[code]['base_price']:
            base = self.data[code]['base_price']
            return round((current_price - base) / base * 100, 2)
        return 0
    
    def get_report(self):
        """生成追踪报告"""
        report = []
        today = datetime.now().strftime('%Y-%m-%d')
        
        for code, info in self.data.items():
            if not info['prices']:
                continue
                
            latest = info['prices'][-1]
            target_price = info['base_price'] * (1 - info['target_drop']/100)
            
            report.append({
                '代码': code,
                '名称': info['name'],
                '分类': info['category'],
                '当前价格': latest['price'],
                '基准价格': info['base_price'],
                '累计涨跌': f"{latest['change_pct']}%",
                '目标跌幅': f"{info['target_drop']}%",
                '目标价格': round(target_price, 2),
                '距离目标': f"{round((latest['price'] - target_price) / target_price * 100, 1)}%",
                '是否可买': '🔴 可买' if latest['change_pct'] <= -info['target_drop'] else '⚪ 观察',
                '最后更新': latest['date']
            })
        
        return pd.DataFrame(report)
    
    def export_to_excel(self, filename='stock_tracking.xlsx'):
        """导出到Excel"""
        df = self.get_report()
        
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='追踪概览', index=False)
            
            # 详细价格历史
            for code, info in self.data.items():
                if info['prices']:
                    price_df = pd.DataFrame(info['prices'])
                    sheet_name = f"{code.replace('.HK', '')}"
                    price_df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
        
        print(f"✅ 报告已导出: {filename}")

# 使用示例
def demo():
    """演示如何使用"""
    tracker = StockTracker()
    
    # 模拟添加今日价格（实际使用时需要接入数据源）
    print("=== 港股标的追踪系统 ===\n")
    print("使用说明：")
    print("1. 手动记录每日收盘价")
    print("2. 运行脚本生成报告")
    print("3. 当'是否可买'显示🔴时，深度分析后考虑买入\n")
    
    print("示例命令：")
    print("tracker.add_price('1398.HK', 4.2)  # 记录工商银行价格")
    print("tracker.get_report()  # 获取报告")
    print("tracker.export_to_excel()  # 导出Excel\n")
    
    # 如果有数据，显示报告
    if tracker.data:
        print("当前追踪报告：")
        print(tracker.get_report())
    else:
        print("暂无数据，请先添加价格记录")

if __name__ == '__main__':
    demo()
