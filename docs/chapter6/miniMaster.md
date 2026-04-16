# miniMaster

本项目是一个极简的实例，着重实现维护agent长期运行稳定的方法，快速体验harness的核心理念

## Tool 设计

为 Agent 设计一套好用的工具集，是让它从“聊天机器人”蜕变为“生产力助手”的关键。在我的 Agent 系统中，工具（Tools）被主要划分为两个核心模块：负责文件和系统基础交互的 `base_tool`，以及负责信息检索的 `search_tool`。

### 1. 基础系统工具 (Base Tools)

`base_tool` 目录下包含了 Agent 与操作系统进行直接交互的最基础能力。这些工具构成了 Agent 读写代码、执行命令的基石：

* **Bash Tool (`bash_tool.py`)**：赋予了 Agent 执行命令行指令的能力。虽然名字叫 `bash`，但它本质上是一个“通用命令执行工具”。在当前项目的 Windows 环境中，它会通过 PowerShell 执行命令，因此像 `Get-ChildItem -Force` 这类命令会更稳定。它同样保留了默认 30 秒超时机制，避免某条命令一直卡住主流程。执行结束后，它会结构化返回标准输出 (`stdout`)、标准错误 (`stderr`) 和返回码 (`returncode`)。
* **Read Tool (`read_tool.py`)**：负责读取文件内容。除了完整读取文件外，它还支持通过传入 `start_line` 和 `end_line` 参数来读取特定行号范围的内容，这对于大文件的局部上下文读取非常有用。更重要的是，它会统一以当前工作目录（workspace）为基准解析相对路径，这样 Agent 说“读取 `main_agent.py`”时，不会因为进程启动位置不同而读错文件。
* **Write Tool (`write_tool.py`)**：提供文件写入功能。它支持三种模式：覆盖 (`overwrite`)、追加 (`append`) 和新建 (`create`)。同时，它还具备自动创建缺失目录的能力，让 Agent 写入文件时更加顺畅。和 `read` 一样，它也会基于 workspace 解析相对路径，因此 `docs/output.md` 这类路径写起来更自然。
* **Edit Tool (`edit_tool.py`)**：为了让 Agent 能够精准修改代码而设计。它通过接收一组替换规则 (`replacements`)，在文件中定位 `original_text` 并将其替换为 `new_text`。它还支持 `replace_all` 选项来决定是全局替换还是单次替换。整个编辑过程同样建立在统一的工作目录之上，使得“读哪个文件”和“改哪个文件”始终保持一致。

### 2. 搜索检索工具 (Search Tools)

为了让 Agent 能够在庞大的代码库或文件系统中精准定位信息，`search_tool` 目录提供了强大的文件和文本检索能力：

* **Glob Tool (`glob_tool.py`)**：基于通配符的文件查找工具。它利用 `glob` 模块查找匹配特定模式的文件或目录。它支持递归搜索 (`recursive`)，并且可以选择是否包含隐藏文件 (`include_hidden`)，最多可返回默认 1000 个结果。和基础工具一样，`glob` 也会把相对模式统一解释为“相对于当前 workspace”，并尽量把结果以相对路径形式返回，方便 Agent 继续阅读和总结。
* **Grep Tool (`grep_tool.py`)**：基于正则表达式的文本搜索工具。它能够在指定目录或文件中搜索文本模式，支持区分大小写搜索和递归目录遍历。它还能通过 `include_pattern` 参数过滤特定类型的文件，最终返回包含文件名、行号、匹配文本的具体结果。这里的一个细节是：它也会统一按 workspace 解析路径，从而让“先 `glob` 找文件，再 `grep` 搜内容，再 `read` 打开文件”这一整套链路对“当前目录”的理解保持一致。

### 3. 工具核心层 (Tool Core)

仅仅拥有 `bash`、`read`、`write`、`edit`、`glob`、`grep` 这些具体工具还不够。对于一个真正要长期运行的 Agent 来说，更重要的是：**这些工具能否被统一发现、统一创建、统一执行、统一描述给模型**。因此，在 `tools/core/` 目录下，项目额外提供了一层通用的工具核心框架。

这一层并不是直接给 Agent 干活的“业务工具”，而是负责组织和管理工具的“基础设施”。它的存在，使得具体工具只需要关心自己的业务逻辑，而不需要反复去处理参数校验、实例复用、结果归一化等公共问题。

如果用一个更通俗的比喻来理解，可以把 `base_tool/` 和 `search_tool/` 看成“具体工人”，而 `tools/core/` 看成“工地的管理系统”。具体工人负责真正干活，管理系统负责安排这些工人怎样登记、怎样上岗、怎样统一汇报结果。这样设计的原因很简单：**如果每个工具既要干自己的活，又要自己处理注册、校验、异常、Prompt 描述，那代码会很快变乱，而且后续新增工具时也会越来越难维护。**

* **BaseTool (`base.py`)**：所有具体工具共享的统一基类。无论是 `BashTool`、`ReadTool`，还是 `GlobTool`、`GrepTool`，本质上都是 `BaseTool` 的子类。它负责执行前的参数校验、执行后的结果归一化，以及 `prompt_block()` 文本的统一导出。除此之外，它还额外提供了 `resolve_path()` 和 `relativize_path()` 这类公共能力，用来统一处理“相对路径到底相对于哪里”这个在 Agent 系统里非常容易出错的问题。可以把它理解成“所有工具共同遵守的一套模板”，这样每个工具只要专心实现自己的 `run()` 逻辑就够了。
* **ToolSpec / ToolContext / ToolResult (`types.py`)**：这三个数据结构分别承担不同职责。`ToolSpec` 用来描述工具的静态元信息，例如名称、说明、分类、输入 schema；`ToolContext` 用来描述工具运行时共享的上下文，例如工作目录和环境变量；`ToolResult` 用来统一工具的执行结果，确保所有工具都能以相似的格式向外返回成功状态、结果数据和错误信息。通俗地说，`ToolSpec` 像“工具说明书”，`ToolContext` 像“工具工作的环境”，`ToolResult` 像“工具干完活后交上来的回执”。在当前项目里，`ToolContext.workspace` 尤其重要，因为它决定了所有工具眼中的“当前目录”到底是什么。
* **ToolCatalog 与 discover_tools (`catalog.py`, `discover.py`)**：`ToolCatalog` 负责保存所有已注册工具的定义信息，而 `discover_tools()` 则负责扫描 `tools/` 目录，自动发现符合规则的工具类并注册进目录中。这样一来，新增工具时只要放在合适目录并遵循统一约定，就能被系统自动识别。可以把这两个模块理解成“工具花名册”和“负责点名的人”。
* **ToolFactory 与 ToolExecutor (`factory.py`, `executor.py`)**：`ToolFactory` 负责根据工具名称创建实例，并根据 `ToolSpec` 中的 `singleton` 策略决定是否复用已有实例；`ToolExecutor` 负责真正执行工具，并将未知工具、参数错误或运行异常统一整理成结构化结果返回给上层。也就是说，一个负责“把工具准备好”，一个负责“真正去调用工具并接住异常”。
* **ToolPromptRenderer 与 ToolService (`renderer.py`, `service.py`)**：`ToolPromptRenderer` 负责把工具元数据渲染成适合放进 Prompt 的说明文本；`ToolService` 则把“发现、创建、执行、渲染”这些能力组合成一个稳定入口，让主流程可以更简单地使用整套工具系统。前者更像“给大模型看的工具说明书生成器”，后者更像“对外统一服务窗口”。

从教学角度看，可以把 `tools/core/` 理解成整个工具系统的“底座”。`base_tool/` 和 `search_tool/` 提供的是 Agent 真正使用的能力，而 `tools/core/` 提供的是让这些能力长期稳定运行的方法。

从职责拆分的角度看，这样设计还有一个明显好处：当以后再增加新的工具时，通常只需要补一个新的工具类，而不需要把“参数校验、工具注册、错误处理、Prompt 描述”这些代码再抄一遍。也就是说，工具越多，这种分层设计的价值就越明显。

### 4. 统一的接口设计

在实现上，所有的 Tool 都遵循了一种高度一致的接口规范，这大大降低了 Agent 调用工具的认知负担：

* **结构化元信息定义**：每个工具类都通过 `ToolSpec` 来声明自己的名称、说明、分类和输入 schema，而不是把这些信息零散地写在多个属性里。这样做的好处是，工具定义天然就是结构化的，系统可以直接读取这些信息来做分类、渲染 Prompt 和实例管理。说得更直白一点，就是“工具先把自己介绍清楚”，后面的系统才能稳定地使用它。
* **Prompt 结构化导出**：每个工具类依然可以通过 `prompt_block()` 输出给大模型看的工具说明文本，但这一步已经不再依赖工具自己手工拼接全部逻辑，而是建立在 `ToolSpec` 的统一元数据之上。这使得 Agent 能够清晰地理解如何构造调用参数，也让 Prompt 文本和实际工具定义保持一致。这样设计的目的，是让“模型看到的工具说明”和“程序真正执行的工具定义”尽量保持同一套来源。
* **标准化执行流程**：所有工具的业务逻辑都被封装在 `run(self, tool_input: dict)` 方法中，而真正对外暴露的统一执行入口是 `execute()`。这意味着调用方不需要关心不同工具的内部差异，只需要按照统一协议传入参数、接收结果即可。对于 Agent 来说，这就像“无论调用哪种工具，入口形式都差不多”，学习成本会低很多。
* **统一结果结构与容错**：工具执行后通常返回 `ToolResult`，再由基类或执行层统一整理成包含 `"success"`、结果数据和错误信息的字典结构。这样无论执行成功还是发生错误（如文件不存在、路径不存在、正则语法错误、命令超时等），系统都能够稳定地向上层反馈结果，避免 Agent 因为单个工具出错而中断运行。也就是说，调用方不用去猜每个工具失败时会不会抛异常、会返回什么格式，而是总能拿到一套可预期的结果。
* **工作目录一致性**：所有文件类与搜索类工具，都会尽量基于统一的 workspace 解析相对路径。这样 `glob("*")`、`read("main_agent.py")`、`edit("main_agent.py")` 指向的是同一个“当前目录”，不会出现一个工具在项目根目录工作、另一个工具在子目录工作的混乱情况。对于刚接触 Agent 系统的同学来说，这一点非常关键，因为很多“Agent 好像会了，但总是找错文件”的问题，根源其实就在这里。
* **平台差异下的稳定执行**：当前项目运行在 Windows 环境中，因此 `bash` 工具实际会通过 PowerShell 执行命令。同时，在 Prompt 中也会明确提醒模型：如果只是列目录、搜索文件、读取内容，应优先使用 `glob`、`grep`、`read` 这类专用工具，而不是凡事都先去拼一条命令。这样做的目的，是减少因为平台命令差异带来的无意义失败。
* **统一入口与服务封装**：在主流程中，`utils/get_tools.py` 提供了 `get_registry()`、`execute_tool()`、`get_all_tools_prompt()` 等统一入口；而内部则由 `ToolService` 组织底层的 `Catalog`、`Factory`、`Executor` 和 `Renderer`。这使得主流程可以以较低的认知成本使用工具系统，而不必感知底层实现细节。简单来说，就是“主流程只管用，底层怎么组织由工具系统自己解决”。
* **控制指令与真实工具分流**：在 `main_agent.py` 中，像 `init_tasks`、`add_task`、`update_task_status`、`validate_tool` 这类名称虽然看起来像工具，但本质上属于主循环内部的控制动作；而 `read`、`write`、`edit`、`bash`、`glob`、`grep` 才是真正交给工具系统执行的外部能力。这样的分流设计，使得任务调度逻辑和工具调用逻辑保持了清晰边界。通俗地说，就是“做计划”和“拿工具干活”要分开，不然系统很容易越写越乱。

### 5. Agent 调用工具是如何串起来的？

对于刚接触 Agent 系统的同学来说，最容易疑惑的一点往往是：**“工具到底是谁在调用？是用户直接调，还是模型自己调？”**  

在 miniMaster 里，更准确的理解方式是：**用户只提出目标，真正决定下一步要不要调用工具、调用哪个工具、拿到结果后是否继续调用下一个工具，都是 Agent 在做。**

如果把这个过程写成“流程图式文字”，大致可以理解成：

`用户提问 -> Plan-Agent 判断这是直接回答还是需要执行任务 -> 如果需要执行任务，交给 Generator-Agent -> Generator-Agent 选择最合适的工具 -> 工具返回结构化结果 -> Generator-Agent 根据结果决定下一步 -> 任务完成后提交结论 -> Validate-Agent 再做核查 -> 最终返回结果`

再看一个更具体的例子。假设用户的问题是：**“帮我看看 `main_agent.py` 里有没有 `execute_runtime_tool` 这个函数。”**

Agent 的典型思路会像这样：

`用户提问 -> Plan-Agent 判断这是一个需要执行的任务 -> Generator-Agent 先调用 grep 搜索 execute_runtime_tool -> grep 返回命中文件和行号 -> Generator-Agent 再调用 read 读取对应文件片段 -> Generator-Agent 整理成结论 -> Validate-Agent 再次用 grep 或 read 核查 -> 返回答案`

这就是为什么工具设计不能只看“工具本身能不能用”，还要看“工具之间能不能顺畅接力”。单个工具再强，如果前一个工具的结果无法成为后一个工具的输入，整个 Agent 流程依然会很别扭。


---

## 2. Prompt 设计与动作协议 (Prompting)

在很多初学者的理解里，Prompt 好像就是“给模型说一句话”。但在一个真正可运行的 Agent 系统中，Prompt 远不只是“说一句话”这么简单。它至少要同时解决三个问题：

* **告诉模型当前要做什么**
* **告诉模型它可以做哪些动作**
* **告诉程序应该怎样稳定地解析模型的输出**

如果这三件事混在一起手写，很容易出现一种常见问题：Prompt 里写的是一套规则，程序真正允许的是另一套规则，模型输出又是第三套格式。这样系统一跑起来，就会经常出现“模型好像答得对，但程序接不住”的情况。

因此，在 miniMaster 中，Prompt 相关能力被单独拆到了 `prompting/` 目录下，主要分成三块：**提示词构造、动作策略、输出协议**。

### 1. Prompt 构造层 (`builders.py`)

`builders.py` 负责生成不同 Agent 所使用的 Prompt。它并不是简单地拼接几段字符串，而是在做一件更重要的事：**把“角色职责、当前上下文、可用工具、输出要求”组合成一份适合当前场景的工作说明书。**

当前项目中主要有四个 Prompt 构造函数：

* **`build_plan_prompt()`**：负责为 Plan-Agent 构造 Prompt。它不仅会把用户问题和当前任务列表传进去，还会明确告诉模型：哪些情况需要拆任务，哪些情况只需要直接回复用户。比如“你好”“你有哪些工具可以使用？”这类输入，在当前项目中就不应该被误判成一个复杂任务，而是应该直接通过 `respond_to_user` 自然回复。
* **`build_generator_prompt()`**：负责为 Generator-Agent 构造 Prompt。这里会把当前子任务、工作记忆、基础工具说明、搜索工具说明全部组合进去。这样 Generator 不是盲目“拍脑袋决定下一步”，而是会结合自己刚刚做过的动作继续推进。
* **`build_validate_prompt()`**：负责为 Validate-Agent 构造 Prompt。它的重点不是“继续完成任务”，而是“独立验证当前结论是否真的成立”。因此这里会重点提供当前任务结论、验证阶段记忆，以及验证工具的使用规则。
* **`build_summary_prompt()`**：负责为记忆压缩流程生成 Prompt。当 `WorkingMemory` 过长时，系统会把较早的记录和旧摘要一起交给模型压缩，从而得到一段更短、但仍然保留关键信息的摘要文本。

从教学角度看，这一层可以理解成“给不同角色写不同版本的任务说明书”。Plan-Agent、Generator-Agent、Validate-Agent 都是 Agent，但它们的职责不同，因此看到的 Prompt 本来就不应该一样。

### 2. 动作策略层 (`policies.py`)

如果说 `builders.py` 负责“怎么说”，那么 `policies.py` 负责“允许做什么”。

这里的核心思想非常简单：**不同角色，只开放和它职责匹配的动作。**

* **Plan-Agent**：负责高层调度，所以开放的是 `init_tasks`、`add_task`、`update_task_status`、`subagent_tool`、`respond_to_user`。它的任务是决定流程，而不是亲自去读文件、写文件。
* **Generator-Agent**：负责真正执行任务，因此开放的是 `bash`、`read`、`write`、`edit`、`glob`、`grep` 等底层工具，同时保留 `update_task_conclusion`，用于提交当前任务的结论。
* **Validate-Agent**：负责核查结果，因此保留的是 `bash`、`read`、`glob`、`grep` 这些偏验证性质的能力，以及最终输出验证结论的 `validate_tool`。

这样设计的好处很直观：每个 Agent 都不会“权限过大”。Plan-Agent 不会一上来就跳过规划直接乱改文件，Validate-Agent 也不会一边验证一边偷偷把结果改掉。职责边界越清楚，系统的行为就越稳定。

### 3. 输出协议层 (`protocol.py`)

除了告诉模型“要做什么”和“能做什么”，还必须解决最后一个工程问题：**模型输出后，程序怎么稳定接住？**

当前项目采用的是**JSON-only 动作协议**。也就是说，Agent 的输出目标不是一段自由散文，而是一个明确的 JSON 对象，例如：

```json
{
  "think": "需要先搜索目标文件",
  "tool": "grep",
  "parameters": {
    "pattern": "execute_runtime_tool",
    "path": ".",
    "recursive": true
  }
}
```

`protocol.py` 负责的事情主要有三类：

* **提取 JSON**：即使模型偶尔输出了带代码块包裹的 JSON 或额外说明，也尽量把中间真正的 JSON 对象提取出来。
* **校验动作是否合法**：例如当前 Agent 是否真的允许使用这个动作，参数是否满足 schema 要求。
* **容错处理**：现实里模型并不总是百分之百听话，它有时会输出 `action` 而不是 `tool`，或者输出 `args` 而不是 `parameters`。因此协议层会先做一层轻量归一化，再继续校验，避免系统因为这种小漂移直接崩掉。

对于初学者来说，可以把这一层理解成“Agent 输出的翻译官 + 安检员”。翻译官负责把模型的话整理成程序能懂的结构，安检员负责确认这份结构到底合不合法。

### 4. 统一的模型调用入口

在 `main_agent.py` 中，三个 Agent 最终都不会各自维护一套完全独立的模型调用代码，而是统一通过 `call_agent_model()` 发起模型请求，再通过 `request_agent_action()` 完成“调用模型 -> 解析输出 -> 校验动作”这一整套流程。

这样做的原因也很简单：**Plan-Agent、Generator-Agent、Validate-Agent 的职责不同，但它们和模型交互的基本动作其实是一样的。** 如果三处都重复写一次请求代码、解析代码、校验代码，不但啰嗦，也很容易某一处改了、另一处忘了改。

从教学角度看，这个设计还有一个好处：学生在阅读主循环时，不需要先陷进大量重复的 API 调用细节，而是可以把注意力放在真正重要的地方，也就是“每个 Agent 在什么时候被唤醒、做了什么决策、怎样把结果交给下一层”。

---

## 3. 状态管理与动态工作记忆 (State Management)

在 harness 的设计中，状态和记忆管理十分重要。它要让 Agent 知道各个任务当前处于什么状态，也要让 Agent 记得自己已经尝试过什么方法，从而更稳定地做出下一步决策。
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

## 4. 多智能体编排 (multi-agent Orchestration)

**“规划-执行-验证”三层嵌套循环 (Plan-Generate-Validate)** 的多智能体协作架构。各个 Agent 均遵循 ReAct 范式。相对于只做 plan & solve 的方式，这里额外增加了 validate 这一层：每次任务完成后先进行校验，校验通过后，才真正进入下一层流程。这样做的目的，是保证系统在长期任务中的稳定性。
每个 Agent 各司其职，拥有独立的 Prompt 和职责边界：

#### 4.1 第一层循环：Plan-Agent (全局调度)

Plan-Agent 是整个系统的大脑。它不直接干脏活累活（比如写代码或查文件），它的主要职责是审视用户的原始需求，并维护 `ToDoList` 任务看板。

它的核心循环受 `max_iter` 控制，通过专属的任务管理动作（如 `init_tasks`, `add_task`）来拆解步骤。当它明确了当前要做的具体任务后，会调用 `subagent_tool`，将任务“外包”给下层的执行智能体。

不过在当前项目里，Plan-Agent 并不只会“拆任务”。如果用户只是简单问候、咨询能力，或者提出一个根本不需要进入任务调度的问题，它也可以直接使用 `respond_to_user` 给出自然回复。这样做的好处是：**不是每一句用户输入都要被硬塞进复杂的工作流里。**

也就是说，Plan-Agent 首先判断的是“这句话需要不需要进入执行流程”，而不是上来就默认拆任务。它的核心路由大致如下：

```python
        # 伪代码：Plan-Agent 的核心路由逻辑
        if plan_tool == "init_tasks":
            to_do_list.init_tasks(task_list)
            continue
        elif plan_tool == "respond_to_user":
            print(message)
            break
        elif plan_tool == "subagent_tool":
            curr_task_name = plan_params.get("task_name")
            curr_task = to_do_list.get_task_by_name(curr_task_name)
            
            # 唤醒下一层的 Generator-Agent 执行具体任务
            # 进入第二层循环...
```

#### 4.2 第二层循环：Generator-Agent (执行者)

当 `subagent_tool` 被触发后，系统进入内部的 `while True` 循环，唤醒 Generator-Agent。这是真正干活的角色。

为了适应重度代码编写和文件搜索，我为 Generator 赋予了非常宽裕的独立记忆（`keep_latest_n=8, max_chars=80000`），并向它开放了所有的 `base_tool` 和 `search_tool`。

在真正开始行动之前，主程序会先通过 `build_generator_prompt()` 组装一份执行提示词，再通过统一的 `request_agent_action()` 调用模型并解析出动作。随后，Generator 会在这个子循环中不断尝试：搜索文件 -> 读取代码 -> 修改代码 -> 执行命令 -> 继续观察结果。

在这个过程中，上一节提到的**动态记忆压缩机制**会默默保障它的上下文不会溢出。与此同时，`main_agent.py` 还会把控制动作和真实工具分开处理：像 `update_task_conclusion` 这类属于流程控制，而 `read`、`grep`、`glob` 这些才是真正交给工具系统执行的能力。

当 Generator 认为当前子任务已经搞定时，它必须调用一个特殊的动作 `update_task_conclusion` 来提交成果：

```python
                if gen_tool != "update_task_conclusion":
                    # 正常执行基础或搜索工具
                    result = execute_runtime_tool(gen_tool, gen_params)
                    generator_memory.add_memory(gen_step, gen_tool, gen_params, result)
                    continue  # 继续第二层循环干活
                else:
                    # Generator 认为完成了，提交结论
                    conclusion = gen_params.get("conclusion", "")
                    to_do_list.update_task_conclusion(curr_task_name, conclusion)
                    # 触发质检，进入第三层循环...
```

#### 4.3 第三层循环：Validate-Agent (评估者)

当 Generator 提交成果后，第三层循环启动，Validate-Agent 接管控制权。

它是一个拥有完全独立、清空记忆的全新实例，它的 Prompt 指令明确要求：**验证当前任务的完成是否有效**。它可以自己调用检索或终端工具去核实 Generator 的工作，最后必须调用 `validate_tool` 输出 `有效` 或 `无效` 以及原因。

在当前项目里，Validate-Agent 也会通过和 Generator 相同的统一入口 `request_agent_action()` 调用模型，但它的 Prompt 和动作集合是另一套。它关注的不是“怎样把事情做完”，而是“已有证据是否足以证明事情真的做完了”。例如，验证目录结构时，它通常更适合优先使用 `glob`；验证文件内容时，则更适合优先使用 `read` 或 `grep`。

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
