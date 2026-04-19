# nfl_data_py → nflreadpy Migration Plan

**Goal:** Replace `nfl_data_py` with `nflreadpy` across the entire codebase, update all data to use 2025 as the current season, and predict for 2026. The live app should always use the most recent available data (currently 2025).

---

## Background & Key Findings

### Why nflreadpy
- `nfl_data_py` is officially deprecated by the nflverse team
- `nflreadpy` is its successor with 2025 data support
- `nflreadpy` returns **Polars DataFrames** — must call `.to_pandas()` immediately after every load call to keep all downstream pandas code unchanged

### Critical Column Name Differences (Rosters Only)
`nflreadpy.load_rosters()` uses different column names than `nfl_data_py.import_seasonal_rosters()`:

| nfl_data_py column | nflreadpy column |
|--------------------|-----------------|
| `player_id`        | `gsis_id`        |
| `player_name`      | `full_name`      |

All other datasets (player stats, PBP, schedules) use **identical column names**.
Every roster load must immediately rename these two columns after `.to_pandas()`.

### Function Mapping

| nfl_data_py | nflreadpy | Notes |
|---|---|---|
| `nfl.import_pbp_data(seasons)` | `nflreadpy.load_pbp(seasons)` | Same columns |
| `nfl.import_seasonal_rosters(seasons)` | `nflreadpy.load_rosters(seasons)` | Rename `gsis_id`→`player_id`, `full_name`→`player_name` after load |
| `nfl.import_seasonal_data(seasons, s_type='REG')` | `nflreadpy.load_player_stats(seasons, summary_level='reg')` | Same columns |
| `nfl.import_schedules(seasons)` | `nflreadpy.load_schedules(seasons)` | Same columns |

### Files Affected
1. `requirements.txt`
2. `webapp/views.py`
3. `Models/NewModel/_run_phase1.py`
4. `Models/patch_mlmodel.py`
5. `Models/patch_predcode.py`

Files **not** affected: `_run_phase2.py`, `_run_phase3.py` (already correct: `FEATURE_SEASON=2025`, `PREDICT_YEAR=2026`, `TEST_SEASONS=[2024,2025]`)

---

## Step 0 — Pre-flight Column Verification (Do This First)

Before changing any code, run this one-off script to verify column names in the live nflreadpy data and confirm the column mapping above is correct.

```python
import nflreadpy

# Verify roster columns
rosters = nflreadpy.load_rosters([2025]).to_pandas()
print("ROSTER COLUMNS:", rosters.columns.tolist())
print("Has gsis_id:", 'gsis_id' in rosters.columns)
print("Has full_name:", 'full_name' in rosters.columns)
print("Has player_id:", 'player_id' in rosters.columns)
print("Has player_name:", 'player_name' in rosters.columns)
print()

# Verify player stats columns
stats = nflreadpy.load_player_stats([2025], summary_level='reg').to_pandas()
print("PLAYER STATS COLUMNS:", stats.columns.tolist())
print("Has player_id:", 'player_id' in stats.columns)
print("Has passing_epa:", 'passing_epa' in stats.columns)
print("Has pacr:", 'pacr' in stats.columns)
print("Has dakota:", 'dakota' in stats.columns)
print("Has player_display_name:", 'player_display_name' in stats.columns)
print()

# Verify schedule columns
sched = nflreadpy.load_schedules([2025]).to_pandas()
print("SCHEDULE COLUMNS:", sched.columns.tolist())
print("Has game_type:", 'game_type' in sched.columns)
print("Has home_team:", 'home_team' in sched.columns)
print("Has away_team:", 'away_team' in sched.columns)
```

**Expected results:**
- Roster: `gsis_id` and `full_name` present, `player_id` and `player_name` absent
- Player stats: `player_id`, `passing_epa`, `pacr`, `dakota`, `player_display_name` all present
- Schedules: `game_type`, `home_team`, `away_team` all present

**If any expectation is wrong**, stop and reconcile the column names before proceeding. Update this plan accordingly.

---

## Step 1 — Install Dependencies

```bash
pip install nflreadpy polars
```

Update `requirements.txt` — add:
```
nflreadpy
polars
```

> Note: `nfl_data_py` is not currently listed in `requirements.txt` (it was a missing dependency). Do not add it. Remove it if it appears anywhere.

---

## Step 2 — `webapp/views.py`

This is the highest-priority file as it powers the live web app.

### Change 2A — `_get_team_schedule()` function (line ~132)

**Before:**
```python
import nfl_data_py as nfl
schedule_df = nfl.import_schedules([2024])
```

**After:**
```python
import nflreadpy
schedule_df = nflreadpy.load_schedules([2025]).to_pandas()
```

No column renames needed — schedule columns are identical.

### Change 2B — Startup data load block (lines ~188–222)

**Before:**
```python
import nfl_data_py as nfl
...
_stats_raw = nfl.import_seasonal_data(_seasons, s_type='REG')
...
_roster_raw = nfl.import_seasonal_rosters(_seasons)[['player_id', 'player_name', 'position']].drop_duplicates('player_id')
...
_r_latest = (nfl.import_seasonal_rosters([_latest_season])
             [['player_id', 'player_name', 'position', 'team']]
             ...)
```

**After:**
```python
import nflreadpy
...
_stats_raw = nflreadpy.load_player_stats(_seasons, summary_level='reg').to_pandas()
...
_roster_raw = (nflreadpy.load_rosters(_seasons).to_pandas()
               .rename(columns={'gsis_id': 'player_id', 'full_name': 'player_name'})
               [['player_id', 'player_name', 'position']].drop_duplicates('player_id'))
...
_r_latest = (nflreadpy.load_rosters([_latest_season]).to_pandas()
             .rename(columns={'gsis_id': 'player_id', 'full_name': 'player_name'})
             [['player_id', 'player_name', 'position', 'team']]
             ...)
```

**Year logic:** The dynamic year calculation using `date.today()` already handles 2025 automatically — no constant to update. The fallback loop `for _try_year in [_nfl_end_year, _nfl_end_year - 1]` will correctly try 2025 first then 2024.

Update error/print strings to reference `nflreadpy` instead of `nfl_data_py`.

---

## Step 3 — `Models/NewModel/_run_phase1.py`

### Change 3A — Import (line 1)

**Before:**
```python
import nfl_data_py as nfl
```

**After:**
```python
import nflreadpy
```

### Change 3B — PBP load (line 18)

**Before:**
```python
pbp_raw = nfl.import_pbp_data(SEASONS)
```

**After:**
```python
pbp_raw = nflreadpy.load_pbp(SEASONS).to_pandas()
```

No column renames needed — PBP columns are identical.

### Change 3C — Roster load (lines 23–28)

**Before:**
```python
roster_raw = nfl.import_seasonal_rosters(SEASONS)
roster = (
    roster_raw[roster_raw['game_type'] == 'REG']
    [['player_id','player_name','position','team','age','entry_year','rookie_year','draft_number','season']]
    .drop_duplicates(['player_id','season'])
)
```

**After:**
```python
roster_raw = (nflreadpy.load_rosters(SEASONS).to_pandas()
              .rename(columns={'gsis_id': 'player_id', 'full_name': 'player_name'}))
roster = (
    roster_raw[roster_raw['game_type'] == 'REG']
    [['player_id','player_name','position','team','age','entry_year','rookie_year','draft_number','season']]
    .drop_duplicates(['player_id','season'])
)
```

### Change 3D — `SEASONS` list (line 9)

Already correct: `SEASONS = [2020, 2021, 2022, 2023, 2024, 2025]` — no change needed.

---

## Step 4 — `Models/patch_mlmodel.py`

This script patches `MLModel.ipynb` by overwriting cell source strings. The embedded strings themselves contain `nfl_data_py` code and must be updated.

There are **3 cells** to update: CELL0 (QB), CELL1 (RB), CELL2 (WR/TE). Each follows the same pattern.

### Change 4A — CELL0 (QB)

Within the CELL0 string:

**Before:**
```python
import nfl_data_py as nfl
...
print("Fetching QB advanced features (passing_epa, pacr, dakota) for 2015-2023...")
seasonal_all = nfl.import_seasonal_data(list(range(2015, 2024)))
adv = seasonal_all[['player_id', 'season', 'passing_epa', 'pacr', 'dakota']].copy()
```

**After:**
```python
import nflreadpy
...
print("Fetching QB advanced features (passing_epa, pacr, dakota) for 2015-2025...")
seasonal_all = nflreadpy.load_player_stats(list(range(2015, 2026)), summary_level='reg').to_pandas()
adv = seasonal_all[['player_id', 'season', 'passing_epa', 'pacr', 'dakota']].copy()
```

### Change 4B — CELL1 (RB)

Within the CELL1 string:

**Before:**
```python
import nfl_data_py as nfl
...
print("Fetching RB opportunity/EPA features for 2015-2023...")
seasonal_all = nfl.import_seasonal_data(list(range(2015, 2024)))
opp = seasonal_all[['player_id', 'season', 'target_share', 'ry_sh', 'rushing_epa', 'receiving_epa', 'rtd_sh', 'rfd_sh']].copy()
```

**After:**
```python
import nflreadpy
...
print("Fetching RB opportunity/EPA features for 2015-2025...")
seasonal_all = nflreadpy.load_player_stats(list(range(2015, 2026)), summary_level='reg').to_pandas()
opp = seasonal_all[['player_id', 'season', 'target_share', 'ry_sh', 'rushing_epa', 'receiving_epa', 'rtd_sh', 'rfd_sh']].copy()
```

### Change 4C — CELL2 (WR/TE)

Within the CELL2 string: same pattern as above, update import, year range (`2015, 2024` → `2015, 2026`), and print string.

---

## Step 5 — `Models/patch_predcode.py`

This script patches `PredictionCode.ipynb`. There are **3 cells**: CELL1 (QB), CELL2 (RB), CELL3 (WR/TE). Each follows the same pattern.

### Change 5A — CELL1 (QB)

Within the CELL1 string:

**Before:**
```python
import nfl_data_py as nfl
CURRENT_YEAR = 2024
...
print("Fetching QB advanced features (passing_epa, pacr, dakota) for 2022-2023...")
qb_adv_raw = nfl.import_seasonal_data([2022, 2023])
```

And within `dfMaker()`:
```python
roster_raw = nfl.import_seasonal_rosters([CURRENT_YEAR - 1])
```

**After:**
```python
import nflreadpy
CURRENT_YEAR = 2025
...
print("Fetching QB advanced features (passing_epa, pacr, dakota) for 2023-2024...")
qb_adv_raw = nflreadpy.load_player_stats([2023, 2024], summary_level='reg').to_pandas()
```

And within `dfMaker()`:
```python
roster_raw = (nflreadpy.load_rosters([CURRENT_YEAR - 1]).to_pandas()
              .rename(columns={'gsis_id': 'player_id', 'full_name': 'player_name'}))
```

> `CURRENT_YEAR - 1` resolves to 2024, so rosters will load from the 2024 season — the most recently completed season when predicting for 2026.

### Change 5B — CELL2 (RB)

Same pattern as 5A:
- `import nfl_data_py as nfl` → `import nflreadpy`
- `CURRENT_YEAR = 2024` → `CURRENT_YEAR = 2025`
- `nfl.import_seasonal_data([2022, 2023])` → `nflreadpy.load_player_stats([2023, 2024], summary_level='reg').to_pandas()`
- `nfl.import_seasonal_rosters(...)` → `nflreadpy.load_rosters(...).to_pandas().rename(columns={'gsis_id': 'player_id', 'full_name': 'player_name'})`
- Update print string: `"2022-2023"` → `"2023-2024"`

### Change 5C — CELL3 (WR/TE)

Same pattern as 5A and 5B.

---

## Step 6 — Re-run Patch Scripts Against Notebooks

After updating `patch_mlmodel.py` and `patch_predcode.py`, apply them to the notebooks:

```bash
cd /Users/kmaran3/Dropbox/Darkhorse/Models
python patch_mlmodel.py
python patch_predcode.py
```

Verify each notebook opens without errors and that the patched cells show the new `nflreadpy` imports and updated years.

---

## Step 7 — Testing

### 7.1 — Unit-Level: Column Verification (Step 0)
Run the pre-flight verification script from Step 0 first. All assertions must pass before any other testing.

### 7.2 — Module-Level: Standalone Script Tests

Run each modified script in isolation to confirm data loads correctly:

**`_run_phase1.py`:**
```bash
cd /Users/kmaran3/Dropbox/Darkhorse/Models/NewModel
python _run_phase1.py
```
Expected: Loads PBP for 2020–2025, prints roster row count, no import errors.

**`patch_mlmodel.py` + `patch_predcode.py`:**
```bash
cd /Users/kmaran3/Dropbox/Darkhorse/Models
python patch_mlmodel.py   # Should print "Patched X cells in MLModel.ipynb"
python patch_predcode.py  # Should print "Patched X cells in PredictionCode.ipynb"
```

### 7.3 — Integration: Flask App Startup

Restart the Flask app and check the startup log output:

```bash
cd /Users/kmaran3/Dropbox/Darkhorse
python app.py
```

**Expected startup log lines:**
```
NFL stats loaded through season 2025
NFL data ready: history 2020–2025, grades/roster from season 2025 (N players)
```

If you see `season 2024` instead of `2025` in the second message, nflreadpy may not have 2025 player stats yet — the fallback to 2024 will kick in automatically, which is acceptable behavior.

### 7.4 — Integration: Rosters Page

Navigate to the rosters page in the browser and verify:

- [ ] Player names render correctly (confirms `full_name` → `player_name` rename worked)
- [ ] Player stats show 2025 season data (check a known player's stat line)
- [ ] Team abbreviations display correctly (confirms `gsis_id` → `player_id` rename worked so merges succeeded)
- [ ] The schedule widget shows 2025 games (not 2024)

### 7.5 — Integration: Rankings Page

- [ ] Player rankings load without 500 errors
- [ ] `Predicted PPG` and `2025 PPG` columns populate as expected

### 7.6 — Regression: Check for Empty DataFrames

In the startup log, check that no "could not load" warnings appear. Specifically watch for:
```
Warning: could not load nflreadpy stats: ...
Warning: Could not load NFL schedule data: ...
```
These indicate a silent fallback to empty DataFrames.

### 7.7 — Notebook Smoke Test (Optional but Recommended)

Open `MLModel.ipynb` and `PredictionCode.ipynb` in Jupyter, run the first patched cell of each, and confirm:
- No import errors
- Data loads with 2025 rows present
- Column coverage printout shows reasonable percentages (>50%)

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `gsis_id`/`full_name` assumption is wrong | Medium | High | Step 0 verification catches this before any code changes |
| 2025 player stats not yet in nflreadpy | Low | Low | Dynamic fallback already in `views.py`; will gracefully use 2024 |
| `ry_sh`, `wopr_x`, `racr` missing from `load_player_stats` | Low | Medium | Check in Step 0; these are nflverse-standard columns |
| Patch scripts silently fail (wrong cell index) | Low | Medium | Run notebooks after patching and verify cell content manually |
| PBP data for 2025 is very large / slow to load | Medium | Low | nflreadpy has built-in caching; first run will be slow, subsequent fast |

---

## Summary Checklist

- [ ] Step 0 — Run column verification script; confirm all expected columns present
- [ ] Step 1 — Install `nflreadpy` and `polars`; update `requirements.txt`
- [ ] Step 2 — Update `webapp/views.py` (schedule year 2024→2025; swap all nfl_data_py calls)
- [ ] Step 3 — Update `Models/NewModel/_run_phase1.py` (swap import + 2 load calls)
- [ ] Step 4 — Update `Models/patch_mlmodel.py` (3 embedded cell strings; year range 2015-2024→2015-2026)
- [ ] Step 5 — Update `Models/patch_predcode.py` (3 embedded cell strings; CURRENT_YEAR 2024→2025; data years 2022-2023→2023-2024)
- [ ] Step 6 — Re-run both patch scripts to apply changes to `.ipynb` notebooks
- [ ] Step 7.1 — Column verification passes
- [ ] Step 7.2 — Standalone script tests pass
- [ ] Step 7.3 — Flask startup log shows 2025 data
- [ ] Step 7.4 — Rosters page shows correct 2025 data
- [ ] Step 7.5 — Rankings page loads without errors
- [ ] Step 7.6 — No empty DataFrame warnings in logs
- [ ] Step 7.7 — (Optional) Notebook smoke test passes
