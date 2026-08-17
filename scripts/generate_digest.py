"""
Weekly auto-written digest - a short editorial summary of the week's
dominant story and any notable momentum leaderboard shift, written by
Gemini and read directly by index.html.

This is entirely optional and additive. If GEMINI_API_KEY isn't set, or
the call fails, comes back empty, or comes back malformed, this script
leaves any existing data/digest.json untouched rather than overwriting it
with something worse or deleting it - a stale-but-real digest is still
useful, and its own "date" field already makes that staleness visible on
the site (see the freshness indicator work in fetch_news.py /
compute_momentum.py).

Uses a single Gemini call per run - this runs weekly, so even worst-case
that's a handful of calls a month, well inside a free-tier quota.

Run this after compute_momentum.py, on the same weekly schedule - it
reads that script's already-written data/momentum.json and
data/momentum_history.json for "what changed on the leaderboard", plus
data/news.json (written daily) for the week's top stories.

Configuration:
  GEMINI_API_KEY - env var. Required; without it this script is a no-op.
"""

import datetime
import json
import os

import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
NEWS_JSON_PATH = os.path.join(DATA_DIR, "news.json")
MOMENTUM_HISTORY_JSON_PATH = os.path.join(DATA_DIR, "momentum_history.json")
DIGEST_JSON_PATH = os.path.join(DATA_DIR, "digest.json")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

LOOKBACK_DAYS = 7
MAX_STORIES_IN_PROMPT = 10
MAX_SUMMARY_LEN = 500  # sanity bound in case Gemini ignores the length ask


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def recent_story_titles():
    stories = load_json(NEWS_JSON_PATH, [])
    cutoff = (datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    recent = [s for s in stories if s.get("date", "") >= cutoff]
    recent.sort(key=lambda s: s.get("date", ""), reverse=True)
    return [s["title"] for s in recent[:MAX_STORIES_IN_PROMPT] if s.get("title")]


def momentum_shift_summary():
    """One-line description of how the #1 leaderboard spot changed vs.
    the previous recorded week, or None if there isn't a previous week to
    compare against yet (e.g. the first couple of runs after
    momentum_history.json started being written)."""
    history = load_json(MOMENTUM_HISTORY_JSON_PATH, [])
    if len(history) < 2:
        return None
    current = sorted(history[-1]["tools"], key=lambda t: t["rank"])
    previous = sorted(history[-2]["tools"], key=lambda t: t["rank"])
    if not current or not previous:
        return None
    if current[0]["name"] != previous[0]["name"]:
        return f"{current[0]['name']} overtook {previous[0]['name']} for the #1 momentum spot this week."
    return f"{current[0]['name']} held the #1 momentum spot for another week."


def build_prompt(titles, shift_summary):
    lines = [
        "You are writing a short editorial digest for a news site that "
        "tracks AI-assisted coding tools (GitHub Copilot, Claude Code, "
        "Cursor, Codex, and the broader \"vibe coding\" trend). Based on "
        "this week's headlines and leaderboard movement below, write a "
        "2-3 sentence summary (under 60 words total) of the dominant "
        "theme this week. Plain prose, no markdown, no restating the "
        "leaderboard line verbatim - just the summary itself.\n",
    ]
    if shift_summary:
        lines.append(f"Leaderboard: {shift_summary}\n")
    lines.append("Headlines this week:")
    lines.extend(f"- {t}" for t in titles)
    return "\n".join(lines)


def call_gemini(prompt):
    resp = requests.post(
        GEMINI_API_URL,
        params={"key": GEMINI_API_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=20,
    )
    if resp.status_code != 200:
        print(f"  WARNING: Gemini digest request failed ({resp.status_code}): {resp.text[:200]}")
        return None
    try:
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        print(f"  WARNING: unexpected Gemini digest response shape: {e}")
        return None
    return text.strip()


def main():
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set - skipping digest (leaving any existing data/digest.json as-is).")
        return

    titles = recent_story_titles()
    if not titles:
        print("No recent stories to summarize - skipping digest (leaving any existing data/digest.json as-is).")
        return

    prompt = build_prompt(titles, momentum_shift_summary())

    try:
        summary = call_gemini(prompt)
    except Exception as e:
        print(f"  WARNING: Gemini digest call errored: {e}")
        summary = None

    if not summary:
        print("No usable digest from Gemini this run - leaving any existing data/digest.json as-is.")
        return

    summary = summary[:MAX_SUMMARY_LEN]
    with open(DIGEST_JSON_PATH, "w") as f:
        json.dump({"date": datetime.date.today().isoformat(), "summary": summary}, f, indent=2)
    print(f"Wrote weekly digest to {DIGEST_JSON_PATH}: {summary}")


if __name__ == "__main__":
    main()
