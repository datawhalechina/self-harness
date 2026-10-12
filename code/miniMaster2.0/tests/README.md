# 离线工具回归测试

从 `code/miniMaster2.0/` 目录运行：

```bash
python -m unittest discover -s tests -p "test_grep_tool.py" -v
```

Grep 测试使用真实临时文件、`ToolService` 和搜索后端，不需要模型服务或 API Key。请先安装 ripgrep，并确认 `rg --version` 可运行；否则四项真实子进程测试会跳过，仅执行 Python 回退测试。

覆盖以 `-` 开头的查询和文件名、普通正则、文件过滤、递归开关、结果上限，以及无匹配和无效正则的区别。测试文件会在结束时自动清理。
