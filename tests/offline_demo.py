"""Offline-Test der ganzen Pipeline ohne API-Keys: Drehbuch, Hintergründe und Stimme
werden durch Platzhalter ersetzt, Figuren + Schnitt + Untertitel laufen echt.
Ergebnis: output/demo/.../final.mp4"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from PIL import Image, ImageDraw  # noqa: E402

import main  # noqa: E402
import media_gen  # noqa: E402
import script_gen  # noqa: E402
import tts  # noqa: E402

S = [
    ("Ich bin der höflichste Dieb, den Paris je gesehen hat.", 3, "medium",
     [{"id": "thief", "pose": "wave", "expression": "wink", "position": "center"}], "thief"),
    ("Und heute Nacht hole ich mir das berühmteste Collier der Welt.", 2, "wide",
     [{"id": "thief", "pose": "point", "expression": "grin", "position": "left"}], "thief"),
    ("Jede Kamera hier hat einen toten Winkel.", None, "close", [], None),
    ("Mila hat die Pläne für den alten Wartungstunnel besorgt.", 4, "medium",
     [{"id": "thief", "pose": "hands_hips", "expression": "smile"}, {"id": "partner", "pose": "think", "expression": "smirk"}], "thief"),
    ("Um genau Mitternacht laufe ich los.", 1, "wide",
     [{"id": "thief", "pose": "idle", "expression": "smile", "move": "walk_in_left", "position": "center"}], "thief"),
    ("Doch dann stand plötzlich der Wächter vor mir!", 1, "wide",
     [{"id": "guard", "pose": "arms_up", "expression": "shocked", "position": "right"},
      {"id": "thief", "pose": "shrug", "expression": "shocked", "position": "left"}], "thief"),
]
COLORS = {None: ((60, 50, 45), (20, 18, 16)), 1: ((210, 170, 110), (120, 80, 50)), 2: ((40, 40, 55), (15, 15, 20)),
          3: ((230, 225, 210), (140, 130, 120)), 4: ((90, 70, 55), (40, 30, 25))}


def fake_script(cfg, bible, history, part):
    return {"scenes": [{"narration": n, "background": "x", "location": l, "shot": sh, "characters": c,
                        "speaker": sp} for n, l, sh, c, sp in S],
            "caption": "Der Gentleman-Dieb – Teil 1", "hashtags": ["story", "heist"], "summary": "Test"}


def fake_bg(cfg, bible, scene, dest):
    top, bot = COLORS.get(scene.get("location"), COLORS[None])
    im = Image.new("RGB", (768, 1365))
    dr = ImageDraw.Draw(im)
    for y in range(im.height):
        f = y / im.height
        dr.line([(0, y), (im.width, y)], fill=tuple(int(a + (b - a) * f) for a, b in zip(top, bot)))
    for x in range(0, im.width, 96):  # etwas Struktur, damit man die Kamerafahrt sieht
        dr.line([(x, im.height * 0.66), (im.width / 2 + (x - im.width / 2) * 2.2, im.height)], fill=(0, 0, 0), width=2)
    dr.line([(0, im.height * 0.66), (im.width, im.height * 0.66)], fill=(0, 0, 0), width=3)
    im.save(dest)
    return dest


def fake_tts(cfg, text, dest):
    words, t, pos = [], 0.15, 0
    for w in text.split(" "):
        d = 0.18 + 0.045 * len(w)
        words.append({"word": w, "start": t, "end": t + d, "char": pos})
        t += d + 0.06
        pos += len(w) + 1
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=f=180:d={t + 0.1}",
                    "-af", "volume=0.2", str(dest)], check=True)
    return words


script_gen.generate_script = fake_script
media_gen.scene_background = fake_bg
tts.synthesize = fake_tts
main.STATE = Path(tempfile.mkdtemp()) / "state.json"
main.OUT = main.ROOT / "output" / "demo"
cfg = main.load_config()
cfg["render"]["music"] = None
cfg["video"]["enabled"] = False
print(main.generate(cfg)["dir"])
