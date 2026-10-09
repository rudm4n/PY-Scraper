"""Credenziali della sessione del browser.

Come of-scraper, lo strumento non fa login con password: riusa la sessione
che hai già nel browser (cookie + header). I valori stanno in auth.json nella
cartella di configurazione, con permessi 600, e non vanno mai committati.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import config_dir


class AuthError(RuntimeError):
    pass


@dataclass
class Auth:
    cookie: str = ""
    user_agent: str = ""
    # Header extra che il sito richiede (es. Authorization, x-bc, x-csrf...).
    # Quali servono davvero si vedrà dal file HAR.
    extra_headers: dict[str, str] = field(default_factory=dict)

    def headers(self) -> dict[str, str]:
        if not self.cookie and not self.extra_headers:
            raise AuthError("Credenziali mancanti: esegui prima `privacy-scraper auth`.")
        headers = {"Accept": "application/json, text/plain, */*"}
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        if self.cookie:
            headers["Cookie"] = self.cookie
        headers.update(self.extra_headers)
        return headers

    @staticmethod
    def default_path() -> Path:
        return config_dir() / "auth.json"

    @classmethod
    def load(cls, path: Path | None = None) -> "Auth":
        path = path or cls.default_path()
        if not path.exists():
            raise AuthError(f"{path} non esiste: esegui prima `privacy-scraper auth`.")
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            cookie=data.get("cookie", ""),
            user_agent=data.get("user_agent", ""),
            extra_headers=dict(data.get("extra_headers", {})),
        )

    def save(self, path: Path | None = None) -> Path:
        path = path or self.default_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
        return path
