from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

import httpx

from .api import ApiError, PrivacyAPI, site_headers
from .auth import Auth, AuthError
from .config import Config
from .db import MediaDB
from .downloader import download_all, make_fetcher
from .models import Area


def find_latest_har() -> Path | None:
    """HAR di Privacy più recente nelle cartelle dove Firefox di solito salva."""
    home = Path.home()
    found: list[Path] = []
    for folder in (home, home / "Scaricati", home / "Downloads", home / "Desktop", home / "Scrivania"):
        if folder.is_dir():
            found += [p for p in folder.glob("*privacy*.har") if "clean" not in p.name.lower()]
    return max(found, key=lambda p: p.stat().st_mtime, default=None)


def cmd_auth(args: argparse.Namespace) -> int:
    if args.from_har is not None:
        har = Path(args.from_har).expanduser() if args.from_har else find_latest_har()
        if har is None:
            print("Nessun HAR di Privacy trovato in Home, Scaricati o Downloads.", file=sys.stderr)
            return 2
        print(f"Leggo le credenziali da {har}")
        return _save_and_verify(Auth.from_har(har))
    print("Prendi i valori dal browser, con privacy.com.br aperto e loggato:")
    print("  F12 > Rete > clicca una richiesta a service.privacy.com.br > Intestazioni")
    print("  > Intestazioni richiesta. Copia il valore di Authorization e di User-Agent.")
    print("Authorization non viene mostrato a schermo.\n")
    authorization = getpass.getpass("Authorization: ").strip()
    if not authorization:
        print("Authorization vuoto: niente salvato.", file=sys.stderr)
        return 2
    user_agent = input("User-Agent: ").strip()
    return _save_and_verify(
        Auth(user_agent=user_agent, extra_headers={"Authorization": authorization})
    )


def _save_and_verify(auth: Auth) -> int:
    path = auth.save()
    print(f"\nCredenziali salvate in {path} (permessi 600).")
    api = PrivacyAPI(auth)
    try:
        me = api.me()
        print(f"Login verificato: {me.get('nickname', '?').strip()}")
    except (ApiError, httpx.HTTPError) as exc:
        print(f"Attenzione, verifica fallita: {exc}", file=sys.stderr)
        return 1
    finally:
        api.close()
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    cfg = Config.load()
    if args.save_dir:
        cfg.save_dir = str(Path(args.save_dir).expanduser().resolve())
    if args.template:
        cfg.filename_template = args.template
    if args.workers:
        cfg.max_concurrent_downloads = args.workers
    path = cfg.save(None)
    for key, value in vars(cfg).items():
        print(f"{key}: {value}")
    print(f"\n(salvato in {path})")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    cfg = Config.load()
    api = PrivacyAPI(Auth.load(), delay=cfg.request_delay_seconds)
    try:
        for creator in api.subscriptions():
            print(f"{creator.username}\t{creator.id}")
    finally:
        api.close()
    return 0


def cmd_scrape(args: argparse.Namespace) -> int:
    cfg = Config.load()
    areas = [Area(a) for a in (args.areas or cfg.areas)]
    save_dir = Path(args.save_dir or cfg.save_dir).expanduser()

    auth = Auth.load()
    api = PrivacyAPI(auth, delay=cfg.request_delay_seconds)
    db = MediaDB(save_dir / ".privacy.db")
    dl_headers = site_headers()
    if auth.user_agent:
        dl_headers["User-Agent"] = auth.user_agent
    dl_client = httpx.Client(
        headers=dl_headers, timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True
    )
    fetch = make_fetcher(api.video_token, dl_headers)
    total_failed = 0
    try:
        creators = api.subscriptions()
        if args.creators:
            wanted = {c.lower() for c in args.creators}
            creators = [c for c in creators if c.username.lower() in wanted]
            missing = wanted - {c.username.lower() for c in creators}
            for name in sorted(missing):
                print(f"! {name}: non risulta tra i tuoi abbonamenti, salto", file=sys.stderr)

        for creator in creators:
            for area in areas:
                print(f"== {creator.username} / {area.value}")
                try:
                    items = list(api.media(creator, area))
                except NotImplementedError as exc:
                    print(f"   ! sezione non ancora supportata ({exc}), salto", file=sys.stderr)
                    continue
                st = api.stats
                if st:
                    print(
                        f"   post letti {st['posts']}: media sbloccati {st['ok']}, "
                        f"bloccati (a pagamento) {st['locked']}, DRM {st['drm']}, "
                        f"tipo sconosciuto {st['unknown']}"
                    )
                if args.dry_run:
                    for m in items:
                        print(f"   {m.media_type.value}\t{m.id}\t{m.url}")
                    continue
                res = download_all(
                    items,
                    save_dir=save_dir,
                    template=cfg.filename_template,
                    db=db,
                    client=dl_client,
                    max_workers=cfg.max_concurrent_downloads,
                    fetch=fetch,
                )
                total_failed += len(res.failed)
                print(
                    f"   scaricati {len(res.downloaded)}, già presenti {res.skipped}, "
                    f"falliti {len(res.failed)}"
                )
                for media, err in res.failed:
                    print(f"   ! {media.id}: {err}", file=sys.stderr)
    finally:
        dl_client.close()
        db.close()
        api.close()
    return 1 if total_failed else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="privacy-scraper",
        description="Scarica i contenuti dei tuoi abbonamenti Privacy (privacy.com.br).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("auth", help="salva le credenziali della tua sessione")
    a.add_argument(
        "--from-har", nargs="?", const="", metavar="FILE",
        help="prendi le credenziali da un HAR di Firefox (senza FILE: il più recente)",
    )
    a.set_defaults(func=cmd_auth)

    c = sub.add_parser("config", help="mostra o modifica la configurazione")
    c.add_argument("--save-dir")
    c.add_argument("--template", help="es. {username}/{area}/{date}_{media_id}.{ext}")
    c.add_argument("--workers", type=int, help="download in parallelo")
    c.set_defaults(func=cmd_config)

    sub.add_parser("list", help="elenca i creator a cui sei abbonato").set_defaults(func=cmd_list)

    s = sub.add_parser("scrape", help="scarica i media")
    s.add_argument("-u", "--creators", nargs="+", help="solo questi username (default: tutti)")
    s.add_argument(
        "-a", "--areas", nargs="+", choices=[a.value for a in Area],
        help="sezioni da scaricare (default: tutte)",
    )
    s.add_argument("--save-dir", help="cartella di destinazione per questo giro")
    s.add_argument("--dry-run", action="store_true", help="elenca i media senza scaricarli")
    s.set_defaults(func=cmd_scrape)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (AuthError, ApiError, NotImplementedError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 2
    except httpx.HTTPError as exc:
        print(f"Errore di rete: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
