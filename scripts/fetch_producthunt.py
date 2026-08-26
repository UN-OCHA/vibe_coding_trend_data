"""
Weekly Product Hunt collector for the vibecoding site - the "what's new"
counterpart to fetch_trends.py's per-tool signals.

Every other source in this pipeline (GitHub, Hacker News, Google Trends, VS
Code Marketplace) only tracks tools someone has already added by name to
TOOLS/GITHUB_TOPICS/HN_TERMS/etc. - see compute_signals.py's docstring. That
makes them all structurally blind to a tool nobody's added yet. Product
Hunt's own "vibe-coding" category (producthunt.com/categories/vibe-coding)
is curated by Product Hunt itself, not by this project, so a brand-new tool
can show up here the same week it launches - before it has enough GitHub/HN
volume to register anywhere else on this site, and often before a person
notices it's worth adding to the other scripts' config by hand.

This script does NOT decide what to do with what it finds. It just writes
every "vibe-coding"-topic launch from the lookback window to
data/producthunt.json, honestly, with no keyword filtering (Product Hunt's
own topic tagging is the filter here, unlike the RSS/YouTube keyword checks
in fetch_news.py/fetch_youtube.py which have to guess topical relevance
themselves). The site cross-references each entry's name against the
tracked-tools list client-side to flag "not yet tracked" - see index.html.

Auth: Product Hunt's v2 API is GraphQL-only, at
  https://api.producthunt.com/v2/api/graphql
Full user-facing apps use an OAuth2 (PKCE) flow, but for a script like this
one, Product Hunt's own docs point at a non-expiring "developer_token" from
the API dashboard (producthunt.com/v2/oauth/applications) instead - same
shape as this pipeline's other secrets (GEMINI_API_KEY, TRENDS_MCP_API_KEY):
a long-lived key read from an env var, sent as `Authorization: Bearer
{token}`. Default app scope is read-only ("public"), which is all this
script needs.

IMPORTANT - two terms from Product Hunt's API docs to respect if this data
is ever surfaced beyond this proof of concept: (1) "The Product Hunt API
must not be used for commercial purposes" without contacting them first;
(2) they ask for attribution linking back to Product Hunt on anything built
with it - see the "Data sources" line in each page's footer disclosure.

IMPORTANT - the GraphQL query below (topic-filtered `posts`, ordered
NEWEST, with `id`/`name`/`tagline`/`url`/`website`/`votesCount`/
`createdAt` on each `Post` node) reflects Product Hunt's v2 schema as
publicly documented, NOT a live schema introspection - this project's
sandbox can't reach api.producthunt.com to verify it directly (see the
GitHub Action, which can). If a field name has drifted, this fails loudly
with a WARNING printout of the GraphQL "errors" payload rather than writing
garbage - check that message against the schema explorer at
api.producthunt.com/v2/docs first if a run ever comes back empty
unexpectedly.

Configuration:
  PRODUCTHUNT_API_KEY  - env var, a developer_token from the API dashboard.
                          Skipped entirely (not a failure) if unset.
"""

import datetime
import json
import os
import sys
import time

import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PRODUCTHUNT_JSON_PATH = os.path.join(DATA_DIR, "producthunt.json")
STATUS_JSON_PATH = os.path.join(DATA_DIR, "status.json")

API_URL = "https://api.producthunt.com/v2/api/graphql"
PRODUCTHUNT_API_KEY = os.environ.get("PRODUCTHUNT_API_KEY", "")

TOPIC_SLUG = "vibe-coding"
LOOKBACK_DAYS = 90  # a niche topic like this launches sparsely - a 7-day
                     # window (like the news/YouTube pipelines use) would
                     # come back empty most weeks
MAX_PAGES = 3        # 20 posts/page - caps a single run at 60 posts, well
                      # inside "fair use" even if the topic suddenly gets busy
MAX_TOTAL_ITEMS_KEPT = 200  # trim the archive so producthunt.json doesn't grow forever

QUERY = """
query VibeCodingLaunches($cursor: String) {
  posts(topic: "%s", order: NEWEST, first: 20, after: $cursor) {
    edges {
      node {
        id
        name
        tagline
        url
        website
        votesCount
        createdAt
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
""" % TOPIC_SLUG


def fetch_posts():
    """Returns a list of raw post dicts from the vibe-coding topic, newest
    first, stopping once a page's oldest post falls outside LOOKBACK_DAYS
    or MAX_PAGES is hit - whichever comes first."""
    if not PRODUCTHUNT_API_KEY:
        print("  WARNING: PRODUCTHUNT_API_KEY not set, skipping Product Hunt fetch.")
        return []

    headers = {
        "Authorization": f"Bearer {PRODUCTHUNT_API_KEY}",
        "Content-Type": "application/json",
    }
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=LOOKBACK_DAYS)

    posts = []
    cursor = None
    for page in range(MAX_PAGES):
        try:
            resp = requests.post(
                API_URL, headers=headers, timeout=30,
                json={"query": QUERY, "variables": {"cursor": cursor}},
            )
        except Exception as e:
            print(f"  WARNING: Product Hunt request failed: {e}")
            break

        if resp.status_code != 200:
            print(f"  WARNING: Product Hunt API returned {resp.status_code}: {resp.text[:300]}")
            break

        payload = resp.json()
        if payload.get("errors"):
            print(f"  WARNING: Product Hunt GraphQL errors (schema may have drifted - see this "
                  f"script's docstring): {payload['errors']}")
            break

        connection = (payload.get("data") or {}).get("posts") or {}
        edges = connection.get("edges") or []
        if not edges:
            break

        hit_cutoff = False
        for edge in edges:
            node = edge.get("node") or {}
            created_at = node.get("createdAt")
            if created_at and datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00")) < cutoff:
                hit_cutoff = True
                break
            posts.append(node)

        print(f"  page {page + 1}: {len(edges)} post(s)")
        if hit_cutoff:
            break

        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        time.sleep(1)

    return posts


def load_existing():
    if not os.path.exists(PRODUCTHUNT_JSON_PATH):
        return []
    with open(PRODUCTHUNT_JSON_PATH) as f:
        return json.load(f)


def update_status():
    """See fetch_news.py's update_status() for why this is duplicated
    per-script rather than shared."""
    status = {}
    if os.path.exists(STATUS_JSON_PATH):
        with open(STATUS_JSON_PATH) as f:
            status = json.load(f)
    status["producthunt"] = datetime.date.today().isoformat()
    with open(STATUS_JSON_PATH, "w") as f:
        json.dump(status, f, indent=2)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"Fetching Product Hunt '{TOPIC_SLUG}' topic launches (last {LOOKBACK_DAYS} days)...")
    raw_posts = fetch_posts()

    items = [{
        "id": p["id"],
        "name": p.get("name", ""),
        "tagline": p.get("tagline", ""),
        "producthunt_url": p.get("url", ""),
        "website": p.get("website", ""),
        "votes": p.get("votesCount", 0),
        "launched": p.get("createdAt", ""),
    } for p in raw_posts if p.get("id")]

    existing = load_existing()
    seen_ids = {item["id"] for item in items}
    merged = items + [item for item in existing if item.get("id") not in seen_ids]
    merged.sort(key=lambda x: x.get("launched", ""), reverse=True)
    merged = merged[:MAX_TOTAL_ITEMS_KEPT]

    with open(PRODUCTHUNT_JSON_PATH, "w") as f:
        json.dump(merged, f, indent=2)
    update_status()

    print(f"Wrote {len(merged)} Product Hunt launch(es) to {PRODUCTHUNT_JSON_PATH} "
          f"({len(items)} new this run).")


if __name__ == "__main__":
    sys.exit(main())
