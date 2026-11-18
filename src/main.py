"""AI Story Bot – erstellt den nächsten Part einer Story-Serie und veröffentlicht ihn.

  python src/main.py run        # nächsten Part erstellen + hochladen (macht die Cloud täglich)
  python src/main.py generate   # nur erstellen
  python src/main.py publish    # zuletzt erstellten Part hochladen
  python src/main.py status     # Stand der Serien
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import ROOT, load_config, read_json, write_json  # noqa: E402

STATE = ROOT / "series" / "state.json"
OUT = ROOT / "output"


def slugify(s: str) -> str:
    s = s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40]


def load_state() -> dict:
    st = read_json(STATE)
    if st is None:  # erste Serie = erste JSON-Datei im series-Ordner
        first = sorted(p.stem for p in (ROOT / "series").glob("*.json") if p.name != "state.json")
        st = {"active": first[0] if first else None, "series": {}}
    return st


def ensure_series(cfg, st) -> str:
    from script_gen import generate_series_bible
    slug = st.get("active")
    done = slug and len(st["series"].get(slug, {}).get("parts", [])) >= cfg["parts_per_series"]
    if not slug or done:
        titles = [read_json(ROOT / "series" / f"{s}.json", {}).get("title", s) for s in st["series"]]
        print("Neue Serie wird erfunden …")
        bible = generate_series_bible(cfg, titles)
        slug = slugify(bible["title"])
        write_json(ROOT / "series" / f"{slug}.json", bible)
        st["active"] = slug
        print(f"  -> {bible['title']}")
    st["series"].setdefault(slug, {"parts": []})
    write_json(STATE, st)
    return slug


def render_3d(cfg, bible, scenes, work: Path) -> list:
    """Baut die Einstellungen in Blender und gibt die Bildpfade zurück."""
    import subprocess

    from faces import face_textures
    specs = {c["id"]: c["spec"] for c in bible["characters"]}
    shots = []
    for i, sc in enumerate(scenes):
        sh = {k: sc.get(k) for k in ("set", "sign_text", "room_type", "shot", "focus")}
        sh["characters"] = [c for c in (sc.get("characters") or []) if c.get("id") in specs]
        sh["seed"] = i
        if not sh["characters"] and sh.get("shot") != "establishing":
            sh["shot"] = "establishing"
        shots.append(sh)
    need = {(c["id"], c.get("expression") or "neutral") for s in shots for c in s["characters"]}
    need |= {(k, "neutral") for k in specs}
    faces = face_textures(specs, need, work / "faces")
    r = cfg["render"]
    data = {"render": {"width": r.get("render_width", 720), "height": r.get("render_height", 1280),
                       "samples": r.get("samples", 32)},
            "characters": specs, "faces": faces, "font": str((ROOT / "assets/fonts/Poppins-Bold.ttf").resolve()),
            "shots": shots}
    write_json(work / "shots.json", data)
    out = work / "img"
    subprocess.run([cfg["render"].get("blender", "blender"), "-b", "-noaudio", "-P",
                    str(ROOT / "src/blender/render_shots.py"), "--", str(work / "shots.json"), str(out)],
                   check=True, stdout=subprocess.DEVNULL if not cfg["render"].get("verbose") else None)
    imgs = [out / f"shot_{i:02d}.png" for i in range(len(shots))]
    missing = [str(p) for p in imgs if not p.exists()]
    if missing:
        raise RuntimeError(f"Blender hat {len(missing)} Bilder nicht erzeugt")
    return imgs


def generate(cfg) -> dict:
    from assemble import assemble, probe_duration, scene_timings
    from script_gen import generate_script
    from tts import synthesize

    st = load_state()
    slug = ensure_series(cfg, st)
    bible = read_json(ROOT / "series" / f"{slug}.json")
    ser = st["series"][slug]
    part = len(ser["parts"]) + 1
    total = cfg["parts_per_series"]
    work = OUT / slug / f"part_{part:02d}"
    work.mkdir(parents=True, exist_ok=True)
    print(f"== {bible['title']} – Teil {part}/{total} ==", flush=True)

    script = read_json(work / "script.json")
    if not script:
        print("Drehbuch …", flush=True)
        script = generate_script(cfg, bible, [p["summary"] for p in ser["parts"]], part)
        # Zu kurzes Drehbuch? Einmal neu schreiben lassen (~2,6 gesprochene Wörter pro Sekunde)
        n_words = len(" ".join(s["narration"] for s in script["scenes"]).split())
        if n_words < cfg["min_seconds"] * 2.4:
            print(f"  Drehbuch zu kurz ({n_words} Wörter) – wird verlängert …", flush=True)
            longer = dict(cfg, target_seconds=cfg["target_seconds"] + 15)
            retry_script = generate_script(longer, bible, [p["summary"] for p in ser["parts"]], part)
            if len(" ".join(s["narration"] for s in retry_script["scenes"]).split()) > n_words:
                script = retry_script
        write_json(work / "script.json", script)
    scenes = [s for s in script["scenes"] if s.get("narration", "").strip()]
    print(f"  {len(scenes)} Szenen", flush=True)

    print("Stimme …", flush=True)
    voice = work / "voice.mp3"
    words = read_json(work / "words.json")
    if not words or not voice.exists():
        words = synthesize(cfg, " ".join(s["narration"].strip() for s in scenes), voice)
        write_json(work / "words.json", words)
    narr = [s["narration"].strip() for s in scenes]
    times = scene_timings(narr, words, probe_duration(voice))
    speech_end = times[-1][1]
    missing = cfg["min_seconds"] - speech_end
    if missing > 0:  # Mindestlänge garantieren: Endkarte
        print(f"  +{missing:.1f}s Endkarte für Mindestlänge", flush=True)
        times[-1] = (times[-1][0], times[-1][1] + missing)

    print("3D-Szenen rendern …", flush=True)
    imgs = render_3d(cfg, bible, scenes, work)

    print("Schnitt …", flush=True)
    segments = [(imgs[i], e - s) for i, (s, e) in enumerate(times)]
    final = assemble(cfg, segments, voice, words, part, total, work, work / "final.mp4", ROOT,
                     end_card=(speech_end - 0.5, times[-1][1]))

    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in script.get("hashtags", []))
    entry = {"part": part, "dir": str(work.relative_to(ROOT)), "summary": script["summary"],
             "caption": f"{script['caption']}\n\n{tags} {cfg['publish']['ai_label_hashtag']}".strip(),
             "published": {}, "attempts": 0}
    ser["parts"].append(entry)
    write_json(STATE, st)
    print(f"Fertig: {final}", flush=True)
    return entry


def publish(cfg, entry: dict | None = None):
    import publish_instagram
    import publish_tiktok
    st = load_state()
    ser = st["series"].get(st.get("active"), {})
    if not ser.get("parts"):
        raise SystemExit("Noch kein Part erstellt.")
    # Eintrag aus dem frisch geladenen Status nehmen, damit Änderungen gespeichert werden
    entry = ser["parts"][-1] if entry is None else next(p for p in ser["parts"] if p["part"] == entry["part"])
    video = ROOT / entry["dir"] / "final.mp4"
    if not video.exists():
        print("Video-Datei nicht mehr vorhanden – übersprungen.")
        return
    entry["attempts"] = entry.get("attempts", 0) + 1
    for name, enabled, fn in (("tiktok", cfg["publish"]["tiktok"], publish_tiktok.publish),
                              ("instagram", cfg["publish"]["instagram"], publish_instagram.publish)):
        if not enabled or entry["published"].get(name):
            continue
        try:
            print(f"Hochladen: {name} …")
            entry["published"][name] = fn(cfg, video, entry["caption"])
            print(f"  ✔ {name}: {entry['published'][name]}")
        except Exception as e:  # noqa: BLE001 – eine Plattform soll die andere nicht blockieren
            print(f"  ✘ {name}: {e}")
        write_json(STATE, st)


def main():
    cfg = load_config()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "generate":
        generate(cfg)
    elif cmd == "publish":
        publish(cfg)
    elif cmd == "run":
        entry = generate(cfg)
        publish(cfg, entry)
        st = load_state()
        ser = st["series"][st["active"]]
        wanted = [p for p in ("tiktok", "instagram") if cfg["publish"][p]]
        if wanted and not ser["parts"][-1]["published"]:
            # Nirgends online -> Part nicht zählen, damit die Story nächstes Mal lückenlos weitergeht
            ser["parts"].pop()
            write_json(STATE, st)
            raise SystemExit("Upload überall fehlgeschlagen – dieser Part wird beim nächsten Lauf neu erstellt.")
    elif cmd == "status":
        st = load_state()
        for slug, s in st["series"].items():
            mark = "▶" if slug == st["active"] else " "
            print(f"{mark} {slug}: {len(s['parts'])}/{cfg['parts_per_series']} Parts")
            for p in s["parts"]:
                print(f"     Part {p['part']}: {', '.join(p['published']) or 'nicht hochgeladen'}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
