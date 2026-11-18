"""Schneidet Szenen, Stimme, Musik und Wort-Untertitel zu einem 9:16-Video."""
import subprocess
from pathlib import Path


def ff(*args):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *map(str, args)]
    subprocess.run(cmd, check=True)


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def scene_timings(narrations: list, words: list, audio_len: float) -> list:
    """Start/Ende jeder Szene anhand der Wort-Zeitstempel bestimmen."""
    offsets, pos = [], 0
    for n in narrations:
        offsets.append(pos)
        pos += len(n) + 1  # +1 für das Leerzeichen beim Zusammenfügen
    starts = []
    for i, off in enumerate(offsets):
        if i == 0:
            starts.append(0.0)
            continue
        w = next((w for w in words if w["char"] >= off), None)
        starts.append(w["start"] if w else audio_len)
    end = audio_len + 0.5
    return [(s, (starts[i + 1] if i + 1 < len(starts) else end)) for i, s in enumerate(starts)]


def render_segment(cfg, src: Path, dur: float, idx: int, dest: Path):
    W, H, fps = cfg["render"]["width"], cfg["render"]["height"], cfg["render"]["fps"]
    dur = max(dur, 0.4)
    fit = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    if src.suffix.lower() in (".mp4", ".mov", ".webm"):
        ff("-stream_loop", -1, "-i", src, "-t", f"{dur:.3f}", "-vf", f"{fit},fps={fps}",
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", 20, "-pix_fmt", "yuv420p", dest)
    else:
        frames = int(dur * fps) + 1
        step = 0.07 / frames
        z = f"min(1+{step}*on,1.07)" if idx % 2 == 0 else f"max(1.07-{step}*on,1.0)"
        vf = (f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},"
              f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={fps},setsar=1")
        ff("-loop", 1, "-i", src, "-t", f"{dur:.3f}", "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", 20, "-pix_fmt", "yuv420p", dest)


def _ts(t: float) -> str:
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def write_ass(cfg, words: list, part: int, total: int, dest: Path, end_card=None):
    r = cfg["render"]
    W, H = r["width"], r["height"]
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{r['font']},{r['font_size']},&H{r.get('caption_color', '0021E1FF')},&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,6,2,5,40,40,0,1
Style: Part,{r['font']},{int(r['font_size']*0.8)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,2,0,3,18,0,8,40,40,170,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    label = "FINALE" if part == total else f"PART {part}"
    lines.append(f"Dialogue: 1,{_ts(0)},{_ts(2.8)},Part,,0,0,0,,{{\\3c&H2020E0&\\fad(150,250)}}{label}")
    y = int(H * 0.58)
    for i, w in enumerate(words):
        end = words[i + 1]["start"] if i + 1 < len(words) else w["end"] + 0.4
        txt = w["word"].replace("{", "(").replace("}", ")").replace("\\", "")
        pop = "{\\pos(%d,%d)\\fscx75\\fscy75\\t(0,90,\\fscx100\\fscy100)}" % (W // 2, y)
        lines.append(f"Dialogue: 0,{_ts(w['start'])},{_ts(end)},Word,,0,0,0,,{pop}{txt}")
    if end_card and end_card[1] - end_card[0] > 0.8:
        txt = (cfg.get("end_text_final", "ENDE") if part == total
               else cfg.get("end_text", "TEIL {n} FOLGT…").format(n=part + 1))
        lines.append(f"Dialogue: 2,{_ts(end_card[0])},{_ts(end_card[1])},Part,,0,0,0,,"
                     f"{{\\an5\\pos({W // 2},{int(H * 0.42)})\\fscx130\\fscy130\\3c&H2020E0&\\fad(250,0)}}{txt}")
    dest.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def assemble(cfg, segments: list, voice: Path, words: list, part: int, total: int,
             work: Path, out: Path, root: Path, end_card=None):
    """segments = [(quelle_bild_oder_clip, dauer), ...]"""
    seg_files = []
    for i, (src, dur) in enumerate(segments):
        if Path(src).suffix == ".mp4" and Path(src).name.startswith("scene_"):  # schon fertig gerendert
            seg_files.append(Path(src))
            continue
        p = work / f"seg_{i:02d}.mp4"
        render_segment(cfg, Path(src), dur, i, p)
        seg_files.append(p)
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in seg_files))
    raw = work / "video_raw.mp4"
    ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", raw)

    ass = work / "captions.ass"
    write_ass(cfg, words, part, total, ass, end_card)
    ass_arg = str(ass.resolve()).replace("\\", "/").replace(":", "\\:")
    fonts = str((root / "assets" / "fonts").resolve()).replace(":", "\\:")
    ass_arg = f"{ass_arg}':fontsdir='{fonts}"

    total_len = probe_duration(raw)
    music = cfg["render"].get("music")
    music = (root / music) if music else None
    vol = cfg["render"].get("music_volume", 0.12)
    if music and music.exists():
        ff("-i", raw, "-i", voice, "-stream_loop", -1, "-i", music,
           "-filter_complex",
           f"[0:v]ass='{ass_arg}'[v];[2:a]volume={vol}[m];[1:a]apad[vo];"
           f"[vo][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
           "-map", "[v]", "-map", "[a]", "-t", f"{total_len:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", 20, "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out)
    else:
        ff("-i", raw, "-i", voice, "-vf", f"ass='{ass_arg}'", "-af", "apad", "-map", "0:v", "-map", "1:a", "-t", f"{total_len:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", 20, "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out)
    return out
