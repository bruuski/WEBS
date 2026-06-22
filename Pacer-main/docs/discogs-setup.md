# Discogs API Setup

Pacer uses the Discogs API to fetch artist, album, and track metadata
(genre, style, label, format, year, country, master release). This is the
primary data source for music catalog info as of 2026-06-10.

## Register an App

1. Sign in to <https://www.discogs.com>.
2. Go to <https://www.discogs.com/settings/developers>.
3. Click "Create an app" (or "New Application").
4. Fill in:
   - **Name:** Pacer
   - **Description:** Music rating & review site
   - **URL:** <https://github.com/0xzhepyr/Pacer> (or your fork)
5. Save. Discogs will issue a **Consumer Key** and **Consumer Secret**.

## Configure Pacer

Set the following environment variables (in `.env` for local dev, or via your
hosting provider's dashboard for production):

```bash
DISCOGS_CONSUMER_KEY=your_consumer_key_here
DISCOGS_CONSUMER_SECRET=your_consumer_secret_here
# Optional: override User-Agent (default: "Pacer/1.0 +https://github.com/0xzhepyr/Pacer")
DISCOGS_USER_AGENT="Pacer/1.0 (your-email@example.com)"
```

> **Important:** Discogs requires a unique User-Agent per app. If you fork
> Pacer, change `DISCOGS_USER_AGENT` to identify your deployment (email
> recommended; Discogs uses it to contact you if your app misbehaves).

## Restart Pacer

```bash
python run.py
# or in production: restart your gunicorn process / redeploy
```

If env vars are missing, `discogs_configured()` returns False and Pacer
degrades gracefully: song pages hide the "Catalog" panel, search returns
503 with a helpful message. The rest of Pacer (ratings, comments, forum,
feed) continues to work.

## Rate Limits

- **Authenticated (with Consumer Key/Secret):** 240 requests per minute
- **Unauthenticated:** 25 requests per minute

Pacer's caching strategy:
- Artist data: cached in-memory for 7 days
- Release/master data: cached in-memory for 30 days
- Spotify preview URL (artist+title → spotify_id): cached in DB for 30 days

The in-memory caches reset on every Pacer restart. The DB cache survives
restarts.

## Troubleshooting

- **`[discogs] 401 on /...`**: Consumer Key/Secret invalid. Re-register the app.
- **`[discogs] 429 on /...`**: Rate limited. Pacer falls back to cache. If
  cache is empty, the affected feature (e.g. Catalog panel) is hidden.
- **`[discogs] 5xx on /...`**: Discogs is having issues. Wait a few minutes.
- **No "Catalog" panel on song page**: Either Discogs is not configured, or
  Discogs doesn't have a match for the track. Check `/admin` to see logs.
