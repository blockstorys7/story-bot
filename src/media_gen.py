"""Bilder & Clips über fal.ai (ein Key für viele Modelle)."""
import os
import time
import urllib.parse
import zlib
from pathlib import Path

import requests

from common import data_uri, download, env, retry


def fal_run(model: str, payload: dict, poll=3, timeout=900) -> dict:
    h = {"Authorization": f"Key {env('FAL_KEY')}", "Content-Type": "application/json"}
    r = requests.post(f"https://queue.fal.run/{model}", json=payload, headers=h, timeout=120)
    r.raise_for_status()
    job = r.json()
    t0 = time.time()
    while True:
        s = requests.get(job["status_url"], headers=h, timeout=60).json()
        if s.get("status") == "COMPLETED":
            break
        if s.get("status") in ("FAILED", "ERROR") or time.time() - t0 > timeout:
            raise RuntimeError(f"fal-Job fehlgeschlagen: {s}")
        time.sleep(poll)
    res = requests.get(job["response_url"], headers=h, timeout=120)
    res.raise_for_status()
    return res.json()


def pollinations_image(cfg: dict, prompt: str, dest: Path, seed: int) -> Path:
    """Gratis-Bilder über Pollinations. Mit kostenlosem Key (enter.pollinations.ai):
    kein Wasserzeichen, höheres Limit."""
    W, H = cfg["render"]["width"], cfg["render"]["height"]
    url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:1500])
    params = {"width": W, "height": H, "model": cfg["image"].get("free_model", "flux"),
              "seed": seed, "nologo": "true", "enhance": "false"}
    headers = {}
    if os.environ.get("POLLINATIONS_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['POLLINATIONS_KEY']}"

    def get():
        r = requests.get(url, params=params, headers=headers, timeout=300)
        r.raise_for_status()
        if not r.headers.get("content-type", "").startswith("image"):
            raise RuntimeError("keine Bilddatei erhalten")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return dest
    out = retry(get, tries=5, wait=16)
    if not headers:
        time.sleep(16)  # anonymes Limit: ca. 1 Bild pro 15 s
    return out


def scene_background(cfg: dict, bible: dict, scene: dict, dest: Path) -> Path:
    """Hintergrund OHNE Figuren. Gleicher Ort = gleicher Seed -> gleicher Look."""
    if dest.exists():
        return dest
    locs = bible.get("locations", [])
    li = scene.get("location")
    loc = locs[li] if isinstance(li, int) and 0 <= li < len(locs) else ""
    prompt = (f"{scene.get('background', '')}. Setting: {loc}. Empty environment, no people, "
              f"no characters, no figures, no animals. {cfg['background_style']}")
    seed = zlib.crc32(f"{bible.get('title')}-{li}".encode()) % 100000
    if cfg["image"].get("provider") == "pollinations":
        return pollinations_image(cfg, prompt, dest, seed)
    out = retry(lambda: fal_run(cfg["image"]["model"], {
        "prompt": prompt, "num_images": 1, "aspect_ratio": "9:16", "seed": seed}))
    return download(out["images"][0]["url"], dest)


def scene_clip(cfg: dict, still: Path, scene: dict, dest: Path) -> Path:
    """Upgrade: animiert ein fertiges Szenenbild (mit unseren Figuren) per Kling."""
    if dest.exists():
        return dest
    out = retry(lambda: fal_run(cfg["video"]["model"], {
        "prompt": f"{scene.get('background', '')}, the blocky toy characters move naturally, "
                  "keep character design exactly the same, smooth camera",
        "image_url": data_uri(still),
        "duration": cfg["video"]["clip_seconds"],
        "negative_prompt": "blur, distort, morphing faces, low quality, text, watermark"}))
    return download(out["video"]["url"], dest)
