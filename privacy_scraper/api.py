"""Client delle API di Privacy (privacy.com.br).

Endpoint ricavati dai file HAR del sito (tutti su service.privacy.com.br,
autenticati con l'header Authorization della sessione del browser):

- abbonamenti: GET /subscriptionmanager/subscriptions/active?page=N (da 1)
- post:        GET /timelinequeries/profile/{offset}/{limit}/{handle}
- token video: POST /mediavideotoken/generate {"file_id": ...}

Messaggi, storie e acquisti non sono ancora nei HAR: quei metodi sollevano
NotImplementedError invece di inventare endpoint.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import urlsplit

import httpx

from .auth import Auth
from .models import Area, Creator, Media, MediaType

BASE_URL = "https://service.privacy.com.br"
SITE_ORIGIN = "https://privacy.com.br"
# Il sito chiede i post a blocchi di 10.
PAGE_SIZE = 10
# Limite di sicurezza contro paginazioni che non finiscono mai.
MAX_PAGES = 10_000

_MEDIA_TYPES = {
    "image": MediaType.IMAGE,
    "gif": MediaType.IMAGE,
    "video": MediaType.VIDEO,
    "audio": MediaType.AUDIO,
}
_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "heic"}


class ApiError(RuntimeError):
    pass


def site_headers() -> dict[str, str]:
    """Header che il browser manda verso i server di Privacy."""
    return {"Origin": SITE_ORIGIN, "Referer": SITE_ORIGIN + "/"}


def _parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def image_ext(url: str) -> str:
    """Estensione originale di un'immagine.

    Gli URL di image.privacy.com.br finiscono con un JSON in base64 che
    contiene la chiave del file (es. ".../2026-10-9/xyz--Nome.jpg").
    """
    segment = urlsplit(url).path.rsplit("/", 1)[-1]
    try:
        raw = base64.b64decode(segment + "=" * (-len(segment) % 4))
        key = json.loads(raw)["key"]
    except (binascii.Error, ValueError, KeyError, TypeError):
        return ""
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    if ext == "jpeg":
        ext = "jpg"
    return ext if ext in _IMAGE_EXTS else ""


def parse_post_media(
    post: dict[str, Any], creator: Creator, area: Area, stats: Counter | None = None
) -> Iterator[Media]:
    """Media scaricabili di un post: salta quelli bloccati e quelli con DRM.

    Se c'è stats, conta i media visti per motivo ("ok", "locked", "drm", "unknown").
    """
    stats = stats if stats is not None else Counter()
    post_id = str(post.get("postId", ""))
    created = _parse_date(post.get("publishedDate"))
    text = post.get("description") or ""
    for m in post.get("medias") or []:
        media_type = _MEDIA_TYPES.get(str(m.get("type", "")).lower())
        url = m.get("url")
        if m.get("isLocked") or not url:
            stats["locked"] += 1
            continue
        if not m.get("mediaId") or media_type is None:
            stats["unknown"] += 1
            continue
        if m.get("drmMediaId"):
            stats["drm"] += 1
            continue
        stats["ok"] += 1
        ext = ""
        if media_type is MediaType.IMAGE:
            ext = "gif" if m.get("type") == "gif" else image_ext(url)
        yield Media(
            id=str(m["mediaId"]),
            url=url,
            media_type=media_type,
            area=area,
            creator=creator,
            post_id=post_id,
            created_at=created,
            text=text,
            ext=ext,
        )


class PrivacyAPI:
    def __init__(self, auth: Auth, *, delay: float = 0.5, client: httpx.Client | None = None):
        self._delay = delay
        # Riepilogo dell'ultima chiamata a media(): post letti e media per motivo.
        self.stats: Counter = Counter()
        self.client = client or httpx.Client(
            base_url=BASE_URL,
            headers={**auth.headers(), **site_headers()},
            timeout=httpx.Timeout(30.0, read=120.0),
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, path: str, retries: int = 5, **kwargs: Any) -> Any:
        """Richiesta con pausa tra le chiamate e backoff su 429/5xx."""
        for attempt in range(1, retries + 1):
            time.sleep(self._delay)
            resp = self.client.request(method, path, **kwargs)
            if resp.status_code in (401, 403):
                raise ApiError(
                    f"{resp.status_code} su {path}: sessione scaduta o header mancanti, "
                    "riesegui `privacy-scraper auth`."
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == retries:
                    break
                wait = float(resp.headers.get("Retry-After", 2**attempt))
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise ApiError(f"{path}: troppi tentativi falliti (ultimo status {resp.status_code})")

    def get_json(self, path: str, params: dict[str, Any] | None = None, retries: int = 5) -> Any:
        return self._request("GET", path, retries, params=params)

    def post_json(self, path: str, body: dict[str, Any], retries: int = 5) -> Any:
        return self._request("POST", path, retries, json=body)

    # ---- endpoint del sito ---------------------------------------------------

    def me(self) -> dict[str, Any]:
        """Profilo dell'utente loggato, usato per verificare le credenziali."""
        return self.get_json("/profile/users/me/context")

    def subscriptions(self) -> list[Creator]:
        """Creator a cui sei abbonato (abbonamenti attivi)."""
        creators: dict[str, Creator] = {}
        for page in range(1, MAX_PAGES + 1):
            data = self.get_json(
                "/subscriptionmanager/subscriptions/active",
                {"page": page, "filter": "all", "sort": "closest"},
            )
            items = data.get("items") or []
            new = 0
            for item in items:
                c = item.get("creator") or {}
                if c.get("uid") is None or not c.get("handle") or str(c["uid"]) in creators:
                    continue
                creators[str(c["uid"])] = Creator(id=str(c["uid"]), username=c["handle"])
                new += 1
            if not new:
                break
        return list(creators.values())

    def video_token(self, file_id: str) -> str:
        """Token da mandare nell'header "content" a video.privacy.com.br e keyaes."""
        data = self.post_json("/mediavideotoken/generate", {"file_id": file_id})
        token = data.get("content") if isinstance(data, dict) else None
        if not token:
            raise ApiError(f"token video mancante per {file_id}")
        return token

    def media(self, creator: Creator, area: Area) -> Iterator[Media]:
        """Tutti i media sbloccati di un creator in una sezione."""
        self.stats = Counter()
        handlers = {
            Area.POSTS: self._posts,
            Area.MESSAGES: self._messages,
            Area.STORIES: self._stories,
            Area.PURCHASED: self._purchased,
        }
        return handlers[area](creator)

    def _posts(self, creator: Creator) -> Iterator[Media]:
        seen: set[str] = set()
        for page in range(MAX_PAGES):
            offset = page * PAGE_SIZE
            data = self.get_json(f"/timelinequeries/profile/{offset}/{PAGE_SIZE}/{creator.username}")
            items = data.get("items") or []
            new = [p for p in items if p.get("postId") not in seen]
            for post in new:
                seen.add(post.get("postId"))
                self.stats["posts"] += 1
                yield from parse_post_media(post, creator, Area.POSTS, self.stats)
            # Una pagina può avere meno di PAGE_SIZE post anche se non è l'ultima:
            # ci si ferma solo su pagina vuota o fatta solo di post già visti.
            if not new:
                break

    def _messages(self, creator: Creator) -> Iterator[Media]:
        raise NotImplementedError("messaggi: endpoint non ancora presente nei HAR")

    def _stories(self, creator: Creator) -> Iterator[Media]:
        raise NotImplementedError("storie: endpoint non ancora presente nei HAR")

    def _purchased(self, creator: Creator) -> Iterator[Media]:
        raise NotImplementedError("acquisti: endpoint non ancora presente nei HAR")
