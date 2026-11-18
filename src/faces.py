"""Zeichnet Anime-Gesichter als transparente Texturen für die 3D-Köpfe."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024  # Texturgröße
EXPRESSIONS = ["neutral", "happy", "smile", "shocked", "angry", "sad", "smirk", "worried", "wink", "laugh"]


def hx(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def eye(dr, img, cx, cy, iris, expr, side, closed=False):
    w, h = S * 0.175, S * 0.24
    line = (35, 25, 30)
    if closed or expr in ("happy", "laugh"):  # ^ ^ Augen
        dr.arc([cx - w * .6, cy - h * .25, cx + w * .6, cy + h * .45], 200, 340, fill=line, width=int(S * .028))
        return
    if expr == "shocked":
        h *= 1.08
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    # Weiß des Auges
    dr.rounded_rectangle([x0, y0, x1, y1], radius=int(w * .45), fill=(255, 255, 255))
    # Iris mit Verlauf
    ir_w, ir_h = w * (0.55 if expr == "shocked" else 0.86), h * (0.62 if expr == "shocked" else 0.84)
    icx, icy = cx + side * w * 0.04, cy + h * 0.06
    lay = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    top, bot = mix(iris, (20, 10, 10), .55), mix(iris, (255, 240, 200), .35)
    steps = 24
    for i in range(steps):
        t = i / steps
        yy0 = icy - ir_h / 2 + ir_h * t
        ld.rectangle([icx - ir_w / 2, yy0, icx + ir_w / 2, yy0 + ir_h / steps + 1], fill=mix(top, bot, t) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([icx - ir_w / 2, icy - ir_h / 2, icx + ir_w / 2, icy + ir_h / 2], fill=255)
    img.paste(lay, (0, 0), mask)
    # Pupille + Glanzlichter
    pw = ir_w * (0.32 if expr != "shocked" else 0.25)
    dr.ellipse([icx - pw / 2, icy - pw * .7, icx + pw / 2, icy + pw * .7], fill=(25, 15, 15))
    dr.ellipse([icx - ir_w * .32, icy - ir_h * .36, icx - ir_w * .02, icy - ir_h * .08], fill=(255, 255, 255))
    dr.ellipse([icx + ir_w * .1, icy + ir_h * .12, icx + ir_w * .26, icy + ir_h * .28], fill=(255, 255, 255))
    # obere Wimpernlinie (dick) + Lidschatten
    dr.arc([x0 - w * .08, y0 - h * .02, x1 + w * .08, y1 + h * .4], 195, 345, fill=line, width=int(S * .03))
    dr.line([(x1 if side > 0 else x0, cy - h * .32), (x1 + side * w * .14, cy - h * .38)], fill=line, width=int(S * .022))
    if expr in ("angry", "smirk"):  # halb geschlossen
        dr.polygon([(x0 - 6, y0 - 4), (x1 + 6, y0 - 4), (x1 + 6, cy - h * (0.05 if side > 0 else 0.25)),
                    (x0 - 6, cy - h * (0.25 if side > 0 else 0.05))], fill=(0, 0, 0, 0))


def brows(dr, cx, cy, expr, side):
    w = S * .15
    line = (45, 30, 30)
    y = cy - S * .17
    tilt = {"angry": -1, "sad": 1, "worried": 1, "shocked": 0, "smirk": -0.5}.get(expr, 0.15)
    inner, outer = cx - side * w * .5, cx + side * w * .5
    dy = S * .035 * tilt
    if expr == "shocked":
        y -= S * .03
    dr.line([(inner, y + dy), (outer, y - dy)], fill=line, width=int(S * .022))


def mouth(dr, expr):
    cx, cy = S * .5, S * .76
    line = (60, 25, 25)
    red, dark = (215, 70, 75), (95, 25, 30)
    if expr in ("happy", "laugh"):
        w = S * (.2 if expr == "happy" else .25)
        dr.chord([cx - w / 2, cy - S * .06, cx + w / 2, cy + S * .1], 0, 180, fill=dark)
        dr.chord([cx - w / 3, cy + S * .01, cx + w / 3, cy + S * .1], 0, 180, fill=red)
        dr.line([cx - w / 2 + 8, cy - S * .01, cx + w / 2 - 8, cy - S * .01], fill=(255, 255, 255), width=int(S * .02))
    elif expr == "shocked":
        dr.ellipse([cx - S * .045, cy - S * .03, cx + S * .045, cy + S * .07], fill=dark)
    elif expr in ("sad", "worried"):
        dr.arc([cx - S * .07, cy, cx + S * .07, cy + S * .08], 200, 340, fill=line, width=int(S * .016))
    elif expr == "angry":
        dr.line([cx - S * .06, cy + S * .03, cx + S * .06, cy + S * .02], fill=line, width=int(S * .018))
    elif expr == "smirk":
        dr.arc([cx - S * .05, cy - S * .06, cx + S * .09, cy + S * .03], 20, 120, fill=line, width=int(S * .016))
    elif expr in ("smile", "wink"):
        dr.arc([cx - S * .07, cy - S * .06, cx + S * .07, cy + S * .03], 25, 155, fill=line, width=int(S * .016))
    else:  # neutral
        dr.line([cx - S * .03, cy + S * .02, cx + S * .03, cy + S * .02], fill=line, width=int(S * .014))


def draw_face(eye_color: str, expr: str, dest: Path, blush=False):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    iris = hx(eye_color)
    for side, cx in ((-1, S * .3), (1, S * .7)):
        cy = S * .48
        closed = expr == "wink" and side > 0
        eye(dr, img, cx, cy, iris, expr, side, closed)
        brows(dr, cx, cy, expr, side)
    if blush or expr in ("happy", "laugh"):
        bl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bl)
        for cx in (S * .24, S * .76):
            bd.ellipse([cx - S * .07, S * .62, cx + S * .07, S * .68], fill=(255, 120, 130, 90))
        img.alpha_composite(bl.filter(ImageFilter.GaussianBlur(14)))
    if expr == "worried":  # Schweißtropfen
        dr.ellipse([S * .82, S * .3, S * .88, S * .4], fill=(150, 210, 255))
    mouth(dr, expr)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    return dest


def face_textures(specs: dict, needed: set, outdir: Path) -> dict:
    """needed = {(char_id, expression)} -> {"id:expr": pfad}"""
    out = {}
    for cid, expr in needed:
        if cid not in specs:
            continue
        expr = expr if expr in EXPRESSIONS else "neutral"
        p = outdir / f"face_{cid}_{expr}.png"
        if not p.exists():
            draw_face(specs[cid].get("eye_color", "#d9822b"), expr, p)
        out[f"{cid}:{expr}"] = str(p.resolve())
    return out
