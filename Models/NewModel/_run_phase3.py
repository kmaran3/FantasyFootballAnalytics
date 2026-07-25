import pandas as pd
import numpy as np
import pickle
import os
import warnings
warnings.filterwarnings('ignore')

from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error
import xgboost as xgb

INPUT_DIR  = '../PickleFiles/NewModel'
OUTPUT_DIR = '../PickleFiles/NewModel'

# Columns to never use as features
EXCLUDE_COLS = {
    'player_name', 'team', 'position', 'age_bucket',
    'season', 'next_ppg', 'ppg', 'fantasy_pts',
    'ppg_lag1', 'ppg_lag2'  # intermediate cols from weighted_ppg calc
}

# Walk-forward test seasons (we know ground truth for these)
TEST_SEASONS = [2024, 2025]

print('Imports done.')

# =========

# ── Helper Functions ──────────────────────────────────────────────────────────

def create_target(df, id_col='player_name', season_col='season', ppg_col='ppg'):
    """
    Add next_ppg = the player's PPG in their next season.
    Rows where next_ppg is NaN = the player had no following season in the dataset.
    The 2025 feature rows will have next_ppg=NaN — these are what we predict for 2026.
    """
    df = df.sort_values([id_col, season_col]).copy()
    df['next_ppg'] = df.groupby(id_col)[ppg_col].shift(-1)
    return df


def get_feature_cols(df):
    """Return all numeric columns not in EXCLUDE_COLS."""
    numeric = df.select_dtypes(include=[np.number]).columns.tolist()
    return [c for c in numeric if c not in EXCLUDE_COLS]


def make_ridge():
    """Ridge pipeline: median impute NaN, standardize, then Ridge."""
    return Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('scaler',  StandardScaler()),
        ('model',   Ridge(alpha=10.0))
    ])


def make_xgb():
    """XGBoost — handles NaN natively, capped depth to avoid overfitting on small datasets."""
    return xgb.XGBRegressor(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.7,
        min_child_weight=5,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=42,
        verbosity=0
    )


def walk_forward_cv(df, feature_cols, test_seasons):
    """
    Walk-forward cross-validation.
    For each test_season:
      - Train on all feature_seasons < (test_season - 1), target = next season ppg
      - Test on feature_season = (test_season - 1), target = test_season ppg
    Returns a dict of {test_season: {'ridge_mae': x, 'xgb_mae': y, 'blend_mae': z, 'n': n}}
    """
    results = {}

    for test_season in test_seasons:
        feature_season = test_season - 1  # the season whose features predict test_season

        train = df[(df['season'] < feature_season) & df['next_ppg'].notna()]
        test  = df[(df['season'] == feature_season) & df['next_ppg'].notna()]

        if len(train) < 10 or len(test) < 3:
            print(f'  Skipping {test_season}: insufficient data (train={len(train)}, test={len(test)})')
            continue

        X_train = train[feature_cols]
        y_train = train['next_ppg']
        X_test  = test[feature_cols]
        y_test  = test['next_ppg']

        # Ridge
        ridge = make_ridge()
        ridge.fit(X_train, y_train)
        ridge_preds = ridge.predict(X_test)
        ridge_mae   = mean_absolute_error(y_test, ridge_preds)

        # XGBoost
        xgb_model = make_xgb()
        xgb_model.fit(X_train, y_train)
        xgb_preds = xgb_model.predict(X_test)
        xgb_mae   = mean_absolute_error(y_test, xgb_preds)

        # Blend (50/50)
        blend_preds = (ridge_preds + xgb_preds) / 2
        blend_mae   = mean_absolute_error(y_test, blend_preds)

        results[test_season] = {
            'ridge_mae': round(ridge_mae, 2),
            'xgb_mae':   round(xgb_mae, 2),
            'blend_mae': round(blend_mae, 2),
            'n':         len(test)
        }

    return results


def pick_strategy(cv_results):
    """
    Compare average MAE across CV folds.
    If difference between winner and blend is < 5%, use blend (safer).
    Otherwise use the clear winner.
    """
    if not cv_results:
        return 'blend'

    avg = {'ridge': 0, 'xgb': 0, 'blend': 0}
    for r in cv_results.values():
        avg['ridge'] += r['ridge_mae']
        avg['xgb']   += r['xgb_mae']
        avg['blend']  += r['blend_mae']

    n = len(cv_results)
    avg = {k: v / n for k, v in avg.items()}
    best = min(avg, key=avg.get)
    second = sorted(avg, key=avg.get)[1]

    # If best is within 5% of blend, prefer blend for stability
    if best != 'blend' and abs(avg[best] - avg['blend']) / avg['blend'] < 0.05:
        return 'blend'
    return best


def train_final_and_predict(df, feature_cols, strategy, predict_season=2025):
    """
    Train final model on ALL seasons with known next_ppg.
    Predict next year PPG for players in predict_season.
    Returns (predictions_df, ridge_model, xgb_model)
    """
    train = df[df['next_ppg'].notna()]
    pred  = df[df['season'] == predict_season].copy()

    X_train = train[feature_cols]
    y_train = train['next_ppg']
    X_pred  = pred[feature_cols]

    ridge = make_ridge()
    ridge.fit(X_train, y_train)

    xgb_model = make_xgb()
    xgb_model.fit(X_train, y_train)

    ridge_preds = ridge.predict(X_pred)
    xgb_preds   = xgb_model.predict(X_pred)
    blend_preds = (ridge_preds + xgb_preds) / 2

    strategy_preds = {'ridge': ridge_preds, 'xgb': xgb_preds, 'blend': blend_preds}[strategy]

    # Confidence-weighted blending: anchor low-experience players toward weighted_ppg
    # confidence = min(seasons_played / 3, 1.0)
    # final = confidence * model_pred + (1 - confidence) * weighted_ppg
    if 'seasons_played' in df.columns:
        seasons_played = pred['seasons_played'].values
    else:
        # Compute from full df: count how many prior seasons each player appears in
        season_counts  = df.groupby('player_name')['season'].count().to_dict()
        seasons_played = pred['player_name'].map(season_counts).fillna(1).values
    confidence     = np.minimum(seasons_played / 3.0, 1.0)
    raw_preds      = np.maximum(strategy_preds, 0)
    anchored_preds = confidence * raw_preds + (1 - confidence) * pred['weighted_ppg'].values

    pred = pred[['player_name', 'team', 'season', 'age', 'weighted_ppg', 'ppg', 'games']].copy()
    pred['predicted_ppg_2026'] = np.maximum(anchored_preds, 0)
    pred['model_pred_raw']     = raw_preds
    pred['confidence']         = confidence
    pred['seasons_played']     = seasons_played
    pred['ridge_pred']         = np.maximum(ridge_preds, 0)
    pred['xgb_pred']           = np.maximum(xgb_preds, 0)
    pred['strategy']           = strategy
    pred = pred.sort_values('predicted_ppg_2026', ascending=False).reset_index(drop=True)

    return pred, ridge, xgb_model


def run_position(name, full_pkl, feature_pkl):
    """Full pipeline for one position: CV -> pick strategy -> final model -> predictions."""
    print(f'\n{"="*50}')
    print(f'  {name}')
    print(f'{"="*50}')

    df      = pd.read_pickle(f'{INPUT_DIR}/{full_pkl}')
    df      = create_target(df)
    feat_cols = get_feature_cols(df)
    print(f'  Player-seasons: {len(df)} | Features: {len(feat_cols)}')
    print(f'  Training rows (next_ppg known): {df["next_ppg"].notna().sum()}')

    # Walk-forward CV
    print('\n  Walk-forward CV:')
    cv = walk_forward_cv(df, feat_cols, TEST_SEASONS)
    for season, r in cv.items():
        print(f'    Predicting {season} (n={r["n"]}): '
              f'Ridge MAE={r["ridge_mae"]:.2f} | '
              f'XGB MAE={r["xgb_mae"]:.2f} | '
              f'Blend MAE={r["blend_mae"]:.2f}')

    strategy = pick_strategy(cv)
    print(f'\n  Selected strategy: {strategy.upper()}')

    # Final model + 2026 predictions
    preds, ridge_model, xgb_model = train_final_and_predict(df, feat_cols, strategy)

    print(f'\n  2026 Predictions (top 10):')
    print(preds[['player_name','team','age','predicted_ppg_2026','weighted_ppg']]
          .head(10).to_string(index=False))

    # Save
    pos = name.lower()
    preds.to_pickle(f'{OUTPUT_DIR}/{pos}_predictions_ppr.pkl')
    with open(f'{OUTPUT_DIR}/{pos}_ridge_ppr.pkl', 'wb') as f:
        pickle.dump(ridge_model, f)
    with open(f'{OUTPUT_DIR}/{pos}_xgb_ppr.pkl', 'wb') as f:
        pickle.dump(xgb_model, f)

    return preds, cv


print('Helper functions defined.')

# =========

# ── QB ────────────────────────────────────────────────────────────────────────
qb_preds, qb_cv = run_position('QB', 'qb_full.pkl', 'qb_features.pkl')

# =========

# ── RB ────────────────────────────────────────────────────────────────────────
rb_preds, rb_cv = run_position('RB', 'rb_full.pkl', 'rb_features.pkl')

# =========

# ── WR ────────────────────────────────────────────────────────────────────────
wr_preds, wr_cv = run_position('WR', 'wr_full.pkl', 'wr_features.pkl')

# =========

# ── TE ────────────────────────────────────────────────────────────────────────
te_preds, te_cv = run_position('TE', 'te_full.pkl', 'te_features.pkl')

# =========

# ── Accuracy Summary + Combined Rankings ─────────────────────────────────────

print('\nACCURACY SUMMARY (MAE = avg points per game off)')
print('-' * 60)
for pos, cv in [('QB', qb_cv), ('RB', rb_cv), ('WR', wr_cv), ('TE', te_cv)]:
    for season, r in cv.items():
        best = min(r['ridge_mae'], r['xgb_mae'], r['blend_mae'])
        print(f'  {pos} predicting {season}: best MAE = {best:.2f} ppg (n={r["n"]})')

# Combine all predictions into one rankings table
all_preds = []
for pos, df in [('QB', qb_preds), ('RB', rb_preds), ('WR', wr_preds), ('TE', te_preds)]:
    df = df.copy()
    df['position'] = pos
    all_preds.append(df)

combined = pd.concat(all_preds, ignore_index=True)
combined = combined.sort_values('predicted_ppg_2026', ascending=False).reset_index(drop=True)
combined['rank'] = combined.index + 1

combined.to_pickle(f'{OUTPUT_DIR}/combined_predictions_ppr.pkl')

print('\nTOP 30 PPR PREDICTIONS FOR 2026')
print('-' * 60)
print(combined[['rank','player_name','position','team','age',
                'predicted_ppg_2026','weighted_ppg','strategy']]
      .head(30).to_string(index=False))

print('\nSaved:')
print('  combined_predictions_ppr.pkl')
print('  qb/rb/wr/te _predictions_ppr.pkl')
print('  qb/rb/wr/te _ridge_ppr.pkl + _xgb_ppr.pkl')