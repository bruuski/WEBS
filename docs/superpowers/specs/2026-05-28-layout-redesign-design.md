# Pacer Layout Redesign + Multi-Theme System — Design Spec

**Date:** 2026-05-28  
**Status:** Approved  
**Scope:** New layout structure (Tumblr-inspired) + 3 switchable themes

---

## Overview

Redesign Pacer's layout from the current Win98-only top-nav + taskbar structure to a Tumblr-inspired layout with left sidebar + top nav. Add a "Change Palette" system allowing users to switch between 3 visual themes while keeping the same layout structure.

---

## Layout Structure (All Themes)

```
┌──────────┬──────────────────────────────────────────────┐
│          │  [Trending/Home] [Charts] [Search] [Profile] │
│  PACER   ├──────────────────────────────────────────────┤
│          │                                              │
│  Blog    │              Main Content                    │
│          │                                              │
│  Palette │                                              │
│          │                                              │
│  Login/  │                                              │
│  Signup  │                                              │
│          │                                              │
└──────────┴──────────────────────────────────────────────┘
```

### Left Sidebar (fixed)
- Logo + Name (PACER)
- Blog (link to /blog — communities/threads)
- Change Palette (opens theme picker)
- Auth: Sign up / Log in (if not logged in), or @username / Log Off (if logged in)

### Top Nav (horizontal, above content)
- Trending (Home / X-style feed) — `/`
- Charts — `/songs`
- Search — `/search`
- Profile — `/u/<username>` (only if logged in)

### Main Content Area
- Takes remaining space to the right of sidebar and below top nav
- All existing page content renders here

### Mini Player
- Stays at bottom of page (persistent, same as now)

---

## 3 Themes

### 1. Modern (Dark)
- Background: #1a1a2e or similar dark
- Text: #e0e0e0 (light gray/white)
- Accent: #6c63ff or brand color
- Cards: slightly lighter dark (#2d2d44)
- Borders: subtle, 1px solid rgba(255,255,255,0.1)
- Font: system sans-serif (Inter, -apple-system, etc.)
- Buttons: rounded, filled accent color
- No beveled edges, no taskbar

### 2. Win98 (Retro)
- Background: #c0c0c0 (classic gray)
- Text: #000
- Accent: navy blue title bars
- Cards: beveled panels (outset/inset borders)
- Font: Tahoma, MS Sans Serif
- Buttons: 3D beveled (outset border)
- Taskbar at bottom (optional, could be removed since sidebar replaces it)

### 3. Clean (Light Minimal)
- Background: #ffffff
- Text: #333
- Accent: #0066cc or subtle blue
- Cards: white with light border or shadow
- Borders: 1px solid #e0e0e0
- Font: system sans-serif
- Buttons: simple outlined or filled, no effects
- Minimal decoration

---

## Theme Switching

### Storage
- `localStorage` for immediate effect (client-side)
- `users.palette` column in DB for persistence across devices (logged-in users)

### Mechanism
1. User clicks "Change Palette" in sidebar
2. Dropdown/popover shows 3 options (Modern, Win98, Clean)
3. On select: 
   - Set `<body>` class to `theme-modern`, `theme-win98`, or `theme-clean`
   - Save to localStorage
   - If logged in, POST to `/profile/palette` to save in DB
4. On page load: read from localStorage (fast) or DB (fallback)

### CSS Architecture
```css
/* Base layout (shared) */
.sidebar { ... }
.top-nav { ... }
.main-content { ... }

/* Theme: Modern */
body.theme-modern { --bg: #1a1a2e; --text: #e0e0e0; ... }
body.theme-modern .sidebar { ... }
body.theme-modern .card { ... }

/* Theme: Win98 */
body.theme-win98 { --bg: #c0c0c0; --text: #000; ... }
body.theme-win98 .card { border: 2px outset #fff; ... }

/* Theme: Clean */
body.theme-clean { --bg: #fff; --text: #333; ... }
body.theme-clean .card { border: 1px solid #e0e0e0; ... }
```

---

## Data Model Change

```sql
ALTER TABLE users ADD COLUMN palette TEXT DEFAULT 'modern';
```

---

## Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/profile/palette` | Save palette preference (JSON: {"palette": "modern"}) |

---

## Migration from Current Layout

- Remove: masthead (logo area at top), horizontal nav bar, taskbar (Win98 only keeps it as decorative)
- Add: left sidebar (fixed), top nav bar (inside content area)
- `base.html` completely rewritten
- All existing templates keep `{% block content %}` — only the wrapper changes
- Mini player moves from taskbar to a fixed bottom bar

---

## Implementation Order

1. Add `palette` column to users table
2. Rewrite `base.html` with new layout (sidebar + top nav + main content)
3. Create CSS variables system with 3 theme definitions
4. Add palette switcher UI + JS
5. Add `/profile/palette` route
6. Migrate existing Win98 styles to work under `body.theme-win98`
7. Create Modern theme styles
8. Create Clean theme styles
9. Test all pages under all 3 themes
10. Remove old taskbar/masthead code

---

## Key Decisions

- Layout is the SAME for all themes — only visual styling changes
- Default theme for new users: Modern (dark)
- Theme preference saved in both localStorage (fast) and DB (persistent)
- Mini player stays as fixed bottom bar in all themes
- HTMX boost continues to work (sidebar + mini player outside `<main>`)
- Mobile: sidebar collapses to hamburger menu
