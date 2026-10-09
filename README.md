# privacy-scraper

CLI Python ispirata a [of-scraper](https://github.com/datawhores/OF-Scraper) per archiviare
in locale i contenuti dei creator a cui **sei abbonato** su Privacy (privacy.com.br): post, messaggi,
storie e acquisti.

Usa la sessione del tuo browser (cookie + header), quindi scarica solo quello che il tuo
account può già vedere.

> **Stato:** la parte generica è pronta: CLI, configurazione, credenziali, download in
> parallelo con retry e registro dei file già scaricati. Gli endpoint del sito
> (`privacy_scraper/api.py`) vanno ancora implementati partendo da un file HAR del sito.
> Se dal HAR risulta che Privacy non ha le storie, l'area `stories` va tolta.

## Installazione

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Uso

```bash
privacy-scraper auth                      # incolla Cookie, User-Agent e header richiesti
privacy-scraper config --save-dir ~/CF    # opzionale
privacy-scraper list                      # creator a cui sei abbonato
privacy-scraper scrape                    # tutto, per tutti i creator
privacy-scraper scrape -u alice bob -a posts messages
privacy-scraper scrape --dry-run          # elenca senza scaricare
```

I file finiscono in `save_dir` secondo `filename_template`, che di default è:

```
{username}/{area}/{media_type}/{date}_{post_id}_{media_id}.{ext}
```

Campi disponibili: `username`, `creator_id`, `area`, `media_type`, `post_id`, `media_id`,
`date`, `ext`.

I media già scaricati sono registrati in `save_dir/.privacy.db` e vengono saltati nei
giri successivi.

## File locali

- `~/.config/privacy-scraper/config.json`: configurazione.
- `~/.config/privacy-scraper/auth.json`: credenziali, salvate con permessi 600. **Non
  committarlo e non condividerlo.**

## Test

```bash
pip install -e '.[dev]' && pytest
```
