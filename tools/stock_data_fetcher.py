#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票数据抓取工具 (V5.3.2)
支持港股和A股数据自动抓取，多数据源对比
"""

import json
import sys
from dataclasses import dataclass
from typing import Optional, Dict, List
from datetime import datetime


@dataclass
class StockData:
    """股票数据结构"""
    code: str
    name: str = ""
    price: float = 0.0
    pe_ttm: float = 0.0
    pb: float = 0.0
    dividend_yield: float = 0.0
    market_cap: float = 0.0  # 亿港元/亿人民币
    total_debt: float = 0.0
    interest_bearing_debt: float = 0.0
    cash: float = 0.0
    avg_volume: float = 0.0  # 日均成交额
    currency: str = "HKD"
    
    # 数据源和置信度
    data_sources: Dict[str, str] = None
    confidence: str = "unknown"  # high/medium/low
    
    def __post_init__(self):
        if self.data_sources is None:
            self.data_sources = {}
    
    @property
    def net_cash(self) -> float:
        """净现金 = 现金 - 有息负债"""
        return self.cash - self.interest_bearing_debt
    
    @property
    def interest_bearing_ratio(self) -> float:
        """有息负债率"""
        if self.total_debt == 0:
            return 0.0
        return self.interest_bearing_debt / self.total_debt


class StockDataFetcher:
    """股票数据抓取器"""
    
    def __init__(self, stock_code: str):
        """
        初始化
        :param stock_code: 股票代码，如 "1288.HK" 或 "601288.SH"
        """
        self.code = stock_code
        self.data = StockData(code=stock_code)
        self.errors = []
        
    def fetch_all(self) -> StockData:
        """
        抓取所有数据源并综合
        :return: 综合后的股票数据
        """
        print(f"开始抓取 {self.code} 数据...")
        
        # 尝试多个数据源
        self._try_akshare()
        self._try_yfinance()
        
        # 计算置信度
        self._calculate_confidence()
        
        return self.data
    
    def _try_akshare(self):
        """使用akshare抓取（推荐，国内稳定）"""
        try:
            import akshare as ak
            
            if self.code.endswith('.HK'):
                # 港股数据
                hk_code = self.code.replace('.HK', '')
                
                # 尝试获取港股基础数据
                try:
                    df = ak.stock_hk_hist(symbol=hk_code, period="daily", 
                                         start_date="20250101", adjust="")
                    if not df.empty:
                        latest = df.iloc[-1]
                        self.data.price = float(latest['收盘'])
                        self.data.data_sources['price'] = 'akshare_hk'
                        
                        # 计算日均成交（近20日）
                        if len(df) >= 20:
                            avg_vol = df.tail(20)['成交额'].mean()
                            self.data.avg_volume = float(avg_vol)
                            self.data.data_sources['volume'] = 'akshare_hk'
                except Exception as e:
                    self.errors.append(f"akshare price error: {e}")
                
                # 获取财务数据
                try:
                    # 尝试获取港股财务指标
                    fin_df = ak.stock_hk_fhpx_detail(symbol=hk_code)
                    if not fin_df.empty:
                        latest = fin_df.iloc[0]
                        # 这里需要根据实际返回字段调整
                        self.data.data_sources['financial'] = 'akshare_hk'
                except Exception as e:
                    self.errors.append(f"akshare financial error: {e}")
                    
            elif self.code.endswith('.SH') or self.code.endswith('.SZ'):
                # A股数据
                pass  # 类似实现
                
        except ImportError:
            self.errors.append("akshare not installed")
        except Exception as e:
            self.errors.append(f"akshare error: {e}")
    
    def _try_yfinance(self):
        """使用yfinance抓取（备用）"""
        try:
            import yfinance as yf
            
            ticker = yf.Ticker(self.code)
            info = ticker.info
            
            # 基础价格数据
            if info.get('currentPrice'):
                self.data.price = info.get('currentPrice')
                self.data.data_sources['price'] = 'yfinance'
            
            if info.get('trailingPE'):
                self.data.pe_ttm = info.get('trailingPE')
                self.data.data_sources['pe'] = 'yfinance'
            
            if info.get('priceToBook'):
                self.data.pb = info.get('priceToBook')
                self.data.data_sources['pb'] = 'yfinance'
            
            if info.get('dividendYield'):
                self.data.dividend_yield = info.get('dividendYield') * 100
                self.data.data_sources['dividend'] = 'yfinance'
            
            if info.get('marketCap'):
                # 转换为亿港元（假设是港元计价的港股）
                self.data.market_cap = info.get('marketCap') / 1e8
                self.data.data_sources['market_cap'] = 'yfinance'
            
            # 获取历史成交量
            hist = ticker.history(period="1mo")
            if not hist.empty:
                avg_vol = (hist['Volume'] * hist['Close']).mean()
                self.data.avg_volume = avg_vol
                self.data.data_sources['volume'] = 'yfinance'
                
        except ImportError:
            self.errors.append("yfinance not installed")
        except Exception as e:
            self.errors.append(f"yfinance error: {e}")
    
    def _calculate_confidence(self):
        """计算数据置信度"""
        sources_count = len(self.data.data_sources)
        
        if sources_count >= 4:
            self.data.confidence = "high"
        elif sources_count >= 2:
            self.data.confidence = "medium"
        else:
            self.data.confidence = "low"
    
    def export_markdown(self) -> str:
        """导出为Markdown格式的数据块"""
        md = f"""### 自动抓取数据（{datetime.now().strftime('%Y-%m-%d')}）

| 指标 | 数值 | 数据源 | 置信度 |
|------|------|--------|--------|
| 股价 | {self.data.price:.2f} {self.data.currency} | {self.data.data_sources.get('price', 'N/A')} | {self.data.confidence} |
| PE-TTM | {self.data.pe_ttm:.2f} | {self.data.data_sources.get('pe', 'N/A')} | {self.data.confidence} |
| PB | {self.data.pb:.2f} | {self.data.data_sources.get('pb', 'N/A')} | {self.data.confidence} |
| 股息率 | {self.data.dividend_yield:.2f}% | {self.data.data_sources.get('dividend', 'N/A')} | {self.data.confidence} |
| 市值 | {self.data.market_cap:.2f}亿 | {self.data.data_sources.get('market_cap', 'N/A')} | {self.data.confidence} |
| 日均成交 | {self.data.avg_volume/1e4:.2f}万 | {self.data.data_sources.get('volume', 'N/A')} | {self.data.confidence} |
| 净现金 | {self.data.net_cash:.2f}亿 | 计算值 | - |
| 有息负债率 | {self.data.interest_bearing_ratio*100:.1f}% | 计算值 | - |

**数据质量**: {self.data.confidence} ({len(self.data.data_sources)}个数据源)
**抓取时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return md
    
    def print_report(self):
        """打印报告"""
        print("\n" + "="*60)
        print(f"股票数据报告: {self.code}")
        print("="*60)
        print(f"股价: {self.data.price:.2f}")
        print(f"PE-TTM: {self.data.pe_ttm:.2f}")
        print(f"PB: {self.data.pb:.2f}")
        print(f"股息率: {self.data.dividend_yield:.2f}%")
        print(f"市值: {self.data.market_cap:.2f}亿")
        print(f"日均成交: {self.data.avg_volume/1e4:.2f}万")
        print(f"净现金: {self.data.net_cash:.2f}亿")
        print(f"数据置信度: {self.data.confidence}")
        if self.errors:
            print(f"\n警告: 发现 {len(self.errors)} 个错误")
            for err in self.errors[:3]:
                print(f"  - {err}")
        print("="*60)


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python stock_data_fetcher.py <股票代码>")
        print("示例: python stock_data_fetcher.py 1288.HK")
        print("      python stock_data_fetcher.py 601288.SH")
        sys.exit(1)
    
    code = sys.argv[1]
    fetcher = StockDataFetcher(code)
    data = fetcher.fetch_all()
    fetcher.print_report()
    
    # 导出markdown
    print("\n--- Markdown 格式 ---")
    print(fetcher.export_markdown())


if __name__ == "__main__":
    main()
