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

### Changing or adding keywords to an EXISTING source

Each source's search terms live in one list at the top of
`scripts/fetch_trends.py`:

```python
GITHUB_TOPICS = ["vibe-coding", "github-copilot", "claude-code", "codex", "cursor-ide"]
HN_TERMS = ["vibe coding", "github copilot", "claude code", "chatgpt codex", "cursor ai"]
TRENDS_TERMS = ["vibe coding", "github copilot", "claude code", "chatgpt codex"]
```

To add or remove a term: edit the relevant list, commit, push. That's the
entire change - no other file needs to be touched, and no new secrets or
functions are needed, since the existing fetch function already loops over
whatever's in the list.

**Before adding a term, check the following per source:**

- **GitHub** (`GITHUB_TOPICS`): must be a real, exact topic slug. Verify it
  exists first by visiting `github.com/topics/<name>` in a browser - if the
  page shows repos, it's real. A made-up or misspelled slug doesn't error,
  it just silently returns a count of 0 forever, which can look like "this
  isn't happening" when really it's "this tag doesn't exist."
- **Hacker News** (`HN_TERMS`): any phrase works, since HN's search matches
  free text rather than a fixed tag list - no need to verify existence
  first. Multi-word phrases should be lowercase, matching the style of
  what's already there, for consistency in the output labels.
- **Google Trends / Trends MCP** (`TRENDS_TERMS`): the free tier is capped
  at 20 requests/day and 100/month. Each term in this list costs one
  request per weekly run. Before adding a term, do the math: (number of
  terms) x (runs per month, currently ~4) must stay under 100. Currently 4
  terms x 4 runs/month = 16 requests/month, well under the cap - but this
  margin shrinks fast if the list grows.

**Removing a term** works the same way in reverse - delete it from the
list, commit, push. Historical data already written to the CSV for that
term stays in the file; it just stops getting new rows going forward.

---

### Adding an ENTIRELY NEW source (a different website/API)

This is a bigger change than editing a list - it means writing a new
Python function and wiring it into three other places. Follow these steps
in order; skipping one is the most common way this breaks.

**Step 1: Confirm the new source actually has a usable API first**

Before writing any code, check that the site has:
- A public API (not just a website you'd have to scrape - scraping is
  fragile, often against a site's terms of service, and specifically
  caused problems earlier in this project's history with Reddit and
  Google Trends)
- Either no authentication required, or a free/self-service way to get an
  API key (an approval-gated process, like Reddit's, is a dealbreaker for
  a pipeline that needs to run unattended - see the Google Trends section
  above for what happened when that assumption turned out to be wrong)
- A way to filter or count results by keyword and, ideally, by date range

**Step 2: Decide which output file the new data belongs in**

- If the new source returns a **raw count** (e.g. "42 posts", "1,200
  repos") -> it belongs in `data/counts_trends.csv`, alongside GitHub and
  Hacker News
- If it returns an **index or percentage** (e.g. "on a 0-100 scale") ->
  it belongs in `data/interest_trends.csv`, alongside Google Trends
- If it's a genuinely different unit from both (e.g. a dollar amount, a
  star rating) -> create a third CSV file rather than forcing it into an
  existing one. Mixing units in one file makes charts misleading.

**Step 3: Write the fetch function**

Add a new function to `fetch_trends.py`, following the shape of the
existing ones (`fetch_github_topic_counts()` is the simplest template to
copy). At minimum it needs to:

```python
def fetch_newsource_mentions():
    print("Fetching <NewSource> data...")

    # If this source needs a credential, check for it and skip gracefully
    # if it's missing - don't let a missing key crash the whole script.
    if not NEWSOURCE_API_KEY:
        print("  WARNING: NEWSOURCE_API_KEY not set, skipping.")
        return

    for term in NEWSOURCE_TERMS:
        try:
            resp = requests.get(
                "https://api.newsource.example.com/search",
                params={"q": term},
                headers={"Authorization": f"Bearer {NEWSOURCE_API_KEY}"},
                timeout=30,
            )
        except Exception as e:
            print(f"  WARNING: request failed for '{term}': {e}")
            time.sleep(2)
            continue

        if resp.status_code != 200:
            print(f"  WARNING: API returned {resp.status_code} for '{term}': {resp.text[:200]}")
            time.sleep(2)
            continue

        value = resp.json().get("count", 0)  # adjust to match the real response shape
        append_row(COUNTS_CSV_PATH, "newsource", f"mentions_{term.replace(' ', '_')}", value)
        time.sleep(1)  # pace requests - don't hammer the API
```

Match the existing error-handling pattern exactly: a failed request should
print a `WARNING:` and move to the next term, never crash the whole
script. One source failing should never stop the others from running -
this is why GitHub, HN, and Trends are all independent in this pipeline.

**Step 4: Add the term list and any credentials to the CONFIG block**

Near the top of the file, alongside `GITHUB_TOPICS` etc.:

```python
NEWSOURCE_TERMS = ["vibe coding", "github copilot"]  # start small, expand later
NEWSOURCE_API_KEY = os.environ.get("NEWSOURCE_API_KEY", "")
```

**Step 5: Call the new function from `main()`**

```python
def main():
    ensure_csv_exists(COUNTS_CSV_PATH)
    ensure_csv_exists(INTEREST_CSV_PATH)
    fetch_github_topic_counts()
    fetch_hn_mentions()
    fetch_google_trends()
    fetch_newsource_mentions()   # <- add this line
    print("Done.")
```

**Step 6: If it needs a credential, wire it through the workflow file**

Edit `.github/workflows/update-data.yml`, adding the new secret to the
existing `env:` block for the "Run data collection script" step:

```yaml
      - name: Run data collection script
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TRENDS_MCP_API_KEY: ${{ secrets.TRENDS_MCP_API_KEY }}
          NEWSOURCE_API_KEY: ${{ secrets.NEWSOURCE_API_KEY }}    # <- add this line
        run: python scripts/fetch_trends.py
```

**Step 7: Register the actual secret value in GitHub**

Repo -> Settings -> Secrets and variables -> Actions -> New repository
secret. Name must match exactly what's referenced in the YAML
(`NEWSOURCE_API_KEY` in this example) - a mismatch here fails silently,
with the script just treating the key as missing and skipping the source.

**Step 8: Test locally if possible, then test via Actions**

If you can run Python locally, run `python scripts/fetch_trends.py` with
the new env var set, and confirm it writes a row without errors before
pushing. Either way, after pushing, go to the Actions tab and manually
trigger a run (the "Run workflow" button), then check the logs for the
new source's fetch step specifically, and confirm the CSV got a new row
for it.

**Step 9: Update the documentation**

Add the new source to the "What each source actually measures" section of
this README, so the next person (including future-you) knows what the
numbers mean without having to read the code.

**Step 10: If the new source feeds Power BI, add a third Power Query
connection** (only needed if you created a third CSV file in Step 2) -
same pattern as the two existing connections: Get Data -> Web API -> base
URL `https://api.github.com` -> Advanced Editor -> point `RelativePath` at
the new file.

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
