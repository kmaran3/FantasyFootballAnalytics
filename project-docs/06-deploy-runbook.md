# Deploy Runbook: AI Draft Copilot

## Overview

This runbook covers deploying the AI Draft Copilot feature to Railway. The feature adds an SSE-streaming chat panel to the draft board, powered by Groq (Llama 3.3 70B) with pre-computed ML model predictions.

## Pre-deploy checklist

- [ ] All tests pass (see `project-docs/05-test-plan.md` — current status: GO)
- [ ] `GROQ_API_KEY` is set in Railway dashboard (feature degrades gracefully without it)
- [ ] Branch merged to `main` (Railway auto-deploys from `main`)

## What changed (deployment-relevant)

| Change | Detail |
|--------|--------|
| **Worker type** | `gunicorn -k gevent -w 4 --timeout 30` (was default sync workers) |
| **New dependencies** | `openai>=1.0.0`, `gevent>=24.0`, `unidecode>=1.3.0` |
| **New blueprint** | `webapp/copilot/` — SSE endpoint at `/draft-board/copilot/chat` |
| **New env var** | `GROQ_API_KEY` (optional — fallback mode works without it) |
| **New static assets** | Pickle model files in `webapp/copilot/models/` (~3 files) |

## Environment variables

| Variable | Required | Where to set | Notes |
|----------|----------|-------------|-------|
| `GROQ_API_KEY` | No (recommended) | Railway dashboard → Variables | Free from groq.com. Without it, copilot uses rule-based fallback. |
| `SECRET_KEY` | Yes | Already set | No change needed |
| `DATABASE_URL` | Yes | Already set | No change needed |

## How to deploy

1. **Merge to main**: Railway auto-deploys on push to `main`.
2. **Set env var** (first time only): In Railway dashboard → your service → Variables → add `GROQ_API_KEY`.
3. **Monitor deploy**: Railway dashboard → Deployments → watch build logs for dependency install success.
4. **Verify health**: Railway's healthcheck at `/` will confirm the app is up.

## How to verify after deploy

1. Navigate to a draft board page.
2. Confirm the "✦ Copilot" button appears in the topbar.
3. Click it — panel should slide open.
4. Type "Who should I draft?" and send.
5. With `GROQ_API_KEY` set: response streams in progressively.
6. Without key: response appears at once with "Running in limited mode" note and banner shows.

## How to roll back

Railway keeps previous deployments. To roll back:

1. **Railway dashboard** → Deployments → find the last known-good deploy → click "Redeploy".
2. If the issue is `GROQ_API_KEY` related: simply remove or update the variable in Railway dashboard. The app degrades gracefully without it.
3. If gevent workers cause issues: revert `Procfile` and `railway.toml` to use sync workers (`gunicorn app:app`), push to `main`.

**Rollback in one sentence**: Redeploy the previous Railway deployment from the dashboard — no data migration involved, purely a code rollback.

## If something breaks

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| App won't start / crashes on boot | `gevent` or `google-genai` install failed | Check Railway build logs. Pin versions if needed. |
| Copilot returns errors | Invalid or expired `GROQ_API_KEY` | Get a new free key from groq.com, update in Railway Variables. App uses fallback in the meantime. |
| SSE responses hang / timeout | Gunicorn timeout too short | Increase `--timeout` in `Procfile` and `railway.toml` (currently 30s). |
| High memory usage | Pickle model files loaded per-worker | Models are `lru_cache`'d per worker. With 4 gevent workers sharing process, this should be ~3 copies max. Reduce `-w` if needed. |
| `/draft-board/copilot/chat` 404 | Blueprint not registered | Check `webapp/__init__.py` for `copilot_bp` import/registration. |
| Rate limit errors (429) | User exceeding 10 req/min | Working as designed. In-memory rate limiting resets on redeploy. |

## Monitoring

- **Railway dashboard**: CPU, memory, request logs
- **Health check**: `GET /` — configured in `railway.toml` with 100s timeout
- **Copilot status**: `GET /draft-board/copilot/status` — returns `{"available": true/false}` confirming API key presence

## Release readiness

| Area | Status |
|------|--------|
| Code changes | Complete — all files committed |
| Tests | GO — all blocking/major bugs fixed |
| Deployment config | Ready — `Procfile`, `railway.toml` updated |
| Dependencies | Declared in `requirements.txt` |
| Secrets | `GROQ_API_KEY` — user must add to Railway dashboard |
| Rollback | One-click redeploy from Railway dashboard |
| Graceful degradation | Verified — works without API key |

## User action items

1. **Add `GROQ_API_KEY`** to Railway dashboard → Variables (get from [Groq Console](https://console.groq.com/keys))
2. **Merge branch to `main`** to trigger Railway auto-deploy
3. **Verify** using the post-deploy checklist above
