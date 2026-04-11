from flask import Blueprint, render_template, url_for, flash, redirect, request, jsonify, current_app as app
from flask_login import login_user, current_user, logout_user, login_required
import pandas as pd
import requests
from sqlalchemy import create_engine, text
from bs4 import BeautifulSoup
from pathlib import Path
from webapp.forms import LoginForm, RegistrationForm
from webapp import db, User, UserRanking, MockDraft
import json

main = Blueprint('main', __name__)

_DB_PATH = Path(__file__).resolve().parent.parent / 'webapp' / 'my_database.db'
engine = create_engine(f'sqlite:///{_DB_PATH}', echo=True)

_BASE_DIR = Path(__file__).parent.parent
_PICKLE_DIR = _BASE_DIR / 'Models' / 'PickleFiles'

# nflverse uses 'LA' for Rams; our DB uses 'LAR'
_TEAM_ABBR_MAP = {'LA': 'LAR'}

_player_details_cache = None
_team_schedule_cache = None


def _normalize_team(team):
    return _TEAM_ABBR_MAP.get(str(team), str(team))


def _get_player_details():
    global _player_details_cache
    if _player_details_cache is not None:
        return _player_details_cache

    details = {}

    # Age from currYearRoster
    roster_path = _PICKLE_DIR / 'currYearRoster.pkl'
    if roster_path.exists():
        roster_df = pd.read_pickle(roster_path)
        for _, row in roster_df.iterrows():
            name = str(row['Player']).strip()
            details[name] = {
                'age': int(row['Age']) if pd.notna(row['Age']) else None,
                'position': str(row['Pos']),
                'stats_year': None,
                'stats': {}
            }

    def _int(val):
        return int(val) if pd.notna(val) else 0

    def _float1(val):
        return round(float(val), 1) if pd.notna(val) else 0.0

    # QB stats (most recent season)
    qb_path = _PICKLE_DIR / 'final_qb_data.pkl'
    if qb_path.exists():
        df = pd.read_pickle(qb_path)
        df = df[df['season'] == df['season'].max()]
        if 'season_type' in df.columns:
            df = df[df['season_type'] == 'REG']
        for _, row in df.iterrows():
            name = str(row['player_display_name']).strip()
            stat = {
                'GP': _int(row['GP']),
                'completions': _int(row['completions']),
                'attempts': _int(row['attempts']),
                'passing_yards': _int(row['passing_yards']),
                'passing_tds': _int(row['passing_tds']),
                'interceptions': _int(row['interceptions']),
                'rushing_yards': _int(row['rushing_yards']),
                'rushing_tds': _int(row['rushing_tds']),
                'fantasy_points': _float1(row['fantasy_points']),
            }
            entry = details.setdefault(name, {'age': _int(row['age']) if pd.notna(row['age']) else None, 'position': 'QB', 'stats_year': None, 'stats': {}})
            entry['stats_year'] = int(row['season'])
            entry['stats'] = stat

    # RB stats
    rb_path = _PICKLE_DIR / 'final_rb_data.pkl'
    if rb_path.exists():
        df = pd.read_pickle(rb_path)
        df = df[df['season'] == df['season'].max()]
        if 'season_type' in df.columns:
            df = df[df['season_type'] == 'REG']
        for _, row in df.iterrows():
            name = str(row['player_display_name']).strip()
            stat = {
                'GP': _int(row['GP']),
                'carries': _int(row['carries']),
                'rushing_yards': _int(row['rushing_yards']),
                'rushing_tds': _int(row['rushing_tds']),
                'receptions': _int(row['receptions']),
                'targets': _int(row['targets']),
                'receiving_yards': _int(row['receiving_yards']),
                'receiving_tds': _int(row['receiving_tds']),
                'fantasy_points': _float1(row['fantasy_points']),
            }
            entry = details.setdefault(name, {'age': _int(row['age']) if pd.notna(row['age']) else None, 'position': 'RB', 'stats_year': None, 'stats': {}})
            entry['stats_year'] = int(row['season'])
            entry['stats'] = stat

    # WR/TE stats
    wrte_path = _PICKLE_DIR / 'final_wrte_data.pkl'
    if wrte_path.exists():
        df = pd.read_pickle(wrte_path)
        df = df[df['season'] == df['season'].max()]
        if 'season_type' in df.columns:
            df = df[df['season_type'] == 'REG']
        for _, row in df.iterrows():
            name = str(row['player_display_name']).strip()
            stat = {
                'GP': _int(row['GP']),
                'receptions': _int(row['receptions']),
                'targets': _int(row['targets']),
                'receiving_yards': _int(row['receiving_yards']),
                'receiving_tds': _int(row['receiving_tds']),
                'carries': _int(row['carries']),
                'rushing_yards': _int(row['rushing_yards']),
                'fantasy_points': _float1(row['fantasy_points']),
            }
            entry = details.setdefault(name, {'age': _int(row['age']) if pd.notna(row['age']) else None, 'position': str(row['position']), 'stats_year': None, 'stats': {}})
            entry['stats_year'] = int(row['season'])
            entry['stats'] = stat

    _player_details_cache = details
    return details


def _get_team_schedule():
    global _team_schedule_cache
    if _team_schedule_cache is not None:
        return _team_schedule_cache

    try:
        import nflreadpy
        schedule_df = nflreadpy.load_schedules([2025]).to_pandas()
        reg_df = schedule_df[schedule_df['game_type'] == 'REG'].sort_values('week')

        team_games = {}
        for _, row in reg_df.iterrows():
            week = int(row['week'])
            home = _normalize_team(row['home_team'])
            away = _normalize_team(row['away_team'])

            team_games.setdefault(home, [])
            if len(team_games[home]) < 5:
                team_games[home].append({'week': week, 'opponent': away, 'home_away': 'home'})

            team_games.setdefault(away, [])
            if len(team_games[away]) < 5:
                team_games[away].append({'week': week, 'opponent': home, 'home_away': 'away'})

        _team_schedule_cache = team_games
    except Exception as e:
        print(f'Warning: Could not load NFL schedule data: {e}')
        _team_schedule_cache = {}

    return _team_schedule_cache


def _ranking_extras(df):
    """Return player_details_json, team_schedule_json, teams, bye_weeks for a ranking df."""
    player_details = _get_player_details()
    team_schedule = _get_team_schedule()
    rows = df.to_dict(orient='records')
    teams = sorted(set(str(r['Team']) for r in rows if r.get('Team')))
    bye_weeks = sorted(set(int(r['Bye Week']) for r in rows if r.get('Bye Week') is not None))
    return (
        json.dumps(player_details),
        json.dumps(team_schedule),
        teams,
        bye_weeks,
    )

# Load stat data once at startup
_data_dir = Path(__file__).parent.parent / 'Models' / 'PickleFiles'

def _load(filename):
    try:
        return pd.read_pickle(_data_dir / filename)
    except Exception:
        return pd.DataFrame()

_rankings = _load('Full PPR Rankings with Weighted VBD.pkl')

# Load live seasonal stats from nflreadpy
_nfl_seasonal  = pd.DataFrame()
_nfl_latest    = pd.DataFrame()   # most-recent season with accurate position + team per player
_nfl_roster_map = {}
try:
    import nflreadpy
    from datetime import date as _date
    _today = _date.today()
    # NFL season Y runs Sep Y – Jan/Feb Y+1; before September the latest complete season is Y-1
    _nfl_end_year = _today.year if _today.month >= 9 else _today.year - 1

    # Try loading up to _nfl_end_year; if nflreadpy doesn't have that year yet, fall back one year
    _stats_raw = pd.DataFrame()
    for _try_year in [_nfl_end_year, _nfl_end_year - 1]:
        try:
            _seasons = list(range(2020, _try_year + 1))
            _stats_raw = nflreadpy.load_player_stats(_seasons, summary_level='reg').to_pandas()
            if not _stats_raw.empty:
                print(f'NFL stats loaded through season {_try_year}')
                break
        except Exception as _ye:
            print(f'NFL data unavailable for seasons through {_try_year}: {_ye}')

    if _stats_raw.empty:
        raise RuntimeError('Could not load NFL seasonal stats for any year')

    # nflreadpy player stats already includes player_name, position, recent_team — no roster merge needed
    _nfl_seasonal = _stats_raw.copy()

    # For grades + roster stats: use the most recent season actually present in the data
    _latest_season = int(_stats_raw['season'].max())
    _nfl_latest = (_stats_raw[_stats_raw['season'] == _latest_season]
                   .assign(_pos=lambda x: x['position'],
                           _team=lambda x: x['recent_team'],
                           _name=lambda x: x['player_name'])
                   .copy())
    print(f'NFL data ready: history 2020–{max(_seasons)}, grades/roster from season {_latest_season} ({len(_nfl_latest)} players)')
except Exception as e:
    print(f'Warning: could not load nflreadpy stats: {e}')

# Normalize currAVs team names to abbreviations
_TEAM_NAME_MAP = {
    'arizona cardinals': 'ARI', 'atlanta falcons': 'ATL', 'baltimore ravens': 'BAL',
    'buffalo bills': 'BUF', 'carolina panthers': 'CAR', 'chicago bears': 'CHI',
    'cincinnati bengals': 'CIN', 'cleveland browns': 'CLE', 'dallas cowboys': 'DAL',
    'denver broncos': 'DEN', 'detroit lions': 'DET', 'green bay packers': 'GB',
    'houston texans': 'HOU', 'indianapolis colts': 'IND', 'jacksonville jaguars': 'JAX',
    'kansas city chiefs': 'KC', 'los angeles rams': 'LA', 'los angeles chargers': 'LAC',
    'las vegas raiders': 'LV', 'miami dolphins': 'MIA', 'minnesota vikings': 'MIN',
    'new england patriots': 'NE', 'new orleans saints': 'NO', 'new york giants': 'NYG',
    'new york jets': 'NYJ', 'philadelphia eagles': 'PHI', 'pittsburgh steelers': 'PIT',
    'seattle seahawks': 'SEA', 'san francisco 49ers': 'SF', 'tampa bay buccaneers': 'TB',
    'tennessee titans': 'TEN', 'washington commanders': 'WAS',
}

def _normalize_av_team(raw):
    raw = str(raw).strip()
    # Already an abbreviation
    if len(raw) <= 3:
        return raw.upper()
    # Strip leading "12. " style prefixes then match
    import re
    clean = re.sub(r'^\d+\.\s*', '', raw).strip().lower()
    return _TEAM_NAME_MAP.get(clean, raw.upper())

_raw_avs = _load('currAVs.pkl')
if not _raw_avs.empty:
    _raw_avs['team'] = _raw_avs['team'].apply(_normalize_av_team)
    _curr_avs = _raw_avs.set_index('team')
else:
    _curr_avs = _raw_avs

# ── New model predictions (Phase 3) ──────────────────────────────────
def _load_new_model_rankings():
    try:
        _new_model_dir = _BASE_DIR / 'Models' / 'PickleFiles' / 'NewModel'
        combined = pd.read_pickle(_new_model_dir / 'combined_predictions_ppr.pkl')
        combined = combined.rename(columns={
            'player_name': 'Name',
            'position':    'Position',
            'team':        'Team',
            'predicted_ppg_2026': 'Predicted PPG',
            'weighted_ppg': 'Weighted PPG',
            'ppg':         '2025 PPG',
            'vbd':         'VBD',
        })
        combined['Predicted PPG'] = combined['Predicted PPG'].round(2)
        combined['Weighted PPG']  = combined['Weighted PPG'].round(2)
        combined['2025 PPG']      = combined['2025 PPG'].round(2)
        combined['VBD']           = combined['VBD'].round(2)
        combined['Age']           = combined['age'].apply(lambda x: int(x) if pd.notna(x) and x != '' else '')
        combined = combined[['rank','Name','Position','Team','Age','Predicted PPG','VBD','Weighted PPG','2025 PPG']].copy()
        combined = combined.rename(columns={'rank': 'Rank'})
        print(f'New model rankings loaded: {len(combined)} players')
        return combined
    except Exception as e:
        import traceback
        print(f'Warning: could not load new model predictions: {e}')
        traceback.print_exc()
        return pd.DataFrame()

_new_model_rankings = _load_new_model_rankings()
print(f'_new_model_rankings shape: {_new_model_rankings.shape}, empty: {_new_model_rankings.empty}')
_new_model_table_data = _new_model_rankings.to_dict(orient='records') if not _new_model_rankings.empty else []
print(f'_new_model_table_data prebuilt: {len(_new_model_table_data)} rows')

# ── Helpers shared by composite grades and roster stats ───────────
import math as _math

def _safe_f(v, digits=1):
    try:
        f = float(v)
        return round(f, digits) if not (_math.isnan(f) or _math.isinf(f)) else None
    except (TypeError, ValueError):
        return None

def _safe_i(v):
    r = _safe_f(v, 0)
    return int(r) if r is not None else None

def _find_team_col(df):
    for c in ['recent_team', 'team', 'Team', 'posteam']:
        if c in df.columns:
            return c
    return None

def _norm_team(t):
    t = str(t).strip().upper()
    return _TEAM_ABBR_MAP.get(t, t)

# ── Composite team grades from starter fantasy performance ─────────
def _compute_composite_grades():
    per_team = {}

    use_live = (not _nfl_latest.empty
                and '_pos' in _nfl_latest.columns
                and '_team' in _nfl_latest.columns)

    if use_live:
        fpc = next((c for c in ['fantasy_points_ppr', 'fantasy_points'] if c in _nfl_latest.columns), None)
        gpc = next((c for c in ['games', 'GP'] if c in _nfl_latest.columns), None)

        if fpc and gpc:
            df = _nfl_latest.dropna(subset=['_pos', '_team']).copy()
            df['_team'] = df['_team'].apply(_norm_team)
            df['fpg']   = df[fpc] / df[gpc].clip(lower=1)

            def _process_live(pos_filter, pos_label, n_starters):
                pos_df = df[df['_pos'].str.upper() == pos_filter].copy()
                pos_df = pos_df.sort_values(fpc, ascending=False)
                top = pos_df.groupby('_team').head(n_starters)
                for team, val in top.groupby('_team')['fpg'].mean().items():
                    sf = _safe_f(val, 3)
                    if sf is not None:
                        per_team.setdefault(team, {})[pos_label] = sf

            _process_live('QB', 'QB', 1)
            _process_live('RB', 'RB', 2)
            _process_live('WR', 'WR', 3)
            _process_live('TE', 'TE', 2)

    else:
        # Fallback: pickle files (2023 data)
        def _process_pkl(df_raw, pos_label, n_starters, pos_filter=None):
            if df_raw.empty:
                return
            latest = df_raw['season'].max()
            st_col = 'season_type' if 'season_type' in df_raw.columns else None
            mask = df_raw['season'] == latest
            if st_col:
                mask = mask & (df_raw[st_col] == 'REG')
            df = df_raw[mask].copy()
            tc = _find_team_col(df)
            if tc is None or 'fantasy_points' not in df.columns or 'GP' not in df.columns:
                return
            df[tc] = df[tc].apply(_norm_team)
            df['fpg'] = df['fantasy_points'] / df['GP'].clip(lower=1)
            df_sorted = df.sort_values('fantasy_points', ascending=False)
            if pos_filter:
                pc = next((c for c in ['position', 'Position'] if c in df.columns), None)
                if pc:
                    df_sorted = df_sorted[df_sorted[pc].str.upper() == pos_filter]
            top = df_sorted.groupby(tc).head(n_starters)
            for team, val in top.groupby(tc)['fpg'].mean().items():
                sf = _safe_f(val, 3)
                if sf is not None:
                    per_team.setdefault(team, {})[pos_label] = sf

        _process_pkl(_load('final_qb_data.pkl'), 'QB', 1)
        _process_pkl(_load('final_rb_data.pkl'), 'RB', 2)
        wrte = _load('final_wrte_data.pkl')
        _process_pkl(wrte, 'WR', 3, 'WR')
        _process_pkl(wrte, 'TE', 2, 'TE')

    # Min-max normalize each position group across all teams
    composite = {}
    for pos in ['QB', 'RB', 'WR', 'TE']:
        vals = {t: d[pos] for t, d in per_team.items() if pos in d}
        if not vals:
            continue
        mn, mx = min(vals.values()), max(vals.values())
        rng = mx - mn if mx > mn else 1.0
        for team, v in vals.items():
            composite.setdefault(team, {})[pos] = round((v - mn) / rng, 2)

    # OLine + DST from currAVs (no player-level proxy available)
    if not _curr_avs.empty:
        for team in _curr_avs.index:
            row = _curr_avs.loc[team]
            composite.setdefault(team, {})
            for col, key in [('oline', 'OLine'), ('dst', 'DST')]:
                if col in _curr_avs.columns:
                    v = _safe_f(row[col], 2)
                    if v is not None:
                        composite[team][key] = v

    return composite

# ── Per-player stats for roster list view ─────────────────────────
def _compute_roster_stats():
    stats = {}

    # Prefer live nflreadpy data; fall back to pickle files
    use_live = (not _nfl_latest.empty
                and '_pos' in _nfl_latest.columns
                and '_team' in _nfl_latest.columns)

    if use_live:
        fpc = next((c for c in ['fantasy_points_ppr', 'fantasy_points'] if c in _nfl_latest.columns), None)
        gpc = next((c for c in ['games', 'GP'] if c in _nfl_latest.columns), None)

        if fpc and gpc:
            df = _nfl_latest.dropna(subset=['_pos', '_team', '_name']).copy()
            for _, row in df.iterrows():
                name = str(row.get('_name', '')).strip()
                if not name:
                    continue
                pos = str(row.get('_pos', '')).upper().strip()
                if pos not in ('QB', 'RB', 'WR', 'TE'):
                    continue
                team = _norm_team(row.get('_team', ''))
                gp   = max(_safe_i(row.get(gpc, 1)) or 1, 1)
                fp   = _safe_f(row.get(fpc))

                if pos == 'QB':
                    stats[name] = {
                        'pos': 'QB', 'team': team, 'gp': gp,
                        'fantasy_points': fp,
                        'pass_yds': _safe_i(row.get('passing_yards')),
                        'pass_td':  _safe_i(row.get('passing_tds')),
                        'int':      _safe_i(row.get('passing_interceptions')),
                        'rush_yds': _safe_i(row.get('rushing_yards')),
                    }
                elif pos == 'RB':
                    carries  = _safe_i(row.get('carries', 1)) or 1
                    rush_yds = _safe_i(row.get('rushing_yards', 0)) or 0
                    stats[name] = {
                        'pos': 'RB', 'team': team, 'gp': gp,
                        'fantasy_points': fp,
                        'rush_yds': rush_yds,
                        'ypc':      round(rush_yds / carries, 1) if carries > 0 else None,
                        'rec':      _safe_i(row.get('receptions')),
                        'rec_yds':  _safe_i(row.get('receiving_yards')),
                    }
                else:  # WR / TE
                    tgts = _safe_i(row.get('targets'))
                    rec  = _safe_i(row.get('receptions'))
                    stats[name] = {
                        'pos': pos, 'team': team, 'gp': gp,
                        'fantasy_points': fp,
                        'targets':    tgts,
                        'receptions': rec,
                        'catch_pct':  round(rec / tgts * 100, 1) if tgts and tgts > 0 and rec is not None else None,
                        'rec_yds':    _safe_i(row.get('receiving_yards')),
                    }

    else:
        # Fallback: pickle files (2023 data)
        def _team_pkl(row, tc):
            return _norm_team(row.get(tc, '')) if tc else ''

        qb_df = _load('final_qb_data.pkl')
        if not qb_df.empty:
            df = qb_df[qb_df['season'] == qb_df['season'].max()]
            if 'season_type' in df.columns:
                df = df[df['season_type'] == 'REG']
            tc = _find_team_col(df)
            for _, row in df.iterrows():
                name = str(row.get('player_display_name', '')).strip()
                if not name:
                    continue
                rush_yds = _safe_i(row.get('rushing_yards', 0)) or 0
                stats[name] = {
                    'pos': 'QB', 'team': _team_pkl(row, tc),
                    'gp': _safe_i(row.get('GP', 1)) or 1,
                    'fantasy_points': _safe_f(row.get('fantasy_points')),
                    'pass_yds': _safe_i(row.get('passing_yards')),
                    'pass_td':  _safe_i(row.get('passing_tds')),
                    'int':      _safe_i(row.get('interceptions')),
                    'rush_yds': rush_yds,
                }

        rb_df = _load('final_rb_data.pkl')
        if not rb_df.empty:
            df = rb_df[rb_df['season'] == rb_df['season'].max()]
            if 'season_type' in df.columns:
                df = df[df['season_type'] == 'REG']
            tc = _find_team_col(df)
            for _, row in df.iterrows():
                name = str(row.get('player_display_name', '')).strip()
                if not name:
                    continue
                carries  = _safe_i(row.get('carries', 1)) or 1
                rush_yds = _safe_i(row.get('rushing_yards', 0)) or 0
                stats[name] = {
                    'pos': 'RB', 'team': _team_pkl(row, tc),
                    'gp': _safe_i(row.get('GP', 1)) or 1,
                    'fantasy_points': _safe_f(row.get('fantasy_points')),
                    'rush_yds': rush_yds,
                    'ypc':      round(rush_yds / carries, 1) if carries > 0 else None,
                    'rec':      _safe_i(row.get('receptions')),
                    'rec_yds':  _safe_i(row.get('receiving_yards')),
                }

        wrte_df = _load('final_wrte_data.pkl')
        if not wrte_df.empty:
            df = wrte_df[wrte_df['season'] == wrte_df['season'].max()]
            if 'season_type' in df.columns:
                df = df[df['season_type'] == 'REG']
            tc = _find_team_col(df)
            pc = next((c for c in ['position', 'Position'] if c in df.columns), None)
            for _, row in df.iterrows():
                name = str(row.get('player_display_name', '')).strip()
                if not name:
                    continue
                pos  = str(row.get(pc, 'WR')).upper() if pc else 'WR'
                tgts = _safe_i(row.get('targets'))
                rec  = _safe_i(row.get('receptions'))
                stats[name] = {
                    'pos': pos, 'team': _team_pkl(row, tc),
                    'gp': _safe_i(row.get('GP', 1)) or 1,
                    'fantasy_points': _safe_f(row.get('fantasy_points')),
                    'targets':    tgts,
                    'receptions': rec,
                    'catch_pct':  round(rec / tgts * 100, 1) if tgts and tgts > 0 and rec is not None else None,
                    'rec_yds':    _safe_i(row.get('receiving_yards')),
                }

    # Fantasy-point thresholds per position for color coding
    fp_thresholds = {}
    for pos in ['QB', 'RB', 'WR', 'TE']:
        fps = sorted(v['fantasy_points'] for v in stats.values()
                     if v.get('pos') == pos and v.get('fantasy_points') is not None)
        if fps:
            n = len(fps)
            fp_thresholds[pos] = {'p25': fps[n // 4], 'p75': fps[3 * n // 4]}

    return stats, fp_thresholds

_composite_grades  = _compute_composite_grades()
_roster_stats, _fp_thresholds = _compute_roster_stats()

# Load stat data once at startup
_data_dir = Path(__file__).parent.parent / 'Models' / 'PickleFiles'

def _load(filename):
    try:
        return pd.read_pickle(_data_dir / filename)
    except Exception:
        return pd.DataFrame()

_qb_stats    = _load('final_qb_data.pkl')
_rb_stats    = _load('final_rb_data.pkl')
_wrte_stats  = _load('final_wrte_data.pkl')
_qb_model    = _load('QBDFForModelPPR.pkl')
_rb_model    = _load('RBDFForModelPPR.pkl')
_wrte_model  = _load('WRTEDFForModelPPR.pkl')
_rankings    = _load('Full PPR Rankings with Weighted VBD.pkl')
_curr_avs    = _load('currAVs.pkl')

@main.route('/', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(id=form.username.data).first()
        if user and user.password == form.password.data:
            login_user(user)
            return redirect(url_for('main.home'))
        else:
            flash('Invalid username or password')
    return render_template('login.html', form=form)

@main.route('/logout')
def logout():
    logout_user()
    flash('You have been logged out.')
    return redirect(url_for('main.login'))

@main.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash('An account with that email already exists.')
            return render_template('register.html', form=form)
        if User.query.filter_by(id=form.username.data).first():
            flash('That username is already taken.')
            return render_template('register.html', form=form)
        user = User(id=form.username.data, email=form.email.data, password=form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Thanks for registering! Please log in.')
        return redirect(url_for('main.login'))
    return render_template('register.html', form=form)

@main.route('/home')
@login_required
def home():
    return render_template('home.html')

@main.route('/about')
def about():
    return render_template('about.html')

@main.route('/contact')
def contact():
    return render_template('contact.html')

@main.route('/rankings', methods=['GET', 'POST'])
@login_required
def rankings():
    return redirect(url_for('main.get_ppr_rankings'))

@main.route('/rankings/ppr')
@login_required
def get_ppr_rankings():
    import sqlite3
    with sqlite3.connect(str(_DB_PATH)) as conn:
        df = pd.read_sql('SELECT * FROM Full_PPR', con=conn)
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    pd_json, ts_json, teams, bye_weeks = _ranking_extras(df)
    return render_template('rankings.html', table_data=df.to_dict(orient='records'), table_type='PPR',
                           user_rankings=saved, player_details_json=pd_json,
                           team_schedule_json=ts_json, teams=teams, bye_weeks=bye_weeks)

@main.route('/rankings/half-ppr')
@login_required
def get_half_ppr_rankings():
    import sqlite3
    with sqlite3.connect(str(_DB_PATH)) as conn:
        df = pd.read_sql('SELECT * FROM Half_PPR', con=conn)
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    pd_json, ts_json, teams, bye_weeks = _ranking_extras(df)
    return render_template('rankings.html', table_data=df.to_dict(orient='records'), table_type='Half PPR',
                           user_rankings=saved, player_details_json=pd_json,
                           team_schedule_json=ts_json, teams=teams, bye_weeks=bye_weeks)

@main.route('/rankings/standard')
@login_required
def get_standard_rankings():
    import sqlite3
    with sqlite3.connect(str(_DB_PATH)) as conn:
        df = pd.read_sql('SELECT * FROM Non_PPR', con=conn)
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    pd_json, ts_json, teams, bye_weeks = _ranking_extras(df)
    return render_template('rankings.html', table_data=df.to_dict(orient='records'), table_type='Standard',
                           user_rankings=saved, player_details_json=pd_json,
                           team_schedule_json=ts_json, teams=teams, bye_weeks=bye_weeks)

@main.route('/rankings/new-model')
@login_required
def get_new_model_rankings():
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    return render_template('rankings.html', table_data=_new_model_table_data, table_type='New Model (PPR)',
                           user_rankings=saved, player_details_json='{}',
                           team_schedule_json='{}', teams=[], bye_weeks=[])

@main.route('/save_rankings', methods=['POST'])
@login_required
def save_rankings():
    data = request.get_json()
    ranking_data = data.get('ranking', [])
    ranking_type = data.get('ranking_type', 'Custom')
    name = data.get('name', 'Untitled')

    # Check for duplicate name
    existing = UserRanking.query.filter_by(user_id=current_user.id, name=name).first()
    if existing:
        return jsonify({'error': 'A ranking with that name already exists. Please choose a different name.'}), 400

    # Convert ranking data to JSON format
    ranking_json = json.dumps(ranking_data)

    # Save the ranking to the database
    user_ranking = UserRanking(user_id=current_user.id, name=name, ranking_type=ranking_type, ranking_data=ranking_json)
    db.session.add(user_ranking)
    db.session.commit()

    return jsonify({'message': 'Rankings saved successfully!', 'ranking_id': user_ranking.id})

@main.route('/update_ranking/<int:ranking_id>', methods=['PUT'])
@login_required
def update_ranking(ranking_id):
    ranking = UserRanking.query.get_or_404(ranking_id)
    if ranking.user_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json()
    ranking_data = data.get('ranking', [])
    ranking.ranking_data = json.dumps(ranking_data)
    db.session.commit()
    return jsonify({'message': 'Ranking updated successfully!'})

@main.route('/rankings/saved/<int:ranking_id>')
@login_required
def view_saved_ranking(ranking_id):
    ranking = UserRanking.query.get_or_404(ranking_id)
    if ranking.user_id != current_user.id:
        flash('Access denied.')
        return redirect(url_for('main.rankings'))
    # Parse the saved JSON data back into table format
    rows = json.loads(ranking.ranking_data)
    # Get column headers from the ranking type's original table
    header_map = {'PPR': 'Full_PPR', 'Half PPR': 'Half_PPR', 'Standard': 'Non_PPR'}
    table_name = header_map.get(ranking.ranking_type, 'Full_PPR')
    with engine.connect() as connection:
        df = pd.read_sql(text(f'SELECT * FROM {table_name} LIMIT 1'), con=connection)
    headers = list(df.columns)
    # Convert rows back to list of dicts
    table_data = []
    for row in rows:
        row_dict = {}
        for i, header in enumerate(headers):
            row_dict[header] = row[i] if i < len(row) else ''
        table_data.append(row_dict)
    saved = UserRanking.query.filter_by(user_id=current_user.id).order_by(UserRanking.timestamp.desc()).all()
    player_details = _get_player_details()
    team_schedule = _get_team_schedule()
    teams = sorted(set(str(r.get('Team', '')) for r in table_data if r.get('Team')))
    bye_weeks = sorted(set(int(r['Bye Week']) for r in table_data if r.get('Bye Week') is not None))
    return render_template('rankings.html', table_data=table_data, table_type=ranking.name,
                           user_rankings=saved, saved_ranking_id=ranking.id, saved_ranking_name=ranking.name,
                           player_details_json=json.dumps(player_details),
                           team_schedule_json=json.dumps(team_schedule),
                           teams=teams, bye_weeks=bye_weeks)

@main.route('/user_rankings')
@login_required
def user_rankings():
    # Retrieve all rankings for the current user
    user_rankings = UserRanking.query.filter_by(user_id=current_user.id).all()
    return render_template('user_rankings.html', user_rankings=user_rankings)

@main.route('/delete_ranking/<int:ranking_id>', methods=['DELETE'])
@login_required
def delete_ranking(ranking_id):
    ranking = UserRanking.query.get_or_404(ranking_id)
    if ranking.user_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    db.session.delete(ranking)
    db.session.commit()
    return jsonify({'message': 'Ranking deleted successfully!'})

@main.route('/player_stats')
@login_required
def player_stats():
    name = request.args.get('name', '').strip()
    pos  = request.args.get('pos', '').strip().upper()
    team = request.args.get('team', '').strip().upper()

    if not name:
        return jsonify({})

    # --- Historical stats from nflreadpy (2020–2025) ---
    history = []
    if not _nfl_seasonal.empty:
        player_rows = _nfl_seasonal[_nfl_seasonal['player_name'] == name].sort_values('season')
        if pos == 'QB':
            cols = ['season', 'games', 'completions', 'attempts', 'passing_yards',
                    'passing_tds', 'passing_interceptions', 'rushing_yards', 'rushing_tds', 'fantasy_points_ppr']
        elif pos == 'RB':
            cols = ['season', 'games', 'carries', 'rushing_yards', 'rushing_tds',
                    'receptions', 'targets', 'receiving_yards', 'receiving_tds', 'fantasy_points_ppr']
        else:  # WR / TE
            cols = ['season', 'games', 'receptions', 'targets', 'receiving_yards',
                    'receiving_tds', 'target_share', 'air_yards_share', 'fantasy_points_ppr']

        import math as _m
        available = [c for c in cols if c in player_rows.columns]
        hist = player_rows[available].tail(5).round(1)
        hist = hist.rename(columns={'games': 'GP', 'fantasy_points_ppr': 'fantasy_points'})
        history = [
            {k: (None if isinstance(v, float) and _m.isnan(v) else v) for k, v in row.items()}
            for row in hist.to_dict(orient='records')
        ]

    # --- Rankings info ---
    rank_row = _rankings[_rankings['Name'] == name]
    ranking = {}
    if not rank_row.empty:
        r = rank_row.iloc[0]
        ranking = {
            'Rank': int(r['Rank']),
            'Final PPG': round(float(r['Final PPG']), 2) if pd.notna(r['Final PPG']) else None,
            'ESPN ADP': round(float(r['ESPN ADP']), 1) if pd.notna(r['ESPN ADP']) else None,
            'VBD': round(float(r['VBD']), 2) if pd.notna(r['VBD']) else None,
            'Bye Week': int(r['Bye Week']) if pd.notna(r['Bye Week']) else None,
        }

    # --- Team grade (composite from starter fantasy performance) ---
    team_grade = {}
    if team and team in _composite_grades:
        cg = _composite_grades[team]
        team_grade = {
            'OLine': cg.get('OLine'),
            'QB':    cg.get('QB'),
            'RB':    cg.get('RB'),
            'WR':    cg.get('WR'),
            'TE':    cg.get('TE'),
            'DST':   cg.get('DST'),
        }

    return jsonify({
        'history': history,
        'ranking': ranking,
        'team_grade': team_grade,
    })


@main.route('/mockdraft')
@login_required
def mock_draft():
    return render_template('mockdraft.html')


@main.route('/mockdraft/players')
@login_required
def mockdraft_players():
    import math
    scoring = request.args.get('scoring', 'ppr')
    table_map = {'ppr': 'Full_PPR', 'half_ppr': 'Half_PPR', 'standard': 'Non_PPR'}
    table_name = table_map.get(scoring, 'Full_PPR')
    with engine.connect() as connection:
        df = pd.read_sql(text(f'SELECT * FROM {table_name}'), con=connection)
    # Normalize position strings: 'WR1' -> 'WR', 'RB2' -> 'RB', etc.
    df['Position'] = df['Position'].str.replace(r'\d+$', '', regex=True).str.strip()
    # Exclude K and DEF
    df = df[~df['Position'].isin(['K', 'DEF', 'DST'])]
    # Replace NaN with None so jsonify produces valid JSON (not literal NaN)
    players = [
        {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in row.items()}
        for row in df.to_dict(orient='records')
    ]
    return jsonify(players)


@main.route('/mockdraft/save', methods=['POST'])
@login_required
def mockdraft_save():
    data = request.get_json()
    draft = MockDraft(
        user_id=current_user.id,
        draft_type=data.get('draft_type', 'snake'),
        scoring=data.get('scoring', 'ppr'),
        settings=json.dumps(data.get('settings', {})),
        board=json.dumps(data.get('board', [])),
        user_team=json.dumps(data.get('user_team', [])),
    )
    db.session.add(draft)
    db.session.commit()
    return jsonify({'message': 'Draft saved!', 'id': draft.id})


@main.route('/mockdraft/email', methods=['POST'])
@login_required
def mockdraft_email():
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    data = request.get_json()
    send_full = data.get('send_full', False)
    board = data.get('board', [])
    user_team = data.get('user_team', [])
    scoring = data.get('scoring', 'ppr')
    draft_type = data.get('draft_type', 'snake')
    settings = data.get('settings', {})

    # Build HTML email
    from datetime import date
    subject = f"Darkhorse Mock Draft — {date.today().strftime('%Y-%m-%d')} — {scoring.upper()} {draft_type.capitalize()}"

    if send_full:
        content = _build_board_html(board, settings)
    else:
        content = _build_team_html(user_team, scoring)

    html_body = f"""
    <html><body style="background:#1a2332;color:#f1faee;font-family:Arial,sans-serif;padding:20px;">
    <h2 style="color:#2d8b8b;">Darkhorse Mock Draft Results</h2>
    <p style="color:#a8dadc;">{scoring.upper()} | {draft_type.capitalize()} | {date.today().strftime('%B %d, %Y')}</p>
    {content}
    </body></html>
    """

    try:
        smtp_host = app.config.get('MAIL_SERVER', '')
        smtp_port = int(app.config.get('MAIL_PORT', 587))
        smtp_user = app.config.get('MAIL_USERNAME', '')
        smtp_pass = app.config.get('MAIL_PASSWORD', '')

        if not smtp_host or not smtp_user:
            return jsonify({'message': 'Email sent (email server not configured — draft saved instead).'}), 200

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = smtp_user
        msg['To'] = current_user.email
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, current_user.email, msg.as_string())

        return jsonify({'message': f'Draft emailed to {current_user.email}!'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _build_board_html(board, settings):
    if not board:
        return '<p>No draft data.</p>'
    num_teams = settings.get('num_teams', len(board))
    team_names = [f'Team {i+1}' for i in range(num_teams)]
    html = '<table style="border-collapse:collapse;width:100%;">'
    html += '<tr><th style="padding:6px;border:1px solid #2d8b8b;">Round</th>'
    for t in team_names:
        html += f'<th style="padding:6px;border:1px solid #2d8b8b;color:#a8dadc;">{t}</th>'
    html += '</tr>'
    for round_picks in board:
        html += '<tr>'
        html += f'<td style="padding:6px;border:1px solid #2d8b8b;color:#a8dadc;">{round_picks.get("round","")}</td>'
        for pick in round_picks.get('picks', []):
            html += f'<td style="padding:6px;border:1px solid #2d8b8b;">{pick.get("name","—")} <span style="color:#a8dadc;">({pick.get("position","")})</span></td>'
        html += '</tr>'
    html += '</table>'
    return html


def _build_team_html(user_team, scoring):
    if not user_team:
        return '<p>No picks.</p>'
    html = '<table style="border-collapse:collapse;width:60%;">'
    html += '<tr><th style="padding:6px;border:1px solid #2d8b8b;">Round</th><th style="padding:6px;border:1px solid #2d8b8b;">Player</th><th style="padding:6px;border:1px solid #2d8b8b;">Position</th><th style="padding:6px;border:1px solid #2d8b8b;">Team</th></tr>'
    for pick in user_team:
        html += f'<tr><td style="padding:6px;border:1px solid #2d8b8b;">{pick.get("round","")}</td><td style="padding:6px;border:1px solid #2d8b8b;">{pick.get("name","")}</td><td style="padding:6px;border:1px solid #2d8b8b;color:#a8dadc;">{pick.get("position","")}</td><td style="padding:6px;border:1px solid #2d8b8b;">{pick.get("nfl_team","")}</td></tr>'
    html += '</table>'
    return html


@main.route('/my_drafts')
@login_required
def my_drafts():
    drafts = MockDraft.query.filter_by(user_id=current_user.id).order_by(MockDraft.created_at.desc()).all()
    draft_list = []
    for d in drafts:
        settings = json.loads(d.settings)
        draft_list.append({
            'id': d.id,
            'draft_type': d.draft_type,
            'scoring': d.scoring,
            'created_at': d.created_at.strftime('%Y-%m-%d %H:%M'),
            'num_teams': settings.get('num_teams', '?'),
        })
    return render_template('my_drafts.html', drafts=draft_list)


@main.route('/my_drafts/<int:draft_id>')
@login_required
def view_draft(draft_id):
    draft = MockDraft.query.get_or_404(draft_id)
    if draft.user_id != current_user.id:
        flash('Access denied.')
        return redirect(url_for('main.my_drafts'))
    return render_template('view_draft.html',
        draft=draft,
        board=json.loads(draft.board),
        user_team=json.loads(draft.user_team),
        settings=json.loads(draft.settings),
    )


@main.route('/my_drafts/<int:draft_id>/delete', methods=['DELETE'])
@login_required
def delete_draft(draft_id):
    draft = MockDraft.query.get_or_404(draft_id)
    if draft.user_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403
    db.session.delete(draft)
    db.session.commit()
    return jsonify({'message': 'Draft deleted.'})


@main.route('/rosters')
@login_required
def rosters():
    data_path = Path(app.root_path) / 'data' / 'teamsPastRoster.pkl'

    if not data_path.exists():
        flash('Roster file not found. Please generate teamsPastRoster.pkl first.')
        return redirect(url_for('main.home'))

    df = pd.read_pickle(data_path)

    return render_template(
        'rosters.html',
        table_data=df.to_dict(orient='records'),
        columns=df.columns.tolist(),
        roster_stats_json=json.dumps(_roster_stats),
        fp_thresholds_json=json.dumps(_fp_thresholds),
    )

def fetch_player_data():
    url = 'https://www.footballguys.com/adp'
    response = requests.get(url)
    player_data = []
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')
        for row in rows:
            name_td = row.find('td', class_='name sticky-col text-start text-nowrap')
            if name_td:
                name_a = name_td.find('a')
                if name_a:
                    player_name = name_a.get_text().strip()
                    tds = row.find_all('td')
                    if len(tds) >= 15:
                        adp_value = tds[14].get_text().strip()
                        if adp_value != '-':
                            player_data.append((player_name, adp_value))
        player_data_sorted = sorted(player_data, key=lambda x: int(x[1]) if x[1].isdigit() else float('inf'))
        return player_data_sorted
    else:
        return []
