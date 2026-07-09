# Worker API contract

The skill needs a deployed OAT Overview worker. These are the only routes it
touches. Any backend implementing them will work.

`/api/admin/*` requires `Authorization: Bearer $OAT_ADMIN_TOKEN`.

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

## `GET /api/team/period?span=all`

Public read. The script uses only `stats.posts`, before and after the scrape, to
report how many new videos landed.

```json
{"stats": {"posts": 349, "views": 45276359, "creators": 2, "accounts": 2}}
```

> This route is unauthenticated in the reference worker. If your roster is not
> meant to be public, put access control in front of it — see the README.
