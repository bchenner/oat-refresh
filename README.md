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

## Requirements

**There is nothing to `pip install`.** The script imports only `argparse`,
`json`, `os`, `pathlib`, `re`, `sys` and `urllib` — all standard library. A test
(`TestNoDependencies`) fails the build if a third-party import ever sneaks in, so
that promise stays true.

What it does depend on:

| Dependency | Version | Why | Checked by `--check` |
|---|---|---|---|
| Python | 3.9+ | runs the script | yes |
| Claude Code | any recent | hosts the skill | — |
| Google Drive connector | — | the agent reads the roster sheet through it | no — enable it in your claude.ai connector settings |
| A deployed OAT Overview worker | — | four admin routes + one public read ([`docs/API.md`](docs/API.md)) | yes |
| `OAT_WORKER_URL` / `OAT_ADMIN_TOKEN` | — | reach and authenticate to the worker | yes |
| `OAT_SHEET_ID` | — | locate the roster sheet | yes |

Verify everything at once, before you need it:

```bash
python scripts/oat_refresh.py --check
```

It reports the Python version, whether the config resolves, whether the worker
is reachable, whether your admin token is accepted, **whether the admin routes
actually reject an unauthenticated request**, and how many creators and accounts
are live. It never prints the token. Non-zero exit means don't bother refreshing
until you've fixed it.

On macOS and Linux, use `python3` if `python` is not on your PATH.

### The worker's own dependencies

The skill is a client; it installs none of this. If you are standing a worker up
from scratch, it needs:

| | |
|---|---|
| Cloudflare account | Workers + D1 + Pages |
| [Hono](https://hono.dev) | the worker's HTTP router |
| [Wrangler](https://developers.cloudflare.com/workers/wrangler/) | deploy, D1 migrations, secrets |
| A TikTok scraping API | the reference worker uses [ScrapeCreators](https://scrapecreators.com); metered, keep the key secret |
| `ADMIN_TOKEN` secret | must equal your `OAT_ADMIN_TOKEN` |

Any backend serving the five routes in [`docs/API.md`](docs/API.md) will work.

## Development

```bash
python -m unittest discover -s tests -v
```

18 offline tests. No network, no worker, no config — they run anywhere. CI runs
them on Python 3.9 through 3.13, confirms `requirements.txt` installs nothing,
and refuses any commit containing a real worker hostname, a `.env`, or compiled
bytecode.

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
