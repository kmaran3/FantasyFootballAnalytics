import nfl_data_py as nfl
import pandas as pd
import numpy as np
import pickle
import os
import warnings
warnings.filterwarnings('ignore')

SEASONS = [2020, 2021, 2022, 2023, 2024, 2025]
MIN_GAMES = 8  # minimum games played to include a player-season
OUTPUT_DIR = '../PickleFiles/NewModel'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Age from peak by position
PEAK_AGE = {'QB': 30, 'RB': 25, 'WR': 26, 'TE': 27}

print('Loading PBP data for seasons:', SEASONS)
pbp_raw = nfl.import_pbp_data(SEASONS)
pbp = pbp_raw[pbp_raw['season_type'] == 'REG'].copy()
print(f'Total regular season plays: {len(pbp):,}')

print('Loading roster data...')
roster_raw = nfl.import_seasonal_rosters(SEASONS)
roster = (
    roster_raw[roster_raw['game_type'] == 'REG']
    [['player_id','player_name','position','team','age','entry_year','rookie_year','draft_number','season']]
    .drop_duplicates(['player_id','season'])
)
print(f'Roster rows: {len(roster):,}')

# =========

# ── Helper Functions ──────────────────────────────────────────────────────────

def per_game(df, col, games_col='games'):
    """Return per-game rate, safe divide."""
    return df[col] / df[games_col].replace(0, np.nan)

def add_age_features(df, pos):
    """Add age, age_from_peak, age_squared, and age_bucket columns."""
    peak = PEAK_AGE.get(pos, 27)
    df['age_from_peak'] = df['age'] - peak
    df['age_squared']   = df['age'] ** 2
    # Age buckets — coarse grouping to study threshold effects
    bins   = [0, 22, 24, 26, 28, 30, 32, 35, 99]
    labels = ['<22','22-23','24-25','26-27','28-29','30-31','32-34','35+']
    df['age_bucket'] = pd.cut(df['age'], bins=bins, labels=labels, right=False)
    return df

def merge_roster(df, player_id_col, season_col='season'):
    """Merge age, team, position from roster onto aggregated stats."""
    return df.merge(
        roster[['player_id','player_name','position','team','age','entry_year','rookie_year','draft_number','season']],
        left_on=[player_id_col, season_col],
        right_on=['player_id','season'],
        how='left'
    ).drop(columns=['player_id'])

def red_zone_stats(pbp, player_id_col, yardline_threshold=20):
    """Aggregate red zone plays for a given player id column."""
    rz = pbp[pbp['yardline_100'] <= yardline_threshold]
    return (
        rz.groupby([player_id_col, 'season'])
        .size()
        .reset_index(name='rz_plays')
    )

def filter_garbage_time(df, threshold=21):
    """Remove plays where score differential is beyond threshold."""
    return df[df['score_differential'].abs() <= threshold]

print('Helper functions defined.')

# =========

# ── QB Dataset ────────────────────────────────────────────────────────────────

pbp_clean = filter_garbage_time(pbp)

qb_plays = pbp_clean[
    pbp_clean['passer_player_id'].notna() &
    pbp_clean['play_type'].isin(['pass'])
].copy()

qb_rush = pbp_clean[
    pbp_clean['rusher_player_id'].notna() &
    pbp_clean['qb_scramble'] == 1
].copy()

# Core passing aggregation
qb_agg = qb_plays.groupby(['passer_player_id','season']).agg(
    games          = ('game_id','nunique'),
    attempts       = ('pass_attempt','sum'),
    completions    = ('complete_pass','sum'),
    passing_yards  = ('passing_yards','sum'),
    passing_tds    = ('pass_touchdown','sum'),
    interceptions  = ('interception','sum'),
    sacks          = ('sack','sum'),
    passing_epa    = ('epa','sum'),
    cpoe           = ('cpoe','mean'),
    air_yards      = ('air_yards','sum'),
    xpass          = ('xpass','mean'),
    pass_oe        = ('pass_oe','mean'),
).reset_index()

# QB scramble rushing
qb_rush_agg = qb_rush.groupby(['rusher_player_id','season']).agg(
    rush_yards_qb  = ('rushing_yards','sum'),
    rush_tds_qb    = ('rush_touchdown','sum'),
    scrambles      = ('play_id','count'),
).reset_index().rename(columns={'rusher_player_id':'passer_player_id'})

# Red zone passing
rz_qb = pbp_clean[
    pbp_clean['passer_player_id'].notna() &
    (pbp_clean['yardline_100'] <= 20)
].groupby(['passer_player_id','season']).agg(
    rz_attempts = ('pass_attempt','sum'),
    rz_tds      = ('pass_touchdown','sum'),
).reset_index()

# Merge all QB pieces
qb = (
    qb_agg
    .merge(qb_rush_agg, on=['passer_player_id','season'], how='left')
    .merge(rz_qb,       on=['passer_player_id','season'], how='left')
)
qb = qb[qb['games'] >= MIN_GAMES].copy()

# Per-game rates
for col in ['attempts','completions','passing_yards','passing_tds','interceptions',
            'sacks','passing_epa','air_yards','rush_yards_qb','rush_tds_qb']:
    qb[f'{col}_pg'] = per_game(qb, col)

qb['comp_pct']       = qb['completions'] / qb['attempts'].replace(0, np.nan)
qb['air_yards_pg']   = per_game(qb, 'air_yards')
qb['epa_per_att']    = qb['passing_epa'] / qb['attempts'].replace(0, np.nan)
qb['games_pct']      = (qb['games'] / 17).clip(upper=1.0)

# Merge roster info
qb = merge_roster(qb, 'passer_player_id')
qb = qb[qb['position'] == 'QB'].copy()
qb = add_age_features(qb, 'QB')

print(f'QB dataset: {len(qb)} player-seasons')
print(qb[['player_name','season','team','age','age_bucket','games','passing_yards_pg','epa_per_att','cpoe']].sort_values(['season','passing_yards_pg'], ascending=[True,False]).head(10).to_string())

# =========

# ── RB Dataset ────────────────────────────────────────────────────────────────

rb_rush = pbp_clean[
    pbp_clean['rusher_player_id'].notna() &
    (pbp_clean['qb_scramble'] == 0)
].copy()

rb_rec = pbp_clean[
    pbp_clean['receiver_player_id'].notna() &
    pbp_clean['play_type'].isin(['pass'])
].copy()

# Rushing aggregation
rb_rush_agg = rb_rush.groupby(['rusher_player_id','season']).agg(
    games           = ('game_id','nunique'),
    carries         = ('rush_attempt','sum'),
    rushing_yards   = ('rushing_yards','sum'),
    rushing_tds     = ('rush_touchdown','sum'),
    rushing_epa     = ('epa','sum'),
    fumbles_lost    = ('fumble_lost','sum'),
).reset_index()

# EPA per carry — PBP-native rushing efficiency metric
rb_rush_agg['epa_per_carry'] = rb_rush_agg['rushing_epa'] / rb_rush_agg['carries'].replace(0, np.nan)

# Red zone carries (inside 10)
rz_rb = pbp_clean[
    pbp_clean['rusher_player_id'].notna() &
    (pbp_clean['yardline_100'] <= 10) &
    (pbp_clean['qb_scramble'] == 0)
].groupby(['rusher_player_id','season']).agg(
    rz_carries  = ('rush_attempt','sum'),
    rz_rush_tds = ('rush_touchdown','sum'),
).reset_index()

# Receiving aggregation
rb_rec_agg = rb_rec.groupby(['receiver_player_id','season']).agg(
    targets         = ('pass_attempt','sum'),
    receptions      = ('complete_pass','sum'),
    receiving_yards = ('receiving_yards','sum'),
    receiving_tds   = ('pass_touchdown','sum'),
    receiving_epa   = ('epa','sum'),
    rec_air_yards   = ('air_yards','sum'),
).reset_index()

# Team targets for target share
team_targets = pbp_clean[
    pbp_clean['play_type'] == 'pass'
].groupby(['posteam','season']).agg(
    team_targets = ('pass_attempt','sum')
).reset_index()

# Merge rushing + receiving
rb = (
    rb_rush_agg
    .merge(rz_rb,     on=['rusher_player_id','season'], how='left')
    .merge(rb_rec_agg.rename(columns={'receiver_player_id':'rusher_player_id'}),
           on=['rusher_player_id','season'], how='left')
)
rb = rb[rb['games'] >= MIN_GAMES].fillna(0)

# Per-game rates
for col in ['carries','rushing_yards','rushing_tds','rushing_epa',
            'targets','receptions','receiving_yards','receiving_tds']:
    rb[f'{col}_pg'] = per_game(rb, col)

rb['yards_per_carry'] = rb['rushing_yards'] / rb['carries'].replace(0, np.nan)
rb['catch_rate']      = rb['receptions'] / rb['targets'].replace(0, np.nan)
rb['games_pct']       = (rb['games'] / 17).clip(upper=1.0)

# Merge roster & team targets for target share
rb = merge_roster(rb, 'rusher_player_id')
rb = rb.merge(team_targets, left_on=['team','season'], right_on=['posteam','season'], how='left').drop(columns='posteam')
rb['target_share'] = rb['targets'] / rb['team_targets'].replace(0, np.nan)
rb = rb[rb['position'] == 'RB'].copy()
rb = add_age_features(rb, 'RB')

print(f'RB dataset: {len(rb)} player-seasons')
print(rb[['player_name','season','team','age','age_bucket','games','carries_pg','rushing_yards_pg','target_share']].sort_values(['season','rushing_yards_pg'], ascending=[True,False]).head(10).to_string())

# =========

# ── WR Dataset ────────────────────────────────────────────────────────────────

wr_rec = pbp_clean[
    pbp_clean['receiver_player_id'].notna() &
    pbp_clean['play_type'].isin(['pass'])
].copy()

wr_agg = wr_rec.groupby(['receiver_player_id','season']).agg(
    games           = ('game_id','nunique'),
    targets         = ('pass_attempt','sum'),
    receptions      = ('complete_pass','sum'),
    receiving_yards = ('receiving_yards','sum'),
    receiving_tds   = ('pass_touchdown','sum'),
    receiving_epa   = ('epa','sum'),
    air_yards       = ('air_yards','sum'),
    yac             = ('yards_after_catch','sum'),
    fumbles_lost    = ('fumble_lost','sum'),
).reset_index()

# Red zone targets inside 20
rz_wr = pbp_clean[
    pbp_clean['receiver_player_id'].notna() &
    (pbp_clean['yardline_100'] <= 20)
].groupby(['receiver_player_id','season']).agg(
    rz_targets  = ('pass_attempt','sum'),
    rz_rec_tds  = ('pass_touchdown','sum'),
).reset_index()

# 3rd down targets — measures QB trust
third_wr = pbp_clean[
    pbp_clean['receiver_player_id'].notna() &
    (pbp_clean['down'] == 3)
].groupby(['receiver_player_id','season']).agg(
    third_down_targets = ('pass_attempt','sum'),
).reset_index()

wr = (
    wr_agg
    .merge(rz_wr,    on=['receiver_player_id','season'], how='left')
    .merge(third_wr, on=['receiver_player_id','season'], how='left')
)
wr = wr[wr['games'] >= MIN_GAMES].fillna(0)

# Per-game rates
for col in ['targets','receptions','receiving_yards','receiving_tds','receiving_epa','air_yards']:
    wr[f'{col}_pg'] = per_game(wr, col)

wr['yards_per_rec']     = wr['receiving_yards'] / wr['receptions'].replace(0, np.nan)
wr['catch_rate']        = wr['receptions'] / wr['targets'].replace(0, np.nan)
wr['yac_per_rec']       = wr['yac'] / wr['receptions'].replace(0, np.nan)
wr['air_yards_per_tgt'] = wr['air_yards'] / wr['targets'].replace(0, np.nan)
wr['epa_per_target']    = wr['receiving_epa'] / wr['targets'].replace(0, np.nan)
wr['games_pct']         = (wr['games'] / 17).clip(upper=1.0)

# Merge roster + team targets for target/air yards share
wr = merge_roster(wr, 'receiver_player_id')
team_air_yards = pbp_clean[
    pbp_clean['play_type'] == 'pass'
].groupby(['posteam','season']).agg(
    team_targets   = ('pass_attempt','sum'),
    team_air_yards = ('air_yards','sum'),
).reset_index()

wr = wr.merge(team_air_yards, left_on=['team','season'], right_on=['posteam','season'], how='left').drop(columns='posteam')
wr['target_share']    = wr['targets']   / wr['team_targets'].replace(0, np.nan)
wr['air_yards_share'] = wr['air_yards'] / wr['team_air_yards'].replace(0, np.nan)
wr['wopr']            = (1.5 * wr['target_share']) + (0.7 * wr['air_yards_share'])
wr['third_down_tgt_share'] = wr['third_down_targets'] / wr['team_targets'].replace(0, np.nan)

wr = wr[wr['position'] == 'WR'].copy()
wr = add_age_features(wr, 'WR')

print(f'WR dataset: {len(wr)} player-seasons')
print(wr[['player_name','season','team','age','age_bucket','games','target_share','wopr','receiving_yards_pg']].sort_values(['season','wopr'], ascending=[True,False]).head(10).to_string())

# =========

# ── TE Dataset ────────────────────────────────────────────────────────────────
# Same aggregation as WR — just filtered to TE position

te = wr_agg.copy()
te = (
    te
    .merge(rz_wr,    on=['receiver_player_id','season'], how='left')
    .merge(third_wr, on=['receiver_player_id','season'], how='left')
)
te = te[te['games'] >= MIN_GAMES].fillna(0)

for col in ['targets','receptions','receiving_yards','receiving_tds','receiving_epa','air_yards']:
    te[f'{col}_pg'] = per_game(te, col)

te['yards_per_rec']     = te['receiving_yards'] / te['receptions'].replace(0, np.nan)
te['catch_rate']        = te['receptions'] / te['targets'].replace(0, np.nan)
te['epa_per_target']    = te['receiving_epa'] / te['targets'].replace(0, np.nan)
te['air_yards_per_tgt'] = te['air_yards'] / te['targets'].replace(0, np.nan)
te['games_pct']         = (te['games'] / 17).clip(upper=1.0)

te = merge_roster(te, 'receiver_player_id')
te = te.merge(team_air_yards, left_on=['team','season'], right_on=['posteam','season'], how='left').drop(columns='posteam')
te['target_share']    = te['targets']   / te['team_targets'].replace(0, np.nan)
te['air_yards_share'] = te['air_yards'] / te['team_air_yards'].replace(0, np.nan)
te['third_down_tgt_share'] = te['third_down_targets'] / te['team_targets'].replace(0, np.nan)

te = te[te['position'] == 'TE'].copy()
te = add_age_features(te, 'TE')

print(f'TE dataset: {len(te)} player-seasons')
print(te[['player_name','season','team','age','age_bucket','games','target_share','receiving_yards_pg','epa_per_target']].sort_values(['season','target_share'], ascending=[True,False]).head(10).to_string())

# =========

# ── Fantasy Points — Add Target Variable ─────────────────────────────────────
# Calculate PPR fantasy points directly from PBP for each player-season

def calc_fantasy_ppr(pbp):
    """Calculate PPR fantasy points per player per season from PBP."""
    results = []

    # Passing
    pass_pts = pbp[pbp['passer_player_id'].notna()].groupby(['passer_player_id','season']).agg(
        pass_yds = ('passing_yards','sum'),
        pass_tds = ('pass_touchdown','sum'),
        ints     = ('interception','sum'),
    ).reset_index()
    pass_pts['fantasy_pts'] = (pass_pts['pass_yds'] * 0.04) + (pass_pts['pass_tds'] * 4) - (pass_pts['ints'] * 2)
    pass_pts = pass_pts[['passer_player_id','season','fantasy_pts']].rename(columns={'passer_player_id':'player_id'})

    # Rushing (non-scramble)
    rush_pts = pbp[pbp['rusher_player_id'].notna() & (pbp['qb_scramble']==0)].groupby(['rusher_player_id','season']).agg(
        rush_yds = ('rushing_yards','sum'),
        rush_tds = ('rush_touchdown','sum'),
    ).reset_index()
    rush_pts['fantasy_pts'] = (rush_pts['rush_yds'] * 0.1) + (rush_pts['rush_tds'] * 6)
    rush_pts = rush_pts[['rusher_player_id','season','fantasy_pts']].rename(columns={'rusher_player_id':'player_id'})

    # Receiving (PPR = 1pt per reception)
    rec_pts = pbp[pbp['receiver_player_id'].notna()].groupby(['receiver_player_id','season']).agg(
        rec      = ('complete_pass','sum'),
        rec_yds  = ('receiving_yards','sum'),
        rec_tds  = ('pass_touchdown','sum'),
    ).reset_index()
    rec_pts['fantasy_pts'] = rec_pts['rec'] + (rec_pts['rec_yds'] * 0.1) + (rec_pts['rec_tds'] * 6)
    rec_pts = rec_pts[['receiver_player_id','season','fantasy_pts']].rename(columns={'receiver_player_id':'player_id'})

    # QB scramble rushing
    qb_rush_pts = pbp[pbp['rusher_player_id'].notna() & (pbp['qb_scramble']==1)].groupby(['rusher_player_id','season']).agg(
        rush_yds = ('rushing_yards','sum'),
        rush_tds = ('rush_touchdown','sum'),
    ).reset_index()
    qb_rush_pts['fantasy_pts'] = (qb_rush_pts['rush_yds'] * 0.1) + (qb_rush_pts['rush_tds'] * 6)
    qb_rush_pts = qb_rush_pts[['rusher_player_id','season','fantasy_pts']].rename(columns={'rusher_player_id':'player_id'})

    all_pts = pd.concat([pass_pts, rush_pts, rec_pts, qb_rush_pts])
    return all_pts.groupby(['player_id','season'])['fantasy_pts'].sum().reset_index()

fantasy_pts = calc_fantasy_ppr(pbp)
print(f'Fantasy points calculated for {len(fantasy_pts)} player-seasons')

# Merge fantasy points onto each position dataset
for pos_df, id_col, name in [
    (qb, 'passer_player_id', 'QB'),
    (rb, 'rusher_player_id', 'RB'),
    (wr, 'receiver_player_id', 'WR'),
    (te, 'receiver_player_id', 'TE'),
]:
    merged = pos_df.merge(fantasy_pts, left_on=[id_col,'season'], right_on=['player_id','season'], how='left').drop(columns='player_id')
    merged['ppg'] = merged['fantasy_pts'] / merged['games'].replace(0, np.nan)
    globals()[name.lower()] = merged
    print(f'{name}: fantasy_pts range {merged["fantasy_pts"].min():.1f} – {merged["fantasy_pts"].max():.1f}, avg ppg {merged["ppg"].mean():.1f}')

# =========

# ── Age Curve Analysis ────────────────────────────────────────────────────────
# For each position, show average PPG by age bucket to understand
# how age thresholds impact fantasy performance

import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('Average Fantasy PPG by Age Bucket (2023–2025)', fontsize=14, fontweight='bold')

pos_data = [('QB', qb), ('RB', rb), ('WR', wr), ('TE', te)]

for ax, (pos, df) in zip(axes.flat, pos_data):
    age_curve = (
        df.groupby('age_bucket', observed=True)['ppg']
        .agg(['mean','count','std'])
        .reset_index()
    )
    age_curve = age_curve[age_curve['count'] >= 3]  # min 3 players per bucket

    bars = ax.bar(age_curve['age_bucket'].astype(str), age_curve['mean'],
                  color='#444', alpha=0.85, edgecolor='white')
    ax.errorbar(range(len(age_curve)), age_curve['mean'],
                yerr=age_curve['std'], fmt='none', color='#f8f39f', capsize=4)

    # Annotate with sample size
    for i, (_, row) in enumerate(age_curve.iterrows()):
        ax.text(i, row['mean'] + 0.3, f'n={int(row["count"])}', ha='center', fontsize=7, color='gray')

    ax.set_title(f'{pos} — Peak age: {PEAK_AGE[pos]}', fontweight='bold')
    ax.set_xlabel('Age Bucket')
    ax.set_ylabel('Avg PPG (PPR)')
    ax.tick_params(axis='x', rotation=30)

plt.tight_layout()
plt.savefig(f'{OUTPUT_DIR}/age_curves.png', dpi=120, bbox_inches='tight')
plt.show()
print('Age curve chart saved.')

# =========

# ── Team Context Analysis ─────────────────────────────────────────────────────
# Show average PPG by team for each position to understand team-level variance

fig, axes = plt.subplots(2, 2, figsize=(18, 12))
fig.suptitle('Average Fantasy PPG by Team — 2025 Season', fontsize=14, fontweight='bold')

for ax, (pos, df) in zip(axes.flat, pos_data):
    team_avg = (
        df[df['season'] == 2025]
        .groupby('team')['ppg']
        .mean()
        .sort_values(ascending=False)
        .reset_index()
    )
    ax.barh(team_avg['team'], team_avg['ppg'], color='#444', alpha=0.85)
    ax.set_title(f'{pos}', fontweight='bold')
    ax.set_xlabel('Avg PPG (PPR)')
    ax.invert_yaxis()

plt.tight_layout()
plt.savefig(f'{OUTPUT_DIR}/team_ppg.png', dpi=120, bbox_inches='tight')
plt.show()
print('Team PPG chart saved.')

# =========

# ── Save Datasets ─────────────────────────────────────────────────────────────

qb.to_pickle(f'{OUTPUT_DIR}/qb_dataset.pkl')
rb.to_pickle(f'{OUTPUT_DIR}/rb_dataset.pkl')
wr.to_pickle(f'{OUTPUT_DIR}/wr_dataset.pkl')
te.to_pickle(f'{OUTPUT_DIR}/te_dataset.pkl')

print('Datasets saved to', OUTPUT_DIR)
for name, df in [('QB',qb),('RB',rb),('WR',wr),('TE',te)]:
    print(f'  {name}: {len(df)} rows, {len(df.columns)} columns')
    print(f'       Seasons: {sorted(df["season"].unique())}')
    print(f'       Age range: {df["age"].min():.0f}–{df["age"].max():.0f}')