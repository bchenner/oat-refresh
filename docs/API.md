# Worker API contract

The skill needs a deployed OAT Overview worker. The **admin + team routes below
are the only ones the skill calls**; the read routes at the end are what the
scraped data powers on the dashboard (listed for completeness — the skill does
not call them).

`/api/admin/*` requires `Authorization: Bearer $OAT_ADMIN_TOKEN`. Everything
under `/api/team/*`, `/api/video/*`, and `/api/challenges` is public read.

## `GET /api/admin/state`

Returns **every** creator and account, including retired ones.

```json
{
  "creators": [{"id": "c01", "name": "Ana Torres", "color": "#FF3D77", "active": 1}],
  "accounts": [{"id": "a01", "handle": "ana.creates", "active": 1, "creator_id": "c01"}]
}
```

The reconciler cannot work from the public `/api/team/*` reads, which expose
only live rows: it would try to re-add a deactivated handle and collide on
`UNIQUE(handle, platform)`.

## `POST /api/admin/creators`

Upsert creators. Accepts an object or an array.

```json
[{"id": "c02", "name": "Marco Silva", "color": "#2DE2E6"}]
```

`{"active": false}` retires a creator and all their handles.

## `POST /api/admin/accounts`

Upsert handles. `creator_id` attaches a handle to an existing creator — this is
how one person ends up with several accounts.

```json
[{"id": "a04", "handle": "ana.backup", "creator_id": "c01", "display_name": "Ana Torres"}]
```

Omit `creator_id` and the account gets a creator of its own.

## `POST /api/admin/sync`

Scrapes every active account. Returns coverage per account so a partial scrape
cannot pass for a complete one.

```json
{
  "ok": [{"handle": "ana.creates", "captured": 240, "claimed": 240, "truncated": false}],
  "failed": [],
  "truncated": [],
  "videos": 240
}
```

- `captured` vs `claimed` — what we stored vs what the profile says exists.
- `truncated` — the page budget ran out with more to fetch. Raise
  `SCRAPE_MAX_PAGES` and redeploy.

## `GET /api/team/period?span=week|month|year|all&start=YYYY-MM-DD`

Public read — the whole dashboard for a period. The script uses only
`stats.posts`, before and after the scrape, to report how many new videos landed.
The full payload also carries per-creator aggregates (views, virality, share
rate, percentile inputs), per-creator top videos, and the account rollup.

```json
{"stats": {"posts": 349, "views": 45276359, "followers": 296454,
           "eng": 1.3, "creators": 6, "accounts": 7}}
```

`start` is any date inside the wanted period; the server snaps it to the boundary.
`span=all` runs from the first tracked post to today.

## Read routes the skill does **not** call

Listed so the contract is complete. These are what the scraped data powers on the
dashboard — no admin token needed.

- `GET /api/video/:id` — one video's detail: latest view/like/comment/share/save
  counts plus its snapshot history (the "views over time" curve). The history
  grows one point per sync, so it fills in over time.
- `GET /api/challenges` — challenge standings. The *races* (views, posts) are
  computed live from scraped videos within each challenge's window; the *GMV*
  tier is config-only (GMV is not scrapeable). Definitions live in the worker's
  `src/challenges.config.js`, not here.

> `/api/team/*`, `/api/video/*`, and `/api/challenges` are unauthenticated in the
> reference worker. If your roster is not meant to be public, put access control
> in front of them — see the README.
