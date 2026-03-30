import DefaultTheme from 'vitepress/theme'
import './custom.css'
import DecisionDashboard from './DecisionDashboard.vue'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component('DecisionDashboard', DecisionDashboard)
  }
}
