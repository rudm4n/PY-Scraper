import base64
import json
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from privacy_scraper.api import PrivacyAPI, image_ext, parse_post_media
from privacy_scraper.auth import Auth
from privacy_scraper.db import MediaDB
from privacy_scraper.downloader import download_all, make_fetcher
from privacy_scraper.hls import download_hls, video_file_id
from privacy_scraper.models import Area, Creator, MediaType

CREATOR = Creator(id="7", username="alice")
VIDEO_URL = "https://video.privacy.com.br/abc123/hls/v1--alice.m3u8"


def image_url(key: str) -> str:
    payload = json.dumps({"bucket": "b", "key": key}).encode()
    return "https://image.privacy.com.br/" + base64.b64encode(payload).decode()


def post(pid: str, medias: list[dict], date: str = "2026-10-09T00:59:37.186Z") -> dict:
    return {"postId": pid, "publishedDate": date, "description": "ciao", "medias": medias}


def img(mid: str, key: str = "2026-10-9/x--alice.jpeg", **kw) -> dict:
    return {"isLocked": False, "mediaId": mid, "type": "image", "url": image_url(key), **kw}


def make_api(handler) -> PrivacyAPI:
    client = httpx.Client(base_url="https://service.privacy.com.br",
                          transport=httpx.MockTransport(handler))
    return PrivacyAPI(Auth(extra_headers={"Authorization": "x"}), delay=0, client=client)


def test_image_ext_from_base64_key():
    assert image_ext(image_url("a/b--alice.jpeg")) == "jpg"
    assert image_ext(image_url("a/b--alice.png")) == "png"
    assert image_ext("https://image.privacy.com.br/not-base64!") == ""


def test_parse_post_media_skips_locked_and_drm():
    p = post("p1", [
        img("m1"),
        {"isLocked": True, "type": "video", "maxResolution": 1920},
        {"isLocked": False, "mediaId": "m3", "type": "video", "url": VIDEO_URL, "drmMediaId": "d"},
        {"isLocked": False, "mediaId": "m4", "type": "video", "url": VIDEO_URL, "drmMediaId": None},
    ])
    items = list(parse_post_media(p, CREATOR, Area.POSTS))
    assert [m.id for m in items] == ["m1", "m4"]
    assert items[0].media_type is MediaType.IMAGE and items[0].extension == "jpg"
    assert items[1].is_hls and items[1].extension == "mp4"
    assert items[0].created_at.year == 2026 and items[0].post_id == "p1"


def test_posts_paginate_by_offset_until_short_page():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        offset = int(req.url.path.split("/")[3])
        if offset == 0:
            items = [post(f"p{i}", [img(f"m{i}")]) for i in range(10)]
        elif offset == 10:
            items = [post("p0", [img("m0")]), post("p10", [img("m10")])]  # p0 fissato, ripetuto
        else:
            raise AssertionError("pagina in più")
        return httpx.Response(200, json={"items": items})

    media = list(make_api(handler).media(CREATOR, Area.POSTS))
    assert calls == ["/timelinequeries/profile/0/10/alice", "/timelinequeries/profile/10/10/alice"]
    assert [m.id for m in media] == [f"m{i}" for i in range(11)]


def test_subscriptions_stop_when_no_new_creators():
    pages = []

    def handler(req: httpx.Request) -> httpx.Response:
        page = int(req.url.params["page"])
        pages.append(page)
        items = [{"creator": {"uid": "1", "handle": "alice"}}] if page <= 2 else []
        return httpx.Response(200, json={"items": items})

    creators = make_api(handler).subscriptions()
    assert creators == [Creator(id="1", username="alice")]
    assert pages == [1, 2]  # la pagina 2 ripete la 1: stop


def test_video_token():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST" and json.loads(req.content) == {"file_id": "abc123"}
        return httpx.Response(200, json={"content": "TOKEN"})

    assert make_api(handler).video_token("abc123") == "TOKEN"
    assert video_file_id(VIDEO_URL) == "abc123"


KEY = bytes(range(16))


def encrypt(data: bytes, seq: int) -> bytes:
    padder = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(KEY), modes.CBC(seq.to_bytes(16, "big"))).encryptor()
    return enc.update(padder.update(data) + padder.finalize()) + enc.finalize()


def hls_handler(seen: list):
    base = "https://video.privacy.com.br/abc123/hls/"
    master = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=700000\nv1--alice_360p.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=4000000\nv1--alice_1080p.m3u8\n"
    )
    variant = (
        "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:1\n"
        '#EXT-X-KEY:METHOD=AES-128,URI="https://keyaes.privacy.com.br/keys/alice/abc123/1/keyaes.key"\n'
        "#EXTINF:3,\nv1--alice_1080p_00001.ts\n#EXTINF:3,\nv1--alice_1080p_00002.ts\n#EXT-X-ENDLIST\n"
    )
    files = {
        base + "v1--alice.m3u8": master.encode(),
        base + "v1--alice_1080p.m3u8": variant.encode(),
        base + "v1--alice_1080p_00001.ts": encrypt(b"SEG-ONE", 1),
        base + "v1--alice_1080p_00002.ts": encrypt(b"SEG-TWO", 2),
        "https://keyaes.privacy.com.br/keys/alice/abc123/1/keyaes.key": KEY,
    }

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        seen.append((url.rsplit("/", 1)[-1], req.headers.get("x-content-uri"), req.headers.get("content")))
        return httpx.Response(200, content=files[url]) if url in files else httpx.Response(404)

    return handler


def test_download_hls_picks_best_variant_and_decrypts(tmp_path):
    seen: list = []
    client = httpx.Client(transport=httpx.MockTransport(hls_handler(seen)))
    out = download_hls(client, VIDEO_URL, tmp_path / "v.mp4", "TOKEN", remux=lambda s, d: False)
    assert out == tmp_path / "v.ts"
    assert out.read_bytes() == b"SEG-ONESEG-TWO"
    assert all(name == uri and tok == "TOKEN" for name, uri, tok in seen)
    assert "v1--alice_360p.m3u8" not in [s[0] for s in seen]
    assert [s[0] for s in seen].count("keyaes.key") == 1
    assert not list(tmp_path.glob("*.part"))


def test_download_hls_remux_replaces_ts(tmp_path):
    def remux(src: Path, dst: Path) -> bool:
        dst.write_bytes(b"MP4" + src.read_bytes())
        return True

    client = httpx.Client(transport=httpx.MockTransport(hls_handler([])))
    out = download_hls(client, VIDEO_URL, tmp_path / "v.mp4", "TOKEN", remux=remux)
    assert out == tmp_path / "v.mp4" and out.read_bytes() == b"MP4SEG-ONESEG-TWO"
    assert not (tmp_path / "v.ts").exists()


def test_download_all_with_hls_fetcher(tmp_path, monkeypatch):
    monkeypatch.setattr("privacy_scraper.hls.remux_with_ffmpeg", lambda s, d: False)
    client = httpx.Client(transport=httpx.MockTransport(hls_handler([])))
    p = post("p1", [{"isLocked": False, "mediaId": "m1", "type": "video", "url": VIDEO_URL}])
    items = list(parse_post_media(p, CREATOR, Area.POSTS))
    db = MediaDB(tmp_path / "x.db")
    fetch = make_fetcher(lambda file_id: "TOKEN-" + file_id)
    res = download_all(items, save_dir=tmp_path, template="{username}/{media_id}.{ext}",
                       db=db, client=client, fetch=fetch)
    assert res.failed == []
    assert res.downloaded == [tmp_path / "alice" / "m1.ts"]
    assert db.is_downloaded(items[0])
