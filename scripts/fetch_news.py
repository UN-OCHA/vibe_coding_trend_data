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
OG_IMAGE_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE)
OG_IMAGE_RE_ALT = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.IGNORECASE)
MAX_OG_IMAGE_FETCHES_PER_RUN = 15  # politeness/runtime cap - see fetch_og_image


def extract_thumbnail(entry):
    """Best-effort image URL for a story card, from feed data only (see
    fetch_og_image for the network fallback). RSS has no one standard
    field for this, so check the common ones in order of reliability:
    Media RSS thumbnail/content, an enclosure, then an <img> tag in
    either the full content or the summary HTML. Returns "" if none are
    present.

    The content vs. summary distinction matters in practice: ICTworks
    (WordPress) puts its only <img> inside <content:encoded>
    (feedparser: entry.content), with summary/description left as a
    plain-text excerpt with no image at all - checking summary alone
    silently missed every story from it. TechCrunch's feed has no image
    data in ANY field (confirmed by inspecting a live entry - no media
    tags, no enclosure, no content field, plain-text summary) - for
    that case there's genuinely nothing here to extract; see
    fetch_og_image for how those get a thumbnail instead."""
    media_thumb = entry.get("media_thumbnail")
    if media_thumb and media_thumb[0].get("url"):
        return media_thumb[0]["url"]

    media_content = entry.get("media_content")
    if media_content:
        for m in media_content:
            if m.get("url") and m.get("medium", "image") == "image":
                return m["url"]

    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("image/") and enc.get("href"):
            return enc["href"]

    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and link.get("type", "").startswith("image/"):
            return link.get("href", "")

    for block in entry.get("content", []):
        match = IMG_TAG_RE.search(block.get("value", ""))
        if match:
            return match.group(1)

    match = IMG_TAG_RE.search(entry.get("summary", ""))
    if match:
        return match.group(1)

    return ""


def fetch_og_image(url):
    """Last-resort fallback for a story whose feed has no image data in
    any field (confirmed case: TechCrunch). Fetches the article page
    itself and reads its og:image meta tag.

    This is the one place this script does anything scraping-adjacent -
    fetch_news.py's module docstring explains why the rest of the
    pipeline sticks to RSS instead. Kept deliberately minimal to limit
    that exposure: one GET per story, a short timeout, and any failure
    (network error, no og:image tag, non-200) just means no image for
    that story rather than a crashed run. Callers are responsible for
    respecting MAX_OG_IMAGE_FETCHES_PER_RUN so a source with no feed
    images can't turn every run into dozens of extra requests."""
    if not url:
        return ""
    try:
        resp = requests.get(
            url, timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; VibecodeDailyBot/1.0; +https://github.com/UN-OCHA/vibe_coding_trend_data)"},
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"    WARNING: og:image fetch failed for {url}: {e}")
        return ""

    match = OG_IMAGE_RE.search(resp.text) or OG_IMAGE_RE_ALT.search(resp.text)
    return match.group(1) if match else ""


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
    """Returns (new_items, url_to_image). url_to_image covers every entry
    currently in the feed - on-topic or not, already archived or not - so
    main() can also use it to backfill a missing image onto a story that
    was added before image extraction existed, as long as that story is
    still within the feed's current window."""
    print(f"Fetching: {source['name']} ({source['url']})")
    try:
        parsed = feedparser.parse(source["url"])
    except Exception as e:
        print(f"  WARNING: could not parse feed for '{source['name']}': {e}")
        return [], {}

    if parsed.bozo and not parsed.entries:
        print(f"  WARNING: feed for '{source['name']}' looked malformed and returned no entries.")
        return [], {}

    url_to_image = {e.get("link", ""): extract_thumbnail(e) for e in parsed.entries}

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
            "image": url_to_image[entry.get("link", "")],
            "date": date_str,
            "fetched_at": datetime.date.today().isoformat(),
        })
    return items, url_to_image


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
    url_to_image = {}
    for source in sources:
        items, source_url_to_image = fetch_feed_items(source)
        new_items.extend(items)
        url_to_image.update(source_url_to_image)
        time.sleep(1)

    existing = load_existing_news()

    # Backfill: a story added before image extraction existed (or whose
    # feed just didn't have one at the time) gets a second chance here if
    # it's still within the feed's current window.
    backfilled = 0
    for item in existing:
        if not item.get("image") and url_to_image.get(item.get("url")):
            item["image"] = url_to_image[item["url"]]
            backfilled += 1
    if backfilled:
        print(f"Backfilled image(s) for {backfilled} existing stor{'y' if backfilled == 1 else 'ies'} still present in today's feeds.")

    # og:image fallback - for stories whose feed has no image data in any
    # field at all (confirmed case: TechCrunch). Capped per run: this is
    # one HTTP request per attempt against a third-party site we don't
    # control, so it stays bounded and polite rather than trying every
    # image-less story every single run.
    og_fetches = 0
    for item in new_items + existing:
        if og_fetches >= MAX_OG_IMAGE_FETCHES_PER_RUN:
            break
        if item.get("image"):
            continue
        image = fetch_og_image(item["url"])
        if image:
            item["image"] = image
            print(f"  og:image found for: {item['title'][:60]}")
        og_fetches += 1
        time.sleep(1)

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
