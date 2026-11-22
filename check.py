"""
LotC Applications -> Discord webhook

Run on a schedule (GitHub Actions). Each run:
  * reads the main application list (https://www.lordofthecraft.net/apply/new/),
    where submitted apps sit while Pending / Under Review, and posts any new one;
  * reads the Accepted list and posts any newly accepted app.
IDs already posted are saved to seen_apps.json so nothing posts twice.

Environment:
  DISCORD_WEBHOOK_URL  (required) the channel webhook link
  PAGES_TO_SCAN        (optional, default 2) Accepted pages to read, 25 apps each
  TEST_POST            (optional) "true" = also re-post the newest pending and
                       newest accepted app, labelled as a test
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
PAGES_TO_SCAN = int(os.getenv("PAGES_TO_SCAN", "2"))
TEST_POST = os.getenv("TEST_POST", "").lower() in {"1", "true", "yes"}
STATE_FILE = Path(os.getenv("STATE_FILE", "seen_apps.json"))

BASE = "https://www.lordofthecraft.net"

# Pending apps live directly under /apply/new/<name>-r<id>/ ; once decided they
# move to /apply/new/accepted/... or /apply/new/denied/... (same id).
CATEGORIES = {
    "pending": {
        "pages": [BASE + "/apply/new/"],
        "link": re.compile(r"/apply/new/([^/?#]+)-r(\d+)/?"),
        "title": "📥 New Application",
        "color": 0xF1C40F,
    },
    "accepted": {
        "pages": [BASE + "/apply/new/accepted/"]
        + [BASE + f"/apply/new/accepted/page/{n}/" for n in range(2, PAGES_TO_SCAN + 1)],
        "link": re.compile(r"/apply/new/accepted/([^/?#]+)-r(\d+)/?"),
        "title": "✅ Application Accepted",
        "color": 0x2ECC71,
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (LotC-applications notifier; checks every 15 min)",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------- parsing ---
def parse_listing(html: str, link_re: re.Pattern) -> list[dict]:
    """Return [{id, ign, url}] for every application link matching link_re."""
    soup = BeautifulSoup(html, "html.parser")
    apps: dict[int, dict] = {}
    for a in soup.find_all("a", href=True):
        m = link_re.search(a["href"])
        if not m:
            continue
        rid = int(m.group(2))
        text = a.get_text(strip=True)
        if rid not in apps:
            apps[rid] = {"id": rid, "ign": None, "url": BASE + m.group(0).rstrip("/") + "/"}
        # The record title (the IGN) is the link with real text; skip
        # "3 comments" / "22 hours ago" style links to the same record.
        if text and apps[rid]["ign"] is None and not re.search(r"\d+\s+comment|ago|\bat\b", text, re.I):
            apps[rid]["ign"] = text
    for app in apps.values():
        if not app["ign"]:
            app["ign"] = link_re.search(app["url"]).group(1)
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


# ------------------------------------------------------------- formatting ---
def _code(text: str) -> str:
    """Inline code chip: copyable, and underscores in names don't turn italic."""
    return "`" + text.replace("`", "'") + "`"


def _short_tz(tz: str) -> str:
    """'GMT - 6 (Central Time US & Canada, Mexico City)' -> 'GMT-6'"""
    tz = re.sub(r"\s*\(.*\)\s*$", "", tz)
    return re.sub(r"\s*([+-])\s*", r"\1", tz).strip()


def build_embed(kind: str, app: dict, info: dict, test: bool = False) -> dict:
    cat = CATEGORIES[kind]
    lines = [f"**IGN:** {_code(app['ign'])}"]
    lines.append(f"**Discord:** {_code(info['discord']) if info.get('discord') else '—'}")
    if info.get("character"):
        char = info["character"] + (f" · {info['race']}" if info.get("race") else "")
        lines.append(f"**Character:** {char}")
    if info.get("timezone"):
        lines.append(f"**Timezone:** {_short_tz(info['timezone'])}")
    lines.append("")
    lines.append(f"[View Application ↗]({app['url']})")
    footer = f"Lord of the Craft · #{app['id']}" + (" · test post" if test else "")
    return {
        "title": cat["title"],
        "description": "\n".join(lines),
        "color": cat["color"],
        "footer": {"text": footer},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ------------------------------------------------------------------- io ---
def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    data = json.loads(STATE_FILE.read_text() or "{}")
    if isinstance(data, list):  # old format: a plain list of accepted ids
        data = {"accepted": data}
    return {k: set(v) for k, v in data.items()}


def save_state(state: dict) -> None:
    out = {k: sorted(v)[-2000:] for k, v in state.items()}
    STATE_FILE.write_text(json.dumps(out) + "\n")


def post(embed: dict) -> None:
    for _ in range(3):
        r = requests.post(WEBHOOK, json={"embeds": [embed]}, timeout=30)
        if r.status_code == 429:  # rate limited: wait as Discord asks
            time.sleep(float(r.json().get("retry_after", 2)) + 0.5)
            continue
        r.raise_for_status()
        return
    raise RuntimeError("Discord kept rate-limiting the webhook")


def app_info(app: dict) -> dict:
    try:
        return parse_application(fetch(app["url"]))
    except Exception as exc:  # still post the basics
        print(f"Couldn't read {app['url']}: {exc}", file=sys.stderr)
        return {}


def scan(kind: str) -> dict[int, dict]:
    cat = CATEGORIES[kind]
    apps: dict[int, dict] = {}
    for url in cat["pages"]:
        for app in parse_listing(fetch(url), cat["link"]):
            apps.setdefault(app["id"], app)
        time.sleep(1)
    return apps


# ----------------------------------------------------------------- main ---
def main() -> int:
    if not WEBHOOK:
        print("DISCORD_WEBHOOK_URL is not set", file=sys.stderr)
        return 1

    state = load_state()
    newest: dict[str, dict] = {}
    failed = False

    for kind in CATEGORIES:
        try:
            apps = scan(kind)
        except Exception as exc:
            print(f"[{kind}] couldn't read the list: {exc}", file=sys.stderr)
            failed = True
            continue
        if apps:
            newest[kind] = max(apps.values(), key=lambda a: a["id"])

        if kind not in state:  # first time watching this list: don't flood
            state[kind] = set(apps)
            save_state(state)
            print(f"[{kind}] first run: recorded {len(apps)} existing applications without posting.")
            continue

        new = sorted((a for a in apps.values() if a["id"] not in state[kind]), key=lambda a: a["id"])
        for app in new:
            post(build_embed(kind, app, app_info(app)))
            state[kind].add(app["id"])
            save_state(state)  # save as we go so a crash never double-posts
            print(f"[{kind}] posted #{app['id']} {app['ign']}")
            time.sleep(1.5)
        if not new:
            print(f"[{kind}] nothing new ({len(apps)} on the list).")

    if TEST_POST:
        for kind, app in newest.items():
            post(build_embed(kind, app, app_info(app), test=True))
            print(f"[{kind}] test post: #{app['id']} {app['ign']}")
            time.sleep(1.5)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
