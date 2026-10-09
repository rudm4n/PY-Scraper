from datetime import datetime
from pathlib import Path

import httpx
import pytest

from privacy_scraper.auth import Auth, AuthError
from privacy_scraper.db import MediaDB
from privacy_scraper.downloader import download_all, render_path
from privacy_scraper.models import Area, Creator, Media, MediaType

CREATOR = Creator(id="42", username="alice")


def make_media(mid: str, url: str | None = None) -> Media:
    return Media(
        id=mid,
        url=url or f"https://cdn.example/{mid}.jpg?token=x",
        media_type=MediaType.IMAGE,
        area=Area.POSTS,
        creator=CREATOR,
        post_id="p1",
        created_at=datetime(2026, 1, 2),
    )


def test_render_path_default_template():
    path = render_path("{username}/{area}/{media_type}/{date}_{post_id}_{media_id}.{ext}", make_media("m1"))
    assert path == Path("alice/posts/image/2026-01-02_p1_m1.jpg")


def test_render_path_cannot_escape_save_dir():
    evil = Media(**{**make_media("m1").__dict__, "creator": Creator(id="1", username="..")})
    path = render_path("{username}/../{media_id}.{ext}", evil)
    assert ".." not in path.parts


def test_extension_fallback_by_type():
    m = Media(**{**make_media("m1").__dict__, "url": "https://cdn.example/file", "media_type": MediaType.VIDEO})
    assert m.extension == "mp4"


def test_auth_roundtrip_and_permissions(tmp_path):
    p = tmp_path / "auth.json"
    Auth(cookie="sess=1", user_agent="UA", extra_headers={"Authorization": "x"}).save(p)
    assert (p.stat().st_mode & 0o777) == 0o600
    auth = Auth.load(p)
    assert auth.headers()["Cookie"] == "sess=1"
    assert auth.headers()["Authorization"] == "x"


def test_auth_empty_raises():
    with pytest.raises(AuthError):
        Auth().headers()


def test_download_all_writes_files_and_skips_on_second_run(tmp_path, monkeypatch):

    def handler(request: httpx.Request) -> httpx.Response:
        if "bad" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, content=b"data-" + request.url.path.encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    db = MediaDB(tmp_path / "x.db")
    items = [make_media("a"), make_media("b"), make_media("a"), make_media("bad")]
    tpl = "{username}/{media_id}.{ext}"

    monkeypatch.setattr("privacy_scraper.downloader.time.sleep", lambda s: None)

    res = download_all(items, save_dir=tmp_path, template=tpl, db=db, client=client, max_workers=2)
    assert sorted(p.name for p in res.downloaded) == ["a.jpg", "b.jpg"]
    assert res.skipped == 1  # il duplicato di "a"
    assert [m.id for m, _ in res.failed] == ["bad"]
    assert (tmp_path / "alice" / "a.jpg").read_bytes() == b"data-/a.jpg"
    assert not list(tmp_path.rglob("*.part"))

    res2 = download_all(items, save_dir=tmp_path, template=tpl, db=db, client=client)
    assert res2.downloaded == []
    assert res2.skipped == 3
