"""
Daily news collector for the vibecoding site.

Unlike fetch_trends.py (numeric counts, weekly), this script pulls actual
articles - headline, link, source, date, category - and writes them to
data/news.json, which the site reads directly (no build step needed).

Sources are NOT hardcoded here. They live in a Google Sheet that a
non-technical person can edit directly - see docs/GOOGLE_SHEET_SCHEMA.md
for the exact columns expected. This script reads that sheet at the start
of every run via its public "publish to web" CSV export URL, so adding or
removing a source is a spreadsheet edit, not a code change.

A story's category (or categories - see categorize()) is NOT one of those
sheet columns, deliberately: a single feed can publish stories that read
very differently (a product launch vs. a funding round vs. a safety
story), so categorizing per-source instead of per-article was a poor fit.
Each story is categorized from its own title, and can land in more than
one category if it fits.

Each row in the sheet is one RSS feed. If a source doesn't publish RSS, it
doesn't belong in this pipeline - see the "adding a new source" notes in the
main repo README for why (scraping is fragile and often against ToS).

Same goes for the humanitarian-relevance flag (is_humanitarian_relevant()):
derived per-article from the title, not a sheet column either.

Optionally, if GEMINI_API_KEY is set, classify_with_gemini() adds a second
pass on top of (not instead of) the keyword-based matches_topic() /
categorize() above: for each new story that already passed the keyword
filter, ask Gemini to confirm it's genuinely on-topic (catches ambiguous
keyword matches, e.g. "Cursor" as a literal mouse cursor) and to assign
more accurate categories. It's called only on that already-small, already-
filtered set of new items per run - never on the whole archive - and is
capped at MAX_GEMINI_CALLS_PER_RUN calls per run to stay well inside a
free-tier quota. If the key is missing, the call fails, or the response
doesn't parse, this script silently falls back to the keyword-only result;
Gemini is never required for this script to work.

Configuration:
  SHEET_CSV_URL   - env var, the published-CSV URL of the Google Sheet.
  GEMINI_API_KEY  - env var, optional. Without it, classification is
                    keyword-only (see above).
  Everything else comes from the sheet itself, not from this file.
"""

import csv
import datetime
import html
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
STATUS_JSON_PATH = os.path.join(DATA_DIR, "status.json")
MAX_ITEMS_PER_SOURCE = 5
MAX_TOTAL_ITEMS_KEPT = 300  # trim the archive so news.json doesn't grow forever

SHEET_CSV_URL = os.environ.get("SHEET_CSV_URL", "")

# General tech/AI outlets (Ars Technica AI, TechCrunch AI, etc.) cover far
# more than vibe coding specifically - model releases, chips, policy, AI
# slop takes. A source-level category isn't enough to keep the site on
# topic, so every entry's title is also checked against this list before
# it's kept. Edit this list to tune what counts as "on topic" - it's
# intentionally broad (tool names + generic phrasing) since a feed's own
# scope varies a lot. "github copilot" (not bare "copilot") deliberately
# excludes Microsoft's broader Copilot branding (Windows/Office), which
# shows up constantly in general AI news and isn't about coding.
TOPIC_KEYWORDS = [
    "vibe coding", "vibe-coding", "vibecoding", "vibe-coded", "vibe coded",
    "ai coding", "ai-assisted coding", "ai pair programming",
    "coding agent", "agentic coding", "coding assistant",
    "ai code generation", "ai-generated code", "ai developer tool",
    "github copilot", "claude code",
    "replit agent", "devin ai", "llm coding",
]

# "Cursor" and "Codex" alone are ambiguous with ordinary English words (a
# mouse cursor, a historical codex) when matched as a lowercase substring -
# checked instead as a capitalized whole word against the ORIGINAL title,
# since real headlines about the tools always capitalize them as a proper
# noun ("Cursor raises $2B...") while generic uses don't ("the cursor
# blinks"). Same problem, same fix, for "Windsurf" (the sport) and
# "Lovable" (just an ordinary adjective) - both used to be looser
# substring entries in TOPIC_KEYWORDS above, which would have quietly let
# through any windsurfing-hobby story or any review calling something
# generically "lovable".
CAPITALIZED_WORD_KEYWORDS = ["Cursor", "Codex", "Windsurf", "Lovable"]
CAPITALIZED_WORD_RE = re.compile(r"\b(" + "|".join(CAPITALIZED_WORD_KEYWORDS) + r")\b")


def matches_topic(title):
    lowered = title.lower()
    if any(keyword in lowered for keyword in TOPIC_KEYWORDS):
        return True
    return bool(CAPITALIZED_WORD_RE.search(title))


# A story's category (or categories) come from its own title, not from
# whatever category its source is generally filed under in the Google
# Sheet - a source-wide category was a poor fit once a single feed (e.g.
# TechCrunch AI) turned out to publish stories that read very differently
# (a product launch vs. a funding round vs. a safety story). A title can
# match more than one of these, which is the point - a story is filed
# under every category it fits, not forced into exactly one. Order here is
# just display order, checked independently, not priority.
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


def categorize(title):
    lowered = title.lower()
    categories = [
        name for name, keywords in CATEGORY_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]
    return categories or ["Uncategorized"]


# Whether a story is "relevant to our work" used to be a person's one-time
# judgment call per SOURCE in the sheet (see git history /
# GOOGLE_SHEET_SCHEMA.md) - every story from a source got the same flag
# regardless of what that particular story was actually about. Derived from
# the title instead now, same reasoning as categorize(): a source-level
# flag is too coarse once you look at what any one source actually
# publishes.
HUMANITARIAN_KEYWORDS = [
    "humanitarian", "nonprofit", "non-profit", "ngo", "ict4d",
    "refugee", "disaster", "crisis", "relief", "developing world",
    "global south", "least developed", "low-resource", "low resource",
    "low-connectivity", "low connectivity", "offline-first", "offline first",
    "aid worker", "displacement", "displaced", "emergency response",
    "field team", "underserved",
]


def is_humanitarian_relevant(title):
    lowered = title.lower()
    return any(keyword in lowered for keyword in HUMANITARIAN_KEYWORDS)


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
# Hard cap on Gemini calls per run. This key is on Google's free tier and
# this script runs unattended on a schedule - there's no human in the loop
# to notice a runaway call count before it burns through a daily quota, so
# this cap is deliberately conservative and independent of how many sources
# end up in the sheet. Only ever called on the small, already keyword-
# filtered set of NEW items for a single run (see fetch_feed_items) - never
# re-run against the existing archive, which would scale with its size
# instead of with a single day's new stories.
MAX_GEMINI_CALLS_PER_RUN = 30
GEMINI_CALL_DELAY_SECONDS = 4  # keeps well under typical free-tier RPM limits
_gemini_calls_made = 0

VALID_CATEGORIES = set(CATEGORY_KEYWORDS.keys())


def classify_with_gemini(title, excerpt):
    """Best-effort second opinion on a story that already passed the
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
        "\"vibe coding\" trend). Given a headline and excerpt that already "
        "matched a keyword filter, decide two things and return them as "
        "JSON:\n\n"
        "is_relevant (boolean): true only if this story is genuinely "
        "about AI coding tools/assistants themselves - a launch, funding "
        "round, research finding, or risk concerning one of them. False "
        "if the match was a false positive, e.g. an ordinary mouse "
        "\"cursor\", a crossword \"codex\", or a tool mentioned only in "
        "passing while the story is about something else entirely.\n\n"
        "categories (array of strings): pick zero or more from exactly "
        "this list - Tools, Industry, Risks, Research - describing what "
        "the story is about. Tools = a product launch/update/feature. "
        "Industry = funding/valuation/acquisition/business news. Risks = "
        "security, safety, job loss, bias, or other concerns. Research = "
        "an academic paper, benchmark, or study. Use an empty array if "
        "none clearly fit.\n\n"
        f"Headline: {title}\n"
        f"Excerpt: {excerpt or '(none)'}"
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


IMG_TAG_RE = re.compile(r'<img[^>]+src="([^"]+)"')
OG_IMAGE_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE)
OG_IMAGE_RE_ALT = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.IGNORECASE)
MAX_OG_IMAGE_FETCHES_PER_RUN = 15  # politeness/runtime cap - see fetch_og_image

TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
EXCERPT_MAX_LEN = 160


def extract_excerpt(entry):
    """Plain-text excerpt for the story card - feed summaries are HTML,
    so this strips tags and unescapes entities before trimming to a clean
    word boundary rather than cutting mid-word."""
    text = TAG_RE.sub(" ", entry.get("summary", ""))
    text = html.unescape(text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    if len(text) > EXCERPT_MAX_LEN:
        text = text[:EXCERPT_MAX_LEN].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return text


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
    docs/GOOGLE_SHEET_SCHEMA.md): name, type, url, active, note

    A story's category and humanitarian relevance both come from its own
    title now (categorize(), is_humanitarian_relevant()), not from a
    sheet column - see those functions for why. The sheet no longer needs
    category or humanitarian_relevant columns at all for rss rows; if
    either is still present here it's simply not read.
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
            "note": row.get("note", "").strip(),
        })
    return sources


def fetch_feed_items(source):
    """Returns (new_items, url_to_image, url_to_excerpt). Both lookups
    cover every entry currently in the feed - on-topic or not, already
    archived or not - so main() can also use them to backfill a missing
    image/excerpt onto a story that predates this data existing, as long
    as that story is still within the feed's current window."""
    print(f"Fetching: {source['name']} ({source['url']})")
    try:
        parsed = feedparser.parse(source["url"])
    except Exception as e:
        print(f"  WARNING: could not parse feed for '{source['name']}': {e}")
        return [], {}, {}

    if parsed.bozo and not parsed.entries:
        print(f"  WARNING: feed for '{source['name']}' looked malformed and returned no entries.")
        return [], {}, {}

    url_to_image = {e.get("link", ""): extract_thumbnail(e) for e in parsed.entries}
    url_to_excerpt = {e.get("link", ""): extract_excerpt(e) for e in parsed.entries}

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

        title = entry.get("title", "Untitled")
        link = entry.get("link", "")
        excerpt = url_to_excerpt[link]
        categories = categorize(title)

        # Optional second opinion - see classify_with_gemini(). A None
        # result (no key, cap hit, or a failed/malformed call) means "keep
        # the keyword-based result as-is", not "drop this story".
        gemini_result = classify_with_gemini(title, excerpt)
        if gemini_result is not None:
            if not gemini_result["relevant"]:
                print(f"  Gemini flagged as off-topic, skipping: {title[:60]}")
                continue
            if gemini_result["categories"]:
                categories = gemini_result["categories"]

        items.append({
            "title": title,
            "url": link,
            "source": source["name"],
            "categories": categories,
            "humanitarian_relevant": is_humanitarian_relevant(title),
            "image": url_to_image[link],
            "excerpt": excerpt,
            "date": date_str,
            "fetched_at": datetime.date.today().isoformat(),
        })
    return items, url_to_image, url_to_excerpt


def load_existing_news():
    if not os.path.exists(NEWS_JSON_PATH):
        return []
    with open(NEWS_JSON_PATH) as f:
        return json.load(f)


def update_status():
    """Records today's date as the last time this pipeline ran, so the
    site can show an honest "as of" freshness indicator instead of
    leaving visitors to guess. Duplicated in fetch_youtube.py /
    compute_momentum.py rather than shared - see this codebase's
    self-contained-scripts convention (module docstrings)."""
    status = {}
    if os.path.exists(STATUS_JSON_PATH):
        with open(STATUS_JSON_PATH) as f:
            status = json.load(f)
    status["news"] = datetime.date.today().isoformat()
    with open(STATUS_JSON_PATH, "w") as f:
        json.dump(status, f, indent=2)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    sources = load_source_config()
    print(f"Loaded {len(sources)} active RSS source(s) from the Google Sheet.")

    new_items = []
    url_to_image = {}
    url_to_excerpt = {}
    for source in sources:
        items, source_url_to_image, source_url_to_excerpt = fetch_feed_items(source)
        new_items.extend(items)
        url_to_image.update(source_url_to_image)
        url_to_excerpt.update(source_url_to_excerpt)
        time.sleep(1)

    existing = load_existing_news()

    # Prune anything already archived that doesn't pass the topic filter.
    # An early run (before this filter existed) added a batch of generic
    # AI/tech stories with no topic check at all, and because of the URL
    # dedup below, nothing had ever removed them since - they'd sit in the
    # archive forever otherwise. Re-checking the whole archive here, not
    # just new items, also means tightening TOPIC_KEYWORDS later cleans up
    # the backlog automatically instead of only affecting new fetches.
    before_prune = len(existing)
    existing = [item for item in existing if matches_topic(item.get("title", ""))]
    pruned = before_prune - len(existing)
    if pruned:
        print(f"Pruned {pruned} already-archived stor{'y' if pruned == 1 else 'ies'} that no longer pass the topic filter.")

    # Same reasoning, applied to categories and humanitarian relevance -
    # cheap (no network), so re-derive for the whole archive every run
    # rather than only for new items. Tuning CATEGORY_KEYWORDS or
    # HUMANITARIAN_KEYWORDS later takes effect on old stories too. This is
    # keyword-only, deliberately - classify_with_gemini() is only ever
    # called on today's new items (see fetch_feed_items), not the archive,
    # so re-running this daily can't scale Gemini usage with archive size.
    for item in existing:
        item["categories"] = categorize(item.get("title", ""))
        item["humanitarian_relevant"] = is_humanitarian_relevant(item.get("title", ""))

    # Backfill: a story added before image/excerpt extraction existed (or
    # whose feed just didn't have one at the time) gets a second chance
    # here if it's still within the feed's current window.
    backfilled = 0
    for item in existing:
        url = item.get("url")
        if not item.get("image") and url_to_image.get(url):
            item["image"] = url_to_image[url]
            backfilled += 1
        if not item.get("excerpt") and url_to_excerpt.get(url):
            item["excerpt"] = url_to_excerpt[url]
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
    update_status()

    print(f"Wrote {len(merged)} total item(s) to {NEWS_JSON_PATH} ({len(new_items)} new this run).")


if __name__ == "__main__":
    main()
