import { defineConfig } from 'vitepress'

export default defineConfig({
  title: '投资分析模板',
  description: '港股/A股个股投资分析框架 V5.5.7',
  lang: 'zh-CN',
  
  // 忽略的死链（有些文件可能临时不存在）
  ignoreDeadLinks: true,
  
  themeConfig: {
    // 导航栏
    nav: [
      { text: '首页', link: '/' },
      { text: '分析模板', link: '/个股分析标准模版' },
      { text: '版本日志', link: '/CHANGELOG' }
    ],
    
    // 侧边栏
    sidebar: [
      {
        text: '📋 核心文档',
        collapsed: false,
        items: [
          { text: '个股分析标准模版', link: '/个股分析标准模版' },
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
          { text: '08-烟蒂股策略框架', link: '/05-策略框架/08-烟蒂股策略框架' }
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
          { text: '保利物业_06049_投资分析报告', link: '/07-分析输出/保利物业_06049_投资分析报告' }
        ]
      },
      {
        text: '🔭 07-标的追踪',
        collapsed: true,
        items: [
          { text: '查看目录', link: '/07-标的追踪/' }
        ]
      }
    ],
    
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
      copyright: 'Copyright © 2026 投资分析模板 V5.5.7'
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
