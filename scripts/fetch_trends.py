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
  4. VS Code       - install count per extension, via the Marketplace's
     Marketplace     Extension Gallery API (marketplace.visualstudio.com).
                     Unlike the other three, this is a direct usage count,
                     not a proxy for one - the tradeoff is that only tools
                     shipping an actual VS Code extension have one at all
                     (see VSCODE_EXTENSIONS below). No API key needed, but
                     it's the same undocumented-for-third-party-use endpoint
                     VS Code's own client calls, not an official public API -
                     see fetch_vscode_marketplace_installs() for the same
                     kind of "inferred, not documented" caveat as Trends.
  5. Reddit        - post mention counts per search term, past 7 days
                     (reddit.com/search.json, unauthenticated). This is the
                     signal that closes the gap GitHub/VS Code leave open:
                     it's the second metric (after Hacker News) that every
                     tracked tool gets, including the four with no public
                     GitHub ecosystem or VS Code extension. Two caveats
                     worth knowing, both covered in fetch_reddit_mentions():
                     unauthenticated requests to reddit.com are commonly
                     rate-limited or blocked outright from data-center IPs
                     (GitHub Actions runners included) - treat this as at
                     least as unreliable as the Trends signal, maybe more -
                     and the count is capped at one page (100 results),
                     unlike HN's true total, so it plateaus instead of
                     distinguishing "busy week" from "huge week" past that
                     cap.

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

# "windsurf-ide" (not bare "windsurf") for the same reason "cursor-ide" isn't
# bare "cursor" - the word alone collides with an unrelated real thing (here,
# the windsurfing sport) badly enough that a GitHub topic tag built on it
# would be noisy. Same reasoning behind "devin ai" and "lovable ai" below
# rather than bare "devin"/"lovable" - both are also ordinary words/names.
# Replit Agent, Devin, and Lovable have no GITHUB_TOPICS entry at all: unlike
# the other five, they're not tools people build a public GitHub ecosystem of
# extensions/configs/example repos around (Replit/Lovable projects mostly
# live on those platforms' own hosting, not pushed to GitHub with a
# meaningful topic tag), so a repo count for them would be thin at best and
# actively misleading at worst - see compute_signals.py's TOOLS dict, which
# skips the GitHub signal for these three rather than faking one.
GITHUB_TOPICS = ["vibe-coding", "github-copilot", "claude-code", "codex", "cursor-ide", "windsurf-ide"]
HN_TERMS = [
    "vibe coding", "github copilot", "claude code", "chatgpt codex", "cursor ai",
    "windsurf editor", "replit agent", "devin ai", "lovable ai",
]
# 8 terms now (was 4) - still comfortably inside the Trends MCP free tier's
# 100/month cap on the normal weekly schedule (8/week * ~4.3 weeks =~ 34/month),
# but leaves less slack for extra manual runs than before - see the README.
TRENDS_TERMS = [
    "vibe coding", "github copilot", "claude code", "chatgpt codex",
    "windsurf editor", "replit agent", "devin ai", "lovable ai",
]  # Cursor deliberately excluded - "cursor" alone is too generic to track cleanly even qualified

# Deliberately the exact same phrases as HN_TERMS - Reddit's search doesn't
# need different disambiguation than HN's does, and keeping the two lists
# identical means compute_signals.py's TOOLS dict can point both signals at
# the same underlying term per tool. Kept as its own constant (not literally
# "= HN_TERMS") so the two can diverge later without it being surprising.
REDDIT_TERMS = [
    "vibe coding", "github copilot", "claude code", "chatgpt codex", "cursor ai",
    "windsurf editor", "replit agent", "devin ai", "lovable ai",
]

# Maps a display name to its exact Marketplace item ID (the "itemName="
# value in a marketplace.visualstudio.com/items?itemName=... URL, i.e.
# "Publisher.extension-name"). ONLY "GitHub Copilot" has been checked
# against a real, well-known listing - the rest are a best effort, since
# this sandbox has no live internet access to open the Marketplace and
# confirm them. That's a safe kind of wrong, not a misleading one: a
# mistaken ID just returns zero matching extensions (handled as "not
# found" below), not a real count attributed to the wrong product - but
# double-check each of these against the live Marketplace before trusting
# the numbers. Cursor and Windsurf aren't here at all: both are standalone
# forked editors, not something installed as a VS Code extension, so
# there's nothing to look up for them. Replit Agent, Devin, and Lovable
# are browser-only hosted platforms - same reasoning.
VSCODE_EXTENSIONS = {
    "GitHub Copilot": "GitHub.copilot",
    "Claude Code": "Anthropic.claude-code",  # UNVERIFIED - confirm the exact ID
    "Codex": "openai.chatgpt",  # UNVERIFIED - confirm the exact ID
}

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
# 4. VS Code Marketplace - install count per extension -> counts_trends.csv
# ---------------------------------------------------------------------------

def fetch_vscode_marketplace_installs():
    print("Fetching VS Code Marketplace install counts...")
    url = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json;api-version=3.0-preview.1",
    }

    for tool_name, extension_id in VSCODE_EXTENSIONS.items():
        body = {
            "filters": [{"criteria": [{"filterType": 7, "value": extension_id}]}],  # 7 = exact extension name
            "flags": 914,  # includes install/rating statistics in the response
        }
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
        except Exception as e:
            print(f"  WARNING: request failed for '{extension_id}': {e}")
            time.sleep(1)
            continue
        if resp.status_code != 200:
            print(f"  WARNING: Marketplace API returned {resp.status_code} for '{extension_id}': {resp.text[:200]}")
            time.sleep(1)
            continue

        try:
            extensions = resp.json()["results"][0]["extensions"]
        except (KeyError, IndexError, TypeError) as e:
            print(f"  WARNING: unexpected Marketplace response shape for '{extension_id}': {e}")
            time.sleep(1)
            continue

        if not extensions:
            print(f"  WARNING: no extension found for '{extension_id}' - check this ID against the live Marketplace listing")
            time.sleep(1)
            continue

        stats = extensions[0].get("statistics", [])
        install_count = next((s["value"] for s in stats if s.get("statisticName") == "install"), None)
        if install_count is None:
            print(f"  WARNING: no install-count statistic in response for '{extension_id}'")
            time.sleep(1)
            continue

        metric_name = f"vscode_installs_{tool_name.lower().replace(' ', '_')}"
        stage_row(COUNTS_CSV_PATH, "vscode_marketplace", metric_name, int(install_count))
        time.sleep(1)


# ---------------------------------------------------------------------------
# 5. Reddit - post mention counts per term, last 7 days -> counts_trends.csv
# ---------------------------------------------------------------------------

# A descriptive, honest User-Agent, as Reddit's API guidance asks for -
# doesn't avoid the rate-limiting/blocking risk described in the module
# docstring, but an unlabeled default requests User-Agent gets blocked even
# more readily.
REDDIT_HEADERS = {"User-Agent": "vibecode-weekly-trends-bot/1.0 (github.com/UN-OCHA/vibe_coding_trend_data)"}


def fetch_reddit_mentions():
    print("Fetching Reddit mention counts...")
    url = "https://www.reddit.com/search.json"

    for term in REDDIT_TERMS:
        metric_name = term.replace(" ", "_")
        # t=week asks Reddit's own search to restrict to the past 7 days,
        # same window HN and Trends use - no client-side date filtering
        # needed like fetch_hn_mentions() does. limit=100 is the practical
        # ceiling for a single unauthenticated request; see the module
        # docstring for why that's a real cap, not just a safety margin.
        params = {"q": term, "sort": "new", "t": "week", "limit": 100}
        try:
            resp = requests.get(url, headers=REDDIT_HEADERS, params=params, timeout=30)
        except Exception as e:
            print(f"  WARNING: request failed for '{term}': {e}")
            time.sleep(2)
            continue
        if resp.status_code != 200:
            print(f"  WARNING: Reddit returned {resp.status_code} for '{term}' - this commonly means "
                  f"reddit.com rate-limited or blocked this request rather than the query itself being "
                  f"wrong (see the module docstring): {resp.text[:200]}")
            time.sleep(2)
            continue
        try:
            children = resp.json()["data"]["children"]
        except (KeyError, TypeError, ValueError) as e:
            # A block/CAPTCHA page returns HTML or a differently-shaped
            # JSON body, not the search listing - .json() itself can raise
            # here too (ValueError covers requests' JSONDecodeError).
            print(f"  WARNING: unexpected Reddit response shape for '{term}' (often means a block page instead of real results): {e}")
            time.sleep(2)
            continue

        stage_row(COUNTS_CSV_PATH, "reddit", f"weekly_mentions_{metric_name}", len(children))
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
    fetch_vscode_marketplace_installs()
    fetch_reddit_mentions()
    flush_staged()
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
