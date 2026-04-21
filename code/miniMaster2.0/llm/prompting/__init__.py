"""Prompt 与动作协议层。

这里把“给模型看什么”和“允许模型做什么”拆成三个模块：
- builders: 负责拼 Prompt 文本
- policies: 负责声明动作白名单
- protocol: 负责在 function call 协议上做适配与校验
"""
