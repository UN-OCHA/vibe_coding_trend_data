"""
Computes the weekly "momentum score" leaderboard from the existing trends
CSVs and writes data/momentum.json for the site to read directly.

The score blends three signals per tool, each normalized onto a comparable
scale before combining (raw repo counts and raw HN comment counts live on
wildly different scales, so summing them directly would let GitHub's
numbers drown everything else out):

  1. GitHub repo count, week-over-week % growth
  2. Hacker News weekly comment count, week-over-week % growth
  3. Google Trends interest, latest value (already 0-100)

score = 40% * normalized(github growth) + 30% * normalized(hn growth)
        + 30% * (trends interest / 100)

Growth terms are normalized with a simple clip to [-50%, +50%] mapped onto
[0, 1], so one noisy outlier week can't dominate the score. This is a
starting formula, not a final one - the weighting is a judgment call and
should be revisited once there's more than five weeks of real data to
sanity-check it against.

Run this after fetch_trends.py, on the same weekly schedule.
"""

import csv
import json
import os
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
COUNTS_CSV_PATH = os.path.join(DATA_DIR, "counts_trends.csv")
INTEREST_CSV_PATH = os.path.join(DATA_DIR, "interest_trends.csv")
MOMENTUM_JSON_PATH = os.path.join(DATA_DIR, "momentum.json")

# Maps a display name to the metric-name fragments used across both CSVs.
# Edit this dict (not the CSVs) to add a tool to the leaderboard.
TOOLS = {
    "Claude Code": {"github": "repo_count_claude-code", "hn": "claude_code", "trends": "interest_claude_code"},
    "Codex": {"github": "repo_count_codex", "hn": "chatgpt_codex", "trends": "interest_chatgpt_codex"},
    "Cursor": {"github": "repo_count_cursor-ide", "hn": "cursor_ai", "trends": None},
    "GitHub Copilot": {"github": "repo_count_github-copilot", "hn": "github_copilot", "trends": "interest_github_copilot"},
}


def load_series(path):
    """Returns {metric: [(date, value), ...]} sorted by date."""
    series = defaultdict(list)
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            series[row["metric"]].append((row["date"], float(row["value"])))
    for metric in series:
        series[metric].sort(key=lambda x: x[0])
    return series


def pct_growth(series, metric):
    points = series.get(metric, [])
    if len(points) < 2:
        return 0.0
    prev, latest = points[-2][1], points[-1][1]
    if prev == 0:
        return 0.0
    return (latest - prev) / prev


def normalize_growth(pct):
    """Clip to [-50%, +50%] and map onto [0, 1]."""
    clipped = max(-0.5, min(0.5, pct))
    return (clipped + 0.5) / 1.0


def latest_value(series, metric):
    if not metric:
        return None
    points = series.get(metric, [])
    return points[-1][1] if points else None


def main():
    counts = load_series(COUNTS_CSV_PATH)
    interest = load_series(INTEREST_CSV_PATH)

    results = []
    for name, metrics in TOOLS.items():
        github_growth = pct_growth(counts, metrics["github"])
        hn_growth = pct_growth(counts, f"weekly_comments_{metrics['hn']}")
        trends_value = latest_value(interest, metrics["trends"]) if metrics["trends"] else None

        trends_component = (trends_value / 100) if trends_value is not None else 0.5  # neutral if untracked

        score = (
            0.4 * normalize_growth(github_growth)
            + 0.3 * normalize_growth(hn_growth)
            + 0.3 * trends_component
        ) * 100

        results.append({
            "name": name,
            "score": round(score, 1),
            "github_repo_count": latest_value(counts, metrics["github"]),
            "github_growth_pct": round(github_growth * 100, 1),
            "hn_comments": latest_value(counts, f"weekly_comments_{metrics['hn']}"),
            "hn_growth_pct": round(hn_growth * 100, 1),
            "trends_interest": trends_value,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i

    with open(MOMENTUM_JSON_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Wrote momentum scores for {len(results)} tool(s) to {MOMENTUM_JSON_PATH}.")
    for r in results:
        print(f"  #{r['rank']} {r['name']}: {r['score']}")


if __name__ == "__main__":
    main()
