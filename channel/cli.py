from channel.base import BaseChannel
from contracts.message import Message


class CLIChannel(BaseChannel):
    name = "cli"
    channel_id = "cli"

    def receive_message(self, message: str) -> None:
        print(f"\n{message}")

    def send_message(self, prompt: str | None = None) -> Message:
        content = input(prompt or "> ")
        return self.build_message(content=content)


cli = CLIChannel
