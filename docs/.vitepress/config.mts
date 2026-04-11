import { defineConfig } from 'vitepress'
// https://vitepress.dev/reference/site-config

// 自动判断部署环境
// EdgeOne 环境 → 根路径 /
const isEdgeOne = !!process.env.EDGEONE;
const baseConfig = isEdgeOne ? '/' : '/dive-into-context-engineering/';

export default defineConfig({
  lang: 'zh-CN',
  title: "Dive Into Context Engineering",
  description: "上下文工程入门与实战教程",
  // 自动切换基础路径
  base: baseConfig,
  markdown: {
    math: true
  },
  themeConfig: {
    logo: '/datawhale-logo.png',

    // 修正为你的仓库地址
    nav: [
      { text: 'PDF版本下载', link: 'https://github.com/funnamer/dive-into-context-engineering/releases' },
    ],
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
              navigateText: '切换'
            }
          }
        }
      }
    },
    sidebar: [
      {
        text: 'Context Engineering 教程',
        items: [
          { text: '第1章：总览', link: '/chapter1/overview' },
          { text: '第2章：提示词工程', link: '/chapter2/prompt_engineering' },
          { text: '第3章：上下文工程', link: '/chapter3/context_engineering' },
          { text: '第4章：harness-engineering', link: '/chapter4/harness_engineering' },
          { text: '第5章：从提示词到上下文到harness的演进', link: '/chapter5/evolution' },
          { text: '第6章：小项目实践', link: '/chapter6/miniMaster' }
        ]
      }
    ],

    // 修正为你的 GitHub 地址
    socialLinks: [
      { icon: 'github', link: 'https://github.com/datawhalechina/dive-into-context-engineering' }
    ],

    // 修正在线编辑链接
    editLink: {
      pattern: 'https://github.com/datawhalechina/dive-into-context-engineering/blob/main/docs/:path'
    },

    footer: {
      message: '<a href="https://beian.miit.gov.cn/" target="_blank">京ICP备2026002630号-1</a> | <a href="https://beian.mps.gov.cn/#/query/webSearch?code=11010602202215" rel="noreferrer" target="_blank">京公网安备11010602202215号</a>',
      copyright: '本作品采用 <a href="http://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank">知识共享署名-非商业性使用-相同方式共享 4.0 国际许可协议（CC BY-NC-SA 4.0）</a> 进行许可'
    }
  }
})