"""Rendert ein paar Probe-Einstellungen mit Blender (für den Vorschau-Workflow)."""
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from faces import face_textures
ROOT = Path(__file__).resolve().parent.parent
bible = json.loads((ROOT / "series" / "stadt_der_regeln.json").read_text())
specs = {c["id"]: c["spec"] for c in bible["characters"]}
shots = [
    {"set": "street", "shot": "close", "focus": "kai", "characters": [{"id": "kai", "pose": "wave", "expression": "happy"}]},
    {"set": "street", "shot": "establishing", "characters": []},
    {"set": "facade", "shot": "wide", "sign_text": "RATHAUS", "characters": [{"id": "buergermeister", "pose": "hands_hips", "expression": "smirk"}]},
    {"set": "room", "room_type": "bakery", "shot": "medium", "focus": "kai", "characters": [
        {"id": "kai", "pose": "point", "expression": "shocked"}, {"id": "baecker", "pose": "carry", "expression": "smile", "prop": "bread"}]},
    {"set": "jail", "shot": "close", "focus": "kai", "characters": [{"id": "kai", "pose": "idle", "expression": "worried"}]},
    {"set": "sign", "shot": "establishing", "sign_text": "+2 JAHRE", "characters": []},
    {"set": "meadow", "shot": "medium", "focus": "mo", "characters": [{"id": "mo", "pose": "hold_sign", "expression": "happy", "sign_text": "NEUE REGEL: SCHERE ZÄHLT NICHT"}]},
    {"set": "street", "shot": "medium", "focus": "polizist", "characters": [
        {"id": "polizist", "pose": "point", "expression": "angry"}, {"id": "lena", "pose": "shrug", "expression": "shocked"}]},
]
need = {(c["id"], c.get("expression", "neutral")) for s in shots for c in s["characters"]} | {(k, "neutral") for k in specs}
out = ROOT / "preview"
out.mkdir(exist_ok=True)
faces = face_textures(specs, need, out / "faces")
data = {"render": {"width": 720, "height": 1280, "samples": 32}, "characters": specs, "faces": faces,
        "font": str((ROOT / "assets/fonts/Montserrat.ttf").resolve()), "shots": [dict(s, seed=i) for i, s in enumerate(shots)]}
(out / "shots.json").write_text(json.dumps(data, ensure_ascii=False))
subprocess.run(["blender", "-b", "-noaudio", "-P", str(ROOT / "src/blender/render_shots.py"), "--", str(out / "shots.json"), str(out / "img")], check=True)
