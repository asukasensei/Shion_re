from config.config import Config
from contracts.event import Event
from memory.session.compressor import SessionCompressor


class SessionWriteHandler:
    def __init__(self) -> None:
        settings = Config().config.get("memory", {})
        self.compressor = SessionCompressor(
            session_limit=settings.get("session_compress_chars", 1000),
            tail_limit=settings.get("session_tail_chars", 500),
            recent_limit=settings.get("recent_max_chars", 500),
        )

    async def __call__(self, event: Event) -> None:
        await self.compressor.append_and_compress(event.content)
        
