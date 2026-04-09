# 06-模拟组合管理

> 数据硬约束、一致性原则、常见错误修复

---

## 目标

根治模拟持仓数据反复出错的问题，建立**不可违背**的数据一致性保障机制。

---

## 问题历史

| 时间 | 问题 | 影响 | 根本原因 |
|------|------|------|----------|
| 2026-03-30 | 天津发展持仓被清零 | 少算10万市值 | ticker格式不一致导致识别失败 |
| 2026-03-30 | 成本价不一致 | 收益率计算错误(-10% vs +1%) | state和trades.csv初始化逻辑分离 |
| 2026-03-30 | 现金计算错误 | 仓位比例失真 | START_CASH硬编码，未根据实际交易计算 |
| 2026-04-09 | 网页显示错误成本价 | 盈亏计算错误 | `public/dashboard/dashboard_snapshot.json` 未同步更新 |
| 2026-04-09 | 历史操作记录不显示 | 操作流水空白 | `dashboard_snapshot.json` 缺少 `recent_actions` 字段 |
| 2026-04-09 | VIX策略网页数据未更新 | 网页显示旧收益 | 更新数据后未同步 `public/vix_strategy/dashboard_data.json` |

---

## 硬约束原则

### 1. 单一真相源原则

**唯一权威数据源**：`08-决策追踪/simulation_trades.csv`

```
所有持仓数据必须以trades.csv为准：
- 成本价 = trades.csv中的成交价格
- 持股数 = trades.csv中的成交股数净额
- 现金 = 初始资金 - trades.csv中所有买入金额 + 所有卖出金额
- code = trades.csv中的code列（必须是5位字符串，保留前导0）
```

**禁止行为**：
- ❌ 在代码中硬编码成本价、持股数、现金
- ❌ 多个地方维护同一份数据
- ❌ 直接修改state.json而不更新trades.csv

### 2. 强制验证原则

**每次运行前必须验证**：

```bash
python scripts/validate_simulation_data.py
```

**验证项**：
1. trades.csv结构完整（必须有code列）
2. state.json与trades.csv数据一致
3. 所有持仓字段完整（name, code, ticker, shares, avg_cost, sell_trigger, lot_size）
4. 现金计算正确

**失败处理**：
- 验证失败时脚本返回退出码1，主程序停止运行
- 必须人工修复后才能继续

### 3. 备份优先原则

**修改state前自动备份**：

```python
# 每次更新state前自动创建时间戳备份
simulation_state.json.20260330_214921.bak
```

**恢复方式**：
```bash
cp simulation_state.json.20260330_214921.bak simulation_state.json
```

### 4. 只读验证脚本

**validate_simulation_data.py 只检测不修改**：

| 行为 | 允许？ |
|------|--------|
| 读取state.json | ✅ 允许 |
| 读取trades.csv | ✅ 允许 |
| 打印问题报告 | ✅ 允许 |
| 自动修改数据 | ❌ 禁止 |

**所有数据修复必须由人工确认后执行**

### 5. 多文件数据一致性原则（V5.5.14新增）⭐⭐⭐⭐⭐

**问题案例**：
- 2026-04-09：网页显示错误成本价（0.365 vs 0.295），发现 `public/dashboard/dashboard_snapshot.json` 未同步更新
- 根因：VitePress 网页组件从 `public/dashboard/dashboard_snapshot.json` 读取数据，而非 `08-决策追踪/dashboard_snapshot.json`

**强制性要求**：

修改模拟持仓数据时，**必须同时更新以下所有文件**，保持数据完全一致：

```
修改数据源
    ├── 1️⃣ 08-决策追踪/simulation_trades.csv      (唯一真相源)
    ├── 2️⃣ 08-决策追踪/simulation_state.json       (运行时状态)
    ├── 3️⃣ 08-决策追踪/dashboard_snapshot.json     (决策追踪目录)
    └── 4️⃣ public/dashboard/dashboard_snapshot.json  (VitePress网页数据源)  ⭐ 容易遗漏！
```

**更新后验证清单**：
- [ ] `simulation_trades.csv` - 成本价、股数、现金正确
- [ ] `simulation_state.json` - 与 trades.csv 一致
- [ ] `08-决策追踪/dashboard_snapshot.json` - 数据已更新
- [ ] **`public/dashboard/dashboard_snapshot.json`** - 数据已同步 ⭐
- [ ] 网页刷新后显示正确

### 6. VIX定投策略数据一致性（V5.5.14新增）⭐⭐⭐⭐⭐

**策略特点**：
- 买卖：每两周周二执行
- 收益：每日更新
- 网页展示：独立页面 `模拟持仓/VIX定投策略.md`

**数据文件清单**：

| 序号 | 文件路径 | 用途 | 更新频率 |
|------|----------|------|----------|
| 1 | `08-决策追踪/vix_dca_strategy/trades.csv` | 交易记录（仅定投日） | 每两周一次 |
| 2 | `08-决策追踪/vix_dca_strategy/daily_snapshot.csv` | 每日收益快照 | **每天** |
| 3 | `08-决策追踪/vix_dca_strategy/state.json` | 当前持仓状态 | **每天** |
| 4 | `08-决策追踪/vix_dca_strategy/dashboard_data.json` | 汇总数据 | **每天** |
| 5 | `模拟持仓/VIX定投策略.md` | **网页展示页面** | **每天** ⭐ |
| 6 | `public/vix_strategy/dashboard_data.json` | 网页数据源 | **每天** ⭐ |

**强制性要求**：

> **更新VIX策略数据时，必须同时更新网页展示文件！**

```
每日更新流程：
    ├── 1️⃣ 执行脚本更新数据
    │       python scripts/update_vix_dca.py --date YYYY-MM-DD --vix XX.X --price XX.XX
    │
    ├── 2️⃣ 更新网页展示页面（必须手动！）
    │       编辑 模拟持仓/VIX定投策略.md
    │       - 更新"当前收益"表格
    │       - 更新"收益走势"表格
    │       - 更新"关键指标"
    │
    └── 3️⃣ 同步网页数据文件（必须！）
            copy 08-决策追踪\vix_dca_strategy\dashboard_data.json public\vix_strategy\dashboard_data.json
```

**更新后验证清单**：
- [ ] `daily_snapshot.csv` - 今日收益已记录
- [ ] `state.json` - 当前收益、市值已更新
- [ ] **`模拟持仓/VIX定投策略.md`** - 网页显示数据已更新 ⭐
- [ ] **`public/vix_strategy/dashboard_data.json`** - 网页数据源已同步 ⭐
- [ ] 网页刷新后显示最新收益

**常见错误**：
```
❌ 错误：只更新数据文件，不更新网页展示页面
❌ 错误：更新数据后未同步 public/ 目录
❌ 错误：网页上的收益数字与实际不符

✅ 正确：数据文件、网页页面、public目录三处同步更新
```

---

## 关键文件说明

| 文件 | 用途 | 修改方式 |
|------|------|----------|
| `simulation_trades.csv` | **唯一真相源**，所有交易记录 | 脚本自动追加，人工可查看 |
| `simulation_state.json` | 运行时状态缓存，从trades重建 | **禁止直接修改** |
| `simulation_daily_snapshot.csv` | 每日持仓快照，用于回溯 | 脚本自动追加 |
| `dashboard_snapshot.json` | Dashboard展示数据 | 脚本自动生成 |

---

## 数据结构要求

### dashboard_snapshot.json 必须字段

```json
{
  "meta": {
    "template_version": "V5.5.14",
    "engine_version": "V3.1",
    "generated_at": "2026-04-09",
    "latest_trade_date": "2026-04-09"
  },
  "portfolio": {
    "initial_capital": 500000.0,
    "cash": 109160.0,
    "market_value": 404500.0,
    "net_value": 513660.0,
    "total_return_pct": 2.732,
    "position_ratio_pct": 78.8,
    "positions": [...]
  },
  "today_actions": [],           // 今日操作（可空）
  "recent_actions": [...]        // 最近操作流水（**必须！**）
}
```

### recent_actions 格式

```json
{
  "date": "2026-03-26",
  "ticker": "1522.HK",
  "name": "京投交通科技",
  "action": "INIT_BUY",
  "price": 0.295,
  "shares": 342000,
  "amount": 100890.0,
  "reason": "初始建仓（3月26日收盘价）"
}
```

---

## 数据修复SOP

当发现数据不一致时：

```
1. 立即停止：不要运行主脚本
2. 运行验证：python scripts/validate_simulation_data.py
3. 查看问题：根据报告定位具体问题
4. 决定方案：
   - 如果是trades.csv错误 → 修正trades.csv
   - 如果是state.json错误 → 删除state.json，让脚本从trades.csv重建
5. 重新验证：确保问题已解决
6. 恢复运行：再次执行主脚本
```

---

## 常见错误及修复

### 错误1：code不一致
```
[FAIL] code不一致: 1522.HK state=01522, trades=1522
```
**原因**：trades.csv中code列被识别为数字，前导0丢失
**修复**：确保 trades.csv 中 code 是字符串（带前导0）

### 错误2：成本价不一致
```
[FAIL] 成本价不一致: 0882.HK state=2.50, trades=2.55
```
**修复**：
1. 确认trades.csv中的价格是正确的实际成交价
2. 删除state.json让脚本重建

### 错误3：持仓缺失
```
[FAIL] 持仓缺失: 3320.HK 有交易记录但无持仓
```
**原因**：ticker格式不一致导致识别失败
**修复**：
1. 统一所有ticker格式（港股为4位数字，如0882.HK）
2. 检查state.json中的ticker是否与trades.csv一致

### 错误4：网页显示错误数据
**现象**：文件改了但网页显示不对
**原因**：`public/dashboard/dashboard_snapshot.json` 未同步
**修复**：同时更新 `08-决策追踪/` 和 `public/dashboard/` 下的文件

### 错误5：历史操作记录不显示
**现象**："今日操作"页面只显示"今日无自动操作"，最近操作流水空白
**原因**：`dashboard_snapshot.json` 缺少 `recent_actions` 字段
**修复**：添加 `recent_actions` 数组，包含历史操作记录

---

## 新增/修改标的流程

```
1. 停止自动脚本
2. 在 trades.csv 中手动添加 INIT_BUY 记录
3. 确保包含所有列：date,ticker,name,code,action,price,shares,amount,cash_after,reason
4. code必须是5位字符串（如"01522"）
5. 删除 state.json（让脚本重建）
6. 运行验证脚本确认无误
7. 恢复自动脚本
```

---

## 检查命令速查

```bash
# 检查 dashboard_snapshot.json 是否包含 recent_actions
grep -q "recent_actions" public/dashboard/dashboard_snapshot.json && echo "OK" || echo "缺少 recent_actions!"

# 比较两个目录的 dashboard_snapshot.json 是否一致
diff 08-决策追踪/dashboard_snapshot.json public/dashboard/dashboard_snapshot.json

# 查看 trades.csv 内容
cat 08-决策追踪/simulation_trades.csv

# 验证数据一致性
python scripts/validate_simulation_data.py
```
