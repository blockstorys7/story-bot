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
            params={"key": env("GEMINI_API_KEY")}, timeout=120,
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


PROMPT = """Du schreibst virale deutsche TikTok-Serien im Stil von Roblox-Storys: eine Erzählerstimme erzählt eine witzige, absurde Geschichte, dazu sehr schnelle Schnitte (alle 1–2 Sekunden ein neues Bild).

SERIE:
{bible}

BISHERIGE TEILE (Zusammenfassungen):
{history}

AUFGABE: Schreibe Teil {part} von {total}.
- Sprache: {language}. Natürlich, umgangssprachlich, wie ein junger Erzähler, der einem Freund etwas erzählt.
- Gesprochene Länge ca. {seconds} Sekunden = ca. {words} Wörter insgesamt. NICHT kürzer.
- Erster Satz = starker Hook{recap}.
- {ending}
- 35 bis 45 Szenen. Jede Szene = ein kurzer Satzteil mit 4–10 Wörtern (ein Schnitt).
- Keine echten Marken, Personen oder geschützten Figuren.

Pro Szene:
- "narration": der gesprochene Text dieser Szene
- "set": street | facade | room | jail | meadow | sign
- "sign_text": Text auf dem Schild/Gebäude, GROSSBUCHSTABEN, max. 3 Wörter (bei facade Pflicht, z.B. "RATHAUS", "GEFÄNGNIS"; bei sign die Pointe, z.B. "+2 JAHRE"), sonst null
- "room_type": nur bei set=room: bakery | office | police | school | home | shop
- "shot": close (Gesicht groß, für Reaktionen – oft verwenden!) | medium | wide | establishing (nur Ort, ohne Figuren)
- "focus": id der wichtigsten Figur im Bild
- "characters": 0–3 Figuren: {{"id", "pose", "expression", "prop", "sign_text"}}
    pose: idle | wave | point | arms_up | shrug | hold_sign | think | carry | hands_hips | walk | run | sneak | victory | facepalm
    expression: neutral | happy | smile | shocked | angry | sad | smirk | worried | wink | laugh
    prop: null | sign | bread | box   (bei hold_sign: "sign_text" = Text auf dem Schild, z.B. "NEUE REGEL: KEIN HÜPFEN")
Wechsle oft zwischen Nahaufnahmen (close) der Gesichter, Orten und Pointen-Schildern – wie ein schneller TikTok-Schnitt.

Antworte NUR mit JSON:
{{
  "scenes": [{{"narration": "...", "set": "street", "sign_text": null, "room_type": null, "shot": "close", "focus": "...",
              "characters": [{{"id": "...", "pose": "idle", "expression": "happy", "prop": null}}]}}],
  "caption": "kurzer Post-Text mit Teil-Nummer, ohne Hashtags",
  "hashtags": ["...", "..."],
  "summary": "2-3 Sätze: was in diesem Teil passiert ist (für Kontinuität)"
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
        words=int(seconds * 2.4), recap=recap, ending=ending,
    )
    script = llm(cfg, prompt)
    script["part"] = part
    return script


NEW_SERIES_PROMPT = """Erfinde eine neue fesselnde deutsche TikTok-Serie ({total} Teile) im Stil von Roblox-Storys in einer bunten Blockstadt (z.B. absurde Stadtregeln, Gefängnisausbruch, Schulchaos, Detektivfall, Rache am Nachbarn). Keine echten Marken oder geschützten Figuren.
Bisherige Serien (nicht wiederholen): {previous}

Figuren (4–6) werden in 3D per Code gebaut; beschreibe sie NUR mit diesen Feldern:
skin, eye_color, hair_color, hat_color, top, shirt, trim, pants, shoes, tie: Hex-Farben wie "#2f3f6b" (trim/tie optional)
hair: none | short | spiky | messy | long | bun
hat: none | police | tophat | beanie | cap | flatcap
outfit: suit | jacket | uniform | hoodie | tshirt | dress
Gib jeder Figur klar unterscheidbare Haare/Farben. Die Hauptfigur sollte auffällige Haare haben.

Antworte NUR mit JSON:
{{"title": "...", "premise": "...", "tone": "...",
  "characters": [{{"id": "kurz_ohne_leerzeichen", "name": "...", "spec": {{"skin": "#...", "eye_color": "#...", "hair": "spiky", "hair_color": "#...", "hat": "none", "outfit": "suit", "top": "#...", "shirt": "#...", "trim": "#...", "pants": "#...", "shoes": "#..."}}}}],
  "sets": "street, facade, room, jail, meadow, sign"}}"""


SHORTEN_PROMPT = """Hier ist ein Drehbuch als JSON. Es ist zu lang ({have} Wörter gesprochen). Kürze die Erzählung auf höchstens {want} Wörter:
streiche unwichtige Szenen ganz oder kürze Sätze, aber behalte Hook, roten Faden und das Ende/den Cliffhanger.
Behalte exakt dasselbe JSON-Format mit allen Feldern pro Szene. Antworte NUR mit dem JSON.

{script}"""


def shorten_script(cfg: dict, script: dict, want: int) -> dict:
    have = len(" ".join(s["narration"] for s in script["scenes"]).split())
    out = llm(cfg, SHORTEN_PROMPT.format(have=have, want=want, script=json.dumps(script, ensure_ascii=False)))
    if not out.get("scenes"):
        return script
    for k in ("caption", "hashtags", "summary", "part"):
        out.setdefault(k, script.get(k))
    return out


def generate_series_bible(cfg: dict, previous_titles: list) -> dict:
    return llm(cfg, NEW_SERIES_PROMPT.format(total=cfg["parts_per_series"],
                                             previous=", ".join(previous_titles) or "keine"))
