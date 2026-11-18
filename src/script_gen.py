"""Schreibt mit Claude das Drehbuch für den nächsten Part einer Serie."""
import json
import os
import re

import requests

from common import env, retry


def _call(prov: str, model: str, prompt: str) -> str:
    if prov == "gemini":
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": env("GEMINI_API_KEY")}, timeout=300,
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}})
        r.raise_for_status()
        return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
    if prov == "pollinations":
        h = {"Content-Type": "application/json"}
        if os.environ.get("POLLINATIONS_KEY"):
            h["Authorization"] = f"Bearer {os.environ['POLLINATIONS_KEY']}"
        r = requests.post("https://text.pollinations.ai/openai", headers=h, timeout=300, json={
            "model": model, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model, "max_tokens": 4000, "messages": [{"role": "user", "content": prompt}]},
        timeout=180)
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"])


def parse_json(text: str) -> dict:
    """JSON aus der Antwort holen – kleine Formatfehler der KI werden automatisch repariert."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    m = re.search(r"\{.*\}", text, re.S)
    raw = m.group(0) if m else text
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        from json_repair import repair_json
        obj = repair_json(raw, return_objects=True)
        if not isinstance(obj, dict) or not obj:
            raise
        return obj


def gemini_models() -> list:
    """Fragt bei Google ab, welche Flash-Modelle es aktuell gibt (Namen ändern sich öfter)."""
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         params={"key": env("GEMINI_API_KEY"), "pageSize": 200}, timeout=30)
        names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        flash = [n for n in names if "flash" in n and not any(x in n for x in ("image", "tts", "audio", "live", "exp"))]
        return sorted(flash, reverse=True)[:4]
    except Exception:  # noqa: BLE001
        return []


def llm(cfg: dict, prompt: str) -> dict:
    """Probiert das Hauptmodell und dann die Ausweichmodelle (z.B. wenn Gemini überlastet ist)."""
    chain = [(cfg["llm"].get("provider", "gemini"), cfg["llm"]["model"])]
    fb = [tuple(x.split(":", 1)) for x in cfg["llm"].get("fallbacks", [])]
    if any(p == "gemini" for p, _ in chain + fb) and os.environ.get("GEMINI_API_KEY"):
        chain += [("gemini", m) for m in gemini_models() if ("gemini", m) not in chain + fb]
    chain += fb
    last = None
    for prov, model in chain:
        print(f"  Sprachmodell: {prov}/{model}")
        try:
            return retry(lambda: parse_json(_call(prov, model, prompt)), tries=2, wait=20)
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  ! {prov}/{model} nicht verfügbar – nächstes Modell")
    raise RuntimeError(f"Kein Sprachmodell erreichbar: {last}")


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
