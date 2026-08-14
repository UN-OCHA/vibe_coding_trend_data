"""
Daily YouTube fetcher - finds recently-published, fast-gaining videos on
vibe coding subtopics and writes them to data/youtube.json.

There's no official "trending in this niche" endpoint, so this approximates
it: for each configured search topic (or channel - see below), pull recent
videos (published in the last N days) via the YouTube Data API's
search.list, then fetch view counts via videos.list and rank by
views-per-day-since-published as a simple proxy for "gaining popularity"
rather than just "most viewed ever".

Topics and channels come from the same Google Sheet as the news sources -
see docs/GOOGLE_SHEET_SCHEMA.md.
  type=youtube          - url column holds a search query (e.g.
                           "vibe coding tutorial"), searched across all of
                           YouTube.
  type=youtube_channel  - url column holds a channel name, @handle, or raw
                           channel ID - resolved to a channel ID (see
                           resolve_channel_id()) and that channel's recent
                           uploads are pulled instead of a keyword search.

Requires a YouTube Data API v3 key (free tier: 10,000 quota units/day;
search.list costs 100 units regardless of mode, so keep the topic/channel
list modest. A youtube_channel row costs up to 2x a youtube row's quota if
its url is a plain name or @handle, since resolving that to a channel ID
is a separate lookup before the actual video search - a raw channel ID
(starts with "UC", 24 characters) skips that extra call.

Unlike fetch_news.py's RSS sources, results here previously had no
relevance gate at all beyond whatever YouTube's own search ranked highly
for a topic query - a channel row in particular pulls a channel's ENTIRE
recent upload history, on-topic or not. matches_topic() (duplicated from
fetch_news.py) now filters every search result's title before it costs a
videos.list quota call, same reasoning as that script: a curated source
isn't the same as every item from it being on-topic.

Optionally, if GEMINI_API_KEY is set, classify_with_gemini() adds a second
opinion on top of that keyword filter, same pattern (and same per-run cap)
as fetch_news.py - see that script's docstring for the reasoning. Falls
back to keyword-only behavior if the key is missing or a call fails.

Configuration:
  SHEET_CSV_URL     - env var, same sheet as fetch_news.py
  YOUTUBE_API_KEY   - env var, YouTube Data API v3 key
  GEMINI_API_KEY    - env var, optional. Without it, classification is
                      keyword-only.
"""

import csv
import datetime
import io
import json
import os
import re
import sys
import time

import requests

# Duplicated from fetch_news.py rather than imported - each script here is
# self-contained and independently runnable (see README), so a shared
# module isn't part of this codebase's pattern. Keep these two lists in
# sync by hand if either changes. See fetch_news.py's categorize() /
# is_humanitarian_relevant() for the reasoning: a video's category and
# humanitarian relevance come from its own title, not a sheet column -
# a source-level flag was too coarse once a single search topic could
# surface videos about very different things.
CATEGORY_KEYWORDS = {
    "Tools": [
        "launches", "launch", "release", "released", "update", "updated",
        "feature", "introduces", "adds", "new mode", "desktop app", "ide",
        "extension", "plugin", "open-sources", "open sources", "now available",
        "rolls out", "rolling out", "ships", "now supports", "now the default",
        "goes live", "in beta",
    ],
    "Industry": [
        "raise", "raises", "raised", "funding", "valuation", "valued at",
        "ipo", "acquire", "acquisition", "invest", "investor", "startup",
        "revenue", "partners with", "partnership", "merger", "billion",
        "million",
    ],
    "Risks": [
        "vulnerability", "vulnerable", "security flaw", "exploit", "breach",
        "backdoor", "malicious", "risk", "concern", "warns", "warning",
        "job loss", "layoff", "hallucinat", "bias", "prompt injection",
        "safety", "danger", "harm", "scam", "fraud",
    ],
    "Research": [
        "research", "researchers", "study", "benchmark", "paper", "arxiv",
        "evaluation", "finds", "found that", "analysis",
    ],
}

HUMANITARIAN_KEYWORDS = [
    "humanitarian", "nonprofit", "non-profit", "ngo", "ict4d",
    "refugee", "disaster", "crisis", "relief", "developing world",
    "global south", "least developed", "low-resource", "low resource",
    "low-connectivity", "low connectivity", "offline-first", "offline first",
    "aid worker", "displacement", "displaced", "emergency response",
    "field team", "underserved",
]


def categorize(title):
    lowered = title.lower()
    categories = [
        name for name, keywords in CATEGORY_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]
    return categories or ["Uncategorized"]


def is_humanitarian_relevant(title):
    lowered = title.lower()
    return any(keyword in lowered for keyword in HUMANITARIAN_KEYWORDS)


# Also duplicated from fetch_news.py - see that file for the reasoning on
# both the keyword list and the capitalized-whole-word handling for
# "Cursor"/"Codex" (ambiguous with ordinary English words otherwise).
TOPIC_KEYWORDS = [
    "vibe coding", "vibe-coding", "vibecoding", "vibe-coded", "vibe coded",
    "ai coding", "ai-assisted coding", "ai pair programming",
    "coding agent", "agentic coding", "coding assistant",
    "ai code generation", "ai-generated code", "ai developer tool",
    "github copilot", "claude code", "windsurf",
    "replit agent", "devin ai", "llm coding",
]
CAPITALIZED_WORD_KEYWORDS = ["Cursor", "Codex"]
CAPITALIZED_WORD_RE = re.compile(r"\b(" + "|".join(CAPITALIZED_WORD_KEYWORDS) + r")\b")


def matches_topic(title):
    lowered = title.lower()
    if any(keyword in lowered for keyword in TOPIC_KEYWORDS):
        return True
    return bool(CAPITALIZED_WORD_RE.search(title))


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
# Same conservative per-run cap as fetch_news.py, and for the same reason -
# see that file. This script's own counter is independent of
# fetch_news.py's (they run as separate processes), so the two scripts'
# caps are not shared, but each is bounded on its own.
MAX_GEMINI_CALLS_PER_RUN = 30
GEMINI_CALL_DELAY_SECONDS = 4
_gemini_calls_made = 0

VALID_CATEGORIES = set(CATEGORY_KEYWORDS.keys())


def classify_with_gemini(title, description):
    """Best-effort second opinion on a video that already passed the
    keyword-based matches_topic() filter. Returns
    {"relevant": bool, "categories": [...]} on success, or None if the key
    isn't configured, the per-run cap is hit, or anything about the call
    fails or comes back malformed - callers must fall back to the keyword-
    based result in every None case, never treat None as "not relevant"."""
    global _gemini_calls_made
    if not GEMINI_API_KEY:
        return None
    if _gemini_calls_made >= MAX_GEMINI_CALLS_PER_RUN:
        return None
    _gemini_calls_made += 1

    prompt = (
        "You are helping curate a news site about AI-assisted software "
        "development tools (examples: GitHub Copilot, Claude Code, "
        "Cursor, Codex, Windsurf, Replit Agent, Devin, and the general "
        "\"vibe coding\" trend). Given a YouTube video title and "
        "description that already matched a keyword filter, decide two "
        "things and return them as JSON:\n\n"
        "is_relevant (boolean): true only if this video is genuinely "
        "about AI coding tools/assistants themselves. False if the match "
        "was a false positive, e.g. an ordinary mouse \"cursor\", or a "
        "tool mentioned only in passing (a channel's general programming "
        "video that isn't really about the tool).\n\n"
        "categories (array of strings): pick zero or more from exactly "
        "this list - Tools, Industry, Risks, Research - describing what "
        "the video is about. Tools = a product launch/update/feature/demo. "
        "Industry = funding/valuation/acquisition/business news. Risks = "
        "security, safety, job loss, bias, or other concerns. Research = "
        "an academic paper, benchmark, or study. Use an empty array if "
        "none clearly fit.\n\n"
        f"Title: {title}\n"
        f"Description: {(description or '(none)')[:500]}"
    )

    try:
        resp = requests.post(
            GEMINI_API_URL,
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseSchema": {
                        "type": "OBJECT",
                        "properties": {
                            "is_relevant": {"type": "BOOLEAN"},
                            "categories": {
                                "type": "ARRAY",
                                "items": {"type": "STRING"},
                            },
                        },
                        "required": ["is_relevant", "categories"],
                    },
                },
            },
            timeout=15,
        )
        time.sleep(GEMINI_CALL_DELAY_SECONDS)
        if resp.status_code != 200:
            print(f"    WARNING: Gemini classification failed ({resp.status_code}) for '{title[:60]}': {resp.text[:200]}")
            return None
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        categories = [c for c in parsed.get("categories", []) if c in VALID_CATEGORIES]
        return {
            "relevant": bool(parsed.get("is_relevant", True)),
            "categories": categories,
        }
    except Exception as e:
        print(f"    WARNING: Gemini classification error for '{title[:60]}': {e}")
        return None


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
YOUTUBE_JSON_PATH = os.path.join(DATA_DIR, "youtube.json")
LOOKBACK_DAYS = 7
MAX_RESULTS_PER_TOPIC = 10
KEEP_TOP_N = 15

SHEET_CSV_URL = os.environ.get("SHEET_CSV_URL", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")


def load_youtube_topics():
    """Returns (topics, channels). topics are type=youtube rows (search
    queries); channels are type=youtube_channel rows (a name/@handle/ID
    to resolve - see resolve_channel_id())."""
    if not SHEET_CSV_URL:
        print("ERROR: SHEET_CSV_URL not set - cannot load topic config.")
        sys.exit(1)

    resp = requests.get(SHEET_CSV_URL, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))

    topics = []
    channels = []
    for row in reader:
        if row.get("active", "").strip().lower() not in ("yes", "true", "1"):
            continue
        row_type = row.get("type", "").strip().lower()
        # for both row types, the "url" column holds the topic query /
        # channel name-or-handle-or-ID rather than an actual URL
        if row_type == "youtube":
            topics.append({"query": row.get("url", "").strip()})
        elif row_type == "youtube_channel":
            channels.append({"channel_query": row.get("url", "").strip()})
    return topics, channels


CHANNEL_ID_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")


def resolve_channel_id(channel_query):
    """Accepts a raw channel ID, an @handle, or a plain channel name and
    returns a channel ID, or None if it couldn't be resolved. A raw ID is
    used as-is (no extra API call, and the only form that's unambiguous);
    an @handle is resolved via channels.list; anything else is treated as
    a name and resolved via a type=channel search.list, taking the top
    match - an ambiguous or misspelled name can resolve to the wrong
    channel, so if that happens, switch the sheet row to the exact
    @handle or channel ID instead."""
    channel_query = channel_query.strip()
    if CHANNEL_ID_RE.match(channel_query):
        return channel_query

    if channel_query.startswith("@"):
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"key": YOUTUBE_API_KEY, "part": "id", "forHandle": channel_query},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"  WARNING: channel handle lookup failed for '{channel_query}': {resp.status_code} {resp.text[:200]}")
            return None
        items = resp.json().get("items", [])
        if not items:
            print(f"  WARNING: no channel found for handle '{channel_query}'")
            return None
        return items[0]["id"]

    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={"key": YOUTUBE_API_KEY, "part": "snippet", "type": "channel", "q": channel_query, "maxResults": 1},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  WARNING: channel name search failed for '{channel_query}': {resp.status_code} {resp.text[:200]}")
        return None
    items = resp.json().get("items", [])
    if not items:
        print(f"  WARNING: no channel found matching '{channel_query}'")
        return None
    channel_id = items[0]["id"]["channelId"]
    print(f"  Resolved channel '{channel_query}' -> '{items[0]['snippet']['title']}' ({channel_id})")
    return channel_id


def _search_videos(extra_params, error_label):
    """Shared by search_recent_videos and search_channel_videos - both
    query search.list for recent videos, differing only in whether
    they're scoped by a text query or a channel ID."""
    published_after = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=LOOKBACK_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet",
        "type": "video",
        "order": "date",
        "publishedAfter": published_after,
        "maxResults": MAX_RESULTS_PER_TOPIC,
    }
    params.update(extra_params)

    resp = requests.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=30)
    if resp.status_code != 200:
        print(f"  WARNING: YouTube search failed for '{error_label}': {resp.status_code} {resp.text[:200]}")
        return []
    return resp.json().get("items", [])


def search_recent_videos(query):
    return _search_videos({"q": query}, query)


def search_channel_videos(channel_id):
    return _search_videos({"channelId": channel_id}, channel_id)


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
    topics, channels = load_youtube_topics()
    print(f"Loaded {len(topics)} active YouTube topic(s) and {len(channels)} channel(s) from the Google Sheet.")

    all_results = []
    for topic in topics:
        all_results.extend(search_recent_videos(topic["query"]))

    for channel in channels:
        channel_id = resolve_channel_id(channel["channel_query"])
        if not channel_id:
            continue  # already warned in resolve_channel_id
        all_results.extend(search_channel_videos(channel_id))

    before_filter = len(all_results)
    all_results = [r for r in all_results if matches_topic(r.get("snippet", {}).get("title", ""))]
    skipped = before_filter - len(all_results)
    if skipped:
        print(f"  Filtered out {skipped} off-topic video result(s) before fetching stats.")

    all_candidates = []
    if all_results:
        video_ids = [r["id"]["videoId"] for r in all_results if "videoId" in r.get("id", {})]
        stats = get_video_stats(video_ids)

        for vid, data in stats.items():
            published = datetime.datetime.strptime(
                data["snippet"]["publishedAt"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=datetime.timezone.utc)
            age_days = max((datetime.datetime.now(datetime.timezone.utc) - published).days, 1)
            views = int(data.get("statistics", {}).get("viewCount", 0))

            thumbnails = data["snippet"].get("thumbnails", {})
            thumbnail = (thumbnails.get("medium") or thumbnails.get("default") or {}).get("url", "")
            title = data["snippet"]["title"]
            description = data["snippet"].get("description", "")
            categories = categorize(title)

            # Optional second opinion - see classify_with_gemini(). A None
            # result (no key, cap hit, or a failed/malformed call) means
            # "keep the keyword-based result as-is", not "drop this video".
            gemini_result = classify_with_gemini(title, description)
            if gemini_result is not None:
                if not gemini_result["relevant"]:
                    print(f"  Gemini flagged as off-topic, skipping: {title[:60]}")
                    continue
                if gemini_result["categories"]:
                    categories = gemini_result["categories"]

            all_candidates.append({
                "title": title,
                "channel": data["snippet"]["channelTitle"],
                "url": f"https://www.youtube.com/watch?v={vid}",
                "thumbnail": thumbnail,
                "published": published.date().isoformat(),
                "views": views,
                "views_per_day": round(views / age_days, 1),
                "categories": categories,
                "humanitarian_relevant": is_humanitarian_relevant(title),
            })

    all_candidates.sort(key=lambda x: x["views_per_day"], reverse=True)
    top = all_candidates[:KEEP_TOP_N]

    with open(YOUTUBE_JSON_PATH, "w") as f:
        json.dump(top, f, indent=2)

    print(f"Wrote {len(top)} video(s) to {YOUTUBE_JSON_PATH}, ranked by views/day since published.")


if __name__ == "__main__":
    main()
