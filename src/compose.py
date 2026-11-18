"""Setzt eine Szene zusammen: KI-Hintergrund + per Code gezeichnete Figuren,
mit Kamerafahrt, Laufen, Wippen und Mundbewegung beim Sprechen."""
import math
import subprocess
from pathlib import Path

from PIL import Image

import characters as C

SHOTS = {  # Figurenhöhe relativ zur Bildhöhe, Lage der Füße bzw. des Kopfes
    "wide": {"h": 0.46, "feet": 0.90},
    "medium": {"h": 0.82, "top": 0.20},
    "close": {"h": 1.65, "top": 0.10},
}
POS = {"left": 0.27, "center": 0.5, "right": 0.73, "far_left": 0.2, "far_right": 0.8}


class Scene:
    def __init__(self, cfg, specs: dict, scene: dict, bg: Path, t0: float, words: list):
        self.W, self.H, self.fps = cfg["render"]["width"], cfg["render"]["height"], cfg["render"]["fps"]
        self.specs, self.sc, self.t0 = specs, scene, t0
        self.words = words
        chars = [c for c in scene.get("characters", []) if c.get("id") in specs][:3]
        shot = scene.get("shot", "wide")
        if shot == "close" and len(chars) > 1:
            shot = "medium"
        if shot == "medium" and len(chars) > 2:
            shot = "wide"
        self.shot, self.chars = shot, chars
        self.hscale = 0.62 if (shot == "medium" and len(chars) == 2) else 1.0
        img = Image.open(bg).convert("RGB")
        s = max(self.W * 1.12 / img.width, self.H * 1.12 / img.height)
        self.bg = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
        self.cache = {}

    def sprite(self, cid, pose, expr, mouth, phase):
        key = (cid, pose, expr, mouth, phase)
        if key not in self.cache:
            im = C.render(self.specs[cid], pose, expr, mouth, phase)
            k = SHOTS[self.shot]["h"] * self.hscale * self.H / im.height
            self.cache[key] = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.BILINEAR)
        return self.cache[key]

    def talking(self, t):
        g = self.t0 + t
        return any(w["start"] <= g < w["end"] for w in self.words)

    def frame(self, t, dur, idx) -> Image.Image:
        W, H = self.W, self.H
        # Kamerafahrt: abwechselnd rein/raus zoomen, leicht seitlich
        p = t / max(dur, 0.01)
        z = 1.0 + 0.10 * (p if idx % 2 == 0 else 1 - p)
        cw, ch = self.bg.width / z / 1.12 * 1.0, self.bg.height / z / 1.12
        cx = self.bg.width / 2 + (p - 0.5) * self.bg.width * 0.03 * (1 if idx % 3 else -1)
        cy = self.bg.height / 2
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        fr = self.bg.resize((W, H), Image.BILINEAR, box=box).convert("RGBA")

        n = len(self.chars)
        for i, c in enumerate(self.chars):
            pos = c.get("position") or "center"
            if n > 1 and len({d.get("position") for d in self.chars}) < n:  # doppelte Positionen auflösen
                pos = (["left", "right"], ["far_left", "center", "far_right"])[n - 2][i]
            if n == 2 and self.shot == "medium":
                pos = {"left": "far_left", "right": "far_right"}.get(pos, pos)
            x = POS.get(pos, 0.5) * W
            move = c.get("move", "none")
            pose = c.get("pose", "idle")
            if move in ("walk_in_left", "walk_in_right", "run_across", "walk_out_right", "walk_out_left"):
                pose = "run" if move == "run_across" else "walk"
                if move == "walk_in_left":
                    x = -0.35 * W + (x + 0.35 * W) * min(1, p / 0.7)
                elif move == "walk_in_right":
                    x = 1.35 * W - (1.35 * W - x) * min(1, p / 0.7)
                elif move == "walk_out_right":
                    x = x + (1.4 * W - x) * p
                elif move == "walk_out_left":
                    x = x - (x + 0.4 * W) * p
                else:
                    x = -0.35 * W + 1.7 * W * p
                if move.startswith("walk_in") and p >= 0.7:
                    pose = c.get("pose", "idle")
            phase = round((t * (2.2 if pose == "run" else 1.6)) % 1 * 8) / 8 if pose in ("walk", "run") else 0
            mouth = c.get("id") == self.sc.get("speaker") and self.talking(t) and int(t * 9) % 2 == 0
            sp = self.sprite(c["id"], pose, c.get("expression", "smile"), mouth, phase)
            bob = math.sin((t + i * 0.37) * 2 * math.pi * 0.9) * H * 0.004
            st = SHOTS[self.shot]
            if "feet" in st:
                y = st["feet"] * H - sp.height
                sh = C.shadow(int(sp.width * 0.55), int(sp.width * 0.12))
                fr.alpha_composite(sh, (int(x - sh.width / 2), int(st["feet"] * H - sh.height * 0.6)))
            else:
                y = st["top"] * H - sp.height * 0.13
            fr.alpha_composite(sp, (int(x - sp.width / 2), int(y + bob)))
        return fr.convert("RGB")


def render_scene(cfg, specs, scene, bg: Path, t0, dur, words, idx, dest: Path, still: Path | None = None):
    sc = Scene(cfg, specs, scene, bg, t0, words)
    n = max(1, int(round(dur * sc.fps)))
    if still is not None:
        sc.frame(dur / 2, dur, idx).save(still)
        return still
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{sc.W}x{sc.H}", "-r", str(sc.fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-pix_fmt", "yuv420p", str(dest)], stdin=subprocess.PIPE)
    for f in range(n):
        proc.stdin.write(sc.frame(f / sc.fps, dur, idx).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg-Fehler beim Szenen-Rendern")
    return dest
