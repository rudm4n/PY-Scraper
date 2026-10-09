# privacy-scraper

CLI Python ispirata a [of-scraper](https://github.com/datawhores/OF-Scraper) per archiviare
in locale i contenuti dei creator a cui **sei abbonato** su Privacy (privacy.com.br): post, messaggi,
storie e acquisti.

Usa la sessione del tuo browser (header `Authorization`), quindi scarica solo quello che il tuo
account può già vedere.

> **Stato:** funzionano abbonamenti e post (immagini e video). Messaggi, storie e
> acquisti non sono ancora supportati: servono altri file HAR del sito, e per ora
> `scrape` salta quelle sezioni con un avviso.

Cosa viene scaricato dai post:

- immagini, così come le serve il sito (filigrana compresa);
- video HLS alla qualità più alta, decifrati e uniti. Con `ffmpeg` installato diventano
  `.mp4`, altrimenti restano `.ts`;
- non vengono scaricati i media bloccati (post a pagamento non acquistati) né quelli
  protetti da DRM.

## Installazione

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Per i video in `.mp4` serve anche `ffmpeg` (es. `sudo apt install ffmpeg`).

## Credenziali

Il modo più semplice: salva un HAR da Firefox (F12 > Rete > ⚙ > Salva tutto come HAR)
mentre sei loggato su privacy.com.br, poi esegui:

```bash
privacy-scraper auth --from-har            # usa il HAR di Privacy più recente
privacy-scraper auth --from-har FILE.har   # oppure un file preciso
```

Il comando legge `Authorization` e `User-Agent` dal HAR originale (non da quello pulito).
Dopo, cancella il HAR: contiene la tua sessione.

In alternativa `privacy-scraper auth` chiede i due valori a mano:

1. apri privacy.com.br e fai login;
2. premi F12, scheda **Rete**, ricarica la pagina;
3. clicca una richiesta verso `service.privacy.com.br`, poi **Intestazioni**;
4. in **Intestazioni richiesta** copia il valore di `Authorization` e di `User-Agent`.

Il comando verifica subito le credenziali. Quando la sessione scade (errore 401/403),
ripeti `privacy-scraper auth`.

## Uso

```bash
privacy-scraper auth                      # incolla Authorization e User-Agent
privacy-scraper config --save-dir ~/Privacy   # opzionale
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
