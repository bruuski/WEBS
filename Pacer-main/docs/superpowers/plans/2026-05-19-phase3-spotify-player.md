# Phase 3: Embedded Spotify Player — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Spotify embed player on song/album/artist pages and a persistent mini player in the taskbar that keeps playing during navigation via HTMX boost.

**Architecture:** Add HTMX library, enable `hx-boost` on body for SPA-like navigation, embed Spotify iframes on detail pages, add mini player widget to taskbar in `base.html`. Small JS module for player state management.

**Tech Stack:** Flask, HTMX, Spotify Embed (iframe), vanilla JS, CSS.

**Prerequisite:** Phase 1 (Architecture Refactor) and Phase 2 (Artist Pages) must be complete.

---

## File Structure

```
pacer/
├── static/
│   ├── htmx.min.js         (NEW - HTMX library, downloaded)
│   ├── player.js            (NEW - mini player state management)
│   └── style.css            (MODIFY - mini player + embed styles)
├── templates/
│   ├── base.html            (MODIFY - add HTMX, hx-boost, mini player in taskbar)
│   ├── song.html            (MODIFY - add Spotify embed)
│   ├── album.html           (MODIFY - add Spotify embed)
│   └── artist.html          (MODIFY - add Spotify embed for top track)
```

---

## Task 1: Add HTMX library

**Files:**
- Create: `static/htmx.min.js`

- [ ] **Step 1: Download HTMX**

```bash
curl -o static/htmx.min.js https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js
```

- [ ] **Step 2: Commit**

```bash
git add static/htmx.min.js
git commit -m "feat(player): add HTMX library"
```

---

## Task 2: Enable HTMX boost in base.html

**Files:**
- Modify: `templates/base.html`

- [ ] **Step 1: Add HTMX script tag in head**

Add before closing `</head>`:

```html
<script src="{{ url_for('static', filename='htmx.min.js') }}"></script>
```

- [ ] **Step 2: Add hx-boost to body**

Change `<body>` to:

```html
<body hx-boost="true">
```

- [ ] **Step 3: Wrap page content in main with hx-target**

Wrap the existing `{% block content %}` area:

```html
<main id="content" hx-target="this" hx-swap="innerHTML show:window:top">
  {% block content %}{% endblock %}
</main>
```

The taskbar must be OUTSIDE of `<main>` so it is never swapped during navigation.

- [ ] **Step 4: Verify navigation still works**

```bash
python run.py
```

Click around the site — pages should load without full reload (check: taskbar doesn't flash/reload).

- [ ] **Step 5: Commit**

```bash
git add templates/base.html
git commit -m "feat(player): enable HTMX boost for SPA-like navigation"
```

---

## Task 3: Add Spotify embed to song page

**Files:**
- Modify: `templates/song.html`

- [ ] **Step 1: Add embed iframe**

Add after the song header/info section, before ratings:

```html
{% if song["spotify_id"] %}
<div class="spotify-embed">
  <iframe
    src="https://open.spotify.com/embed/track/{{ song['spotify_id'] }}?theme=0"
    width="100%" height="152" frameborder="0"
    allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
    loading="lazy">
  </iframe>
</div>
{% endif %}
```

- [ ] **Step 2: Add play button that sends to mini player**

Add a button next to the embed:

```html
{% if song["spotify_id"] %}
<button class="btn-play-mini"
        onclick="playInMini('{{ song['spotify_id'] }}', '{{ song['title'] }}', '{{ song['artist'] }}')">
  Play in Mini Player
</button>
{% endif %}
```

- [ ] **Step 3: Commit**

```bash
git add templates/song.html
git commit -m "feat(player): add Spotify embed to song page"
```

---

## Task 4: Add Spotify embed to album page

**Files:**
- Modify: `templates/album.html`

- [ ] **Step 1: Add album embed iframe**

```html
{% if album["spotify_id"] %}
<div class="spotify-embed">
  <iframe
    src="https://open.spotify.com/embed/album/{{ album['spotify_id'] }}?theme=0"
    width="100%" height="352" frameborder="0"
    allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
    loading="lazy">
  </iframe>
</div>
{% endif %}
```

- [ ] **Step 2: Commit**

```bash
git add templates/album.html
git commit -m "feat(player): add Spotify embed to album page"
```

---

## Task 5: Add Spotify embed to artist page

**Files:**
- Modify: `templates/artist.html`

- [ ] **Step 1: Add embed for top track in artist page**

In the top tracks section, add play buttons for each track:

```html
{% for track in top_tracks %}
<li>
  <button class="btn-play-mini"
          onclick="playInMini('{{ track['spotify_id'] }}', '{{ track['name'] }}', '{{ artist['name'] }}')">
    ▶
  </button>
  <a href="{{ url_for('music.track_from_spotify', spotify_id=track['spotify_id']) }}">
    {{ track["name"] }}
  </a>
  <span class="track-album">{{ track["album_name"] }}</span>
</li>
{% endfor %}
```

- [ ] **Step 2: Commit**

```bash
git add templates/artist.html
git commit -m "feat(player): add play buttons to artist page tracks"
```

---

## Task 6: Create persistent mini player in taskbar

**Files:**
- Modify: `templates/base.html`

- [ ] **Step 1: Add mini player HTML to taskbar**

Inside the taskbar div, between start menu and clock:

```html
<div id="mini-player" class="mini-player">
  <div class="mini-player-info">
    <span id="mini-player-title" class="mini-player-title">No track</span>
  </div>
  <div class="mini-player-controls">
    <button id="mini-prev" class="btn-taskbar" onclick="miniPrev()">◄◄</button>
    <button id="mini-play" class="btn-taskbar" onclick="miniToggle()">▶</button>
    <button id="mini-next" class="btn-taskbar" onclick="miniNext()">►►</button>
  </div>
  <iframe id="spotify-mini-iframe"
          src=""
          width="0" height="0"
          allow="autoplay; encrypted-media"
          style="display:none;">
  </iframe>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add templates/base.html
git commit -m "feat(player): add mini player widget to taskbar"
```

---

## Task 7: Create player.js

**Files:**
- Create: `static/player.js`

- [ ] **Step 1: Create player.js with state management**

```javascript
// Mini Player State
const MiniPlayer = {
  currentTrack: null,
  queue: [],
  queueIndex: -1,

  init() {
    // Restore from localStorage
    const saved = localStorage.getItem("miniPlayerTrack");
    if (saved) {
      try {
        this.currentTrack = JSON.parse(saved);
        this.updateDisplay();
        // Don't auto-play on page load, just show last track
      } catch (e) {}
    }
  },

  play(spotifyId, title, artist) {
    this.currentTrack = { spotifyId, title, artist };
    localStorage.setItem("miniPlayerTrack", JSON.stringify(this.currentTrack));
    this.updateIframe();
    this.updateDisplay();
  },

  updateIframe() {
    if (!this.currentTrack) return;
    const iframe = document.getElementById("spotify-mini-iframe");
    if (iframe) {
      iframe.src = `https://open.spotify.com/embed/track/${this.currentTrack.spotifyId}?theme=0&autoplay=1`;
      iframe.style.display = "block";
      iframe.width = "80";
      iframe.height = "80";
    }
  },

  updateDisplay() {
    const titleEl = document.getElementById("mini-player-title");
    if (titleEl && this.currentTrack) {
      titleEl.textContent = `${this.currentTrack.title} - ${this.currentTrack.artist}`;
    }
  },

  toggle() {
    // Spotify embed doesn't expose play/pause API easily
    // This is a visual indicator only
    const btn = document.getElementById("mini-play");
    if (btn) {
      btn.textContent = btn.textContent === "▶" ? "❚❚" : "▶";
    }
  }
};

// Global functions called from onclick
function playInMini(spotifyId, title, artist) {
  MiniPlayer.play(spotifyId, title, artist);
}

function miniToggle() {
  MiniPlayer.toggle();
}

function miniPrev() {
  // Future: queue navigation
}

function miniNext() {
  // Future: queue navigation
}

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
  MiniPlayer.init();
});

// Re-initialize after HTMX swap (player.js persists but DOM might change)
document.addEventListener("htmx:afterSwap", () => {
  // Mini player is outside main, so it persists. No action needed.
});
```

- [ ] **Step 2: Add script tag to base.html**

Add after htmx script:

```html
<script src="{{ url_for('static', filename='player.js') }}"></script>
```

- [ ] **Step 3: Commit**

```bash
git add static/player.js templates/base.html
git commit -m "feat(player): add player.js with state management"
```

---

## Task 8: Add mini player and embed CSS

**Files:**
- Modify: `static/style.css`

- [ ] **Step 1: Add mini player styles**

```css
/* Mini Player in Taskbar */
.mini-player {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  margin: 0 8px;
  overflow: hidden;
}
.mini-player-info {
  flex: 1;
  overflow: hidden;
}
.mini-player-title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 11px;
  font-family: "VT323", monospace;
  display: block;
}
.mini-player-controls {
  display: flex;
  gap: 2px;
}
.btn-taskbar {
  background: #c0c0c0;
  border: 2px outset #fff;
  padding: 1px 4px;
  font-size: 10px;
  cursor: pointer;
  font-family: monospace;
}
.btn-taskbar:active {
  border-style: inset;
}

/* Spotify Embed */
.spotify-embed {
  margin: 12px 0;
  border: 2px inset #808080;
}

/* Play in Mini button */
.btn-play-mini {
  background: #c0c0c0;
  border: 2px outset #fff;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}
.btn-play-mini:active {
  border-style: inset;
}
```

- [ ] **Step 2: Commit**

```bash
git add static/style.css
git commit -m "feat(player): add mini player and embed styles"
```

---

## Task 9: Verify player end-to-end

- [ ] **Step 1: Run the app**

```bash
python run.py
```

- [ ] **Step 2: Test page embed**

Visit a song page with a Spotify ID. Verify the Spotify embed iframe loads and plays 30s preview.

- [ ] **Step 3: Test mini player**

Click "Play in Mini Player" on a song page. Verify:
- Mini player in taskbar shows track title
- Spotify mini iframe loads
- Navigate to another page — mini player stays visible and doesn't reset

- [ ] **Step 4: Test persistence**

Refresh the page. Verify mini player shows last played track title (from localStorage).

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(player): complete Spotify player implementation"
```
