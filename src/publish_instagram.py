"""Instagram Reels über die Instagram API (Instagram Login), mit direktem Datei-Upload –
kein eigener Webserver nötig."""
import time
from pathlib import Path

import requests

from common import env, load_tokens, save_tokens


def access_token() -> str:
    """Long-lived Token (60 Tage) – wird alle ~30 Tage automatisch verlängert."""
    all_t = load_tokens()
    ig = all_t.get("instagram") or {"access_token": env("IG_ACCESS_TOKEN"), "refreshed_at": 0}
    if time.time() - ig["refreshed_at"] > 30 * 86400:
        r = requests.get("https://graph.instagram.com/refresh_access_token", params={
            "grant_type": "ig_refresh_token", "access_token": ig["access_token"]}, timeout=60)
        if r.ok:
            ig = {"access_token": r.json()["access_token"], "refreshed_at": time.time()}
            all_t["instagram"] = ig
            save_tokens(all_t)
    return ig["access_token"]


def publish(cfg: dict, video: Path, caption: str) -> str:
    v = cfg["publish"]["instagram_api_version"]
    base = f"https://graph.instagram.com/{v}"
    tok, uid = access_token(), env("IG_USER_ID")

    c = requests.post(f"{base}/{uid}/media", timeout=60, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200],
        "share_to_feed": "true", "access_token": tok}).json()
    if "id" not in c:
        raise RuntimeError(f"Instagram Container: {c}")
    cid = c["id"]

    data = video.read_bytes()
    up = requests.post(f"https://rupload.facebook.com/ig-api-upload/{v}/{cid}", data=data, timeout=600,
                       headers={"Authorization": f"OAuth {tok}", "offset": "0",
                                "file_size": str(len(data))})
    if not up.ok:
        raise RuntimeError(f"Instagram Upload: {up.text}")

    for _ in range(60):
        st = requests.get(f"{base}/{cid}", params={"fields": "status_code,status",
                                                   "access_token": tok}, timeout=60).json()
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram Verarbeitung: {st}")
        time.sleep(10)

    pub = requests.post(f"{base}/{uid}/media_publish", timeout=60,
                        data={"creation_id": cid, "access_token": tok}).json()
    if "id" not in pub:
        raise RuntimeError(f"Instagram Publish: {pub}")
    return pub["id"]
