import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors
import umap
import pickle
import warnings
warnings.filterwarnings('ignore')

BASE        = Path(__file__).parent.parent / 'PickleFiles' / 'NewModel'
GRADES_PATH = Path(__file__).parent.parent / 'PickleFiles' / 'AVgrades.pkl'
OUT         = BASE
K_COMPS     = 5
PEAK_AGE    = {'QB': 30, 'RB': 25, 'WR': 26, 'TE': 27}

# ── Team grades ───────────────────────────────────────────────────
grades_raw = pd.read_pickle(GRADES_PATH)
grades = grades_raw[['season', 'team', 'rb', 'oline', 'wrte', 'qb']].copy()
grades = grades.rename(columns={'rb': 'rb_grade', 'oline': 'oline_grade', 'wrte': 'wrte_grade', 'qb': 'qb_grade'})
print(f'Team grades: {grades.shape}, seasons {sorted(grades["season"].unique())}')

# ── Load full datasets + new_team flag ───────────────────────────
def add_new_team_flag(df):
    df = df.sort_values(['player_name', 'season']).copy()
    df['prev_team'] = df.groupby('player_name')['team'].shift(1)
    df['new_team'] = ((df['prev_team'].notna()) & (df['team'] != df['prev_team'])).astype(int)
    return df.drop(columns=['prev_team'])

pos_dfs = {}
for pos in ['rb', 'wr', 'te', 'qb']:
    df = pd.read_pickle(BASE / f'{pos}_full.pkl')
    df = add_new_team_flag(df)
    pos_dfs[pos] = df
    print(f'{pos.upper()}: {df.shape}, seasons {sorted(df["season"].unique())}')

# ── Feature sets ─────────────────────────────────────────────────
FEATURES = {
    'rb': ['age', 'seasons_played', 'age_curve', 'new_team',
           'ppg_lag1', 'weighted_ppg',
           'lag1_carries_pg', 'lag1_targets_pg', 'lag1_target_share',
           'rb_grade', 'oline_grade'],
    'wr': ['age', 'seasons_played', 'age_curve', 'new_team',
           'ppg_lag1', 'weighted_ppg',
           'lag1_targets_pg', 'lag1_target_share', 'lag1_wopr',
           'wrte_grade'],
    'te': ['age', 'seasons_played', 'age_curve', 'new_team',
           'ppg_lag1', 'weighted_ppg',
           'lag1_targets_pg', 'lag1_target_share',
           'wrte_grade'],
    'qb': ['age', 'seasons_played', 'age_curve', 'new_team',
           'ppg_lag1', 'weighted_ppg',
           'lag1_passing_yards_pg', 'lag1_passing_tds_pg', 'lag1_comp_pct',
           'qb_grade'],
}

RADAR_FEATURES = {
    'rb': ['age', 'seasons_played', 'ppg_lag1', 'lag1_carries_pg', 'lag1_target_share', 'new_team', 'rb_grade', 'oline_grade'],
    'wr': ['age', 'seasons_played', 'ppg_lag1', 'lag1_targets_pg', 'lag1_target_share', 'lag1_wopr', 'new_team', 'wrte_grade'],
    'te': ['age', 'seasons_played', 'ppg_lag1', 'lag1_targets_pg', 'lag1_target_share', 'new_team', 'wrte_grade'],
    'qb': ['age', 'seasons_played', 'ppg_lag1', 'lag1_passing_yards_pg', 'lag1_passing_tds_pg', 'lag1_comp_pct', 'new_team', 'qb_grade'],
}

# ── Build entering-season profiles ───────────────────────────────
def build_entering_profile(pos, df, grades):
    pos_upper = pos.upper()
    peak = PEAK_AGE.get(pos_upper, 28)
    grade_cols = {
        'rb': ['rb_grade', 'oline_grade'],
        'wr': ['wrte_grade'],
        'te': ['wrte_grade'],
        'qb': ['qb_grade'],
    }[pos]

    # Historical: entering seasons 2021-2025
    hist = df[df['season'] >= 2021].copy()
    hist = hist.merge(grades[['season', 'team'] + grade_cols], on=['season', 'team'], how='left')
    hist = hist.dropna(subset=['ppg_lag1'])
    hist = hist.dropna(subset=FEATURES[pos])
    hist['outcome_ppg'] = hist['ppg']
    hist['is_current']  = False

    # Current: entering 2026
    curr = df[df['season'] == 2025].copy()
    curr['age']           = curr['age'] + 1
    curr['seasons_played']= curr['seasons_played'] + 1
    curr['age_curve']     = peak - curr['age']
    curr['ppg_lag1']      = curr['ppg']
    if 'targets_pg'   in curr.columns: curr['lag1_targets_pg']   = curr['targets_pg']
    if 'target_share' in curr.columns: curr['lag1_target_share'] = curr['target_share']
    if 'carries_pg'   in curr.columns: curr['lag1_carries_pg']   = curr['carries_pg']
    if 'wopr'         in curr.columns: curr['lag1_wopr']          = curr['wopr']
    if 'passing_yards_pg' in curr.columns: curr['lag1_passing_yards_pg'] = curr['passing_yards_pg']
    if 'passing_tds_pg'  in curr.columns: curr['lag1_passing_tds_pg']  = curr['passing_tds_pg']
    if 'comp_pct'        in curr.columns: curr['lag1_comp_pct']         = curr['comp_pct']
    g2025 = grades[grades['season'] == 2025][['team'] + grade_cols]
    curr = curr.merge(g2025, on='team', how='left')
    curr = curr.dropna(subset=FEATURES[pos])
    curr['outcome_ppg'] = np.nan
    curr['is_current']  = True

    print(f'{pos_upper}: {len(hist)} historical, {len(curr)} entering-2026')
    return hist.reset_index(drop=True), curr.reset_index(drop=True)

historical, current = {}, {}
for pos in ['rb', 'wr', 'te', 'qb']:
    historical[pos], current[pos] = build_entering_profile(pos, pos_dfs[pos], grades)

# ── KNN comps ────────────────────────────────────────────────────
all_comps  = {}
all_scaled = {}

for pos in ['rb', 'wr', 'te', 'qb']:
    hist = historical[pos]
    curr = current[pos]
    feat_cols  = FEATURES[pos]
    radar_cols = RADAR_FEATURES[pos]

    scaler      = StandardScaler()
    hist_scaled = scaler.fit_transform(hist[feat_cols])
    curr_scaled = scaler.transform(curr[feat_cols])

    nn = NearestNeighbors(n_neighbors=K_COMPS, metric='euclidean')
    nn.fit(hist_scaled)
    distances, indices = nn.kneighbors(curr_scaled)

    for i, row in curr.iterrows():
        player = row['player_name']
        comps  = []
        for dist, idx in zip(distances[i], indices[i]):
            comp = hist.iloc[idx]
            comp_feat = {c: round(float(comp[c]), 2) for c in radar_cols if c in comp.index}
            curr_feat = {c: round(float(row[c]),  2) for c in radar_cols if c in row.index}
            comps.append({
                'player':        comp['player_name'],
                'season':        int(comp['season']),
                'team':          str(comp['team']),
                'outcome_ppg':   round(float(comp['outcome_ppg']), 2),
                'similarity':    round(1 / (1 + dist), 3),
                'comp_features': comp_feat,
                'curr_features': curr_feat,
            })
        all_comps[player] = comps

    all_scaled[pos] = {
        'hist_df':     hist,
        'curr_df':     curr,
        'hist_scaled': hist_scaled,
        'curr_scaled': curr_scaled,
    }
    print(f'{pos.upper()}: comps built for {len(curr)} players')

# ── UMAP ─────────────────────────────────────────────────────────
print('\nFitting UMAP (this may take a minute)...')
umap_records = []

for pos, data in all_scaled.items():
    hist_df     = data['hist_df']
    curr_df     = data['curr_df']
    hist_scaled = data['hist_scaled']
    curr_scaled = data['curr_scaled']

    combined = np.vstack([hist_scaled, curr_scaled])
    reducer  = umap.UMAP(n_components=2, random_state=42, n_neighbors=20, min_dist=0.03, spread=0.8)
    coords   = reducer.fit_transform(combined)
    n_hist   = len(hist_df)

    for i, (x, y) in enumerate(coords[:n_hist]):
        r = hist_df.iloc[i]
        umap_records.append({
            'player_name': r['player_name'], 'season': int(r['season']),
            'team': str(r['team']), 'position': pos.upper(),
            'age': float(r['age']), 'ppg': round(float(r['outcome_ppg']), 2),
            'ppg_lag1': round(float(r['ppg_lag1']), 2),
            'is_current': False,
            'x': round(float(x), 4), 'y': round(float(y), 4),
        })

    for i, (x, y) in enumerate(coords[n_hist:]):
        r = curr_df.iloc[i]
        umap_records.append({
            'player_name': r['player_name'], 'season': 2026,
            'team': str(r['team']), 'position': pos.upper(),
            'age': float(r['age']), 'ppg': round(float(r['ppg_lag1']), 2),
            'ppg_lag1': round(float(r['ppg_lag1']), 2),
            'is_current': True,
            'x': round(float(x), 4), 'y': round(float(y), 4),
        })

    print(f'{pos.upper()} UMAP done — {n_hist} hist + {len(curr_df)} current')

umap_df = pd.DataFrame(umap_records)
print(f'\nTotal UMAP points: {len(umap_df)} ({umap_df["is_current"].sum()} entering-2026)')

# ── Save ─────────────────────────────────────────────────────────
with open(OUT / 'similarity_comps.pkl', 'wb') as f:
    pickle.dump(all_comps, f)
umap_df.to_pickle(OUT / 'umap_coords.pkl')
print('\nSaved similarity_comps.pkl and umap_coords.pkl')

# ── Sanity check ─────────────────────────────────────────────────
for name in ['Wandale Robinson', 'Puka Nacua', 'Jahmyr Gibbs', 'Josh Allen']:
    if name in all_comps:
        print(f'\n{name} (entering 2026):')
        for c in all_comps[name]:
            print(f'  {c["player"]} entering {c["season"]} ({c["team"]}) -> {c["outcome_ppg"]} PPG | sim={c["similarity"]}')
