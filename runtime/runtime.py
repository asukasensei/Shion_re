from threading import Event, Thread

from agent.main_agent import MainAgent
from channel.base import ChannelBus
from channel.cli import CLIChannel
from event.event_bus import EventBus
from message.message_bus import MessageBus
from message.message_post_bus import MessagePostBus
from runtime.dispatcher import Dispatcher
from background_worker.backworker import BackgroundWorker
from memory.diary.diary import DiaryService

import asyncio



class Runtime:
    def __init__(self) -> None:
        self.event_bus = EventBus()
        self.message_bus = MessageBus()
        self.message_post_bus = MessagePostBus()
        self.channel_bus = ChannelBus()
        self.cli_channel = CLIChannel()
        self.channel_bus.register_channel(self.cli_channel)
        self.main_agent = MainAgent()
        self.diary_service = DiaryService()
        self.dispatcher = Dispatcher(
            message_bus=self.message_bus,
            message_post_bus=self.message_post_bus,
            main_agent=self.main_agent,
            event_bus=self.event_bus,
        )
        self.background_worker = BackgroundWorker(
            event_bus=self.event_bus
        )
        self.stop_event = Event()

    def push_channel_message(
        self,
        channel_id: str,
        content: str,
        user_id: str = "01",
        target: str = "agent",
    ) -> None:
        channel = self.channel_bus.get_channel(channel_id)
        if channel is None:
            raise ValueError(f"Unknown channel: {channel_id}")
        self.message_bus.push_message(
            channel.build_message(content=content, user_id=user_id, target=target)
        )

    def run(self) -> None:
        print("正在加载程序并整理记忆，请稍候……")
        try:
            asyncio.run(self.diary_service.process_if_new_day())
        except Exception as e:
            print(f"处理日记时发生错误，原始记录已保留: {e}")
        print("程序已准备就绪，输入 /exit 或 /quit 退出。")
        dispatcher_thread = Thread(
            target=self.dispatcher.run_forever,
            args=(self.stop_event,),
            daemon=True,
        )
        output_thread = Thread(target=self._run_output_loop, daemon=True)
        background_thread = Thread(
            target=self.background_worker.run_forever,
            args=(self.stop_event,),
            name="background-worker",
            daemon=False,
        )
        dispatcher_thread.start()
        output_thread.start()
        background_thread.start()

        try:
            while not self.stop_event.is_set():
                message = self.cli_channel.send_message()
                if message.content in {"/exit", "/quit"}:
                    self.stop_event.set()
                    break
                self.message_bus.push_message(message)
        except KeyboardInterrupt:
            self.stop_event.set()
        finally:
            dispatcher_thread.join(timeout=1)
            output_thread.join(timeout=1)
            background_thread.join()

    def _run_output_loop(self) -> None:
        while not self.stop_event.is_set():
            post = self.message_post_bus.pop_message(block=True, timeout=0.2)
            if post is None:
                continue
            try:
                self.channel_bus.dispatch_message(post.channel, post.content)
            finally:
                self.message_post_bus.task_done()
