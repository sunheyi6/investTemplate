# VIX定投策略自动更新系统 V2.0

## 概述

本系统自动获取VIX恐慌指数和纳指100 ETF（513110）的价格数据，每日更新VIX定投策略的收益情况。

**核心逻辑**：
- 使用**昨日美股收盘后的VIX数据**，指导今日A股ETF的定投操作
- 每日A股收盘后自动更新ETF收盘价和持仓收益
- 定投日（每双周周二）根据完整策略执行：基础档位 → 趋势修正 → 封顶 → 风控 → 卖出 → 回流

**策略版本**：V2.0（原策略·最终版）

---

## 策略规则速查

### 买入规则（按顺序执行）

| 步骤 | 规则 | 说明 |
|:---|:---|:---|
| 1. 基础档位 | VIX<15:0 / 15-18:1000 / 18-20:1500 / 20-25:3000 / 25-30:4500 / 30-35:6000 / ≥35:6000 | 根据VIX区间确定基础金额 |
| 2. 趋势修正 | 恐慌加剧(>均值): ×0.7 / 恐慌消退(<均值): ×1.3 / 稳定(差≤0.5): ×1.0 | 基于前两个双周周二VIX均值 |
| 3. 封顶处理 | VIX≥30时，修正后金额≤6000 | 即使×1.3后超出，也只买6000 |
| 4. 极端风控 | VIX≥35且>均值 → 暂停买入+减仓5% | 优先于一切买入操作 |

### 卖出规则

| 条件 | 减仓比例 |
|:---|:---:|
| 连续2期 VIX < 15 | 10% |
| 连续2期 VIX < 12 | 15%（累计） |
| 连续2期 VIX < 10 | 25%（累计） |

- 累计减仓不超过40%（永留60%底仓）
- 减仓资金进入资金池，后续回流接回

### 回流规则

| 触发条件 | 买回比例 |
|:---|:---:|
| VIX 重新 ≥ 25 | 50% |
| VIX 重新 ≥ 30 | 剩余50% |

- 回流不占用当期买入封顶额度
- 与当期定投一同在双周周二执行

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `scripts/auto_update_vix_dca.py` | 自动更新脚本 V2.0 |
| `.github/workflows/vix_dca_daily_update.yml` | GitHub Actions工作流 |
| `decision-tracking/vix_dca_strategy/strategy_config.json` | 策略配置（档位、修正、风控参数） |
| `decision-tracking/vix_dca_strategy/state.json` | 策略状态数据 |
| `decision-tracking/vix_dca_strategy/dashboard_data.json` | 仪表板数据 |
| `decision-tracking/vix_dca_strategy/daily_snapshot.csv` | 每日快照记录 |
| `decision-tracking/vix_dca_strategy/trades.csv` | 交易记录 |
| `portfolio/VIX定投策略.md` | 网页展示文档 |
| `public/vix_strategy/dashboard_data.json` | 网页数据源 |

---

## 本地使用

### 基本用法（自动获取数据）

```bash
python scripts/auto_update_vix_dca.py
```

### 手动指定数据

```bash
# 指定今日数据
python scripts/auto_update_vix_dca.py --date 2026-05-05 --vix 22.50 --price 2.20

# 试运行（不保存）
python scripts/auto_update_vix_dca.py --dry-run

# 强制更新（即使今天已更新）
python scripts/auto_update_vix_dca.py --force
```

---

## GitHub Actions 定时执行

### 执行时间

- **北京时间**: 每天 15:30 ~ 15:40（A股收盘后）
- **UTC时间**: 每天 07:30 ~ 07:40
- **执行日**: 周一到周五（工作日）

### 手动触发

在 GitHub 仓库页面：
1. 进入 Actions 标签
2. 选择 "VIX定投策略每日更新"
3. 点击 "Run workflow"
4. 可选：指定日期、VIX值、价格，或强制更新

---

## 数据源

| 数据 | 来源 | 说明 |
|------|------|------|
| VIX指数 | Yahoo Finance (^VIX) | 美股波动率指数 |
| ETF价格 | akshare (东方财富) | 纳指100 ETF (513110) |

---

## 更新逻辑

### 每日更新（无论是否定投日）

1. 获取今日VIX
2. 获取今日ETF收盘价
3. 计算持仓市值和收益
4. 更新 `state.json`
5. 更新 `dashboard_data.json`
6. 记录每日快照到 `daily_snapshot.csv`
7. 更新 `VIX定投策略.md` 文档
8. 同步到 `public/vix_strategy/`

### 定投日额外操作

如果今天是定投日（每双周周二），按以下顺序执行：

```
1. 记录本期VIX到历史日志
2. 极端风控检查（VIX≥35且上升？→ 暂停+减仓5%）
3. 基础档位计算
4. 趋势修正（×0.7 / ×1.3 / ×1.0）
5. 封顶处理（VIX≥30时≤6000）
6. 卖出检查（连续2期低VIX？→ 减仓）
7. 回流检查（VIX重新≥25/30？→ 买回）
8. 执行基础买入
```

---

## 故障排查

### 问题：自动获取数据失败

**解决方案**：手动指定数据

```bash
python scripts/auto_update_vix_dca.py --vix 29.50 --price 2.35
```

### 问题：今天已更新，但需要重新更新

**解决方案**：使用 `--force` 参数

```bash
python scripts/auto_update_vix_dca.py --force
```

### 问题：GitHub Actions 执行失败

检查步骤：
1. 查看 Actions 日志
2. 确认依赖安装成功
3. 检查数据源是否可用
4. 尝试手动触发并指定参数

---

## 定投日历（2026年）

| 日期 | 状态 | 说明 |
|------|------|------|
| 2026-03-24 | ✅ 已执行 | 初始建仓（标准定投，VIX=21.0） |
| 2026-04-07 | ✅ 已执行 | 标准定投（VIX=19.5） |
| 2026-05-05 | ⏳ 待定 | 下次定投日 |
| 2026-05-19 | ⏳ 待定 | 双周定投 |
| 2026-06-02 | ⏳ 待定 | 双周定投 |

---

## 注意事项

1. **VIX数据时效性**：使用昨日美股收盘后的VIX数据
2. **ETF价格**：使用今日A股收盘后513110价格
3. **交易日**：定投日如遇节假日顺延
4. **数据备份**：Git历史自动备份所有数据变化
5. **策略状态**：state.json 中 `strategy_state` 字段跟踪VIX历史、减仓比例、回流状态等，请勿手动修改

---

**版本**: V2.0（原策略·最终版）  
**最后更新**: 2026-04-29
