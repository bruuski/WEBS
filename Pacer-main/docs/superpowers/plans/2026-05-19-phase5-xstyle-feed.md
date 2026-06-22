# Phase 5: X-style Feed - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Twitter/X-style feed to the homepage with manual posts, auto-generated activity items, likes, replies, reposts, and infinite scroll.

**Architecture:** New tables (posts, activities, likes, replies, reposts), new feed blueprint routes, HTMX-powered infinite scroll and interactions, compose box with song/album attachment.

**Tech Stack:** Flask, SQLite, HTMX, Jinja2, CSS.

**Prerequisite:** Phases 1-4 must be complete.

---

## File Structure

```
pacer/
  db.py                    (MODIFY - add posts, activities, likes, replies, reposts tables)
  services/
    feed.py              (NEW - feed assembly, activity generation)
  routes/
    feed.py              (MODIFY - rewrite homepage as feed, add post/like/reply/repost routes)
  templates/
    home.html            (MODIFY - rewrite as feed timeline)
    partials/
      feed_item.html   (NEW - single feed item partial for HTMX)
      feed_list.html   (NEW - list of feed items)
      compose_box.html (NEW - post compose form)
      like_button.html (NEW - like button partial)
  static/
    style.css            (MODIFY - feed styles)
```

---

## Task 1: Add feed tables to database

**Files:** Modify pacer/db.py

Add these tables to SCHEMA: posts (id, user_id, body max 280, song_id nullable, album_id nullable, created_at), activities (id, user_id, type, song_id, album_id, rating_stars, created_at), likes (id, user_id, post_id, activity_id, created_at, UNIQUE constraints), replies (id, user_id, post_id, activity_id, body, created_at), reposts (id, user_id, post_id, activity_id, created_at, UNIQUE constraints).

- [ ] Add tables to SCHEMA string
- [ ] Run app to verify schema creates
- [ ] Commit: feat(feed): add feed tables to schema

---

## Task 2: Create feed service

**Files:** Create pacer/services/feed.py

Functions to implement:

- get_timeline(offset=0, limit=20): UNION ALL query combining posts + activities + reposts, ORDER BY created_at DESC, LIMIT/OFFSET. Join with users table for display info.
- create_activity(user_id, type, song_id=None, album_id=None, rating_stars=None): Insert into activities table.
- get_feed_item_counts(item_type, item_id): Count likes, replies, reposts for a given item.
- has_user_liked(user_id, item_type, item_id): Check if user already liked.

- [ ] Create services/feed.py with all functions
- [ ] Commit: feat(feed): add feed service module

---

## Task 3: Add feed routes

**Files:** Modify pacer/routes/feed.py

Routes to implement:

- GET / : Homepage with feed timeline (first 20 items) + compose box
- GET /feed/more?offset=N : HTMX partial returning next 20 feed items (hx-swap afterend)
- POST /posts : Create new post (validate max 280 chars, optional song_id/album_id)
- POST /posts/id/like : Like post, return updated like button partial
- POST /posts/id/unlike : Unlike post, return updated like button partial
- POST /posts/id/reply : Reply to post, return new reply HTML
- POST /posts/id/repost : Repost, return updated repost button
- POST /activities/id/like : Like activity
- POST /activities/id/reply : Reply to activity
- POST /activities/id/repost : Repost activity

- [ ] Rewrite home route to serve feed
- [ ] Add /feed/more route for infinite scroll
- [ ] Add post CRUD routes
- [ ] Add like/reply/repost routes for posts
- [ ] Add like/reply/repost routes for activities
- [ ] Commit: feat(feed): add feed routes with HTMX interactions

---

## Task 4: Create feed templates

**Files:** Create/modify templates

templates/home.html:
- Compose box at top (logged-in users only)
- Feed items container
- Infinite scroll trigger div at bottom with hx-get=/feed/more?offset=20 hx-trigger=revealed hx-swap=afterend

templates/partials/feed_item.html:
- User PFP/emoji + username link + relative timestamp
- Post body text OR activity description (e.g. "rated Song X 4 stars")
- Optional attached song/album card with cover art
- Action bar: like button + count, reply button + count, repost button + count

templates/partials/compose_box.html:
- Win98 styled textarea (max 280 chars, char counter)
- Attach Song button (opens search modal/dropdown)
- Attach Album button
- Post button (hx-post=/posts, hx-target=feed-list, hx-swap=afterbegin)

templates/partials/like_button.html:
- Heart icon (filled if liked, empty if not)
- Count number
- hx-post to toggle like

- [ ] Create all template files
- [ ] Commit: feat(feed): add feed templates and partials

---

## Task 5: Integrate activity generation into existing routes

**Files:** Modify pacer/routes/music.py, pacer/routes/profile.py

In music.py song_detail POST (rating):
- After inserting/updating rating, call create_activity(user_id, "rating", song_id=song_id, rating_stars=stars)

In music.py album_detail POST (rating):
- After inserting/updating album rating, call create_activity(user_id, "rating", album_id=album_id, rating_stars=stars)

In profile.py new_playlist POST:
- After creating playlist, call create_activity(user_id, "playlist_create")

- [ ] Add activity generation to song rating
- [ ] Add activity generation to album rating
- [ ] Add activity generation to playlist creation
- [ ] Commit: feat(feed): integrate activity generation into existing routes

---

## Task 6: Add feed CSS styles

**Files:** Modify static/style.css

Styles to add:
- .feed-timeline: max-width 600px, margin auto
- .feed-item: Win98 panel (beveled border), padding, margin-bottom
- .feed-item-header: flex, avatar + username + timestamp
- .feed-item-body: text content, word-wrap
- .feed-item-attachment: song/album card with cover art thumbnail
- .feed-item-actions: flex row, gap, action buttons
- .compose-box: Win98 inset border textarea, button row
- .btn-like, .btn-reply, .btn-repost: small icon buttons, hover state
- .liked state: filled heart, color change

- [ ] Add all feed styles
- [ ] Commit: feat(feed): add feed timeline styles

---

## Task 7: Verify feed end-to-end

- [ ] Run app: python run.py
- [ ] Create a post via compose box, verify it appears at top of feed
- [ ] Like a post - verify HTMX swap (no page reload, heart fills)
- [ ] Reply to a post - verify reply appears inline
- [ ] Repost - verify repost counter updates
- [ ] Rate a song, go to homepage, verify activity item appears
- [ ] Scroll down past 20 items, verify infinite scroll loads more
- [ ] Final commit: feat(feed): complete X-style feed implementation
