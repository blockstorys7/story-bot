import base64
import json
import mimetypes
import os
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise SystemExit(f"Fehlende Umgebungsvariable {name} (siehe .env.example)")
    return val


def read_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dest


def retry(fn, tries=3, wait=5):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  ! Fehler ({e}), neuer Versuch in {wait}s …")
            time.sleep(wait)
            wait *= 2


# --- Tokens: lokal in tokens.json, in der Cloud (GitHub Actions) als Secret TOKENS_JSON ---
TOKENS_FILE = ROOT / "tokens.json"


def load_tokens() -> dict:
    if os.environ.get("TOKENS_JSON", "").strip():
        return json.loads(os.environ["TOKENS_JSON"])
    return read_json(TOKENS_FILE, {})


def save_tokens(tokens: dict) -> None:
    os.environ["TOKENS_JSON"] = json.dumps(tokens)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        import subprocess
        # braucht GH_TOKEN (Fine-grained Token mit "Secrets: Read and write" für dieses Repo)
        r = subprocess.run(["gh", "secret", "set", "TOKENS_JSON", "--body", json.dumps(tokens)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("  ! Konnte Secret TOKENS_JSON nicht speichern:", r.stderr.strip())
    else:
        write_json(TOKENS_FILE, tokens)
