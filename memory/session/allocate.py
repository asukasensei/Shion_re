
from config.config import Config
from memory.session.jsonl_store import JsonlConversationStore

SUPPORTED_BACKENDS = {
    "jsonl": JsonlConversationStore(),
    "redis": None,  # Placeholder for RedisConversationStore
}



class SessionAllocator:
    def __init__(self, config: Config) -> None:
        self.path = config.config["conversation_store"]["jsonl_path"]
        self.SUPPORTED_BACKENDS = {
        "jsonl": JsonlConversationStore(self.path),
        "redis": None,  # Placeholder for RedisConversationStore
    }
        self.config = config.config["conversation_store"]["backend"]
        self.store_method = self.SUPPORTED_BACKENDS.get(self.config)

    def append()->None:
        pass

