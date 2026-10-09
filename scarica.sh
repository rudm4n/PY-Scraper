#!/usr/bin/env bash
# Aggiorna il programma e scarica i nuovi contenuti dei tuoi abbonamenti Privacy.
# Durante il download il PC non va in sospensione.
#
# Uso:  ~/PY-Scraper/scarica.sh            (post di tutti i creator)
#       ~/PY-Scraper/scarica.sh -u nome    (solo quel creator)
set -euo pipefail
cd "$(dirname "$0")"

git pull -q || echo "! aggiornamento non riuscito, uso la versione già presente" >&2
.venv/bin/pip install -q -e . >/dev/null

# Per ora funzionano solo i post: se non passi -a, scarica quelli.
args=("$@")
[[ " ${args[*]-} " == *" -a "* || " ${args[*]-} " == *" --areas "* ]] || args+=(-a posts)

if command -v systemd-inhibit >/dev/null && systemd-inhibit --list >/dev/null 2>&1; then
  exec systemd-inhibit --what=idle:sleep:handle-lid-switch --who=privacy-scraper \
    --why="download in corso" .venv/bin/privacy-scraper scrape "${args[@]}"
fi
exec .venv/bin/privacy-scraper scrape "${args[@]}"
