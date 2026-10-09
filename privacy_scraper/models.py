from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Area(str, Enum):
    """Sezioni del sito da cui si scaricano i media (come le "areas" di of-scraper)."""

    POSTS = "posts"
    MESSAGES = "messages"
    STORIES = "stories"
    PURCHASED = "purchased"


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


@dataclass(frozen=True)
class Creator:
    id: str
    username: str


@dataclass(frozen=True)
class Media:
    id: str
    url: str
    media_type: MediaType
    area: Area
    creator: Creator
    post_id: str
    created_at: datetime
    text: str = ""
    # Estensione nota a priori, quando l'URL non la contiene.
    ext: str = ""

    @property
    def is_hls(self) -> bool:
        return self.url.split("?", 1)[0].lower().endswith(".m3u8")

    @property
    def extension(self) -> str:
        if self.ext:
            return self.ext
        if self.is_hls:
            return "mp4"
        path = self.url.split("?", 1)[0].rsplit("/", 1)[-1]
        if "." in path:
            return path.rsplit(".", 1)[-1].lower()
        return {MediaType.IMAGE: "jpg", MediaType.VIDEO: "mp4", MediaType.AUDIO: "mp3"}[self.media_type]
