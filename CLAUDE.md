# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Source of truth

**`REGOG_REBUILD_V8.md`** (repo root) is the current build document — 30 sections covering every subsystem, known bugs, and rebuild instructions. All other `REGOG_*.md` docs (V6, V5, V4, V1, audits, debates) are historical and superseded; do not take direction from them.

## Commands

```bash
pytest -q                          # full test suite (fast, <2s) — keep it green
pytest tests/test_land_score.py    # single test file
pytest tests/test_land_score.py -k test_name   # single test

python3 -m py_compile web/app.py regog/scrapers/loopnet_auth.py   # quick syntax check

python3 regog/main.py              # CLI scanner (subcommands: scan, leads, report, config)
python3 -m scrapers.loopnet_auth login-credentials [email] [password]  # run from regog/ dir
```

Run `pytest` before and after touching scoring or scoring-adjacent code; fix regressions immediately.

### Web app — start/stop gotchas

The Flask app (`serve_report.py`, port 8080) must be started **by the user in their own terminal**, not from an AI tool call — the tool subshell reaps detached background processes. Tell the user to run:

```bash
nohup bash scripts/regog_keepalive.sh > /tmp/regog-app.log 2>&1 < /dev/null & disown
```

Stopping requires **both** pkills (the keepalive has no EXIT trap, so killing it orphans the server):

```bash
pkill -f regog_keepalive.sh && pkill -f serve_report.py
```

The codespace idle-kills processes after ~20 minutes — if the app is down with no traceback in `/tmp/regog-app.log`, that's the cause, not a code bug.

## Architecture

Pipeline: **scrapers → enrichment → scoring → SQLite (`regog.db`) → UI/reports**.

- `regog/` — the Python package. `main.py` is the CLI entry; `scrapers/` (HomeHarvest/Realtor, Zillow stealth, Redfin, Craigslist, FEMA flood, assessor, permits, LoopNet), `enrichment/` (comp engine, brain classifier, geocoder), `scoring/` (land/residential/commercial scorers), `db/`, `scheduler/`, `ui/` (terminal UI + Jinja2 report), `utils/`.
- `web/app.py` — Flask backend wrapping the same scan pipeline: REST + SSE-streamed background scan threads, Lava Search (TOP_20_METROS), Flip Radar, LoopNet auth endpoints. `web/static/index.html` is the entire single-page UI (CSS + JS inline).
- `serve_report.py` — serves the web app on 0.0.0.0:8080.

**Import convention:** `web/app.py` and `tests/conftest.py` insert `regog/` onto `sys.path`, so cross-module imports are written relative to the package dir (`from scrapers.x import y`, `from db.database import ...`), not `from regog.scrapers...`. Module-level CLI runs (`python3 -m scrapers.loopnet_auth`) must be launched from inside `regog/`.

All data sources are free/no-API-key. Playwright (with `playwright-stealth`) is used for browser scrapers.

## LoopNet auth (read V8 §15 before touching)

- Primary: email/password login (`POST /api/loopnet/login` → `login_with_credentials()` in `regog/scrapers/loopnet_auth.py`). Fallback: DevTools cookie-bundle paste. Both write `loopnet_session.json`.
- **The codespace egress IP is on Akamai's denylist** — loopnet.com returns 403 before login is possible, regardless of cookies or stealth. Credentials login only works from a clean IP or with `LOOPNET_PROXY=http://user:pass@host:port` set. Do not chase this as a code bug.
- `loopnet_session.json` and `loopnet_credentials.json` (repo root) hold real secrets — gitignored, never commit.
