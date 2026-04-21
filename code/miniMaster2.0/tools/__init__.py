"""工具系统总入口包。

miniMaster 把工具分成三层：
- `core`: 统一抽象、上下文和注册服务
- `base_tool`: 读写文件、执行命令等基础工具
- `search_tool`: glob / grep 这类检索工具
"""
