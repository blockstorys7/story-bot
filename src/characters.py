"""Zeichnet blockige 3D-Spielfiguren per Code.

Jede Figur wird aus einer festen Beschreibung (Farben, Hut, Bart …) gebaut –
dadurch sieht sie in JEDEM Clip und jedem Part exakt gleich aus.
"""
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

U = 220  # Pixel pro Block-Einheit (Arbeitsauflösung, wird später skaliert)
D = 0.16  # Tiefe der Seiten-/Oberflächen (3D-Effekt)

POSES = {  # (Winkel linker Arm, rechter Arm) in Grad, 0 = hängt runter, + = nach außen
    "idle": (4, -4), "wave": (8, -160), "point": (4, -95), "shrug": (40, -40),
    "arms_up": (160, -160), "carry": (-25, 25), "think": (4, -135), "hands_hips": (28, -28),
    "walk": (0, 0), "run": (0, 0), "sneak": (-30, 30),
}
EXPRESSIONS = ["smile", "grin", "wink", "shocked", "angry", "sad", "smirk", "neutral"]


def hx(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def box(dr: ImageDraw.ImageDraw, x, y, w, h, color, top=True, side=True, r=0.08):
    """Quader in Schrägprojektion: Front + Oberseite (hell) + rechte Seite (dunkel)."""
    d = D * U
    col = hx(color) if isinstance(color, str) else color
    if side:
        dr.polygon([(x + w, y), (x + w + d, y - d), (x + w + d, y + h - d), (x + w, y + h)],
                   fill=shade(col, 0.62))
    if top:
        dr.polygon([(x, y), (x + d, y - d), (x + w + d, y - d), (x + w, y)], fill=shade(col, 1.18))
    dr.rounded_rectangle([x, y, x + w, y + h], radius=int(r * U), fill=col)
    # leichter Verlauf: unten etwas dunkler
    dr.rectangle([x + 2, y + h * 0.82, x + w - 2, y + h - 2], fill=shade(col, 0.9))
    return col


def limb(length, width, color, end_color=None, shoe=None):
    """Arm/Bein als eigenes Bild, Drehpunkt oben Mitte."""
    pad = int(D * U) + 4
    img = Image.new("RGBA", (int(width + 2 * pad), int(length + 2 * pad)), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    box(dr, pad, pad, width, length, color, r=0.06)
    if end_color:  # Hand / Haut unten
        box(dr, pad, pad + length * 0.78, width, length * 0.22, end_color, top=False, r=0.06)
    if shoe:
        box(dr, pad, pad + length * 0.84, width, length * 0.16, shoe, top=False, r=0.04)
    return img, (pad + width / 2, pad)


def paste_rot(canvas, part, pivot, at, angle):
    img, (px, py) = part
    big = Image.new("RGBA", (img.width * 3, img.height * 3), (0, 0, 0, 0))
    ox, oy = img.width * 1.5 - px, img.height * 1.5 - py
    big.paste(img, (int(ox), int(oy)), img)
    big = big.rotate(angle, resample=Image.BICUBIC, center=(img.width * 1.5, img.height * 1.5))
    canvas.alpha_composite(big, (int(at[0] - img.width * 1.5), int(at[1] - img.height * 1.5)))


def face(dr, x, y, w, h, expr, mouth_open, spec):
    eye_c = (25, 25, 25)
    ex1, ex2, ey = x + w * 0.33, x + w * 0.67, y + h * 0.42
    ew, eh = w * 0.065, h * 0.11
    if expr == "shocked":
        ew, eh = w * 0.085, h * 0.14
    # Augen
    for i, ex in enumerate((ex1, ex2)):
        if expr == "wink" and i == 1:
            dr.arc([ex - ew * 1.6, ey - eh * 0.5, ex + ew * 1.6, ey + eh], 200, 340, fill=eye_c, width=int(U * 0.035))
        else:
            dr.ellipse([ex - ew, ey - eh, ex + ew, ey + eh], fill=eye_c)
            dr.ellipse([ex - ew * 0.45, ey - eh * 0.7, ex + ew * 0.05, ey - eh * 0.15], fill=(255, 255, 255))
    lw = int(U * 0.04)
    if expr == "angry":
        dr.line([ex1 - ew * 2, ey - eh * 2.0, ex1 + ew * 1.5, ey - eh * 1.2], fill=eye_c, width=lw)
        dr.line([ex2 + ew * 2, ey - eh * 2.0, ex2 - ew * 1.5, ey - eh * 1.2], fill=eye_c, width=lw)
    if expr == "sad":
        dr.line([ex1 - ew * 2, ey - eh * 1.3, ex1 + ew * 1.5, ey - eh * 2.0], fill=eye_c, width=lw)
        dr.line([ex2 + ew * 2, ey - eh * 1.3, ex2 - ew * 1.5, ey - eh * 2.0], fill=eye_c, width=lw)
    # Accessoires über den Augen
    acc = spec.get("accessory", "none")
    if acc == "sunglasses":
        dr.rounded_rectangle([x + w * 0.18, ey - eh * 1.2, x + w * 0.82, ey + eh * 1.0], radius=int(U * .05), fill=(15, 15, 20))
    elif acc == "eyemask":
        dr.rounded_rectangle([x + w * 0.1, ey - eh * 1.4, x + w * 0.9, ey + eh * 1.3], radius=int(U * .08), fill=(20, 20, 24))
        for ex in (ex1, ex2):
            dr.ellipse([ex - ew * 1.2, ey - eh * 0.8, ex + ew * 1.2, ey + eh * 0.8], fill=(240, 240, 240))
            dr.ellipse([ex - ew * 0.7, ey - eh * 0.6, ex + ew * 0.7, ey + eh * 0.6], fill=eye_c)
    elif acc == "glasses":
        for ex in (ex1, ex2):
            dr.ellipse([ex - ew * 2.2, ey - eh * 1.2, ex + ew * 2.2, ey + eh * 1.2], outline=eye_c, width=int(U * .025))
    # Mund
    mx, my, mw = x + w * 0.5, y + h * 0.66, w * 0.36
    red, dark = (215, 40, 45), (60, 15, 15)
    if expr == "shocked":
        r = w * (0.09 if mouth_open else 0.06)
        dr.ellipse([mx - r, my - r * 0.6, mx + r, my + r * 1.5], fill=dark)
    elif mouth_open or expr == "grin":
        dr.chord([mx - mw / 2, my - h * 0.1, mx + mw / 2, my + h * 0.17], 0, 180, fill=dark)
        dr.chord([mx - mw / 3, my + h * 0.02, mx + mw / 3, my + h * 0.16], 0, 180, fill=red)
        dr.line([mx - mw / 2, my + h * 0.035, mx + mw / 2, my + h * 0.035], fill=(250, 250, 250), width=int(U * .03))
    elif expr in ("angry", "sad"):
        dr.arc([mx - mw / 2.4, my, mx + mw / 2.4, my + h * 0.16], 200, 340, fill=eye_c, width=lw)
    elif expr == "neutral":
        dr.line([mx - mw / 3, my + h * 0.04, mx + mw / 3, my + h * 0.04], fill=eye_c, width=lw)
    elif expr == "smirk":
        dr.arc([mx - mw / 2, my - h * 0.1, mx + mw / 2.5, my + h * 0.07], 10, 120, fill=eye_c, width=lw)
    else:  # smile, wink
        dr.arc([mx - mw / 2, my - h * 0.12, mx + mw / 2, my + h * 0.08], 20, 160, fill=eye_c, width=lw)


def head(canvas, cx, top, spec, expr, mouth_open):
    dr = ImageDraw.Draw(canvas)
    w = h = 1.32 * U
    x, y = cx - w / 2, top
    skin = hx(spec["skin"])
    hair = spec.get("hair", "none")
    hair_c = hx(spec.get("hair_color", "#2a1d14"))
    if hair == "long":
        box(dr, x - 0.08 * U, y + 0.05 * U, w + 0.16 * U, h * 1.15, hair_c, top=False)
    box(dr, x, y, w, h, skin, r=0.18)
    beard = spec.get("beard", "none")
    bc = hx(spec.get("beard_color", spec.get("hair_color", "#1a1a1a")))
    if beard in ("short", "full"):
        dr.rounded_rectangle([x, y + h * (0.55 if beard == "short" else 0.45), x + w, y + h], radius=int(U * .15), fill=bc)
        dr.polygon([(x + w, y + h * 0.55), (x + w + D * U, y + h * 0.55 - D * U), (x + w + D * U, y + h - D * U), (x + w, y + h)], fill=shade(bc, .62))
        # Hautfläche um den Mund freilassen
        dr.rounded_rectangle([x + w * 0.27, y + h * 0.56, x + w * 0.73, y + h * 0.84], radius=int(U * .08), fill=skin)
    face(dr, x, y, w, h, expr, mouth_open, spec)
    if beard == "mustache":
        dr.rounded_rectangle([x + w * 0.3, y + h * 0.58, x + w * 0.7, y + h * 0.66], radius=int(U * .04), fill=bc)
    if hair in ("short", "long", "spiky"):
        box(dr, x - 0.03 * U, y - 0.06 * U, w + 0.06 * U, h * 0.22, hair_c, r=0.08)
        if hair == "spiky":
            for i in range(5):
                sx = x + w * (0.1 + 0.2 * i)
                dr.polygon([(sx - 0.1 * U, y), (sx, y - 0.25 * U), (sx + 0.1 * U, y)], fill=hair_c)
    if hair == "bun":
        box(dr, x - 0.03 * U, y - 0.06 * U, w + 0.06 * U, h * 0.2, hair_c)
        dr.ellipse([cx - 0.22 * U, y - 0.45 * U, cx + 0.22 * U, y], fill=hair_c)
    hat = spec.get("hat", "none")
    hc = hx(spec.get("hat_color", "#333333"))
    if hat == "flatcap":
        box(dr, x - 0.05 * U, y - 0.2 * U, w + 0.1 * U, 0.32 * U, hc, r=0.12)
        dr.rounded_rectangle([x - 0.02 * U, y + 0.06 * U, x + w + 0.02 * U, y + 0.18 * U], radius=int(U * .05), fill=shade(hc, .8))
    elif hat == "police":
        box(dr, x - 0.08 * U, y - 0.3 * U, w + 0.16 * U, 0.36 * U, hc, r=0.06)
        dr.rectangle([x, y + 0.04 * U, x + w, y + 0.16 * U], fill=(20, 20, 20))
        dr.ellipse([cx - 0.09 * U, y - 0.22 * U, cx + 0.09 * U, y - 0.04 * U], fill=(230, 190, 60))
    elif hat == "tophat":
        box(dr, x - 0.15 * U, y - 0.06 * U, w + 0.3 * U, 0.12 * U, hc, r=0.03)
        box(dr, x + 0.1 * U, y - 0.75 * U, w - 0.2 * U, 0.7 * U, hc, r=0.04)
    elif hat == "beanie":
        box(dr, x - 0.04 * U, y - 0.25 * U, w + 0.08 * U, 0.48 * U, hc, r=0.2)
        dr.rectangle([x - 0.04 * U, y + 0.1 * U, x + w + 0.04 * U, y + 0.23 * U], fill=shade(hc, .85))
    elif hat == "cap":
        box(dr, x - 0.03 * U, y - 0.18 * U, w + 0.06 * U, 0.3 * U, hc, r=0.15)
        dr.rounded_rectangle([x + w * 0.1, y + 0.06 * U, x + w * 1.05, y + 0.16 * U], radius=int(U * .04), fill=shade(hc, .8))


def torso(canvas, cx, top, spec):
    dr = ImageDraw.Draw(canvas)
    w, h = 2.0 * U, 2.0 * U
    x, y = cx - w / 2, top
    outfit = spec.get("outfit", "suit")
    jacket = hx(spec.get("jacket", spec.get("shirt", "#3355aa")))
    shirt = hx(spec.get("shirt", "#ffffff"))
    if outfit in ("suit", "jacket", "uniform"):
        box(dr, x, y, w, h, jacket, r=0.06)
        dr.polygon([(cx - 0.42 * U, y), (cx + 0.42 * U, y), (cx, y + h * 0.5)], fill=shirt)
        if spec.get("tie"):
            tc = hx(spec["tie"])
            dr.polygon([(cx - 0.1 * U, y + 0.05 * U), (cx + 0.1 * U, y + 0.05 * U), (cx + 0.14 * U, y + h * 0.42),
                        (cx, y + h * 0.5), (cx - 0.14 * U, y + h * 0.42)], fill=tc)
        dr.line([(cx - 0.42 * U, y), (cx, y + h * 0.5), (cx + 0.42 * U, y)], fill=shade(jacket, .7), width=int(U * .05))
        for i in range(3):
            dr.ellipse([cx - 0.05 * U, y + h * (0.6 + 0.12 * i), cx + 0.05 * U, y + h * (0.6 + 0.12 * i) + 0.1 * U], fill=shade(jacket, .55))
        if outfit == "uniform":
            dr.rectangle([x + w * 0.62, y + h * 0.22, x + w * 0.8, y + h * 0.36], fill=(230, 190, 60))
    elif outfit == "hoodie":
        box(dr, x, y, w, h, jacket, r=0.1)
        dr.rounded_rectangle([x + w * 0.25, y + h * 0.6, x + w * 0.75, y + h * 0.85], radius=int(U * .06), fill=shade(jacket, .85))
        dr.line([(cx - 0.15 * U, y), (cx - 0.15 * U, y + h * 0.35)], fill=(240, 240, 240), width=int(U * .04))
        dr.line([(cx + 0.15 * U, y), (cx + 0.15 * U, y + h * 0.35)], fill=(240, 240, 240), width=int(U * .04))
    else:  # tshirt
        box(dr, x, y, w, h, shirt, r=0.06)
    if spec.get("belt", True):
        dr.rectangle([x, y + h - 0.16 * U, x + w, y + h - 0.04 * U], fill=(30, 25, 22))
    acc = spec.get("neck")
    if acc == "chain":
        dr.arc([cx - 0.6 * U, y - 0.3 * U, cx + 0.6 * U, y + 0.55 * U], 20, 160, fill=(235, 200, 70), width=int(U * .07))
    elif acc == "pearls":
        for i in range(9):
            import math
            a = math.radians(25 + i * 16)
            px, py = cx + 0.55 * U * math.cos(a), y + 0.1 * U + 0.4 * U * math.sin(a)
            dr.ellipse([px - .07 * U, py - .07 * U, px + .07 * U, py + .07 * U], fill=(245, 240, 225))


@lru_cache(maxsize=512)
def _render(spec_items, pose, expr, mouth_open, phase):
    spec = dict(spec_items)
    W, H = int(5 * U), int(6.8 * U)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cx = W / 2
    head_top = 1.0 * U
    torso_top = head_top + 1.32 * U + 0.02 * U
    hip = torso_top + 2.0 * U
    pants = spec.get("pants", "#2b2f3a")
    shoes = spec.get("shoes", "#1b1b1b")
    skin = spec["skin"]
    sleeve = spec.get("jacket", spec.get("shirt")) if spec.get("outfit", "suit") != "tshirt" else spec.get("shirt")

    import math
    swing, lift_l, lift_r = 0, 0, 0
    if pose in ("walk", "run"):
        k = 1 if pose == "walk" else 2
        sn = math.sin(phase * 2 * math.pi)
        swing = sn * 18 * k
        lift_l, lift_r = max(0, sn) * 0.22 * U * k, max(0, -sn) * 0.22 * U * k
    leg = limb(2.0 * U, 0.98 * U, pants, shoe=shoes)
    # Beine: beim Laufen abwechselnd anheben (Frontansicht)
    paste_rot(img, leg, None, (cx - 0.5 * U, hip - lift_l), 0)
    paste_rot(img, leg, None, (cx + 0.5 * U, hip - lift_r), 0)
    torso(img, cx, torso_top, spec)
    la, ra = POSES.get(pose, POSES["idle"])
    if pose in ("walk", "run"):
        la, ra = 8 + swing, -8 + swing
    arm = limb(2.0 * U, 0.95 * U, sleeve, end_color=skin)
    paste_rot(img, arm, None, (cx - 1.48 * U, torso_top + 0.05 * U), -la)
    paste_rot(img, arm, None, (cx + 1.48 * U, torso_top + 0.05 * U), -ra)
    head(img, cx, head_top, spec, expr, mouth_open)
    return img


def render(spec: dict, pose="idle", expr="smile", mouth_open=False, phase=0.0) -> Image.Image:
    keep = {k: v for k, v in spec.items() if isinstance(v, (str, int, float, bool)) or v is None}
    return _render(tuple(sorted(keep.items())), pose, expr, bool(mouth_open), round(phase, 2))


def shadow(w, h):
    s = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(s).ellipse([0, 0, w, h], fill=(0, 0, 0, 110))
    return s.filter(ImageFilter.GaussianBlur(h / 4))
