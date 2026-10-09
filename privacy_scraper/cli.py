from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

import httpx

from .api import PrivacyAPI
from .auth import Auth, AuthError
from .config import Config
from .db import MediaDB
from .downloader import download_all
from .models import Area


def cmd_auth(args: argparse.Namespace) -> int:
    print("Incolla i valori presi dal browser (F12 > Network > una richiesta API > Headers).")
    print("Non vengono mostrati a schermo. Invio vuoto per saltare un campo.\n")
    cookie = getpass.getpass("Cookie: ").strip()
    user_agent = input("User-Agent: ").strip()
    extra: dict[str, str] = {}
    print("Altri header richiesti (es. Authorization). Riga vuota per finire.")
    while True:
        name = input("  nome header: ").strip()
        if not name:
            break
        extra[name] = getpass.getpass(f"  valore di {name}: ").strip()
    path = Auth(cookie=cookie, user_agent=user_agent, extra_headers=extra).save()
    print(f"\nCredenziali salvate in {path} (permessi 600).")
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

    api = PrivacyAPI(Auth.load(), delay=cfg.request_delay_seconds)
    db = MediaDB(save_dir / ".privacy.db")
    dl_client = httpx.Client(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True)
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
                items = list(api.media(creator, area))
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

    sub.add_parser("auth", help="salva cookie e header della tua sessione").set_defaults(func=cmd_auth)

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
    except (AuthError, NotImplementedError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
