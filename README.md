# Vibecoding trends dashboard - data pipeline

Weekly, automated collection of vibecoding-adoption signals across GitHub,
Hacker News, and Google Trends, feeding a Power BI dashboard.

## Two output files, not one

Data is split into two CSVs because GitHub/Hacker News produce **raw
counts** while Google Trends produces a **0-100 relative index** -
different units that shouldn't be plotted on the same axis without
normalization.

- `data/counts_trends.csv` - GitHub repo counts + Hacker News mentions
- `data/interest_trends.csv` - Google Trends search interest index

Both share the same shape: `date, source, metric, value`.

## How it works

```
GitHub Actions (weekly, cron)
  -> runs scripts/fetch_trends.py
  -> appends new rows to BOTH csv files
  -> commits + pushes both back to this repo
                    |
                    v
Power BI Service (weekly scheduled refresh)
  -> reads BOTH csvs via the GitHub Contents API (two separate queries)
  -> dashboard updates automatically
```

## What each source actually measures

**GitHub** - for each configured topic tag, how many repos are labeled
with that exact topic. Official API, no auth required (though a token
raises the rate limit substantially).

**Hacker News** - for each configured search term, how many stories and
how many comments mentioned that term in the last 7 days, tracked as
separate metrics. Uses the official Algolia HN Search API - no auth, no
approval process, true total match count (`nbHits`), no artificial cap.

**Google Trends** - relative search interest (0-100, where 100 = that
term's own peak). Not a count of anything - an index. Fetched via Trends
MCP (see caveat below), NOT the `pytrends`/`pytrends-modern` libraries -
both were tested against this exact pipeline running on real GitHub
Actions infrastructure and both reliably got `429`-blocked by Google.
GitHub's shared runner IP ranges appear to already be flagged by Google's
anti-scraping systems, and no amount of retry/backoff logic fixed it.

## ⚠️ Important caveat: Google Trends' data source is a third-party vendor

Unlike GitHub and Hacker News (both official, stable, platform-run APIs),
the Google Trends numbers in this pipeline come from **Trends MCP**
(`trendsmcp.ai`), an **unofficial, third-party commercial proxy service** -
not a Google product, and not affiliated with Google or Anthropic. A few
things worth knowing before relying on it long-term:

- **It is the least stable link in this entire pipeline.** GitHub and HN
  are run by large, established platforms with public APIs unlikely to
  disappear. Trends MCP is a much smaller, newer commercial operator - its
  free tier, pricing, or existence could change with little notice.
- **Free tier limits: 100 requests/month, capped at 20/day.** This is why
  `TRENDS_TERMS` is deliberately kept to just 4 terms - each weekly run
  uses about 4 requests, leaving comfortable headroom, but don't expand
  this list significantly without checking the math against the cap.
- **If this stops working**, check `trendsmcp.ai` directly for status
  before assuming the script is broken - it may be a vendor-side change.
  Fallback options if it needs replacing again: a manual weekly Google
  Trends CSV export (30 seconds, drop into the repo), or re-evaluating
  paid alternatives (SerpApi, Apify's Trends actor) if budget allows.
- **The exact API response format was inferred from partial public
  documentation**, not a fully confirmed spec - if `fetch_google_trends()`
  starts throwing "unexpected response shape" warnings, check
  `trendsmcp.ai/docs` for what may have changed and adjust the parsing
  logic in the script accordingly.

Given this, treat the Google Trends numbers on the dashboard as the most
likely of the three sources to have gaps or need future maintenance -
GitHub and Hacker News are meaningfully more dependable.

## Adding or changing what's tracked

**Adding a search term/keyword to an existing source** - just add a string
to the relevant list at the top of `fetch_trends.py` (`GITHUB_TOPICS`,
`HN_TERMS`, or `TRENDS_TERMS`), commit, push. No other changes needed.
Two things to check first:
- GitHub topics must be real, exact topic slugs - verify at
  `github.com/topics/<name>` first. A made-up one just silently returns 0.
- Trends MCP is rate-capped (20/day, 100/month) - each added term is one
  more request per run. Don't expand that list without checking the math.

**Adding an entirely new source (a different site/API)** - more involved,
follow the pattern of the existing fetch functions:
1. Write a new `fetch_<source>_something()` function that calls the API and
   calls `append_row(path, source_name, metric_name, value)` per result
2. Decide which CSV it belongs in - `counts_trends.csv` for raw counts,
   `interest_trends.csv` for an index/percentage, or a new third file if
   it's a genuinely different unit from both
3. Add the function call into `main()`
4. If it needs credentials: read them via `os.environ.get(...)`, add the
   env var to `.github/workflows/update-data.yml`, and add the actual
   secret value under the repo's Settings -> Secrets and variables -> Actions
5. Update the "What each source actually measures" section so the next
   person knows what the new numbers mean

## Step-by-step setup

### 1. Push the project into your repo
Copy in `.github/workflows/update-data.yml`, `data/counts_trends.csv`,
`data/interest_trends.csv`, `scripts/fetch_trends.py`,
`scripts/requirements.txt`, this README - into your repo root (not as a
subfolder).

No credentials needed for GitHub or Hacker News. For Google Trends:

### 2. Register for a Trends MCP API key
Go to https://www.trendsmcp.ai/, sign up with an email, get a free API key
(no credit card required). Free tier: 100 requests/month, 20/day.

### 3. Add repo secrets
Settings -> Secrets and variables -> Actions -> New repository secret:
- `TRENDS_MCP_API_KEY`

(`GITHUB_TOKEN` needs no setup - Actions provides it automatically.)

### 4. Test the workflow manually
Actions tab -> "Update vibecoding trends data" -> Run workflow. Check the
logs for each of the three fetch steps, and confirm both CSVs got new rows.

### 5. Let it run weekly
Cron is set to Monday 06:00 UTC - no further action needed.

### 6. Connect Power BI - TWO separate Web API connections
Repeat the connection process once per file:

- Get Data -> **Web API**
- URL (base only): `https://api.github.com`
- Authentication kind: Anonymous
- Click Next, then open **Advanced Editor** and use:

```m
let
    Source = Web.Contents("https://api.github.com", [
        RelativePath = "repos/<owner>/<repo>/contents/data/counts_trends.csv",
        Headers = [
            Authorization = "Bearer <your fine-grained PAT>",
            Accept = "application/vnd.github.raw"
        ]
    ]),
    #"Imported CSV" = Csv.Document(Source, [Delimiter=",", Columns=4, Encoding=65001, QuoteStyle=QuoteStyle.None]),
    #"Promoted Headers" = Table.PromoteHeaders(#"Imported CSV", [PromoteAllScalars=true])
in
    #"Promoted Headers"
```

Repeat with `RelativePath` pointing at `data/interest_trends.csv` for the
second query. Name the two queries something clear (e.g. `CountsTrends` and
`InterestTrends`) in the Queries pane.

### 7. Shape both in Power Query
Set `date` to Date type, `value` to Whole Number, on both queries
independently.

### 8. Build visuals
Keep the two queries as separate tables (don't merge/append them - the
units don't match). Build one visual set for counts, one for the interest
index, using `source`/`metric` slicers on each.

### 9. Publish and schedule refresh
Shared workspace, weekly scheduled refresh (Pro license required).

## Configuration

Edit the top of `scripts/fetch_trends.py`:
- `GITHUB_TOPICS` - GitHub topic tags to count repos for
- `HN_TERMS` - search phrases to count HN story/comment mentions for
- `TRENDS_TERMS` - search phrases for Trends MCP (keep short - rate cap)

## Handoff notes (for whoever inherits this)

- **GitHub Actions write side**: uses the auto-provided `GITHUB_TOKEN`, no
  rotation ever needed. Hacker News needs no credentials at all either.
- **Trends MCP API key**: tied to whoever registered it. If that access is
  lost, register a new free key and update the repo secret - same process
  as the original setup.
- **Power BI read side (PAT)**: tied to whoever generated it. Update both
  Power Query connections (counts + interest) if it's rotated.
- Transferring the repo to an org: Settings -> Transfer ownership. No
  secrets transfer automatically with repo ownership - re-add
  `TRENDS_MCP_API_KEY` under the new org repo after transfer.
- **Re-read the Google Trends caveat above periodically** - this is the
  one part of the pipeline most likely to need attention over time.
