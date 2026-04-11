# miniMaster
## Tool 设计

为 Agent 设计一套好用的工具集，是让它从“聊天机器人”蜕变为“生产力助手”的关键。在我的 Agent 系统中，工具（Tools）被主要划分为两个核心模块：负责文件和系统基础交互的 `base_tool`，以及负责信息检索的 `search_tool`。

### 1. 基础系统工具 (Base Tools)

`base_tool` 目录下包含了 Agent 与操作系统进行直接交互的最基础能力。这些工具构成了 Agent 读写代码、执行命令的基石：

* **Bash Tool (`bash_tool.py`)**：赋予了 Agent 执行 Shell 命令的能力。它通过 `subprocess` 模块运行命令，并设计了默认 30 秒的超时机制，以防止命令阻塞。执行后会结构化地返回标准输出 (`stdout`)、标准错误 (`stderr`) 以及执行状态。
* **Read Tool (`read_tool.py`)**：负责读取文件内容。除了完整读取文件外，它还支持通过传入 `start_line` 和 `end_line` 参数来读取特定行号范围的内容，这对于大文件的局部上下文读取非常有用。
* **Write Tool (`write_tool.py`)**：提供文件写入功能。它支持三种模式：覆盖 (`overwrite`)、追加 (`append`) 和新建 (`create`)。同时，它还具备自动创建缺失目录的能力，让 Agent 写入文件时更加顺畅。
* **Edit Tool (`edit_tool.py`)**：为了让 Agent 能够精准修改代码而设计。它通过接收一组替换规则 (`replacements`)，在文件中定位 `original_text` 并将其替换为 `new_text`。它还支持 `replace_all` 选项来决定是全局替换还是单次替换。

### 2. 搜索检索工具 (Search Tools)

为了让 Agent 能够在庞大的代码库或文件系统中精准定位信息，`search_tool` 目录提供了强大的文件和文本检索能力：

* **Glob Tool (`glob_tool.py`)**：基于通配符的文件查找工具。它利用 `glob` 模块查找匹配特定模式的文件或目录。它支持递归搜索 (`recursive`)，并且可以选择是否包含隐藏文件 (`include_hidden`)，最多可返回默认 1000 个结果。
* **Grep Tool (`grep_tool.py`)**：基于正则表达式的文本搜索工具。它能够在指定目录或文件中搜索文本模式，支持区分大小写搜索和递归目录遍历。它还能通过 `include_pattern` 参数过滤特定类型的文件，最终返回包含文件名、行号、匹配文本的具体结果。

### 3. 统一的接口设计

在实现上，所有的 Tool 都遵循了一种高度一致的接口规范，这大大降低了 Agent 调用工具的认知负担：
* **Prompt 结构化导出**：每个工具类都包含一个 `prompt_block()` 方法，该方法会返回工具的名称、描述以及基于 JSON Schema 的输入参数定义。这使得 Agent 能够清晰地理解如何构造调用参数。
* **标准化执行与容错**：每个工具的业务逻辑都被封装在 `run(self, tool_input: dict)` 方法中。更重要的是，所有工具都在内部实现了 `try...except` 异常捕获。无论执行成功还是发生错误（如文件不存在、正则语法错误等），工具都会返回包含 `"success": True/False` 和错误信息的 JSON 字典，确保 Agent 不会因为工具崩溃而中断运行。


---

## 2. 状态管理与动态工作记忆 (State Management)

任何一个需要持续工作的 Agent，都面临一个核心的技术挑战：**如何平衡不断增长的执行记录与 LLM 有限的上下文窗口（Token 限制）？** 如果像“金鱼”一样只有短暂记忆，Agent 就会陷入死循环；但如果把所有历史都毫无保留地塞进 Prompt，不仅会导致 Token 溢出报错，还会让大模型产生“幻觉”或“分心”（Lost in the Middle）。

为了解决这个问题，在架构中，状态管理被清晰地划分为“宏观”和“微观”两层。宏观层面由 `ToDoList` 类接管，充当 Agent 的“任务看板”，记录全局子任务的生命周期。而微观层面，也就是 Agent 执行具体动作时的“脑容量”，则交由 **`WorkingMemory`（动态压缩工作记忆）** 来管理。

不采用简单的“丢弃最旧记忆”的滑动窗口策略，而是实现了一套**基于字符长度触发的平滑动态压缩机制**。下面是核心代码实现：

```python
import json

class WorkingMemory:
    """工作记忆管理类 - 按照 Token(字符) 长度触发动态压缩"""

    def __init__(self, keep_latest_n: int = 3, max_chars: int = 45000):
        self.memories = []
        # 触发压缩时，保留最后几个步骤的完整 JSON 不被压缩（保持当前工作的连贯性）
        self.keep_latest_n = keep_latest_n
        # 触发阈值：20k token 大约等于 40000~50000 个字符
        self.max_chars = max_chars
        self.summary = ""

    def add_memory(self, step: int, tool_name: str, parameters: dict, result: any):
        """添加新记忆（记录每一步的工具调用和返回结果）"""
        self.memories.append({
            "step": step,
            "tool_call": {"tool_name": tool_name, "parameters": parameters},
            "result": result
        })

    def get_prompt_context(self) -> str:
        """组装给 Agent 看的完整上下文：早期摘要 + 近期详细步骤"""
        context = ""
        if self.summary:
            context += f"【早期步骤摘要】:\n{self.summary}\n\n"

        # 只要没超限，Agent 就能看到所有近期步骤的完整内容
        context += "【执行步骤】:\n" + json.dumps(self.memories, ensure_ascii=False, indent=2)
        return context

    def check_needs_summary(self) -> bool:
        """核心策略：判断当前上下文是否超过了容量阈值"""
        current_length = len(self.get_prompt_context())
        # 只有长度超标，且记忆数量大于我们要保留的底线时，才触发压缩
        return current_length > self.max_chars and len(self.memories) > self.keep_latest_n

    def get_memories_to_summarize(self) -> list:
        """获取需要被压缩的庞大旧记忆"""
        if self.check_needs_summary():
            # 取出除了最后 keep_latest_n 步之外的所有早期记忆，打包准备送去压缩
            return self.memories[:-self.keep_latest_n]
        return []

    def commit_summary(self, new_summary: str):
        """用大模型返回的摘要覆盖旧摘要，并清理掉已被压缩的冗长数据"""
        self.summary = new_summary
        # 核心：截断数组，只保留最后 keep_latest_n 步的详细记忆，腾出大量空间
        self.memories = self.memories[-self.keep_latest_n:]
```

#### 动态记忆压缩是如何运转的？

1. **内容长度检测 (`check_needs_summary`)**
   通过 `max_chars`（默认约 4.5 万字符，大致对应 20k Tokens）设定了安全红线。每一次执行新动作前，系统都会预检当前的上下文长度。只有当文本量真正逼近 Token 极限时，才会触发压缩动作。这意味着在资源允许的范围内，Agent 始终拥有最高精度、最完整的上下文。
2. **平滑的上下文过渡 (`keep_latest_n`)**
   通过切片操作 `self.memories[:-self.keep_latest_n]` 和 `self.memories[-self.keep_latest_n:]`，我在触发压缩时，**强制保留了最近 N 步（如 3 步或 8 步）的完整 JSON 记录**。这保证了 Agent 思考和执行的微观连贯性。
3. **滚动式记忆沉淀 (`get_prompt_context` & `commit_summary`)**
   当触发压缩时，被抛弃的早期记录并没有消失。主循环（参考后续的 `Generator-Agent` 逻辑）会调用大模型，将这些冗长的早期 JSON 记录连同旧的 `summary` 一起，浓缩成一段高度精简的文本。在下一次拼接 Prompt 时，Agent 看到的将会是：`【早期步骤摘要】+【最近 3 步详细 JSON 执行过程】`。

---

### 3. 任务编排与多智能体协作机制 (Task Orchestration)


**“规划-执行-验证”三层嵌套循环 (Plan-Generate-Validate)** 的多智能体协作架构。
每个 Agent 各司其职，拥有独立的 Prompt 和职责边界：

#### 3.1 第一层循环：Plan-Agent (全局调度)

Plan-Agent 是整个系统的大脑。它不直接干脏活累活（比如写代码或查文件），它的唯一职责是审视用户的原始需求，并维护 `ToDoList` 任务看板。

它的核心循环受 `max_iter` 控制，通过专属的任务管理工具（如 `init_tasks`, `add_task`）来拆解步骤。当它明确了当前要做的具体任务后，会调用 `subagent_tool`，将任务“外包”给下层的执行智能体：

```python
        # 伪代码：Plan-Agent 的核心路由逻辑
        if plan_tool == "init_tasks":
            to_do_list.init_tasks(task_list)
            continue
        elif plan_tool == "subagent_tool":
            curr_task_name = plan_params.get("task_name")
            curr_task = to_do_list.get_task_by_name(curr_task_name)
            
            # 唤醒下一层的 Generator-Agent 执行具体任务
            # 进入第二层循环...
```

#### 3.2 第二层循环：Generator-Agent (执行者)

当 `subagent_tool` 被触发后，系统进入内部的 `while True` 循环，唤醒 Generator-Agent。这是真正干活的角色。

为了适应重度代码编写和文件搜索，我为 Generator 赋予了非常宽裕的独立记忆（`keep_latest_n=8, max_chars=80000`），并向它开放了所有的 `base_tool` 和 `search_tool`。

它会在这个子循环中不断尝试：搜索文件 -> 读取代码 -> 修改代码 -> 执行 Bash 脚本测试。在这个过程中，上一节提到的**动态记忆压缩机制**会默默保障它的上下文不会溢出。当 Generator 认为当前子任务已经搞定时，它必须调用一个特殊的工具 `update_task_conclusion` 来提交成果：

```python
                if gen_tool != "update_task_conclusion":
                    # 正常执行基础或搜索工具
                    result = execute_tool(gen_tool, gen_params)
                    generator_memory.add_memory(gen_step, gen_tool, gen_params, result)
                    continue  # 继续第二层循环干活
                else:
                    # Generator 认为完成了，提交结论
                    conclusion = gen_params.get("conclusion", "")
                    to_do_list.update_task_conclusion(curr_task_name, conclusion)
                    # 触发质检，进入第三层循环...
```

#### 3.3 第三层循环：Validate-Agent (评估者)

当 Generator 提交成果后，第三层循环启动，Validate-Agent 接管控制权。

它是一个拥有完全独立、清空记忆的全新实例，它的 Prompt 指令明确要求：**验证当前任务的完成是否有效**。它可以自己调用检索或终端工具去核实 Generator 的工作，最后必须调用 `validate_tool` 输出 `有效` 或 `无效` 以及原因。
从而完成**纠错闭环（Feedback Loop）** ：

```python
                            # Validate-Agent 得出验证结论
                            status = val_params.get("status") 
                            reason = val_params.get("reason", "未知错误")

                            if status == "有效":
                                is_valid = True
                                break  # 结束第三层循环，准备回退到第一层
                            else:
                                # 【核心逻辑】验证失败：将错误原因强行写入 Generator 的记忆中
                                generator_memory.add_memory(
                                    gen_step + 1,
                                    "system_feedback",
                                    {},
                                    f"验证失败，请重新调整。原因: {reason}"
                                )
                                is_valid = False
                                break  # 结束第三层循环，回到第二层循环，让 Generator 看到反馈并重试
```

如果验证失败，则会构造了一条名为 `system_feedback` 的内容，注入到 Generator-Agent 的 `WorkingMemory` 中。随后，程序跳出第三层循环，**继续回到第二层循环**。

此时，Generator-Agent 它在上下文里看到了自己之前的操作记录，同时也看到了 Validate-Agent 刚刚打回的“验证失败原因”。基于这些详尽的上下文，Generator 可以立即思考新的解决方案并重试，直到最终通过验证。当验证通过（`is_valid = True`），任务状态才会被真正更新为 `DONE`，控制权重新回到最外层的 Plan-Agent 手中。

