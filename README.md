# AI Story Bot 🎬 – läuft komplett in der Cloud, Einrichtung nur mit dem Handy

Jeden Tag erstellt GitHub automatisch einen neuen Part deiner Story-Serie
(~72 s, 9:16, Erzählerstimme, Wort-für-Wort-Untertitel) und lädt ihn auf TikTok und Instagram hoch.
Dein Handy kann dabei aus sein. Kosten: **0 €**.

**Warum die Figuren immer gleich aussehen:** Die KI malt nur die Hintergründe (ohne Personen).
Die Blockfiguren zeichnet der Code selbst nach einer festen Bauanleitung (`series/*.json` → `spec`).
Dieselbe Figur sieht deshalb in jedem Clip und jedem Part exakt gleich aus – inklusive
Posen, Gesichtsausdrücken, Laufen und Mundbewegung beim Sprechen.

```
GitHub (täglich 18:07) → Gemini schreibt Part N → Pollinations malt Hintergründe
 → Code zeichnet Figuren + animiert → edge-tts spricht → ffmpeg schneidet → TikTok + Instagram
```

---

## Einrichtung (alles im Handy-Browser, ca. 30–45 min, einmalig)

Tipp: In Chrome/Safari „Desktop-Website anfordern“ einschalten – GitHub, TikTok- und Meta-Entwicklerseiten
sind dann leichter zu bedienen.

### 1. Schlüssel besorgen (gratis)
- **Gemini:** aistudio.google.com → „Get API key“ → kopieren.
- **Pollinations:** enter.pollinations.ai → anmelden → Key kopieren (optional, aber empfohlen: kein Wasserzeichen).

### 2. TikTok-App anlegen
1. developers.tiktok.com → anmelden → *Manage apps* → *Connect an app*.
2. Produkte **Login Kit** und **Content Posting API** hinzufügen, bei Content Posting **Direct Post** einschalten.
3. Scopes `user.info.basic` und `video.publish`.
4. Redirect URI: `https://github.com/DEIN-GITHUB-NAME` (irgendeine https-Seite reicht).
5. *Client key* und *Client secret* notieren.
6. **Audit beantragen** (sonst sind Posts nur für dich sichtbar und dein Konto muss privat sein).

### 3. Instagram vorbereiten
1. In der Instagram-App: Einstellungen → Kontotyp → **Professionelles Konto** (Creator).
2. developers.facebook.com → *App erstellen* → Anwendungsfall **Instagram API** („Instagram API with Instagram Login“).
3. Dein Instagram-Konto hinzufügen → **Token generieren** → Token kopieren. Dort steht auch die **Instagram-User-ID**.
   Berechtigungen: `instagram_business_basic`, `instagram_business_content_publish`.

### 4. GitHub-Secrets eintragen
Im Repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Inhalt |
|---|---|
| `GEMINI_API_KEY` | Gemini-Key |
| `POLLINATIONS_KEY` | Pollinations-Key (optional) |
| `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` | aus Schritt 2 |
| `TIKTOK_REDIRECT_URI` | exakt dieselbe Adresse wie in Schritt 2.4 |
| `IG_USER_ID` / `IG_ACCESS_TOKEN` | aus Schritt 3 |
| `GH_PAT` | siehe unten – damit der Bot erneuerte Logins speichern kann |

**GH_PAT erstellen:** Profilbild → Settings → Developer settings → Personal access tokens →
*Fine-grained tokens* → *Generate new token* → nur dieses Repository → Permissions:
**Secrets: Read and write** → erstellen → kopieren → als Secret `GH_PAT` speichern.

### 5. TikTok verbinden
1. Repo → **Actions** → „TikTok verbinden“ → **Run workflow** (Feld leer lassen).
2. Den Lauf öffnen → in der Zusammenfassung steht ein Link → öffnen → erlauben.
3. Du landest auf der Redirect-Seite: **komplette Adresse** aus der Adresszeile kopieren (enthält `?code=`).
4. „TikTok verbinden“ erneut starten und die Adresse ins Feld einfügen. → ✅
   (Der Code ist nur wenige Minuten gültig – zügig machen.)

### 6. Testen
Actions → **Story Bot** → **Run workflow**. Nach ca. 10–15 min ist der Part online.
Das Video kannst du auch im Lauf unter *Artifacts* herunterladen.
Ab jetzt läuft alles automatisch jeden Tag um 18:07 Uhr.

---

## Anpassen (direkt auf GitHub im Browser, Stift-Symbol)
- `config.yaml` – Sprache, Länge, Parts pro Serie, Stimme (`edge_voice`).
- Uhrzeit: `.github/workflows/story-bot.yml` → `cron` (Zeit in UTC, Deutschland = UTC+1 im Winter).
- Eigene Story/Figuren: `series/museum_heist.json` als Vorlage. Nach dem letzten Part erfindet der Bot
  selbst eine neue Serie mit neuen Figuren.

## Später upgraden (wenn Geld reinkommt)
In `config.yaml`: `llm.provider: anthropic`, `image.provider: fal`, `tts.provider: elevenlabs`,
`video.enabled: true` (Kling animiert die fertigen Szenen mit deinen Figuren) – plus die passenden Secrets.

## Gut zu wissen
- GitHub Actions ist für private Repos bis 2.000 Minuten/Monat gratis; ein Part braucht ca. 10–15 min.
- Schlägt der Upload überall fehl, wird der Part nicht gezählt und beim nächsten Lauf neu erstellt.
- KI-Inhalte werden gekennzeichnet (TikTok `is_aigc` + Hashtag) – das verlangen beide Plattformen.
- Gratis-Dienste können ihre Limits ändern; der Bot wiederholt fehlgeschlagene Anfragen automatisch.
- Lokal testen ohne Keys: `python tests/offline_demo.py`.
