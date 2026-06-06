from contracts.message import Message


class BaseChannel:
    name: str
    channel_id: str

    def receive_message(self, message: str) -> None:
        raise NotImplementedError

    def send_message(self, prompt: str | None = None) -> Message:
        raise NotImplementedError

    def build_message(
        self,
        content: str,
        user_id: str = "01",
        target: str = "agent",
    ) -> Message:
        return Message(
            user_id=user_id,
            target=target,
            channel_id=self.channel_id,
            content=content,
        )


class ChannelBus:
    def __init__(self) -> None:
        self.channels: dict[str, BaseChannel] = {}

    def register_channel(self, channel: BaseChannel) -> None:
        self.channels[channel.name] = channel

    def get_channel(self, channel_name: str) -> BaseChannel | None:
        return self.channels.get(channel_name)

    def dispatch_message(self, channel_name: str, message: str) -> None:
        channel = self.get_channel(channel_name)
        if channel:
            channel.receive_message(message)
