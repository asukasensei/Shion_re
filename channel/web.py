from channel.base import BaseChannel
from contracts.message import Message
from message.message_post_bus import MessagePost

class WebChannel(BaseChannel):
    name = "web"
    channel_id = "web"

    def receive_message(self, message: MessagePost | str) -> None:
        content = message.content if isinstance(message, MessagePost) else message
        print(f"\n{content}")

    def send_message(self, content: dict) -> Message:
        return self.build_message(
            content=str(content.get("content", "")),
            user_id=content.get("user_id", "01"),
            target=content.get("target", "agent"),
            session_id=content.get("session_id"),
        )
