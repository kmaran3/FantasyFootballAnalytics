#!/usr/bin/env python3
"""Patch script for MLModel.ipynb — rewrites cells 0, 1, 2."""
import json, copy

NB_PATH = "/Users/kmaran3/Dropbox/Darkhorse/Models/MLModel.ipynb"

with open(NB_PATH) as f:
    nb = json.load(f)

# ── CELL 0 : QB ────────────────────────────────────────────────────────────────
CELL0 = r"""#QB ML MODEL - IMPROVED
import pandas as pd
import numpy as np
import warnings
import nfl_data_py as nfl
import xgboost as xgb
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_absolute_error
from scipy.stats import pearsonr
import joblib

pd.options.mode.chained_assignment = None
warnings.filterwarnings('ignore')

scaler = MinMaxScaler()
PEAK_AGE_QB = 30

dfFantasy = pd.read_pickle("PickleFiles/final_qb_data.pkl")
dfFantasy.replace([np.inf, -np.inf], np.nan, inplace=True)
for column in dfFantasy.select_dtypes(include=[np.number]).columns:
    dfFantasy[column].fillna(dfFantasy[column].mean(), inplace=True)

# ---- Add advanced EPA/efficiency features from nfl_data_py ----
print("Fetching QB advanced features (passing_epa, pacr, dakota) for 2015-2023...")
seasonal_all = nfl.import_seasonal_data(list(range(2015, 2024)))
adv = seasonal_all[['player_id', 'season', 'passing_epa', 'pacr', 'dakota']].copy()
adv['season'] = adv['season'].astype(int)
dfFantasy['season'] = dfFantasy['season'].astype(int)
dfFantasy = dfFantasy.merge(adv, on=['player_id', 'season'], how='left')
print(f"  passing_epa coverage: {dfFantasy['passing_epa'].notna().mean()*100:.0f}%")

def correctData(df, pprTF):
    # Counting stats to convert to per-game
    count_cols = ['completions', 'attempts', 'passing_yards', 'passing_tds', 'interceptions',
                  'sacks', 'sack_fumbles_lost', 'passing_air_yards', 'passing_yards_after_catch',
                  'passing_first_downs', 'passing_2pt_conversions',
                  'carries', 'rushing_yards', 'rushing_tds', 'rushing_fumbles_lost',
                  'rushing_first_downs', 'rushing_2pt_conversions', 'fantasy_points', 'age']
    df.loc[:, 'PPG'] = df['fantasy_points'] / df['GP']
    # ppg_prev = last year's PPG — computed BEFORE shifting (will become prev-year feature after shift)
    df = df.sort_values(['player_display_name', 'season']).reset_index(drop=True)
    df['ppg_prev'] = df['PPG']
    for col in count_cols:
        df.loc[:, col] = df[col] / df['GP']
    # passing_epa is a season total -> divide by GP; pacr/dakota are ratios -> leave as-is
    df.loc[:, 'passing_epa'] = df['passing_epa'] / df['GP'].replace(0, np.nan)
    # pacr and dakota: already normalised, do NOT divide
    df = df[df.GP > 7]
    df = df[df.fantasy_points >= 0]
    df = df[df.PPG > 5]
    df = df.sort_values(['player_display_name', 'season']).reset_index(drop=True)
    df['ppg_last_year'] = df.groupby('player_display_name')['PPG'].shift(1).fillna(df['PPG'])
    df['delta_ppg'] = df['PPG'] - df['ppg_last_year']
    return df

def removeUnwanted(dfPos, pos):
    drop_cols = ['season', 'GP', 'season_type', 'fantasy_points',
                 'player_display_name', 'player_id', 'team', 'position']
    return dfPos.drop(columns=drop_cols, errors='ignore')

def makeCorrectShift(df):
    # All stats + advanced features + ppg_prev shifted 1 year back so they become "last year's" features
    shifters = ['season', 'GP', 'season_type', 'age', 'fantasy_points',
                'completions', 'attempts', 'passing_yards', 'passing_tds', 'interceptions',
                'sacks', 'sack_fumbles_lost', 'passing_air_yards', 'passing_yards_after_catch',
                'passing_first_downs', 'passing_2pt_conversions',
                'carries', 'rushing_yards', 'rushing_tds', 'rushing_fumbles_lost',
                'rushing_first_downs', 'rushing_2pt_conversions',
                'passing_epa', 'pacr', 'dakota',
                'ppg_prev', 'ppg_last_year', 'delta_ppg']
    # Only shift columns that actually exist in df
    shifters = [c for c in shifters if c in df.columns]
    df[shifters] = df.groupby('player_display_name')[shifters].shift(1)
    return df.dropna()

XGB_PARAMS = {
    'n_estimators': 300, 'max_depth': 3, 'min_child_weight': 5,
    'reg_alpha': 0.3, 'reg_lambda': 2.0, 'subsample': 0.75,
    'colsample_bytree': 0.7, 'learning_rate': 0.05,
    'random_state': 42, 'verbosity': 0
}

TRAIN_START_YEARS = [2019, 2018, 2017, 2016, 2015]

def getScaleBack(df):
    return [df['PPG'].min(), df['PPG'].max()]

def machineLearning(df, arr):
    predictors = [c for c in df.columns
                  if c != 'PPG' and 'Unnamed' not in c and c != 'YearsBack']
    x_df = df[predictors]
    y = df['PPG'].values
    split = int(len(y) * 0.8)
    cv = xgb.XGBRegressor(**XGB_PARAMS)
    cv.fit(x_df.iloc[:split], y[:split])
    p = cv.predict(x_df.iloc[split:])
    p_ppg = p * (arr[1] - arr[0]) + arr[0]
    a_ppg = y[split:] * (arr[1] - arr[0]) + arr[0]
    mae = mean_absolute_error(a_ppg, p_ppg)
    corr = 0.0
    if len(a_ppg) > 2:
        corr, _ = pearsonr(p_ppg, a_ppg)
        print(f"  Holdout MAE: {mae:.2f} PPG | r={corr:.3f} | n={len(a_ppg)}")
    final = xgb.XGBRegressor(**XGB_PARAMS)
    final.fit(x_df, y)
    return (mae, corr, final)

print("Training QB models (3 PPR formats) with trial-and-error year ranges...")
for ppr in [0, 1, 2]:
    lbl = {0: 'Standard', 1: 'HalfPPR', 2: 'FullPPR'}[ppr]
    print(f"\nQB {lbl}:")

    dfFC_base = dfFantasy.copy()
    dfFC_base = correctData(dfFC_base, ppr)
    dfFC_base = makeCorrectShift(dfFC_base)

    best_corr = -999
    best_model = None
    best_start = None

    for start_year in TRAIN_START_YEARS:
        dfFC = dfFC_base[dfFC_base['season'] >= start_year].copy()
        dfFC = dfFC.loc[dfFC['season'] != 2012]
        dfFC['age_from_peak'] = dfFC['age'] - PEAK_AGE_QB
        dfFC['age_squared'] = dfFC['age'] ** 2
        dfFC['games_missed'] = (17 - dfFC['GP']).clip(lower=0)
        dfFC = removeUnwanted(dfFC, 'QB')
        dfFC = dfFC.reset_index(drop=True)
        if len(dfFC) < 20:
            print(f"  start_year={start_year}: too few rows ({len(dfFC)}), skipping")
            continue
        scaleQB = getScaleBack(dfFC)
        dfFC_scaled = dfFC.copy()
        dfFC_scaled[dfFC_scaled.columns] = scaler.fit_transform(dfFC_scaled[dfFC_scaled.columns])
        print(f"  start_year={start_year} ({len(dfFC)} rows, {len(dfFC.columns)-1} features):", end=" ")
        mae, corr, model = machineLearning(dfFC_scaled, scaleQB)
        if corr > best_corr:
            best_corr = corr
            best_model = model
            best_start = start_year

    print(f"  Best start_year={best_start} with r={best_corr:.3f}")
    path = {0: "qb models/qbModelNonPPR.joblib",
            1: "qb models/qbModelHalfPPR.joblib",
            2: "qb models/qbModelPPR.joblib"}[ppr]
    joblib.dump(best_model, path)
    print(f"  Saved {path}")
"""

# ── CELL 1 : RB ────────────────────────────────────────────────────────────────
CELL1 = r"""#RB ML MODEL - IMPROVED
import pandas as pd
import numpy as np
import warnings
import nfl_data_py as nfl
import xgboost as xgb
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_absolute_error
from scipy.stats import pearsonr
import joblib

pd.options.mode.chained_assignment = None
warnings.filterwarnings('ignore')

scaler = MinMaxScaler()
PEAK_AGE_RB = 25

dfFantasy = pd.read_pickle("PickleFiles/final_rb_data.pkl")
dfFantasy.replace([np.inf, -np.inf], np.nan, inplace=True)
for column in dfFantasy.select_dtypes(include=[np.number]).columns:
    dfFantasy[column].fillna(dfFantasy[column].mean(), inplace=True)

# ---- Add opportunity + EPA features from nfl_data_py ----
print("Fetching RB opportunity/EPA features for 2015-2023...")
seasonal_all = nfl.import_seasonal_data(list(range(2015, 2024)))
opp = seasonal_all[['player_id', 'season', 'target_share', 'ry_sh',
                     'rushing_epa', 'receiving_epa', 'rtd_sh', 'rfd_sh']].copy()
opp['season'] = opp['season'].astype(int)
dfFantasy['season'] = dfFantasy['season'].astype(int)
dfFantasy = dfFantasy.merge(opp, on=['player_id', 'season'], how='left')
print(f"  target_share coverage: {dfFantasy['target_share'].notna().mean()*100:.0f}%")
print(f"  rushing_epa coverage:  {dfFantasy['rushing_epa'].notna().mean()*100:.0f}%")

def correctData(df, pprTF):
    count_cols = ['carries', 'rushing_yards', 'rushing_tds', 'rushing_fumbles_lost',
                  'rushing_first_downs', 'rushing_2pt_conversions', 'receptions', 'targets',
                  'receiving_yards', 'receiving_tds', 'receiving_fumbles_lost',
                  'receiving_air_yards', 'receiving_yards_after_catch', 'receiving_first_downs',
                  'receiving_2pt_conversions', 'special_teams_tds', 'fantasy_points', 'rrtd', 'age']
    if pprTF == 0:
        df.loc[:, "fantasy_points"] = df["fantasy_points"] - df["receptions"]
    elif pprTF == 1:
        df.loc[:, "fantasy_points"] = df["fantasy_points"] - (df["receptions"] / 2)
    df.loc[:, 'PPG'] = df['fantasy_points'] / df['GP']
    # ppg_prev before shift
    df = df.sort_values(['player_display_name', 'season']).reset_index(drop=True)
    df['ppg_prev'] = df['PPG']
    for col in count_cols:
        df.loc[:, col] = df[col] / df['GP']
    # EPA totals -> per game; shares -> leave as-is
    gp_safe = df['GP'].replace(0, np.nan)
    df.loc[:, 'rushing_epa'] = df['rushing_epa'] / gp_safe
    df.loc[:, 'receiving_epa'] = df['receiving_epa'] / gp_safe
    # rtd_sh, rfd_sh are share columns — do NOT divide
    df = df[df.GP > 7]
    df = df[df.fantasy_points >= 0]
    df = df[df.PPG > 2]
    df = df.sort_values(['player_display_name', 'season']).reset_index(drop=True)
    df['ppg_last_year'] = df.groupby('player_display_name')['PPG'].shift(1).fillna(df['PPG'])
    df['delta_ppg'] = df['PPG'] - df['ppg_last_year']
    return df

def removeUnwanted(dfPos, pos):
    drop_cols = ['season', 'GP', 'season_type', 'fantasy_points',
                 'player_display_name', 'player_id', 'team', 'position']
    return dfPos.drop(columns=drop_cols, errors='ignore')

def makeCorrectShift(df):
    shifters = ['player_id', 'season', 'player_display_name', 'team', 'GP', 'position',
                'age', 'season_type', 'carries', 'rushing_yards', 'rushing_tds',
                'rushing_fumbles_lost', 'rushing_first_downs', 'rushing_2pt_conversions',
                'receptions', 'targets', 'receiving_yards', 'receiving_tds',
                'receiving_fumbles_lost', 'receiving_air_yards', 'receiving_yards_after_catch',
                'receiving_first_downs', 'receiving_2pt_conversions', 'special_teams_tds',
                'fantasy_points', 'rrtd',
                'target_share', 'ry_sh', 'rushing_epa', 'receiving_epa', 'rtd_sh', 'rfd_sh',
                'ppg_prev', 'ppg_last_year', 'delta_ppg']
    shifters = [c for c in shifters if c in df.columns]
    df[shifters] = df.groupby('player_display_name')[shifters].shift(1)
    return df.dropna()

XGB_PARAMS = {
    'n_estimators': 300, 'max_depth': 3, 'min_child_weight': 5,
    'reg_alpha': 0.3, 'reg_lambda': 2.0, 'subsample': 0.75,
    'colsample_bytree': 0.7, 'learning_rate': 0.05,
    'random_state': 42, 'verbosity': 0
}

TRAIN_START_YEARS = [2019, 2018, 2017, 2016, 2015]

def getScaleBack(df):
    return [df['PPG'].min(), df['PPG'].max()]

def machineLearning(df, arr):
    predictors = [c for c in df.columns
                  if c != 'PPG' and 'Unnamed' not in c and c != 'YearsBack']
    x_df = df[predictors]
    y = df['PPG'].values
    split = int(len(y) * 0.8)
    cv = xgb.XGBRegressor(**XGB_PARAMS)
    cv.fit(x_df.iloc[:split], y[:split])
    p = cv.predict(x_df.iloc[split:])
    p_ppg = p * (arr[1] - arr[0]) + arr[0]
    a_ppg = y[split:] * (arr[1] - arr[0]) + arr[0]
    mae = mean_absolute_error(a_ppg, p_ppg)
    corr = 0.0
    if len(a_ppg) > 2:
        corr, _ = pearsonr(p_ppg, a_ppg)
        print(f"  Holdout MAE: {mae:.2f} PPG | r={corr:.3f} | n={len(a_ppg)}")
    final = xgb.XGBRegressor(**XGB_PARAMS)
    final.fit(x_df, y)
    return (mae, corr, final)

print("Training RB models (3 PPR formats) with trial-and-error year ranges...")
for ppr in [0, 1, 2]:
    lbl = {0: 'Standard', 1: 'HalfPPR', 2: 'FullPPR'}[ppr]
    print(f"\nRB {lbl}:")

    dfFC_base = dfFantasy.copy()
    dfFC_base = correctData(dfFC_base, ppr)
    dfFC_base = makeCorrectShift(dfFC_base)

    best_corr = -999
    best_model = None
    best_start = None

    for start_year in TRAIN_START_YEARS:
        dfFC = dfFC_base[dfFC_base['season'] >= start_year].copy()
        dfFC = dfFC.loc[dfFC['season'] != 2012]
        dfFC['age_from_peak'] = dfFC['age'] - PEAK_AGE_RB
        dfFC['age_squared'] = dfFC['age'] ** 2
        dfFC['games_missed'] = (17 - dfFC['GP']).clip(lower=0)
        dfFC = removeUnwanted(dfFC, 'RB')
        dfFC = dfFC.reset_index(drop=True)
        if len(dfFC) < 20:
            print(f"  start_year={start_year}: too few rows ({len(dfFC)}), skipping")
            continue
        scaleRB = getScaleBack(dfFC)
        dfFC_scaled = dfFC.copy()
        dfFC_scaled[dfFC_scaled.columns] = scaler.fit_transform(dfFC_scaled[dfFC_scaled.columns])
        print(f"  start_year={start_year} ({len(dfFC)} rows, {len(dfFC.columns)-1} features):", end=" ")
        mae, corr, model = machineLearning(dfFC_scaled, scaleRB)
        if corr > best_corr:
            best_corr = corr
            best_model = model
            best_start = start_year

    print(f"  Best start_year={best_start} with r={best_corr:.3f}")
    path = {0: "rb models/rbModelNonPPR.joblib",
            1: "rb models/rbModelHalfPPR.joblib",
            2: "rb models/rbModelPPR.joblib"}[ppr]
    joblib.dump(best_model, path)
    print(f"  Saved {path}")
"""

# ── CELL 2 : WRTE (split into WR + TE models) ──────────────────────────────────
CELL2 = r"""#WR + TE ML MODELS - IMPROVED (separate models per position)
import pandas as pd
import numpy as np
import warnings
import nfl_data_py as nfl
import xgboost as xgb
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_absolute_error
from scipy.stats import pearsonr
import joblib

pd.options.mode.chained_assignment = None
warnings.filterwarnings('ignore')

scaler = MinMaxScaler()
PEAK_AGE_WRTE = 26

dfFantasy = pd.read_pickle("PickleFiles/final_wrte_data.pkl")
dfFantasy.replace([np.inf, -np.inf], np.nan, inplace=True)
for column in dfFantasy.select_dtypes(include=[np.number]).columns:
    dfFantasy[column].fillna(dfFantasy[column].mean(), inplace=True)

# ---- Add opportunity + EPA features from nfl_data_py ----
print("Fetching WR/TE opportunity/EPA features for 2015-2023...")
seasonal_all = nfl.import_seasonal_data(list(range(2015, 2024)))
opp = seasonal_all[['player_id', 'season', 'target_share', 'air_yards_share',
                     'wopr_x', 'racr', 'receiving_epa', 'yac_sh', 'tgt_sh']].copy()
opp['season'] = opp['season'].astype(int)
dfFantasy['season'] = dfFantasy['season'].astype(int)
dfFantasy = dfFantasy.merge(opp, on=['player_id', 'season'], how='left')
print(f"  target_share coverage: {dfFantasy['target_share'].notna().mean()*100:.0f}%")
print(f"  receiving_epa coverage: {dfFantasy['receiving_epa'].notna().mean()*100:.0f}%")

def correctData(df, pprTF):
    count_cols = ['carries', 'rushing_yards', 'rushing_tds', 'rushing_fumbles_lost',
                  'rushing_first_downs', 'rushing_2pt_conversions', 'receptions', 'targets',
                  'receiving_yards', 'receiving_tds', 'receiving_fumbles_lost',
                  'receiving_air_yards', 'receiving_yards_after_catch', 'receiving_first_downs',
                  'receiving_2pt_conversions', 'special_teams_tds', 'fantasy_points', 'rrtd', 'age']
    if pprTF == 0:
        df.loc[:, "fantasy_points"] = df["fantasy_points"] - df["receptions"]
    elif pprTF == 1:
        df.loc[:, "fantasy_points"] = df["fantasy_points"] - (df["receptions"] / 2)
    df.loc[:, 'PPG'] = df['fantasy_points'] / df['GP']
    df = df.sort_values(['player_display_name', 'season']).reset_index(drop=True)
    df['ppg_prev'] = df['PPG']
    for col in count_cols:
        df.loc[:, col] = df[col] / df['GP']
    # receiving_epa is season total -> per game; wopr_x, racr, yac_sh, tgt_sh are ratios
    gp_safe = df['GP'].replace(0, np.nan)
    df.loc[:, 'receiving_epa'] = df['receiving_epa'] / gp_safe
    # wopr_x, racr, yac_sh, tgt_sh: do NOT divide
    df = df[df.GP > 7]
    df = df[df.fantasy_points >= 0]
    df = df[df.PPG > 2]
    df = df.sort_values(['player_display_name', 'season']).reset_index(drop=True)
    df['ppg_last_year'] = df.groupby('player_display_name')['PPG'].shift(1).fillna(df['PPG'])
    df['delta_ppg'] = df['PPG'] - df['ppg_last_year']
    return df

def removeUnwanted(dfPos, pos):
    drop_cols = ['season', 'GP', 'season_type', 'fantasy_points',
                 'player_display_name', 'player_id', 'team', 'position']
    return dfPos.drop(columns=drop_cols, errors='ignore')

def makeCorrectShift(df):
    shifters = ['player_id', 'season', 'player_display_name', 'team', 'GP', 'position',
                'age', 'season_type', 'carries', 'rushing_yards', 'rushing_tds',
                'rushing_fumbles_lost', 'rushing_first_downs', 'rushing_2pt_conversions',
                'receptions', 'targets', 'receiving_yards', 'receiving_tds',
                'receiving_fumbles_lost', 'receiving_air_yards', 'receiving_yards_after_catch',
                'receiving_first_downs', 'receiving_2pt_conversions', 'special_teams_tds',
                'fantasy_points', 'rrtd',
                'target_share', 'air_yards_share', 'wopr_x', 'racr',
                'receiving_epa', 'yac_sh', 'tgt_sh',
                'ppg_prev', 'ppg_last_year', 'delta_ppg']
    shifters = [c for c in shifters if c in df.columns]
    df[shifters] = df.groupby('player_display_name')[shifters].shift(1)
    return df.dropna()

XGB_PARAMS = {
    'n_estimators': 300, 'max_depth': 3, 'min_child_weight': 5,
    'reg_alpha': 0.3, 'reg_lambda': 2.0, 'subsample': 0.75,
    'colsample_bytree': 0.7, 'learning_rate': 0.05,
    'random_state': 42, 'verbosity': 0
}

TRAIN_START_YEARS = [2019, 2018, 2017, 2016, 2015]

def getScaleBack(df):
    return [df['PPG'].min(), df['PPG'].max()]

def machineLearning(df, arr):
    predictors = [c for c in df.columns
                  if c != 'PPG' and 'Unnamed' not in c and c != 'YearsBack']
    x_df = df[predictors]
    y = df['PPG'].values
    split = int(len(y) * 0.8)
    cv = xgb.XGBRegressor(**XGB_PARAMS)
    cv.fit(x_df.iloc[:split], y[:split])
    p = cv.predict(x_df.iloc[split:])
    p_ppg = p * (arr[1] - arr[0]) + arr[0]
    a_ppg = y[split:] * (arr[1] - arr[0]) + arr[0]
    mae = mean_absolute_error(a_ppg, p_ppg)
    corr = 0.0
    if len(a_ppg) > 2:
        corr, _ = pearsonr(p_ppg, a_ppg)
        print(f"  Holdout MAE: {mae:.2f} PPG | r={corr:.3f} | n={len(a_ppg)}")
    final = xgb.XGBRegressor(**XGB_PARAMS)
    final.fit(x_df, y)
    return (mae, corr, final)

print("Training WR and TE models separately (3 PPR formats each) with trial-and-error year ranges...")

# Prepare base data (correctData + shift) once, then split by position
for pos_group in ['WR', 'TE']:
    print(f"\n{'='*50}")
    print(f"Position group: {pos_group}")
    for ppr in [0, 1, 2]:
        lbl = {0: 'Standard', 1: 'HalfPPR', 2: 'FullPPR'}[ppr]
        print(f"\n  {pos_group} {lbl}:")

        dfFC_base = dfFantasy[dfFantasy['position'] == pos_group].copy()
        dfFC_base = correctData(dfFC_base, ppr)
        dfFC_base = makeCorrectShift(dfFC_base)

        best_corr = -999
        best_model = None
        best_start = None

        for start_year in TRAIN_START_YEARS:
            dfFC = dfFC_base[dfFC_base['season'] >= start_year].copy()
            dfFC = dfFC.loc[dfFC['season'] != 2012]
            dfFC['age_from_peak'] = dfFC['age'] - PEAK_AGE_WRTE
            dfFC['age_squared'] = dfFC['age'] ** 2
            dfFC['games_missed'] = (17 - dfFC['GP']).clip(lower=0)
            dfFC = removeUnwanted(dfFC, pos_group)
            dfFC = dfFC.reset_index(drop=True)
            if len(dfFC) < 20:
                print(f"    start_year={start_year}: too few rows ({len(dfFC)}), skipping")
                continue
            scale_arr = getScaleBack(dfFC)
            dfFC_scaled = dfFC.copy()
            dfFC_scaled[dfFC_scaled.columns] = scaler.fit_transform(dfFC_scaled[dfFC_scaled.columns])
            print(f"    start_year={start_year} ({len(dfFC)} rows, {len(dfFC.columns)-1} features):", end=" ")
            mae, corr, model = machineLearning(dfFC_scaled, scale_arr)
            if corr > best_corr:
                best_corr = corr
                best_model = model
                best_start = start_year

        print(f"    Best start_year={best_start} with r={best_corr:.3f}")
        prefix = 'wr' if pos_group == 'WR' else 'te'
        path = {0: f"wrte models/{prefix}ModelNonPPR.joblib",
                1: f"wrte models/{prefix}ModelHalfPPR.joblib",
                2: f"wrte models/{prefix}ModelPPR.joblib"}[ppr]
        joblib.dump(best_model, path)
        print(f"    Saved {path}")
"""

# ── Apply patches ──────────────────────────────────────────────────────────────
nb['cells'][0]['source'] = [CELL0]
nb['cells'][1]['source'] = [CELL1]
nb['cells'][2]['source'] = [CELL2]

with open(NB_PATH, 'w') as f:
    json.dump(nb, f, indent=1)

print("patch_mlmodel.py: MLModel.ipynb cells 0, 1, 2 successfully rewritten.")
