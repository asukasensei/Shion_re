import asyncio
from threading import Event

from agent.main_agent import MainAgent
from contracts.message import Message
from event.event_bus import EventBus
from message.message_bus import MessageBus
from message.message_post_bus import MessagePost, MessagePostBus
from contracts.event import Event


class Dispatcher:
    def __init__(
        self,
        message_bus: MessageBus,
        message_post_bus: MessagePostBus,
        event_bus: EventBus,
        main_agent: MainAgent,
    ) -> None:
        self.message_bus = message_bus
        self.message_post_bus = message_post_bus
        self.event_bus = event_bus
        self.main_agent = main_agent

    def dispatch_once(self, block: bool = True, timeout: float = 0.2) -> bool:
        message = self.message_bus.pop_message(block=block, timeout=timeout)
        if message is None:
            return False

        try:
            asyncio.run(self._dispatch_message(message))
        except Exception as exc:
            self.message_post_bus.push_message(
                MessagePost(channel=message.channel_id, content=f"[agent error] {exc}")
            )
        finally:
            self.message_bus.task_done()

        return True

    async def _dispatch_message(self, message: Message) -> None:
        response_parts: list[str] = []

        try:
            async for post in self.main_agent.run(message):
                self._push_post(message, post)
                response_parts.append(post.content)
        finally:
            event = Event(
                event_type="session_write",
                event_id=f"session-write:{message.message_id}",
                priority="immediate",
                content={
                    "time": message.created_at,
                    "user": message.content,
                    "agent_response": "".join(response_parts),
                },
            )
            self.event_bus.publish(event)

    def run_forever(self, stop_event: Event) -> None:
        while not stop_event.is_set():
            self.dispatch_once(block=True, timeout=0.2)

    def _push_post(self, source: Message, post: MessagePost | str | dict) -> None:
        if isinstance(post, MessagePost):
            self.message_post_bus.push_message(post)
            return
        if isinstance(post, str):
            self.message_post_bus.push_message(
                MessagePost(channel=source.channel_id, content=post)
            )
            return
        self.message_post_bus.push_message(
            MessagePost(channel=source.channel_id, content=str(post))
        )
