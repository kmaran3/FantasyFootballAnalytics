#!/usr/bin/env python3
"""Patch script for PredictionCode.ipynb — rewrites cells 1, 2, 3, 4."""
import json

NB_PATH = "/Users/kmaran3/Dropbox/Darkhorse/Models/PredictionCode.ipynb"

with open(NB_PATH) as f:
    nb = json.load(f)

# ── CELL 1 : QB dfMaker ────────────────────────────────────────────────────────
CELL1 = r"""import nflreadpy
import pandas as pd
import numpy as np
from unidecode import unidecode

CURRENT_YEAR = 2025
PEAK_AGE_QB = 30

# Load advanced features ONCE outside dfMaker — covers both YearsBack=1 (2024) and YearsBack=2 (2023)
print("Fetching QB advanced features (passing_epa, pacr) for 2023-2024...")
qb_adv_raw = nflreadpy.load_player_stats([2023, 2024], summary_level='reg').to_pandas()
qb_adv = qb_adv_raw[['player_id', 'season', 'passing_epa', 'pacr']].copy()
qb_adv['season'] = qb_adv['season'].astype(int)

QB_COLS = ["team", "position", "penalty", "GP", "player_display_name", "age",
           'completions', 'attempts', 'passing_yards', 'passing_tds', 'interceptions',
           'sacks', 'sack_fumbles_lost', 'passing_air_yards', 'passing_yards_after_catch',
           'passing_first_downs', 'passing_2pt_conversions',
           'carries', 'rushing_yards', 'rushing_tds',
           'rushing_fumbles_lost', 'rushing_first_downs', 'rushing_2pt_conversions',
           'passing_epa', 'pacr',
           "PPG", 'ppg_prev', 'ppg_last_year', 'delta_ppg',
           'age_from_peak', 'age_squared', 'games_missed']

def dfMaker():
    for ppr in range(3):
        # Read files fresh each ppr iteration
        oldQBStats = pd.read_pickle("PickleFiles/final_qb_data.pkl")
        oldQBStats['YearsBack'] = CURRENT_YEAR - oldQBStats['season'].astype(int)
        oldQBStats['season'] = oldQBStats['season'].astype(int)
        # Merge advanced features by player_id + season
        oldQBStats = oldQBStats.merge(qb_adv, on=['player_id', 'season'], how='left')

        currTeamsRoster = pd.read_pickle("PickleFiles/currYearRoster.pkl")
        currAVs = pd.read_pickle("PickleFiles/currAVs.pkl")

        completeDFQB = pd.DataFrame(columns=QB_COLS)
        rookieList = []

        for index in range(len(currTeamsRoster)):
            year = currTeamsRoster.loc[index, 'Yrs']
            bday = currTeamsRoster.loc[index, 'BirthDate']
            pos  = currTeamsRoster.loc[index, 'Pos']
            age  = currTeamsRoster.loc[index, 'Age']
            name = currTeamsRoster.loc[index, 'Player']
            team = currTeamsRoster.loc[index, 'Team']

            if pos != "QB":
                continue

            # Skip rookies
            if year == "Rook":
                rookieList.append({"Name": name, "Year": year, "Bday": bday, "Age": age, "Team": team})
                continue

            # Single-season lookup: prefer YearsBack=1 if GP>=8, else fall back to YearsBack=2
            r1 = oldQBStats[(oldQBStats['player_display_name'] == name) & (oldQBStats['YearsBack'] == 1)].copy()
            r2 = oldQBStats[(oldQBStats['player_display_name'] == name) & (oldQBStats['YearsBack'] == 2)].copy()

            if not r1.empty and r1.iloc[0]['GP'] >= 8:
                row = r1.iloc[0]
            elif not r2.empty:
                row = r2.iloc[0]
            else:
                continue  # no usable data

            gp = float(row['GP'])
            if gp < 6:
                continue

            # Build per-game counting stats
            count_cols = ['completions', 'attempts', 'passing_yards', 'passing_tds', 'interceptions',
                          'sacks', 'sack_fumbles_lost', 'passing_air_yards', 'passing_yards_after_catch',
                          'passing_first_downs', 'passing_2pt_conversions',
                          'carries', 'rushing_yards', 'rushing_tds', 'rushing_fumbles_lost',
                          'rushing_first_downs', 'rushing_2pt_conversions']

            per_game = {col: float(row.get(col, 0)) / gp for col in count_cols}

            # Advanced features
            passing_epa = float(row['passing_epa']) / gp if pd.notna(row.get('passing_epa')) else 0.0
            pacr         = float(row['pacr'])           if pd.notna(row.get('pacr'))         else 0.0

            # PPG from per-game stats
            PPG = (per_game['rushing_yards'] * 0.1 +
                   per_game['passing_yards'] * 0.04 +
                   per_game['rushing_tds'] * 6 +
                   per_game['passing_tds'] * 4 +
                   per_game['rushing_fumbles_lost'] * -2 +
                   per_game['sack_fumbles_lost'] * -2 +
                   per_game['interceptions'] * -2)

            # ppg_prev = YearsBack=1 PPG (always from r1, regardless of which row was chosen for stats)
            if not r1.empty:
                r1row = r1.iloc[0]
                gp1 = max(float(r1row['GP']), 1)
                fp1 = float(r1row.get('fantasy_points', 0))
                ppg_yb1 = fp1 / gp1
            else:
                ppg_yb1 = PPG

            if not r2.empty:
                r2row = r2.iloc[0]
                gp2 = max(float(r2row['GP']), 1)
                fp2 = float(r2row.get('fantasy_points', 0))
                ppg_yb2 = fp2 / gp2
            else:
                ppg_yb2 = ppg_yb1

            ppg_prev     = ppg_yb1
            ppg_last_year = ppg_yb2
            delta_ppg    = ppg_yb1 - ppg_yb2
            age_from_peak = float(age) - PEAK_AGE_QB
            age_squared  = float(age) ** 2
            games_missed = max(0, 17 - (int(r1.iloc[0]['GP']) if not r1.empty else 17))
            penalty      = gp  # penalty placeholder (same as original GP-based value)

            row_data = {
                "team": team, "position": pos, "penalty": penalty, "GP": gp,
                "player_display_name": name, "age": float(age),
                **per_game,
                "passing_epa": passing_epa, "pacr": pacr,
                "PPG": PPG,
                "ppg_prev": ppg_prev, "ppg_last_year": ppg_last_year, "delta_ppg": delta_ppg,
                "age_from_peak": age_from_peak, "age_squared": age_squared,
                "games_missed": games_missed
            }

            individualDFQB = pd.DataFrame([row_data], columns=QB_COLS)
            completeDFQB = pd.concat([completeDFQB, individualDFQB], ignore_index=True)

        # Save
        completeDFQB = pd.merge(completeDFQB, currAVs, on='team', how='left')
        completeDFQB = completeDFQB.fillna(0)
        completeDFQB = completeDFQB.sort_values(by='PPG')
        pkl_map = {0: "PickleFiles/QBDFForModelNonPPR.pkl",
                   1: "PickleFiles/QBDFForModelHalfPPR.pkl",
                   2: "PickleFiles/QBDFForModelPPR.pkl"}
        completeDFQB.to_pickle(pkl_map[ppr])
        print(f"  QB ppr={ppr}: {len(completeDFQB)} players saved -> {pkl_map[ppr]}")

dfMaker()
"""

# ── CELL 2 : RB dfMaker ────────────────────────────────────────────────────────
CELL2 = r"""import nflreadpy
import pandas as pd
import numpy as np
from unidecode import unidecode

CURRENT_YEAR = 2025
PEAK_AGE_RB = 25

# Load opportunity + EPA features ONCE outside dfMaker
print("Fetching RB opportunity/EPA features for 2023-2024...")
rb_opp_raw = nflreadpy.load_player_stats([2023, 2024], summary_level='reg').to_pandas()
rb_opp = rb_opp_raw[['player_id', 'season',
                       'target_share',
                       'rushing_epa', 'receiving_epa']].copy()
rb_opp['season'] = rb_opp['season'].astype(int)

RB_COLS = ["team", "position", "penalty", "GP", "player_display_name", "age",
           'carries', 'rushing_yards', 'rushing_tds', 'rushing_fumbles_lost',
           'rushing_first_downs', 'rushing_2pt_conversions',
           'receptions', 'targets', 'receiving_yards', 'receiving_tds',
           'receiving_fumbles_lost', 'receiving_air_yards', 'receiving_yards_after_catch',
           'receiving_first_downs', 'receiving_2pt_conversions', 'special_teams_tds', 'rrtd',
           "PPG",
           'target_share', 'rushing_epa', 'receiving_epa',
           'ppg_prev', 'ppg_last_year', 'delta_ppg',
           'age_from_peak', 'age_squared', 'games_missed']

def dfMaker():
    for ppr in range(3):
        oldRBStats = pd.read_pickle("PickleFiles/final_rb_data.pkl")
        oldRBStats['YearsBack'] = CURRENT_YEAR - oldRBStats['season'].astype(int)
        oldRBStats['season'] = oldRBStats['season'].astype(int)
        oldRBStats = oldRBStats.merge(rb_opp, on=['player_id', 'season'], how='left')

        currTeamsRoster = pd.read_pickle("PickleFiles/currYearRoster.pkl")
        currAVs = pd.read_pickle("PickleFiles/currAVs.pkl")

        completeDFRB = pd.DataFrame(columns=RB_COLS)
        rookieList = []

        for index in range(len(currTeamsRoster)):
            year = currTeamsRoster.loc[index, 'Yrs']
            bday = currTeamsRoster.loc[index, 'BirthDate']
            pos  = currTeamsRoster.loc[index, 'Pos']
            age  = currTeamsRoster.loc[index, 'Age']
            name = currTeamsRoster.loc[index, 'Player']
            team = currTeamsRoster.loc[index, 'Team']

            if pos != "RB":
                continue

            if year == "Rook":
                rookieList.append({"Name": name, "Year": year, "Bday": bday, "Age": age, "Team": team})
                continue

            r1 = oldRBStats[(oldRBStats['player_display_name'] == name) & (oldRBStats['YearsBack'] == 1)].copy()
            r2 = oldRBStats[(oldRBStats['player_display_name'] == name) & (oldRBStats['YearsBack'] == 2)].copy()

            if not r1.empty and r1.iloc[0]['GP'] >= 8:
                row = r1.iloc[0]
            elif not r2.empty:
                row = r2.iloc[0]
            else:
                continue

            gp = float(row['GP'])
            if gp < 6:
                continue

            count_cols = ['carries', 'rushing_yards', 'rushing_tds', 'rushing_fumbles_lost',
                          'rushing_first_downs', 'rushing_2pt_conversions',
                          'receptions', 'targets', 'receiving_yards', 'receiving_tds',
                          'receiving_fumbles_lost', 'receiving_air_yards', 'receiving_yards_after_catch',
                          'receiving_first_downs', 'receiving_2pt_conversions', 'special_teams_tds', 'rrtd']
            per_game = {col: float(row.get(col, 0)) / gp for col in count_cols}

            # Opportunity: shares/ratios — no divide
            target_share  = float(row['target_share'])  if pd.notna(row.get('target_share'))  else 0.0
            # EPA totals -> per game
            rushing_epa   = float(row['rushing_epa'])   / gp if pd.notna(row.get('rushing_epa'))   else 0.0
            receiving_epa = float(row['receiving_epa']) / gp if pd.notna(row.get('receiving_epa')) else 0.0

            # PPG (base, without PPR adjustment yet — add receptions below)
            base_ppg = (per_game['rushing_yards'] * 0.1 +
                        per_game['rushing_tds'] * 6 +
                        per_game['rushing_fumbles_lost'] * -2 +
                        per_game['receiving_yards'] * 0.1 +
                        per_game['receiving_tds'] * 6 +
                        per_game['receiving_fumbles_lost'] * -2)
            rec_pg = per_game['receptions']
            if ppr == 2:
                PPG = base_ppg + rec_pg
            elif ppr == 1:
                PPG = base_ppg + rec_pg * 0.5
            else:
                PPG = base_ppg

            # ppg_prev / ppg_last_year — always from r1 / r2
            def rb_ppg_from_row(r, p):
                gp_ = max(float(r['GP']), 1)
                b = (float(r.get('rushing_yards', 0)) * 0.1 +
                     float(r.get('rushing_tds', 0)) * 6 +
                     float(r.get('rushing_fumbles_lost', 0)) * -2 +
                     float(r.get('receiving_yards', 0)) * 0.1 +
                     float(r.get('receiving_tds', 0)) * 6 +
                     float(r.get('receiving_fumbles_lost', 0)) * -2) / gp_
                rec_ = float(r.get('receptions', 0)) / gp_
                return b + (rec_ if p == 2 else rec_ * 0.5 if p == 1 else 0)

            ppg_yb1 = rb_ppg_from_row(r1.iloc[0], ppr) if not r1.empty else PPG
            ppg_yb2 = rb_ppg_from_row(r2.iloc[0], ppr) if not r2.empty else ppg_yb1

            ppg_prev      = ppg_yb1
            ppg_last_year = ppg_yb2
            delta_ppg     = ppg_yb1 - ppg_yb2
            age_from_peak = float(age) - PEAK_AGE_RB
            age_squared   = float(age) ** 2
            games_missed  = max(0, 17 - int(r1.iloc[0]['GP'])) if not r1.empty else 17
            penalty       = gp

            row_data = {
                "team": team, "position": pos, "penalty": penalty, "GP": gp,
                "player_display_name": name, "age": float(age),
                **per_game,
                "PPG": PPG,
                "target_share": target_share,
                "rushing_epa": rushing_epa, "receiving_epa": receiving_epa,
                "ppg_prev": ppg_prev, "ppg_last_year": ppg_last_year, "delta_ppg": delta_ppg,
                "age_from_peak": age_from_peak, "age_squared": age_squared,
                "games_missed": games_missed
            }

            individualDFRB = pd.DataFrame([row_data], columns=RB_COLS)
            completeDFRB = pd.concat([completeDFRB, individualDFRB], ignore_index=True)

        completeDFRB = pd.merge(completeDFRB, currAVs, on='team', how='left')
        completeDFRB = completeDFRB.fillna(0)
        completeDFRB = completeDFRB.sort_values(by='PPG')
        pkl_map = {0: "PickleFiles/RBDFForModelNonPPR.pkl",
                   1: "PickleFiles/RBDFForModelHalfPPR.pkl",
                   2: "PickleFiles/RBDFForModelPPR.pkl"}
        completeDFRB.to_pickle(pkl_map[ppr])
        print(f"  RB ppr={ppr}: {len(completeDFRB)} players saved -> {pkl_map[ppr]}")

dfMaker()
"""

# ── CELL 3 : WRTE dfMaker ──────────────────────────────────────────────────────
CELL3 = r"""import nflreadpy
import pandas as pd
import numpy as np
from unidecode import unidecode

CURRENT_YEAR = 2025
PEAK_AGE_WRTE = 26

# Load opportunity + EPA features ONCE outside dfMaker
print("Fetching WR/TE opportunity/EPA features for 2023-2024...")
wrte_opp_raw = nflreadpy.load_player_stats([2023, 2024], summary_level='reg').to_pandas()
wrte_opp = wrte_opp_raw[['player_id', 'season',
                           'target_share', 'air_yards_share',
                           'wopr', 'racr', 'receiving_epa']].copy()
wrte_opp['season'] = wrte_opp['season'].astype(int)

WRTE_COLS = ["team", "position", "penalty", "GP", "player_display_name", "age",
             'carries', 'rushing_yards', 'rushing_tds', 'rushing_fumbles_lost',
             'rushing_first_downs', 'rushing_2pt_conversions',
             'receptions', 'targets', 'receiving_yards', 'receiving_tds',
             'receiving_fumbles_lost', 'receiving_air_yards', 'receiving_yards_after_catch',
             'receiving_first_downs', 'receiving_2pt_conversions', 'special_teams_tds', 'rrtd',
             "PPG",
             'target_share', 'air_yards_share', 'wopr', 'racr', 'receiving_epa',
             'ppg_prev', 'ppg_last_year', 'delta_ppg',
             'age_from_peak', 'age_squared', 'games_missed']

def dfMaker():
    for ppr in range(3):
        oldWRTEStats = pd.read_pickle("PickleFiles/final_wrte_data.pkl")
        oldWRTEStats['YearsBack'] = CURRENT_YEAR - oldWRTEStats['season'].astype(int)
        oldWRTEStats['season'] = oldWRTEStats['season'].astype(int)
        oldWRTEStats = oldWRTEStats.merge(wrte_opp, on=['player_id', 'season'], how='left')

        currTeamsRoster = pd.read_pickle("PickleFiles/currYearRoster.pkl")
        currAVs = pd.read_pickle("PickleFiles/currAVs.pkl")

        completeDFWRTE = pd.DataFrame(columns=WRTE_COLS)
        rookieList = []

        for index in range(len(currTeamsRoster)):
            year = currTeamsRoster.loc[index, 'Yrs']
            bday = currTeamsRoster.loc[index, 'BirthDate']
            pos  = currTeamsRoster.loc[index, 'Pos']
            age  = currTeamsRoster.loc[index, 'Age']
            name = currTeamsRoster.loc[index, 'Player']
            team = currTeamsRoster.loc[index, 'Team']

            if pos not in ("WR", "TE"):
                continue

            if year == "Rook":
                rookieList.append({"Name": name, "Year": year, "Bday": bday, "Age": age, "Team": team})
                continue

            r1 = oldWRTEStats[(oldWRTEStats['player_display_name'] == name) & (oldWRTEStats['YearsBack'] == 1)].copy()
            r2 = oldWRTEStats[(oldWRTEStats['player_display_name'] == name) & (oldWRTEStats['YearsBack'] == 2)].copy()

            if not r1.empty and r1.iloc[0]['GP'] >= 8:
                row = r1.iloc[0]
            elif not r2.empty:
                row = r2.iloc[0]
            else:
                continue

            gp = float(row['GP'])
            if gp < 6:
                continue

            count_cols = ['carries', 'rushing_yards', 'rushing_tds', 'rushing_fumbles_lost',
                          'rushing_first_downs', 'rushing_2pt_conversions',
                          'receptions', 'targets', 'receiving_yards', 'receiving_tds',
                          'receiving_fumbles_lost', 'receiving_air_yards', 'receiving_yards_after_catch',
                          'receiving_first_downs', 'receiving_2pt_conversions', 'special_teams_tds', 'rrtd']
            per_game = {col: float(row.get(col, 0)) / gp for col in count_cols}

            # Shares/ratios — no divide
            target_share    = float(row['target_share'])    if pd.notna(row.get('target_share'))    else 0.0
            air_yards_share = float(row['air_yards_share']) if pd.notna(row.get('air_yards_share')) else 0.0
            wopr            = float(row['wopr'])             if pd.notna(row.get('wopr'))             else 0.0
            racr            = float(row['racr'])             if pd.notna(row.get('racr'))             else 0.0
            # receiving_epa is season total -> per game
            receiving_epa   = float(row['receiving_epa']) / gp if pd.notna(row.get('receiving_epa')) else 0.0

            base_ppg = (per_game['rushing_yards'] * 0.1 +
                        per_game['rushing_tds'] * 6 +
                        per_game['rushing_fumbles_lost'] * -2 +
                        per_game['receiving_yards'] * 0.1 +
                        per_game['receiving_tds'] * 6 +
                        per_game['receiving_fumbles_lost'] * -2)
            rec_pg = per_game['receptions']
            if ppr == 2:
                PPG = base_ppg + rec_pg
            elif ppr == 1:
                PPG = base_ppg + rec_pg * 0.5
            else:
                PPG = base_ppg

            def wrte_ppg_from_row(r, p):
                gp_ = max(float(r['GP']), 1)
                b = (float(r.get('rushing_yards', 0)) * 0.1 +
                     float(r.get('rushing_tds', 0)) * 6 +
                     float(r.get('rushing_fumbles_lost', 0)) * -2 +
                     float(r.get('receiving_yards', 0)) * 0.1 +
                     float(r.get('receiving_tds', 0)) * 6 +
                     float(r.get('receiving_fumbles_lost', 0)) * -2) / gp_
                rec_ = float(r.get('receptions', 0)) / gp_
                return b + (rec_ if p == 2 else rec_ * 0.5 if p == 1 else 0)

            ppg_yb1 = wrte_ppg_from_row(r1.iloc[0], ppr) if not r1.empty else PPG
            ppg_yb2 = wrte_ppg_from_row(r2.iloc[0], ppr) if not r2.empty else ppg_yb1

            ppg_prev      = ppg_yb1
            ppg_last_year = ppg_yb2
            delta_ppg     = ppg_yb1 - ppg_yb2
            age_from_peak = float(age) - PEAK_AGE_WRTE
            age_squared   = float(age) ** 2
            games_missed  = max(0, 17 - int(r1.iloc[0]['GP'])) if not r1.empty else 17
            penalty       = gp

            row_data = {
                "team": team, "position": pos, "penalty": penalty, "GP": gp,
                "player_display_name": name, "age": float(age),
                **per_game,
                "PPG": PPG,
                "target_share": target_share, "air_yards_share": air_yards_share,
                "wopr": wopr, "racr": racr, "receiving_epa": receiving_epa,
                "ppg_prev": ppg_prev, "ppg_last_year": ppg_last_year, "delta_ppg": delta_ppg,
                "age_from_peak": age_from_peak, "age_squared": age_squared,
                "games_missed": games_missed
            }

            individualDFWRTE = pd.DataFrame([row_data], columns=WRTE_COLS)
            completeDFWRTE = pd.concat([completeDFWRTE, individualDFWRTE], ignore_index=True)

        completeDFWRTE = pd.merge(completeDFWRTE, currAVs, on='team', how='left')
        completeDFWRTE = completeDFWRTE.fillna(0)
        completeDFWRTE = completeDFWRTE.sort_values(by='PPG')
        pkl_map = {0: "PickleFiles/WRTEDFForModelNonPPR.pkl",
                   1: "PickleFiles/WRTEDFForModelHalfPPR.pkl",
                   2: "PickleFiles/WRTEDFForModelPPR.pkl"}
        completeDFWRTE.to_pickle(pkl_map[ppr])
        print(f"  WRTE ppr={ppr}: {len(completeDFWRTE)} players saved -> {pkl_map[ppr]}")

dfMaker()
"""

# ── CELL 4 : scorer ────────────────────────────────────────────────────────────
CELL4 = r"""import pandas as pd
import numpy as np
from itertools import chain
import joblib
from sklearn.preprocessing import MinMaxScaler
import warnings
warnings.filterwarnings("ignore")

def getScaleBack(df):
    column_index = df.columns.get_loc("PPG")
    min_value = df["PPG"].min()
    max_value = df["PPG"].max()
    return [min_value, max_value]

def scorer():
    scaler = MinMaxScaler()

    for ppr in range(3):
        dictScores = {}

        if ppr == 0:
            qb   = pd.read_pickle("PickleFiles/QBDFForModelNonPPR.pkl")
            rb   = pd.read_pickle("PickleFiles/RBDFForModelNonPPR.pkl")
            wrte = pd.read_pickle("PickleFiles/WRTEDFForModelNonPPR.pkl")

            rbModel   = joblib.load("rb models/rbModelNonPPR.joblib")
            wrModel   = joblib.load("wrte models/wrModelNonPPR.joblib")
            teModel   = joblib.load("wrte models/teModelNonPPR.joblib")
            qbModel   = joblib.load("qb models/qbModelNonPPR.joblib")
        elif ppr == 1:
            qb   = pd.read_pickle("PickleFiles/QBDFForModelHalfPPR.pkl")
            rb   = pd.read_pickle("PickleFiles/RBDFForModelHalfPPR.pkl")
            wrte = pd.read_pickle("PickleFiles/WRTEDFForModelHalfPPR.pkl")

            rbModel   = joblib.load("rb models/rbModelHalfPPR.joblib")
            wrModel   = joblib.load("wrte models/wrModelHalfPPR.joblib")
            teModel   = joblib.load("wrte models/teModelHalfPPR.joblib")
            qbModel   = joblib.load("qb models/qbModelHalfPPR.joblib")
        elif ppr == 2:
            qb   = pd.read_pickle("PickleFiles/QBDFForModelPPR.pkl")
            rb   = pd.read_pickle("PickleFiles/RBDFForModelPPR.pkl")
            wrte = pd.read_pickle("PickleFiles/WRTEDFForModelPPR.pkl")

            rbModel   = joblib.load("rb models/rbModelPPR.joblib")
            wrModel   = joblib.load("wrte models/wrModelPPR.joblib")
            teModel   = joblib.load("wrte models/teModelPPR.joblib")
            qbModel   = joblib.load("qb models/qbModelPPR.joblib")

        # Route by position: WR -> wrModel, TE -> teModel, RB -> rbModel, QB -> qbModel
        modelsDict = {"QB": qbModel, "WR": wrModel, "TE": teModel, "RB": rbModel}

        scaleQB   = getScaleBack(qb)
        scaleRB   = getScaleBack(rb)
        scaleWRTE = getScaleBack(wrte)

        # Scale each positional df (drop metadata columns)
        drop_meta = ["GP", "player_display_name", "team", "position", "penalty", "PPG"]

        rbScaled = rb.copy()
        rbScaled = rbScaled.drop(columns=drop_meta, errors='ignore')
        rbScaled[rbScaled.columns] = scaler.fit_transform(rbScaled[rbScaled.columns])

        wrteScaled = wrte.copy()
        wrteScaled = wrteScaled.drop(columns=drop_meta, errors='ignore')
        wrteScaled[wrteScaled.columns] = scaler.fit_transform(wrteScaled[wrteScaled.columns])

        qbScaled = qb.copy()
        qbScaled = qbScaled.drop(columns=drop_meta, errors='ignore')
        qbScaled[qbScaled.columns] = scaler.fit_transform(qbScaled[qbScaled.columns])

        allPosDFs       = [rb, wrte, qb]
        allPosDfsScaled = [rbScaled, wrteScaled, qbScaled]
        scaleBack       = [scaleRB, scaleWRTE, scaleQB]

        indPosArr = []

        for ind in range(len(allPosDFs)):
            currDF = allPosDFs[ind]
            scaled = allPosDfsScaled[ind]
            arr    = scaleBack[ind]

            currDF["Final PPG"] = 0

            for i in range(len(currDF)):
                currRow = currDF.iloc[[i]]
                currRow = currRow.reset_index()
                scaled  = scaled.reset_index()
                scaled  = scaled.drop(columns=["index"], errors='ignore')
                currRowForModel = scaled.iloc[[i]]

                pos  = currRow.loc[0, "position"]
                name = currRow.loc[0, "player_display_name"]
                team = currRow.loc[0, "team"]

                # Route directly by position (WR and TE are separate models)
                model = modelsDict[pos]
                currRowForModel = currRowForModel[model.feature_names_in_]
                prediction = model.predict(currRowForModel)

                prediction = (prediction * (arr[1] - arr[0])) + arr[0]
                currDF.at[i, "Final PPG"] = prediction[0]

            indPosArr.append(currDF)

        finalrbs  = indPosArr[0].sort_values(by="Final PPG", ascending=False)
        finalwrte = indPosArr[1].sort_values(by="Final PPG", ascending=False)
        finalqbs  = indPosArr[2].sort_values(by="Final PPG", ascending=False)

        finalrbs["Rank"]  = np.arange(1, len(finalrbs) + 1)
        finalwrte["Rank"] = np.arange(1, len(finalwrte) + 1)
        finalqbs["Rank"]  = np.arange(1, len(finalqbs) + 1)

        finalrbs  = finalrbs[["Rank",  "player_display_name", "team", "position", "Final PPG"]]
        finalwrte = finalwrte[["Rank", "player_display_name", "team", "position", "Final PPG"]]
        finalqbs  = finalqbs[["Rank",  "player_display_name", "team", "position", "Final PPG"]]

        finalrbs.columns  = ["Rank", "Name", "Team", "Position", "Final PPG"]
        finalwrte.columns = ["Rank", "Name", "Team", "Position", "Final PPG"]
        finalqbs.columns  = ["Rank", "Name", "Team", "Position", "Final PPG"]

        if ppr == 0:
            finalrbs.to_pickle("PickleFiles/RBs_NonPPR.pkl")
            finalwrte.to_pickle("PickleFiles/WRTE_NonPPR.pkl")
            finalqbs.to_pickle("PickleFiles/QBs_NonPPR.pkl")
        elif ppr == 1:
            finalrbs.to_pickle("PickleFiles/RBs_HalfPPR.pkl")
            finalwrte.to_pickle("PickleFiles/WRTE_HalfPPR.pkl")
            finalqbs.to_pickle("PickleFiles/QBs_HalfPPR.pkl")
        elif ppr == 2:
            finalrbs.to_pickle("PickleFiles/RBs_PPR.pkl")
            finalwrte.to_pickle("PickleFiles/WRTE_PPR.pkl")
            finalqbs.to_pickle("PickleFiles/QBs_PPR.pkl")

scorer()
"""

# ── Apply patches ──────────────────────────────────────────────────────────────
nb['cells'][1]['source'] = [CELL1]
nb['cells'][2]['source'] = [CELL2]
nb['cells'][3]['source'] = [CELL3]
nb['cells'][4]['source'] = [CELL4]

with open(NB_PATH, 'w') as f:
    json.dump(nb, f, indent=1)

print("patch_predcode.py: PredictionCode.ipynb cells 1, 2, 3, 4 successfully rewritten.")
