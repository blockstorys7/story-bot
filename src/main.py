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


def generate(cfg) -> dict:
    from assemble import assemble, probe_duration, scene_timings
    from compose import render_scene
    from media_gen import scene_background, scene_clip
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
    print(f"== {bible['title']} – Part {part}/{total} ==")
    specs = {c["id"]: c["spec"] for c in bible["characters"]}

    script = read_json(work / "script.json")
    if not script:
        print("Drehbuch …")
        script = generate_script(cfg, bible, [p["summary"] for p in ser["parts"]], part)
        write_json(work / "script.json", script)
    scenes = script["scenes"]

    print(f"Hintergründe ({len(scenes)} Szenen) …")
    bgs = [scene_background(cfg, bible, sc, work / f"bg_{i:02d}.png") for i, sc in enumerate(scenes)]

    print("Stimme …")
    voice = work / "voice.mp3"
    words = read_json(work / "words.json")
    if not words or not voice.exists():
        words = synthesize(cfg, " ".join(s["narration"] for s in scenes), voice)
        write_json(work / "words.json", words)
    times = scene_timings([s["narration"] for s in scenes], words, probe_duration(voice))

    print("Szenen animieren …")
    animate = set()
    if cfg["video"]["enabled"]:
        animate = {i for i, sc in enumerate(scenes) if sc.get("animate")}
        animate = set(sorted(animate)[: cfg["video"]["max_clips_per_part"]])
    segments = []
    for i, (sc, (s, e)) in enumerate(zip(scenes, times)):
        if i in animate:
            still = render_scene(cfg, specs, sc, bgs[i], s, e - s, words, i, None, still=work / f"still_{i:02d}.png")
            segments.append((scene_clip(cfg, still, sc, work / f"clip_{i:02d}.mp4"), e - s))
        else:
            dest = work / f"scene_{i:02d}.mp4"
            render_scene(cfg, specs, sc, bgs[i], s, e - s, words, i, dest)
            segments.append((dest, e - s))

    print("Schnitt …")
    final = assemble(cfg, segments, voice, words, part, total, work, work / "final.mp4", ROOT)

    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in script.get("hashtags", []))
    entry = {"part": part, "dir": str(work.relative_to(ROOT)), "summary": script["summary"],
             "caption": f"{script['caption']}\n\n{tags} {cfg['publish']['ai_label_hashtag']}".strip(),
             "published": {}, "attempts": 0}
    ser["parts"].append(entry)
    write_json(STATE, st)
    print(f"Fertig: {final}")
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
