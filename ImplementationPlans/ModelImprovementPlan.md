# Model Improvement Plan — 2024 Validation & Accuracy Optimization

**Date:** 2026-03-24
**Status:** Draft — pending answers to open questions (marked ⚠️)

---

## Current Model Performance (Baseline)

| Metric | Full PPR | Half PPR | Non-PPR |
|--------|----------|----------|---------|
| MAE | 5.11 PPG | 4.52 PPG | 3.92 PPG |
| RMSE | 6.52 | 5.95 | 5.34 |
| Correlation | **0.10** | 0.19 | 0.31 |
| Matched Players | 302 | 302 | 302 |

**Key failures:** Saquon Barkley (-18 PPG error), Ja'Marr Chase (-17.5), Derrick Henry (-17). The model is essentially near-random for Full PPR (r=0.10).

**Root causes identified:**
1. No opportunity features — target share, carry share, snap % are the strongest predictors in fantasy research but are absent
2. No year-over-year change features — the model sees absolute stats but not trajectory
3. Random 80/20 split leaks future data into training — should use time-series cross-validation
4. No age curve modeling — RB decline at 28, WR peak at 26-28, etc.
5. Gradient Boosting with default params isn't ideal; no ensembling
6. Breakout players (new team, new role, post-injury bounce-back) have no indicator features

---

## Open Questions

> ⚠️ **Q1 — Training vs test use of 2024 data:**
> (a) Use 2024 actuals as **validation only** — tune the model to minimize 2024 error, then output improved 2024 predictions
> (b) **Add 2024 to training set** — so the eventual 2025 prediction model also learns from 2024
> **Recommendation:** Do both — first validate/tune using 2024 as test, then add 2024 to training for the final 2025-ready model

> ⚠️ **Q2 — Scoring format priority:**
> All three formats (Full/Half/Non-PPR) or focus on one?

> ⚠️ **Q3 — K and DEF positions:**
> Include kicker/defense in model improvements or skip?

> ⚠️ **Q4 — Breakout player features:**
> Add new-team, contract-year, age-curve, coaching change features?

> ⚠️ **Q5 — Runtime constraints:**
> Large ensembles/neural nets can take 10-30 min to train. Acceptable?

---

## Improvement Strategy (Ranked by Expected Impact)

### Tier 1 — Highest Impact (fix fundamental data gaps)

#### 1A. Fetch 2024 Actual Stats & Build Evaluation Framework
**Why:** Can't improve what you can't measure. Need ground truth per player.
- Use `nfl_data_py.import_seasonal_data([2024])` to get 2024 actual PPG for all skill position players
- Build a comparison DataFrame: `[Name, Team, Position, Predicted_PPG, Actual_PPG, Error, Abs_Error]`
- Segment errors by position, age bracket, games played, PPG tier
- Identify systematic biases (e.g., does model always underpredict RBs over 30?)
- Save as `2024_model_evaluation.pkl`

#### 1B. Add Opportunity / Role Features
**Why:** Target share and carry share are the #1 predictors of fantasy output per every major fantasy research study. The current model doesn't have them.
- **Target Share** (WR/TE): targets / team_pass_attempts — measures how much of the passing game a receiver controls
- **Air Yards Share** (WR/TE): player_air_yards / team_pass_air_yards — captures downfield role
- **Carry Share** (RB): carries / team_rush_attempts — captures backfield workload split
- **Route Run %** (WR/TE): targets / routes_run — derived from NGS data
- **Snap %**: snaps / team_snaps — captures overall involvement
- **Red Zone Target/Carry Share**: captures TD opportunity, very predictive
- Source: `nfl_data_py.import_seasonal_data()` has target_share, air_yards_share; NGS data has route participation

#### 1C. Add Year-Over-Year Change Features (Trajectory)
**Why:** The model currently sees a player's absolute stats from year N-1 but not whether they're improving or declining. A player who jumped from 12 to 20 PPG is very different from one who fell from 25 to 20.
- For each stat: `delta_stat = stat_year_N-1 - stat_year_N-2` (YoY change)
- Key deltas: `delta_ppg`, `delta_targets`, `delta_carries`, `delta_share`
- Age-adjusted delta: whether the change is expected given age curve
- Add as additional features to all three position DataFrames

#### 1D. Fix Cross-Validation (Time-Series Split)
**Why:** Current random 80/20 split allows the model to train on 2022 data and test on 2020 — this inflates accuracy metrics and the model learns patterns that don't generalize to future years.
- Replace `train_test_split(random_state=42)` with **TimeSeriesSplit** or manual walk-forward:
  - Fold 1: Train 2013-2018, test 2019
  - Fold 2: Train 2013-2019, test 2020
  - Fold 3: Train 2013-2020, test 2021
  - Fold 4: Train 2013-2021, test 2022
  - Fold 5: Train 2013-2022, test 2023
- This gives a realistic estimate of how the model generalizes to future seasons
- MAE/correlation from this will be much more honest than current metrics

---

### Tier 2 — High Impact (model architecture improvements)

#### 2A. Switch to XGBoost / LightGBM
**Why:** XGBoost typically outperforms sklearn's GradientBoostingRegressor on tabular data. LightGBM is faster and handles sparse features better. Both support more sophisticated regularization.
- Replace `GradientBoostingRegressor` with `xgboost.XGBRegressor` and `lightgbm.LGBMRegressor`
- Tune: `n_estimators`, `learning_rate`, `max_depth`, `subsample`, `colsample_bytree`, `reg_alpha`, `reg_lambda`
- Use `early_stopping_rounds` to prevent overfitting on validation set
- Compare with current GBR on time-series CV

#### 2B. Ensemble (Stacking)
**Why:** No single model consistently wins on fantasy prediction. Averaging predictions from multiple models typically reduces variance and improves accuracy.
- **Level 0 models:** GBR + XGBoost + LightGBM + Ridge Regression
- **Level 1 (meta-learner):** Simple weighted average or Ridge regression on level-0 out-of-fold predictions
- Expected improvement: ~10-15% MAE reduction over best single model
- Use `sklearn.ensemble.StackingRegressor`

#### 2C. Position-Specific Feature Sets
**Why:** The current model uses the same feature architecture for all positions but QBs and TEs have very different predictive signals.
- **QB-specific:** Add QBR, Next Gen Stats (time to throw, completion % above expectation, aggressiveness %), team pass rate
- **RB-specific:** Add PFF run blocking grade (team context), rush yards before contact, broken tackles, YAC
- **WR-specific:** Add separation (NGS), cushion (coverage), contested catch %, route tree diversity
- **TE-specific:** Distinguish blocking TEs (near-zero fantasy) from receiving TEs upfront
- Source: `nfl_data_py.import_ngs_data()`, `nfl_data_py.import_pfr_advstats()`

#### 2D. Age Curve Modeling
**Why:** Each position has a well-documented performance curve. RBs peak at 24-25 and decline sharply after 27. WRs peak at 26-28 with a slower decline. QBs peak at 28-32. The current model uses raw age but doesn't capture the nonlinear curve shape.
- Create `age_relative_to_peak` feature: `age - position_peak_age` (negative = still improving, positive = declining)
- Add `age_squared` term to capture the parabolic curve
- QB peak age: 30, RB peak: 25, WR peak: 27, TE peak: 26
- Add `career_year` (years since first season) as a proxy for development stage

---

### Tier 3 — Moderate Impact (contextual / situational features)

#### 3A. Team Context Changes
**Why:** A player's 2023 stats don't account for a coaching change, QB change, or team scheme change in 2024. These are major predictors of over/underperformance vs. historical projections.
- **New team indicator**: binary flag for players who changed teams (via comparing team in year N-1 vs year N)
- **New HC / OC**: coaching staff changes affect scheme and usage
- **QB change**: impacts WR/TE value substantially
- **Offensive scheme**: pass rate, run rate tendencies by coach
- Source: Manual mapping or web scrape of coaching changes; `nfl_data_py.import_team_stats()`

#### 3B. Injury / Availability Features
**Why:** Players coming off injury have different baselines. A WR who played 9 games last year (injured) shouldn't be projected the same as one who played 16.
- `games_missed_prev_year` = 17 - GP (as injury proxy)
- `injury_flag` = 1 if GP < 12 in prior year
- `returning_from_injury` = injury_flag AND player is in current roster
- This directly addresses the model treating injured-year stats the same as healthy-year stats

#### 3C. Strength of Schedule (SOS) Features
**Why:** Projected opponents' defensive quality affects expected fantasy output.
- `avg_opposing_def_rank_first8weeks` — average defensive ranking of first 8 opponents
- `opposing_def_pts_allowed_to_position` — how many PPG each opponent allows to QB/RB/WR
- Source: `nfl_data_py.import_schedules([2024])` + `import_team_stats()`

#### 3D. Recency Weighting in Training
**Why:** A player's 2022 season should matter more than their 2016 season when predicting 2024. But the current model treats all historical seasons equally.
- Weight training samples by `recency_weight = 0.85 ^ YearsBack`
  - YearsBack=1 (most recent): weight = 0.85
  - YearsBack=2: weight = 0.72
  - YearsBack=3: weight = 0.61
  - etc.
- Pass `sample_weight` to `model.fit()` in sklearn/XGBoost
- This effectively makes the model prefer patterns from recent seasons

---

### Tier 4 — Advanced (complex but potentially high payoff)

#### 4A. Player Aging Trajectories (Multi-Year Input)
**Why:** The current model uses a single snapshot of a player's most recent season. Using 2-3 years of history as input captures trajectory better.
- For each player: use last 2 years of stats as features (year N-1 and year N-2)
- Requires reformatting the training data significantly
- Only feasible for players with 2+ year history (rookies handled separately)

#### 4B. Regression-to-Mean Adjustment
**Why:** Fantasy research consistently shows that outlier seasons (very high or very low TD totals, reception rates) regress toward the mean. The model can't detect this.
- Calculate position-specific mean and std for each stat
- Add `z_score_ppg` (how many std devs above/below position average the player was)
- High z-score → expect regression downward; low z-score → expect regression upward
- Especially valuable for TD-dependent players

#### 4C. Separate Rookie/Veteran Models
**Why:** Rookies and second-year players have very different predictive signals than veterans. Mixing them degrades both models.
- Rookie model: use college stats, draft position, age, college conference, PFF college grades
- Veteran model: current approach but without rookies contaminating the data
- Source: `nfl_data_py.import_draft_picks()`, PFF college grades

#### 4D. Neural Network (MLP)
**Why:** If the feature set grows large (50+ features), a multi-layer perceptron can capture non-linear interactions that tree models miss.
- Architecture: 3-layer MLP (64→32→16 neurons), ReLU, dropout=0.2, batch normalization
- Use `sklearn.neural_network.MLPRegressor` or PyTorch/Keras
- Only add if tabular models plateau; neural nets require more data and tuning

---

## Implementation Notebook Structure

All improvements will be implemented as new/modified Jupyter notebooks:

| Notebook | Purpose |
|----------|---------|
| `Evaluation2024.ipynb` | Fetch 2024 actuals, compare to predictions, error analysis |
| `FeatureEngineering.ipynb` | Build expanded feature set (opportunity, delta, age curve, context) |
| `ModelComparison.ipynb` | Compare GBR vs XGBoost vs LightGBM with time-series CV |
| `EnsembleModel.ipynb` | Stacking ensemble of best models |
| `ImprovedPrediction.ipynb` | Run full improved pipeline with new features + models |
| `UpdatedRankings.ipynb` | Regenerate rankings from improved predictions |

---

## Recommended Implementation Order

```
Phase 1 (Foundation):
  1. Fetch 2024 actuals → evaluation framework
  2. Fix time-series CV → honest accuracy measurement
  3. Add opportunity features (target share, carry share) → biggest signal gain

Phase 2 (Model):
  4. Switch to XGBoost/LightGBM
  5. Add YoY change features + age curve
  6. Ensemble GBR + XGB + LGB

Phase 3 (Polish):
  7. Add context features (new team, injury, SOS)
  8. Recency weighting
  9. Separate rookie model (if data supports)

Phase 4 (Final):
  10. Add 2024 to training set → retrain for 2025 predictions
  11. Regenerate all ranking pickle files
  12. Update webapp DB via csvtosql.py
```

---

## Expected Outcome Targets

| Metric | Current | Phase 1 Target | Final Target |
|--------|---------|----------------|--------------|
| Full PPR MAE | 5.11 PPG | ≤ 4.0 PPG | ≤ 3.0 PPG |
| Full PPR Correlation | 0.10 | ≥ 0.35 | ≥ 0.50 |
| Non-PPR MAE | 3.92 PPG | ≤ 3.0 PPG | ≤ 2.5 PPG |
| Non-PPR Correlation | 0.31 | ≥ 0.45 | ≥ 0.60 |

*Note: Fantasy football is inherently noisy — correlation above 0.55 would be exceptional and likely matches or exceeds commercial models like FantasyPros consensus.*

---

## Data Sources Summary

| Source | Access Method | Data Available |
|--------|--------------|----------------|
| 2024 Actual Stats | `nfl_data_py.import_seasonal_data([2024])` | PPG, all counting stats |
| Target/Carry Share | `nfl_data_py.import_seasonal_data([2024])` | target_share, air_yards_share |
| NGS Metrics | `nfl_data_py.import_ngs_data([2024])` | separation, time-to-throw, etc. |
| PFR Advanced | `nfl_data_py.import_pfr_advstats([2024])` | broken tackles, drops, pressure rate |
| Schedule/SOS | `nfl_data_py.import_schedules([2024])` | already used |
| Draft Data | `nfl_data_py.import_draft_picks()` | for rookie model |
| Coaching Changes | Manual / web scrape | new HC/OC flags |
