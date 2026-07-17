from collections.abc import Callable
import re


class DealResponse:
    def __init__(self, send_func: Callable[[str], None]):
        self.buffer = ""
        self.send_func = send_func
        self.punctuation_pattern = re.compile(r"[。！？；，,.!?;]")


    def _text_len(self, text: str) -> int:
        """
        计算有效文字长度：
        去掉空白和标点后再统计长度
        """
        cleaned = re.sub(r"[。！？；，,.!?;\s]", "", text)
        return len(cleaned)

    def feed(self, chunk: str):
        """
        接收大模型流式输出的一小段文本
        """
        if not chunk:
            return

        self.buffer += chunk
        search_start = 0
        while True:
            match = self.punctuation_pattern.search(self.buffer, search_start)
            if not match:
                break

            end_index = match.end()
            segment = self.buffer[:end_index]
            if self._text_len(segment) > 2:
                self.send_func(segment)
                self.buffer = self.buffer[end_index:]
                search_start = 0
            else:
                # 短句暂时留在缓冲区，后续文本会与它一起发送；不能
                # 从 buffer 中移除，否则诸如“你好。”这样的回复会丢失。
                search_start = end_index

    def flush(self):
        """
        流式输出结束后，发送剩余内容
        """
        if self.buffer.strip():
            self.send_func(self.buffer)
        self.buffer = ""
