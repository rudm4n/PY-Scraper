from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_TEMPLATE = "{username}/{area}/{media_type}/{date}_{post_id}_{media_id}.{ext}"


def config_dir() -> Path:
    base = os.environ.get("PRIVACY_CONFIG_DIR")
    if base:
        return Path(base)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / "privacy-scraper"


@dataclass
class Config:
    save_dir: str = str(Path.home() / "privacy-downloads")
    filename_template: str = DEFAULT_TEMPLATE
    max_concurrent_downloads: int = 4
    request_delay_seconds: float = 0.5
    areas: list[str] = field(
        default_factory=lambda: ["posts", "messages", "stories", "purchased"]
    )

    @property
    def db_path(self) -> Path:
        return Path(self.save_dir) / ".privacy.db"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_dir() / "config.json"
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: Path | None = None) -> Path:
        path = path or config_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path
