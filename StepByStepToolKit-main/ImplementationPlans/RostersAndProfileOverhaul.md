# Rosters & Player Profile Overhaul — Implementation Plan

## Overview

Four feature areas:
1. **Team Grades** — replace pre-computed team-level grades with a computed composite built from starter-only fantasy performance
2. **Rosters List View** — replace the flat name grid with a sortable, groupable card-table hybrid, stats pre-loaded at startup
3. **Player Profile Improvements** — tooltips on grades, best-season highlighting, chart hover, Compare side-by-side
4. ~~Export button~~ — dropped per user decision

---

## 1. Team Grades — Starter Composite

### Problem
The current grades panel uses `currAVs.pkl`, which contains pre-computed team-level grades unrelated to actual fantasy-relevant starter performance. There is no per-player averaging happening — it's one flat number per team.

### New Approach
Compute a new composite grade per team per position group using **only starters**, defined as:
- **QB**: Top 1 player by total `fantasy_points`
- **RB**: Top 2 players by total `fantasy_points`
- **WR**: Top 3 players by total `fantasy_points`
- **TE**: Top 2 players by total `fantasy_points`

Grade metric: **fantasy points per game** (total `fantasy_points` / `GP`) for the most recent season in the pickle files. Average across starters per position group, then min-max normalize to 0–1 across all teams.

### Data Sources
- `final_qb_data.pkl` → QB starters (`YearsBack == 1`, `season_type == 'REG'`)
- `final_rb_data.pkl` → RB starters
- `final_wrte_data.pkl` → WR starters (Position == 'WR') and TE starters (Position == 'TE')

### Computed Grades (5 values per team)
| Grade | Starters Used | Metric |
|---|---|---|
| QB | QB1 | fantasy_pts/game |
| RB | RB1 + RB2 avg | fantasy_pts/game |
| WR | WR1+WR2+WR3 avg | fantasy_pts/game |
| TE | TE1 + TE2 avg | fantasy_pts/game |
| OLine | Keep existing `currAVs` OLine | No player-level proxy available |

OLine stays from `currAVs.pkl` since there is no individual OLine player metric in the data.

### Implementation

**`views.py`** — compute at startup, cache in `_composite_grades` dict:
```python
_composite_grades = {}  # { 'KC': { 'QB': 0.88, 'RB': 0.74, ... } }
```

Steps:
1. Load `final_qb_data.pkl`, `final_rb_data.pkl`, `final_wrte_data.pkl` filtered to `YearsBack==1` and `season_type=='REG'`
2. For each position group, group by team, sort by `fantasy_points` desc, slice to starter count, compute avg pts/game
3. Min-max normalize each grade column across all teams (0 = worst, 1 = best)
4. Merge OLine from `currAVs.pkl`
5. Store result in `_composite_grades`

**`/player_stats` route** — replace `team_grade` lookup from `_curr_avs` to `_composite_grades`:
```python
team_grade = _composite_grades.get(team, {})
```

**`rosters.html`** — add `(starters only)` label under "Team Grades" heading in the profile panel.

---

## 2. Rosters List View

### Problem
Current grid is 500+ small name buttons with no context. Hard to scan, compare, or discover players.

### New Layout

Replace `#rosterGrid` with a **sortable card-table**:

```
[ Position Filter ] [ Team Filter ] [ Search ] [ Group by Position toggle ]

┌──────────────────────────────────────────────────────────────────────┐
│ #  │ Player         │ Pos │ Team │ Stat1 │ Stat2 │ Stat3 │ Fant Pts │
├────┼────────────────┼─────┼──────┼───────┼───────┼───────┼──────────┤
│ 1  │ Josh Allen     │ QB  │ BUF  │ 4,300 │ 37 TD │ 10 INT│  380.2   │  ← row color-coded
│ 2  │ Lamar Jackson  │ QB  │ BAL  │ 3,950 │ 39 TD │ 5 INT │  410.8   │
└──────────────────────────────────────────────────────────────────────┘
```

### Stat Columns Per Position
| Position | Stat 1 | Stat 2 | Stat 3 | Fantasy Pts |
|---|---|---|---|---|
| QB | Pass Yds | TD / INT | Rush Yds | Fant Pts |
| RB | Rush Yds | Yds/Carry | Rec / Rec Yds | Fant Pts |
| WR | Targets | Receptions | Catch % | Fant Pts |
| TE | Targets | Receptions | Rec Yds | Fant Pts |

### Fantasy Points Color Scale
Fantasy Pts column background uses a red → yellow → green gradient relative to position group:
- Top 25% of position → green (`#2d8b8b`)
- Middle 50% → yellow-neutral (`#8b8b2d`)
- Bottom 25% → muted red (`#8b2d2d`)

### Pre-loading Stats at Startup

**`views.py`** — build `_roster_stats` dict at startup:
```python
_roster_stats = {}  # { 'Josh Allen': { 'pos': 'QB', 'pass_yds': 4300, ... } }
```

Steps:
1. Load all three pickle files, filter to `YearsBack==1` and `season_type=='REG'`
2. Build a name-keyed dict with position-appropriate stat columns + `fantasy_points`
3. Pass to `rosters.html` as JSON (`roster_stats_json`) via the `/rosters` route

### Sorting

Click any column header to sort ascending/descending. Pure JS — no server round-trip. Sort state indicated by an up/down arrow on the active column header.

### Grouping Toggle

Button in the filter bar: **"Flat List" / "By Position"**

- **Flat**: all players in one table, sorted by selected column
- **By Position**: four sections (QB, RB, WR, TE), each independently sorted, collapsible headers

### Sparkline / Chart

**No chart in the list view.** Chart only appears in the player profile panel when a player row is clicked (same as current behavior).

### Files Modified
| File | Change |
|---|---|
| `views.py` | Build `_roster_stats` at startup; pass `roster_stats_json` to template |
| `rosters.html` | Replace grid with sortable table; add grouping toggle; wire click → profile |
| `styles.css` | Table styles, color scale, sort arrows |

---

## 3. Player Profile Improvements

### 3a. Team Grades Tooltip

On each grade label row (OLine, QB, RB, WR/TE, DST), add a small `ⓘ` icon. On hover, a CSS tooltip popover appears explaining the grade:

| Grade | Tooltip Text |
|---|---|
| OLine | "How well this team's offensive line protects the QB and opens running lanes. Higher = better pass and run blocking." |
| QB | "Starter QB's fantasy output per game vs. league average. Reflects overall passing efficiency and rushing upside." |
| RB | "Average fantasy production of the top 2 RBs per game. Reflects volume, efficiency, and receiving usage." |
| WR | "Average fantasy production of the top 3 WRs per game. Reflects target share, yards, and touchdown opportunity." |
| TE | "Average fantasy production of the top 2 TEs per game. High scores indicate a target-heavy, pass-catching TE." |
| DST | "Team defensive strength from existing model. Higher = better against opposing offenses." |

Implementation: pure CSS tooltip (no JS required). Add `.grade-info` span with `data-tip` attribute; style with `::after` pseudo-element positioned above the icon.

### 3b. Season History — Best Season Highlighting

After the season history table renders, JS scans each numeric column and highlights the cell with the highest value with a distinct Ocean Depths accent background (`#1a3d3d` border + `#2d8b8b` text).

Logic:
```javascript
// For each stat column, find max value row and add class 'best-season'
table.querySelectorAll('tbody tr').forEach(...) → find max per column → add highlight class
```

### 3c. Fantasy Points Chart — Hover Tooltip

Chart.js already supports hover tooltips. Currently the chart is initialized without a custom tooltip config. Add:
```javascript
plugins: {
  tooltip: {
    callbacks: {
      title: (items) => `Season ${items[0].label}`,
      label: (item)  => `Fantasy Pts: ${item.parsed.y.toFixed(1)}`
    }
  }
}
```

This shows `Season 2023 | Fantasy Pts: 312.4` on hover. No structural changes needed.

### 3d. Compare Player — Side-by-Side View

**Trigger:** "Compare Player" button in the player profile header.

**Flow:**
1. User opens a player profile (e.g., Josh Allen)
2. Clicks "Compare Player" button
3. A search input appears in a slide-in right panel
4. User types a name → autocomplete dropdown (filtered from already-loaded roster data)
5. User selects second player → AJAX call to `/player_stats` for that player
6. Right panel fills with second player's full profile (bio, grades, chart, stats table)
7. Both profiles shown side-by-side (left = original, right = comparison)
8. "Clear Compare" button dismisses the right panel and returns to single-profile view

**Layout:**
```
┌─────────────────────┬─────────────────────┐
│  Josh Allen         │  Lamar Jackson      │
│  BUF · QB           │  BAL · QB           │
├─────────────────────┼─────────────────────┤
│  Team Grades        │  Team Grades        │
│  OLine: ████ 0.73   │  OLine: ████ 0.81   │
├─────────────────────┼─────────────────────┤
│  Season History     │  Season History     │
│  (table)            │  (table)            │
├─────────────────────┼─────────────────────┤
│  Fantasy Pts Chart  │  Fantasy Pts Chart  │
└─────────────────────┴─────────────────────┘
```

**Implementation:**
- The profile panel expands to a two-column flex layout when compare mode is active
- Second player's data fetched from existing `/player_stats` endpoint (no new route needed)
- Autocomplete built from `roster_stats_json` already on the page (no extra API call)
- Each chart rendered independently (two Chart.js instances, one per player)

**Files Modified:**
- `rosters.html` — compare button, second profile panel, autocomplete search, two-column layout
- `styles.css` — compare layout, slide-in panel, autocomplete dropdown

---

## 4. Implementation Order

| Step | Task | Files |
|---|---|---|
| 1 | Compute `_composite_grades` at startup | `views.py` |
| 2 | Compute `_roster_stats` at startup | `views.py` |
| 3 | Update `/player_stats` to use composite grades | `views.py` |
| 4 | Pass `roster_stats_json` through `/rosters` route | `views.py` |
| 5 | Rebuild rosters list as sortable card-table | `rosters.html`, `styles.css` |
| 6 | Add grouping toggle (flat vs by-position) | `rosters.html` |
| 7 | Add grade tooltips + `(starters only)` label | `rosters.html`, `styles.css` |
| 8 | Best-season column highlighting | `rosters.html` |
| 9 | Chart hover tooltips | `rosters.html` |
| 10 | Compare Player side-by-side | `rosters.html`, `styles.css` |

---

## 5. Key Edge Cases

- Players in `_roster_stats` may not match names in `teamsPastRoster.pkl` exactly — use fuzzy name alignment or a name normalization pass at startup
- Some players will have no recent stats (rookies, IR) — show `—` for missing stat cells, no color-coding
- Compare player: if selected player has no stats data, show bio only with a "No stat data available" message in the stat panels
- OLine grade remains from `currAVs.pkl` — some teams may not be in that dataset; fall back to `—`
- Fantasy points color scale computed per position group, not globally (QBs score much higher than TEs)
