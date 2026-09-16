"""
訊息格式的唯一真實來源。

前後端都照這份。改這裡的時候記得同步 web/js/store.js。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Layer(str, Enum):
    ASR = "ASR"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


@dataclass
class Segment:
    """
    Server → Client。

    重要規則:
      id       偵測到開口的那一刻就發，不是等切完才發
      rev      單調遞增；前端收到比現有更舊的 rev 直接丟棄
      replaces L3 合併句子時用；前端刪除列表內全部 id，插入新的
    """
    id: str
    rev: int
    layer: Layer
    t_start: float
    t_end: float
    lang: str = ""          # 來源語言。前端用它設 lang 屬性，
                            # 中日共用漢字字形不同，不標會選錯字體。
    text: str = ""
    translation: Optional[str] = None
    replaces: list[str] = field(default_factory=list)

    def to_message(self) -> dict:
        return {
            "type": "segment",
            "id": self.id,
            "rev": self.rev,
            "layer": self.layer.value,
            "t_start": round(self.t_start, 2),
            "t_end": round(self.t_end, 2),
            "lang": self.lang,
            "text": self.text,
            "translation": self.translation,
            "replaces": self.replaces,
        }


# Client → Server
#   {"type": "start", "source_lang": "zh", "target_lang": "en",
#    "glossary": ["Zenoh", "ROS 2"]}
#   {"type": "audio", "seq": 1234}        // 後接 binary frame
#   {"type": "stop"}
#   {"type": "ping"}
