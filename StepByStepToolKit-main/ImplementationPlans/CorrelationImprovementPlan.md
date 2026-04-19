# Correlation Improvement Plan — Achieving r > 0.5 Across All Formats

**Date:** 2026-03-26
**Current:** Full PPR r=0.092 | Half PPR r=0.177 | Non-PPR r=0.374
**Target:** r > 0.50 for all three formats
**Files to edit:** `Models/MLModel.ipynb`, `Models/PredictionCode.ipynb`

---

## Root Cause Analysis

### Why is Full PPR at r=0.09 (essentially random)?

Three compounding problems were found:

**Problem 1 — Missing "last year's PPG" as a direct feature (CRITICAL)**
`ppg_last_year` in training features = N-2 PPG (two seasons ago), NOT last season's PPG.
Here's why: `ppg_last_year = PPG.shift(1)` computes N-1 PPG for a row at season N.
But then `ppg_last_year` is added to `shifters`, so after `makeCorrectShift`, it shifts again — becoming N-2 PPG in the final training row.
Result: the model **never sees last year's PPG directly**. It only sees two-years-ago PPG and the N-2→N-1 trend.
Last year's PPG is the single strongest fantasy predictor. Without it, the model is flying blind.

**Problem 2 — Prediction features don't match training features (CRITICAL)**
`MLModel.ipynb` trains on **single-season per-game stats** (one row per player per year).
`PredictionCode.ipynb` dfMaker builds features by **averaging stats across 2-4 seasons** (x=1, x=2, x=3 weighted by games), then divides by total games across all years.
A player with 100 carries in 2023 and 150 carries in 2022 gets ~125 weighted carries, but the model expects ~100 (2023 only). This systematic mismatch corrupts all features.

**Problem 3 — Not enough predictive signal in features**
The model lacks several high-value metrics available in nfl_data_py:
- EPA (Expected Points Added) — one of the strongest efficiency predictors
- WOPR, RACR — opportunity quality metrics for WR/TE
- `pacr`, `dakota` — composite QB efficiency metrics
- Games missed (injury proxy) — tells model whether stats came from a partial season

---

## Change 1: Add `ppg_prev` as a Direct Feature (Highest Impact)

**Files:** `MLModel.ipynb` (all 3 cells) + `PredictionCode.ipynb` (cells 1-3)

### MLModel change (all 3 cells)

In `correctData()`, after computing `ppg_last_year` and `delta_ppg`, add:
```python
df['ppg_prev'] = df['PPG']  # will be shifted to become last year's PPG
```

Add `'ppg_prev'` to `shifters` in `makeCorrectShift()`.

After `makeCorrectShift`, the training row predicting season N now has:
- `ppg_prev` = N-1 PPG ← **last year's PPG, directly**
- `ppg_last_year` = N-2 PPG (two years ago)
- `delta_ppg` = N-1 PPG - N-2 PPG (trajectory into N-1)

### PredictionCode change (cells 1-3)

In each dfMaker, after computing `ppg_yb1` and `ppg_yb2`:
```python
individualDFXX['ppg_prev'] = ppg_yb1       # last year's PPG (YearsBack=1)
individualDFXX['ppg_last_year'] = ppg_yb2  # two years ago (YearsBack=2) — unchanged
individualDFXX['delta_ppg'] = ppg_yb1 - ppg_yb2  # unchanged
```

**Why this matters:** A simple "predict last year's PPG" baseline would likely achieve r ≈ 0.45-0.55 for skill positions. Without `ppg_prev`, our model can't even match that baseline. This single change is expected to push correlation from ~0.09 to ~0.35+ just by itself.

---

## Change 2: Fix Prediction to Use Single-Season Stats (Second Highest Impact)

**File:** `PredictionCode.ipynb` (cells 1-3)

### Current behavior (wrong)
The dfMaker accumulates stats from x=1 (2023), x=2 (2022), x=3 (2021) etc. and divides by total games. This produces a multi-year weighted average that looks nothing like a single-season row in training.

### New behavior
Rewrite each dfMaker to use **only YearsBack=1 (2023) per-game stats** as features:
- Find the YearsBack=1 row for the player (from `oldRBStats` etc.)
- Divide raw stats by GP to get per-game values directly
- Fall back to YearsBack=2 only if no YearsBack=1 data exists (injury/missing)
- Add `games_missed = max(0, 17 - GP_yb1)` as a feature (see Change 4)

This is a significant rewrite of the dfMaker loop for cells 1-3. The multi-year aggregation loop is replaced by a simple single-season lookup. The penalty/injury logic that weighted older years less is no longer needed — instead, `games_missed` becomes a feature the model learns from.

**Why this matters:** Currently every counting stat (carries, receiving_yards, etc.) in prediction is a blend across multiple years. The model was trained on single-season per-game stats. Fixing this alignment is expected to push correlation another ~0.10-0.15.

---

## Change 3: Add EPA and Advanced Opportunity Features

**Files:** `MLModel.ipynb` (all 3 cells) + `PredictionCode.ipynb` (cells 1-3)

Add the following columns from `nfl_data_py.import_seasonal_data()` to training and prediction:

### All positions
| Column | What it measures |
|--------|-----------------|
| `games_missed` | Computed: `max(0, 17 - GP)` — injury proxy |

### QB-specific
| Column | What it measures |
|--------|-----------------|
| `passing_epa` | Total expected points added passing |
| `pacr` | Passer Air Conversion Ratio (passing yards / air yards) |
| `dakota` | Composite QB efficiency metric (adjusted EPA + CPOE) |

### RB-specific
| Column | What it measures |
|--------|-----------------|
| `rushing_epa` | Total expected points added rushing |
| `receiving_epa` | EPA from receiving (pass-catching RB quality) |
| `rtd_sh` | Rushing TD share of team |
| `rfd_sh` | Rushing first down share |

### WR/TE-specific
| Column | What it measures |
|--------|-----------------|
| `wopr_x` | Weighted Opportunity Rating (0.7×target_share + 1.5×air_yards_share) |
| `racr` | Receiver Air Conversion Ratio (receiving_yards / air_yards) — efficiency |
| `receiving_epa` | EPA from receiving |
| `yac_sh` | YAC share within team — yards after catch contribution |
| `tgt_sh` | Target share (redundant with target_share but a different calculation) |

### MLModel implementation
In the merge at the top of each cell, expand the opp column list:
```python
# RB: was ['player_id','season','target_share','ry_sh']
opp = seasonal_all[['player_id','season','target_share','ry_sh',
                     'rushing_epa','receiving_epa','rtd_sh','rfd_sh']].copy()
# WRTE: was ['player_id','season','target_share','air_yards_share']
opp = seasonal_all[['player_id','season','target_share','air_yards_share',
                     'wopr_x','racr','receiving_epa','yac_sh','tgt_sh']].copy()
# QB: add new columns
opp = seasonal_all[['player_id','season','passing_epa','pacr','dakota']].copy()
```

Add all new columns to `shifters` so they shift 1 year (features = last year's opportunity metrics).

After `makeCorrectShift`, add `games_missed = max(0, 17 - GP)` — GP is already shifted.

### PredictionCode implementation
In cells 1-3, load the same expanded opp_data and merge by player_id into oldXXStats. New columns are picked up from the YearsBack=1 row during the single-season lookup (Change 2).

---

## Change 4: Tune XGBoost to Reduce Overfitting

**File:** `MLModel.ipynb` (all 3 cells)

### Current params
```python
XGB_PARAMS = {'n_estimators':400, 'learning_rate':0.05, 'max_depth':4,
              'subsample':0.8, 'colsample_bytree':0.8, 'min_child_weight':3,
              'reg_alpha':0.1, 'reg_lambda':1.0, 'random_state':42, 'verbosity':0}
```

### New params
```python
XGB_PARAMS = {'n_estimators':300, 'learning_rate':0.05, 'max_depth':3,
              'subsample':0.75, 'colsample_bytree':0.7, 'min_child_weight':5,
              'reg_alpha':0.3, 'reg_lambda':2.0, 'random_state':42, 'verbosity':0}
```

**Changes:**
- `max_depth`: 4→3 (shallower trees = less overfitting on small QB dataset)
- `min_child_weight`: 3→5 (requires more samples per leaf)
- `reg_alpha`: 0.1→0.3, `reg_lambda`: 1.0→2.0 (stronger L1/L2 regularization)
- `n_estimators`: 400→300, `subsample`/`colsample_bytree` slightly reduced

QBs especially have ~150-200 training rows after filtering, so max_depth=4 with 400 trees is overkill.

---

## Change 5: Limit Training to 2017-2023 (Modern Era)

**File:** `MLModel.ipynb` (all 3 cells)

Currently uses 2013-2023. Pre-2017 NFL football was a significantly different game:
- Lower pass rates, different rules on illegal contact/defensive holding
- Usage patterns for RBs and TEs have shifted dramatically
- Feature distributions from 2013-2016 may be training the model on patterns that no longer exist

**Change:** Update the seasonal data fetch range:
```python
# Was: list(range(2013, 2024))
seasonal_all = nfl.import_seasonal_data(list(range(2017, 2024)))
```

Also update the `dfFC.loc[dfFC['season'] != 2012]` filter to remove pre-2017:
```python
dfFC = dfFC[dfFC['season'] >= 2018]  # first prediction year after training starts at 2017
```

**Why:** More relevant training data → better generalization. Shrinks training set but improves signal-to-noise ratio.

---

## Change 6 (Optional): Separate WR and TE Models

**File:** `MLModel.ipynb` (cell 2 only) + `PredictionCode.ipynb` (cell 3)

Currently WRs and TEs are trained in the same model. These are very different player types:
- A TE like Travis Kelce has usage patterns more similar to a slot WR
- A blocking TE (e.g., 3 targets, 1.2 PPG) degrades the model's ability to predict receiving TEs
- `wopr_x`, `racr`, `target_share` mean different things for WR vs TE (TEs face different coverage)

**Change:** Split cell 2 into two separate models:
- `wrteModels/wrModelPPR.joblib` trained on WR only
- `wrteModels/teModelPPR.joblib` trained on TE only
- In scorer (PredictionCode cell 4): route WR to wrModel and TE to teModel

This adds complexity but should improve TE predictions significantly (TEs are notoriously hard to predict at the combined level).

⚠️ **This is the lowest-priority change.** Do Changes 1-5 first.

---

## Implementation Order

```
Step 1 — MLModel.ipynb: Add ppg_prev to all 3 cells (Change 1)
Step 2 — MLModel.ipynb: Add EPA/advanced features to all 3 cells (Change 3)
Step 3 — MLModel.ipynb: Update XGB params (Change 4) + training year range (Change 5)
Step 4 — Retrain all models (run MLModel.ipynb)
Step 5 — PredictionCode.ipynb cells 1-3: Rewrite dfMaker to single-season (Change 2) + add ppg_prev (Change 1) + add new features (Change 3)
Step 6 — Run full pipeline: PredictionCode → RankingCSVCreation → VBD → csvtosql
Step 7 — Run Evaluation2024.ipynb to check correlation
Step 8 — If still below 0.5: add Change 6 (separate WR/TE) and/or further tune params
```

---

## Open Questions

> ⚠️ **Q1 — Training data range:**
> Use 2017-2023 or keep 2013-2023? Narrower = less data but more relevant patterns.
> **Recommendation:** Start with 2017-2023 (modern era), test, fall back to 2013 if underfitting.

> ⚠️ **Q2 — Partial-season players in prediction:**
> If a player only played 5 games in 2023 (injured), should their 5-game per-game stats be used directly? Or should we fall back to 2022?
> **Recommendation:** Use 2023 stats if GP ≥ 8; fall back to 2022 if GP < 8. Add `games_missed` as a feature.

> ⚠️ **Q3 — Separate WR and TE models:**
> More accurate but more complex. Do you want to implement this if Changes 1-5 don't reach r > 0.5?

> ⚠️ **Q4 — Scoring format for ppg_prev:**
> `ppg_prev` in prediction needs to be format-specific (PPR vs Half vs Non-PPR). The current code computes this from counting stats per format — that's correct. Confirm this approach is acceptable.
