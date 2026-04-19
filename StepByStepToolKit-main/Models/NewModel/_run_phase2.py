import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

INPUT_DIR  = '../PickleFiles/NewModel'
OUTPUT_DIR = '../PickleFiles/NewModel'

# Weighted PPG weights: 70% last season, 25% two seasons ago, 5% three seasons ago
PPG_WEIGHTS = {0: 0.70, 1: 0.25, 2: 0.05}  # key = seasons ago

# Feature season and prediction year
FEATURE_SEASON = 2025
PREDICT_YEAR   = 2026

# Volume stats that should be scaled by games_pct to normalize missed time
# Rate stats (epa_per_att, yards_per_carry, etc.) are already per-play — leave as-is
QB_VOLUME  = ['attempts','completions','passing_yards','passing_tds','interceptions',
               'sacks','passing_epa','air_yards','rush_yards_qb','rush_tds_qb',
               'rz_attempts','rz_tds','scrambles']

RB_VOLUME  = ['carries','rushing_yards','rushing_tds','rushing_epa',
               'targets','receptions','receiving_yards','receiving_tds',
               'rz_carries','rz_rush_tds','fumbles_lost']

WR_VOLUME  = ['targets','receptions','receiving_yards','receiving_tds','receiving_epa',
               'air_yards','yac','rz_targets','rz_rec_tds','third_down_targets','fumbles_lost']

TE_VOLUME  = ['targets','receptions','receiving_yards','receiving_tds','receiving_epa',
               'air_yards','rz_targets','rz_rec_tds','third_down_targets']

POSITION_VOLUME = {'QB': QB_VOLUME, 'RB': RB_VOLUME, 'WR': WR_VOLUME, 'TE': TE_VOLUME}

print('Config loaded. Feature season:', FEATURE_SEASON, '→ predicting', PREDICT_YEAR)

# =========

# ── Helper Functions ──────────────────────────────────────────────────────────

def scale_volume_stats(df, volume_cols):
    """
    Scale volume stats by games_pct to normalize for missed time.
    A player who played 8/17 games gets their total yards scaled up to a full-season pace.
    Only applied to volume totals — rate stats are already per-play.
    """
    df = df.copy()
    for col in volume_cols:
        if col in df.columns:
            df[f'{col}_adj'] = df[col] / df['games_pct'].replace(0, np.nan)
    return df


def add_lag_features(df, stat_cols, id_col='player_name', season_col='season'):
    """
    For each stat column, add:
      - lag1_{col}: value from t-1 season
      - lag2_{col}: value from t-2 season
      - delta_{col}: lag1 - lag2 (trend direction)
    Players with only 1 season of data get NaN for lag2 and delta.
    Players with 0 prior seasons get NaN for all lags.
    XGBoost handles NaN natively — no artificial boost for experienced players.
    """
    df = df.sort_values([id_col, season_col]).copy()
    for col in stat_cols:
        if col not in df.columns:
            continue
        df[f'lag1_{col}'] = df.groupby(id_col)[col].shift(1)
        df[f'lag2_{col}'] = df.groupby(id_col)[col].shift(2)
        df[f'delta_{col}'] = df[f'lag1_{col}'] - df[f'lag2_{col}']
    return df


def weighted_ppg(df, id_col='player_name', season_col='season', ppg_col='ppg'):
    """
    Compute weighted PPG for each player-season:
      weighted_ppg = 0.70 * ppg(t) + 0.25 * ppg(t-1) + 0.05 * ppg(t-2)
    If prior seasons don't exist, renormalize weights to sum to 1.
    This avoids penalizing breakout players for weak historical seasons.
    """
    df = df.sort_values([id_col, season_col]).copy()
    df['ppg_lag1'] = df.groupby(id_col)[ppg_col].shift(1)
    df['ppg_lag2'] = df.groupby(id_col)[ppg_col].shift(2)

    def _weighted_row(row):
        vals    = [row[ppg_col], row['ppg_lag1'], row['ppg_lag2']]
        weights = [0.70, 0.25, 0.05]
        # Only use seasons that exist — renormalize so weights sum to 1
        pairs = [(v, w) for v, w in zip(vals, weights) if pd.notna(v)]
        if not pairs:
            return np.nan
        total_w = sum(w for _, w in pairs)
        return sum(v * (w / total_w) for v, w in pairs)

    df['weighted_ppg'] = df.apply(_weighted_row, axis=1)
    return df


def build_feature_row(df, feature_season, volume_cols, id_col='player_name'):
    """
    After lag features are added across all seasons, extract just the feature_season
    row for each player. This becomes the input to the 2026 model.
    """
    return df[df['season'] == feature_season].copy().reset_index(drop=True)


print('Helper functions defined.')

# =========

# ── QB Feature Engineering ────────────────────────────────────────────────────

qb = pd.read_pickle(f'{INPUT_DIR}/qb_dataset.pkl')
print(f'QB raw: {len(qb)} player-seasons across {sorted(qb["season"].unique())}')

# Step 1 — Scale volume stats by games_pct
qb = scale_volume_stats(qb, QB_VOLUME)

# Step 2 — Stat columns to create lags/deltas for
# Use adjusted volume stats + rate stats
qb_adj_cols = [f'{c}_adj' for c in QB_VOLUME if f'{c}_adj' in qb.columns]
qb_rate_cols = ['comp_pct','epa_per_att','cpoe','air_yards_pg','xpass','pass_oe',
                'passing_yards_pg','passing_tds_pg','games_pct']
qb_lag_cols = qb_adj_cols + qb_rate_cols

# Step 3 — Lag features
qb = add_lag_features(qb, qb_lag_cols)

# Step 4 — Weighted PPG
qb = weighted_ppg(qb)

# Step 5 — Extract feature season rows
qb_features = build_feature_row(qb, FEATURE_SEASON, QB_VOLUME)

print(f'QB features: {len(qb_features)} players for {PREDICT_YEAR} prediction')
print(f'Columns: {len(qb_features.columns)}')
print(qb_features[['player_name','team','age','weighted_ppg','lag1_passing_yards_adj',
                    'delta_passing_yards_adj','epa_per_att']].sort_values('weighted_ppg', ascending=False).head(10).to_string())

# =========

# ── RB Feature Engineering ────────────────────────────────────────────────────

rb = pd.read_pickle(f'{INPUT_DIR}/rb_dataset.pkl')
print(f'RB raw: {len(rb)} player-seasons across {sorted(rb["season"].unique())}')

# Step 1 — Scale volume stats
rb = scale_volume_stats(rb, RB_VOLUME)

# Step 2 — Stat columns
rb_adj_cols  = [f'{c}_adj' for c in RB_VOLUME if f'{c}_adj' in rb.columns]
rb_rate_cols = ['yards_per_carry','catch_rate','target_share','epa_per_carry',
                'carries_pg','rushing_yards_pg','targets_pg','games_pct']
rb_lag_cols  = rb_adj_cols + rb_rate_cols

# Step 3 — Lag features
rb = add_lag_features(rb, rb_lag_cols)

# Step 4 — Weighted PPG
rb = weighted_ppg(rb)

# Step 5 — Extract feature season rows
rb_features = build_feature_row(rb, FEATURE_SEASON, RB_VOLUME)

print(f'RB features: {len(rb_features)} players for {PREDICT_YEAR} prediction')
print(f'Columns: {len(rb_features.columns)}')
print(rb_features[['player_name','team','age','weighted_ppg','lag1_rushing_yards_adj',
                    'delta_rushing_yards_adj','target_share']].sort_values('weighted_ppg', ascending=False).head(10).to_string())

# =========

# ── WR Feature Engineering ────────────────────────────────────────────────────

wr = pd.read_pickle(f'{INPUT_DIR}/wr_dataset.pkl')
print(f'WR raw: {len(wr)} player-seasons across {sorted(wr["season"].unique())}')

# Step 1 — Scale volume stats
wr = scale_volume_stats(wr, WR_VOLUME)

# Step 2 — Stat columns
wr_adj_cols  = [f'{c}_adj' for c in WR_VOLUME if f'{c}_adj' in wr.columns]
wr_rate_cols = ['yards_per_rec','catch_rate','yac_per_rec','air_yards_per_tgt',
                'epa_per_target','target_share','air_yards_share','wopr',
                'third_down_tgt_share','targets_pg','receiving_yards_pg','games_pct']
wr_lag_cols  = wr_adj_cols + wr_rate_cols

# Step 3 — Lag features
wr = add_lag_features(wr, wr_lag_cols)

# Step 4 — Weighted PPG
wr = weighted_ppg(wr)

# Step 5 — Extract feature season rows
wr_features = build_feature_row(wr, FEATURE_SEASON, WR_VOLUME)

print(f'WR features: {len(wr_features)} players for {PREDICT_YEAR} prediction')
print(f'Columns: {len(wr_features.columns)}')
print(wr_features[['player_name','team','age','weighted_ppg','lag1_receiving_yards_adj',
                    'delta_receiving_yards_adj','wopr']].sort_values('weighted_ppg', ascending=False).head(10).to_string())

# =========

# ── TE Feature Engineering ────────────────────────────────────────────────────

te = pd.read_pickle(f'{INPUT_DIR}/te_dataset.pkl')
print(f'TE raw: {len(te)} player-seasons across {sorted(te["season"].unique())}')

# Step 1 — Scale volume stats
te = scale_volume_stats(te, TE_VOLUME)

# Step 2 — Stat columns
te_adj_cols  = [f'{c}_adj' for c in TE_VOLUME if f'{c}_adj' in te.columns]
te_rate_cols = ['yards_per_rec','catch_rate','epa_per_target','air_yards_per_tgt',
                'target_share','air_yards_share','third_down_tgt_share',
                'targets_pg','receiving_yards_pg','games_pct']
te_lag_cols  = te_adj_cols + te_rate_cols

# Step 3 — Lag features
te = add_lag_features(te, te_lag_cols)

# Step 4 — Weighted PPG
te = weighted_ppg(te)

# Step 5 — Extract feature season rows
te_features = build_feature_row(te, FEATURE_SEASON, TE_VOLUME)

print(f'TE features: {len(te_features)} players for {PREDICT_YEAR} prediction')
print(f'Columns: {len(te_features.columns)}')
print(te_features[['player_name','team','age','weighted_ppg','lag1_receiving_yards_adj',
                    'delta_receiving_yards_adj','target_share']].sort_values('weighted_ppg', ascending=False).head(10).to_string())

# =========

# ── Validation — Check lag/delta coverage ────────────────────────────────────
# Show how many players have lag1 vs lag2 features
# Players with 0 prior seasons = no lag (rookies/new dataset entries)
# Players with 1 prior season  = lag1 only, delta = NaN
# Players with 2+ prior seasons = full lag1 + lag2 + delta

for name, df in [('QB', qb_features), ('RB', rb_features), ('WR', wr_features), ('TE', te_features)]:
    # Find a representative lag col
    lag1_col = next((c for c in df.columns if c.startswith('lag1_') and 'ppg' not in c), None)
    lag2_col = next((c for c in df.columns if c.startswith('lag2_') and 'ppg' not in c), None)

    has_lag1  = df[lag1_col].notna().sum()  if lag1_col else 0
    has_lag2  = df[lag2_col].notna().sum()  if lag2_col else 0
    total     = len(df)

    print(f'{name}: {total} players | lag1={has_lag1} ({has_lag1/total*100:.0f}%) | '
          f'lag2={has_lag2} ({has_lag2/total*100:.0f}%) | '
          f'no lag={total-has_lag1} (will use current season only)')

print()
print('NaN distribution is expected — XGBoost handles missing values natively.')
print('Players with no lag data are NOT penalized; the model learns to use whatever is available.')

# =========

# ── Save Feature Datasets ─────────────────────────────────────────────────────

qb_features.to_pickle(f'{OUTPUT_DIR}/qb_features.pkl')
rb_features.to_pickle(f'{OUTPUT_DIR}/rb_features.pkl')
wr_features.to_pickle(f'{OUTPUT_DIR}/wr_features.pkl')
te_features.to_pickle(f'{OUTPUT_DIR}/te_features.pkl')

# Also save the full multi-season datasets (needed for Phase 3 walk-forward training)
qb.to_pickle(f'{OUTPUT_DIR}/qb_full.pkl')
rb.to_pickle(f'{OUTPUT_DIR}/rb_full.pkl')
wr.to_pickle(f'{OUTPUT_DIR}/wr_full.pkl')
te.to_pickle(f'{OUTPUT_DIR}/te_full.pkl')

print('Saved feature datasets (2025 rows for 2026 prediction):')
for name, df in [('QB', qb_features), ('RB', rb_features), ('WR', wr_features), ('TE', te_features)]:
    print(f'  {name}: {len(df)} players, {len(df.columns)} features')

print()
print('Saved full multi-season datasets (for Phase 3 training):')
for name, df in [('QB', qb), ('RB', rb), ('WR', wr), ('TE', te)]:
    print(f'  {name}: {len(df)} player-seasons, {len(df.columns)} columns')