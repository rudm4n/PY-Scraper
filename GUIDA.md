# Guida rapida: privacy-scraper

Scarica in `~/privacy-downloads` foto e video dei creator a cui sei abbonato su
privacy.com.br. Scarica solo quello che il tuo account può già vedere.

## Uso di tutti i giorni

Apri il terminale (Ctrl+Alt+T) e lancia:

```bash
~/PY-Scraper/scarica.sh
```

Il comando:

1. aggiorna il programma all'ultima versione;
2. scarica i post nuovi di tutti i creator a cui sei abbonato;
3. salta i file già scaricati;
4. tiene acceso il PC finché il download non finisce.

Alla fine stampa, per ogni creator:

```
== Daanfeet / posts
   post letti 135: media sbloccati 286, bloccati (a pagamento) 47, DRM 0, tipo sconosciuto 0
   scaricati 3, già presenti 283, falliti 0
```

- **bloccati (a pagamento)**: post da comprare a parte. Il sito non manda il file.
- **falliti**: rilancia il comando. Se restano, segnalali.

Solo un creator:

```bash
~/PY-Scraper/scarica.sh -u Daanfeet
```

## Dove trovi i file

```
~/privacy-downloads/<creator>/posts/image/<data>_<post>_<media>.jpg
~/privacy-downloads/<creator>/posts/video/<data>_<post>_<media>.mp4
```

## Quando il login scade

Se compare un errore `401` o `403`, la sessione è scaduta. Rinnovala così:

1. In Firefox apri privacy.com.br e fai login.
2. Premi F12, apri la scheda **Rete** e premi F5.
3. Clicca l'ingranaggio ⚙ del pannello e scegli **Salva tutto come HAR**. Premi **Salva**.
4. Nel terminale lancia:

   ```bash
   cd ~/PY-Scraper && .venv/bin/privacy-scraper auth --from-har
   ```

   Deve stampare `Login verificato: ...`.
5. Cancella il file HAR da Scaricati: contiene il tuo login.

Poi rilancia `~/PY-Scraper/scarica.sh`.

## Installazione su un altro PC (Linux)

```bash
sudo apt install -y git python3-venv ffmpeg
cd ~ && git clone -b claude/zen-feynman-m038w9 https://github.com/rudm4n/PY-Scraper.git
cd ~/PY-Scraper && python3 -m venv .venv && .venv/bin/pip install -e .
```

Poi segui "Quando il login scade" per salvare le credenziali.

## Cosa non scarica (per ora)

- Chat, acquisti e storie: non ancora supportati.
- Post a pagamento non comprati.
- Video con DRM vero: non vengono sbloccati.

## Sicurezza

- Le credenziali stanno in `~/.config/privacy-scraper/auth.json`, leggibile solo da te.
  Non condividerlo.
- Non mandare a nessuno i file HAR originali.
