"""TikTok Content Posting API (Direct Post).

Einmalig: `python src/publish_tiktok.py auth` -> Login-Link öffnen, danach die
Weiterleitungs-URL einfügen. Tokens landen in tokens.json und werden automatisch erneuert.
"""
import math
import secrets
import sys
import time
import urllib.parse
from pathlib import Path

import requests

from common import env, load_tokens, save_tokens
API = "https://open.tiktokapis.com/v2"


def _save(tok: dict):
    all_t = load_tokens()
    tok["expires_at"] = time.time() + tok.get("expires_in", 86400) - 300
    all_t["tiktok"] = tok
    save_tokens(all_t)


def auth_url(state="storybot") -> str:
    return "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": env("TIKTOK_CLIENT_KEY"), "response_type": "code",
        "scope": "user.info.basic,video.publish", "redirect_uri": env("TIKTOK_REDIRECT_URI"),
        "state": state})


def exchange(back_url: str):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(back_url.strip()).query)
    if "code" not in q:
        raise SystemExit("In der URL ist kein ?code=… – bitte die komplette Weiterleitungs-URL kopieren.")
    r = requests.post(f"{API}/oauth/token/", data={
        "client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
        "code": q["code"][0], "grant_type": "authorization_code",
        "redirect_uri": env("TIKTOK_REDIRECT_URI")}, timeout=60)
    r.raise_for_status()
    if "access_token" not in r.json():
        raise SystemExit(f"TikTok-Fehler: {r.json()}")
    _save(r.json())
    print("TikTok verbunden ✔")


def auth_cli():
    state = secrets.token_urlsafe(12)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": env("TIKTOK_CLIENT_KEY"), "response_type": "code",
        "scope": "user.info.basic,video.publish", "redirect_uri": env("TIKTOK_REDIRECT_URI"),
        "state": state})
    print("1) Diesen Link öffnen und mit deinem TikTok-Konto erlauben:\n\n" + url + "\n")
    back = input("2) Die komplette URL, auf die du weitergeleitet wurdest, hier einfügen: ").strip()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)
    if q.get("state", [""])[0] != state:
        raise SystemExit("State stimmt nicht überein – bitte erneut versuchen.")
    r = requests.post(f"{API}/oauth/token/", data={
        "client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
        "code": q["code"][0], "grant_type": "authorization_code",
        "redirect_uri": env("TIKTOK_REDIRECT_URI")}, timeout=60)
    r.raise_for_status()
    _save(r.json())
    print("TikTok verbunden ✔")


def access_token() -> str:
    tok = load_tokens().get("tiktok")
    if not tok:
        raise SystemExit("TikTok nicht verbunden: python src/publish_tiktok.py auth")
    if time.time() > tok["expires_at"]:
        r = requests.post(f"{API}/oauth/token/", data={
            "client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
            "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}, timeout=60)
        r.raise_for_status()
        tok = r.json()
        _save(tok)
    return tok["access_token"]


def publish(cfg: dict, video: Path, title: str) -> str:
    h = {"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json; charset=UTF-8"}
    info = requests.post(f"{API}/post/publish/creator_info/query/", headers=h, timeout=60).json()["data"]
    privacy = cfg["publish"]["tiktok_privacy"]
    if privacy not in info.get("privacy_level_options", []):
        privacy = info["privacy_level_options"][0]
        print(f"  TikTok: Sichtbarkeit -> {privacy} (App evtl. noch nicht auditiert)")

    size = video.stat().st_size
    chunk = size if size <= 64 * 1024 * 1024 else 10 * 1024 * 1024
    count = 1 if chunk == size else math.floor(size / chunk)
    init = requests.post(f"{API}/post/publish/video/init/", headers=h, timeout=60, json={
        "post_info": {"title": title[:2200], "privacy_level": privacy,
                      "disable_duet": False, "disable_stitch": False, "disable_comment": False,
                      "is_aigc": True},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                        "chunk_size": chunk, "total_chunk_count": count}}).json()
    if init.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init: {init['error']}")
    up_url, pid = init["data"]["upload_url"], init["data"]["publish_id"]

    with open(video, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1  # letzter Chunk nimmt den Rest
            f.seek(start)
            body = f.read(end - start + 1)
            r = requests.put(up_url, data=body, timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(body)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            r.raise_for_status()

    for _ in range(60):
        s = requests.post(f"{API}/post/publish/status/fetch/", headers=h,
                          json={"publish_id": pid}, timeout=60).json()["data"]
        if s["status"] == "PUBLISH_COMPLETE":
            return pid
        if s["status"] == "FAILED":
            raise RuntimeError(f"TikTok: {s.get('fail_reason')}")
        time.sleep(5)
    return pid  # läuft noch – TikTok veröffentlicht trotzdem


if __name__ == "__main__":
    if sys.argv[1:] == ["auth"]:
        auth_cli()
    elif sys.argv[1:2] == ["link"]:      # Cloud: Link ausgeben
        print(auth_url())
    elif sys.argv[1:2] == ["exchange"]:  # Cloud: Weiterleitungs-URL eintauschen
        exchange(sys.argv[2])
