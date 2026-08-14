"""
Daily news collector for the vibecoding site.

Unlike fetch_trends.py (numeric counts, weekly), this script pulls actual
articles - headline, link, source, date, category - and writes them to
data/news.json, which the site reads directly (no build step needed).

Sources and categories are NOT hardcoded here. They live in a Google Sheet
that a non-technical person can edit directly - see docs/GOOGLE_SHEET_SCHEMA.md
for the exact columns expected. This script reads that sheet at the start of
every run via its public "publish to web" CSV export URL, so adding, removing,
or re-categorizing a source is a spreadsheet edit, not a code change.

Each row in the sheet is one RSS feed. If a source doesn't publish RSS, it
doesn't belong in this pipeline - see the "adding a new source" notes in the
main repo README for why (scraping is fragile and often against ToS).

Configuration:
  SHEET_CSV_URL - env var, the published-CSV URL of the Google Sheet.
  Everything else (which sources, which categories, the humanitarian flag)
  comes from the sheet itself, not from this file.
"""

import csv
import datetime
import io
import json
import os
import re
import sys
import time

import feedparser
import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
NEWS_JSON_PATH = os.path.join(DATA_DIR, "news.json")
MAX_ITEMS_PER_SOURCE = 5
MAX_TOTAL_ITEMS_KEPT = 300  # trim the archive so news.json doesn't grow forever

SHEET_CSV_URL = os.environ.get("SHEET_CSV_URL", "")

# General tech/AI outlets (Ars Technica AI, TechCrunch AI, etc.) cover far
# more than vibe coding specifically - model releases, chips, policy, AI
# slop takes. A source-level category isn't enough to keep the site on
# topic, so every entry's title is also checked against this list before
# it's kept. Edit this list to tune what counts as "on topic" - it's
# intentionally broad (tool names + generic phrasing) since a feed's own
# scope varies a lot.
TOPIC_KEYWORDS = [
    "vibe coding", "vibe-coding", "vibecoding",
    "ai coding", "ai-assisted coding", "ai pair programming",
    "coding agent", "agentic coding", "coding assistant",
    "ai code generation", "ai-generated code", "ai developer tool",
    "copilot", "cursor", "claude code", "codex", "windsurf",
    "replit agent", "devin ai", "llm coding", "vibe-coded", "vibe coded",
]


def matches_topic(title):
    lowered = title.lower()
    return any(keyword in lowered for keyword in TOPIC_KEYWORDS)


IMG_TAG_RE = re.compile(r'<img[^>]+src="([^"]+)"')


def extract_thumbnail(entry):
    """Best-effort image URL for a story card. RSS has no one standard
    field for this, so check the common ones in order of reliability:
    Media RSS thumbnail/content, a plain enclosure, then fall back to the
    first <img> in the summary HTML. Returns "" if none are present -
    the site falls back to a gradient placeholder in that case."""
    media_thumb = entry.get("media_thumbnail")
    if media_thumb and media_thumb[0].get("url"):
        return media_thumb[0]["url"]

    media_content = entry.get("media_content")
    if media_content:
        for m in media_content:
            if m.get("url") and m.get("medium", "image") == "image":
                return m["url"]

    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and link.get("type", "").startswith("image/"):
            return link.get("href", "")

    summary = entry.get("summary", "")
    match = IMG_TAG_RE.search(summary)
    if match:
        return match.group(1)

    return ""


def load_source_config():
    """Fetch and parse the Google Sheet. Expected columns (see
    docs/GOOGLE_SHEET_SCHEMA.md):
      name, type, url, category, active, humanitarian_relevant, note
    """
    if not SHEET_CSV_URL:
        print("ERROR: SHEET_CSV_URL not set - cannot load source config.")
        sys.exit(1)

    resp = requests.get(SHEET_CSV_URL, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))

    sources = []
    for row in reader:
        if row.get("active", "").strip().lower() not in ("yes", "true", "1"):
            continue
        if row.get("type", "").strip().lower() != "rss":
            continue  # fetch_youtube.py handles the youtube rows separately
        sources.append({
            "name": row.get("name", "").strip(),
            "url": row.get("url", "").strip(),
            "category": row.get("category", "").strip() or "Uncategorized",
            "humanitarian_relevant": row.get("humanitarian_relevant", "").strip().lower() in ("yes", "true", "1"),
            "note": row.get("note", "").strip(),
        })
    return sources


def fetch_feed_items(source):
    print(f"Fetching: {source['name']} ({source['url']})")
    try:
        parsed = feedparser.parse(source["url"])
    except Exception as e:
        print(f"  WARNING: could not parse feed for '{source['name']}': {e}")
        return []

    if parsed.bozo and not parsed.entries:
        print(f"  WARNING: feed for '{source['name']}' looked malformed and returned no entries.")
        return []

    on_topic = [e for e in parsed.entries if matches_topic(e.get("title", ""))]
    skipped = len(parsed.entries) - len(on_topic)
    if skipped:
        print(f"  Filtered out {skipped} off-topic entr{'y' if skipped == 1 else 'ies'} from '{source['name']}'.")

    items = []
    for entry in on_topic[:MAX_ITEMS_PER_SOURCE]:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if published:
            date_str = datetime.date(*published[:3]).isoformat()
        else:
            date_str = datetime.date.today().isoformat()

        items.append({
            "title": entry.get("title", "Untitled"),
            "url": entry.get("link", ""),
            "source": source["name"],
            "category": source["category"],
            "humanitarian_relevant": source["humanitarian_relevant"],
            "image": extract_thumbnail(entry),
            "date": date_str,
            "fetched_at": datetime.date.today().isoformat(),
        })
    return items


def load_existing_news():
    if not os.path.exists(NEWS_JSON_PATH):
        return []
    with open(NEWS_JSON_PATH) as f:
        return json.load(f)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    sources = load_source_config()
    print(f"Loaded {len(sources)} active RSS source(s) from the Google Sheet.")

    new_items = []
    for source in sources:
        new_items.extend(fetch_feed_items(source))
        time.sleep(1)

    existing = load_existing_news()

    # Dedup on (url) - a story already in the archive doesn't get re-added,
    # so re-running this daily doesn't create duplicates.
    seen_urls = {item["url"] for item in existing if item.get("url")}
    merged = existing + [item for item in new_items if item["url"] not in seen_urls]

    # Newest first, trim to the cap
    merged.sort(key=lambda x: x["date"], reverse=True)
    merged = merged[:MAX_TOTAL_ITEMS_KEPT]

    with open(NEWS_JSON_PATH, "w") as f:
        json.dump(merged, f, indent=2)

    print(f"Wrote {len(merged)} total item(s) to {NEWS_JSON_PATH} ({len(new_items)} new this run).")


if __name__ == "__main__":
    main()
