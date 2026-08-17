"""
Weekly auto-written digest - a short editorial summary of the week's
dominant story and any notable momentum leaderboard shift, written by
Gemini and read directly by index.html.

Despite being "weekly," this is meant to run daily, alongside the news
pipeline (fetch_news.py / fetch_youtube.py) - it only needs whatever's
already on disk (data/news.json, data/momentum_history.json), not a fresh
trends/momentum run, so it doesn't belong gated behind that workflow.
What keeps it "weekly" instead of regenerating (and re-billing a Gemini
call) every single day is self-imposed: main() checks the existing
digest's own "date" field and skips regenerating if it's less than
MIN_DAYS_BETWEEN_DIGESTS old. Running this daily just means a new digest
is *possible* every day; in practice it only actually writes one roughly
once a week, and there's no dependency on which workflow last touched
momentum data.

This is entirely optional and additive. If GEMINI_API_KEY isn't set, or
the call fails, comes back empty, or comes back malformed, this script
leaves any existing data/digest.json untouched rather than overwriting it
with something worse or deleting it - a stale-but-real digest is still
useful, and its own "date" field already makes that staleness visible on
the site (see the freshness indicator work in fetch_news.py /
compute_momentum.py).

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
MIN_DAYS_BETWEEN_DIGESTS = 6  # keeps a script invoked daily behaving weekly


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


def days_since_last_digest():
    """Age in days of the existing digest, or None if there isn't one yet
    (or its date field is unreadable) - both treated as "go ahead and
    write one" by the caller."""
    existing = load_json(DIGEST_JSON_PATH, None)
    if not existing or not existing.get("date"):
        return None
    try:
        prev_date = datetime.date.fromisoformat(existing["date"])
    except ValueError:
        return None
    return (datetime.date.today() - prev_date).days


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

    age_days = days_since_last_digest()
    if age_days is not None and age_days < MIN_DAYS_BETWEEN_DIGESTS:
        print(f"Last digest is {age_days} day(s) old (< {MIN_DAYS_BETWEEN_DIGESTS}) - this is meant to "
              f"refresh about once a week, so skipping today.")
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
