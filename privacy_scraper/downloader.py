from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import httpx

from .db import MediaDB
from .models import Media

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe(value: str) -> str:
    return _UNSAFE.sub("_", value).strip(" .") or "_"


def render_path(template: str, media: Media) -> Path:
    """Costruisce il percorso del file dal template (es. "{username}/{area}/...")."""
    fields = {
        "username": media.creator.username,
        "creator_id": media.creator.id,
        "area": media.area.value,
        "media_type": media.media_type.value,
        "post_id": media.post_id,
        "media_id": media.id,
        "date": media.created_at.strftime("%Y-%m-%d"),
        "ext": media.extension,
    }
    rendered = template.format(**{k: _safe(v) for k, v in fields.items()})
    # Le "/" del template separano cartelle; ".." non deve uscire da save_dir.
    parts = [p for p in rendered.split("/") if p not in ("", ".", "..")]
    return Path(*parts)


@dataclass
class DownloadResult:
    downloaded: list[Path] = field(default_factory=list)
    skipped: int = 0
    failed: list[tuple[Media, str]] = field(default_factory=list)


def _fetch(client: httpx.Client, media: Media, target: Path, retries: int = 3) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    for attempt in range(1, retries + 1):
        try:
            with client.stream("GET", media.url) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_bytes(1 << 16):
                        f.write(chunk)
            tmp.replace(target)
            return target
        except httpx.HTTPError:
            tmp.unlink(missing_ok=True)
            if attempt == retries:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def download_all(
    items: Iterable[Media],
    *,
    save_dir: Path,
    template: str,
    db: MediaDB,
    client: httpx.Client,
    max_workers: int = 4,
    on_done: Callable[[Media, Path | None, str | None], None] | None = None,
) -> DownloadResult:
    result = DownloadResult()
    todo: list[tuple[Media, Path]] = []
    seen: set[tuple[str, str]] = set()
    for media in items:
        key = (media.creator.id, media.id)
        if key in seen or db.is_downloaded(media):
            result.skipped += 1
            continue
        seen.add(key)
        todo.append((media, save_dir / render_path(template, media)))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch, client, m, p): m for m, p in todo}
        for fut in as_completed(futures):
            media = futures[fut]
            try:
                path = fut.result()
            except Exception as exc:  # noqa: BLE001 - riportiamo e continuiamo
                result.failed.append((media, str(exc)))
                if on_done:
                    on_done(media, None, str(exc))
                continue
            # Scritture sul DB solo da questo thread.
            db.mark_downloaded(media, path)
            result.downloaded.append(path)
            if on_done:
                on_done(media, path, None)
    return result
