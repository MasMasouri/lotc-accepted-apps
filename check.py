"""
LotC Accepted Applications -> Discord webhook

Run on a schedule (GitHub Actions). Each run reads the accepted list on
https://www.lordofthecraft.net/apply/new/accepted/, posts any application it
hasn't posted before to a Discord channel via webhook, and saves the IDs it has
seen to seen_apps.json.

Environment:
  DISCORD_WEBHOOK_URL  (required) the channel webhook link
  PAGES_TO_SCAN        (optional, default 2) listing pages to read, 25 apps each
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
PAGES_TO_SCAN = int(os.getenv("PAGES_TO_SCAN", "2"))
STATE_FILE = Path(os.getenv("STATE_FILE", "seen_apps.json"))

BASE = "https://www.lordofthecraft.net"
LIST_URL = BASE + "/apply/new/accepted/"
PAGE_URL = BASE + "/apply/new/accepted/page/{n}/"
APP_LINK_RE = re.compile(r"/apply/new/accepted/([^/?#]+)-r(\d+)/?")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (LotC-accepted-apps notifier; checks every 15 min)",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------- parsing ---
def parse_listing(html: str) -> list[dict]:
    """Return [{id, ign, url}] for every accepted app linked on a listing page."""
    soup = BeautifulSoup(html, "html.parser")
    apps: dict[int, dict] = {}
    for a in soup.find_all("a", href=True):
        m = APP_LINK_RE.search(a["href"])
        if not m:
            continue
        rid = int(m.group(2))
        text = a.get_text(strip=True)
        url = BASE + m.group(0).rstrip("/") + "/"
        if rid not in apps:
            apps[rid] = {"id": rid, "ign": None, "url": url}
        # The record title (the IGN) is the link with real text; skip
        # "3 comments" / "22 hours ago" style links to the same record.
        if text and apps[rid]["ign"] is None and not re.search(r"\d+\s+comment|ago|\bat\b", text, re.I):
            apps[rid]["ign"] = text
    for app in apps.values():
        if not app["ign"]:
            app["ign"] = APP_LINK_RE.search(app["url"]).group(1)
    return list(apps.values())


def _field(lines: list[str], label: str) -> str | None:
    """Find 'Label: value' on one line, or 'Label:' with the value on the next."""
    same = re.compile(rf"^{re.escape(label)}\s*:\s*(\S.*)$", re.I)
    alone = re.compile(rf"^{re.escape(label)}\s*:$", re.I)
    for i, line in enumerate(lines):
        m = same.match(line)
        if m:
            return m.group(1).strip()
        if alone.match(line):
            for nxt in lines[i + 1:i + 3]:
                if nxt:
                    return nxt
    return None


def parse_application(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines()]
    lines = [ln for ln in lines if ln]
    return {
        "discord": _field(lines, "Discord"),
        "character": _field(lines, "Character Name"),
        "race": _field(lines, "Character Race"),
        "timezone": _field(lines, "Timezone"),
    }


# ------------------------------------------------------------------- io ---
def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def load_seen() -> set[int] | None:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text() or "[]"))
    return None  # first ever run


def save_seen(seen: set[int]) -> None:
    STATE_FILE.write_text(json.dumps(sorted(seen)[-2000:]) + "\n")


def build_embed(app: dict, info: dict) -> dict:
    fields = [
        {"name": "IGN", "value": app["ign"], "inline": True},
        {"name": "Discord", "value": info.get("discord") or "—", "inline": True},
    ]
    if info.get("character"):
        char = info["character"] + (f" ({info['race']})" if info.get("race") else "")
        fields.append({"name": "Character", "value": char, "inline": False})
    if info.get("timezone"):
        fields.append({"name": "Timezone", "value": info["timezone"], "inline": False})
    return {
        "title": f"✅ Accepted: {app['ign']}",
        "url": app["url"],
        "color": 0x2ECC71,
        "fields": fields,
        "footer": {"text": f"Application #{app['id']}"},
    }


def post(embed: dict) -> None:
    for _ in range(3):
        r = requests.post(WEBHOOK, json={"embeds": [embed]}, timeout=30)
        if r.status_code == 429:  # rate limited: wait as Discord asks
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            continue
        r.raise_for_status()
        return
    raise RuntimeError("Discord kept rate-limiting the webhook")


# ----------------------------------------------------------------- main ---
def main() -> int:
    if not WEBHOOK:
        print("DISCORD_WEBHOOK_URL is not set", file=sys.stderr)
        return 1

    apps: dict[int, dict] = {}
    for n in range(1, PAGES_TO_SCAN + 1):
        url = LIST_URL if n == 1 else PAGE_URL.format(n=n)
        for app in parse_listing(fetch(url)):
            apps.setdefault(app["id"], app)
        time.sleep(1)
    if not apps:
        print("No applications found on the listing - the site layout may have changed", file=sys.stderr)
        return 1

    seen = load_seen()
    if seen is None:
        save_seen(set(apps))
        print(f"First run: recorded {len(apps)} existing applications without posting.")
        return 0

    new = sorted((a for a in apps.values() if a["id"] not in seen), key=lambda a: a["id"])
    for app in new:
        try:
            info = parse_application(fetch(app["url"]))
        except Exception as exc:  # still post the basics
            print(f"Couldn't read {app['url']}: {exc}", file=sys.stderr)
            info = {}
        post(build_embed(app, info))
        seen.add(app["id"])
        save_seen(seen)  # save as we go so a crash never double-posts
        print(f"Posted #{app['id']} {app['ign']}")
        time.sleep(1.5)

    if not new:
        print("No new accepted applications.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
