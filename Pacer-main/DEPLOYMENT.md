# Deploying Pacer to Railway + GitHub

This guide covers the two-step path: **push to GitHub first**, then **deploy
to Railway from that GitHub repo**. The same instructions apply to Render
and Heroku with minor env-var name differences (called out at the end).

---

## 1. Push to GitHub

Pacer's remote is already configured:

```
origin → https://github.com/0xzhepyr/Pacer.git
```

You have 40 local commits ahead of `origin/main`. From a clean shell:

```bash
# one-time: make sure git knows who you are
git config user.name  "Your Name"
git config user.email "you@example.com"

# confirm there is nothing dirty
git status

# push
git push origin main
```

If GitHub rejects the push (e.g. the remote's `main` has commits you don't
have locally), prefer a non-destructive pull first:

```bash
git fetch origin
git rebase origin/main   # or: git pull --rebase
git push origin main
```

**Never force-push to `main`.** If you really need to rewrite history, do it
on a topic branch and open a PR.

### What's safe to push

- All source under `pacer/`, `templates/`, `static/`, `tests/`
- `requirements.txt`, `Procfile`, `runtime.txt`, `nixpacks.toml`, `railway.toml`
- `DEPLOYMENT.md`, `README.md`, `AGENTS.md`, `docs/`
- `.env.example` (template only, no secrets)
- `.gitignore` (which keeps secrets and DB files out)

### What's NEVER pushed (covered by `.gitignore`)

- `.env` (real secrets)
- `pacer.db`, `*.sqlite*`
- `__pycache__/`, `.pytest_cache/`

---

## 2. Deploy to Railway

### 2.1 Create the project

1. Go to <https://railway.app/new>
2. Pick **Deploy from GitHub repo** and select `0xzhepyr/Pacer`.
3. Railway auto-detects the Python project via `nixpacks.toml` and starts the build.

### 2.2 Add a persistent volume (REQUIRED)

Railway's filesystem is ephemeral by default — every redeploy wipes
`pacer.db` and any uploaded images. To keep your data between deploys:

1. In the Railway dashboard, click your service → **Settings** → **Volumes**.
2. Click **+ New Volume**, mount it at `/data`, size 1 GB to start.
3. Set the env var `DATA_DIR=/data` (see step 2.3). The app creates
   `pacer.db` there on first boot.

Without a volume, the app still works — the demo seed re-runs on every
deploy and your users / ratings will be lost. This is fine for a demo,
not for a real deployment.

### 2.3 Set environment variables

In **Variables**, add:

| Variable                  | Required | Notes                                                                                  |
|---------------------------|----------|----------------------------------------------------------------------------------------|
| `PACER_SECRET`            | yes      | `python -c "import secrets; print(secrets.token_urlsafe(48))"` — the app refuses to boot without this in production |
| `DISCOGS_CONSUMER_KEY`    | yes      | From <https://www.discogs.com/settings/developers>                                     |
| `DISCOGS_CONSUMER_SECRET` | yes      | Same                                                                                   |
| `SPOTIFY_CLIENT_ID`       | optional | Needed for the 30s previews + trending grid. App still works without — search and catalog panels still function |
| `SPOTIFY_CLIENT_SECRET`   | optional | Same                                                                                   |
| `DATA_DIR`                | yes      | Set to `/data` so it matches the volume mount                                          |
| `SPOTIFY_REDIRECT_URI`    | optional | Auto-derived from `RAILWAY_PUBLIC_DOMAIN` if you don't set it. Whatever you choose, add the same URL to your Spotify app's "Redirect URIs" |
| `PINATA_API_KEY`          | optional | Only if you want IPFS uploads for profile pics / post images                           |
| `PINATA_SECRET_KEY`       | optional | Same                                                                                   |

> Tip: Railway also injects `RAILWAY_PUBLIC_DOMAIN` (e.g. `pacer.up.railway.app`).
> The app uses that to build the Spotify redirect URI automatically, so you
> usually don't need to set `SPOTIFY_REDIRECT_URI` by hand.

### 2.4 Add the Spotify redirect URI

Whatever URL the app derives (e.g. `https://pacer.up.railway.app/spotify/callback`)
**must be added** to your Spotify app's Redirect URIs list at
<https://developer.spotify.com/dashboard>. Otherwise OAuth login breaks.

### 2.5 First deploy

1. Click **Deploy**. The build runs `pip install -r requirements.txt`.
2. The `release` process in `Procfile` initializes the SQLite schema and
   seeds demo users. If it fails, the deploy is rolled back and the
   previous version stays up.
3. The `web` process starts gunicorn. Health checks ping `/healthz`.
4. Open the generated `*.up.railway.app` URL — you should see the Pacer
   home page with seeded users (`tom` / `myspace` and the others).

### 2.6 Verify

```bash
curl https://<your-app>.up.railway.app/healthz
# expected: {"status":"ok","production":true,"db_path":"/data/pacer.db","db_exists":true,"db_reachable":true}
```

Then log in as `tom` with password `myspace` and confirm the trending grid
populates (Spotify creds), search works (Discogs creds), and you can attach
a song to a post.

### 2.7 Subsequent deploys

Just `git push origin main`. Railway watches the repo, rebuilds, runs the
`release` process (idempotent — won't duplicate seed data), then swaps
gunicorn. The persistent volume keeps the DB intact.

---

## 3. Adapting to other platforms

### Render

1. New → Web Service → connect the GitHub repo.
2. Build command: `pip install -r requirements.txt`
3. Start command: `gunicorn run:app --bind 0.0.0.0:$PORT --workers 2`
4. Add a **Disk** at `/data`, set `DATA_DIR=/data`.
5. Set the same env vars as Railway; Render auto-injects `RENDER_EXTERNAL_URL`
   which the app uses for the Spotify redirect URI.

### Heroku

1. `heroku create` and `heroku git:remote -a <app>`.
2. `heroku addons:create heroku-postgresql:mini` *or* mount a filesystem
   add-on for SQLite. Pacer uses SQLite by default; for a real install
   consider a Postgres adapter.
3. `heroku config:set PACER_SECRET=... DISCOGS_CONSUMER_KEY=...` etc.
4. `git push heroku main`. The `Procfile`'s `web` and `release` processes
   run automatically.

### Bare VPS / Docker

`Dockerfile` is not included (Pacer is small enough that a `python:3.13`
image + `pip install -r requirements.txt` + the `Procfile` covers it).
A minimal `Dockerfile` would be:

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "run:app", "--bind", "0.0.0.0:5000", "--workers", "2"]
```

---

## 4. Troubleshooting

| Symptom                                                                 | Likely cause                                                                                |
|-------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| App crashes on boot with `PACER_SECRET is set to the placeholder ...`  | Forgot to set `PACER_SECRET` in platform env vars.                                          |
| `/healthz` returns 500 with `db_reachable: false`                      | Persistent volume not mounted, or `DATA_DIR` doesn't match the mount path.                 |
| Trending grid empty                                                     | Missing `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — or Spotify API is blocked.          |
| Search returns "Catalog not configured"                                | Missing `DISCOGS_CONSUMER_KEY` / `DISCOGS_CONSUMER_SECRET`.                                 |
| "Connect Spotify" button shows "redirect URI mismatch"                 | The auto-derived `SPOTIFY_REDIRECT_URI` doesn't match the one registered in the Spotify dashboard. Add the railway URL to the dashboard. |
| Demo users disappear after redeploy                                     | No persistent volume. Either mount one or treat the deploy as a fresh demo.                |
| `gunicorn: command not found` on build                                  | Missing `gunicorn` in `requirements.txt`. It IS listed; this means the build cache is stale. Trigger a clear-cache rebuild from the Railway dashboard. |
