"""
Daily YouTube fetcher - finds recently-published, fast-gaining videos on
vibe coding subtopics and writes them to data/youtube.json.

There's no official "trending in this niche" endpoint, so this approximates
it: for each configured search topic, pull recent videos (published in the
last N days) via the YouTube Data API's search.list, then fetch view counts
via videos.list and rank by views-per-day-since-published as a simple proxy
for "gaining popularity" rather than just "most viewed ever".

Search topics come from the same Google Sheet as the news sources - any row
with type=youtube is treated as a search query here, not an RSS feed.
See docs/GOOGLE_SHEET_SCHEMA.md.

Requires a YouTube Data API v3 key (free tier: 10,000 quota units/day;
search.list costs 100 units, so keep the topic list modest - each daily run
costs roughly 100-150 units per topic).

Configuration:
  SHEET_CSV_URL     - env var, same sheet as fetch_news.py
  YOUTUBE_API_KEY   - env var, YouTube Data API v3 key
"""

import csv
import datetime
import io
import json
import os
import sys

import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
YOUTUBE_JSON_PATH = os.path.join(DATA_DIR, "youtube.json")
LOOKBACK_DAYS = 7
MAX_RESULTS_PER_TOPIC = 10
KEEP_TOP_N = 15

SHEET_CSV_URL = os.environ.get("SHEET_CSV_URL", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")


def load_youtube_topics():
    if not SHEET_CSV_URL:
        print("ERROR: SHEET_CSV_URL not set - cannot load topic config.")
        sys.exit(1)

    resp = requests.get(SHEET_CSV_URL, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))

    topics = []
    for row in reader:
        if row.get("active", "").strip().lower() not in ("yes", "true", "1"):
            continue
        if row.get("type", "").strip().lower() != "youtube":
            continue
        topics.append({
            "query": row.get("url", "").strip(),  # for youtube rows, "url" column holds the search query
            "category": row.get("category", "").strip() or "Uncategorized",
            "humanitarian_relevant": row.get("humanitarian_relevant", "").strip().lower() in ("yes", "true", "1"),
        })
    return topics


def search_recent_videos(query):
    published_after = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=LOOKBACK_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "key": YOUTUBE_API_KEY,
            "q": query,
            "part": "snippet",
            "type": "video",
            "order": "date",
            "publishedAfter": published_after,
            "maxResults": MAX_RESULTS_PER_TOPIC,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  WARNING: YouTube search failed for '{query}': {resp.status_code} {resp.text[:200]}")
        return []
    return resp.json().get("items", [])


def get_video_stats(video_ids):
    if not video_ids:
        return {}
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"key": YOUTUBE_API_KEY, "id": ",".join(video_ids), "part": "statistics,snippet"},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  WARNING: YouTube videos.list failed: {resp.status_code} {resp.text[:200]}")
        return {}
    return {item["id"]: item for item in resp.json().get("items", [])}


def main():
    if not YOUTUBE_API_KEY:
        print("WARNING: YOUTUBE_API_KEY not set, skipping YouTube fetch.")
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    topics = load_youtube_topics()
    print(f"Loaded {len(topics)} active YouTube topic(s) from the Google Sheet.")

    all_candidates = []
    for topic in topics:
        results = search_recent_videos(topic["query"])
        video_ids = [r["id"]["videoId"] for r in results if "videoId" in r.get("id", {})]
        stats = get_video_stats(video_ids)

        for vid, data in stats.items():
            published = datetime.datetime.strptime(
                data["snippet"]["publishedAt"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=datetime.timezone.utc)
            age_days = max((datetime.datetime.now(datetime.timezone.utc) - published).days, 1)
            views = int(data.get("statistics", {}).get("viewCount", 0))

            thumbnails = data["snippet"].get("thumbnails", {})
            thumbnail = (thumbnails.get("medium") or thumbnails.get("default") or {}).get("url", "")

            all_candidates.append({
                "title": data["snippet"]["title"],
                "channel": data["snippet"]["channelTitle"],
                "url": f"https://www.youtube.com/watch?v={vid}",
                "thumbnail": thumbnail,
                "published": published.date().isoformat(),
                "views": views,
                "views_per_day": round(views / age_days, 1),
                "category": topic["category"],
                "humanitarian_relevant": topic["humanitarian_relevant"],
            })

    all_candidates.sort(key=lambda x: x["views_per_day"], reverse=True)
    top = all_candidates[:KEEP_TOP_N]

    with open(YOUTUBE_JSON_PATH, "w") as f:
        json.dump(top, f, indent=2)

    print(f"Wrote {len(top)} video(s) to {YOUTUBE_JSON_PATH}, ranked by views/day since published.")


if __name__ == "__main__":
    main()
