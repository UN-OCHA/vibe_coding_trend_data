# Vibecode Weekly Reporting

A GitHub Pages site tracking vibe coding trends: weekly momentum data
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
  -> scripts/fetch_youtube.py                     -> scripts/compute_momentum.py
  -> scripts/generate_digest.py (optional)        -> writes data/*.csv, data/momentum.json,
  -> writes data/news.json, data/youtube.json        data/momentum_history.json, data/status.json
  -> writes/updates data/status.json,             -> commits + pushes
     data/digest.json (optional)
  -> commits + pushes
                    |                                       |
                    +-------------------+-------------------+
                                        v
                          index.html / leaderboard.html
                        (fetches the JSON/CSV directly, no build step)
                                        |
                                        v
                                   GitHub Pages
```

## Repo layout

- `index.html`, `leaderboard.html` — the site
- `assets/` — shared CSS/JS (`style.css`, `app.js`, `bump-chart.js`)
- `data/` — the CSVs/JSON both workflows write to, and what the site reads
- `scripts/` — the five Python scripts (trends, news, YouTube, momentum, digest)
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

## Momentum score

Blends three normalized signals per tool — GitHub growth (40%), Hacker News
growth (30%), Trends interest (30%) — into a single weekly score. The exact
weighting is a first-pass judgment call; see the note in
`scripts/compute_momentum.py` and revisit it once there's more history.

Not every tool gets all three signals. Cursor has no Trends coverage
("Cursor" is too generic a search term to track cleanly) and falls back to
the average of the other tools' Trends values for that third. Replit Agent,
Devin, and Lovable have no GitHub signal at all - none of them are tools
people build a public GitHub ecosystem of extensions/example repos around
the way an IDE or CLI tool is, so a repo count would be thin (Replit
Agent/Lovable - usage mostly stays on the vendor's own hosted platform) or
actively misleading (Devin - "devin" is also just a common first name).
Rather than fake a number for a signal nobody's actually measuring, those
tools skip that term and reweight to 50% Hacker News + 50% Trends.

## Adding a tool to the leaderboard

Edit the `TOOLS` dict at the top of `scripts/compute_momentum.py` — map a
display name to the matching metric names already being tracked in the two
CSVs. Set `"github"` or `"trends"` to `None` if that signal genuinely isn't
trackable for this tool (see "Momentum score" above) - `"hn"` is the one
every tool is expected to have, since Hacker News needs no topic tag or
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

- `data/momentum_history.json` only goes back as far as the first run
  after it was added (see `save_history_entry()` in
  `compute_momentum.py`) — the leaderboard's bump chart has no rank data
  for any week before that and says so in its caption rather than
  guessing.
- The humanitarian-relevance flag is derived per *article/video* from its
  own title (`is_humanitarian_relevant()` in `fetch_news.py` /
  `fetch_youtube.py`), not set once per source — see
  `docs/GOOGLE_SHEET_SCHEMA.md` for the reasoning. Tune the keyword list
  in those scripts, not the Sheet.
- `data/news.json` ships with a handful of placeholder rows so the site
  isn't empty on first load — delete them once the daily workflow has run
  for real.
