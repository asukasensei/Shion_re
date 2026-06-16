import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from contracts.message import Message
from contracts.state.state import State


def message_to_state(content: str) -> State:
    message = Message(
        user_id="test-user",
        channel_id="cli",
        target="agent",
        content=content,
    )
    return State.from_message(message)


def main() -> None:
    content = input("请输入测试消息: ")
    state = message_to_state(content)

    print("\nState 内容:")
    print(
        json.dumps(
            state.to_dict(),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
