"""
外部服務抽象。

為什麼要介面: 現在只有 NCHC，但之後可能接 AORUS 當第二路由。
有介面的話那時只是多一個檔案，呼叫端一行都不用改。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ASRResult:
    text: str
    avg_logprob: float | None = None
    elapsed_ms: float = 0.0


class ASRProvider(ABC):
    @abstractmethod
    async def transcribe(
        self,
        wav_bytes: bytes,
        language: str,
        prompt: str = "",
    ) -> ASRResult: ...


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        model: str,
        messages: list[dict],
        stream: bool = False,
    ): ...
