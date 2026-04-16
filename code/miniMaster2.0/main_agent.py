from app.bootstrap import bootstrap_runtime
from app.orchestration import run_main_loop


def main():
    """程序入口。"""
    try:
        runtime = bootstrap_runtime()
        run_main_loop(runtime)
        print("\n程序结束。")
    except Exception as exc:
        print(f"\n程序异常退出: {exc}")
        raise


# ==========================================
# 主体逻辑
# ==========================================
if __name__ == "__main__":
    main()
