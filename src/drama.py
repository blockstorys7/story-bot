"""Gezeichnete 2D-Drama-Videos (Puppentheater-Stil) mit mehreren Stimmen.

Figuren und Orte werden pro Serie EINMAL von der KI gezeichnet und gespeichert
(series/assets/<serie>/) – dadurch sehen sie in jedem Teil gleich aus.
"""
import asyncio
import json
import math
import os
import re
import subprocess
import time
import urllib.parse
import zlib
from pathlib import Path

import requests
from PIL import Image, ImageFilter

from common import ROOT, read_json, retry, write_json
from script_gen import llm

W, H, FPS = 1080, 1920, 30

VOICES = {  # kostenlose Microsoft-Neuralstimmen (edge-tts)
    "narrator": "de-DE-FlorianMultilingualNeural",
    "m": ["de-DE-ConradNeural", "de-DE-KillianNeural", "de-AT-JonasNeural", "de-CH-JanNeural"],
    "f": ["de-DE-SeraphinaMultilingualNeural", "de-DE-KatjaNeural", "de-DE-AmalaNeural", "de-AT-IngridNeural"],
    "child": ["de-DE-GiselaNeural"],
}
CHILD_FALLBACK = ("de-DE-KatjaNeural", "+55Hz", "+8%")  # helle Frauenstimme, höher gestimmt

STYLE = ("2D digital illustration, hand-drawn storybook style, soft cel shading, warm muted colors, "
         "clean outlines, cozy, slightly melancholic mood")


# ------------------------------------------------------------------ Bilder (KI)
def ai_image(prompt: str, dest: Path, w: int, h: int, seed: int) -> Path:
    """Gratis-Bilder über Pollinations (neuer und alter Endpunkt)."""
    key = os.environ.get("POLLINATIONS_KEY", "").strip()
    q = urllib.parse.quote(prompt[:1400])
    tries = []
    if key:
        tries.append((f"https://gen.pollinations.ai/image/{q}",
                      {"model": "flux", "width": w, "height": h, "seed": seed, "nologo": "true"},
                      {"Authorization": f"Bearer {key}"}))
    tries.append((f"https://image.pollinations.ai/prompt/{q}",
                  {"model": "flux", "width": w, "height": h, "seed": seed, "nologo": "true",
                   **({"token": key} if key else {})}, {}))
    last = None
    for attempt in range(6):
        for url, params, headers in tries:
            try:
                r = requests.get(url, params=params, headers=headers, timeout=240)
                if r.ok and r.headers.get("content-type", "").startswith("image"):
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(r.content)
                    return dest
                last = f"{r.status_code} {r.text[:120]}"
            except Exception as e:  # noqa: BLE001
                last = str(e)
        print(f"  ! Bild fehlgeschlagen ({last}), neuer Versuch …", flush=True)
        time.sleep(10 + attempt * 10)
    raise RuntimeError(f"Bild konnte nicht erzeugt werden: {last}")


def cutout(src: Path, dest: Path) -> Path:
    """Hintergrund entfernen (rembg, Modell für Zeichnungen) und auf Figur zuschneiden."""
    from rembg import new_session, remove
    global _SESSION
    try:
        _SESSION
    except NameError:
        _SESSION = new_session("isnet-anime")
    im = remove(Image.open(src).convert("RGB"), session=_SESSION)
    a = im.split()[-1].point(lambda v: 255 if v > 40 else 0)
    im.putalpha(Image.composite(im.split()[-1], Image.new("L", im.size, 0), a))
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    im.save(dest)
    return dest


def series_assets(cfg, bible: dict, slug: str) -> dict:
    """Figuren + Orte einmal pro Serie zeichnen und im Repo speichern."""
    d = ROOT / "series" / "assets" / slug
    d.mkdir(parents=True, exist_ok=True)
    assets = {"chars": {}, "locs": {}}
    for i, ch in enumerate(bible["characters"]):
        p = d / f"char_{ch['id']}.png"
        if not p.exists():
            print(f"  Figur zeichnen: {ch['name']}", flush=True)
            raw = d / f"raw_{ch['id']}.png"
            ai_image(f"Full body character design of {ch['look']}, standing straight, facing the viewer, neutral calm "
                     f"expression, arms hanging down, whole body visible from head to shoes, centered, "
                     f"plain flat light grey background, no shadow, no text. {STYLE}",
                     raw, 768, 1344, zlib.crc32(ch["id"].encode()) % 99999)
            cutout(raw, p)
            raw.unlink(missing_ok=True)
        assets["chars"][ch["id"]] = p
    for i, loc in enumerate(bible["locations"]):
        p = d / f"loc_{i}.png"
        if not p.exists():
            print(f"  Ort zeichnen: {loc[:50]}", flush=True)
            ai_image(f"Background illustration of {loc}, eye-level view, empty room without any people, "
                     f"no characters, detailed interior, vertical composition. {STYLE}",
                     p, 864, 1536, 1000 + i)
        assets["locs"][i] = p
    return assets


# ------------------------------------------------------------------ Drehbuch
DRAMA_PROMPT = """Du schreibst emotionale deutsche TikTok-Drama-Serien als gezeichnete Kurzfilme (wie animierte Bildergeschichten).
Viele Dialoge, kurze Sätze, Gefühle, Spannung, am Ende ein Cliffhanger. Erzähler nur sparsam (innere Gedanken der Hauptfigur in Ich-Form).

SERIE:
{bible}

BISHERIGE TEILE:
{history}

AUFGABE: Schreibe Teil {part} von {total}. Gesprochene Länge ca. {seconds} Sekunden (~{words} Wörter), NICHT länger als {maxw} Wörter.
{ending}
25–40 Zeilen. Jede Zeile = ein Satz bzw. Satzteil (max. ~14 Wörter) mit:
- "speaker": "narrator" (Gedanken der Hauptfigur) oder id einer Figur
- "text": was gesagt wird
- "location": Index des Ortes aus "locations"
- "present": ids der Figuren, die im Bild sind (1–3)
- "shot": "wide" (ganzer Raum) | "medium" (Figuren halbnah) | "close" (Gesicht/Oberkörper der sprechenden Figur – oft verwenden!)
- "focus": id der Figur, auf die die Kamera schaut
Keine echten Marken oder Personen.

Antworte NUR mit JSON:
{{"lines": [{{"speaker": "...", "text": "...", "location": 0, "present": ["..."], "shot": "close", "focus": "..."}}],
  "caption": "kurzer Post-Text mit Teil-Nummer", "hashtags": ["..."], "summary": "2-3 Sätze, was passiert ist"}}"""

DRAMA_SERIES_PROMPT = """Erfinde eine neue emotionale deutsche TikTok-Drama-Serie ({total} Teile) als gezeichnete Bildergeschichte
(z.B. Körpertausch, Familiengeheimnis, Zeitreise, zweite Chance, Verrat). Bodenständig, berührend, spannend. Keine echten Personen.
Bisherige Serien (nicht wiederholen): {previous}

Antworte NUR mit JSON:
{{"title": "...", "premise": "...", "tone": "...",
  "characters": [{{"id": "kurz", "name": "...", "gender": "m|f|child", "height": 1.0,
                   "look": "ENGLISCHE genaue Aussehensbeschreibung (Alter, Haare, Kleidung, Farben)"}}],
  "locations": ["ENGLISCHE Beschreibung eines Ortes, z.B. 'a small worn-out living room with a blue couch and a red carpet at night'"]}}
2–4 Figuren (Kinder: height 0.62), 3–4 Orte."""


# ------------------------------------------------------------------ Stimmen
def voice_map(bible) -> dict:
    used = {"m": 0, "f": 0, "child": 0}
    vm = {"narrator": bible.get("narrator_voice", VOICES["narrator"])}
    for ch in bible["characters"]:
        g = ch.get("gender", "m") if ch.get("gender") in VOICES else "m"
        lst = VOICES[g]
        vm[ch["id"]] = ch.get("voice") or lst[used[g] % len(lst)]
        used[g] += 1
    if any(v == vm["narrator"] for k, v in vm.items() if k != "narrator"):
        vm["narrator"] = "de-DE-KillianNeural"
    return vm


def tts_line(text: str, voice: str, dest: Path, rate="+6%", pitch="+0Hz", gender="m"):
    """Spricht eine Zeile. Fällt die Stimme aus, werden Ersatzstimmen probiert."""
    import edge_tts

    def attempt(v, r, p):
        async def run():
            await edge_tts.Communicate(text, v, rate=r, pitch=p).save(str(dest))
        retry(lambda: asyncio.run(run()), tries=2, wait=4)

    options = [(voice, rate, pitch)]
    if gender == "child":
        options.append(CHILD_FALLBACK)
    options += [(v, rate, pitch) for v in VOICES.get(gender if gender in ("m", "f") else "f", []) if v != voice]
    options.append((VOICES["narrator"], rate, pitch))
    last = None
    for v, r, p in options:
        try:
            attempt(v, r, p)
            if v != voice:
                print(f"  (Ersatzstimme {v} statt {voice})", flush=True)
            return dest
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"Keine Stimme verfügbar: {last}")


def duration(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(p)], capture_output=True, text=True).stdout.strip())


# ------------------------------------------------------------------ Bildaufbau
class Stage:
    def __init__(self, assets, bible):
        self.assets = assets
        self.height = {c["id"]: float(c.get("height", 1.0)) for c in bible["characters"]}
        self.cache = {}

    def bg(self, loc):
        k = ("bg", loc)
        if k not in self.cache:
            p = self.assets["locs"].get(loc) or next(iter(self.assets["locs"].values()))
            im = Image.open(p).convert("RGB")
            s = max(W * 1.3 / im.width, H * 1.3 / im.height)
            self.cache[k] = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
        return self.cache[k]

    def sprite(self, cid, target_h):
        k = ("sp", cid, int(target_h))
        if k not in self.cache:
            im = Image.open(self.assets["chars"][cid]).convert("RGBA")
            s = target_h / im.height
            self.cache[k] = im.resize((max(1, int(im.width * s)), max(1, int(target_h))), Image.LANCZOS)
        return self.cache[k]

    def frame(self, line, t, dur, idx, talking):
        shot = line.get("shot", "medium")
        present = [c for c in (line.get("present") or []) if c in self.assets["chars"]][:3]
        focus = line.get("focus") if line.get("focus") in present else (present[0] if present else None)
        if shot == "close" and focus:
            present = [focus]
        n = len(present)
        xs = {0: [], 1: [0.5], 2: [0.3, 0.7], 3: [0.2, 0.5, 0.8]}[n]
        fx = xs[present.index(focus)] if focus else 0.5
        # Hintergrund: Ausschnitt je nach Einstellung, langsamer Zoom
        bg = self.bg(line.get("location", 0))
        p = t / max(dur, 0.01)
        zoom = {"wide": 1.0, "medium": 1.12, "close": 1.28}.get(shot, 1.1) * (1 + 0.035 * (p if idx % 2 else 1 - p))
        cw, ch = bg.width / 1.3 / zoom, bg.height / 1.3 / zoom
        cx = bg.width / 2 + (fx - 0.5) * (bg.width - cw) * 0.8
        cy = bg.height * 0.52
        x0 = min(max(0, cx - cw / 2), bg.width - cw)
        y0 = min(max(0, cy - ch / 2), bg.height - ch)
        fr = bg.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch)).convert("RGBA")
        # Figuren: wide/medium = Füße auf Boden, close = Kopf oben im Bild
        hh = {"wide": 0.5, "medium": 0.92 if n < 3 else 0.78, "close": 2.1}.get(shot, 0.92)
        for i, cid in enumerate(present):
            sp = self.sprite(cid, H * hh * (self.height.get(cid, 1.0) if shot != "close" else 1.0))
            breath = 1 + 0.008 * math.sin((t + i) * 2 * math.pi * 0.45)
            bob = -abs(math.sin(t * 9)) * H * 0.004 if (talking and cid == line.get("speaker")) else 0
            if breath != 1:
                sp = sp.resize((sp.width, int(sp.height * breath)), Image.BILINEAR)
            x = (fx if shot == "close" else xs[i]) * W - sp.width / 2
            feet = {"wide": 0.93, "medium": 1.14 if n < 3 else 1.04}.get(shot)
            y = (0.1 * H if shot == "close" or feet is None else feet * H - sp.height) + bob
            if shot == "wide":  # weicher Bodenschatten
                sh = Image.new("RGBA", (int(sp.width * 0.8), int(sp.width * 0.12)), (0, 0, 0, 0))
                from PIL import ImageDraw
                ImageDraw.Draw(sh).ellipse([0, 0, sh.width, sh.height], fill=(0, 0, 0, 90))
                sh = sh.filter(ImageFilter.GaussianBlur(sh.height / 3))
                fr.alpha_composite(sh, (int(x + sp.width * 0.1), int(feet * H - sh.height * 0.6)))
            fr.alpha_composite(sp, (int(x), int(y)))
        return fr.convert("RGB")


def render_segment(stage, line, dur, idx, dest: Path, talk_until: float):
    n = max(1, int(round(dur * FPS)))
    proc = subprocess.Popen(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                             "-crf", "21", "-pix_fmt", "yuv420p", str(dest)], stdin=subprocess.PIPE)
    for f in range(n):
        t = f / FPS
        proc.stdin.write(stage.frame(line, t, dur, idx, t < talk_until).tobytes())
    proc.stdin.close()
    if proc.wait():
        raise RuntimeError("ffmpeg-Fehler")
    return dest


def ass_time(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def write_captions(lines, times, dest: Path, part, total):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Line,Crimson Text,66,&H00FFFFFF,&H00FFFFFF,&H00202020,&H78000000,1,0,0,0,100,100,0,0,1,4,2,5,150,150,0,1
Style: Part,Crimson Text,58,&H00FFFFFF,&H00FFFFFF,&H00202020,&H00000000,1,0,0,0,100,100,1,0,1,4,0,8,40,40,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = [f"Dialogue: 1,{ass_time(0)},{ass_time(2.5)},Part,,0,0,0,,{{\\fad(200,300)}}Teil {part}"]
    for ln, (s, e) in zip(lines, times):
        txt = ln["text"].replace("{", "(").replace("}", ")")
        ev.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Line,,0,0,0,,{{\\pos({W // 2},{int(H * 0.62)})\\fad(80,80)}}{txt}")
    dest.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ Ablauf
def generate_drama(cfg, bible, slug, part, total, history, work: Path) -> dict:
    script = read_json(work / "script.json")
    if not script:
        print("Drehbuch …", flush=True)
        if part == 1:
            ending = "Erster Teil: starker, verwirrender Einstieg in den ersten 2 Zeilen. Ende mit Cliffhanger."
        elif part < total:
            ending = "Knüpfe direkt an den letzten Teil an. Ende mit Cliffhanger."
        else:
            ending = "FINALE: emotionale Auflösung."
        sec = cfg["target_seconds"]
        script = llm(cfg, DRAMA_PROMPT.format(bible=json.dumps(bible, ensure_ascii=False), part=part, total=total,
                                              history="\n".join(history) or "(Anfang)", seconds=sec,
                                              words=int(sec * 2.3), maxw=int(cfg.get("max_seconds", 88) * 2.4),
                                              ending=ending))
        write_json(work / "script.json", script)
    lines = [ln for ln in script["lines"] if re.search(r"[A-Za-zÄÖÜäöüß0-9]", ln.get("text", ""))]
    valid = {c["id"] for c in bible["characters"]} | {"narrator"}
    for ln in lines:
        if ln.get("speaker") not in valid:
            ln["speaker"] = "narrator"

    print("Figuren & Orte …", flush=True)
    assets = series_assets(cfg, bible, slug)

    print(f"Stimmen ({len(lines)} Zeilen) …", flush=True)
    vm = voice_map(bible)
    genders = {c["id"]: c.get("gender", "m") for c in bible["characters"]}
    clips, times, t = [], [], 0.25
    for i, ln in enumerate(lines):
        p = work / f"line_{i:02d}.mp3"
        if not p.exists():
            v = vm.get(ln["speaker"], vm["narrator"])
            g = genders.get(ln["speaker"], "m")
            tts_line(ln["text"], v, p, pitch="+25Hz" if g == "child" else "+0Hz", gender=g)
        d = duration(p)
        gap = 0.35 if i + 1 < len(lines) and lines[i + 1]["speaker"] != ln["speaker"] else 0.18
        clips.append((p, t))
        times.append((t, t + d))
        t += d + gap
    total_len = max(t + 0.6, cfg["min_seconds"])
    # Audio zusammensetzen
    voice = work / "voice.wav"
    inputs, filt = [], []
    for i, (p, start) in enumerate(clips):
        inputs += ["-i", str(p)]
        filt.append(f"[{i}:a]aresample=48000,adelay={int(start * 1000)}|{int(start * 1000)}[a{i}]")
    filt.append("".join(f"[a{i}]" for i in range(len(clips))) + f"amix=inputs={len(clips)}:normalize=0,apad[out]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[out]",
                    "-t", f"{total_len:.2f}", "-ac", "2", str(voice)], check=True)

    print("Szenen zeichnen …", flush=True)
    stage = Stage(assets, bible)
    segs = []
    for i, ln in enumerate(lines):
        s = 0 if i == 0 else times[i][0] - 0.1
        e = (times[i + 1][0] - 0.1) if i + 1 < len(lines) else total_len
        dest = work / f"seg_{i:02d}.mp4"
        if not dest.exists():
            render_segment(stage, ln, e - s, i, dest, talk_until=times[i][1] - s)
        segs.append(dest)
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in segs))
    raw = work / "video_raw.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(raw)],
                   check=True)

    print("Untertitel & Ton …", flush=True)
    ass = work / "captions.ass"
    write_captions(lines, times, ass, part, total)
    fonts = str((ROOT / "assets" / "fonts").resolve())
    final = work / "final.mp4"
    music = cfg["render"].get("music")
    music = ROOT / music if music else None
    vf = f"ass='{ass.resolve()}':fontsdir='{fonts}'"
    if music and music.exists():
        cmd = ["-i", str(raw), "-i", str(voice), "-stream_loop", "-1", "-i", str(music), "-filter_complex",
               f"[0:v]{vf}[v];[2:a]volume={cfg['render'].get('music_volume', 0.1)}[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]",
               "-map", "[v]", "-map", "[a]"]
    else:
        cmd = ["-i", str(raw), "-i", str(voice), "-vf", vf, "-map", "0:v", "-map", "1:a"]
    subprocess.run(["ffmpeg", "-y", "-v", "error", *cmd, "-t", f"{total_len:.2f}", "-c:v", "libx264", "-preset",
                    "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(final)], check=True)
    print(f"Fertig: {final} ({total_len:.0f}s)", flush=True)
    return script
