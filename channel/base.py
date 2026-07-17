from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING

from contracts.message import Message
from message.message_bus import MessageBus

if TYPE_CHECKING:
    from message.message_post_bus import MessagePost


class BaseChannel(ABC):
    name: str
    channel_id: str

    def __init__(self, message_bus: MessageBus | None = None) -> None:
        self._message_bus = message_bus

    async def start(self) -> None:
        """Start channel resources. Channels without resources may no-op."""

    async def end(self) -> None:
        """Stop channel resources. Channels without resources may no-op."""

    def receive_message(self, message: MessagePost | str) -> None:
        raise NotImplementedError

    def send_message(self, prompt: str | None = None) -> Message:
        raise NotImplementedError

    def build_message(
        self,
        content: str,
        user_id: str = "01",
        target: str = "agent",
        *,
        session_id: str | None = None,
        kind: str = "text",
        metadata: dict | None = None,
    ) -> Message:
        return Message(
            user_id=user_id,
            target=target,
            channel_id=self.channel_id,
            session_id=session_id,
            kind=kind,
            content=content,
            metadata=metadata or {},
        )

    def push_message(self, message: Message) -> None:
        if self._message_bus is None:
            raise RuntimeError(f"{self.name} channel has no message bus")
        self._message_bus.push_message(message)


class ChannelBus:
    def __init__(self) -> None:
        self.channels: dict[str, BaseChannel] = {}

    def register_channel(self, channel: BaseChannel) -> None:
        self.channels[channel.name] = channel

    def get_channel(self, channel_name: str) -> BaseChannel | None:
        return self.channels.get(channel_name)

    def dispatch_post(self, post: MessagePost) -> None:
        channel = self.get_channel(post.channel)
        if channel:
            channel.receive_message(post)

    def dispatch_message(self, channel_name: str, message: str) -> None:
        """Compatibility wrapper for legacy callers."""
        channel = self.get_channel(channel_name)
        if channel:
            channel.receive_message(message)
