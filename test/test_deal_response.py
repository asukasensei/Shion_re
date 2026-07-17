import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.deal_response import DealResponse


def main() -> None:
    content = input("请输入测试消息: ")

    def print_segment(segment: str) -> None:
        print(f"[DealResponse 输出] {segment}")

    dealer = DealResponse(print_segment)

    print("\n开始逐步 feed:")
    for char in content:
        print(f"[feed] {char}")
        dealer.feed(char)
        time.sleep(0.03)

    print("[flush]")
    dealer.flush()


if __name__ == "__main__":
    main()
