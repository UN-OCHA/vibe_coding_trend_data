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
| `active` | yes | `yes` | `yes`/`true`/`1` to include, anything else to pause without deleting the row |
| `note` | no | `Added after Aug tools roundup` | Free text, not shown on the site - for whoever maintains the sheet |

That's it - `category` and `humanitarian_relevant` are **not** sheet
columns. Both are derived automatically per article/video from its own
title (see "Categories and the humanitarian flag" below), not set once
per source. If your sheet still has either column from an earlier
version, it's safe to delete - neither script reads them anymore.

## Example rows

```
name,type,url,active,note
Ars Technica AI,rss,https://arstechnica.com/tag/ai/feed/,yes,
The Batch,rss,https://www.deeplearning.ai/the-batch/feed/,yes,
ICT4D roundup,rss,https://example.org/ict4d/feed/,yes,humanitarian tech newsletter
vibe coding tutorial,youtube,vibe coding tutorial,yes,
AI coding for nonprofits,youtube,AI coding for nonprofits,yes,
```

## Adding a new RSS source

1. Find the site's RSS feed URL (usually `/feed`, `/rss`, or linked in the
   page footer - most WordPress and Substack sites publish one automatically).
2. Add a row with `type=rss`, `active=yes`.
3. Done - no code change, no redeploy. Picked up on the next daily run.

## Removing a source

Set `active` to `no`, or delete the row. Either works; setting it to `no`
keeps a record of why it was added in case someone wants it back later.

## Categories and the humanitarian flag

Both used to be a person's one-time judgment call per *source* in this
sheet - every story from a source got the same category and the same
humanitarian flag, regardless of what any individual story was actually
about. Neither is set here anymore. Instead, `categorize()` and
`is_humanitarian_relevant()` in `scripts/fetch_news.py` (duplicated in
`scripts/fetch_youtube.py`) check each article/video's own title against
a keyword list - a story can land in more than one category if it
genuinely fits, and the humanitarian flag reflects what that specific
story is about rather than a blanket judgment about its source. Edit
`CATEGORY_KEYWORDS` / `HUMANITARIAN_KEYWORDS` in those files to tune what
counts as "on topic" for either - not this sheet.
