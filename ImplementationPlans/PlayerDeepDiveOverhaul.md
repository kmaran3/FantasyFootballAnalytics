# Player Deep Dive Overhaul

## Overview

Replace the broken rankings page inline deep dive and rosters page with a unified, two-level player detail system:

- **Level 1 — Inline Deep Dive** (rankings page, existing row expansion): show headshot, 2025 stats, fantasy points, and a "See More" / "Compare" button
- **Level 2 — Full Player Page** (new dedicated route `/player/<name>`): the complete profile currently on the rosters page (bio, team grades, season history chart, season history table, compare player)
- **Hide** the Rosters nav tab entirely

---

## Current State

### What's broken in the inline deep dive
- `playerDetails` is built from pkl files (max season 2024) and passed as a giant JSON blob at page load — so Puka Nacua and other 2025 players not in the old pkl files show "Stats not available"
- The schedule section hardcodes "2024 Season — First 5 Games" and uses `teamSchedule` which is either empty or stale
- No headshot shown
- No "See More" or "Compare" button

### What the rosters page does well (to be preserved in Level 2)
- ESPN headshot via `espn_id`
- Bio table (team, position, height, weight, birth date, college, draft info)
- Team grades bar chart
- Fantasy points by season (Chart.js line chart)
- Season history table
- Compare player side-by-side panel

---

## Implementation Plan

### Step 1 — Fix the inline deep dive (Level 1)

**Backend: `views.py`**

1. Stop passing `playerDetails` as a static JSON blob at page load — it's stale and missing 2025 players
2. Create a new API endpoint `GET /player_quick_stats?name=<name>&pos=<pos>&team=<team>` that returns:
   - `espn_id` (looked up from `teamsPastRoster.pkl` by player name)
   - `stats`: 2025 season stats from `_nfl_seasonal` (same source as the rosters `/player_stats` endpoint — `player_display_name` match)
   - `fantasy_points`: total 2025 PPR fantasy points
   - `ranking`: predicted PPG, VBD, ADP from `_model_table`

**Frontend: `rankings.html`**

3. When a player row is clicked and the deep dive panel opens, fire a fetch to `/player_quick_stats` (lazy-loaded per player, not all at once at page load)
4. Render the panel with:
   - **Left**: ESPN headshot (`https://a.espncdn.com/i/headshots/nfl/players/full/{espn_id}.png`), fallback hidden on error
   - **Center**: 2025 season stats table (position-specific: QB gets pass yds/TDs/INT/rush, RB gets rush yds/carries/rec/rec yds, WR/TE gets targets/rec/catch%/rec yds) + total fantasy points
   - **Right**: Model metrics (Predicted PPG, VBD, ADP)
   - **Bottom row**: "See Full Profile →" button (links to `/player/<encoded-name>?pos=<pos>&team=<team>`) and "Compare" button (links to `/player/<encoded-name>?pos=<pos>&team=<team>&compare=true`)
5. Remove the hardcoded "2024 Season — First 5 Games" schedule section entirely
6. Show a loading spinner while fetching

---

### Step 2 — Create the Full Player Page (Level 2)

**Backend: `views.py`**

1. Add route `GET /player/<name>` that renders `player_profile.html`
2. Pass to template:
   - `player_name`, `pos`, `team` (from query params)
   - `espn_id` (from `teamsPastRoster.pkl`)
   - `roster_stats_json` (same `_roster_stats` dict already computed)
   - `fp_thresholds_json` (same as rosters page)
   - `compare` flag (bool, from query param)
   - `back_url` = referrer or `/rankings/ppr` as default

**Frontend: new `player_profile.html`**

3. Copy the player profile panel HTML/JS from `rosters.html` (the `#player-profile` div and all its JS functions: `openProfile`, `loadPlayerStats`, `renderStatsIntoPanel`, compare panel logic, Chart.js chart)
4. Auto-call `openProfile` on page load with the passed-in player data (no need for the roster table — go straight to profile)
5. Add a **Back to Rankings** button at the top that uses `back_url`
6. If `compare=true` query param is present, auto-open the compare panel
7. Re-use the existing `/player_stats` API endpoint (already works correctly)

---

### Step 3 — Hide the Rosters nav tab

**`base.html`**

1. Find the Rosters nav link and add `style="display:none"` (or remove it entirely)
2. The `/rosters` route can remain in `views.py` for now (no need to delete it — just hide the entry point)

---

### Step 4 — Wire up "Compare" from the full player page

The rosters page already has a compare panel that lets you search for a second player and load their stats side by side. This will carry over to `player_profile.html` as-is since the JS and `/player_stats` endpoint are shared.

---

## File Changes Summary

| File | Change |
|------|--------|
| `webapp/views.py` | Add `/player_quick_stats` endpoint; add `/player/<name>` route; keep `/rosters` route untouched |
| `webapp/templates/rankings.html` | Replace static `playerDetails` JSON with lazy fetch to `/player_quick_stats`; add headshot, stats, model metrics, "See Full Profile" + "Compare" buttons to deep dive panel |
| `webapp/templates/player_profile.html` | New file — adapted from rosters page profile section; auto-loads player on mount; has back button |
| `webapp/templates/base.html` | Hide Rosters nav link |
| `webapp/static/css/styles.css` | Add any new styles needed for deep dive panel layout (headshot, stat cards, buttons) |

---

## Data Flow

```
Rankings page row click
  → fetch /player_quick_stats?name=X&pos=Y&team=Z
      ← { espn_id, stats (2025), fantasy_points, ranking }
  → render inline deep dive (headshot + stats + model metrics)
  → "See Full Profile" click
      → navigate to /player/<name>?pos=Y&team=Z
          → player_profile.html loads
          → fetch /player_stats?name=X&pos=Y&team=Z (existing endpoint)
              ← { history (multi-season), ranking, team_grade }
          → render full profile (headshot, bio, grades, chart, history table)
          → "Compare" → side-by-side compare panel (existing logic)
          → "Back to Rankings" → back_url
```

---

## Testing Checklist

- [ ] Puka Nacua inline deep dive shows 2025 stats and headshot
- [ ] Stats are correct per position (QB/RB/WR/TE show appropriate columns)
- [ ] "See Full Profile" navigates to `/player/Puka-Nacua?pos=WR&team=LA`
- [ ] Full player page shows: headshot, bio, team grades (all 6), season history chart, season history table
- [ ] Back button returns to the correct rankings tab (PPR / Half PPR / Standard)
- [ ] Compare panel works on full player page
- [ ] Rosters nav tab is hidden
- [ ] Players with no ESPN headshot degrade gracefully (image hidden)
- [ ] Players not in pkl files (new 2025 players) still show stats from nflreadpy live data
