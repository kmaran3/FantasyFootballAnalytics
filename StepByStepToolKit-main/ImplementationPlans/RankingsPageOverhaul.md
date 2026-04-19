# Rankings Page Overhaul — Implementation Plan

**Date:** 2026-03-24
**Branch:** Krishna
**Status:** Draft — Pending answers on open questions (marked ⚠️)

---

## Summary of Features

| # | Feature | Complexity | Files Touched |
|---|---------|-----------|---------------|
| 1 | Team filter on rankings page | Low | `rankings.html`, `styles.css` |
| 2 | Bye week filter on rankings page | Low | `rankings.html`, `styles.css` |
| 3 | Deep dive panel: Age, Last Year's Stats, Stat Year label | Medium | `views.py`, `rankings.html`, `styles.css` |
| 4 | Deep dive panel: First 5 upcoming games | Medium–High | `views.py`, `rankings.html`, schedule data source ⚠️ |
| 5 | Dark mode for rankings page | Medium | `styles.css`, `rankings.html` |
| 6 | Logo on every page | Low | `base.html`, `styles.css` |

---

## Decisions (Resolved)

| Question | Decision |
|----------|----------|
| Schedule data source | **`nfl_data_py` library** — fetch `nfl.import_schedules([2024])` at runtime, cache at startup |
| Stats display format | **Position-specific + universal** — show GP + Fantasy Pts for all, plus position-specific stat rows |
| Team filter UI | **Dropdown multi-select** (`<select multiple>`) |
| Bye week filter UI | **Dropdown multi-select** (`<select multiple>`) |

---

## Data Sources & Availability

### Player Statistics (Last Year's Stats)
- **Source files:** `Models/PickleFiles/final_qb_data.pkl`, `final_rb_data.pkl`, `final_wrte_data.pkl`
- **Last season in data:** 2023 (`YearsBack = 1`)
- **QB columns:** `completions`, `attempts`, `passing_yards`, `passing_tds`, `interceptions`, `carries`, `rushing_yards`, `rushing_tds`, `fantasy_points`, `GP`
- **RB columns:** `carries`, `rushing_yards`, `rushing_tds`, `receptions`, `targets`, `receiving_yards`, `receiving_tds`, `fantasy_points`, `GP`
- **WR/TE columns:** `receptions`, `targets`, `receiving_yards`, `receiving_tds`, `carries`, `rushing_yards`, `fantasy_points`, `GP`
- **Join key:** `player_display_name` → matches `Name` in ranking tables (may need fuzzy matching for edge cases)

### Age
- **Source file:** `Models/PickleFiles/currYearRoster.pkl` (columns: `Player`, `Team`, `Pos`, `Yrs`, `Age`, `BirthDate`)
- **Alternative:** `age` column in `final_*_data.pkl` for 2023 season — may be one year behind (should add 1 for 2024)
- **Recommended:** Use `currYearRoster.pkl` `Age` field (already current-year age)
- **Join key:** `Player` → matches `Name` in ranking tables

### Team & Bye Week
- Already present as columns in `Full_PPR`, `Half_PPR`, `Non_PPR` SQLite tables — no new data needed for filters.

### Schedule (First 5 Games)
- **Not currently available** — see Q1 above.
- If using static file: format should be `{ "PLAYER_TEAM": ["Week 1 vs OPP", "Week 2 @ OPP", ...] }` or structured CSV with columns `team, week, opponent, home_away`.

---

## Feature-by-Feature Implementation Plan

---

### Feature 1: Team Filter

**Goal:** Allow users to filter the rankings table by one or more NFL teams.

**Approach:**
1. Add a `<select id="teamFilter" multiple size="1">` dropdown multi-select to the `.position-filter-bar` in `rankings.html`.
2. Populate team options dynamically from Jinja: `{% set teams = table_data | map(attribute='Team') | unique | sort | list %}` — renders all teams present in the current ranking table.
3. Style the `<select>` to match the dark theme: dark background (`#444`), cream text, rounded corners, consistent height with the search input.
4. JavaScript filter logic: on `change`, collect selected option values, iterate `.player-row` elements, read the `Team` column cell (column index resolved from `<thead>`), show/hide rows accordingly.
5. "No selection" (nothing selected) = show all teams.
6. Filter must **compose** with position filter, bye week filter, and search — all active simultaneously should AND their conditions.

**Files to change:**
- `webapp/templates/rankings.html`: Add team `<select>` and update JS filter logic.
- `webapp/static/css/styles.css`: Style team and bye week dropdowns for dark mode.

**Key JS logic change:**
- Refactor current separate filter functions into a single `applyFilters()` function that reads active state from position buttons, team filter, bye week filter, and search input simultaneously. Call `applyFilters()` from all filter event handlers.

---

### Feature 2: Bye Week Filter

**Goal:** Allow users to filter by bye week number.

**Approach:**
1. Add a `<select id="byeWeekFilter" multiple size="1">` dropdown multi-select inline in the `.filter-bar-inner` alongside the team dropdown.
2. Populate bye week options dynamically from Jinja: `{% set bye_weeks = table_data | map(attribute='Bye Week') | unique | sort | list %}`.
3. Style consistently with the team dropdown.
4. JavaScript: same composable `applyFilters()` function reads selected bye week values.
5. "No selection" = show all bye weeks.

**Bye Week column:** Present in DB as `"Bye Week"` (with space) — column index resolution in JS resolves this from `<thead>` text.

**Files to change:**
- `webapp/templates/rankings.html`: Add bye week `<select>`, update JS.
- `webapp/static/css/styles.css`: Shared dropdown styles.

---

### Feature 3: Deep Dive Panel — Age, Last Year's Stats, Stat Year Label

**Goal:** When a player row is clicked, expand a panel showing: player Age, their 2023 season statistics (labeled "2023 Season Stats"), and position-specific stat layout.

**Backend changes (`views.py`):**
1. Load `currYearRoster.pkl` to get age data.
2. Load `final_qb_data.pkl`, `final_rb_data.pkl`, `final_wrte_data.pkl`, filter to `YearsBack == 1` (2023 season) and `season_type == 'REG'`.
3. Build a lookup dict `player_details` keyed by player name → `{ age, stats_year: 2023, position, stats: {...} }`.
4. Pass `player_details` as a JSON-serialized variable to the template (via `json.dumps(player_details_dict)`) so it is available in JavaScript at render time.
5. Do this for all three ranking routes (`get_ppr_rankings`, `get_half_ppr_rankings`, `get_standard_rankings`).

**Name matching note:** The ranking table uses `Name` (e.g., "C.J. Stroud"). The pickle files use `player_display_name` (same format). `currYearRoster.pkl` uses `Player`. Test for exact match; add a fallback strip/lowercase comparison for edge cases.

**Template changes (`rankings.html`):**
1. Inject `player_details` as a JS object: `var playerDetails = {{ player_details_json | safe }};`
2. In the `.player-row` click handler, extract the player `Name` from the clicked row, look up `playerDetails[name]`, and dynamically build HTML for the `.deep-dive-panel`.
3. Deep dive panel layout (position-specific):

```
+-------------------------------------------------------------+
|  [Player Name]            Age: 27        Position: RB       |
+-------------------------------------------------------------+
|  2023 Season Stats                                          |
|  Games: 16  |  Rush Att: 224  |  Rush Yds: 1139  |  Rush TDs: 8  |
|  Receptions: 53  |  Rec Yds: 391  |  Rec TDs: 3  |  Fantasy Pts: 243.0  |
+-------------------------------------------------------------+
|  2024 Season — First 5 Games                               |
|  Wk 1: vs DAL  |  Wk 2: @ PHI  |  Wk 3: vs NYG  | ...    |
+-------------------------------------------------------------+
```

**Position-specific stat rows:**
- **QB:** Comp/Att, Pass Yds, Pass TDs, INTs, Rush Yds, Rush TDs, Fantasy Pts, GP
- **RB:** Carries, Rush Yds, Rush TDs, Receptions, Targets, Rec Yds, Rec TDs, Fantasy Pts, GP
- **WR/TE:** Targets, Receptions, Rec Yds, Rec TDs, Rush Yds, Fantasy Pts, GP
- **K/DEF:** No stats in current data — show "Stats not available" gracefully

**Files to change:**
- `webapp/views.py`: Load pickle data, build player_details dict, pass to templates.
- `webapp/templates/rankings.html`: JS injection of playerDetails, dynamic panel HTML generation, updated click handler.
- `webapp/static/css/styles.css`: Dark-mode-aware deep dive panel styling.

---

### Feature 4: Deep Dive Panel — First 5 Upcoming Games

**Goal:** Show the first 5 games of the 2024 NFL season for each player's team.

**Approach (pending Q1 answer):**

**Using nfl_data_py (decided):**
1. See above — loaded at module level, cached as `_team_schedule`.
2. Pass as `team_schedule_json` (JSON-serialized) to the template.
3. In the JS click handler, look up `teamSchedule[playerTeam]` and render the first 5 entries.

**Selected approach — nfl_data_py:**
1. `pip install nfl-data-py` (add to requirements if present).
2. In `views.py` at module level (one-time at startup):
   ```python
   import nfl_data_py as nfl
   _schedule_df = nfl.import_schedules([2024])
   ```
3. Filter to `season_type == 'REG'`, sort by `week`, take first 5 weeks per team, build dict `{ "BUF": [{"week": 1, "opp": "ARI", "home_away": "home"}, ...], ... }`.
4. Cache as a module-level variable to avoid re-fetching on every request.

**Display format:**
```
Week 1: vs BUF  |  Week 2: @ LAR  |  Week 3: vs SF  |  Week 4: @ SEA  |  Week 5: BYE
```

**Edge cases:** Kickers and DEF use team abbreviations directly. Verify team abbreviation consistency between ranking data and schedule data (e.g., `LAR` vs `LA`, `JAX` vs `JAC`).

**Files to change:**
- `webapp/data/2024_nfl_schedule.json` (new file) OR install `nfl-data-py`
- `webapp/views.py`: Load/build schedule dict, pass to template
- `webapp/templates/rankings.html`: Render schedule in deep dive panel

---

### Feature 5: Dark Mode for Rankings Page

**Goal:** Switch the rankings page to a dark background with appropriately contrasted text, table rows, and interactive elements.

**Scope:** Rankings page only (not site-wide). The rest of the site (`body` default) remains as-is.

**Approach:**
1. Add a `.rankings-page` class to the `<body>` or `<main>` element within `rankings.html` using a `{% block body_class %}{% endblock %}` mechanism in `base.html`, or simply override styles inline in `rankings.html`'s `<style>` block.
2. Define dark-mode overrides in `styles.css` scoped under `.rankings-page` (or a `<style>` block in the template):

**Color palette for dark mode rankings:**
| Element | Current | Dark Mode |
|---------|---------|-----------|
| `body` / `main` background | `#fff` / white | `#1a1a2e` (deep dark navy) |
| Table rows (even) | Bootstrap striped | `#16213e` |
| Table rows (odd) | Bootstrap striped | `#0f3460` |
| Table header | Bootstrap default | `#0f3460` with `#e0e0e0` text |
| Table text | `#000` | `#e0e0e0` |
| `.position-filter-bar` background | `#fff` | `#1a1a2e` |
| `.player-row:hover` | `#e8e8e8` | `#2a2a4e` |
| `.player-row.active-player` | `#e0dfc8` | `#1a4a6e` |
| `.deep-dive-panel` | `#fff` border `#ddd` | `#16213e` border `#2a2a5e` |
| Table `border-bottom` | `#ddd` | `#2a2a5e` |
| Filter bar search input | white bg | `#16213e` bg, `#e0e0e0` text |
| `th`, `td` borders | `#ddd` | `#2a2a5e` |

3. The `.left-panel`, `.right-panel`, and `.position-filter-btn` elements are already dark (`#444`/`#555`) — minor adjustments only.
4. Remove or override Bootstrap `.table-striped` background colors for dark mode rows.

**Implementation options:**
- **(a) CSS class scoping** on `<main>` — cleanest, no JS needed. Add `class="rankings-main"` to the `<main>` block in `rankings.html` (using `{% block main_class %}rankings-main{% endblock %}` in base).
- **(b) Inline `<style>` block** in `rankings.html` — quick and isolated, slightly less clean.

**Recommended:** (a) CSS class scoping.

**Files to change:**
- `webapp/static/css/styles.css`: Add dark mode styles scoped to `.rankings-main`
- `webapp/templates/base.html`: Add `{% block main_class %}{% endblock %}` support on `<main>`
- `webapp/templates/rankings.html`: Set `{% block main_class %}rankings-main{% endblock %}`

---

### Feature 6: Logo on Every Page

**Goal:** Display the Darkhorse logo (`flask_logo.png`) on every page in a consistent location.

**Current state:** Logo is only in `home.html` as a standalone `<img>` in the page content.

**Recommended placement:** In the **navigation bar** (`base.html`), to the left of the nav links. This is the most conventional and non-intrusive placement — visible on every page without occupying content space.

**Approach:**
1. In `base.html`, add the logo image inside `<header class="banner">`, before the `<nav>`:
   ```html
   <div class="nav-logo">
     <img src="{{ url_for('static', filename='images/flask_logo.png') }}" alt="Darkhorse Logo" class="nav-logo-img">
   </div>
   ```
2. Update `<header>` layout to `display: flex; align-items: center;` so the logo sits left of the nav links.
3. Style `.nav-logo-img` to a small circular size (e.g., `height: 40px; width: 40px; border-radius: 50%;`).
4. Keep the existing large logo on `home.html` as-is (or remove it if redundant — user's preference).

**Alternative placement:** Top-left corner fixed overlay (always visible even when scrolling). Less conventional but prominent.

**Files to change:**
- `webapp/templates/base.html`: Add logo markup to header
- `webapp/static/css/styles.css`: Add `.nav-logo`, `.nav-logo-img` styles, adjust header flex layout

---

## Implementation Order (Recommended Sequence)

1. **Feature 6 — Logo** (quickest, self-contained, no dependencies)
2. **Feature 5 — Dark Mode** (sets visual foundation for everything else)
3. **Feature 1 — Team Filter** (pure frontend, uses existing DB data)
4. **Feature 2 — Bye Week Filter** (pure frontend, uses existing DB data)
5. **Feature 3 — Deep Dive: Age + Stats** (requires backend pickle loading)
6. **Feature 4 — Deep Dive: Schedule** (depends on Q1 answer and potentially Feature 3 infrastructure)

---

## Files Changed Summary

| File | Features |
|------|---------|
| `webapp/templates/base.html` | Logo (F6), Dark mode class support (F5) |
| `webapp/templates/rankings.html` | Team filter (F1), Bye filter (F2), Dark mode (F5), Deep dive panel (F3, F4) |
| `webapp/static/css/styles.css` | Dark mode (F5), Logo (F6), Filter UI (F1, F2), Deep dive (F3, F4) |
| `webapp/views.py` | Deep dive data loading (F3, F4) |
| `nfl-data-py` (pip install) | Schedule data fetched via `nfl.import_schedules([2024])` (F4) |

---

## Notes & Risks

- **Name matching:** Joining ranking table names to pickle file names is the highest risk step. Edge cases like "D.K. Metcalf" vs "DK Metcalf", or players who changed teams, need testing. Recommend building a name-normalization helper.
- **K/DEF stats:** Kickers and defenses don't appear in `final_qb_data.pkl`, `final_rb_data.pkl`, or `final_wrte_data.pkl`. The deep dive panel should gracefully show "No detailed stats available" for these positions.
- **Bootstrap table-striped:** Dark mode will need to override Bootstrap's `.table-striped tbody tr:nth-of-type(odd)` background — ensure CSS specificity is high enough.
- **viewSavedRanking route:** The `view_saved_ranking` route also renders `rankings.html`. The `player_details` and `team_schedule` data should also be passed from that route or the deep dive will be empty for saved rankings.
- **Performance:** Loading 3 large pickle files on every rankings page request could be slow. Consider loading them once at app startup and caching as module-level variables in `views.py`.
