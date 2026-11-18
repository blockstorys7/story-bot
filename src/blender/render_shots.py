"""Blender-Skript: baut für jede Einstellung eine Roblox-artige 3D-Szene und rendert ein Bild.

Aufruf:  blender -b -P src/blender/render_shots.py -- shots.json ausgabe_ordner
shots.json = {"render": {...}, "characters": {id: spec}, "faces": {"id:expr": png}, "font": ttf,
              "shots": [{"set", "sign_text", "room_type", "shot", "focus", "characters": [...], "props": [...]}]}
"""
import json
import math
import os
import random
import sys

import bmesh
import bpy
from mathutils import Vector

ARGS = sys.argv[sys.argv.index("--") + 1:]
DATA = json.load(open(ARGS[0], encoding="utf-8"))
OUT = ARGS[1]
ONLY = set(int(x) for x in ARGS[2].split(",")) if len(ARGS) > 2 and ARGS[2] else None
R = DATA.get("render", {})
FONT = None
MATS = {}


# ---------------------------------------------------------------- Grundbausteine
def lin(c):
    """Hex (sRGB) -> lineare RGBA-Farbe für Blender."""
    c = c.lstrip("#")
    out = []
    for i in (0, 2, 4):
        v = int(c[i:i + 2], 16) / 255
        out.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return (*out, 1.0)


def mat(color, rough=0.55, metal=0.0, key=None):
    k = key or f"{color}-{rough}-{metal}"
    if k in MATS:
        return MATS[k]
    m = bpy.data.materials.new(k)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = lin(color)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    MATS[k] = m
    return m


def brick_mat(c1="#b5523b", c2="#a3462f", mortar="#d9cbb8", scale=3.0):
    k = f"brick-{c1}-{scale}"
    if k in MATS:
        return MATS[k]
    m = bpy.data.materials.new(k)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    br = nt.nodes.new("ShaderNodeTexBrick")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    br.inputs["Color1"].default_value = lin(c1)
    br.inputs["Color2"].default_value = lin(c2)
    br.inputs["Mortar"].default_value = lin(mortar)
    br.inputs["Scale"].default_value = scale
    br.inputs["Mortar Size"].default_value = 0.025
    nt.links.new(tc.outputs["Object"], br.inputs["Vector"])
    nt.links.new(br.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.8
    MATS[k] = m
    return m


def stripe_mat(c1, c2, scale=6.0, key=None):
    """Holzboden / Dielen über Wellen-Textur."""
    k = key or f"wood-{c1}"
    if k in MATS:
        return MATS[k]
    m = bpy.data.materials.new(k)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    w = nt.nodes.new("ShaderNodeTexWave")
    w.inputs["Scale"].default_value = scale
    w.inputs["Distortion"].default_value = 2.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = lin(c1)
    ramp.color_ramp.elements[1].color = lin(c2)
    nt.links.new(w.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.6
    MATS[k] = m
    return m


def link(obj, parent=None):
    bpy.context.scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def mesh_obj(name, bm, material, parent=None, smooth=False):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    me.materials.append(material)
    return link(bpy.data.objects.new(name, me), parent)


def box(dims, loc, material, parent=None, bevel=0.06, name="box", rot=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(dims), verts=bm.verts)
    o = mesh_obj(name, bm, material, parent, smooth=bevel > 0)
    o.location = loc
    o.rotation_euler = rot
    if bevel > 0:
        mod = o.modifiers.new("bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 3
        mod.limit_method = "ANGLE"
        try:
            mod.harden_normals = True
            o.data.use_auto_smooth = True  # Blender < 4.1
        except Exception:
            pass
    return o


def cyl(r, depth, loc, material, parent=None, r2=None, seg=24, rot=(0, 0, 0), name="cyl"):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r,
                          radius2=r if r2 is None else r2, depth=depth)
    o = mesh_obj(name, bm, material, parent, smooth=True)
    o.location = loc
    o.rotation_euler = rot
    return o


def sphere(r, loc, material, parent=None, scale=(1, 1, 1), name="sph"):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=14, radius=r)
    o = mesh_obj(name, bm, material, parent, smooth=True)
    o.location = loc
    o.scale = scale
    return o


def empty(loc, parent=None, name="pivot"):
    e = bpy.data.objects.new(name, None)
    e.location = loc
    return link(e, parent)


def text(body, loc, size, color="#ffffff", parent=None, extrude=0.03, rot=(math.radians(90), 0, 0), max_w=None):
    cu = bpy.data.curves.new("txt", "FONT")
    cu.body = body
    if FONT:
        cu.font = FONT
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.size = size
    cu.extrude = extrude
    o = link(bpy.data.objects.new("txt", cu), parent)
    o.location = loc
    o.rotation_euler = rot
    o.data.materials.append(mat(color, 0.4))
    if max_w:  # zu breiten Text verkleinern
        bpy.context.view_layer.update()
        w = o.dimensions.x
        if w > max_w:
            s = max_w / w
            o.scale = (s, s, s)
    return o


def image_plane(path, size, loc, parent=None, rot=(math.radians(90), 0, 0)):
    me = bpy.data.meshes.new("decal")
    h = size / 2
    me.from_pydata([(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    for i, c in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[i].uv = c
    key = f"img-{path}"
    if key not in MATS:
        m = bpy.data.materials.new(key)
        m.use_nodes = True
        nt = m.node_tree
        b = nt.nodes["Principled BSDF"]
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(path)
        nt.links.new(tex.outputs["Color"], b.inputs["Base Color"])
        nt.links.new(tex.outputs["Alpha"], b.inputs["Alpha"])
        b.inputs["Roughness"].default_value = 0.6
        try:
            m.blend_method = "HASHED"
        except Exception:
            pass
        MATS[key] = m
    me.materials.append(MATS[key])
    o = link(bpy.data.objects.new("decal", me), parent)
    o.location = loc
    o.rotation_euler = rot
    return o


# ---------------------------------------------------------------- Figuren
POSES = {  # (vor, seitlich) in Grad je Arm  [links(+x), rechts(-x)], Beine (vor)
    "idle": ((0, 4), (0, 4), (0, 0)), "wave": ((0, 4), (10, 155), (0, 0)),
    "point": ((0, 4), (88, 6), (0, 0)), "arms_up": ((0, 160), (0, 160), (0, 0)),
    "shrug": ((25, 38), (25, 38), (0, 0)), "hold_sign": ((172, 6), (172, 6), (0, 0)),
    "think": ((0, 6), (125, -22), (0, 0)), "carry": ((78, 0), (78, 0), (0, 0)),
    "hands_hips": ((0, 28), (0, 28), (0, 0)), "walk": ((-22, 4), (22, 4), (22, -22)),
    "run": ((-45, 6), (45, 6), (38, -38)), "sneak": ((40, 10), (40, 10), (12, -12)),
    "victory": ((0, 4), (0, 165), (0, 0)), "facepalm": ((0, 4), (140, -30), (0, 0)),
}


def hair(spec, head, rng):
    style = spec.get("hair", "short")
    if style == "none":
        return
    hm = mat(spec.get("hair_color", "#3a2a20"), 0.45)
    top = 1.25 / 2
    # Grundkappe + Hinterkopf
    box((1.42, 1.32, 0.42), (0, 0.03, top + 0.12), hm, head, bevel=0.17, name="hair")
    box((1.42, 0.5, 1.0), (0, 0.45, top - 0.3), hm, head, bevel=0.15, name="hair")
    for sx in (-1, 1):  # Seiten
        box((0.16, 1.0, 0.75 if style != "long" else 1.6), (sx * 0.7, 0.1, top - 0.25 - (0.4 if style == "long" else 0)),
            hm, head, bevel=0.06, name="hair")
    n_front = {"spiky": 7, "messy": 8, "short": 5, "long": 6, "bun": 5}.get(style, 5)
    for i in range(n_front):  # Pony / Fransen vorne, nach unten zeigend
        x = -0.6 + 1.2 * (i + 0.5) / n_front + rng.uniform(-0.04, 0.04)
        ln = rng.uniform(0.38, 0.62) if style in ("spiky", "messy") else rng.uniform(0.25, 0.4)
        tilt = rng.uniform(-0.35, 0.35)
        cyl(0.17, ln, (x, -0.66, top - 0.05), hm, head, r2=0.0, seg=6,
            rot=(math.radians(165), tilt, 0), name="fringe")
    if style in ("spiky", "messy"):
        n = 16 if style == "spiky" else 12
        for i in range(n):  # Strähnen ringsum nach außen
            a = 2 * math.pi * i / n + rng.uniform(-0.2, 0.2)
            el = rng.uniform(0.15, 0.9)
            d = Vector((math.cos(a) * math.cos(el), math.sin(a) * math.cos(el) * 0.9 + 0.25, math.sin(el)))
            pos = Vector((0, 0.1, top - 0.05)) + d * 0.55
            q = d.to_track_quat("Z", "Y")
            o = cyl(0.2, rng.uniform(0.5, 0.85) if style == "spiky" else rng.uniform(0.35, 0.55),
                    pos + d * 0.2, hm, head, r2=0.0, seg=6, name="spike")
            o.rotation_mode = "QUATERNION"
            o.rotation_quaternion = q
    if style == "bun":
        sphere(0.36, (0, 0.35, top + 0.45), hm, head)
    if style == "long":
        box((1.42, 0.3, 1.9), (0, 0.55, top - 1.0), hm, head, bevel=0.12, name="hair")


def hat(spec, head):
    kind = spec.get("hat", "none")
    if kind == "none":
        return
    hm = mat(spec.get("hat_color", "#1d2b55"), 0.5)
    top = 1.25 / 2
    if kind == "police":
        cyl(0.78, 0.42, (0, 0, top + 0.22), hm, head, r2=0.82)
        box((1.35, 0.6, 0.06), (0, -0.62, top + 0.02), mat("#111111", 0.3), head, bevel=0.02)
        box((0.22, 0.04, 0.22), (0, -0.8, top + 0.27), mat("#e8c050", 0.3, 0.6), head, bevel=0.02)
    elif kind == "tophat":
        cyl(1.0, 0.08, (0, 0, top + 0.08), hm, head)
        cyl(0.62, 1.2, (0, 0, top + 0.7), hm, head)
        cyl(0.63, 0.18, (0, 0, top + 0.22), mat("#a01c24", 0.4), head)
    elif kind == "beanie":
        sphere(0.78, (0, 0, top - 0.05), hm, head, scale=(1, 0.95, 0.85))
        cyl(0.8, 0.25, (0, 0, top - 0.1), mat(spec.get("hat_color", "#88b8e8"), 0.7, key="beanierim"), head)
    elif kind == "cap":
        sphere(0.74, (0, 0.02, top - 0.02), hm, head, scale=(1, 1, 0.7))
        box((1.1, 0.7, 0.06), (0, -0.75, top - 0.05), hm, head, bevel=0.03)
    elif kind == "flatcap":
        sphere(0.78, (0, 0.05, top + 0.05), hm, head, scale=(1, 1.1, 0.45))
        box((1.2, 0.45, 0.05), (0, -0.7, top - 0.02), hm, head, bevel=0.02)


def outfit(spec, torso_parent):
    o = spec.get("outfit", "suit")
    top = spec.get("top", "#1b1b20")
    trim = spec.get("trim")
    shirt = spec.get("shirt", "#ffffff")
    if o == "tshirt":
        box((2, 1, 2), (0, 0, 3), mat(shirt), torso_parent, name="torso")
        return
    box((2, 1, 2), (0, 0, 3), mat(top), torso_parent, name="torso")
    if o in ("suit", "jacket", "uniform"):
        box((0.62, 0.04, 1.3), (0, -0.51, 3.3), mat(shirt), torso_parent, bevel=0.01)
        if spec.get("tie"):
            box((0.18, 0.05, 0.95), (0, -0.53, 3.35), mat(spec["tie"], 0.35), torso_parent, bevel=0.01)
        if trim:
            for sx in (-1, 1):
                box((0.1, 0.05, 1.95), (sx * 0.36, -0.52, 3.0), mat(trim, 0.4), torso_parent, bevel=0.01)
            box((2.02, 0.05, 0.1), (0, -0.52, 2.08), mat(trim, 0.4), torso_parent, bevel=0.01)
        if o == "uniform":
            box((0.28, 0.05, 0.32), (0.55, -0.53, 3.45), mat("#e8c050", 0.3, 0.7), torso_parent, bevel=0.02)
    elif o == "hoodie":
        box((1.1, 0.05, 0.5), (0, -0.52, 2.45), mat(top, 0.7, key=f"{top}-pocket"), torso_parent, bevel=0.03)
        for sx in (-0.18, 0.18):
            box((0.05, 0.04, 0.6), (sx, -0.53, 3.6), mat("#f2f2f2"), torso_parent, bevel=0.01)
        box((1.6, 0.6, 0.35), (0, 0.15, 4.0), mat(top), torso_parent, bevel=0.12)  # Kapuze
    elif o == "dress":
        box((2.2, 1.1, 1.2), (0, 0, 2.3), mat(top), torso_parent, bevel=0.08)


def character(cid, spec, cfg, faces):
    rng = random.Random(cid)  # gleiche Figur = gleiche Haare in jedem Bild
    root = empty((cfg["x"], cfg.get("y", 0), 0), name=f"char-{cid}")
    root.rotation_euler = (0, 0, math.radians(cfg.get("turn", 0)))
    skin = mat(spec.get("skin", "#f1c9a5"), 0.5)
    pose = cfg.get("pose", "idle")
    (lf, ls), (rf, rs), (lg, rg) = POSES.get(pose, POSES["idle"])
    pants = mat(spec.get("pants", "#22232a"))
    shoes = mat(spec.get("shoes", "#111111"), 0.4)
    for sx, fwd in ((1, lg), (-1, rg)):  # Beine
        p = empty((sx * 0.5, 0, 2.0), root)
        p.rotation_euler = (math.radians(-fwd), 0, 0)
        box((0.98, 0.98, 1.72), (0, 0, -0.86), pants, p, name="leg")
        box((1.0, 1.02, 0.3), (0, -0.01, -1.85), shoes, p, name="shoe")
    outfit(spec, root)
    sleeve = mat(spec.get("shirt") if spec.get("outfit") == "tshirt" else spec.get("top", "#1b1b20"))
    for sx, (fwd, side) in ((1, (lf, ls)), (-1, (rf, rs))):  # Arme
        p = empty((sx * 1.5, 0, 3.88), root)
        p.rotation_euler = (math.radians(-fwd), math.radians(-sx * side), 0)
        if spec.get("outfit") == "tshirt":
            box((0.98, 0.98, 0.7), (0, 0, -0.35), sleeve, p, name="sleeve")
            box((0.97, 0.97, 1.3), (0, 0, -1.3), skin, p, name="arm")
        else:
            box((0.98, 0.98, 1.6), (0, 0, -0.8), sleeve, p, name="sleeve")
            if spec.get("trim"):
                box((1.0, 1.0, 0.1), (0, 0, -1.55), mat(spec["trim"], 0.4), p, bevel=0.01)
            box((0.96, 0.96, 0.4), (0, 0, -1.8), skin, p, name="hand")
    # Kopf
    hp = empty((0, 0, 4.0), root, name="neck")
    tilt = {"sad": 8, "worried": 5, "shocked": -6, "angry": 4}.get(cfg.get("expression", ""), 0)
    hp.rotation_euler = (math.radians(tilt), 0, math.radians(cfg.get("look", 0)))
    head = empty((0, 0, 0.66), hp, name="head")
    box((1.3, 1.2, 1.25), (0, 0, 0), skin, head, bevel=0.3, name="headbox")
    fkey = f"{cid}:{cfg.get('expression', 'neutral')}"
    fpath = faces.get(fkey) or faces.get(f"{cid}:neutral")
    if fpath:
        image_plane(fpath, 1.18, (0, -0.606, -0.04), head)
    hair(spec, head, rng)
    hat(spec, head)
    # Requisiten
    prop = cfg.get("prop")
    if prop == "sign" or pose == "hold_sign":
        board = empty((0, -0.9, 7.2), root)
        box((3.6, 0.12, 1.8), (0, 0, 0), mat("#f4f1ea", 0.6), board, bevel=0.04)
        lines = (cfg.get("sign_text") or "NEUE REGEL").split(":", 1)
        if len(lines) == 2:
            text(lines[0].strip() + ":", (0, -0.08, 0.45), 0.42, "#c81e28", board, max_w=3.3)
            text(lines[1].strip(), (0, -0.08, -0.25), 0.36, "#1a1a1a", board, max_w=3.3)
        else:
            text(lines[0].strip(), (0, -0.08, 0), 0.5, "#1a1a1a", board, max_w=3.3)
    elif prop == "bread":
        sphere(0.45, (-1.5, -1.3, 2.7), mat("#c98a3c", 0.5), root, scale=(1.4, 0.8, 0.7))
    elif prop == "box":
        box((1.6, 1.0, 1.0), (0, -1.4, 2.6), mat("#b08350", 0.7), root, bevel=0.03)
    return root


# ---------------------------------------------------------------- Umgebungen
def world(kind="sky"):
    w = bpy.data.worlds.new("w")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes["Background"]
    if kind == "sky":
        sky = nt.nodes.new("ShaderNodeTexSky")
        try:
            sky.sky_type = "NISHITA"
            sky.sun_elevation = math.radians(48)
            sky.sun_rotation = math.radians(200)
            sky.altitude = 200
            sky.air_density = 1.4
        except Exception:
            pass
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.32
    else:
        bg.inputs["Color"].default_value = lin("#fff4e6")
        bg.inputs["Strength"].default_value = 0.6


def sun(strength=3.2, rot=(50, 12, 35)):
    ld = bpy.data.lights.new("sun", "SUN")
    ld.energy = strength
    ld.angle = math.radians(6)
    ld.color = (1.0, 0.96, 0.9)
    o = link(bpy.data.objects.new("sun", ld))
    o.rotation_euler = tuple(math.radians(a) for a in rot)


def area(loc, power, size, rot=(0, 0, 0), color=(1, 0.96, 0.9)):
    ld = bpy.data.lights.new("area", "AREA")
    ld.energy = power
    ld.size = size
    ld.color = color
    o = link(bpy.data.objects.new("area", ld))
    o.location = loc
    o.rotation_euler = tuple(math.radians(a) for a in rot)


def clouds(rng, y=160, n=7):
    cm = mat("#ffffff", 0.9, key="cloud")
    for _ in range(n):
        x, z = rng.uniform(-90, 90), rng.uniform(45, 80)
        for k in range(4):
            sphere(rng.uniform(6, 10), (x + k * 7 + rng.uniform(-2, 2), y + rng.uniform(-5, 5), z + rng.uniform(-2, 3)),
                   cm, scale=(1.4, 0.6, 0.7))


def hills(y=140, color="#6f8f5a"):
    rng = random.Random(7)
    for i in range(8):
        sphere(rng.uniform(25, 45), (-120 + i * 34 + rng.uniform(-8, 8), y + rng.uniform(0, 25), -12),
               mat(color, 0.9, key="hill"), scale=(1.3, 0.8, 0.75))


def tree(loc):
    cyl(0.25, 2.2, (loc[0], loc[1], 1.1), mat("#6b4a2b", 0.8))
    for dx, dz in ((0, 3.0), (-0.6, 2.5), (0.6, 2.6)):
        sphere(1.1, (loc[0] + dx, loc[1], dz), mat("#4f9e3c", 0.8, key="leaf"))


def lamp(loc):
    gm = mat("#2c2f36", 0.4, 0.3)
    cyl(0.12, 6, (loc[0], loc[1], 3), gm)
    box((1.2, 0.2, 0.15), (loc[0] - 0.5 * (1 if loc[0] > 0 else -1), loc[1], 6), gm, bevel=0.02)


SHOP_NAMES = ["BÄCKER", "CAFÉ", "SHOP", "MARKT", "FRISEUR", "KIOSK", "POST", "BANK", "PIZZA", "APOTHEKE"]
FACADE_COLORS = ["#e8473c", "#f2b33d", "#3f8fd2", "#48b36b", "#9b59b6", "#f07c2a", "#2bb3b3", "#e85d8f", "#f4e3b5"]


def building(x0, y0, w, d, h, color, facing, rng, sign=None, door=True):
    """facing: Richtung, in die die Fassade zeigt: '-y', '+x', '-x'."""
    box((w, d, h), (x0, y0, h / 2), mat(color, 0.7), bevel=0.05)
    trim = mat("#f6f2e8", 0.6, key="trim")
    glass = mat("#7fb4e0", 0.15, key="glass")
    if facing == "-y":
        fy = y0 - d / 2 - 0.06
        box((w + 0.2, 0.4, 0.4), (x0, fy + 0.15, h + 0.1), trim, bevel=0.04)
        cols = max(2, int(w // 2.6))
        for row in range(1, max(2, int(h // 3.2))):
            for c in range(cols):
                wx = x0 - w / 2 + (c + 0.5) * w / cols
                box((1.3, 0.12, 1.6), (wx, fy, 1.4 + row * 3.0), trim, bevel=0.03)
                box((1.05, 0.14, 1.35), (wx, fy - 0.02, 1.4 + row * 3.0), glass, bevel=0.0)
        if door:
            box((1.8, 0.14, 2.9), (x0, fy, 1.45), mat("#3a6fb0", 0.4, key="door"), bevel=0.03)
        if sign:
            box((min(w - 0.6, 1.2 + 0.75 * len(sign)), 0.25, 1.3), (x0, fy - 0.1, 4.0), mat("#1d3557", 0.5, key="signbg"), bevel=0.05)
            text(sign, (x0, fy - 0.26, 4.0), 0.85, "#ffffff", max_w=w - 1.2)
    else:
        sx = 1 if facing == "+x" else -1
        fx = x0 + sx * (w / 2 + 0.06)
        for row in range(1, max(2, int(h // 3.2))):
            for c in range(max(2, int(d // 2.8))):
                wy = y0 - d / 2 + (c + 0.5) * d / max(2, int(d // 2.8))
                box((0.12, 1.3, 1.6), (fx, wy, 1.4 + row * 3.0), trim, bevel=0.03)
                box((0.14, 1.05, 1.35), (fx + sx * 0.02, wy, 1.4 + row * 3.0), glass, bevel=0.0)
        box((0.14, 1.7, 2.8), (fx, y0, 1.4), mat("#3a6fb0", 0.4, key="door"), bevel=0.03)
        aw = mat(rng.choice(["#d63c3c", "#2e86de", "#27ae60", "#f39c12"]), 0.6)
        box((1.3, d * 0.8, 0.12), (fx + sx * 0.6, y0, 3.3), aw, bevel=0.02, rot=(0, math.radians(-sx * 15), 0))
        if sign:
            t = text(sign, (fx + sx * 0.1, y0, 4.3), 0.7, "#ffffff", rot=(math.radians(90), 0, math.radians(sx * 90)), max_w=d * 0.8)
            box((0.15, min(d * 0.85, 0.65 * len(sign) + 1), 1.0), (fx + sx * 0.02, y0, 4.3), mat("#1d3557", 0.5, key="signbg"))
            t.location.x = fx + sx * 0.12


def set_street(shot, rng):
    world("sky")
    sun(3.4, (52, 10, 30))
    box((16, 260, 0.2), (0, 90, -0.1), mat("#5d6168", 0.85, key="asphalt"), bevel=0)
    for y in range(-20, 200, 8):
        box((0.3, 3.5, 0.02), (0, y, 0.01), mat("#f2f2f2", 0.6, key="lane"), bevel=0)
    for k in range(7):  # Zebrastreifen
        box((0.9, 3.2, 0.02), (-3.6 + k * 1.2, 9, 0.012), mat("#f2f2f2", 0.6, key="lane"), bevel=0)
    for sx in (-1, 1):
        box((4, 260, 0.35), (sx * 10, 90, 0.17), mat("#b9b6ad", 0.8, key="sidewalk"), bevel=0.02)
        y = -18
        i = 0
        while y < 190:
            d = rng.uniform(8, 12)
            h = rng.uniform(9, 17)
            c = FACADE_COLORS[(i * 3 + (sx > 0)) % len(FACADE_COLORS)]
            sign = rng.choice(SHOP_NAMES) if rng.random() < 0.45 else None
            building(sx * (12 + 4), y + d / 2, 8, d - 0.4, h, c, "+x" if sx < 0 else "-x", rng, sign=sign)
            y += d
            i += 1
        for ly in range(-10, 190, 18):
            lamp((sx * 8.6, ly))
    hills(230)
    clouds(rng, 260, 9)
    if shot.get("sign_text"):  # markantes Gebäude am Straßenende
        building(0, 210, 26, 12, 18, "#f4f1ea", "-y", rng, sign=shot["sign_text"])


def set_facade(shot, rng):
    world("sky")
    sun(3.4, (50, 8, 25))
    box((80, 80, 0.2), (0, 0, -0.1), mat("#5d6168", 0.85, key="asphalt"), bevel=0)
    box((80, 5, 0.35), (0, 6.5, 0.17), mat("#b9b6ad", 0.8, key="sidewalk"), bevel=0.02)
    col = shot.get("color") or rng.choice(FACADE_COLORS)
    sign = shot.get("sign_text") or "RATHAUS"
    if sign.upper() in ("RATHAUS", "MUSEUM", "SCHULE", "BANK", "GERICHT"):
        col = "#f4f1ea"
        building(0, 14, 22, 10, 14, col, "-y", rng, sign=sign)
        for cx in (-6, -3, 3, 6):  # Säulen
            cyl(0.45, 8, (cx, 8.6, 4.4), mat("#ffffff", 0.5, key="column"))
    else:
        building(0, 14, 14, 10, 11, col, "-y", rng, sign=sign)
    building(-17, 15, 12, 10, 15, rng.choice(FACADE_COLORS), "-y", rng, door=False)
    building(17, 15, 12, 10, 9, rng.choice(FACADE_COLORS), "-y", rng, door=False)
    for x in (-9, 9):
        lamp((x, 5))
    hills(150)
    clouds(rng, 200, 8)


ROOM_COLORS = {"bakery": "#f3e3c3", "office": "#e8edf2", "school": "#dfe8f2", "home": "#f2e6d8",
               "police": "#d9e2ec", "shop": "#f4efe6", "generic": "#f1e8d6"}


def set_room(shot, rng):
    world("indoor")
    rt = shot.get("room_type", "generic")
    wall = mat(ROOM_COLORS.get(rt, "#f1e8d6"), 0.85)
    box((16, 16, 0.2), (0, 2, -0.1), stripe_mat("#b07a45", "#8a5a30", 1.2, key="floor"), bevel=0)
    box((16, 0.3, 9), (0, 6.5, 4.5), wall, bevel=0)
    for sx in (-1, 1):
        box((0.3, 16, 9), (sx * 8, 2, 4.5), wall, bevel=0)
    box((16, 16, 0.2), (0, 2, 9), mat("#fbf8f2", 0.9, key="ceil"), bevel=0)
    box((16, 0.35, 0.5), (0, 6.3, 0.25), mat("#ffffff", 0.6, key="skirt"), bevel=0.02)
    area((0, -2, 8.7), 1400, 9, (0, 0, 0))
    area((0, -9, 5), 700, 8, (75, 0, 0))
    sign = shot.get("sign_text")
    if rt == "bakery":
        box((12, 1.6, 2.2), (0, 2.6, 1.1), mat("#f6f2ea", 0.5, key="counter"), bevel=0.05)
        box((12.2, 1.8, 0.15), (0, 2.6, 2.25), stripe_mat("#c08a55", "#9c6a3a", 2, key="countertop"), bevel=0.02)
        for row, z in enumerate((4.2, 5.4, 6.6)):
            box((11, 0.9, 0.12), (0, 6.0, z), stripe_mat("#c08a55", "#9c6a3a", 2, key="countertop"), bevel=0.02)
            for i in range(9):
                sphere(0.4, (-4.8 + i * 1.2, 5.9, z + 0.32), mat("#d9963f", 0.5, key="bread"), scale=(1.25, 0.9, 0.7))
        sign = sign or "BÄCKER"
    elif rt == "office" or rt == "police":
        box((5, 2.2, 0.2), (0, 2.5, 2.4), stripe_mat("#7a5232", "#5e3d22", 2, key="desk"), bevel=0.03)
        for sx in (-2.2, 2.2):
            box((0.2, 2, 2.3), (sx, 2.5, 1.15), mat("#5e3d22", 0.6), bevel=0.02)
        box((0.9, 0.6, 0.7), (1.3, 2.4, 2.85), mat("#222428", 0.3), bevel=0.03)
    elif rt == "school":
        box((7, 0.15, 3.2), (0, 6.3, 4.5), mat("#2f4f3a", 0.8, key="chalk"), bevel=0.03)
        box((2.2, 0.2, 4.0), (5.0, 6.3, 2.0), mat("#2f6fc0", 0.4, key="door2"), bevel=0.03)
    if sign:
        box((min(12, 1.4 + 0.8 * len(sign)), 0.15, 1.4), (0, 6.25, 7.5), mat("#e2572c", 0.5, key="roomsign"), bevel=0.05)
        text(sign, (0, 6.1, 7.5), 0.9, "#ffffff", max_w=11)


def set_jail(shot, rng):
    world("indoor")
    br = brick_mat()
    box((16, 16, 0.2), (0, 2, -0.1), mat("#bdbab3", 0.85, key="concrete"), bevel=0)
    box((16, 0.3, 9), (0, 6.5, 4.5), br, bevel=0)
    for sx in (-1, 1):
        box((0.3, 16, 9), (sx * 8, 2, 4.5), br, bevel=0)
    box((16, 16, 0.2), (0, 2, 9), mat("#e9e6df", 0.9, key="ceil2"), bevel=0)
    area((0, 1, 8.7), 1100, 7, (0, 0, 0))
    area((0, -9, 5), 600, 8, (75, 0, 0))
    box((5, 1.6, 0.6), (-4.5, 5.2, 1.2), mat("#d7d2c6", 0.8), bevel=0.05)  # Pritsche
    bars = mat("#1c1d21", 0.35, 0.6, key="bars")
    x = -7.6
    while x <= 7.6:
        cyl(0.07, 8.8, (x, -1.6, 4.4), bars, seg=10)
        x += 0.55
    for z in (0.3, 4.4, 8.6):
        box((16, 0.18, 0.18), (0, -1.6, z), bars, bevel=0.02)
    for i, xx in enumerate((-5, 0, 5)):
        box((0.9, 0.1, 0.9), (xx, -1.75, 7.8), mat("#f2f2f2", 0.5, key="numplate"), bevel=0.03)
        text(str(i + 1), (xx, -1.82, 7.8), 0.6, "#111111")
    if shot.get("sign_text"):
        box((5, 0.15, 1.6), (2, 6.25, 5.5), mat("#1f1f22", 0.7, key="board"), bevel=0.04)
        text(shot["sign_text"], (2, 6.1, 5.5), 0.75, "#ffffff", max_w=4.6)


def set_meadow(shot, rng):
    world("sky")
    sun(3.3, (48, 6, 40))
    box((400, 400, 0.2), (0, 100, -0.1), mat("#6cbf4a", 0.95, key="grass"), bevel=0)
    hills(120, "#5c9a48")
    for _ in range(14):
        tree((rng.uniform(-40, 40), rng.uniform(15, 80)))
    clouds(rng, 200, 9)
    if shot.get("sign_text"):
        cyl(0.15, 3, (6, 6, 1.5), mat("#6b4a2b", 0.8))
        box((3.5, 0.2, 1.5), (6, 5.9, 3.2), mat("#f4f1ea", 0.6), bevel=0.04)
        text(shot["sign_text"], (6, 5.75, 3.2), 0.5, "#111111", max_w=3.2)


def set_sign(shot, rng):
    """Großes Schild/Tafel an Ziegelwand – für Pointen wie '+2 JAHRE'."""
    world("indoor")
    box((20, 0.3, 14), (0, 4, 5), brick_mat(scale=2.4), bevel=0)
    box((20, 12, 0.2), (0, 0, -0.1), mat("#bdbab3", 0.85, key="concrete"), bevel=0)
    area((0, -6, 9), 1500, 9, (40, 0, 0))
    box((7.5, 0.25, 3.6), (0, 3.75, 5.6), mat("#1e2421", 0.85, key="chalkboard"), bevel=0.06)
    box((7.9, 0.2, 4.0), (0, 3.8, 5.6), stripe_mat("#8a5a30", "#6e4422", 3, key="frame"), bevel=0.04)
    text(shot.get("sign_text") or "!!!", (0, 3.55, 5.6), 1.4, "#ffffff", max_w=6.8)


SETS = {"street": set_street, "facade": set_facade, "room": set_room, "jail": set_jail,
        "meadow": set_meadow, "sign": set_sign}


# ---------------------------------------------------------------- Kamera & Render
def camera(shot, chars_cfg):
    sc = bpy.context.scene
    cd = bpy.data.cameras.new("cam")
    cam = link(bpy.data.objects.new("cam", cd))
    sc.camera = cam
    kind = shot.get("shot", "medium")
    st = shot.get("set", "street")
    rng = random.Random(shot.get("seed", 1))
    focus = next((c for c in chars_cfg if c["id"] == shot.get("focus")), chars_cfg[0] if chars_cfg else None)
    side = rng.uniform(-1, 1)
    if not chars_cfg or kind == "establishing":
        presets = {"street": ((side * 2, -14, 3.2), (0, 30, 4.5), 24), "facade": ((side * 3, -12, 3.0), (0, 8, 5.5), 26),
                   "room": ((side * 2, -7.5, 4.2), (0, 5, 3.5), 22), "jail": ((side * 2, -8, 4), (0, 3, 3.5), 24),
                   "meadow": ((side * 3, -12, 2.4), (0, 15, 3), 24), "sign": ((0, -6.5, 5.6), (0, 3.6, 5.6), 40)}
        pos, tgt, lens = presets.get(st, presets["street"])
    elif kind == "close":
        hx_ = focus["x"]
        hz = 4.66 + (0.0 if focus.get("pose") != "hold_sign" else 0.0)
        pos, tgt, lens = (hx_ + side * 0.6, -3.4 + focus.get("y", 0), hz + 0.12), (hx_, focus.get("y", 0), hz - 0.08), 50
        cd.dof.use_dof = True
        cd.dof.focus_distance = 3.4
        cd.dof.aperture_fstop = 2.2
    elif kind == "medium":
        cx = sum(c["x"] for c in chars_cfg) / len(chars_cfg) if len(chars_cfg) > 1 else focus["x"]
        pos, tgt, lens = (cx + side * 1.2, -7.2, 4.1), (cx, 0, 3.9 if focus.get("pose") != "hold_sign" else 4.8), 35
        cd.dof.use_dof = True
        cd.dof.focus_distance = 7.2
        cd.dof.aperture_fstop = 4.0
    else:  # wide
        cx = sum(c["x"] for c in chars_cfg) / len(chars_cfg)
        pos, tgt, lens = (cx + side * 2.5, -13, 3.4), (cx, 0, 2.8), 24
        if st in ("room", "jail", "sign"):  # Innenräume: Kamera bleibt im Raum
            pos, tgt, lens = (cx + side * 1.5, -5.8, 4.4), (cx, 2, 3.0), 16
    if kind == "medium" and len(chars_cfg) > 1:
        lens = 28
    cam.location = pos
    d = Vector(tgt) - Vector(pos)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cd.lens = lens
    cd.sensor_fit = "AUTO"
    cd.clip_end = 1000


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.lights, bpy.data.cameras, bpy.data.worlds):
        for b in list(coll):
            if b.users == 0:
                coll.remove(b)


def setup_render():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = int(R.get("samples", 28))
    try:
        sc.cycles.use_adaptive_sampling = True
        sc.cycles.adaptive_threshold = 0.05
    except Exception:
        pass
    sc.cycles.max_bounces = 4
    sc.cycles.diffuse_bounces = 2
    sc.cycles.glossy_bounces = 1
    sc.cycles.transparent_max_bounces = 6
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    sc.render.resolution_x = int(R.get("width", 720))
    sc.render.resolution_y = int(R.get("height", 1280))
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        try:
            sc.view_settings.view_transform = "Filmic"
            sc.view_settings.look = "Medium High Contrast"
        except Exception:
            pass
    sc.render.threads_mode = "AUTO"


def layout_chars(shot):
    cl = [dict(c) for c in shot.get("characters", []) if c.get("id") in DATA["characters"]][:4]
    n = len(cl)
    spots = {1: [0], 2: [-1.7, 1.7], 3: [-3.2, 0, 3.2], 4: [-4.6, -1.55, 1.55, 4.6]}.get(n, [])
    named = {"left": -1.9, "center": 0, "right": 1.9, "far_left": -3.4, "far_right": 3.4}
    for i, c in enumerate(cl):
        c["x"] = spots[i] if n > 1 else named.get(c.get("position", "center"), 0)
        if n == 2:  # leicht zueinander drehen
            c.setdefault("turn", 18 if i == 0 else -18)
        if shot.get("set") == "jail" and c.get("behind_bars", True):
            c["y"] = 1.2
        if shot.get("set") == "room" and shot.get("room_type") == "bakery" and c.get("behind_counter"):
            c["y"] = 4.0
    return cl


def main():
    global FONT
    if DATA.get("font") and os.path.exists(DATA["font"]):
        FONT = bpy.data.fonts.load(DATA["font"])
    setup_render()
    os.makedirs(OUT, exist_ok=True)
    for i, shot in enumerate(DATA["shots"]):
        if ONLY is not None and i not in ONLY:
            continue
        out = os.path.join(OUT, f"shot_{i:02d}.png")
        if os.path.exists(out):
            continue
        clear()
        rng = random.Random(f"{shot.get('set')}-{shot.get('sign_text')}-{shot.get('room_type')}")
        SETS.get(shot.get("set", "street"), set_street)(shot, rng)
        cl = layout_chars(shot)
        for c in cl:
            character(c["id"], DATA["characters"][c["id"]], c, DATA.get("faces", {}))
        camera(shot, cl)
        bpy.context.scene.render.filepath = out
        bpy.ops.render.render(write_still=True)
        print(f"RENDERED {i} {out}", flush=True)


main()
