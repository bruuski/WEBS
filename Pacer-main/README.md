# Pacer

A music ratings + reviews site powered by **Discogs** (catalog metadata) and **Spotify** (audio previews + trending feed). Y2K / Windows-98 aesthetic — chrome italic brand, a Napster-cat-meets-Spotify logo, sky-and-clouds wallpaper, beveled gray windows for every panel, a 7-segment LCD readout for the song score, Post-It featured reviews, threaded posts with greentext, and a working Win98 taskbar (Start menu + live clock). Flask + SQLite, no build step.

## Features

- Sign up / log in (scrypt-hashed passwords)
- Profile with avatar, mood, headline, About Me, favorite artists, and three themes (sky / sunset / cyber)
- **Trending tracks** on the home page, pulled live from Spotify's "Today's Top Hits" (with a 10-minute cache and a New Releases fallback)
- **Discogs-powered catalog info** on song and album pages — label, format, year, country, catalog #, plus accurate style tags (e.g. "Shoegaze", "Dream Pop")
- **Browse by style** with a multi-select filter powered by Discogs (`/songs?style=Shoegaze`)
- Click any trending cover to land on the rating page for that track — Pacer auto-creates the local song record from Spotify + Discogs metadata on first click
- Rate any track 1–5 stars and write a review (one rating per user per song, editable)
- Pitchfork-style decimal score `7.8/10` derived from the average, rendered as a red 7-segment LCD
- 4chan-style threaded posts (`>` becomes greentext, `>>` becomes a quotelink) on profiles and bulletins
- Genius-style featured review block on each track page (styled here as a Post-It note)
- Browse / search / sort the chart (top rated, hottest, newest, A–Z)
- Embedded Spotify player on any track that has a `spotify_id`
- "Connect Spotify" on your own profile → shows your last-4-weeks top tracks
- Win98 taskbar with a real Start menu and a live clock
- **Blog** — a community thread board where logged-in users start their own threads (subject + body) and others reply; recent threads also show up in a column on the home page

The dedicated "submit a track" page has been removed — tracks enter the local DB the first time someone clicks a Spotify trending pick.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your Spotify + Discogs keys
python run.py
```

Then open <http://127.0.0.1:5000>. The first run creates `pacer.db` in the project root and seeds demo users and songs. To deploy to Railway, see [`DEPLOYMENT.md`](DEPLOYMENT.md).

## Spotify configuration

Spotify is now used only for two things: 30-second audio preview URLs and the "Today's Top Hits" featured playlist that drives the homepage trending grid. Without these vars, the trending grid is empty and tracks won't have 30-second previews, but the rest of the app (catalog, ratings, search) still works.

```bash
export SPOTIFY_CLIENT_ID=xxx
export SPOTIFY_CLIENT_SECRET=xxx
export SPOTIFY_REDIRECT_URI=http://127.0.0.1:5000/spotify/callback   # default
export SPOTIFY_TRENDING_PLAYLIST=37i9dQZF1DXcBWIGoYBM5M               # default = Today's Top Hits
```

1. Create an app at <https://developer.spotify.com/dashboard>.
2. Add `http://127.0.0.1:5000/spotify/callback` (or whatever your host is) as a Redirect URI.
3. Copy the Client ID and Client Secret into the env vars above.
4. Restart the app.

**Capabilities:**
- Trending feed and track search both use the Client Credentials flow (no per-user login needed).
- "Connect Spotify" on a profile uses the Authorization Code flow and stores access + refresh tokens per user.
- The "Your top tracks" widget on your own profile calls `/me/top/tracks` with the user's stored token.

## Discogs configuration

Discogs is the primary source for artist, album, and track metadata (genre, style, label, format, year, country). Pacer's "Catalog" panel on song and album pages, the search box, and the Discogs-aware deep links (`/track/spotify/<discogs_id>`, `/album/spotify/<discogs_id>`) all read from Discogs.

Without these vars, the Catalog panel is hidden and search returns a 503, but everything else (ratings, comments, forum, feed, playlist import) continues to work.

```bash
export DISCOGS_CONSUMER_KEY=xxx
export DISCOGS_CONSUMER_SECRET=xxx
# Optional: override User-Agent
# export DISCOGS_USER_AGENT="Pacer/1.0 (your-email@example.com)"
```

1. Sign in to <https://www.discogs.com>.
2. Go to <https://www.discogs.com/settings/developers>.
3. Click "Create an app" and fill in name (Pacer), description, URL.
4. Save. Discogs will issue a **Consumer Key** and **Consumer Secret**.
5. Copy them into the env vars above.
6. Restart the app.

**Rate limit:** 240 requests per minute authenticated. Pacer caches aggressively: artist data in-memory for 7 days, release/master data in-memory for 30 days, Spotify preview lookups in DB for 30 days.

**Setup details:** see `docs/discogs-setup.md`.

## Demo accounts

All passwords are `password` except `tom` which is `myspace`:

- `tom`, `brunette`, `joey`, `kamal`, `dustyn`, `layouts`, `anon`

## Project layout

```
pacer/
  __init__.py        # Flask app factory; init-db / seed CLI
  config.py          # env-var reading (Spotify, Discogs, Pinata)
  db.py              # SQLite connection + schema migration
  seed.py            # demo data seeding
  routes/
    feed.py          # home page (trending + activity)
    music.py         # browse, song/album/artist detail, deep links
    spotify.py       # OAuth + search proxy
    blog.py          # community threads
    profile.py       # user profiles, playlists
    admin.py         # admin dashboard, table viewer, SQL runner
  services/
    spotify.py       # slim Spotify client (trending + preview lookup)
    discogs.py       # primary catalog client (OAuth 1.0a, in-mem cache)
    feed.py          # activity feed helpers
  helpers.py         # current_user, login_required, etc.
run.py               # dev server entry point
requirements.txt
.env.example         # all env vars documented
static/
  style.css          # Y2K Win98 / Bliss-sky theme
templates/
  base.html          # masthead with cat-logo, taskbar, start menu
  home.html          # trending grid + feed
  search.html        # Discogs-powered music search
  song.html          # song detail (with Discogs catalog panel)
  album.html         # album detail (Discogs tracklist)
  artist.html        # artist detail (Discogs bio)
  browse.html        # chart + style filter
docs/
  discogs-setup.md   # Discogs credentials walkthrough
```
