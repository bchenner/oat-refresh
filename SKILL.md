---
name: oat-refresh
description: Refresh the OAT Overview dashboard — read the creator roster sheet for newly-signed creators, add any missing creators/handles, then scrape every tracked TikTok account for new videos. Use when the user says "refresh oat", "update oat overview", "check the creator sheet", "any new creators", "scan for new videos", "sync oat", or runs /oat-refresh.
---

# OAT Overview — refresh

Two jobs in one pass:

1. **Reconcile** the creator roster sheet into the database (add new creators + handles).
2. **Scrape** every active account for new videos.

Additive only. Nothing is deleted, renamed, or reactivated automatically —
retiring a creator stays a deliberate manual act.

## Configuration

Everything environment-specific lives in `.env` at the repo root (gitignored;
copy `.env.example`). Nothing is hardcoded, so this skill points at whichever
worker and sheet you configure.

Get the sheet id and worker URL without exposing the token:

```bash
python scripts/oat_refresh.py --print-config
```

Requires the **Google Drive connector** to read the sheet.

## Do this

1. **Read the sheet.** Take the `sheetId` from `--print-config`, then call
   `mcp__claude_ai_Google_Drive__read_file_content` with it.

   The roster is typically a Google Form response set, so its columns drift as
   the form is edited. Find columns by meaning, not position:
   - the person's name
   - their TikTok link(s) — the column is usually plural; one respondent may
     list several handles

   **Do not read any phone-number, email, or address column.** The dashboard
   has no use for personal contact details and they must never reach the
   database, the logs, or the repo.

2. **Write `rows.json`** to a scratchpad — one entry per respondent, verbatim
   names, every TikTok link they gave. Respondents who wrote `N/A` get an empty
   list; pass them through anyway so the script reports them as skipped.

   ```json
   [
     {"name": "Ana Torres",  "urls": ["https://www.tiktok.com/@ana.creates"]},
     {"name": "Marco Silva", "urls": []}
   ]
   ```

3. **Preview the plan:**

   ```bash
   python scripts/oat_refresh.py --rows <scratchpad>/rows.json --dry-run
   ```

4. **Apply and scrape:** rerun without `--dry-run`. A full catalogue pull takes
   several minutes — TikTok serves 10 videos per request. Give the Bash call a
   timeout of at least 600000 ms.

   Add `--no-sync` to reconcile without spending scrape credits.

5. **Report** to the user: creators added, handles added, rows skipped, videos
   captured vs claimed per account, and how many new videos landed.

## Reading the output

The script prints a plan, then a scrape table. Things that need a human:

- `~ skipped <name>` — the respondent gave no TikTok link, or every handle they
  listed already belongs to someone else. Tell the user; nothing is broken.
- `! @handle exists but deactivated` — a retired handle reappeared in the sheet.
  The script will not silently resurrect it. Reactivate deliberately:
  `POST /api/admin/accounts` with `{"id": "...", "handle": "...", "active": true}`.
- `! @handle — sheet says X, DB says Y` — two people claim one handle. The
  script refuses to move it. Resolve with the user before touching anything.
- `TRUNCATED` — an account outgrew `SCRAPE_MAX_PAGES`. Raise it in the worker's
  `wrangler.toml` and redeploy, or the board silently misses older videos.
- `N not served by TikTok` — the profile's own `video_count` exceeds what the
  feed returns. Usually deleted or private videos. A large gap is worth a look.
- `FAILED` — a handle 404s or the API errored. Usually a typo in the sheet or a
  renamed account. The script exits non-zero.

## Notes

- The admin token is read from the environment or `.env`. **Never print it**,
  never echo it into a command the user can see, never write it to a file that
  is not gitignored.
- A creator is matched to the sheet **by name**, case-insensitively. Two rows
  with the same name collapse into one creator with several handles — which is
  exactly the intent of a plural "Account Link(s)" column.
- New creators are assigned the next unused colour from the dashboard palette.
- The scrape also refreshes profile pictures and follower counts, so it is worth
  running even when the sheet has not changed.
