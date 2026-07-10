#!/usr/bin/env python3
"""Reconcile a creator roster sheet into OAT Overview, then scrape.

Reads a rows.json produced from the roster sheet (the agent does the reading —
a Google Form's columns drift as the form is edited, and a model handles that
better than a positional parser), diffs it against the worker's full state,
adds whatever is missing, and runs a sync.

    rows.json:
        [{"name": "Ana Torres", "urls": ["https://www.tiktok.com/@ana.creates"]},
         {"name": "Marco Silva", "urls": []}]

Additive only. Nothing is ever deleted, renamed, or reactivated: retiring a
creator stays a deliberate manual act.

Configuration comes from the environment or a .env file. No endpoint, token, or
sheet id is baked into this file — see .env.example.
"""
import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

# Every import above is standard library. This script has no third-party
# dependencies and tests/test_oat_refresh.py enforces that.

MIN_PYTHON = (3, 9)
if sys.version_info < MIN_PYTHON:
    # %-format, not an f-string: this must survive on the old interpreter it is
    # complaining about. (Below 3.6 the file fails to parse before reaching here.)
    sys.exit("oat-refresh needs Python %d.%d+ — running %s" % (
        MIN_PYTHON[0], MIN_PYTHON[1], ".".join(str(p) for p in sys.version_info[:3])))

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Per-creator accent colours, matching the dashboard's palette.
PALETTE = ["#FF3D77", "#2DE2E6", "#B481FF", "#FFC24B",
           "#4ADE80", "#FF8A4B", "#5B8CFF", "#F472B6"]

# tiktok.com/@handle, with or without scheme/www/trailing path.
HANDLE_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9._-]+)", re.I)
BARE_RE = re.compile(r"^@?([A-Za-z0-9._-]+)$")

PLACEHOLDERS = {"", "replace-me", "changeme", "your-token-here"}


# ── configuration ───────────────────────────────────────────────────────────

def _parse_env_file(path: pathlib.Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def config():
    """Environment wins over the .env file, so CI can override without editing it.

    OAT_ENV_FILE may point at a wrangler `.dev.vars`, which uses the same
    KEY=VALUE format — hence the bare ADMIN_TOKEN fallback.
    """
    env = dict(os.environ)
    candidate = pathlib.Path(env["OAT_ENV_FILE"]) if env.get("OAT_ENV_FILE") else ROOT / ".env"
    if candidate.exists():
        for k, v in _parse_env_file(candidate).items():
            env.setdefault(k, v)

    worker = (env.get("OAT_WORKER_URL") or "").rstrip("/")
    token = env.get("OAT_ADMIN_TOKEN") or env.get("ADMIN_TOKEN") or ""
    sheet = env.get("OAT_SHEET_ID") or ""

    missing = []
    if worker.lower() in PLACEHOLDERS or not worker.startswith("http"):
        missing.append("OAT_WORKER_URL")
    if token.lower() in PLACEHOLDERS:
        missing.append("OAT_ADMIN_TOKEN")
    if missing:
        sys.exit(
            "missing config: " + ", ".join(missing) + "\n"
            f"set them in the environment or in {ROOT / '.env'} (see .env.example)"
        )
    return worker, token, sheet


# ── api ─────────────────────────────────────────────────────────────────────

def api(worker, path, method="GET", body=None, token=None, timeout=600):
    req = urllib.request.Request(worker + path, method=method)
    # Cloudflare rejects urllib's default User-Agent outright (error 1010).
    req.add_header("user-agent", "oat-refresh/1.0")
    if token:
        req.add_header("authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:200]
        hint = "  (is OAT_ADMIN_TOKEN correct?)" if e.code == 401 else ""
        sys.exit(f"{method} {path} -> HTTP {e.code}: {detail}{hint}")
    except urllib.error.URLError as e:
        sys.exit(f"{method} {path} -> {e.reason}  (is OAT_WORKER_URL correct?)")


def probe(worker, path, token=None, timeout=20):
    """Like api(), but never exits. Returns (status_or_None, payload_or_error)."""
    req = urllib.request.Request(worker + path, method="GET")
    req.add_header("user-agent", "oat-refresh/1.0")
    if token:
        req.add_header("authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, None, timeout=timeout) as r:
            try:
                return r.status, json.loads(r.read().decode())
            except json.JSONDecodeError:
                return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except urllib.error.URLError as e:
        return None, str(e.reason)


# ── preflight ───────────────────────────────────────────────────────────────

def run_check(worker, token, sheet_id):
    """Verify every dependency this skill leans on, before it is needed.

    Returns a process exit code. Never prints the token.
    """
    failures = 0
    warnings = 0

    def say(state, label, detail=""):
        nonlocal failures, warnings
        if state == "FAIL":
            failures += 1
        elif state == "WARN":
            warnings += 1
        print(f"  [{state:^4}] {label}" + (f" — {detail}" if detail else ""))

    print("environment")
    say("PASS", "python", ".".join(str(p) for p in sys.version_info[:3]))
    say("PASS", "third-party packages", "none required")

    print("\nconfiguration")
    say("PASS", "OAT_WORKER_URL", worker)
    say("PASS", "OAT_ADMIN_TOKEN", "set (not shown)")
    if sheet_id:
        say("PASS", "OAT_SHEET_ID", sheet_id)
    else:
        say("WARN", "OAT_SHEET_ID", "unset — the agent cannot find the roster sheet")

    print("\nworker")
    status, payload = probe(worker, "/api/health")
    if status is None:
        say("FAIL", "reachable", str(payload))
        print("\nCannot reach the worker; skipping the remaining checks.")
        return 1
    say("PASS" if status == 200 else "FAIL", "GET /api/health", f"HTTP {status}")

    # An unauthenticated admin route would be a serious hole. Check it directly.
    status, _ = probe(worker, "/api/admin/state")
    if status == 200:
        say("FAIL", "admin routes guarded", "/api/admin/state answered WITHOUT a token")
    else:
        say("PASS", "admin routes guarded", f"unauthenticated -> HTTP {status}")

    status, payload = probe(worker, "/api/admin/state", token=token)
    if status == 200 and isinstance(payload, dict) and "creators" in payload and "accounts" in payload:
        live = sum(1 for a in payload["accounts"] if a.get("active"))
        say("PASS", "admin token accepted",
            f"{len(payload['creators'])} creators, {len(payload['accounts'])} accounts ({live} live)")
    elif status == 401:
        say("FAIL", "admin token accepted", "HTTP 401 — OAT_ADMIN_TOKEN is wrong")
    else:
        say("FAIL", "GET /api/admin/state", f"HTTP {status}, unexpected shape")

    status, payload = probe(worker, "/api/team/period?span=all")
    if status == 200 and isinstance(payload, dict) and "posts" in payload.get("stats", {}):
        say("PASS", "GET /api/team/period", f"{payload['stats']['posts']} posts all time")
        # Informational, not a failure: the reference worker ships this way.
        say("WARN", "public read", "/api/team/* needs no auth — anyone with the URL sees the data")
    else:
        say("FAIL", "GET /api/team/period", f"HTTP {status}, unexpected shape")

    print("\nnot checkable from here")
    print("  [ ?? ] Google Drive connector — the agent needs it to read the sheet")

    print()
    if failures:
        print(f"{failures} failed, {warnings} warning(s) — fix the failures before refreshing")
        return 1
    print(f"all checks passed, {warnings} warning(s)")
    return 0


# ── sheet parsing ───────────────────────────────────────────────────────────

def extract_handles(urls):
    """Pull TikTok handles out of whatever the form respondent typed."""
    out = []
    for raw in urls:
        for chunk in re.split(r"[,\s]+", str(raw or "").strip()):
            if not chunk or chunk.upper() in {"N/A", "NA", "NONE", "-"}:
                continue
            m = HANDLE_RE.search(chunk)
            if m:
                out.append(m.group(1).lower())
                continue
            # Only an explicit "@handle" counts as a bare handle. Handles contain
            # dots (e.g. ana.b.creates), so "looks like a domain" cannot tell
            # them apart from a pasted instagram.com/... link. Anything else is
            # ignored, and the row surfaces as skipped rather than mis-ingested.
            if chunk.startswith("@"):
                b = BARE_RE.match(chunk)
                if b:
                    out.append(b.group(1).lower())
    seen, uniq = set(), []
    for h in out:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


def alloc(prefix, taken, width=2):
    i = 1
    while True:
        cid = f"{prefix}{i:0{width}d}"
        if cid not in taken:
            taken.add(cid)
            return cid
        i += 1


def pick_color(used):
    for c in PALETTE:
        if c not in used:
            used.add(c)
            return c
    return PALETTE[len(used) % len(PALETTE)]


# ── main ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rows", help="rows.json extracted from the roster sheet")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--no-sync", action="store_true", help="reconcile only, skip the scrape")
    ap.add_argument("--print-config", action="store_true",
                    help="print worker url and sheet id (never the token) and exit")
    ap.add_argument("--check", action="store_true",
                    help="verify python, config, and the worker's routes, then exit")
    args = ap.parse_args()

    worker, token, sheet_id = config()

    if args.check:
        sys.exit(run_check(worker, token, sheet_id))
    if args.print_config:
        print(json.dumps({"worker": worker, "sheetId": sheet_id or None}, indent=2))
        return
    if not args.rows:
        ap.error("--rows is required (or use --check / --print-config)")

    rows = json.loads(pathlib.Path(args.rows).read_text(encoding="utf-8"))
    state = api(worker, "/api/admin/state", token=token)

    # Index EVERYTHING, live or retired — a retired handle must not be re-added,
    # or the insert collides on UNIQUE(handle, platform).
    accounts_by_handle = {a["handle"].lower(): a for a in state["accounts"]}
    creators_by_name = {c["name"].strip().lower(): c for c in state["creators"]}
    taken_accounts = {a["id"] for a in state["accounts"]}
    taken_creators = {c["id"] for c in state["creators"]}
    used_colors = {c["color"] for c in state["creators"] if c.get("color")}

    new_creators, new_accounts = [], []
    skipped, retired, moved = [], [], []

    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        handles = extract_handles(row.get("urls") or [])
        if not handles:
            skipped.append(f"{name} — no TikTok link in the sheet")
            continue

        key = name.lower()
        creator = creators_by_name.get(key)

        # Resolve which handles would actually land, before deciding whether the
        # creator is worth creating. Otherwise a row whose only handle is taken
        # or retired leaves an orphan creator with no accounts behind it.
        fresh = []
        for h in handles:
            existing = accounts_by_handle.get(h)
            if not existing:
                fresh.append(h)
            elif not existing["active"]:
                retired.append(f"@{h} ({name}) — exists but deactivated; reactivate by hand")
            elif not creator or existing["creator_id"] != creator["id"]:
                owner = next((c["name"] for c in state["creators"]
                              if c["id"] == existing["creator_id"]), "?")
                moved.append(f"@{h} — sheet says {name}, DB says {owner}; not moving")

        if not fresh:
            if not creator:
                skipped.append(f"{name} — every handle they listed is taken or retired")
            continue

        if creator:
            creator_id = creator["id"]
        else:
            creator_id = alloc("c", taken_creators)
            new_creators.append({"id": creator_id, "name": name, "color": pick_color(used_colors)})
            # So two sheet rows with the same name collapse into one creator.
            creators_by_name[key] = {"id": creator_id, "name": name}

        for h in fresh:
            account_id = alloc("a", taken_accounts)
            new_accounts.append({"id": account_id, "handle": h, "creator_id": creator_id,
                                 "display_name": name})
            accounts_by_handle[h] = {"handle": h, "active": 1, "creator_id": creator_id}

    print("=" * 62)
    print("PLAN")
    print("=" * 62)
    for c in new_creators:
        print(f"  + creator {c['id']}  {c['name']}")
    for a in new_accounts:
        print(f"  + account {a['id']}  @{a['handle']}  -> {a['creator_id']}")
    for s in skipped:
        print(f"  ~ skipped   {s}")
    for r in retired:
        print(f"  ! {r}")
    for m in moved:
        print(f"  ! {m}")
    if not (new_creators or new_accounts):
        print("  (nothing new in the sheet)")

    if args.dry_run:
        print("\ndry run — nothing changed")
        return

    if new_creators:
        api(worker, "/api/admin/creators", "POST", new_creators, token)
    if new_accounts:
        api(worker, "/api/admin/accounts", "POST", new_accounts, token)

    if args.no_sync:
        print("\n--no-sync: skipped the scrape")
        return

    before = api(worker, "/api/team/period?span=all")["stats"]["posts"]
    print("\nscraping (a full catalogue pull takes a few minutes)...")
    report = api(worker, "/api/admin/sync", "POST", {}, token)
    after = api(worker, "/api/team/period?span=all")["stats"]["posts"]

    print("\n" + "=" * 62)
    print("SCRAPE")
    print("=" * 62)
    for a in report.get("ok", []):
        claimed = a.get("claimed")
        missing = None if claimed is None else claimed - a["captured"]
        gap = f"  ({missing} not served by TikTok)" if missing else ""
        flag = "  TRUNCATED — raise SCRAPE_MAX_PAGES" if a.get("truncated") else ""
        print(f"  @{a['handle']:<20} {a['captured']:>4} of {str(claimed):<5} videos{gap}{flag}")
    for f in report.get("failed", []):
        print(f"  @{f['handle']:<20} FAILED: {f['error'][:80]}")

    print(f"\n  new videos since last run: {after - before}")
    print(f"  posts all time:            {after}")
    if report.get("failed"):
        sys.exit(1)


if __name__ == "__main__":
    main()
