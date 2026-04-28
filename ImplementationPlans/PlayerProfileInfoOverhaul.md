# Player Profile Info Overhaul

## Overview
Polish the Player Info table, Fantasy Points chart, and Season History table on every player profile page.

---

## 1. Player Info Table

### Remove Fields
- **Birth Date** — remove entirely
- **Rookie Season** — remove entirely
- **Position** — remove (already shown in the subtitle next to name)
- **Team** — remove (already shown in the subtitle next to name)

### Modify Fields

#### Age
- Show age in years only (integer), derived from birth date on the backend
- Label: `Age`
- Example: `24`

#### Draft Year
- Currently stored as a float (e.g. `2023.0`) — strip the decimal
- Label: `Draft Year`
- Example: `2023`

#### Seasons Played
- Rename `Experience (yrs)` → `Seasons Played`
- Display as integer
- Example: `3`

#### Pick
- Combine `Round` and `Pick` into a single field
- Format: `{round}.{pick_within_round zero-padded to 2 digits}`
- Label: `Pick`
- Examples: `1.05`, `3.20`, `7.01`
- Backend: compute `pick_within_round = overall_pick - (round - 1) * 32` or use stored round/pick fields

#### Height
- Currently stored in inches as a float (e.g. `74.0`)
- Convert to feet and inches: `ft = int(inches // 12)`, `inches_rem = int(inches % 12)`
- Label: `Height`
- Example: `6'2"`

#### Weight
- Strip decimal, append `lbs`
- Label: `Weight`
- Example: `212 lbs`

### Final Field Order
```
Age
Height
Weight
Draft Year
Draft Team
Pick
Seasons Played
```

---

## 2. Fantasy Points by Season Chart

### Current State
Line chart showing total fantasy points per season.

### Changes
Add **GP (games played)** and **PPG (points per game)** alongside the existing total points line.

### Recommended Approach: Tooltip Enhancement
On hover, the tooltip already shows the fantasy points value. Extend it to also show:
- `GP: 16`
- `PPG: 22.4`

This avoids visual clutter from additional lines or toggles.

### Implementation
- Backend: the `/api/player/<name>` endpoint returns `history` rows — ensure each row includes `GP` (already present) and compute `ppg = round(fantasy_points / GP, 1)` if `GP > 0`
- JS: update the Chart.js tooltip callback in `renderHistoryTable` / the fantasy chart section to display GP and PPG alongside the points value

### Optional Toggle (if tooltip feels insufficient)
Add two small pill buttons above the chart: `Total Pts` | `PPG` — clicking switches the Y-axis metric. Default to `Total Pts`.

---

## 3. Season History Table

### Change
Add **Team** as the **2nd column** (after Season), showing which NFL team the player was on that season.

### Implementation
- Backend: the history rows need a `team` field per season
  - For nflreadpy data: `recent_team` is available per season row — include it in the history payload
  - For pkl fallback: add team lookup from the roster/stats pkl files
- JS: update `colOrder` in `renderHistoryTable` to place `team` second:
  ```js
  QB: ['season', 'team', 'GP', 'completions', ...]
  RB: ['season', 'team', 'GP', 'carries', ...]
  WR: ['season', 'team', 'GP', 'receptions', ...]
  TE: ['season', 'team', 'GP', 'receptions', ...]
  ```
- `labelMap`: add `team: 'Team'`

---

## Files to Modify

| File | Changes |
|------|---------|
| `webapp/views.py` | Format height/weight/pick in player API response; add `team` and `ppg` to history rows; compute age from birth date |
| `webapp/templates/player_profile.html` | Update `renderHistoryTable` colOrder + labelMap; update Chart.js tooltip to show GP + PPG; remove Position/Team/BirthDate/RookieSeason from bio fields |

---

## Notes
- All formatting (height, weight, pick, age) should be done server-side in the `/api/player/<name>` view so the JS stays simple
- The subtitle line already shows `WR · LAR` so removing Position and Team from the info table is purely deduplication
- Birth date can be used to compute age on the backend and then discarded from the response
