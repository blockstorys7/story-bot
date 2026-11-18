"""Erzählerstimme + Wort-Zeitstempel (für Wort-für-Wort-Untertitel) über ElevenLabs."""
import base64
from pathlib import Path

import requests

from common import env, retry


def synthesize(cfg: dict, text: str, dest: Path) -> list:
    """Gibt Liste von Wörtern zurück: [{"word", "start", "end", "char": Startindex im Text}]"""
    if cfg["tts"].get("provider") == "edge":
        return synthesize_edge(cfg, text, dest)
    t = cfg["tts"]

    def call():
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{t['voice_id']}/with-timestamps",
            headers={"xi-api-key": env("ELEVENLABS_API_KEY"), "Content-Type": "application/json"},
            json={"text": text, "model_id": t["model"],
                  "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "speed": t.get("speed", 1.0)}},
            timeout=300)
        r.raise_for_status()
        return r.json()

    data = retry(call)
    dest.write_bytes(base64.b64decode(data["audio_base64"]))
    al = data["alignment"]
    return words_from_alignment(al["characters"], al["character_start_times_seconds"],
                                al["character_end_times_seconds"])


def words_from_alignment(chars, starts, ends) -> list:
    words, cur = [], None
    for i, (c, s, e) in enumerate(zip(chars, starts, ends)):
        if c.isspace():
            if cur:
                words.append(cur)
                cur = None
            continue
        if cur is None:
            cur = {"word": c, "start": s, "end": e, "char": i}
        else:
            cur["word"] += c
            cur["end"] = e
    if cur:
        words.append(cur)
    return words


def synthesize_edge(cfg: dict, text: str, dest: Path) -> list:
    """Gratis: Microsoft-Edge-Neuralstimmen (pip install edge-tts), liefert Wort-Zeitstempel."""
    import asyncio
    import edge_tts

    t = cfg["tts"]
    rate = t.get("edge_rate", "+8%")

    async def run():
        com = edge_tts.Communicate(text, t.get("edge_voice", "de-DE-ConradNeural"),
                                   rate=rate, boundary="WordBoundary")
        audio, marks = bytearray(), []
        async for ch in com.stream():
            if ch["type"] == "audio":
                audio += ch["data"]
            elif ch["type"] == "WordBoundary":
                marks.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
        dest.write_bytes(bytes(audio))
        return marks

    marks = retry(lambda: asyncio.run(run()))
    if not marks:  # manche Stimmen liefern keine Wortzeiten -> gleichmäßig schätzen
        import subprocess
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(dest)], capture_output=True, text=True).stdout.strip())
        toks, pos, total = [], 0, len(text.replace(" ", "")) or 1
        t = 0.1
        for w in text.split(" "):
            d = (dur - 0.3) * len(w) / total
            toks.append({"word": w, "start": t, "end": t + d * 0.92, "char": text.find(w, pos)})
            pos = toks[-1]["char"] + len(w)
            t += d
        return toks
    words, pos = [], 0
    for start, end, w in marks:  # Wörter wieder ihrer Position im Text zuordnen
        idx = text.find(w, pos)
        if idx < 0:
            idx = pos
        # Satzzeichen direkt hinter dem Wort für die Untertitel mitnehmen
        tail = idx + len(w)
        while tail < len(text) and not text[tail].isspace() and not text[tail].isalnum():
            tail += 1
        words.append({"word": text[idx:tail] if idx >= pos else w, "start": start, "end": end, "char": idx})
        pos = max(pos, tail)
    return words
