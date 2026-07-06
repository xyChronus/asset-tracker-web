"""Fetch and normalize crypto news from RSS feeds."""

import calendar
import re
import time
from html import unescape

import feedparser
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) asset-tracker/1.0"}


def _strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:280]


def fetch_all(feeds):
    """feeds: list of (source_name, url). Returns list of item dicts."""
    items = []
    for source, url in feeds:
        try:
            resp = requests.get(url, timeout=15, headers=UA)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
            for e in parsed.entries[:30]:
                link = e.get("link")
                title = e.get("title")
                if not link or not title:
                    continue
                pub = e.get("published_parsed") or e.get("updated_parsed")
                ts = int(calendar.timegm(pub) * 1000) if pub else int(time.time() * 1000)
                items.append({
                    "link": link,
                    "source": source,
                    "title": unescape(title).strip(),
                    "published": ts,
                    "summary": _strip_html(e.get("summary", "")),
                })
        except Exception as exc:  # a dead feed should never take the app down
            print(f"[news] {source}: {exc}")
    return items
