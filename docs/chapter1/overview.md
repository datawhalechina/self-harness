# 第一章：概览

## 🎯 项目介绍

&emsp;&emsp;在与大型语言模型（LLM）交互的早期，我们往往认为只要“把话说清楚”，就能得到想要的结果。然而，随着 AI 应用逐渐深入到复杂的真实业务场景中，开发者们发现，仅靠单一的指令输入已经无法驾驭大模型在长周期、多跳推理任务中的不确定性。

&emsp;&emsp;为了突破大模型只能生成文本而不能解决真实问题的限制，AI 工程师们的视角正在经历一次深刻的范式转移：从单纯的**提示词工程（Prompt Engineering）**，走向系统化的**上下文工程（Context Engineering）**，并最终迈向由多智能体协作构成的**harness工程（Harness Engineering）**。

&emsp;&emsp;本教程是 Datawhale 社区的开源学习项目。我们将带领大家穿透框架表象，从最核心的 **Prompt Engineering** 出发，深入理解 **Context Engineering**，并最终掌握 **Harness Engineering** 的核心理念——不仅仅是使用大模型，而是构建能够稳定、可控、高效驱动大模型的工程化系统。教程包含完整的理论讲解与配套的 **miniMaster** 实战代码，帮助你从一名大语言模型的"使用者"，蜕变为一名智能体系统的"构建者"。

## 🌐 在线阅读

**[🚀 访问链接](https://self-harness.datawhale.cc)**

## ✨ 你将收获什么？

- 📖 **Datawhale 开源免费** — 完全免费学习本项目所有内容，与社区共同成长
- 🔍 **理解核心原理** — 深入理解 Prompt、Context 与 Harness 三层演进的核心逻辑
- 🏗️ **亲手实现** — 基于 Python 从零实现一个包含 Plan / Generator / Validate 三层架构的 miniMaster 系统
- ⚙️ **掌握高级技能** — 学习动态工作记忆管理、工具注册与调用、LangSmith 追踪等工程化技术

## 📖 内容导航

| 章节 | 关键内容 | 状态 |
| --- | --- | --- |
| [第1章：总览](./chapter1/overview) | Prompt、Context、Harness 的关系与演进 | ✅ |
| [第2章：提示词工程](./chapter2/prompt_engineering) | Prompt Engineering 的核心技巧与最佳实践 | ✅ |
| [第3章：上下文工程](./chapter3/context_engineering) | Context Engineering 的设计思想与实现 | ✅ |
| [第4章：Harness Engineering](./chapter4/harness_engineering) | Harness 的定义、架构与系统级思考 | ✅ |
| [第5章：从提示词到上下文的演进](./chapter5/evolution) | 完整梳理从 Prompt 到 Harness 的演进路径 | ✅ |
| [第6章：小项目实践](./chapter6/miniMaster) | 手把手实现 miniMaster 2.0 实战项目 | ✅ |

---

## Team

<div style="display:flex; flex-wrap:wrap; gap:24px; justify-content:center; margin-top:16px;">
  <div style="text-align:center; width:120px;">
    <img src="https://www.github.com/funnamer.png" style="width:80px; height:80px; border-radius:50%; object-fit:cover;" />
    <div style="font-weight:bold; margin-top:8px;">张文星</div>
    <div style="font-size:12px; color:#666;">项目负责人/核心贡献者</div>
    <div style="margin-top:4px;"><a href="https://github.com/funnamer">GitHub</a></div>
  </div>
  <div style="text-align:center; width:120px;">
    <img src="https://www.github.com/Sm1les.png" style="width:80px; height:80px; border-radius:50%; object-fit:cover;" />
    <div style="font-weight:bold; margin-top:8px;">Sm1les</div>
    <div style="font-size:12px; color:#666;">核心贡献者</div>
    <div style="margin-top:4px;"><a href="https://github.com/Sm1les">GitHub</a></div>
  </div>
  <div style="text-align:center; width:120px;">
    <img src="https://www.github.com/TheCaptainUniverse.png" style="width:80px; height:80px; border-radius:50%; object-fit:cover;" />
    <div style="font-weight:bold; margin-top:8px;">CaptainUniverse_</div>
    <div style="font-size:12px; color:#666;">核心贡献者</div>
    <div style="margin-top:4px;"><a href="https://github.com/TheCaptainUniverse">GitHub</a></div>
  </div>
</div>
