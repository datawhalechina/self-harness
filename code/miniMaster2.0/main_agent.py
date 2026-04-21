"""miniMaster 程序入口。

这个文件故意保持很薄，只负责两件事：
1. 调用 bootstrap 阶段，把运行时依赖一次性装配好。
2. 把控制权交给顶层主循环，让后续的 Planner / Executor / Validator
   协作逻辑都在 engine 层内部完成。

教学上可以把它理解为传统应用中的 `main()`：入口越薄，系统的职责分层越清楚。
"""

from bootstrap.runtime import bootstrap_runtime
from engine.main_loop import run_main_loop


def main():
    """程序入口。

    这里不直接写业务逻辑，而是把“初始化”和“运行循环”两个阶段拆开。
    这样一来，学生阅读代码时可以很快看出：
    - 运行前需要准备哪些共享对象；
    - 真正的 Agent 行为是从哪里开始接管的。
    """
    try:
        # 第一步：装配 client、tool service、memory、todo list 等运行时依赖。
        runtime = bootstrap_runtime()
        # 第二步：进入多智能体编排主循环。
        run_main_loop(runtime)
        print("\n程序结束。")
    except Exception as exc:
        # 入口层只做统一兜底，真正的错误定位仍交给上层堆栈。
        print(f"\n程序异常退出: {exc}")
        raise


# ==========================================
# 主体逻辑
# ==========================================
if __name__ == "__main__":
    main()
