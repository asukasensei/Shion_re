from collections.abc import Callable
import re


class DealResponse:
    def __init__(self, send_func: Callable[[str], None]):
        self.buffer = ""
        self.send_func = send_func
        self.punctuation_pattern = re.compile(r"[。；,，.;]")


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

        # 只要缓冲区中出现标点，就尝试切分
        while True:
            match = self.punctuation_pattern.search(self.buffer)
            if not match:
                break

            end_index = match.end()
            segment = self.buffer[:end_index]

            # 已存文字大于两个字才发送
            if self._text_len(segment) > 2:
                self.send_func(segment)
                self.buffer = self.buffer[end_index:]
            else:
                # 如果太短，不发送，继续等待后续内容
                break

    def flush(self):
        """
        流式输出结束后，发送剩余内容
        """
        if self._text_len(self.buffer) > 0:
            self.send_func(self.buffer)
            self.buffer = ""
