# Google Sheet: source & topic config

This sheet is the single non-technical control surface for the daily
pipeline. Anyone with edit access can add, remove, or re-flag a source
without touching any code. One row = one RSS feed or one YouTube search
topic.

## Setup (one-time)

1. Create a Google Sheet, name the first tab `sources`.
2. Add the header row exactly as below (column order doesn't matter, but
   the names must match).
3. `File > Share > Publish to web`, choose the `sources` tab, format
   `Comma-separated values (.csv)`. Copy the resulting URL.
4. Add that URL as a repo secret named `SHEET_CSV_URL`.

The scripts re-fetch this sheet on every run, so changes go live on the
next scheduled run - no redeploy needed.

## Columns

| Column | Required | Example | Notes |
|---|---|---|---|
| `name` | yes | `Ars Technica` | Display name shown as the byline on the site |
| `type` | yes | `rss` or `youtube` | Anything else is ignored |
| `url` | yes | `https://arstechnica.com/tag/ai/feed/` | For `type=rss`, the feed URL. For `type=youtube`, the **search query** to run (e.g. `vibe coding tutorial`) |
| `category` | yes | `Tools` | Must match one of: `Tools`, `Industry`, `Culture`, `Risks`, `Research`, `Education`. Anything else falls back to "Uncategorized" on the site |
| `active` | yes | `yes` | `yes`/`true`/`1` to include, anything else to pause without deleting the row |
| `humanitarian_relevant` | yes | `no` | Manually judged - not automated. `yes` tags every story from this source as relevant to the org's work |
| `note` | no | `Added after Aug tools roundup` | Free text, not shown on the site - for whoever maintains the sheet |

## Example rows

```
name,type,url,category,active,humanitarian_relevant,note
Ars Technica AI,rss,https://arstechnica.com/tag/ai/feed/,Tools,yes,no,
The Batch,rss,https://www.deeplearning.ai/the-batch/feed/,Research,yes,no,
ICT4D roundup,rss,https://example.org/ict4d/feed/,Education,yes,yes,humanitarian tech newsletter
vibe coding tutorial,youtube,vibe coding tutorial,Tools,yes,no,
AI coding for nonprofits,youtube,AI coding for nonprofits,Education,yes,yes,
```

## Adding a new RSS source

1. Find the site's RSS feed URL (usually `/feed`, `/rss`, or linked in the
   page footer - most WordPress and Substack sites publish one automatically).
2. Add a row with `type=rss`, `active=yes`.
3. Done - no code change, no redeploy. Picked up on the next daily run.

## Removing a source

Set `active` to `no`, or delete the row. Either works; setting it to `no`
keeps a record of why it was added in case someone wants it back later.

## The humanitarian flag

This is deliberately a **person's judgment call**, set per source (or you
can add per-story overrides later if needed) - not an automated classifier.
Set it thoughtfully; every story from a source flagged `yes` shows up in the
site's "Relevant to our work" filter.
