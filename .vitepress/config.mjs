import { defineConfig } from 'vitepress'

export default defineConfig({
  title: '投资分析模板',
  description: '港股/A股个股投资分析框架 V5.5.12',
  lang: 'zh-CN',
  
  // 忽略的死链（有些文件可能临时不存在）
  ignoreDeadLinks: true,
  
  themeConfig: {
    // 导航栏
    nav: [
      { text: '首页', link: '/' },
      { text: '🎯 模拟持仓', link: '/模拟持仓/持仓' },
      { text: '分析模板', link: '/个股分析标准模版' },
      { text: '版本日志', link: '/CHANGELOG' }
    ],
    
    // 侧边栏
    sidebar: {
      '/模拟持仓/': [
        {
          text: '🎯 模拟持仓',
          collapsed: false,
          items: [
            { text: '总览', link: '/模拟持仓/' },
            { text: '持仓', link: '/模拟持仓/持仓' },
            { text: '今日操作', link: '/模拟持仓/今日操作' },
            { text: '决策记录', link: '/模拟持仓/决策记录' }
          ]
        }
      ],
      '/': [
      {
        text: '📋 核心文档',
        collapsed: false,
        items: [
          { text: '个股分析标准模版', link: '/个股分析标准模版' },
          { text: '🎯 模拟持仓（实时）', link: '/模拟持仓/持仓' },
          { text: '项目介绍', link: '/README' },
          { text: '项目结构说明', link: '/项目结构说明' },
          { text: '更新日志', link: '/CHANGELOG' }
        ]
      },
      {
        text: '🔍 01-筛选框架',
        collapsed: false,
        items: [
          { text: '双市场筛选标准', link: '/01-筛选框架/01-1-双市场筛选标准' },
          { text: '行业筛选白名单', link: '/01-筛选框架/01-行业筛选白名单' },
          { text: '金龟筛选框架', link: '/01-筛选框架/01-金龟筛选框架' }
        ]
      },
      {
        text: '🧹 02-数据清洗',
        collapsed: true,
        items: [
          { text: '强制性核查清单', link: '/02-数据清洗/02-1-强制性核查清单' },
          { text: '核心数据清洗', link: '/02-数据清洗/02-核心数据清洗' }
        ]
      },
      {
        text: '💰 03-估值模型',
        collapsed: true,
        items: [
          { text: 'V2-高股息协议', link: '/03-估值模型/03-V2-高股息协议' },
          { text: 'V3-十倍估值法', link: '/03-估值模型/04-V3-十倍估值法' },
          { text: 'V3.5-FCEV估值法', link: '/03-估值模型/05-V35-FCEV估值法' }
        ]
      },
      {
        text: '🎯 04-决策分析',
        collapsed: true,
        items: [
          { text: '06-类比延伸', link: '/04-决策分析/06-类比延伸' },
          { text: '07-最终决策综述', link: '/04-决策分析/07-最终决策综述' }
        ]
      },
      {
        text: '📊 05-策略框架',
        collapsed: true,
        items: [
          { text: '08-烟蒂股策略框架', link: '/05-策略框架/08-烟蒂股策略框架' },
          { text: 'VIX-纳斯达克100定投策略', link: '/05-策略框架/VIX-纳斯达克100定投策略/README' },
          { text: 'VIX策略回测报告', link: '/05-策略框架/VIX-纳斯达克100定投策略/backtest_report' }
        ]
      },
      {
        text: '📚 06-附录案例',
        collapsed: true,
        items: [
          { text: '09-附录', link: '/06-附录案例/09-附录' }
        ]
      },
      {
        text: '📈 07-分析输出',
        collapsed: true,
        items: [
          { text: '🔥 监控概览（每日更新）', link: '/07-分析输出/监控概览' },
          { text: '保利物业_06049_投资分析报告', link: '/07-分析输出/保利物业_06049_投资分析报告' },
          { text: '天津发展_00882_投资分析报告', link: '/07-分析输出/天津发展_00882_投资分析报告' },
          { text: '中国民航信息网络_00696_投资分析报告', link: '/07-分析输出/中国民航信息网络_00696_投资分析报告' },
          { text: '金融街物业_01502_投资分析报告', link: '/07-分析输出/金融街物业_01502_投资分析报告' },
          { text: '中海物业_02669_投资分析报告', link: '/07-分析输出/中海物业_02669_投资分析报告' },
          { text: '汇贤产业信托_87001_投资分析报告', link: '/07-分析输出/汇贤产业信托_87001_投资分析报告' },
          { text: '蒙牛乳业_02319_投资分析报告', link: '/07-分析输出/蒙牛乳业_02319_投资分析报告' },
          { text: '海底捞_06862_投资分析报告', link: '/07-分析输出/海底捞_06862_投资分析报告' },
          { text: '京投交通科技_01522_投资分析报告', link: '/07-分析输出/京投交通科技_01522_投资分析报告' },
          { text: '绿城服务_02869_投资分析报告', link: '/07-分析输出/绿城服务_02869_投资分析报告' },
          { text: '同仁堂国药_03613_投资分析报告', link: '/07-分析输出/同仁堂国药_03613_投资分析报告' },
          { text: '牧原股份_002714_投资分析报告', link: '/07-分析输出/牧原股份_002714_投资分析报告' },
          { text: '分众传媒_002027_投资分析报告', link: '/07-分析输出/分众传媒_002027_投资分析报告' },
          { text: '青岛啤酒_600600_投资分析报告', link: '/07-分析输出/青岛啤酒_600600_投资分析报告' },
          { text: '华润医药_03320_投资分析报告', link: '/07-分析输出/华润医药_03320_投资分析报告' }
        ]
      },
      {
        text: '🔭 07-标的追踪',
        collapsed: true,
        items: [
          { text: '查看目录', link: '/07-标的追踪/' }
        ]
      },
      {
        text: '🤖 08-决策追踪',
        collapsed: true,
        items: [
          { text: '🎯 模拟持仓', link: '/模拟持仓/持仓' }
        ]
      }
      ]
    },
    
    // 社交链接
    socialLinks: [
      { icon: 'github', link: 'https://github.com/yourname/investTemplate' }
    ],
    
    // 本地搜索
    search: {
      provider: 'local',
      options: {
        translations: {
          button: {
            buttonText: '搜索文档',
            buttonAriaLabel: '搜索文档'
          },
          modal: {
            noResultsText: '无法找到相关结果',
            resetButtonTitle: '清除查询条件',
            footer: {
              selectText: '选择',
              navigateText: '切换',
              closeText: '关闭'
            }
          }
        }
      }
    },
    
    // 页脚
    footer: {
      message: '基于 Apache License 2.0 开源协议',
      copyright: 'Copyright © 2026 投资分析模板 V5.5.12'
    },
    
    // 大纲显示级别
    outline: {
      level: 'deep',
      label: '页面导航'
    },
    
    // 文档页脚
    docFooter: {
      prev: '上一页',
      next: '下一页'
    },
    
    // 编辑链接
    editLink: {
      pattern: 'https://github.com/yourname/investTemplate/edit/main/:path',
      text: '在 GitHub 上编辑此页'
    },
    
    // 最后更新时间
    lastUpdated: {
      text: '最后更新',
      formatOptions: {
        dateStyle: 'full',
        timeStyle: 'medium'
      }
    }
  },
  
  // Markdown 配置
  markdown: {
    lineNumbers: true,
    config: (md) => {
      // 可以在这里添加 markdown-it 插件
    }
  },
  
  // 头部配置
  head: [
    ['link', { rel: 'icon', href: '/favicon.ico' }],
    ['meta', { name: 'author', content: '投资分析模板' }],
    ['meta', { name: 'keywords', content: '投资,港股,A股,价值投资者,股票筛选,估值模型' }]
  ]
})
