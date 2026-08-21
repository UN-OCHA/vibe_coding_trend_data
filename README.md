# Vibecode Weekly Reporting

A GitHub Pages site tracking vibe coding trends: weekly growth signals
(GitHub, Hacker News, Google Trends) plus a daily feed of news and YouTube
videos, sourced from a Google Sheet a non-technical person can edit
directly. No backend — everything renders client-side against static
CSV/JSON files committed by two scheduled GitHub Actions workflows.

## How it fits together

```
Google Sheet (non-technical source/topic config)
        |
        v
GitHub Actions (daily, 05:00 UTC)              GitHub Actions (weekly, Mon 06:00 UTC)
  -> scripts/fetch_news.py                       -> scripts/fetch_trends.py
  -> scripts/fetch_youtube.py                     -> scripts/compute_signals.py
  -> scripts/generate_digest.py (optional)        -> writes data/*.csv, data/signals.json,
  -> writes data/news.json, data/youtube.json        data/status.json
  -> writes/updates data/status.json,             -> commits + pushes
     data/digest.json (optional)
  -> commits + pushes
                    |                                       |
                    +-------------------+-------------------+
                                        v
                          index.html / leaderboard.html / compare.html
                        (fetches the JSON/CSV directly, no build step)
                                        |
                                        v
                                   GitHub Pages
```

## Repo layout

- `index.html`, `leaderboard.html`, `compare.html` — the site
- `assets/` — shared CSS/JS (`style.css`, `app.js`, `trend-chart.js`, `radar-chart.js`, `tool-profiles.js`)
- `data/` — the CSVs/JSON both workflows write to, and what the site reads
- `scripts/` — the five Python scripts (trends, news, YouTube, signals, digest)
- `.github/workflows/` — the two scheduled workflows
- `docs/GOOGLE_SHEET_SCHEMA.md` — the exact columns the Sheet needs

## Non-technical source management

Sources, subtopics, and the humanitarian-relevance flag all live in a
Google Sheet, not in code. See `docs/GOOGLE_SHEET_SCHEMA.md` for setup and
the exact column format. Adding a source is a spreadsheet row; no code
change, no redeploy.

## Required secrets

Set these under Settings → Secrets and variables → Actions:

| Secret | Used by | Notes |
|---|---|---|
| `GITHUB_TOKEN` | weekly workflow | auto-provided, no setup needed |
| `TRENDS_MCP_API_KEY` | weekly workflow | see the Google Trends caveat below |
| `SHEET_CSV_URL` | daily workflow | the published-CSV URL of the sources Sheet |
| `YOUTUBE_API_KEY` | daily workflow | YouTube Data API v3 key, free tier |
| `GEMINI_API_KEY` | daily workflow | optional. Gemini free-tier key - adds an LLM second opinion on top of the keyword-based relevance/category checks in `fetch_news.py` and `fetch_youtube.py` (both run keyword-only if unset, capped at 30 calls/run each - see `MAX_GEMINI_CALLS_PER_RUN`), and powers the auto-written digest in `generate_digest.py`. That script runs daily but self-limits to writing a new digest roughly once a week (`MIN_DAYS_BETWEEN_DIGESTS`); skipped entirely, leaving any prior digest in place, if unset |

## What each data source measures

**GitHub** — repo count per configured topic tag. Official API, no auth
required (a token raises the rate limit).

**Hacker News** — story and comment mentions per search term, last 7 days,
via the official Algolia HN Search API. No auth needed.

**Google Trends** — relative search interest (0–100), via Trends MCP
(`trendsmcp.ai`), an **unofficial third-party proxy**, not a Google
product. Free tier caps at 100 requests/month, 20/day — this is why the
term list stays short. Treat this as the least stable link in the
pipeline; a manual CSV export or a paid alternative (SerpApi, Apify) are
the fallbacks if it breaks. See `scripts/fetch_trends.py` for the parsing
details, since the response schema is inferred, not officially documented.

**News (RSS)** — headline, link, date per configured feed. Feeds only, not
scraping — scraping is fragile and often against a site's terms of service.

**YouTube** — recent videos (last 7 days) per configured search topic,
ranked by views-per-day-since-published as a proxy for "gaining
popularity," since there's no official trending-by-niche endpoint.

## Signals, not a score

This site used to blend GitHub growth, Hacker News growth, and Trends
interest into a single weekly "momentum score" and rank tools by it. That's
gone. After several rounds of patching the score's trustworthiness - an
off-schedule workflow run distorting the growth math, a missing-Trends
tool needing a fallback value, three tools needing their GitHub term
skipped and the weights redistributed just to avoid lying about them - the
conclusion was that combining three narrow, noisy proxies (GitHub
topic-tag counts, comment volume on one forum, search interest via an
unofficial third-party proxy with a confirmed history of silently missing
data points) never made the result more *accurate*. It made it harder to
*audit*: a reader couldn't tell whether a score change reflected real
momentum or one of those known failure modes, and the weighting itself was
never validated against anything, just picked as a starting point.

`scripts/compute_signals.py` now writes each tool's three signals as
separate fields in `data/signals.json` - honestly `null` where a signal
genuinely isn't tracked for that tool - and does not rank tools against
each other. `leaderboard.html` shows them as a sortable table (click a
column to sort by it) instead of a leaderboard; `compare.html`'s radar
chart plots the three signals as three independent axes, not blended into
a fourth "momentum" axis.

Not every tool gets all three signals. Cursor has no Trends coverage
("Cursor" is too generic a search term to track cleanly). Replit Agent,
Devin, and Lovable have no GitHub signal at all - none of them are tools
people build a public GitHub ecosystem of extensions/example repos around
the way an IDE or CLI tool is, so a repo count would be thin (Replit
Agent/Lovable - usage mostly stays on the vendor's own hosted platform) or
actively misleading (Devin - "devin" is also just a common first name). A
missing signal shows as a dash on the site, never a fabricated zero.

## Adding a tool

Edit the `TOOLS` dict at the top of `scripts/compute_signals.py` — map a
display name to the matching metric names already being tracked in the two
CSVs. Set `"github"` or `"trends"` to `None` if that signal genuinely isn't
trackable for this tool (see "Signals, not a score" above) - `"hn"` is the
one every tool is expected to have, since Hacker News needs no topic tag or
Trends term to configure first. If the tool isn't tracked yet, add it to the
`GITHUB_TOPICS`/`HN_TERMS`/`TRENDS_TERMS` lists in `scripts/fetch_trends.py`
first (skip `GITHUB_TOPICS` if you're setting `"github": None`). Also add it
to `assets/tool-profiles.js` (compare.html's hand-curated facts) and to
`TOOL_MATCHERS` in `compare.html` if you want it picked up by the "recent
mentions" count there.

## Hosting

The repo can stay private. Recommended: connect Cloudflare Pages (or
Netlify/Vercel) directly to this repo — works on the free tier without
requiring the repo to be public, and without depending on your org's
GitHub plan. If deploying via GitHub Pages instead, note that private-repo
Pages requires GitHub Team or higher; on Team+ you can keep the repo
private while setting the *published site* to public visibility.

## Known first-pass limitations

- The humanitarian-relevance flag is derived per *article/video* from its
  own title (`is_humanitarian_relevant()` in `fetch_news.py` /
  `fetch_youtube.py`), not set once per source — see
  `docs/GOOGLE_SHEET_SCHEMA.md` for the reasoning. Tune the keyword list
  in those scripts, not the Sheet.
- `data/news.json` ships with a handful of placeholder rows so the site
  isn't empty on first load — delete them once the daily workflow has run
  for real.
