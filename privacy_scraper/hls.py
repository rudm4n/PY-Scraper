"""Download dei video HLS di Privacy.

I video stanno su video.privacy.com.br come playlist HLS cifrate AES-128; la
chiave sta su keyaes.privacy.com.br. Ogni richiesta (playlist, segmenti,
chiave) vuole due header, come fa il player del sito:

- "content": token ottenuto da /mediavideotoken/generate per quel file_id;
- "x-content-uri": nome del file richiesto (ultimo pezzo del path).

ffmpeg da solo non basta perché manda gli stessi header a ogni richiesta, quindi
playlist, chiave e segmenti si scaricano qui, si decifrano e si uniscono in un
.ts. Se ffmpeg è installato il .ts viene rimuxato in .mp4 senza ricodifica.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_ATTR = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def video_file_id(url: str) -> str:
    """Il primo pezzo del path ("/<file_id>/hls/...") identifica il video."""
    return urlsplit(url).path.strip("/").split("/", 1)[0]


def _attrs(line: str) -> dict[str, str]:
    body = line.split(":", 1)[1] if ":" in line else ""
    return {k: v.strip('"') for k, v in _ATTR.findall(body)}


@dataclass
class Segment:
    url: str
    sequence: int
    key_url: str | None
    iv: bytes | None


def best_variant(master: str, base_url: str) -> str | None:
    """URL della variante con banda più alta, o None se non è una master playlist."""
    best: tuple[int, str] | None = None
    lines = [ln.strip() for ln in master.splitlines()]
    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        bandwidth = int(_attrs(line).get("BANDWIDTH", "0") or 0)
        uri = next((ln for ln in lines[i + 1 :] if ln and not ln.startswith("#")), None)
        if uri and (best is None or bandwidth > best[0]):
            best = (bandwidth, urljoin(base_url, uri))
    return best[1] if best else None


def parse_media_playlist(text: str, base_url: str) -> list[Segment]:
    segments: list[Segment] = []
    sequence = 0
    key_url: str | None = None
    iv: bytes | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            sequence = int(line.split(":", 1)[1])
        elif line.startswith("#EXT-X-KEY"):
            a = _attrs(line)
            method = a.get("METHOD", "NONE").upper()
            if method == "NONE":
                key_url, iv = None, None
            elif method == "AES-128":
                key_url = urljoin(base_url, a["URI"])
                iv = bytes.fromhex(a["IV"][2:]) if "IV" in a else None
            else:
                raise ValueError(f"cifratura HLS non supportata: {method}")
        elif line and not line.startswith("#"):
            segments.append(Segment(urljoin(base_url, line), sequence, key_url, iv))
            sequence += 1
    return segments


def _decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    out = dec.update(data) + dec.finalize()
    pad = out[-1] if out else 0
    if 1 <= pad <= 16 and out.endswith(bytes([pad]) * pad):
        out = out[:-pad]
    return out


def download_hls(
    client: httpx.Client,
    url: str,
    target: Path,
    token: str,
    extra_headers: dict[str, str] | None = None,
    remux: Callable[[Path, Path], bool] | None = None,
) -> Path:
    """Scarica, decifra e unisce un video HLS. Ritorna il percorso finale."""

    def get(u: str) -> httpx.Response:
        name = urlsplit(u).path.rsplit("/", 1)[-1]
        headers = {**(extra_headers or {}), "content": token, "x-content-uri": name}
        resp = client.get(u, headers=headers)
        resp.raise_for_status()
        return resp

    playlist_url = url
    text = get(url).text
    variant = best_variant(text, url)
    if variant:
        playlist_url = variant
        text = get(variant).text
    segments = parse_media_playlist(text, playlist_url)
    if not segments:
        raise ValueError(f"playlist HLS vuota: {url}")

    target.parent.mkdir(parents=True, exist_ok=True)
    ts_path = target.with_suffix(".ts")
    tmp = ts_path.with_name(ts_path.name + ".part")
    keys: dict[str, bytes] = {}
    try:
        with open(tmp, "wb") as f:
            for seg in segments:
                data = get(seg.url).content
                if seg.key_url:
                    if seg.key_url not in keys:
                        keys[seg.key_url] = get(seg.key_url).content
                    iv = seg.iv or seg.sequence.to_bytes(16, "big")
                    data = _decrypt(data, keys[seg.key_url], iv)
                f.write(data)
        tmp.replace(ts_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    if target.suffix.lower() == ".ts":
        return ts_path
    if (remux or remux_with_ffmpeg)(ts_path, target):
        ts_path.unlink(missing_ok=True)
        return target
    return ts_path


def remux_with_ffmpeg(src: Path, dst: Path) -> bool:
    """Converte .ts in .mp4 senza ricodifica. False se ffmpeg manca o fallisce."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-c", "copy",
           "-bsf:a", "aac_adtstoasc", str(tmp)]
    if subprocess.run(cmd, check=False).returncode != 0:
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(dst)
    return True
