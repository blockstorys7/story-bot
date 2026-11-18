"""Schreibt mit Claude das Drehbuch für den nächsten Part einer Serie."""
import json
import os
import re

import requests

from common import env, retry


def llm(cfg: dict, prompt: str) -> dict:
    """Ruft das konfigurierte Sprachmodell auf und gibt geparstes JSON zurück.
    provider: gemini (gratis-Kontingent) | pollinations (gratis) | anthropic (bezahlt)"""
    prov = cfg["llm"].get("provider", "gemini")

    def call() -> str:
        if prov == "gemini":
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['llm']['model']}:generateContent",
                params={"key": env("GEMINI_API_KEY")}, timeout=180,
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}})
            r.raise_for_status()
            return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
        if prov == "pollinations":
            h = {"Content-Type": "application/json"}
            if os.environ.get("POLLINATIONS_KEY"):
                h["Authorization"] = f"Bearer {os.environ['POLLINATIONS_KEY']}"
            r = requests.post("https://text.pollinations.ai/openai", headers=h, timeout=300, json={
                "model": cfg["llm"].get("model", "openai"),
                "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": cfg["llm"]["model"], "max_tokens": 4000,
                  "messages": [{"role": "user", "content": prompt}]}, timeout=180)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])

    def parsed():
        return json.loads(re.search(r"\{.*\}", call(), re.S).group(0))
    return retry(parsed, tries=4, wait=20)  # Gratis-Tarife haben enge Minutenlimits

PROMPT = """Du schreibst virale Kurzvideo-Serien (TikTok/Reels): animierte Geschichten mit blockigen 3D-Spielfiguren und Erzählerstimme.

SERIE:
{bible}

BISHERIGE PARTS (Zusammenfassungen):
{history}

AUFGABE: Schreibe Part {part} von {total}.
- Sprache der Erzählung: {language}
- Gesprochene Länge ca. {seconds} Sekunden (~{words} Wörter insgesamt) – NICHT kürzer.
- Erster Satz = starker Hook, der auch ohne Vorwissen funktioniert{recap}.
- Viele kurze Szenen (je 1 Satz, 2–4 Sekunden), wie schnelle Schnitte.
- {ending}
- Keine echten Marken, Personen oder geschützten Figuren nennen.

Pro Szene:
- "background": ENGLISCHE Beschreibung NUR der Umgebung/Objekte, OHNE Personen (z.B. "close-up of a security camera on a dark wall", "long arched maintenance tunnel with warm lamps").
- "location": Index des Ortes aus "locations" der Serie (gleicher Ort = gleicher Look), oder null für Nahaufnahmen von Objekten.
- "shot": "wide" | "medium" | "close"
- "characters": 0–3 Figuren aus der Serie: {{"id", "pose", "expression", "position", "move"}}
    pose: idle | wave | point | shrug | arms_up | carry | think | hands_hips | sneak
    expression: smile | grin | wink | shocked | angry | sad | smirk | neutral
    position: left | center | right
    move: none | walk_in_left | walk_in_right | walk_out_left | walk_out_right | run_across
- "speaker": id der Figur, die gerade erzählt/spricht (Mund bewegt sich), sonst null.
Mische Nahaufnahmen von Figuren, Totalen und Objekt-Szenen ohne Figuren für Abwechslung.

Antworte NUR mit JSON in genau diesem Format:
{{
  "scenes": [{{"narration": "...", "background": "...", "location": 0, "shot": "wide",
              "characters": [{{"id": "...", "pose": "idle", "expression": "smile", "position": "center", "move": "none"}}],
              "speaker": null, "animate": false}}],
  "caption": "kurzer Post-Text mit Teil-Nummer, ohne Hashtags",
  "hashtags": ["...", "..."],
  "summary": "2-3 Sätze: was in diesem Part passiert ist (für Kontinuität)"
}}"""


def generate_script(cfg: dict, bible: dict, history: list, part: int) -> dict:
    total = cfg["parts_per_series"]
    seconds = cfg["target_seconds"]
    if part == 1:
        recap, ending = "", "Ende mit Cliffhanger und 'Folge mir für Teil 2' (in der Erzählsprache)."
    elif part < total:
        recap = " und kurz (1 Satz) an den letzten Part anknüpft"
        ending = f"Ende mit Cliffhanger und Hinweis auf Teil {part + 1}."
    else:
        recap = " und kurz an den letzten Part anknüpft"
        ending = "Dies ist das FINALE: überraschende Auflösung, befriedigendes Ende."

    prompt = PROMPT.format(
        bible=json.dumps(bible, ensure_ascii=False, indent=1),
        history="\n".join(f"Part {i+1}: {s}" for i, s in enumerate(history)) or "(keine – dies ist der Anfang)",
        part=part, total=total, language=cfg["language"], seconds=seconds,
        words=int(seconds * 2.6), recap=recap, ending=ending,
    )
    script = llm(cfg, prompt)
    script["part"] = part
    return script


NEW_SERIES_PROMPT = """Erfinde eine neue fesselnde Kurzvideo-Serie ({total} Parts) mit blockigen 3D-Spielfiguren (Heist, Mystery, Abenteuer, Rache, Flucht …). Keine echten Marken oder geschützten Figuren.
Bisherige Serien (nicht wiederholen): {previous}

Figuren werden per Code gezeichnet; beschreibe sie NUR mit diesen Feldern:
skin/hair_color/beard_color/hat_color/jacket/shirt/pants/shoes/tie: Hex-Farben wie "#2f3f6b" (tie optional)
hair: none | short | long | spiky | bun
beard: none | short | full | mustache
hat: none | flatcap | police | tophat | beanie | cap
outfit: suit | jacket | uniform | hoodie | tshirt
accessory: none | sunglasses | eyemask | glasses
neck: none | chain | pearls
Gib Figuren klar unterscheidbare Farben und Hüte.

Antworte NUR mit JSON:
{{"title": "...", "premise": "...", "tone": "...",
  "characters": [{{"id": "kurz_ohne_leerzeichen", "name": "...", "spec": {{"skin": "#...", "hair": "short", "hair_color": "#...", "beard": "none", "hat": "none", "hat_color": "#...", "outfit": "suit", "jacket": "#...", "shirt": "#...", "pants": "#...", "shoes": "#1b1b1b", "accessory": "none", "neck": "none"}}}}],
  "locations": ["englische Beschreibung eines Ortes", "..."]}}"""


def generate_series_bible(cfg: dict, previous_titles: list) -> dict:
    return llm(cfg, NEW_SERIES_PROMPT.format(total=cfg["parts_per_series"],
                                             previous=", ".join(previous_titles) or "keine"))
