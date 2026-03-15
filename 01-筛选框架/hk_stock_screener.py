#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股金龟筛选器 V1.1 (V5.5.7熊市标准版)
基于投资模板V5.5.7标准自动筛选港股标的
数据来源：东方财富（akshare）

【V5.5.7更新】熊市阈值调整：
- PB < 0.6（原0.8）
- PE < 6（原10）
- 股息率 > 6%（原3.5%）
- FCF倍数 < 3倍（隐含FCF/市值>12%）
"""

import akshare as ak
import pandas as pd
import time
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ==========================================
# 筛选标准配置（V5.5.7 熊市阈值调整版）
# ==========================================
# 当前市场状态：熊市（恒指-4%，技术性熊市，地缘风险）
# 执行标准：FCF倍数<3，股息率>6%，PB<0.6，PE<6
SCREENING_CONFIG = {
    # 基础指标（熊市收紧版 V5.5.7）
    'pb_max': 0.6,                    # PB < 0.6（熊市标准，原0.8）
    'pe_max': 6,                      # PE < 6（熊市标准，原10）
    'dividend_yield_min': 6.0,        # 股息率 > 6%（熊市标准，原3.5%）
    'market_cap_min': 10,             # 市值 > 10亿港元
    
    # 央国企白名单（港股常见央企/国企代码前缀）
    'central_soe_prefix': ['01', '02', '03', '11', '12', '13', '23', '33', '39', '60', '61', '68'],
    # 注：以上为常见央企代码前缀，非绝对准确，仅供参考
    
    # 排除行业（模板明确排除）
    'exclude_industries': ['石油', '煤炭', '影视', '游戏', '博彩', '加密货币'],
    
    # 缓存设置
    'delay': 0.5,                     # 请求间隔，避免被封
}

# ==========================================
# 数据获取模块
# ==========================================

def get_hk_stock_list():
    """
    获取港股全市场股票列表（含基础指标）
    """
    print("📊 正在获取港股列表...")
    try:
        # 获取港股实时行情（包含PE/PB/股息率等）
        df = ak.stock_hk_ggt_components_em()
        print(f"✅ 获取到港股通成分股 {len(df)} 只")
        return df
    except Exception as e:
        print(f"❌ 获取港股列表失败: {e}")
        return pd.DataFrame()

def get_stock_detail(code):
    """
    获取个股详细财务数据
    """
    try:
        time.sleep(SCREENING_CONFIG['delay'])
        
        # 获取财务指标
        financial = ak.stock_financial_hk_analysis_indicator_em(symbol=code)
        
        # 获取公司资料（用于判断国企背景）
        profile = ak.stock_hk_profile_em(symbol=code)
        
        return {
            'financial': financial,
            'profile': profile
        }
    except Exception as e:
        return None

def get_stock_financial_data(code, name):
    """
    获取个股详细财务数据（用于深度分析）
    尝试获取：净利润、现金流、现金余额、负债等
    """
    try:
        time.sleep(SCREENING_CONFIG['delay'])
        
        result = {
            'code': code,
            'name': name,
            'net_profit': None,           # 净利润
            'operating_cash_flow': None,  # 经营现金流
            'cash_and_equivalents': None, # 现金及等价物
            'total_liabilities': None,    # 总负债
            'interest_bearing_debt': None, # 有息负债
            'total_equity': None,         # 股东权益
            'dividend': None,             # 派息金额
        }
        
        # 尝试获取财务摘要
        try:
            summary = ak.stock_hk_financial_summary_em(symbol=code)
            if not summary.empty:
                # 解析财务摘要数据
                for _, row in summary.iterrows():
                    item = row.get('项目', '')
                    value = row.get('数值', '')
                    
                    if '净利润' in item or '股东应占溢利' in item:
                        result['net_profit'] = parse_number(value)
                    elif '经营现金流' in item or '经营活动所得现金' in item:
                        result['operating_cash_flow'] = parse_number(value)
                    elif '现金及现金等价物' in item:
                        result['cash_and_equivalents'] = parse_number(value)
                    elif '总负债' in item:
                        result['total_liabilities'] = parse_number(value)
                    elif '股东权益' in item or '净资产' in item:
                        result['total_equity'] = parse_number(value)
                    elif '派息' in item or '股息' in item:
                        result['dividend'] = parse_number(value)
        except:
            pass
        
        return result
    except Exception as e:
        return None

def parse_number(value_str):
    """解析数值字符串"""
    if pd.isna(value_str) or value_str == '-' or value_str == '':
        return None
    
    # 处理带单位的字符串
    value_str = str(value_str).replace(',', '').replace('港元', '').replace('人民币', '')
    
    try:
        # 处理亿、万等单位
        if '亿' in value_str:
            return float(value_str.replace('亿', ''))
        elif '万' in value_str:
            return float(value_str.replace('万', '')) / 10000
        else:
            return float(value_str)
    except:
        return None

# ==========================================
# 筛选逻辑模块
# ==========================================

def is_likely_central_soe(code, name, profile_df=None):
    """
    判断是否可能是央国企（启发式判断，非100%准确）
    """
    # 从名称判断
    central_keywords = [
        '中国', '中國', '中信', '中建', '中铁', '中交', '中航',
        '中远', '中外运', '中粮', '华润', '保利', '招商',
        '工商', '农业', '建设', '中国', '银行', '保险',
        '石油', '石化', '移动', '联通', '电信', '海洋',
        '国航', '南航', '东航', '中车', '中煤', '中铝',
        '中化', '国药', '中烟', '中广核', '华能', '大唐',
        '华电', '国电', '长江', '三峡', '国家', '中核',
        '中金', '光大', '广发', '海通', '华泰', '国泰',
        '北京', '上海', '天津', '重庆', '广东', '深圳',
        '广州', '厦门', '青岛', '宁波', '南京', '成都',
        '武汉', '西安', '沈阳', '大连', '济南', '杭州',
        '苏州', '无锡', '佛山', '东莞', '长沙', '郑州',
        '石家庄', '太原', '合肥', '南昌', '福州', '昆明',
        '贵阳', '南宁', '海口', '兰州', '银川', '西宁',
        '乌鲁木齐', '拉萨', '呼和浩特', '哈尔滨', '长春'
    ]
    
    name_upper = str(name).upper()
    
    # 检查关键词
    for keyword in central_keywords:
        if keyword in name_upper:
            return True, f"名称含'{keyword}'"
    
    # 从代码前缀判断（粗略）
    code_prefix = str(code)[:2]
    if code_prefix in SCREENING_CONFIG['central_soe_prefix']:
        return True, f"代码前缀{code_prefix}"
    
    return False, "疑似民营"

def should_exclude_industry(name, profile_df=None):
    """
    判断是否属于排除行业
    """
    name_upper = str(name).upper()
    
    for industry in SCREENING_CONFIG['exclude_industries']:
        if industry in name_upper:
            return True, industry
    
    return False, None

def calculate_fcf_yield(financial_data):
    """
    估算FCF收益率（简化版）
    由于数据限制，使用：经营现金流 / 市值
    """
    if not financial_data:
        return None
    
    ocf = financial_data.get('operating_cash_flow')
    
    if ocf and ocf > 0:
        return ocf  # 返回绝对值，后续结合市值计算
    
    return None

def screen_stocks(output_file=None):
    """
    主筛选函数
    """
    print("="*60)
    print("🚀 港股金龟筛选器启动")
    print(f"⏰ 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # 1. 获取基础列表
    base_df = get_hk_stock_list()
    
    if base_df.empty:
        print("❌ 未能获取数据，请检查网络连接")
        return pd.DataFrame()
    
    print(f"\n📋 开始筛选 {len(base_df)} 只港股...")
    print(f"📏 筛选标准: PB<{SCREENING_CONFIG['pb_max']}, PE<{SCREENING_CONFIG['pe_max']}, 股息率>{SCREENING_CONFIG['dividend_yield_min']}%")
    print("-"*60)
    
    results = []
    excluded_count = {
        'pb': 0,
        'pe': 0,
        'dividend': 0,
        'industry': 0,
        'data_error': 0,
    }
    
    # 2. 遍历筛选
    for idx, row in base_df.iterrows():
        code = row.get('代码', '')
        name = row.get('名称', '')
        
        # 获取基础指标
        try:
            pb = float(row.get('市净率', 999)) if row.get('市净率') else 999
            pe = float(row.get('市盈率', 999)) if row.get('市盈率') else 999
            dividend = float(row.get('股息率', 0).replace('%', '')) if row.get('股息率') else 0
        except:
            excluded_count['data_error'] += 1
            continue
        
        # 检查排除行业
        should_exclude, industry = should_exclude_industry(name)
        if should_exclude:
            excluded_count['industry'] += 1
            continue
        
        # 基础指标筛选
        if pb >= SCREENING_CONFIG['pb_max']:
            excluded_count['pb'] += 1
            continue
            
        if pe >= SCREENING_CONFIG['pe_max'] or pe <= 0:
            excluded_count['pe'] += 1
            continue
            
        if dividend < SCREENING_CONFIG['dividend_yield_min']:
            excluded_count['dividend'] += 1
            continue
        
        # 判断央国企背景
        is_soe, soe_reason = is_likely_central_soe(code, name)
        
        # 获取详细财务数据（可选，深度分析时用）
        print(f"  🔍 深度分析: {name}({code}) PB={pb:.2f} PE={pe:.1f} 股息={dividend:.1f}%")
        financial_data = get_stock_financial_data(code, name)
        
        # 计算FCF相关（简化）
        fcf_estimate = None
        if financial_data and financial_data.get('operating_cash_flow'):
            fcf_estimate = financial_data['operating_cash_flow']
        
        # 构建结果
        result = {
            '代码': code,
            '名称': name,
            'PB': round(pb, 2),
            'PE': round(pe, 1),
            '股息率(%)': round(dividend, 2),
            '最新价': row.get('最新价', 'N/A'),
            '涨跌幅(%)': row.get('涨跌幅', 'N/A'),
            '央国企': '✅' if is_soe else '⚠️',
            '央国企判断': soe_reason,
            '估算经营现金流(亿)': fcf_estimate if fcf_estimate else 'N/A',
        }
        
        results.append(result)
        
        # 每10个显示进度
        if len(results) % 10 == 0:
            print(f"  📊 已发现 {len(results)} 只候选标的")
    
    # 3. 整理结果
    print("-"*60)
    print(f"✅ 筛选完成！")
    print(f"   总计检查: {len(base_df)} 只")
    print(f"   符合条件: {len(results)} 只")
    print(f"   排除原因: PB不合格({excluded_count['pb']}), PE不合格({excluded_count['pe']}), "
          f"股息率低({excluded_count['dividend']}), 排除行业({excluded_count['industry']}), "
          f"数据错误({excluded_count['data_error']})")
    
    if not results:
        print("⚠️ 未找到符合条件的标的，请放宽筛选条件重试")
        return pd.DataFrame()
    
    result_df = pd.DataFrame(results)
    
    # 4. 排序（优先央国企，再按综合评分）
    result_df['央国企排序'] = result_df['央国企'].apply(lambda x: 0 if x == '✅' else 1)
    result_df['综合评分'] = (
        result_df['央国企排序'] * 10 +  # 央国企优先
        result_df['PB'] * 5 +           # PB越低越好
        (10 - result_df['股息率(%)'])   # 股息率越高越好
    )
    result_df = result_df.sort_values('综合评分').reset_index(drop=True)
    result_df = result_df.drop(columns=['央国企排序', '综合评分'])
    
    # 5. 输出结果
    print("\n" + "="*60)
    print("📈 候选标的列表（按投资吸引力排序）")
    print("="*60)
    print(result_df.to_string(index=False))
    
    # 6. 分类输出
    print("\n" + "="*60)
    print("🏆 金龟候选（央国企+PB<0.6+股息率>5%）")
    print("="*60)
    golden_turtles = result_df[
        (result_df['央国企'] == '✅') & 
        (result_df['PB'] < 0.6) & 
        (result_df['股息率(%)'] > 5.0)
    ]
    if not golden_turtles.empty:
        print(golden_turtles[['代码', '名称', 'PB', 'PE', '股息率(%)', '央国企判断']].to_string(index=False))
        print(f"\n共 {len(golden_turtles)} 只金龟级标的")
    else:
        print("暂无符合金龟标准的标的")
    
    print("\n" + "="*60)
    print("🥈 银龟候选（其他符合基础标准的标的）")
    print("="*60)
    silver_turtles = result_df[
        ~((result_df['央国企'] == '✅') & 
          (result_df['PB'] < 0.6) & 
          (result_df['股息率(%)'] > 5.0))
    ]
    if not silver_turtles.empty:
        print(silver_turtles[['代码', '名称', 'PB', 'PE', '股息率(%)', '央国企']].head(20).to_string(index=False))
        if len(silver_turtles) > 20:
            print(f"... 及其他 {len(silver_turtles) - 20} 只标的")
    
    # 7. 保存到文件
    if output_file:
        result_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n💾 结果已保存到: {output_file}")
    
    # 8. 生成AI分析用的提示词
    print("\n" + "="*60)
    print("🤖 AI深度分析提示词（复制使用）")
    print("="*60)
    
    top_10_codes = result_df.head(10)['代码'].tolist()
    top_10_names = result_df.head(10)['名称'].tolist()
    
    stock_list = ", ".join([f"{name}({code})" for code, name in zip(top_10_codes, top_10_names)])
    
    prompt = f"""
我使用"个股分析标准模版V5.5.6"进行港股投资。

已通过初筛的候选标的：
{stock_list}

请对以上标的进行【5分钟快速初筛】分析，按模板第一章1.5节的四步筛选法：
1. 地缘政治核查（非洲/冲突区资产>10%？一票否决）
2. 价格位置检查（距52周高点<30%？）
3. 负债快速扫描（财务费用>5亿？）
4. 现金覆盖率检查（现金<市值20%？）

输出格式（表格）：
| 代码 | 名称 | 地缘政治 | 价格位置 | 负债扫描 | 现金覆盖 | 初筛结论 |
|------|------|---------|---------|---------|---------|---------|

对通过初筛的标的，再进行【深度分析】，重点计算：
- 剔除净现金FCF倍数（核心指标）
- 流派判定（纯硬收息型/价值发现型/关联方资源型/烟蒂股型）
- 买点计算（FCF倍数<5倍可建仓）
- 持仓状态标签（🟢正常/🔵已回本/🟡高位/🟠关注/🔴遗留）
"""
    print(prompt)
    
    return result_df

def main():
    """
    主函数
    """
    print("\n")
    
    # 设置输出文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"hk_candidates_{timestamp}.csv"
    
    # 执行筛选
    results = screen_stocks(output_file=output_file)
    
    if not results.empty:
        print("\n" + "="*60)
        print("✨ 筛选完成！建议操作：")
        print("="*60)
        print("1. 查看上方【金龟候选】列表，这些是最佳候选")
        print("2. 复制【AI深度分析提示词】到AI对话中")
        print(f"3. 详细数据已保存到: {output_file}")
        print("4. 对AI分析后的最终候选，务必人工复核年报数据（S级数据源）")
        print("="*60)
    
    return results

if __name__ == "__main__":
    main()
