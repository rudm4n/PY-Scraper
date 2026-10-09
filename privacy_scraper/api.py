"""Client delle API di Privacy (privacy.com.br).

DA COMPLETARE: base URL, endpoint, paginazione e parsing dei JSON dipendono da
come funziona il sito, e vanno ricavati dal file HAR. Finché non ci sono, i
metodi che parlano col sito sollevano NotImplementedError invece di inventare
endpoint.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

import httpx

from .auth import Auth
from .models import Area, Creator, Media

BASE_URL = ""  # TODO(HAR): es. "https://service.privacy.com.br/..."


class ApiError(RuntimeError):
    pass


class PrivacyAPI:
    def __init__(self, auth: Auth, *, delay: float = 0.5, client: httpx.Client | None = None):
        self._delay = delay
        self.client = client or httpx.Client(
            base_url=BASE_URL,
            headers=auth.headers(),
            timeout=httpx.Timeout(30.0, read=120.0),
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def get_json(self, path: str, params: dict[str, Any] | None = None, retries: int = 5) -> Any:
        """GET con pausa tra le richieste e backoff su 429/5xx."""
        for attempt in range(1, retries + 1):
            time.sleep(self._delay)
            resp = self.client.get(path, params=params)
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

    # ---- endpoint del sito: da implementare dopo aver visto il HAR ----------

    def me(self) -> dict[str, Any]:
        """Profilo dell'utente loggato, usato per verificare le credenziali."""
        raise NotImplementedError("endpoint profilo: da ricavare dal HAR")

    def subscriptions(self) -> list[Creator]:
        """Creator a cui sei abbonato."""
        raise NotImplementedError("endpoint abbonamenti: da ricavare dal HAR")

    def media(self, creator: Creator, area: Area) -> Iterator[Media]:
        """Tutti i media sbloccati di un creator in una sezione."""
        handlers = {
            Area.POSTS: self._posts,
            Area.MESSAGES: self._messages,
            Area.STORIES: self._stories,
            Area.PURCHASED: self._purchased,
        }
        return handlers[area](creator)

    def _posts(self, creator: Creator) -> Iterator[Media]:
        raise NotImplementedError("endpoint post: da ricavare dal HAR")

    def _messages(self, creator: Creator) -> Iterator[Media]:
        raise NotImplementedError("endpoint messaggi: da ricavare dal HAR")

    def _stories(self, creator: Creator) -> Iterator[Media]:
        raise NotImplementedError("endpoint storie: da ricavare dal HAR")

    def _purchased(self, creator: Creator) -> Iterator[Media]:
        raise NotImplementedError("endpoint acquisti: da ricavare dal HAR")
