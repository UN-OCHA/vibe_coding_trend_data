"""
Computes each tracked tool's weekly growth signals from the existing
trends CSVs and writes data/signals.json for the site to read directly.

This used to blend three signals into one "momentum score" and rank tools
by it. That's gone - after several sessions spent patching the score's
trustworthiness (an off-schedule run distorting growth math, Cursor's
missing Trends coverage needing a fallback, three tools needing their
GitHub term skipped and the weights redistributed just to avoid lying
about them), the conclusion was that combining three narrow, noisy
proxies - GitHub topic-tag counts, Hacker News comment volume on one
forum, and search interest via an unofficial third-party proxy with a
confirmed history of silently missing data points - into a single
number never actually produced something *more* accurate. It produced
something *harder to audit*: a reader couldn't tell whether a score
change reflected real momentum or one of those known failure modes, and
the 40/30/30 weighting itself was never validated against anything, just
picked as a starting point.

So this script now writes each signal as its own field, honestly null
where a tool genuinely isn't tracked that way, and does NOT rank tools
against each other. The site shows these side by side and lets a reader
draw their own conclusion, rather than presenting one blended number as
a verdict. See README.md's "Signals tracked" section for more.

Two things still worth knowing about the growth comparison:

- pct_growth() compares the latest snapshot against whichever prior
  snapshot is closest to 7 days before it - NOT just "the previous row".
  The trends workflow allows workflow_dispatch (manual runs) on top of its
  Monday schedule, so an ad hoc run can land a datapoint mid-week; naively
  diffing "the last two rows" in that case compares two snapshots only a
  few days apart instead of a real week-over-week gap. That's especially
  distorting for the Hacker News numbers, which are a rolling "mentions in
  the trailing 7 days from right now" count rather than a fixed calendar
  bucket - a single large thread can swing the count a lot between two
  closely-spaced snapshots as it slides in and out of that window, without
  interest actually having changed over a real week.
- Growth terms are still normalized with a simple clip to [-50%, +50%]
  for display purposes (see normalize_growth()) - kept only in case a
  future chart wants a bounded value; the raw *_growth_pct fields written
  below are the real, unclipped percentages.

A tool can be missing GitHub coverage (Replit Agent, Devin, Lovable - not
tools people build a public GitHub ecosystem of extensions/example repos
around), Trends coverage (Cursor - "Cursor" is too generic a search term
to track cleanly), or VS Code Marketplace coverage (only tools that ship
an actual VS Code extension have one - Cursor and Windsurf are standalone
forked editors, not extensions; Replit Agent, Devin, and Lovable are
browser-only) - every tracked tool needs at least a real Hacker News
signal, since that's the one metric every tool here gets by default (no
GitHub topic tag, Trends term, or Marketplace listing to configure first).
VS Code installs is the one signal here that's a direct usage count
rather than a proxy for one - see fetch_trends.py's
fetch_vscode_marketplace_installs().

A Reddit signal was tried and removed again - see fetch_trends.py's
module docstring for why (Reddit's API access policy, not a data-quality
problem).

Run this after fetch_trends.py, on the same weekly schedule.
"""

import csv
import datetime
import json
import os
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
COUNTS_CSV_PATH = os.path.join(DATA_DIR, "counts_trends.csv")
INTEREST_CSV_PATH = os.path.join(DATA_DIR, "interest_trends.csv")
SIGNALS_JSON_PATH = os.path.join(DATA_DIR, "signals.json")
STATUS_JSON_PATH = os.path.join(DATA_DIR, "status.json")

# Maps a display name to the metric-name fragments used across both CSVs.
# Edit this dict (not the CSVs) to add a tool to the site. "github",
# "trends", and "vscode" may each be None if that signal genuinely isn't
# trackable for a tool (see the module docstring) - "hn" is the one metric
# every tool here is expected to have.
TOOLS = {
    "Claude Code": {"github": "repo_count_claude-code", "hn": "claude_code", "trends": "interest_claude_code", "vscode": "vscode_installs_claude_code"},
    "Codex": {"github": "repo_count_codex", "hn": "chatgpt_codex", "trends": "interest_chatgpt_codex", "vscode": "vscode_installs_codex"},
    "Cursor": {"github": "repo_count_cursor-ide", "hn": "cursor_ai", "trends": None, "vscode": None},
    "GitHub Copilot": {"github": "repo_count_github-copilot", "hn": "github_copilot", "trends": "interest_github_copilot", "vscode": "vscode_installs_github_copilot"},
    "Windsurf": {"github": "repo_count_windsurf-ide", "hn": "windsurf_editor", "trends": "interest_windsurf_editor", "vscode": None},
    # No "github" for these three - see the module docstring. No "vscode"
    # for any of Cursor/Windsurf/Replit Agent/Devin/Lovable either - see
    # VSCODE_EXTENSIONS in fetch_trends.py.
    "Replit Agent": {"github": None, "hn": "replit_agent", "trends": "interest_replit_agent", "vscode": None},
    "Devin": {"github": None, "hn": "devin_ai", "trends": "interest_devin_ai", "vscode": None},
    "Lovable": {"github": None, "hn": "lovable_ai", "trends": "interest_lovable_ai", "vscode": None},
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
    """Week-over-week growth: latest point vs. whichever earlier point is
    closest to 7 days before it - not just "the previous row". See the
    module docstring for why. Returns None (not 0.0) if there's fewer
    than 2 points, since "no growth" and "no data to compute growth from"
    are different things and shouldn't look the same on the site."""
    if not metric:
        return None
    points = series.get(metric, [])
    if len(points) < 2:
        return None
    latest_date_str, latest = points[-1]
    latest_date = datetime.date.fromisoformat(latest_date_str)
    target_date = latest_date - datetime.timedelta(days=7)
    prev_date_str, prev = min(
        points[:-1],
        key=lambda p: abs((datetime.date.fromisoformat(p[0]) - target_date).days),
    )
    if prev == 0:
        return None
    return (latest - prev) / prev


def normalize_growth(pct):
    """Clip to [-50%, +50%] and map onto [0, 1]. Not used to compute a
    score anymore - kept as a small utility in case a future chart wants
    a bounded value; signals.json stores the real, unclipped percentage."""
    clipped = max(-0.5, min(0.5, pct))
    return (clipped + 0.5) / 1.0


def latest_value(series, metric):
    if not metric:
        return None
    points = series.get(metric, [])
    return points[-1][1] if points else None


def update_status():
    """Records today's date as the last time signals were recomputed, so
    the site can show an honest "as of" freshness indicator instead of
    leaving visitors to guess. Duplicated in fetch_news.py / fetch_youtube.py
    rather than shared - see this codebase's self-contained-scripts
    convention (module docstrings)."""
    status = {}
    if os.path.exists(STATUS_JSON_PATH):
        with open(STATUS_JSON_PATH) as f:
            status = json.load(f)
    status["trends"] = datetime.date.today().isoformat()
    with open(STATUS_JSON_PATH, "w") as f:
        json.dump(status, f, indent=2)


def main():
    counts = load_series(COUNTS_CSV_PATH)
    interest = load_series(INTEREST_CSV_PATH)

    results = []
    for name, metrics in TOOLS.items():
        github_growth = pct_growth(counts, metrics["github"])
        hn_growth = pct_growth(counts, f"weekly_comments_{metrics['hn']}")
        trends_value = latest_value(interest, metrics["trends"])
        vscode_growth = pct_growth(counts, metrics["vscode"])

        results.append({
            "name": name,
            "github_repo_count": latest_value(counts, metrics["github"]),
            "github_growth_pct": round(github_growth * 100, 1) if github_growth is not None else None,
            "hn_comments": latest_value(counts, f"weekly_comments_{metrics['hn']}"),
            "hn_growth_pct": round(hn_growth * 100, 1) if hn_growth is not None else None,
            "trends_interest": trends_value,
            "vscode_installs": latest_value(counts, metrics["vscode"]),
            "vscode_growth_pct": round(vscode_growth * 100, 1) if vscode_growth is not None else None,
        })

    with open(SIGNALS_JSON_PATH, "w") as f:
        json.dump(results, f, indent=2)
    update_status()

    print(f"Wrote signals for {len(results)} tool(s) to {SIGNALS_JSON_PATH}.")
    for r in results:
        gh = f"{r['github_growth_pct']}%" if r['github_growth_pct'] is not None else "n/a"
        hn = f"{r['hn_growth_pct']}%" if r['hn_growth_pct'] is not None else "n/a"
        ti = r['trends_interest'] if r['trends_interest'] is not None else "n/a"
        vs = f"{r['vscode_installs']:,.0f}" if r['vscode_installs'] is not None else "n/a"
        print(f"  {r['name']}: GitHub {gh}, HN {hn}, Trends {ti}, VS Code installs {vs}")


if __name__ == "__main__":
    main()
