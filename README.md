# oat-refresh

A [Claude Code](https://claude.com/claude-code) skill that keeps a TikTok
creator dashboard in step with the sheet people sign up on.

One command does two jobs:

1. **Reconcile** — read the creator roster sheet, add any newly-signed creators
   and any new handles for creators you already track.
2. **Scrape** — pull every active account for new videos, refreshed follower
   counts, and profile pictures.

Additive only. It never deletes a creator, never renames one, never resurrects a
retired handle, and never moves a handle between people. Each of those is
reported for a human to decide.

## Requires

- Claude Code with the **Google Drive connector** enabled (to read the sheet).
- Python 3.9+ — standard library only, nothing to install.
- A deployed **OAT Overview worker**. The skill talks to four admin routes and
  one public read; see [`docs/API.md`](docs/API.md) for the contract.

## Install

```bash
git clone https://github.com/<you>/oat-refresh.git
cd oat-refresh
cp .env.example .env      # then fill it in
```

Make the skill visible to Claude Code, either by cloning into your skills
directory or by symlinking:

```bash
# macOS / Linux
ln -s "$PWD" ~/.claude/skills/oat-refresh

# Windows (PowerShell, as admin)
New-Item -ItemType SymbolicLink -Path "$HOME\.claude\skills\oat-refresh" -Target "$PWD"
```

Check the config resolves. This prints the worker URL and sheet id, and never
the token:

```bash
python scripts/oat_refresh.py --print-config
```

## Use

Say **"refresh oat"**, **"check the creator sheet"**, or run `/oat-refresh`.

Or drive the script yourself, once you have a `rows.json`:

```bash
python scripts/oat_refresh.py --rows rows.json --dry-run   # show the plan
python scripts/oat_refresh.py --rows rows.json             # apply, then scrape
python scripts/oat_refresh.py --rows rows.json --no-sync   # apply, don't scrape
```

The agent builds `rows.json` from the sheet, because a Google Form's columns
drift as the form is edited and a model reads them more reliably than a
positional parser. The script does the diffing and the writes, because those
must be deterministic and idempotent.

## Configuration

| Variable | Purpose |
|---|---|
| `OAT_WORKER_URL` | Base URL of your worker, no trailing slash |
| `OAT_ADMIN_TOKEN` | Bearer token for `/api/admin/*` |
| `OAT_SHEET_ID` | Google Sheet id holding the roster |
| `OAT_ENV_FILE` | Optional: read config from this file instead of `.env` |

Environment variables win over `.env`, so CI can override without editing files.
`OAT_ENV_FILE` can point at a wrangler `.dev.vars` — it is the same `KEY=VALUE`
format, and a bare `ADMIN_TOKEN` is accepted as a fallback name.

## Security

**Nothing environment-specific is committed to this repo.** No worker URL, no
sheet id, no token, no creator names. All of it is configuration. If you fork
this, keep it that way — the checks below are the ones that matter.

### Never commit

| | Why |
|---|---|
| `OAT_ADMIN_TOKEN` | Grants write access to your dashboard: add creators, trigger scrapes, burn scrape credits. |
| Your scraping API key | Metered. A leaked key is someone else spending your money. |
| `.env`, `.dev.vars` | Where the above live. Both are gitignored here. |
| **The sheet id** | Not a credential — access is permission-gated — but it is a durable pointer at a document full of personal data. If anyone ever sets that sheet to "anyone with the link", the id becomes the key. |
| **Your worker URL** | If your `/api/team/*` reads are unauthenticated (they are, in the reference worker), publishing the URL publishes the whole dataset: names, handles, follower counts, per-video views, captions, thumbnails. It also hands an attacker your `/api/admin/*` surface to guess at. |
| **Real creator names and handles** | People filled in a private signup form. They did not agree to appear in a public repo's example code. Use fictional names in docs and tests. |
| `__pycache__/`, `*.pyc` | Compiled bytecode embeds the absolute path of the source file, which leaks your username and directory layout. Gitignored here. |

### Also worth knowing

- **Git history is forever.** A secret committed and then deleted is still in
  the history, and on a public repo it is scraped within minutes. If it happens,
  rotate the secret — do not just rewrite history and hope.
- **The roster sheet holds personal data.** Names, social handles, and often
  phone numbers or emails. Read only the columns you need. This skill reads the
  name and the TikTok links, and nothing else, on purpose.
- **Rotate the admin token** if it has ever been pasted into a terminal that
  gets screen-shared, a chat, or an issue.

Before pushing, a quick sanity check:

```bash
git ls-files | xargs grep -nEi 'workers\.dev|pages\.dev|[A-Za-z0-9_-]{30,}' || echo "clean"
```

## License

MIT
