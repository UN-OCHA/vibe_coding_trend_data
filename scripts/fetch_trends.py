"""
Weekly data collector for the vibecoding trends site.

Writes to TWO separate CSVs, since GitHub/HN produce raw counts while
Google Trends produces a 0-100 relative index - different units that
shouldn't be plotted on the same axis without normalization:

  data/counts_trends.csv   <- GitHub repo counts + Hacker News mentions
  data/interest_trends.csv <- Google Trends search interest (0-100 index)

Sources:
  1. GitHub       - repo count per topic tag (official API)
  2. Hacker News   - story + comment mention counts per search term, last 7
                     days, via the official Algolia HN Search API.
  3. Google Trends - search interest via Trends MCP (api.trendsmcp.ai), a
                     third-party managed proxy. See README for the full
                     reliability caveat.

Idempotency: this script is safe to run more than once on the same day
(e.g. a manual trigger on top of the scheduled run). Before writing, it
checks whether a row already exists for today's date + source + metric,
and overwrites that row in place rather than appending a duplicate.

Configuration lives in the CONFIG block below.
"""

import csv
import datetime
import json
import os
import sys
import time

import requests

# ---------------------------------------------------------------------------
# CONFIG - edit these to change what gets tracked
# ---------------------------------------------------------------------------

GITHUB_TOPICS = ["vibe-coding", "github-copilot", "claude-code", "codex", "cursor-ide"]
HN_TERMS = ["vibe coding", "github copilot", "claude code", "chatgpt codex", "cursor ai"]
TRENDS_TERMS = ["vibe coding", "github copilot", "claude code", "chatgpt codex"]  # kept short - Trends MCP free tier caps at 20 requests/day, 100/month

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
COUNTS_CSV_PATH = os.path.join(DATA_DIR, "counts_trends.csv")
INTEREST_CSV_PATH = os.path.join(DATA_DIR, "interest_trends.csv")
CSV_HEADERS = ["date", "source", "metric", "value"]

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
TRENDS_MCP_API_KEY = os.environ.get("TRENDS_MCP_API_KEY", "")


def today_str():
    return datetime.date.today().isoformat()


def ensure_csv_exists(path):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)


def load_rows(path):
    """Read all existing rows (excluding header) as a list of lists."""
    with open(path, newline="") as f:
        reader = csv.reader(f)
        rows = [r for r in reader if r]
    return rows[0], rows[1:]  # header, body


def write_rows(path, header, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


# In-memory staging: each fetch function stages rows here instead of
# appending straight to disk, so main() can dedup once at the end against
# whatever's already in the file for today.
_staged = {COUNTS_CSV_PATH: [], INTEREST_CSV_PATH: []}


def stage_row(path, source, metric, value):
    _staged[path].append([today_str(), source, metric, str(value)])
    print(f"  staged: {source} | {metric} | {value}")


def flush_staged():
    """Write staged rows to each CSV, replacing any existing row for the
    same (date, source, metric) so re-running the script the same day
    overwrites rather than duplicates."""
    for path, new_rows in _staged.items():
        if not new_rows:
            continue
        header, existing = load_rows(path)
        by_key = {(r[0], r[1], r[2]): r for r in existing}
        for row in new_rows:
            by_key[(row[0], row[1], row[2])] = row
        write_rows(path, header, list(by_key.values()))
        print(f"Flushed {len(new_rows)} row(s) to {path} (idempotent).")


# ---------------------------------------------------------------------------
# 1. GitHub - repo count per topic  -> counts_trends.csv
# ---------------------------------------------------------------------------

def fetch_github_topic_counts():
    print("Fetching GitHub topic counts...")
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    for topic in GITHUB_TOPICS:
        url = "https://api.github.com/search/repositories"
        params = {"q": f"topic:{topic}", "per_page": 1}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
        except Exception as e:
            print(f"  WARNING: request failed for '{topic}': {e}")
            continue
        if resp.status_code != 200:
            print(f"  WARNING: GitHub API returned {resp.status_code} for topic '{topic}': {resp.text[:200]}")
            continue
        total_count = resp.json().get("total_count", 0)
        stage_row(COUNTS_CSV_PATH, "github", f"repo_count_{topic}", total_count)


# ---------------------------------------------------------------------------
# 2. Hacker News - story + comment mentions per term, last 7 days
# ---------------------------------------------------------------------------

def fetch_hn_mentions():
    print("Fetching Hacker News mention counts...")
    now = datetime.datetime.now(datetime.timezone.utc)
    one_week_ago = now - datetime.timedelta(days=7)
    now_ts = int(now.timestamp())
    week_ago_ts = int(one_week_ago.timestamp())

    for term in HN_TERMS:
        metric_name = term.replace(" ", "_")
        for tag, label in [("story", "stories"), ("comment", "comments")]:
            url = "https://hn.algolia.com/api/v1/search_by_date"
            params = {
                "query": term,
                "tags": tag,
                "numericFilters": f"created_at_i>{week_ago_ts},created_at_i<{now_ts}",
                "hitsPerPage": 1,
            }
            try:
                resp = requests.get(url, params=params, timeout=30)
            except Exception as e:
                print(f"  WARNING: request failed for '{term}' ({label}): {e}")
                time.sleep(1)
                continue
            if resp.status_code != 200:
                print(f"  WARNING: HN Algolia API returned {resp.status_code} for '{term}' ({label}): {resp.text[:200]}")
                time.sleep(1)
                continue
            total_hits = resp.json().get("nbHits", 0)
            stage_row(COUNTS_CSV_PATH, "hackernews", f"weekly_{label}_{metric_name}", total_hits)
            time.sleep(1)


# ---------------------------------------------------------------------------
# 3. Google Trends (via Trends MCP) - search interest per term -> interest_trends.csv
# ---------------------------------------------------------------------------

def fetch_google_trends():
    print("Fetching Google Trends data (via Trends MCP)...")
    if not TRENDS_MCP_API_KEY:
        print("  WARNING: TRENDS_MCP_API_KEY not set, skipping Google Trends fetch.")
        return

    headers = {"Authorization": f"Bearer {TRENDS_MCP_API_KEY}"}

    for term in TRENDS_TERMS:
        body = {
            "mode": "get_time_series",
            "source": "google search",
            "keyword": term,
            "data_mode": "weekly",
        }
        try:
            resp = requests.post("https://api.trendsmcp.ai/api", headers=headers, json=body, timeout=30)
        except Exception as e:
            print(f"  WARNING: Trends MCP request failed for '{term}': {e}")
            time.sleep(2)
            continue

        if resp.status_code != 200:
            print(f"  WARNING: Trends MCP returned {resp.status_code} for '{term}': {resp.text[:200]}")
            time.sleep(2)
            continue

        payload = resp.json()
        if isinstance(payload, dict) and isinstance(payload.get("body"), str):
            try:
                series = json.loads(payload["body"])
            except (json.JSONDecodeError, TypeError) as e:
                print(f"  WARNING: could not parse Trends MCP 'body' field for '{term}': {e}")
                time.sleep(2)
                continue
        elif isinstance(payload, dict):
            series = payload.get("data") or payload.get("results") or payload.get("series")
        else:
            series = payload

        if not series or not isinstance(series, list):
            print(f"  WARNING: unexpected Trends MCP response shape for '{term}': {str(payload)[:200]}")
            time.sleep(2)
            continue

        latest_point = series[-1]
        latest_value = latest_point.get("value")
        if latest_value is None:
            print(f"  WARNING: no 'value' field in latest Trends MCP data point for '{term}': {latest_point}")
            time.sleep(2)
            continue

        stage_row(INTEREST_CSV_PATH, "google_trends", f"interest_{term.replace(' ', '_')}", int(latest_value))
        time.sleep(2)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ensure_csv_exists(COUNTS_CSV_PATH)
    ensure_csv_exists(INTEREST_CSV_PATH)
    fetch_github_topic_counts()
    fetch_hn_mentions()
    fetch_google_trends()
    flush_staged()
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
