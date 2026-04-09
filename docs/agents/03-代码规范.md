# 03-代码规范

> Python脚本、GitHub Actions、YAML配置规范

---

## Python脚本规范

### 文件头模板

```python
# -*- coding: utf-8 -*-
"""
脚本名称 V{版本号} (V{模板版本}版)
功能简述

作者: AI助手
创建日期: YYYY-MM-DD
最后更新: YYYY-MM-DD

使用方式:
    python scripts/脚本名.py [参数]

依赖:
    - pandas
    - akshare
    - (其他依赖)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# 配置集中管理
SCREENING_CONFIG = {
    "version": "V5.5.14",
    "criteria": {
        "pb_max": 0.6,
        "dividend_yield_min": 0.06,
        "fcf_multiple_max": 3.0,
    }
}

# 项目根目录
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """主函数"""
    pass


if __name__ == "__main__":
    sys.exit(main())
```

### 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块名 | 小写+下划线 | `hk_stock_screener.py` |
| 函数名 | 小写+下划线 | `fetch_stock_data()` |
| 常量 | 大写+下划线 | `INITIAL_CAPITAL = 500000` |
| 类名 | 大驼峰 | `PortfolioManager` |
| 私有 | 下划线前缀 | `_internal_helper()` |

### 错误处理

```python
try:
    data = fetch_data()
except Exception as e:
    print(f"[ERROR] 获取数据失败: {e}")
    sys.exit(1)
```

---

## GitHub Actions规范

### 工作流文件位置
`.github/workflows/*.yml`

### 模板

```yaml
name: 工作流名称

on:
  schedule:
    # 香港时间 16:30 = UTC 08:30
    - cron: '30 8 * * 1-5'
  workflow_dispatch:

jobs:
  job_name:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          
      - name: Install dependencies
        run: |
          pip install pandas akshare yfinance
          
      - name: Run script
        run: python scripts/script_name.py
        
      - name: Commit changes
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git add -A
          git diff --quiet && git diff --staged --quiet || git commit -m "自动更新数据"
          git push
```

---

## YAML配置规范

### 文件头

```yaml
# 配置名称 V{版本号}
# 最后更新: YYYY-MM-DD
# 说明: 配置用途简述
```

### 结构示例

```yaml
version: "V5.5.14"

# 仓位限制规则
position_limits:
  core_position_pct: 10        # 核心仓位上限(%)
  satellite_position_pct: 5    # 卫星仓位上限(%)
  single_stock_max_pct: 20     # 单只个股上限(%)

# 止损规则
stop_loss:
  hard_stop_pct: -15           # 硬止损线(%)
  trailing_stop_pct: -10       # 移动止损(%)
  time_stop_days: 90           # 时间止损(天)

# 流动性限制
liquidity:
  min_daily_volume_hkd: 500000  # 最低日成交额(港元)
  max_position_impact_pct: 5    # 最大冲击成本(%)
```

### 注释规范

- 使用**中文注释**
- 注释与配置项同行或上一行
- 数字必须带单位说明

---

## 文件路径规范

### 项目根目录引用

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # scripts/的上级是项目根目录

# 文件路径
STATE_FILE = ROOT / "08-决策追踪" / "simulation_state.json"
TRADES_FILE = ROOT / "08-决策追踪" / "simulation_trades.csv"
```

### 路径常量

```python
# 决策追踪目录
TRACKING_DIR = ROOT / "08-决策追踪"

# 分析输出目录
OUTPUT_DIR = ROOT / "07-分析输出"

# 模拟持仓目录
PORTFOLIO_DIR = ROOT / "模拟持仓"

# 公共目录（VitePress）
PUBLIC_DIR = ROOT / "public"
```

---

## 日志与输出规范

### 输出格式

```python
# 信息
print("[INFO] 正常信息")

# 警告
print("[WARN] 警告信息")

# 错误
print("[ERROR] 错误信息")

# 成功
print("[OK] 操作成功")
```

### 进度显示

```python
import time

for i, item in enumerate(items):
    print(f"处理中... {i+1}/{len(items)}", end='\r')
    process(item)
print()  # 换行
```

---

## 依赖管理

### requirements.txt

```
# 核心依赖
pandas>=2.0.0
akshare>=1.12.0
yfinance>=0.2.0

# 数据可视化
matplotlib>=3.7.0

# 工具
python-dotenv>=1.0.0
```

### 安装命令

```bash
pip install -r requirements.txt
```
