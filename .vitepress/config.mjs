import { defineConfig } from 'vitepress'

export default defineConfig({
  title: '投资分析模板',
  description: '港股/A股个股投资分析框架 V5.5.20',
  lang: 'zh-CN',
  
  // 忽略的死链（有些文件可能临时不存在）
  ignoreDeadLinks: true,
  
  // 排除不需要构建的目录
  srcExclude: ['tmp/**'],
  
  themeConfig: {
    // 导航栏
    nav: [
      { text: '首页', link: '/' },
      { text: '🎯 模拟持仓', link: '/portfolio/holdings' },
      { text: '📈 VIX定投', link: '/portfolio/vix-dca-strategy' },
      { text: '分析模板', link: '/analysis-template' },
      { text: '版本日志', link: '/docs/CHANGELOG' }
    ],
    
    // 侧边栏
    sidebar: {
      '/portfolio/': [
        {
          text: '🎯 模拟持仓',
          collapsed: false,
          items: [
            { text: '总览', link: '/portfolio/' },
            { text: '持仓', link: '/portfolio/holdings' },
            { text: '今日操作', link: '/portfolio/daily-operations' },
            { text: '决策记录', link: '/portfolio/decision-log' },
            { text: '📈 VIX定投策略', link: '/portfolio/vix-dca-strategy' }
          ]
        }
      ],
      '/': [
      {
        text: '📋 核心文档',
        collapsed: false,
        items: [
          { text: '个股分析标准模版', link: '/analysis-template' },
          { text: '🎯 模拟持仓（实时）', link: '/portfolio/holdings' },
          { text: '项目介绍', link: '/README' },
          { text: '项目结构说明', link: '/docs/project-structure' },
          { text: '更新日志', link: '/docs/CHANGELOG' }
        ]
      },
      {
        text: '📋 分析模板',
        collapsed: false,
        items: [
          { text: '01-数据核查与地缘政治排除', link: '/template/01-数据核查与地缘政治排除' },
          { text: '02-央国企筛选与流派识别', link: '/template/02-央国企筛选与流派识别' },
          { text: '03-深度负债与周期分析', link: '/template/03-深度负债与周期分析' },
          { text: '04-动态现金与周期拐点', link: '/template/04-动态现金与周期拐点' },
          { text: '05-极端情景测试', link: '/template/05-极端情景测试' },
          { text: '06-估值与安全边际', link: '/template/06-估值与安全边际' },
          { text: '07-决策流程与持仓管理', link: '/template/07-决策流程与持仓管理' },
          { text: '08-高级烟蒂股分析框架', link: '/template/08-高级烟蒂股分析框架' },
          { text: '09-估值修复框架', link: '/template/09-估值修复框架' },
          { text: '10-特殊轻资产模式', link: '/template/10-特殊轻资产模式' },
          { text: '12-扩张期消费品牌分析框架', link: '/template/12-扩张期消费品牌分析框架' },
          { text: '13-消费分层与AI时代防御框架', link: '/template/13-消费分层与AI时代防御框架' },
          { text: '11-ST套利与特殊事件策略', link: '/template/11-ST套利与特殊事件策略' }
        ]
      },
      {
        text: '📚 项目文档',
        collapsed: true,
        items: [
          { text: '更新日志', link: '/docs/CHANGELOG' },
          { text: '项目结构说明', link: '/docs/project-structure' }
        ]
      },
      {
        text: '📈 个股分析报告',
        collapsed: true,
        items: [
          { text: '🔥 监控概览（每日更新）', link: '/analysis-reports/监控概览' },
          { text: '保利物业_06049_投资分析报告', link: '/analysis-reports/保利物业_06049_投资分析报告' },
          { text: '天津发展_00882_投资分析报告', link: '/analysis-reports/天津发展_00882_投资分析报告' },
          { text: '中国民航信息网络_00696_投资分析报告', link: '/analysis-reports/中国民航信息网络_00696_投资分析报告' },
          { text: '金融街物业_01502_投资分析报告', link: '/analysis-reports/金融街物业_01502_投资分析报告' },
          { text: '中海物业_02669_投资分析报告', link: '/analysis-reports/中海物业_02669_投资分析报告' },
          { text: '汇贤产业信托_87001_投资分析报告', link: '/analysis-reports/汇贤产业信托_87001_投资分析报告' },
          { text: '蒙牛乳业_02319_投资分析报告', link: '/analysis-reports/蒙牛乳业_02319_投资分析报告' },
          { text: '海底捞_06862_投资分析报告', link: '/analysis-reports/海底捞_06862_投资分析报告' },
          { text: '京投交通科技_01522_投资分析报告', link: '/analysis-reports/京投交通科技_01522_投资分析报告' },
          { text: '绿城服务_02869_投资分析报告', link: '/analysis-reports/绿城服务_02869_投资分析报告' },
          { text: '同仁堂国药_03613_投资分析报告', link: '/analysis-reports/同仁堂国药_03613_投资分析报告' },
          { text: '牧原股份_002714_投资分析报告', link: '/analysis-reports/牧原股份_002714_投资分析报告' },
          { text: '分众传媒_002027_投资分析报告', link: '/analysis-reports/分众传媒_002027_投资分析报告' },
          { text: '青岛啤酒_600600_投资分析报告', link: '/analysis-reports/青岛啤酒_600600_投资分析报告' },
          { text: '华润医药_03320_投资分析报告', link: '/analysis-reports/华润医药_03320_投资分析报告' },
          { text: '中国食品_00506_投资分析报告', link: '/analysis-reports/中国食品_00506_投资分析报告' },
          { text: '达势股份_01405_投资分析报告', link: '/analysis-reports/达势股份_01405_投资分析报告' },
          { text: '山东药玻_600529_投资分析报告', link: '/analysis-reports/山东药玻_600529_投资分析报告' },
          { text: '五粮液_000858_投资分析报告', link: '/analysis-reports/五粮液_000858_投资分析报告' },
          { text: '安井食品_603345_投资分析报告', link: '/analysis-reports/安井食品_603345_投资分析报告' },
          { text: '滨江服务_03316_投资分析报告', link: '/analysis-reports/滨江服务_03316_投资分析报告' },
          { text: '神威药业_02877_投资分析报告', link: '/analysis-reports/神威药业_02877_投资分析报告' }
        ]
      }
      ]
    },
    
    // 社交链接
    socialLinks: [
      { icon: 'github', link: 'https://github.com/sunheyi6/investTemplate' }
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
      copyright: 'Copyright © 2026 投资分析模板 V5.5.20'
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
    ['link', { rel: 'shortcut icon', href: '/favicon.ico?v=20260430' }],
    ['link', { rel: 'icon', href: '/favicon.ico?v=20260430' }],
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg?v=20260430' }],
    ['link', { rel: 'icon', type: 'image/png', href: '/favicon.png?v=20260430' }],
    ['meta', { name: 'author', content: '投资分析模板' }],
    ['meta', { name: 'keywords', content: '投资,港股,A股,价值投资者,股票筛选,估值模型' }]
  ]
})
