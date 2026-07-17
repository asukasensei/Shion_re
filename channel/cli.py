from channel.base import BaseChannel
from contracts.message import Message
from message.message_post_bus import MessagePost


class CLIChannel(BaseChannel):
    name = "cli"
    channel_id = "cli"

    def receive_message(self, message: MessagePost | str) -> None:
        content = message.content if isinstance(message, MessagePost) else message
        if content:
            print(f"\n{content}")

    def send_message(self, prompt: str | None = None) -> Message:
        content = input(prompt or "> ")
        return self.build_message(content=content)


cli = CLIChannel
