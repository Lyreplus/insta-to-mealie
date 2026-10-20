# Insta → Mealie

Importa in [Mealie](https://mealie.io) le ricette scritte nella descrizione dei post Instagram.

Dal telefono: **Instagram → Condividi → Insta → Mealie** → controlli l'anteprima → **Importa su Mealie**.
La ricetta viene creata direttamente su Mealie, con foto, link al post, tempi, porzioni e tag `Instagram`.

## Come funziona

```
Telefono (web app / PWA)  ──link──▶  questo server  ──API──▶  Mealie
                                        │
                                        ├─ legge la descrizione del post (yt-dlp, poi Open Graph come riserva)
                                        └─ la divide in titolo / ingredienti / procedimento / note
```

- La divisione usa euristiche (italiano e inglese): intestazioni come «Ingredienti», «Procedimento» e «Consigli»,
  le quantità («200 g», «q.b.») e la pulizia di emoji, hashtag e «seguimi/salva il post».
- Prima di importare vedi un'anteprima modificabile. Le righe che finiscono con `:` («Per la crema:»)
  diventano titoli di sezione in Mealie.
- Se hai configurato un provider AI in Mealie, puoi attivare `MEALIE_AI=true`: comparirà anche il pulsante
  «Importa con l'AI di Mealie», che passa la descrizione grezza all'AI di Mealie.
- Se Instagram non restituisce la descrizione, puoi incollarla a mano nell'app.

## Installazione (sul server di Mealie)

1. Copia questa cartella sul server.
2. In Mealie: **Profilo → Token API → genera un token**.
3. `cp .env.example .env` e compila almeno `MEALIE_URL` e `MEALIE_API_TOKEN`.
   - Se Mealie è nello stesso `docker-compose` o nella stessa rete Docker: `MEALIE_URL=http://mealie:9000`
     (vedi i commenti `networks` in `docker-compose.yml`).
   - `MEALIE_PUBLIC_URL` è l'indirizzo con cui apri Mealie dal telefono (per il pulsante «Apri in Mealie»).
4. `docker compose up -d --build`
5. Apri `http://IP-DEL-SERVER:8099` dal telefono.

Richiede Mealie ≥ 2.0 (usa `/api/recipes/create/html-or-json`). Testato con Mealie v3.29.

## Sul telefono Android

### Opzione A: app installata con «Condividi» (consigliata, richiede HTTPS)

Android mostra l'app nel menu *Condividi* solo se è installata come PWA, e Chrome lo permette solo su **HTTPS**.
Se hai già un reverse proxy (Caddy, Nginx Proxy Manager, Traefik…) per Mealie, aggiungi un sottodominio,
ad esempio `ricette-insta.tuodominio.it → insta-mealie:8099`. In alternativa, con Tailscale:
`tailscale serve --bg --https=8443 http://localhost:8099`.

Poi in Chrome apri l'indirizzo HTTPS → menu ⋮ → **Installa app**.
Da Instagram: **Condividi → Insta → Mealie** e la ricetta si apre già analizzata.

Se il server è raggiungibile da internet, imposta `APP_TOKEN`: l'app lo chiede una sola volta.

### Opzione B: solo rete locale, senza HTTPS

- Apri `http://IP-DEL-SERVER:8099` in Chrome → ⋮ → **Aggiungi a schermata Home**, poi incolla il link
  (Instagram → Condividi → Copia link).
- Per avere comunque la voce nel menu *Condividi*, installa l'app **HTTP Shortcuts** (gratuita, open source):
  crea una scorciatoia di tipo *Browser Shortcut* con URL `http://IP-DEL-SERVER:8099/?text={shared_text}`
  e attiva *Mostra nel menu Condividi* (Trigger → Share). Da Instagram: Condividi → HTTP Shortcuts.

## Se Instagram blocca le richieste

Instagram limita a volte le richieste anonime. Le soluzioni, in ordine:

1. Aggiorna yt-dlp: metti l'ultima versione in `requirements.txt` e ricostruisci l'immagine con
   `docker compose build --pull && docker compose up -d`.
2. Esporta i cookie di Instagram da un browser in cui hai fatto login (formato Netscape, ad esempio con
   l'estensione «Get cookies.txt LOCALLY»; meglio un account secondario), salvali come `instagram-cookies.txt`,
   scommenta il volume in `docker-compose.yml` e imposta `INSTAGRAM_COOKIES_FILE=/srv/instagram-cookies.txt`.
3. Usa «Incolla la descrizione a mano» nell'app.

## Sicurezza

- Imposta sempre `APP_TOKEN` con un valore lungo e casuale (`openssl rand -hex 24`). Senza, chiunque raggiunga
  la porta 8099 può creare ricette nel tuo Mealie.
- Genera il token API da un utente Mealie dedicato e **non admin**: il server non ha bisogno di altri permessi.
- Dietro un reverse proxy, pubblica la porta solo in locale (`127.0.0.1:8099:8099`) e imposta un limite alla
  dimensione delle richieste anche sul proxy (ad esempio `client_max_body_size 256k` in Nginx).
- Il file dei cookie di Instagram equivale a una sessione aperta: usa un account secondario e non metterlo in git.
- Il testo dei post è scritto da sconosciuti: prima di inviarlo a Mealie il server rimuove HTML e immagini markdown.
- Aggiorna periodicamente le dipendenze e ricontrollale con `uvx pip-audit -r requirements.txt`.

## Sviluppo

```bash
uv venv && uv pip install -r requirements.txt pytest
MEALIE_URL=http://localhost:9925 MEALIE_API_TOKEN=... .venv/bin/uvicorn app.main:app --reload --port 8099
.venv/bin/pytest
```

File principali: `app/instagram.py` (lettura del post), `app/parser.py` (divisione della descrizione),
`app/mealie.py` (client Mealie), `app/main.py` (API) e `app/static/` (web app).
