# Pacer Feature Expansion — Design Spec

**Date:** 2026-05-19  
**Status:** Approved  
**Stack:** Flask + Blueprints, SQLite, HTMX, Pinata/IPFS, Spotify API

---

## Overview

Empat fitur baru untuk Pacer — music rating site bergaya Win98:

1. Artist pages (data dari Spotify API)
2. Embedded Spotify player (page embed + persistent mini player)
3. Personalizable profile pages (upload via IPFS, playlists, pinned songs)
4. X-style feed (posts + activity feed + like/reply/repost)

Urutan implementasi: Refactor → Artist Pages → Spotify Player → Profile Pages → X-style Feed

---

## 1. Architecture Refactor

### Motivasi

`app.py` saat ini 1474 baris monolith. Dengan 4 fitur baru, file ini akan membengkak ke 4000-5000 baris. Refactor ke Flask Blueprints untuk maintainability.

### Struktur Baru

```
pacer/
├── __init__.py              ← App factory, register blueprints, config
├── config.py               ← Environment variables, constants
├── db.py                   ← SQLite connection, schema DDL, migrations
├── helpers.py              ← login_required, template filters, utils
├── routes/
│   ├── __init__.py
│   ├── auth.py             ← /login, /signup, /logout
│   ├── profile.py          ← /u/<username>, /profile/edit, upload
│   ├── music.py            ← /songs, /albums, /artists
│   ├── feed.py             ← / (homepage feed), /posts, like/reply/repost
│   ├── blog.py             ← /blog, /bulletins
│   └── spotify.py          ← /spotify/*, /track/spotify/*, /album/spotify/*
├── services/
│   ├── __init__.py
│   ├── spotify.py          ← Spotify API client (token, search, fetch)
│   ├── pinata.py           ← Upload to Pinata, return IPFS CID
│   └── feed.py             ← Feed generation logic
├── static/
│   ├── style.css
│   ├── htmx.min.js
│   ├── spotify.js
│   └── uploads/            ← Temp staging before IPFS upload
├── templates/
│   ├── base.html           ← Layout + persistent mini player
│   ├── partials/           ← HTMX partial fragments
│   │   ├── feed_item.html
│   │   ├── feed_list.html
│   │   ├── player.html
│   │   └── like_button.html
│   ├── home.html
│   ├── profile.html
│   ├── artist.html
│   └── ... (existing templates)
└── run.py                  ← Entry point: init_db, seed, app.run
```

### HTMX Integration

- `hx-boost="true"` pada `<body>` — navigasi tanpa full reload, player tetap jalan
- Hanya `<main>` content yang di-swap saat navigasi
- Taskbar (termasuk mini player) persistent, tidak di-reload

### Migration Strategy

- Refactor tanpa mengubah behavior
- Semua existing URL tetap sama
- Pindahkan kode dari `app.py` ke modul masing-masing
- `app.py` lama dihapus setelah verified

---

## 2. Artist Pages

### Data Model

```sql
CREATE TABLE artists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    image_url TEXT,
    genres TEXT,              -- comma-separated
    popularity INTEGER,
    spotify_url TEXT,
    cached_at TIMESTAMP
);
```

Relasi:
- `songs` + kolom `artist_id INTEGER REFERENCES artists(id)`
- `albums` + kolom `artist_id INTEGER REFERENCES artists(id)`

### Spotify API Endpoints

- `GET /v1/artists/{id}` — info artist
- `GET /v1/artists/{id}/albums` — diskografi
- `GET /v1/artists/{id}/top-tracks` — top tracks

Cache: data artist refresh kalau `cached_at` > 24 jam.

### Routes

| Method | Path | Fungsi |
|--------|------|--------|
| GET | `/artists/<int:artist_id>` | Halaman artist |
| GET | `/artist/spotify/<spotify_id>` | Auto-import, redirect ke halaman artist |

### Halaman Artist — Konten

1. Header — nama, gambar besar, genre tags
2. Top Tracks — 5-10 lagu terpopuler, clickable + play button
3. Diskografi — grid album covers, sorted by year desc
4. Community ratings — average dari semua song/album artist di Pacer
5. Link ke Spotify profile

### Auto-import Flow

1. Cek artist di DB by `spotify_id`
2. Kalau belum ada → fetch Spotify API → insert
3. Redirect ke `/artists/<id>`
4. Top tracks dan albums di-fetch on-demand (cached 24 jam)

### Linking

- Halaman song/album: artist name → link ke `/artists/<id>`
- Search results: artist clickable

---

## 3. Embedded Spotify Player

### Dua Komponen

**A) Page Embed** — di halaman song/album/artist

```html
<iframe src="https://open.spotify.com/embed/track/{spotify_id}"
        width="100%" height="152" frameborder="0"
        allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture">
</iframe>
```

- Track: height 152px
- Album: height 352px (shows tracklist)
- Tidak perlu login Spotify — 30-detik preview untuk semua visitor

**B) Persistent Mini Player** — di taskbar bawah

```
┌─────────────────────────────────────────────────────────┐
│ [Start] │ ♫ Song Title - Artist  [◄◄] [▶/❚❚] [►►] │ 3:45 │
└─────────────────────────────────────────────────────────┘
```

- Styled Win98/Winamp aesthetic
- Track info dengan marquee scroll
- Play/pause, prev, next buttons (beveled Win98)
- Progress indicator
- Klik track info → navigate ke halaman song

### Persistent Player — Teknis

HTMX `hx-boost` membuat navigasi tanpa full page reload:
- Link internal di-intercept oleh HTMX
- Hanya `<main>` di-swap
- Taskbar + mini player iframe TIDAK di-reload
- Player tetap jalan saat navigasi

### Struktur base.html

```html
<body hx-boost="true">
  <div id="page-wrapper">
    <header>...</header>
    <main id="content" hx-target="this" hx-swap="innerHTML">
      {% block content %}{% endblock %}
    </main>
  </div>
  <div id="taskbar">
    <div id="start-menu">...</div>
    <div id="mini-player">
      <iframe id="spotify-mini" src="" allow="autoplay; encrypted-media"></iframe>
    </div>
    <div id="clock">...</div>
  </div>
</body>
```

### Play Interaction

1. User klik "play" di halaman manapun
2. JS update `src` pada `#spotify-mini` iframe
3. Mini player mulai play
4. Navigasi ke halaman lain — player tetap jalan

### State

- `localStorage` menyimpan `currentTrackSpotifyId`
- Refresh page → restore last played track
- Sepenuhnya client-side, tidak perlu backend state

### Limitasi

- Semua user (dengan/tanpa Spotify): 30-detik preview only
- Full playback memerlukan Spotify app (link "Open in Spotify" disediakan)

---

## 4. Personalizable Profile Pages

### Data Model — Extend `users`

```sql
ALTER TABLE users ADD COLUMN profile_pic_cid TEXT;
ALTER TABLE users ADD COLUMN background_cid TEXT;
ALTER TABLE users ADD COLUMN background_preset TEXT;
ALTER TABLE users ADD COLUMN status_message TEXT;
```

### Tabel Baru — Playlists

```sql
CREATE TABLE playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE playlist_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id),
    song_id INTEGER NOT NULL REFERENCES songs(id),
    position INTEGER NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(playlist_id, song_id)
);
```

### Tabel Baru — Pinned Songs

```sql
CREATE TABLE pinned_songs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    song_id INTEGER NOT NULL REFERENCES songs(id),
    position INTEGER NOT NULL,
    UNIQUE(user_id, song_id)
);
```

### Upload Flow (Pinata/IPFS)

1. User pilih file di form edit profile
2. Submit ke `/profile/upload` (multipart form)
3. Backend validasi: max 5MB, format jpg/png/gif/webp
4. Upload ke Pinata: `POST https://api.pinata.cloud/pinning/pinFileToIPFS`
5. Pinata return CID
6. Simpan CID di database
7. Tampilkan via `https://gateway.pinata.cloud/ipfs/{CID}`

### Background Options

**Preset** (built-in):
- `sky` — gradient biru (existing)
- `sunset` — gradient orange/pink (existing)
- `cyber` — dark neon (existing)
- `stars` — animated starfield
- `matrix` — green rain
- `vaporwave` — pink/purple grid
- `ocean` — wave pattern

**Custom** — upload gambar via Pinata, displayed as `background-image: cover`

### Profile Layout

```
┌─────────────────────────────────────────────┐
│ [Custom Background / Preset]                │
│                                             │
│  ┌──────┐                                   │
│  │ PFP  │  Display Name                     │
│  │      │  @username                        │
│  └──────┘  "status message here"            │
│                                             │
│  ┌─ About ──────────────────────────────┐   │
│  │ Headline, about me, fav bands, etc   │   │
│  └──────────────────────────────────────┘   │
│                                             │
│  ┌─ Pinned Songs ───────────────────────┐   │
│  │ ♫ Song 1  ♫ Song 2  ♫ Song 3        │   │
│  └──────────────────────────────────────┘   │
│                                             │
│  ┌─ Playlists ──────────────────────────┐   │
│  │ 📁 My Favorites (12 tracks)          │   │
│  │ 📁 Chill Vibes (8 tracks)            │   │
│  └──────────────────────────────────────┘   │
│                                             │
│  ┌─ Recent Reviews ─────────────────────┐   │
│  │ Song X - ★★★★☆ "Great track..."     │   │
│  └──────────────────────────────────────┘   │
│                                             │
│  ┌─ Wall ───────────────────────────────┐   │
│  │ (existing wall comments)             │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

### Routes

| Method | Path | Fungsi |
|--------|------|--------|
| POST | `/profile/upload` | Upload PFP/background ke Pinata |
| GET/POST | `/profile/playlists/new` | Buat playlist |
| GET | `/profile/playlists/<id>` | Lihat playlist |
| POST | `/profile/playlists/<id>/add` | Tambah song |
| POST | `/profile/playlists/<id>/remove` | Hapus song |
| POST | `/profile/pin/<song_id>` | Pin song |
| POST | `/profile/unpin/<song_id>` | Unpin song |

### Edit Profile Form

Extend form existing:
- File input profile picture (preview before upload)
- File input custom background
- Dropdown preset background
- Text input status message
- Section manage pinned songs (search + add)

---

## 5. X-style Feed

### Data Model

```sql
CREATE TABLE posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,              -- max 280 chars
    song_id INTEGER REFERENCES songs(id),
    album_id INTEGER REFERENCES albums(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    type TEXT NOT NULL,             -- 'rating', 'review', 'playlist_create'
    song_id INTEGER REFERENCES songs(id),
    album_id INTEGER REFERENCES albums(id),
    rating_stars INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE likes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    post_id INTEGER REFERENCES posts(id),
    activity_id INTEGER REFERENCES activities(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, post_id),
    UNIQUE(user_id, activity_id)
);

CREATE TABLE replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    post_id INTEGER REFERENCES posts(id),
    activity_id INTEGER REFERENCES activities(id),
    body TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reposts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    post_id INTEGER REFERENCES posts(id),
    activity_id INTEGER REFERENCES activities(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, post_id),
    UNIQUE(user_id, activity_id)
);
```

### Timeline Assembly

Global feed — gabungan posts + activities + reposts, sorted by `created_at DESC`:

```sql
SELECT 'post' as type, id, user_id, body, created_at FROM posts
UNION ALL
SELECT 'activity' as type, id, user_id, type as body, created_at FROM activities
UNION ALL
SELECT 'repost' as type, r.id, r.user_id, NULL, r.created_at FROM reposts r
ORDER BY created_at DESC
LIMIT 20 OFFSET ?
```

MVP: global timeline (semua user). Follow system bisa ditambah nanti.

### Feed Item Display

**Manual post:**
```
┌─────────────────────────────────────────────┐
│ [PFP] @username · 2 min ago                 │
│                                             │
│ "Just discovered this album, absolute       │
│  masterpiece"                               │
│                                             │
│ ┌─ 🎵 Album Name - Artist ──────────────┐  │
│ │ [cover art]  ★★★★★                    │  │
│ └────────────────────────────────────────┘  │
│                                             │
│ ♡ 3    💬 1    🔁 2                         │
└─────────────────────────────────────────────┘
```

**Activity (auto-generated):**
```
┌─────────────────────────────────────────────┐
│ [PFP] @username rated a song · 5 min ago    │
│                                             │
│ ┌─ 🎵 Song Title - Artist ──────────────┐  │
│ │ ★★★★☆ (4/5)                           │  │
│ └────────────────────────────────────────┘  │
│                                             │
│ ♡ 1    💬 0    🔁 0                         │
└─────────────────────────────────────────────┘
```

### Routes

| Method | Path | Fungsi |
|--------|------|--------|
| GET | `/` | Homepage feed (HTMX infinite scroll) |
| POST | `/posts` | Buat post baru |
| POST | `/posts/<id>/like` | Like post |
| POST | `/posts/<id>/unlike` | Unlike |
| POST | `/posts/<id>/reply` | Reply |
| POST | `/posts/<id>/repost` | Repost |
| POST | `/activities/<id>/like` | Like activity |
| POST | `/activities/<id>/reply` | Reply activity |
| POST | `/activities/<id>/repost` | Repost activity |
| GET | `/feed/more?offset=N` | Load more (HTMX partial) |

### HTMX Interactions

- **Infinite scroll**: `hx-get="/feed/more?offset=20" hx-trigger="revealed" hx-swap="afterend"`
- **Like**: `hx-post="/posts/1/like" hx-swap="outerHTML"` — swap ke liked state
- **Reply**: inline form, submit via `hx-post`, append reply
- **Repost**: satu klik, counter update via swap

### Auto-Activity Generation

Insert ke `activities` saat user:
- Rate song/album → type `'rating'`
- Write review → type `'review'`
- Create playlist → type `'playlist_create'`

### Compose Box

```
┌─ New Post ──────────────────────────────────┐
│ ┌────────────────────────────────────────┐  │
│ │ What's on your mind?                   │  │
│ └────────────────────────────────────────┘  │
│ [🎵 Attach Song] [📀 Attach Album] [Post]  │
└─────────────────────────────────────────────┘
```

Max 280 karakter. Optional attach song/album via search.

### Relationship with Existing Features

- **Bulletins** — tetap ada sebagai fitur terpisah (announcements). Tidak masuk feed.
- **Blog/threads** — tetap ada sebagai forum terpisah. Tidak masuk feed.
- **Wall comments** — tetap ada di profile. Tidak masuk feed.
- Feed adalah layer social baru yang berdiri sendiri di atas fitur existing.

---

## Environment Variables (New)

```
PINATA_API_KEY=...
PINATA_SECRET_KEY=...
PINATA_GATEWAY_URL=https://gateway.pinata.cloud/ipfs/
```

---

## Dependencies (New)

Tambah di `requirements.txt`:
```
Flask==3.0.3
requests>=2.31
```

Tidak ada dependency baru — `requests` sudah cukup untuk Pinata API. HTMX di-serve sebagai static file.

---

## Implementation Order

1. **Refactor** — Pecah `app.py` ke Blueprints, pastikan semua existing behavior tetap
2. **Artist Pages** — Tabel baru, Spotify fetch, halaman artist
3. **Spotify Player** — HTMX boost di base.html, page embed, mini player di taskbar
4. **Profile Pages** — Pinata upload, playlists, pinned songs, new profile layout
5. **X-style Feed** — Posts, activities, likes/replies/reposts, infinite scroll feed
