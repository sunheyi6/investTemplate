<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { withBase } from 'vitepress'

const props = defineProps({
  mode: {
    type: String,
    default: 'home'
  }
})

const loading = ref(true)
const error = ref('')
const data = ref(null)

const showHome = computed(() => props.mode === 'home')
const showPositions = computed(() => props.mode === 'positions')
const showToday = computed(() => props.mode === 'today')
const showDecisions = computed(() => props.mode === 'decisions')
const showFullHeader = computed(() => showHome.value)
const investedCost = computed(() => {
  const list = positions.value || []
  return list.reduce((sum, p) => sum + Number(p.avg_cost || 0) * Number(p.shares || 0), 0)
})

const money = (n) =>
  new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(Number(n || 0))

const humanHKD = (n) => {
  const v = Math.round(Number(n || 0))
  const wan = Math.floor(v / 10000)
  const rest = v % 10000
  if (wan <= 0) return `${rest.toLocaleString('zh-CN')}元`
  if (rest === 0) return `${wan}万元`
  return `${wan}万${rest.toLocaleString('zh-CN')}元`
}

const pct = (n, digits = 2) => {
  const v = Number(n || 0)
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`
}
const holdingPct = (p) => {
  const cost = Number(p.avg_cost || 0)
  const close = Number(p.close || 0)
  if (!cost) return 0
  return ((close / cost) - 1) * 100
}

const actionLabel = (a) => {
  if (a === 'BUY_ADD') return '加仓'
  if (a === 'SELL') return '卖出'
  if (a === 'INIT_BUY') return '建仓'
  return a || '-'
}

const todayHasAction = computed(() => (data.value?.today_actions || []).length > 0)
const positions = computed(() => data.value?.portfolio?.positions || [])
const decisionRows = computed(() => data.value?.ai_decisions?.table_rows || [])
const decisionGroups = computed(() => {
  const groups = {
    green: [],
    yellow: [],
    red: [],
    other: []
  }
  for (const r of decisionRows.value) {
    const status = `${r.status || ''}`.toLowerCase()
    const action = `${r.action || ''}`.toLowerCase()
    if (
      status.includes('🟢') ||
      status.includes('正确') ||
      action.includes('买入') ||
      action.includes('加仓')
    ) {
      groups.green.push(r)
    } else if (
      status.includes('🔴') ||
      status.includes('错误') ||
      status.includes('回避') ||
      action.includes('卖出')
    ) {
      groups.red.push(r)
    } else if (
      status.includes('🟡') ||
      status.includes('待验证') ||
      action.includes('观望') ||
      action.includes('持有')
    ) {
      groups.yellow.push(r)
    } else {
      groups.other.push(r)
    }
  }
  return groups
})

function appLink(path) {
  return withBase(path)
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const candidates = [
      withBase('/dashboard/dashboard_snapshot.json'),
      withBase('/08-决策追踪/dashboard_snapshot.json')
    ]
    let lastStatus = '404'
    for (const url of candidates) {
      const res = await fetch(url, { cache: 'no-store' })
      if (res.ok) {
        data.value = await res.json()
        loading.value = false
        return
      }
      lastStatus = String(res.status)
    }
    throw new Error(`HTTP ${lastStatus}`)
  } catch (e) {
    error.value = `加载失败：${e instanceof Error ? e.message : '未知错误'}`
  } finally {
    loading.value = false
  }
}

onMounted(loadData)

onMounted(() => {
  document.body.classList.add('dashboard-wide')
})

onBeforeUnmount(() => {
  document.body.classList.remove('dashboard-wide')
})
</script>

<template>
  <div class="decision-dashboard">
    <div class="dd-header">
      <p v-if="showFullHeader">持仓/操作/决策记录统一来自同一数据快照。</p>
      <p v-else>查看明细页面（总览信息已收敛到“模拟持仓/总览”）。</p>
      <button class="dd-refresh" @click="loadData">刷新数据</button>
    </div>

    <div v-if="loading" class="dd-loading">加载中...</div>
    <div v-else-if="error" class="dd-error">{{ error }}</div>
    <template v-else>
      <div class="dd-meta" v-if="showFullHeader">
        <span>交易日：{{ data.meta.latest_trade_date }}</span>
        <span>更新时间：{{ data.meta.generated_at }}</span>
      </div>

      <div class="dd-kpis" v-if="showFullHeader">
        <div class="dd-card">
          <div class="dd-label">组合净值</div>
          <div class="dd-value">{{ money(data.portfolio.net_value) }} HKD</div>
        </div>
        <div class="dd-card">
          <div class="dd-label">累计收益率</div>
          <div
            class="dd-value"
            :class="{ up: data.portfolio.total_return_pct >= 0, down: data.portfolio.total_return_pct < 0 }"
          >
            {{ pct(data.portfolio.total_return_pct, 2) }}
          </div>
        </div>
        <div class="dd-card">
          <div class="dd-label">现金余额</div>
          <div class="dd-value">{{ money(data.portfolio.cash) }} HKD</div>
        </div>
        <div class="dd-card">
          <div class="dd-label">仓位比例</div>
          <div class="dd-value">{{ pct(data.portfolio.position_ratio_pct, 2) }}</div>
        </div>
      </div>

      <div class="dd-banner" v-if="showFullHeader" :class="todayHasAction ? 'warn' : 'ok'">
        <template v-if="todayHasAction">
          今日发生 {{ data.today_actions.length }} 笔自动操作，请重点复盘执行逻辑。
        </template>
        <template v-else> 今日无自动操作（仅监控，不调仓）。 </template>
      </div>

      <div v-if="!showFullHeader" class="dd-subsummary">
        <span>净值 {{ money(data.portfolio.net_value) }} HKD</span>
        <span :class="{ up: data.portfolio.total_return_pct >= 0, down: data.portfolio.total_return_pct < 0 }">
          收益 {{ pct(data.portfolio.total_return_pct, 2) }}
        </span>
        <span>现金 {{ money(data.portfolio.cash) }} HKD</span>
        <a :href="appLink('/模拟持仓/')">返回总览</a>
      </div>

      <section v-if="showHome" class="dd-panel">
        <div class="dd-plain-summary">
          <strong>一句话看懂：</strong>
          已投入约 <strong>{{ humanHKD(investedCost) }}</strong>，
          当前市值约 <strong>{{ humanHKD(data.portfolio.market_value) }}</strong>，
          剩余现金约 <strong>{{ humanHKD(data.portfolio.cash) }}</strong>（港元）。
        </div>
        <h3>模块导航</h3>
        <div class="dd-home-links">
          <a :href="appLink('/模拟持仓/持仓')" class="dd-home-link">持仓</a>
          <a :href="appLink('/模拟持仓/今日操作')" class="dd-home-link">今日操作</a>
          <a :href="appLink('/模拟持仓/决策记录')" class="dd-home-link">决策记录</a>
        </div>
      </section>

      <section v-if="showPositions" class="dd-panel">
        <h3>当前真实持仓</h3>
        <table>
          <thead>
            <tr>
              <th>标的</th>
              <th>代码</th>
              <th>股数</th>
              <th>成本价</th>
              <th>现价</th>
              <th>当日涨跌%</th>
              <th>持仓收益率%</th>
              <th>仓位占比</th>
              <th>浮盈亏</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in positions" :key="p.ticker">
              <td>{{ p.name }}</td>
              <td>{{ p.code }}</td>
              <td>{{ p.shares.toLocaleString('zh-CN') }}</td>
              <td>{{ Number(p.avg_cost).toFixed(3) }}</td>
              <td>{{ Number(p.close).toFixed(3) }}</td>
              <td :class="{ up: p.change_pct >= 0, down: p.change_pct < 0 }">{{ pct(p.change_pct, 2) }}</td>
              <td :class="{ up: holdingPct(p) >= 0, down: holdingPct(p) < 0 }">{{ pct(holdingPct(p), 2) }}</td>
              <td>{{ pct(p.weight_pct, 2) }}</td>
              <td :class="{ up: p.unrealized >= 0, down: p.unrealized < 0 }">{{ money(p.unrealized) }}</td>
              <td>{{ p.status }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-if="showToday" class="dd-panel">
        <h3>今日操作流水</h3>
        <div v-if="!todayHasAction" class="dd-empty">今日无自动操作。</div>
        <table v-else>
          <thead>
            <tr>
              <th>日期</th>
              <th>标的</th>
              <th>动作</th>
              <th>价格</th>
              <th>股数</th>
              <th>金额(HKD)</th>
              <th>原因</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(a, idx) in data.today_actions" :key="`${a.date}-${a.ticker}-${idx}`">
              <td>{{ a.date }}</td>
              <td>{{ a.name }}</td>
              <td>{{ actionLabel(a.action) }}</td>
              <td>{{ Number(a.price).toFixed(3) }}</td>
              <td>{{ Number(a.shares).toLocaleString('zh-CN') }}</td>
              <td>{{ money(a.amount) }}</td>
              <td>{{ a.reason || '-' }}</td>
            </tr>
          </tbody>
        </table>

        <h4 style="margin-top: 16px">最近操作流水（最多20条）</h4>
        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>标的</th>
              <th>动作</th>
              <th>价格</th>
              <th>股数</th>
              <th>金额(HKD)</th>
              <th>原因</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(a, idx) in data.recent_actions" :key="`recent-${a.date}-${a.ticker}-${idx}`">
              <td>{{ a.date }}</td>
              <td>{{ a.name }}</td>
              <td>{{ actionLabel(a.action) }}</td>
              <td>{{ Number(a.price).toFixed(3) }}</td>
              <td>{{ Number(a.shares).toLocaleString('zh-CN') }}</td>
              <td>{{ money(a.amount) }}</td>
              <td>{{ a.reason || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-if="showDecisions" class="dd-panel">
        <h3>AI决策记录（只读）</h3>
        <div v-if="decisionRows.length > 0" class="decision-stream">
          <div class="decision-group group-green">
            <h4>🟢 正向建议</h4>
            <div v-if="decisionGroups.green.length === 0" class="dd-empty">暂无</div>
            <div v-else class="decision-cards">
              <article v-for="(r, idx) in decisionGroups.green" :key="`g-${idx}`" class="decision-card card-green">
                <div class="card-top">
                  <span class="name">{{ r.name }}</span>
                  <span class="status">{{ r.status || '🟢' }}</span>
                </div>
                <div class="card-meta">{{ r.date }} · {{ r.code }} · {{ r.action }}</div>
                <div class="card-row">
                  <span>建议价：{{ r.suggest_price || '-' }}</span>
                  <span>当前价：{{ r.current_price || '-' }}</span>
                </div>
                <div class="card-reason">{{ r.reason || '-' }}</div>
              </article>
            </div>
          </div>

          <div class="decision-group group-yellow">
            <h4>🟡 观察待验证</h4>
            <div v-if="decisionGroups.yellow.length === 0" class="dd-empty">暂无</div>
            <div v-else class="decision-cards">
              <article v-for="(r, idx) in decisionGroups.yellow" :key="`y-${idx}`" class="decision-card card-yellow">
                <div class="card-top">
                  <span class="name">{{ r.name }}</span>
                  <span class="status">{{ r.status || '🟡' }}</span>
                </div>
                <div class="card-meta">{{ r.date }} · {{ r.code }} · {{ r.action }}</div>
                <div class="card-row">
                  <span>建议价：{{ r.suggest_price || '-' }}</span>
                  <span>当前价：{{ r.current_price || '-' }}</span>
                </div>
                <div class="card-reason">{{ r.reason || '-' }}</div>
              </article>
            </div>
          </div>

          <div class="decision-group group-red">
            <h4>🔴 风险与回避</h4>
            <div v-if="decisionGroups.red.length === 0" class="dd-empty">暂无</div>
            <div v-else class="decision-cards">
              <article v-for="(r, idx) in decisionGroups.red" :key="`r-${idx}`" class="decision-card card-red">
                <div class="card-top">
                  <span class="name">{{ r.name }}</span>
                  <span class="status">{{ r.status || '🔴' }}</span>
                </div>
                <div class="card-meta">{{ r.date }} · {{ r.code }} · {{ r.action }}</div>
                <div class="card-row">
                  <span>建议价：{{ r.suggest_price || '-' }}</span>
                  <span>当前价：{{ r.current_price || '-' }}</span>
                </div>
                <div class="card-reason">{{ r.reason || '-' }}</div>
              </article>
            </div>
          </div>
        </div>
        <div v-else class="dd-empty">未解析到标准决策表格，下面展示原文摘要。</div>
        <details class="dd-details">
          <summary>查看原文摘要</summary>
          <pre class="dd-raw">{{ data.ai_decisions.raw_excerpt }}</pre>
        </details>
      </section>
    </template>
  </div>
</template>
